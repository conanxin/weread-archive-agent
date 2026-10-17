"""Offline pre-assembly warning gate for personal EPUB chapter checkpoints.

Finds image-only/short-content suspects and large image assets not referenced by
the XHTML body. Never reads cookies, calls APIs, rewrites EPUBs, or reports book
text/title/path/asset names. Warnings need source review, not automatic deletion.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from html.parser import HTMLParser
import hashlib
import html
import json
from pathlib import Path
import posixpath
import re
import sqlite3
import unicodedata
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from tools.book_assembly import _find_package


class BodyScanner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body = 0
        self.skip = 0
        self.text_parts: list[str] = []
        self.image_refs: list[str] = []

    def handle_starttag(self, tag, attributes):
        tag = tag.lower()
        attrs = dict(attributes)
        if tag == "body":
            self.body += 1
        if tag in {"script", "style"}:
            self.skip += 1
        if self.body and not self.skip and tag in {"img", "image"}:
            self.image_refs.append(
                attrs.get("src") or attrs.get("href") or attrs.get("xlink:href") or ""
            )

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "body":
            self.body = max(0, self.body - 1)
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, text):
        if self.body and not self.skip:
            self.text_parts.append(text)


def image_dimensions(raw: bytes) -> tuple[int, int] | None:
    """PNG/JPEG dimensions without non-stdlib runtime dependencies."""
    if raw.startswith(b"\x89PNG\r\n\x1a\n") and len(raw) >= 24:
        return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")
    if not raw.startswith(b"\xff\xd8"):
        return None
    pos = 2
    while pos + 9 < len(raw):
        if raw[pos] != 0xFF:
            pos += 1
            continue
        while pos < len(raw) and raw[pos] == 0xFF:
            pos += 1
        if pos >= len(raw):
            break
        marker = raw[pos]
        pos += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if pos + 2 > len(raw):
            break
        length = int.from_bytes(raw[pos:pos+2], "big")
        if length < 2 or pos + length > len(raw):
            break
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and length >= 7:
            return int.from_bytes(raw[pos+5:pos+7], "big"), int.from_bytes(raw[pos+3:pos+5], "big")
        pos += length
    return None


def resolve_image(document: str, ref: str) -> str | None:
    part = urlsplit(html.unescape(ref))
    if not part.path or part.scheme or part.netloc or ref.startswith(("//", "#")):
        return None
    return posixpath.normpath(
        posixpath.join(posixpath.dirname(document), unquote(part.path))
    )


def audit_epub(path: Path, *, ordinal: int, provider_words: int,
               min_ratio: float = 0.6, large_pixels: int = 250_000) -> dict:
    problems = []
    with ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError("SOURCE_EPUB_ZIP_CRC_FAILED")
        names = set(z.namelist())
        package, manifest, spine = _find_package(z)
        if len(spine) != 1 or spine[0] not in manifest:
            raise ValueError("SOURCE_EPUB_SPINE_INVALID")
        doc = posixpath.normpath(posixpath.join(
            posixpath.dirname(package), manifest[spine[0]]["href"]
        ))
        if doc not in names:
            raise ValueError("SOURCE_EPUB_XHTML_NOT_FOUND")
        scan = BodyScanner()
        scan.feed(z.read(doc).decode("utf-8-sig"))
        scan.close()
        visible = len(re.sub(
            r"\s+", "", unicodedata.normalize("NFC", "".join(scan.text_parts))
        ))
        if provider_words >= 50 and visible / provider_words < min_ratio:
            problems.append("TEXT_BELOW_PROVIDER_ESTIMATE")
        referenced = {resolve_image(doc, s) for s in scan.image_refs}
        linked_hashes = {hashlib.sha256(z.read(name)).digest()
                         for name in referenced if name in names}
        linked_large = any(image_dimensions(z.read(name)) and
                           image_dimensions(z.read(name))[0] * image_dimensions(z.read(name))[1] >= large_pixels
                           for name in referenced if name in names)
        large_unreferenced = 0
        for name in names:
            if not name.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            raw = z.read(name)
            dims = image_dimensions(raw)
            if not dims or dims[0] * dims[1] < large_pixels:
                continue
            # Repackagers often duplicate referenced images under new names.
            if name in referenced or hashlib.sha256(raw).digest() in linked_hashes:
                continue
            # Once a large actual illustration is linked, unused PNGs are
            # often the exporter's legacy placeholders rather than lost maps.
            if name.lower().endswith(".png") and linked_large:
                continue
            large_unreferenced += 1
        if large_unreferenced:
            problems.append("UNREFERENCED_LARGE_IMAGE")
    return {
        "ordinal": ordinal,
        "estimated_words": provider_words,
        "visible_characters": visible,
        "image_refs_in_body": len(scan.image_refs),
        "large_unreferenced_images": large_unreferenced,
        "risk_codes": sorted(set(problems)),
    }


def audit_book(book_dir: Path) -> dict:
    """Read-only, partial-queue friendly; fail closed on invalid SHA/snapshot."""
    book_dir = Path(book_dir)
    catalog = book_dir / "catalog.json"
    database = book_dir / "chapters.sqlite"
    if not catalog.is_file() or not database.is_file():
        raise FileNotFoundError("FROZEN_BOOK_OR_QUEUE_NOT_FOUND")
    payload = catalog.read_bytes()
    contents = json.loads(payload.decode("utf-8"))
    selected = [r for r in contents["chapters"] if r["selected_for_export"]]
    with closing(sqlite3.connect(database)) as conn:
        pinned = conn.execute(
            "SELECT value FROM queue_info WHERE key='catalog_sha256'"
        ).fetchone()
        if not pinned or pinned[0] != hashlib.sha256(payload).hexdigest():
            raise ValueError("CATALOG_SNAPSHOT_HASH_MISMATCH")
        rows = conn.execute(
            "SELECT ordinal,state,artifact_path,artifact_sha256 FROM chapters ORDER BY ordinal"
        ).fetchall()
    if not selected or len(rows) != len(selected):
        raise ValueError("CHAPTER_CATALOG_QUEUE_COVERAGE_MISMATCH")
    warnings = []
    checked = 0
    incomplete = 0
    for pos, (ordinal, state, artifact, expected_sha) in enumerate(rows):
        if ordinal != pos + 1:
            raise ValueError("QUEUE_CHAPTER_ORDER_MISMATCH")
        if state != "COMPLETE":
            incomplete += 1
            continue
        source = (book_dir / (artifact or "")).resolve()
        if not artifact or not source.is_relative_to(book_dir.resolve()) or not source.is_file():
            raise ValueError("CHAPTER_ARTIFACT_PATH_INVALID")
        if not expected_sha or hashlib.sha256(source.read_bytes()).hexdigest() != expected_sha:
            raise ValueError("CHAPTER_ARTIFACT_SHA_MISMATCH")
        report = audit_epub(
            source, ordinal=ordinal,
            provider_words=int(selected[pos].get("word_count") or 0)
        )
        checked += 1
        if report["risk_codes"]:
            warnings.append(report)
    counter = Counter(code for entry in warnings for code in entry["risk_codes"])
    return {
        "status": ("PREASSEMBLY_PARTIAL_QUEUE" if incomplete
                   else "PREASSEMBLY_REVIEW_REQUIRED" if warnings
                   else "PREASSEMBLY_NO_DETECTED_RISKS"),
        "chapters_selected": len(selected),
        "chapters_checked": checked,
        "chapters_not_complete": incomplete,
        "risk_chapters_count": len(warnings),
        "risk_codes": dict(sorted(counter.items())),
        "risk_examples": warnings[:30],
        "diagnostic_note": ("Provider wordCount is an estimate; a low ratio or an unreferenced "
                            "large image is a review trigger, not proof of missing publisher content."),
        "source_reader_visual_fidelity": "UNVERIFIED",
        "human_acceptance": "PENDING",
        "full_book_confirmed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline pre-assembly chapter risk audit")
    parser.add_argument("--book-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = audit_book(args.book_dir)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        result = {
            "status": "PREASSEMBLY_EVIDENCE_INVALID",
            "error_class": type(exc).__name__,
            "full_book_confirmed": False,
        }
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data, encoding="utf-8")
    print(data, end="")
    return 1 if result["status"] == "PREASSEMBLY_EVIDENCE_INVALID" else 0


if __name__ == "__main__":
    raise SystemExit(main())
