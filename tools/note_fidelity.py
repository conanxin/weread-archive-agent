"""P3-J: offline note text and anchor fidelity for private EPUB workflows.

Compare raw checkpoint note-image alts to the repaired compiled note spans, with
strict chapter queue/SHA checks. No account session or network access; report
only aggregate counts and anonymous chapter ordinal errors. Reader popups and
human visual acceptance are separate evidence gates.
"""
from __future__ import annotations

import argparse
from collections import Counter
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import posixpath
import unicodedata
from urllib.parse import urlsplit
from zipfile import ZipFile

from tools.book_assembly import _find_package, _read_validated_sources
from tools.heading_fidelity import dedupe_one_chapter

PASS = "P3J_NOTE_TEXT_ANCHOR_PASS"
INCOMPLETE = "P3J_NOTE_TEXT_ANCHOR_INCOMPLETE"
MARKER = "|SOURCE_NOTE|"
BLOCK_TAGS = {"p", "div", "blockquote", "li", "h1", "h2", "h3", "h4",
              "h5", "h6", "figure", "figcaption", "section", "aside"}


def normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFC", text).split())


FOLIO_MAX_DIGITS = 6
FOLIO_VALUE_SLACK = 32
FOLIO_CENTER_TOLERANCE = 0.05
FOLIO_BOTTOM_FRACTION = 0.90


