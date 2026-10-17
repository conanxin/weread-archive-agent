"""Offline comparison: frozen source chapter EPUBs -> assembled EPUB.

Reads only catalog.json, the verified SQLite queue and local EPUBs. No network,
browser session, credentials or book-specific IDs. This proves cached content
parity, NOT live-reader typography, publisher-master parity or human acceptance.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import posixpath
import re
import unicodedata
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile

from tools.book_assembly import _find_package, _read_validated_sources
from tools.heading_fidelity import dedupe_one_chapter

PASS = "P3H_CACHED_SOURCE_PARITY_PASS"
INCOMPLETE = "P3H_CACHED_SOURCE_PARITY_INCOMPLETE"


class BodyReader(HTMLParser):
    """Observe displayed body text and image references without changing markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body_depth = 0
        self.skip_depth = 0
        self.chunks: list[str] = []
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag, attributes):
        tag = tag.lower()
        if tag == "body":
            self.body_depth += 1
        if tag in {"script", "style"}:
            self.skip_depth += 1
        if self.body_depth and tag in {"img", "image"}:
            attrs = dict(attributes)
            self.images.append({
                "src": attrs.get("src") or attrs.get("href")
                       or attrs.get("xlink:href") or "",
                "alt": attrs.get("alt") or "",
            })

    def handle_endtag(self, tag):
        if tag.lower() == "body":
            self.body_depth = max(0, self.body_depth - 1)
        if tag.lower() in {"script", "style"}:
            self.skip_depth = max(0, self.skip_depth - 1)

    def handle_data(self, value):
        if self.body_depth and not self.skip_depth:
            self.chunks.append(value)


def visible_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value))


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def local_member(document: str, reference: str) -> str | None:
    if not reference or reference.startswith(("//", "#")):
        return None
    ref = urlsplit(reference)
    if ref.scheme or ref.netloc or not ref.path:
        return None
    return posixpath.normpath(
        posixpath.join(posixpath.dirname(document), unquote(ref.path))
    )


def all_manifest_images(z: ZipFile) -> tuple[list[str], list[str]]:
    """Return image SHA multiset and unresolved manifest member paths."""
    opf, manifest, _ = _find_package(z)
    names = set(z.namelist())
    hashes, missing = [], []
    for item in manifest.values():
        if not item.get("media-type", "").startswith("image/"):
            continue
        member = posixpath.normpath(posixpath.join(
            posixpath.dirname(opf), unquote(item.get("href", ""))
        ))
        if member in names:
            hashes.append(digest(z.read(member)))
        else:
            missing.append(member)
    return hashes, missing


def read_body(markup: str) -> BodyReader:
    parsed = BodyReader()
    parsed.feed(markup)
    parsed.close()
    return parsed


