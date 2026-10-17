"""P2-D4: offline provenance-gated duplicate heading audit and versioned EPUB.

The pinned upstream's make_chapter_xhtml() prepends an unstyled <h1>title</h1>
before the extracted source body. Some source bodies already begin with the
same H1. Remove ONLY the provable synthetic duplicate, never source markup.

Requires a frozen 100%-complete local chapter queue and the original EPUB hash
recorded in fullbook_QA_report.json. Defaults to audit-only and never modifies
the previously delivered EPUB/PDF or source chapter checkpoints. No network,
cookies, source book text, or real chapter titles are emitted in the report.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

from tools.book_assembly import _read_validated_sources
from tools.chapter_worker import file_sha256

# The FIRST <h1> must have exactly the upstream-generated plain form, without
# attributes/nested markup. The second may be an original source H1.
LEADING_PAIR = re.compile(
    r"(<body\b[^>]*>\s*)(?P<generated><h1>[^<]*</h1>)(?P<gap>\s*)"
    r"(?P<original><h1\b[^>]*>.*?</h1>)",
    re.I | re.S,
)
# In some front matter the original H1 is wrapped in a dedicated source
# copyright-title div, so the immediate H1/H1 rule alone misses it.
COPYRIGHT_PAIR = re.compile(
    r'(<body\b[^>]*>\s*)(?P<generated><h1>[^<]*</h1>)(?P<gap>\s*)'
    r'(?P<original><div class="newCopyRightTitleWrapper">\s*'
    r'<h1 class="newCopyRightTitle">[^<]*</h1>\s*</div>)',
    re.I | re.S,
)
# P3-I: source reader section headings can be genuine <h2 class="secondTitle">.
# The pinned exporter adds a plain H1 immediately before this source element.
# Only enable this strictly attributed pattern for the independent v4 candidate.
SECOND_TITLE_PAIR = re.compile(
    r'(<body\b[^>]*>\s*)(?P<generated><h1>[^<]*</h1>)(?P<gap>\s*)'
    r'(?P<original><h2 class="secondTitle" id="[^"]+">[^<]*</h2>)',
    re.I | re.S,
)
# P4-F: this book has an original source H2 of a different exact class.
# This rule is isolated in v5 to preserve earlier version policies.
CITY_SECTION_PAIR = re.compile(
    r'(<body\b[^>]*>\s*)(?P<generated><h1>[^<]*</h1>)(?P<gap>\s*)'
    r'(?P<original><h2 class="txtheading-1-15" id="[^"]+">[^<]*</h2>)',
    re.I | re.S,
)
HEADING_TEXT = re.compile(r"<[^>]*>", re.S)


def _heading_text(markup: str) -> str:
    return "".join(html.unescape(HEADING_TEXT.sub("", markup)).split())


def dedupe_one_chapter(xhtml: str, *, catalog_title: str,
                       include_source_h2: bool = False,
                       include_city_h2: bool = False) -> tuple[str, bool]:
    match = LEADING_PAIR.search(xhtml) or COPYRIGHT_PAIR.search(xhtml)
    if match is None and include_source_h2:
        match = SECOND_TITLE_PAIR.search(xhtml)
    if match is None and include_city_h2:
        match = CITY_SECTION_PAIR.search(xhtml)
    if not match:
        return xhtml, False
    generated = _heading_text(match.group("generated"))
    original = _heading_text(match.group("original"))
    expected = "".join(catalog_title.split())
    if not generated or generated != original or generated != expected:
        return xhtml, False
    # The leading H1 is precisely the generated header of the pinned exporter.
    # We remove only its bytes; source H1 and all images/text are untouched.
    start, end = match.span("generated")
    transformed = xhtml[:start] + xhtml[end:]
    # Reconstruction invariant protects against unexpected parser behavior.
    if transformed[:start] + xhtml[start:end] + transformed[start:] != xhtml:
        raise ValueError("HEADING_RECONSTRUCTION_FAILED")
    return transformed, True


def _source_qa(book_dir: Path, source: Path, inspector):
    qa = book_dir / "final" / "fullbook_QA_report.json"
    if not qa.is_file():
        raise FileNotFoundError("ORIGINAL_QA_REPORT_MISSING")
    parsed = json.loads(qa.read_text(encoding="utf-8"))
    original = parsed.get("artifacts", {}).get("book.epub", {}).get("sha256")
    if not original or file_sha256(source) != original:
        raise ValueError("ORIGINAL_EPUB_SHA_MISMATCH")
    status = inspector(source, expected=parsed["epub_chapters"])
    if status["status"] != "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED":
        raise ValueError("ORIGINAL_EPUB_STRUCTURE_INVALID")
    return original, parsed["epub_chapters"], status


def audit_and_build(
    *,
    book_dir: Path,
    inspector,
    build_versioned: bool = False,
    target_version: str = "v2-headings",
) -> dict:
    book_dir = book_dir.resolve()
    source = book_dir / "final" / "book.epub"
    if not source.is_file():
        raise FileNotFoundError("ORIGINAL_EPUB_MISSING")
    entries, catalog = _read_validated_sources(
        book_dir / "chapters.sqlite",
        book_dir / "catalog.json",
        inspector,
    )
    original_sha, expected, old_check = _source_qa(book_dir, source, inspector)
    if len(entries) != expected:
        raise ValueError("CHAPTER_COVERAGE_MISMATCH")
    if target_version not in {"v2-headings", "v3-headings", "v4-headings", "v5-headings"}:
        raise ValueError("UNKNOWN_VERSIONED_OUTPUT")
    new_epub = book_dir / "final" / target_version / "book.epub"
    changed_ordinals: list[int] = []
    affected = {}
    with zipfile.ZipFile(source) as z:
        if z.testzip() is not None:
            raise ValueError("SOURCE_ZIP_CRC_FAILED")
        known_paths = set(z.namelist())
        for row in entries:
            n = row["ordinal"]
            chapter_path = f"OEBPS/text/chapter_{n:04d}.xhtml"
            if chapter_path not in known_paths:
                raise ValueError("SOURCE_CHAPTER_PATH_MISSING")
            xhtml = z.read(chapter_path).decode("utf-8-sig")
            new, changed = dedupe_one_chapter(
                xhtml, catalog_title=row["chapter_title"],
                include_source_h2=(target_version in {"v4-headings", "v5-headings"}),
                include_city_h2=(target_version == "v5-headings"),
            )
            if changed:
                changed_ordinals.append(n)
                affected[chapter_path] = new.encode("utf-8")
    result = {
        "status": "H1_AUDIT_READY" if not build_versioned
                  else "H1_VERSIONED_CANDIDATE_READY_FIDELITY_UNVERIFIED",
        "source_chapter_count": expected,
        "source_sha256": original_sha,
        "source_epub_bytes": source.stat().st_size,
        "deduplicated_count": len(changed_ordinals),
        "deduplicated_ordinals": changed_ordinals,
        "criterion": (
            "At the start of body, a generated plain <h1>catalog title</h1> "
            "precedes an identical source title (H1, wrapped copyright H1, or "
            "v4 secondTitle H2 or v5 txtheading-1-15 H2); "
            "matches frozen catalog."
        ),
        "original_unchanged": True,
        "note": (
            "Source EPUB and chapter checkpoints remain untouched; "
            "visual comparison to the original reader is still required."
        ),
    }
    if not build_versioned:
        return result
    if not changed_ordinals:
        raise ValueError("NO_CONFIRMED_SYNTHETIC_DUPLICATES")
    if new_epub.exists():
        raise FileExistsError("VERSIONED_OUTPUT_ALREADY_EXISTS")
    new_epub.parent.mkdir(parents=True, exist_ok=True)
    stage = new_epub.with_suffix(".epub.partial")
    if stage.exists():
        raise FileExistsError("PARTIAL_OUTPUT_ALREADY_EXISTS")
    try:
        with zipfile.ZipFile(source, "r") as old, zipfile.ZipFile(stage, "w") as output:
            # Preserve ZIP metadata/entry bytes whenever possible.
            for info in old.infolist():
                output.writestr(info, affected.get(info.filename, old.read(info.filename)))
        with zipfile.ZipFile(source) as old, zipfile.ZipFile(stage) as new:
            if new.testzip() is not None or set(old.namelist()) != set(new.namelist()):
                raise ValueError("VERSIONED_ZIP_INCOMPLETE")
            for info in old.infolist():
                if info.filename in affected:
                    continue
                if old.read(info.filename) != new.read(info.filename):
                    raise ValueError("UNEXPECTED_UNMODIFIED_CONTENT_DIFF")
        check = inspector(stage, expected=expected)
        if check["status"] != "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED":
            raise ValueError("VERSIONED_EPUB_STRUCTURE_INVALID")
        if (check["manifest_images"] != old_check["manifest_images"]
                or check["image_references"] != old_check["image_references"]
                or check["broken_images"] or check["remote_images"]):
            raise ValueError("EPUB_IMAGE_INTEGRITY_DIFF")
        os.replace(stage, new_epub)
    finally:
        stage.unlink(missing_ok=True)
    result.update({
        "epub_path": str(new_epub),
        "epub_sha256": file_sha256(new_epub),
        "epub_bytes": new_epub.stat().st_size,
        "image_manifest_unchanged": True,
        "image_references_unchanged": True,
        "spine_chapters": check["spine_chapters"],
        "new_epub_text_characters": check["text_characters"],
    })
    report = new_epub.parent / "headings_qa.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description="Offline, provenance-gated heading QA")
    parser.add_argument("--book-dir", type=Path, required=True)
    parser.add_argument("--build-versioned", action="store_true",
                        help="Write a versioned EPUB while preserving the original")
    parser.add_argument("--output-version", choices=["v2-headings", "v3-headings", "v4-headings", "v5-headings"],
                        default="v2-headings")
    args = parser.parse_args()
    import wereadlab
    outcome = audit_and_build(
        book_dir=args.book_dir, inspector=wereadlab.inspect_epub,
        build_versioned=args.build_versioned,
        target_version=args.output_version,
    )
    print(json.dumps(outcome, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