def _standalone_digits(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(stripped) and stripped.isdigit() and len(stripped) <= FOLIO_MAX_DIGITS


def page_number_block_indices(blocks, *, width, height, page_count) -> list[int]:
    """Return the indices of the page-number folio blocks of one page.

    A folio is a standalone numeric block that is horizontally centred on the
    real page width, sits in the bottom band of the real page height, starts
    below every other text block of that page and carries a plausible page
    number. Every threshold is a fraction of the real page box, so a PDF of
    another size is judged by its own geometry instead of a fixed coordinate.
    """
    if width <= 0 or height <= 0:
        raise ValueError("INVALID_PAGE_GEOMETRY")
    if page_count <= 0:
        raise ValueError("INVALID_PAGE_COUNT")
    candidates = []
    for index, block in enumerate(blocks):
        if not _standalone_digits(block[4]):
            continue
        x0, y0, x1, y1 = block[0], block[1], block[2], block[3]
        if abs((x0 + x1) / 2.0 - width / 2.0) > width * FOLIO_CENTER_TOLERANCE:
            continue
        if y0 < height * FOLIO_BOTTOM_FRACTION:
            continue
        value = int(block[4].strip())
        if not 1 <= value <= page_count + FOLIO_VALUE_SLACK:
            continue
        candidates.append(index)
    if not candidates:
        return []
    others = [block for index, block in enumerate(blocks)
              if index not in set(candidates) and (block[4] or "").strip()]
    if others:
        lowest = max(block[3] for block in others)
        candidates = [index for index in candidates if blocks[index][1] >= lowest]
    if not candidates:
        return []
    # Only the single lowest candidate is a folio; a second number on the same
    # baseline is body content and must survive.
    lowest = max(candidates, key=lambda index: (blocks[index][1], index))
    return [lowest]


def pdf_text_without_page_numbers(pages) -> tuple[str, int]:
    """Concatenate PDF text with the page-number folios removed.

    A folio is drawn at the bottom of its page but emitted first in the content
    stream, so it lands inside any annotation that spans a page break. Removing
    only these blocks keeps the surrounding prose, years, dates and isolated
    body numbers untouched.

    Returns the raw text and how many folio blocks were removed.
    """
    pages = list(pages)
    total = len(pages)
    parts: list[str] = []
    removed = 0
    for page in pages:
        raw = page.get_text("blocks")
        blocks = [(b[0], b[1], b[2], b[3], b[4] or "") for b in raw]
        skip = set(page_number_block_indices(
            blocks, width=page.rect.width, height=page.rect.height,
            page_count=total))
        removed += len(skip)
        for index, block in enumerate(raw):
            if index in skip:
                continue
            parts.append(block[4] or "")
    return "".join(parts), removed


def pdf_content_text(pdf_path) -> tuple[str, int]:
    """Normalized PDF content text plus the count of removed folio blocks."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PYMUPDF_REQUIRED_FOR_EXPLICIT_PDF_CHECK") from exc
    with fitz.open(Path(pdf_path)) as doc:
        raw, removed = pdf_text_without_page_numbers(doc)
    return normalize(raw), removed


def pdf_note_multiplicity(note_labels: list[str], pdf_text: str) -> dict:
    """Count full-label text occurrences, including duplicate note content.

    This is global PDF text evidence, not per-page position or visual fidelity.
    """
    expected = Counter(normalize(label) for label in note_labels)
    extracted = normalize(pdf_text)
    found = {label: extracted.count(label) for label in expected if label}
    matched = sum(min(number, found.get(label, 0)) for label, number in expected.items())
    excess = sum(max(0, found.get(label, 0) - number) for label, number in expected.items())
    missing = sum(max(0, number - found.get(label, 0)) for label, number in expected.items())
    return {
        "status": ("PDF_NOTE_OCCURRENCE_MULTIPLICITY_PASS"
                   if not missing and not excess else "PDF_NOTE_OCCURRENCE_MULTIPLICITY_INCOMPLETE"),
        "expected": sum(expected.values()),
        "matched": matched,
        "missing": missing,
        "extra": excess,
    }


class NoteBody(HTMLParser):
    """Extract normalized body text, note anchors, and source/destination labels."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.body = 0
        self.hidden = 0
        self.note_depth = 0
        self.note_buffer: list[str] = []
        self.fragments: list[str] = []
        self.notes: list[str] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        tag = tag.lower()
        if tag == "body":
            self.body += 1
        if tag in {"script", "style"}:
            self.hidden += 1
        if not self.body or self.hidden:
            return
        if tag in BLOCK_TAGS:
            self.fragments.append("|BEGIN:" + tag + "|")
        if tag == "img":
            reference = values.get("src") or ""
            parsed = urlsplit(reference.replace("\\", "/"))
            if (not parsed.scheme and (parsed.path.lower() == "images/note.png"
                                      or parsed.path.lower().endswith("/images/note.png"))):
                self.fragments.append(MARKER)
                alt = (values.get("alt") or "").strip()
                self.notes.append(
                    "〔注：" + alt + "〕"
                    if alt and alt.lower() not in {"image", "note", "icon"}
                    else "〔注〕"
                )
        elif tag == "span" and "weread-note-marker" in values.get("class", "").split():
            self.fragments.append(MARKER)
            self.note_depth += 1
            self.note_buffer = []

    def handle_data(self, data):
        if self.note_depth:
            self.note_buffer.append(data)
        elif self.body and not self.hidden:
            self.fragments.append(data)

    def handle_endtag(self, tag):
        if tag.lower() in BLOCK_TAGS and self.body and not self.hidden and not self.note_depth:
            self.fragments.append("|END:" + tag.lower() + "|")
        if tag.lower() == "span" and self.note_depth:
            self.note_depth -= 1
            if self.note_depth == 0:
                self.notes.append("".join(self.note_buffer))
                self.note_buffer = []
        if tag.lower() == "body":
            self.body = max(0, self.body - 1)
        if tag.lower() in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    @property
    def anchor_text(self):
        return normalize("".join(self.fragments))


def _spine_xhtml(z: ZipFile) -> str:
    opf, manifest, spine = _find_package(z)
    if len(spine) != 1 or spine[0] not in manifest:
        raise ValueError("RAW_PARTIAL_SPINE_INVALID")
    name = posixpath.normpath(posixpath.join(
        posixpath.dirname(opf), manifest[spine[0]]["href"]
    ))
    if name not in z.namelist() or not name.lower().endswith((".xhtml", ".html")):
        raise ValueError("RAW_PARTIAL_DOCUMENT_MISSING")
    return z.read(name).decode("utf-8-sig")


def check_notes(book_dir: Path, compiled_epub: Path, *,
                heading_policy: str = "v3", pdf: Path | None = None,
                inspector=None) -> dict:
    if heading_policy not in {"v3", "v4", "v5", "v6", "v7"}:
        raise ValueError("UNKNOWN_HEADING_POLICY")
    if inspector is None:
        from wereadlab import inspect_epub
        inspector = inspect_epub
    book_dir, compiled_epub = Path(book_dir), Path(compiled_epub)
    rows, _ = _read_validated_sources(
        book_dir / "chapters.sqlite", book_dir / "catalog.json", inspector
    )
    candidate = inspector(compiled_epub, expected=len(rows))
    issues: list[dict] = []
    def flag(kind, ordinal=None):
        problem = {"kind": kind}
        if ordinal is not None:
            problem["ordinal"] = ordinal
        issues.append(problem)
    if candidate["status"] != "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED":
        flag("COMPILED_EPUB_STRUCTURE_INVALID")
    raw_count = selected_count = repaired_count = matches = anchors = 0
    all_notes: list[str] = []
    with ZipFile(compiled_epub) as final:
        if final.testzip() is not None:
            flag("COMPILED_ZIP_CRC_INVALID")
        compiled_paths = set(final.namelist())
        for row in rows:
            n = row["ordinal"]
            raw_path = book_dir / "chapters" / f"{n:04d}.partial.epub"
            target = f"OEBPS/text/chapter_{n:04d}.xhtml"
            if not raw_path.is_file():
                flag("RAW_PARTIAL_MISSING", n)
                continue
            if target not in compiled_paths:
                flag("COMPILED_CHAPTER_MISSING", n)
                continue
            with ZipFile(raw_path) as raw:
                if raw.testzip() is not None:
                    flag("RAW_PARTIAL_CRC_INVALID", n)
                    continue
                raw_markup = _spine_xhtml(raw)
            # The selected chapter can legitimately differ from the raw partial
            # after a source-proven TXT fallback (e.g. extra copyright metadata).
            # Compare full body anchors against that queued, SHA-checked source,
            # while independently checking that its notes match the raw partial.
            with ZipFile(row["file"]) as selected:
                if selected.testzip() is not None:
                    flag("SELECTED_SOURCE_CRC_INVALID", n)
                    continue
                source = _spine_xhtml(selected)
            source, _ = dedupe_one_chapter(
                source, catalog_title=row["chapter_title"],
                include_source_h2=(heading_policy in {"v4", "v5", "v6", "v7"}),
                include_city_h2=(heading_policy in {"v5", "v6", "v7"}),
                include_dash_one_h2=(heading_policy in {"v6", "v7"}),
                include_no_id_h2=(heading_policy == "v7"),
            )
            raw_body, src, dst = NoteBody(), NoteBody(), NoteBody()
            raw_body.feed(raw_markup)
            src.feed(source)
            dst.feed(final.read(target).decode("utf-8-sig"))
            raw_body.close();src.close();dst.close()
            raw_count += len(raw_body.notes)
            selected_count += len(src.notes)
            repaired_count += len(dst.notes)
            if raw_body.notes != src.notes:
                flag("RAW_SELECTED_NOTE_MISMATCH", n)
            if src.anchor_text == dst.anchor_text:
                anchors += 1
            else:
                flag("BODY_OR_NOTE_ANCHOR_MISMATCH", n)
            if len(raw_body.notes) != len(dst.notes) or len(src.notes) != len(dst.notes):
                flag("NOTE_COUNT_MISMATCH", n)
            for before, after in zip(src.notes, dst.notes):
                if before == after:
                    matches += 1
                else:
                    flag("NOTE_TEXT_MISMATCH", n)
            all_notes.extend(dst.notes)

    pdf_status = "NOT_REQUESTED"
    pdf_unique_found = None
    pdf_folios_removed = None
    pdf_occurrences = {"status": "NOT_REQUESTED", "expected": len(all_notes),
                       "matched": None, "missing": None, "extra": None}
    if pdf is not None:
        text, pdf_folios_removed = pdf_content_text(pdf)
        unique = {normalize(label) for label in all_notes}
        pdf_unique_found = sum(bool(s and s in text) for s in unique)
        pdf_status = "PDF_UNIQUE_NOTE_STRINGS_PASS" if pdf_unique_found == len(unique) else "PDF_NOTE_TEXT_INCOMPLETE"
        if pdf_unique_found != len(unique):
            flag("PDF_NOTE_TEXT_MISSING")
        pdf_occurrences = pdf_note_multiplicity(all_notes, text)
        if pdf_occurrences["status"] != "PDF_NOTE_OCCURRENCE_MULTIPLICITY_PASS":
            flag("PDF_NOTE_OCCURRENCE_MULTIPLICITY_MISMATCH")
    unique_count = len({normalize(label) for label in all_notes})
    return {
        "status": PASS if not issues else INCOMPLETE,
        "heading_policy": heading_policy,
        "chapters_expected": len(rows),
        "chapters_body_anchor_exact": anchors,
        "source_note_images": raw_count,
        "selected_source_note_markers": selected_count,
        "repaired_note_markers": repaired_count,
        "notes_text_exact": matches,
        "unique_note_labels": unique_count,
        "pdf_text_search_status": pdf_status,
        "pdf_unique_note_labels_found": pdf_unique_found,
        "pdf_page_number_blocks_removed": pdf_folios_removed,
        "pdf_note_occurrence_status": pdf_occurrences["status"],
        "pdf_note_occurrences_expected": pdf_occurrences["expected"],
        "pdf_note_occurrences_matched": pdf_occurrences["matched"],
        "pdf_note_occurrences_missing": pdf_occurrences["missing"],
        "pdf_note_occurrences_extra": pdf_occurrences["extra"],
        "issue_count": len(issues),
        "issue_codes": dict(sorted(Counter(i["kind"] for i in issues).items())),
        "issue_examples": issues[:25],
        "source_reader_popup_parity": "SEPARATE_GATE",
        "human_visual_acceptance": "PENDING",
        "full_book_confirmed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline repaired annotation text/anchor audit")
    parser.add_argument("--book-dir", type=Path, required=True)
    parser.add_argument("--compiled", type=Path, required=True)
    parser.add_argument("--heading-policy", choices=["v3", "v4", "v5", "v6", "v7"], default="v3")
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = check_notes(args.book_dir, args.compiled,
                             heading_policy=args.heading_policy, pdf=args.pdf)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as exc:
        result = {
            "status": INCOMPLETE,
            "issue_count": 1,
            "issue_codes": {"SOURCE_OR_NOTE_EVIDENCE_INVALID": 1},
            "error_class": type(exc).__name__,
            "full_book_confirmed": False,
        }
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data, encoding="utf-8")
    print(data, end="")
    return 0 if result["status"] == PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