def verify_cached_source(
    book_dir: Path, compiled_epub: Path, *, inspector=None, heading_policy: str = "v3"
) -> dict:
    """Fail closed, return aggregate evidence and issue codes, no original prose."""
    if heading_policy not in {"v3", "v4", "v5", "v6", "v7"}:
        raise ValueError("UNKNOWN_HEADING_POLICY")
    if inspector is None:
        from wereadlab import inspect_epub
        inspector = inspect_epub
    book_dir = Path(book_dir)
    compiled_epub = Path(compiled_epub)
    chapters, _catalog = _read_validated_sources(
        book_dir / "chapters.sqlite", book_dir / "catalog.json", inspector
    )
    candidate = inspector(compiled_epub, expected=len(chapters))
    issues: list[dict] = []
    def flag(kind: str, ordinal: int | None = None):
        issue = {"kind": kind}
        if ordinal is not None:
            issue["ordinal"] = ordinal
        issues.append(issue)

    if candidate["status"] != "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED":
        flag("COMPILED_EPUB_STRUCTURE_INVALID")
    if candidate.get("spine_chapters") != len(chapters):
        flag("CHAPTER_COVERAGE_MISMATCH")
    body_count = used_refs = deduped = compared = 0
    source_hashes: list[str] = []
    compiled_hashes: list[str] = []
    with ZipFile(compiled_epub) as book:
        names = set(book.namelist())
        if book.testzip() is not None or len(names) != len(book.namelist()):
            flag("COMPILED_ZIP_INVALID")
        opf, manifest, spine = _find_package(book)
        actual_spine = [
            posixpath.normpath(posixpath.join(posixpath.dirname(opf), manifest[item]["href"]))
            for item in spine if item in manifest
        ]
        expected_spine = [
            f"OEBPS/text/chapter_{row['ordinal']:04d}.xhtml" for row in chapters
        ]
        if actual_spine != expected_spine:
            flag("SPINE_ORDER_MISMATCH")
        compiled_hashes, broken = all_manifest_images(book)
        if broken:
            flag("COMPILED_IMAGE_MANIFEST_MISSING")
        for row in chapters:
            ordinal = row["ordinal"]
            chapter_name = f"OEBPS/text/chapter_{ordinal:04d}.xhtml"
            if chapter_name not in names:
                flag("COMPILED_CHAPTER_MISSING", ordinal)
                continue
            with ZipFile(row["file"]) as source:
                src_opf, src_manifest, src_spine = _find_package(source)
                if len(src_spine) != 1:
                    flag("SOURCE_SPINE_INVALID", ordinal)
                    continue
                item = src_manifest[src_spine[0]]
                src_name = posixpath.normpath(posixpath.join(
                    posixpath.dirname(src_opf), item["href"]
                ))
                src_data = source.read(src_name).decode("utf-8-sig")
                expected_data, changed = dedupe_one_chapter(
                    src_data, catalog_title=row["chapter_title"],
                    include_source_h2=(heading_policy in {"v4", "v5", "v6", "v7"}),
                    include_city_h2=(heading_policy in {"v5", "v6", "v7"}),
                    include_dash_one_h2=(heading_policy in {"v6", "v7"}),
                    include_no_id_h2=(heading_policy == "v7")
                )
                deduped += int(changed)
                dest_data = book.read(chapter_name).decode("utf-8-sig")
                first, second = read_body(expected_data), read_body(dest_data)
                first_text, second_text = (
                    visible_text("".join(first.chunks)),
                    visible_text("".join(second.chunks)),
                )
                if first_text != second_text:
                    flag("BODY_TEXT_MISMATCH", ordinal)
                else:
                    body_count += len(first_text)
                    compared += 1
                if len(first.images) != len(second.images):
                    flag("IMAGE_REFERENCE_COUNT_MISMATCH", ordinal)
                for ref_a, ref_b in zip(first.images, second.images):
                    used_refs += 1
                    if ref_a["alt"] != ref_b["alt"]:
                        flag("IMAGE_ALT_MISMATCH", ordinal)
                    origin = local_member(src_name, ref_a["src"])
                    target = local_member(chapter_name, ref_b["src"])
                    if not origin or not target or origin not in source.namelist() or target not in names:
                        flag("IMAGE_REFERENCE_UNRESOLVED", ordinal)
                    elif digest(source.read(origin)) != digest(book.read(target)):
                        flag("IMAGE_CONTENT_MISMATCH", ordinal)
                hashes, missing = all_manifest_images(source)
                source_hashes.extend(hashes)
                if missing:
                    flag("SOURCE_IMAGE_MANIFEST_MISSING", ordinal)
        if Counter(source_hashes) != Counter(compiled_hashes):
            flag("IMAGE_MANIFEST_HASH_MULTISET_MISMATCH")

    counts = Counter(x["kind"] for x in issues)
    return {
        "status": PASS if not issues else INCOMPLETE,
        "heading_policy": heading_policy,
        "chapters_expected": len(chapters),
        "chapters_text_exact": compared,
        "normalized_body_characters_matched": body_count,
        "source_proven_generated_h1_removed": deduped,
        "image_reference_pairs_checked": used_refs,
        "source_manifest_image_entries": len(source_hashes),
        "compiled_manifest_image_entries": len(compiled_hashes),
        "unique_source_image_hashes": len(set(source_hashes)),
        "issue_count": len(issues),
        "issue_codes": dict(sorted(counts.items())),
        "issue_examples": issues[:30],
        "source_scope": "FROZEN_LOCAL_CHAPTER_EPUBS_ONLY",
        "source_reader_visual_fidelity": "UNVERIFIED",
        "human_acceptance": "PENDING",
        "full_book_confirmed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline cached source EPUB parity checker")
    parser.add_argument("--book-dir", type=Path, required=True)
    parser.add_argument("--compiled", type=Path, required=True)
    parser.add_argument("--heading-policy", choices=["v3", "v4", "v5", "v6", "v7"], default="v3",
                        help="v4 secondTitle, v5 txtheading-1-15, v6 secondTitle-1 source H2")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        receipt = verify_cached_source(args.book_dir, args.compiled,
                                       heading_policy=args.heading_policy)
    except (OSError, ValueError, KeyError, IndexError) as exc:
        receipt = {
            "status": INCOMPLETE,
            "issue_count": 1,
            "issue_codes": {"SOURCE_OR_EPUB_EVIDENCE_INVALID": 1},
            "error_class": type(exc).__name__,
            "full_book_confirmed": False,
        }
    result = json.dumps(receipt, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding="utf-8")
    print(result, end="")
    return 0 if receipt["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
