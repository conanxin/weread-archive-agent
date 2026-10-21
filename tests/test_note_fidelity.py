"""Synthetic-only annotation recovery parity and fail-closed regression tests."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile

import wereadlab as app
from test_chapter_worker import FixtureProvider, fixture_workspace, run
from tools.book_assembly import assemble_book
from tools.note_fidelity import (PASS, INCOMPLETE, check_notes,
                                 pdf_note_multiplicity, pdf_text_without_page_numbers,
                                 page_number_block_indices)


class FakeRect:
    def __init__(self, width, height):
        self.width = width
        self.height = height


class FakeMatrix:
    def __init__(self, a, b, c, d, e, f):
        self.a, self.b, self.c, self.d, self.e, self.f = a, b, c, d, e, f


class FakePage:
    """Minimal PDF page double exposing only what the text extractor uses."""

    def __init__(self, blocks, *, width=612.0, height=792.0,
                 rotation=0, rotation_matrix=None):
        self.rect = FakeRect(width, height)
        self.blocks = list(blocks)
        self.rotation = rotation
        self.rotation_matrix = rotation_matrix

    def get_text(self, mode):
        assert mode == "blocks"
        return list(self.blocks)


def block(x0, y0, x1, y1, text):
    return (x0, y0, x1, y1, text, 0, 0)


class NoteFidelityTests(unittest.TestCase):
    @staticmethod
    def modify_zip(path, transform):
        staged = path.with_name(path.name + ".next")
        with ZipFile(path) as old, ZipFile(staged, "w") as out:
            for entry in old.infolist():
                content = old.read(entry.filename)
                if entry.filename == "OEBPS/c1.xhtml":
                    content = transform(content)
                out.writestr(entry, content)
        staged.replace(path)

    def case(self, *, bare=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        book, catalog, queue, cookie = fixture_workspace(Path(temporary.name))
        self.assertEqual(run(FixtureProvider(), catalog, queue, cookie, limit=2)["complete"], 2)
        for ordinal in (1, 2):
            label = "" if bare else "  引用注释" + str(ordinal) + "  "
            note_label = "〔注〕" if bare else "〔注：引用注释" + str(ordinal) + "〕"
            raw_file = book / "chapters" / f"{ordinal:04d}.partial.epub"
            repaired = book / "chapters" / f"{ordinal:04d}.epub"
            self.modify_zip(raw_file,
                lambda s: s.replace(b"</p>",
                    ('</p><img src="Images/note.png" alt="' + label + '"/>').encode(),1))
            self.modify_zip(repaired,
                lambda s: s.replace(b"</p>",
                    ('</p><span class="weread-note-marker">' + note_label + '</span>').encode(),1))
            with closing(sqlite3.connect(queue)) as db:
                db.execute(
                    "UPDATE chapters SET artifact_sha256=? WHERE ordinal=?",
                    (hashlib.sha256(repaired.read_bytes()).hexdigest(), ordinal)
                )
                db.commit()
        result = assemble_book(
            db_path=queue, catalog_path=catalog,
            output=book/"final"/"book.epub", inspector=app.inspect_epub
        )
        self.assertEqual(result["status"], "BOOK_EPUB_READY_COMPLETENESS_UNVERIFIED")
        return book, book/"final"/"book.epub"

    @staticmethod
    def modify_compiled(compiled, transform, ordinal=1):
        with ZipFile(compiled) as source:
            parts = [(i, source.read(i.filename)) for i in source.infolist()]
        staged=compiled.with_name("modified.epub")
        target=f"OEBPS/text/chapter_{ordinal:04d}.xhtml"
        with ZipFile(staged, "w") as out:
            for info, raw in parts:
                out.writestr(info, transform(raw) if info.filename == target else raw)
        staged.replace(compiled)

    def kinds(self, report):
        return set(report["issue_codes"])

    def test_complete_note_text_and_anchor_match(self):
        book,compiled=self.case()
        result=check_notes(book,compiled,inspector=app.inspect_epub)
        self.assertEqual(result["status"],PASS)
        self.assertEqual(result["source_note_images"],2)
        self.assertEqual(result["repaired_note_markers"],2)
        self.assertEqual(result["notes_text_exact"],2)
        self.assertEqual(result["chapters_body_anchor_exact"],2)
        self.assertEqual(result["pdf_text_search_status"],"NOT_REQUESTED")
        self.assertFalse(result["full_book_confirmed"])

    def test_bare_note_alt_preserves_explicit_fallback(self):
        book,compiled=self.case(bare=True)
        result=check_notes(book,compiled,inspector=app.inspect_epub)
        self.assertEqual(result["status"],PASS)
        self.assertEqual(result["notes_text_exact"],2)
        self.assertEqual(result["unique_note_labels"],1)

    def test_modified_note_text_is_rejected(self):
        book,compiled=self.case()
        self.modify_compiled(compiled,
            lambda s:s.replace("引用注释1".encode(),"其它注释1".encode(),1))
        report=check_notes(book,compiled,inspector=app.inspect_epub)
        self.assertEqual(report["status"],INCOMPLETE)
        self.assertIn("NOTE_TEXT_MISMATCH",self.kinds(report))

    def test_moved_marker_without_text_loss_is_rejected(self):
        book,compiled=self.case()
        self.modify_compiled(compiled,
            lambda s:s.replace("</p><span class=\"weread-note-marker\">".encode(),
                               "<span class=\"weread-note-marker\">".encode(),1).replace(
                               "</span>".encode(),"</span></p>".encode(),1))
        report=check_notes(book,compiled,inspector=app.inspect_epub)
        self.assertEqual(report["status"],INCOMPLETE)
        self.assertIn("BODY_OR_NOTE_ANCHOR_MISMATCH",self.kinds(report))

    def test_missing_note_marker_is_rejected(self):
        book,compiled=self.case()
        self.modify_compiled(compiled,
            lambda s:s.replace('<span class="weread-note-marker">〔注：引用注释1〕</span>'.encode(),
                               b"",1))
        result=check_notes(book,compiled,inspector=app.inspect_epub)
        self.assertIn("NOTE_COUNT_MISMATCH",self.kinds(result))
        self.assertIn("BODY_OR_NOTE_ANCHOR_MISMATCH",self.kinds(result))

    def test_missing_raw_checkpoint_is_rejected(self):
        book,compiled=self.case()
        (book/"chapters"/"0001.partial.epub").unlink()
        report=check_notes(book,compiled,inspector=app.inspect_epub)
        self.assertEqual(report["status"],INCOMPLETE)
        self.assertIn("RAW_PARTIAL_MISSING",self.kinds(report))

    def test_pdf_inline_note_duplicate_occurrences_all_present(self):
        expected = ["〔注：甲〕", "〔注：甲〕", "〔注：乙〕"]
        result = pdf_note_multiplicity(expected, "前文 〔注：甲〕 接续 〔注：乙〕 〔注：甲〕")
        self.assertEqual(result["status"], "PDF_NOTE_OCCURRENCE_MULTIPLICITY_PASS")
        self.assertEqual((result["expected"], result["matched"]), (3, 3))
        self.assertEqual(result["missing"], 0)
        self.assertEqual(result["extra"], 0)

    def test_pdf_inline_note_missing_repeated_occurrence_rejected(self):
        expected = ["〔注：甲〕", "〔注：甲〕", "〔注：乙〕"]
        result = pdf_note_multiplicity(expected, "〔注：甲〕〔注：乙〕")
        self.assertEqual(result["status"], "PDF_NOTE_OCCURRENCE_MULTIPLICITY_INCOMPLETE")
        self.assertEqual((result["matched"], result["missing"], result["extra"]), (2, 1, 0))

    def test_pdf_inline_note_extra_occurrence_rejected(self):
        expected = ["〔注：甲〕", "〔注：乙〕"]
        result = pdf_note_multiplicity(expected, "〔注：甲〕〔注：乙〕〔注：甲〕")
        self.assertEqual(result["status"], "PDF_NOTE_OCCURRENCE_MULTIPLICITY_INCOMPLETE")
        self.assertEqual((result["matched"], result["missing"], result["extra"]), (2, 0, 1))

    @staticmethod
    def reassemble_selected_source(book):
        output = book / "final" / "book.epub"
        output.unlink()
        report = assemble_book(
            db_path=book / "chapters.sqlite", catalog_path=book / "catalog.json",
            output=output, inspector=app.inspect_epub
        )
        assert report["status"] == "BOOK_EPUB_READY_COMPLETENESS_UNVERIFIED"
        return output

    @staticmethod
    def refresh_selected_hash(book, ordinal=1):
        chosen = book / "chapters" / f"{ordinal:04d}.epub"
        with closing(sqlite3.connect(book / "chapters.sqlite")) as db:
            db.execute("UPDATE chapters SET artifact_sha256=? WHERE ordinal=?",
                       (hashlib.sha256(chosen.read_bytes()).hexdigest(), ordinal))
            db.commit()

    def test_source_proven_txt_expansion_does_not_falsely_break_note_anchor(self):
        book,compiled = self.case()
        # Only the selected source has an extra body paragraph; raw partial
        # retains its original note text and position.
        self.modify_zip(book / "chapters" / "0001.epub",
            lambda raw: raw.replace(
                b"</body>", "<p>已核实的补充版权字段</p></body>".encode("utf-8"), 1))
        self.refresh_selected_hash(book)
        compiled = self.reassemble_selected_source(book)
        report = check_notes(book, compiled, inspector=app.inspect_epub)
        self.assertEqual(report["status"], PASS)
        self.assertEqual(report["chapters_body_anchor_exact"], 2)
        self.assertEqual(report["source_note_images"], 2)
        self.assertEqual(report["selected_source_note_markers"], 2)
        self.assertEqual(report["notes_text_exact"], 2)

    def test_raw_note_change_is_detected_even_if_compiled_matches_selected(self):
        book,compiled = self.case()
        # Both chosen source and output still have the unmodified annotation,
        # but the raw recorded source proves the note should be different.
        self.modify_zip(book / "chapters" / "0001.partial.epub",
            lambda raw: raw.replace(
                "引用注释1".encode("utf-8"), "另一条注释".encode("utf-8"), 1))
        report = check_notes(book, compiled, inspector=app.inspect_epub)
        self.assertEqual(report["status"], INCOMPLETE)
        self.assertIn("RAW_SELECTED_NOTE_MISMATCH", self.kinds(report))

    def test_v7_no_id_heading_and_notes_are_verified_together(self):
        book,compiled = self.case()
        change = lambda raw: raw.replace(
            "<h1>合成章节</h1>".encode("utf-8"),
            '<h1>第一章</h1><h2 class="secondTitle">第一章</h2>'.encode("utf-8"), 1)
        self.modify_zip(book / "chapters" / "0001.partial.epub", change)
        self.modify_zip(book / "chapters" / "0001.epub", change)
        self.refresh_selected_hash(book)
        compiled = self.reassemble_selected_source(book)
        self.modify_compiled(
            compiled,
            lambda raw: raw.replace("<h1>第一章</h1>".encode("utf-8"), b"", 1))
        previous = check_notes(book, compiled, heading_policy="v6",
                               inspector=app.inspect_epub)
        self.assertEqual(previous["status"], INCOMPLETE)
        self.assertIn("BODY_OR_NOTE_ANCHOR_MISMATCH", self.kinds(previous))
        fixed = check_notes(book, compiled, heading_policy="v7",
                            inspector=app.inspect_epub)
        self.assertEqual(fixed["status"], PASS)
        self.assertEqual(fixed["notes_text_exact"], 2)
        self.assertEqual(fixed["chapters_body_anchor_exact"], 2)

    def test_invalid_heading_policy_fails_closed(self):
        book,compiled=self.case()
        with self.assertRaisesRegex(ValueError,"UNKNOWN_HEADING_POLICY"):
            check_notes(book,compiled,heading_policy="../unsafe",inspector=app.inspect_epub)


class PdfPageNumberExtractionTests(unittest.TestCase):
    """Regression: a folio is drawn at the page bottom but emitted first.

    The folio therefore lands inside any annotation spanning a page break and
    used to break a large share of the annotations of one delivered book. Only
    the standalone, centred, bottom-most numeric block may be removed.
    """

    def test_folio_between_note_halves_is_removed_and_note_joins_up(self):
        # The folio block is emitted first in the content stream even though it
        # is drawn at the very bottom of the page.
        page = FakePage([
            block(298.5, 747.9, 313.5, 764.5, "1"),
            block(77.0, 71.9, 535.0, 400.0, "〔注：注释前半"),
        ])
        text, removed = pdf_text_without_page_numbers([page])
        self.assertEqual(removed, 1)
        self.assertNotIn("1", text)
        self.assertIn("〔注：注释前半", text)

    def test_cross_page_annotation_is_reassembled_without_the_folio(self):
        first = FakePage([
            block(298.5, 747.9, 313.5, 764.5, "1"),
            block(77.0, 71.9, 535.0, 400.0, "〔注：跨页注释"),
        ])
        second = FakePage([
            block(298.5, 747.9, 313.5, 764.5, "2"),
            block(77.0, 71.9, 535.0, 400.0, "的后半部分〕"),
        ])
        text, removed = pdf_text_without_page_numbers([first, second])
        self.assertEqual(removed, 2)
        self.assertIn("〔注：跨页注释的后半部分〕", text)
        self.assertNotIn("1", text)
        self.assertNotIn("2", text)

    def test_folio_value_and_geometry_of_a_letter_size_pdf(self):
        # A common Letter-size PDF: 443 pages of 612x792 with a centred folio
        # of the physical page number at y0=747.9.
        blocks = [
            block(298.5, 747.9, 313.5, 764.5, "222"),
            block(77.0, 71.9, 535.0, 700.0, "〔注：跨页注释"),
        ]
        self.assertEqual(
            page_number_block_indices(blocks, width=612.0, height=792.0,
                                      page_count=443), [0])

    def test_body_years_dates_and_isolated_numbers_are_preserved(self):
        page = FakePage([
            block(77.0, 71.9, 535.0, 400.0, "合成正文：一九二六年他毕业，某年某月某日购花八株。"),
            block(77.0, 420.0, 120.0, 440.0, "24"),
            block(300.0, 420.0, 340.0, 440.0, "1949"),
            block(450.0, 420.0, 500.0, 440.0, "1985"),
        ])
        text, removed = pdf_text_without_page_numbers([page])
        self.assertEqual(removed, 0)
        self.assertIn("一九二六年", text)
        self.assertIn("某年某月某日", text)
        self.assertIn("24", text)
        self.assertIn("1949", text)
        self.assertIn("1985", text)

    def test_centred_bottom_number_above_body_text_is_not_a_folio(self):
        # A standalone centred number in the bottom band is only a folio when
        # it also starts below every other text block of that page.
        page = FakePage([
            block(298.5, 747.9, 313.5, 764.5, "12"),
            block(77.0, 71.9, 535.0, 760.0, "正文最后一行在页码之下"),
        ])
        text, removed = pdf_text_without_page_numbers([page])
        self.assertEqual(removed, 0)
        self.assertIn("12", text)

    def test_folio_outside_the_bottom_band_is_kept(self):
        page = FakePage([
            block(298.5, 500.0, 313.5, 516.0, "7"),
            block(77.0, 71.9, 535.0, 760.0, "正文"),
        ])
        text, removed = pdf_text_without_page_numbers([page])
        self.assertEqual(removed, 0)
        self.assertIn("7", text)

    def test_off_centre_bottom_number_is_kept(self):
        page = FakePage([
            block(77.0, 747.9, 92.0, 764.5, "2"),
            block(77.0, 71.9, 535.0, 700.0, "正文"),
        ])
        text, removed = pdf_text_without_page_numbers([page])
        self.assertEqual(removed, 0)
        self.assertIn("2", text)

    def test_threshold_follows_the_real_page_size(self):
        # The same absolute coordinate is a folio on a 792pt page and ordinary
        # mid-page content on a 1200pt page, so no fixed y value is used.
        folio_page = FakePage([
            block(298.5, 760.0, 313.5, 776.0, "9"),
            block(77.0, 71.9, 535.0, 700.0, "正文"),
        ], width=612.0, height=792.0)
        folio_text, folio_removed = pdf_text_without_page_numbers([folio_page])
        self.assertEqual(folio_removed, 1)
        self.assertNotIn("9", folio_text)
        tall_page = FakePage([
            block(298.5, 760.0, 313.5, 776.0, "9"),
            block(77.0, 71.9, 535.0, 1100.0, "正文"),
        ], width=612.0, height=1200.0)
        tall_text, tall_removed = pdf_text_without_page_numbers([tall_page])
        self.assertEqual(tall_removed, 0)
        self.assertIn("9", tall_text)

    def test_number_outside_plausible_page_range_is_kept(self):
        page = FakePage([
            block(298.5, 747.9, 313.5, 764.5, "9999"),
            block(77.0, 71.9, 535.0, 700.0, "正文"),
        ])
        text, removed = pdf_text_without_page_numbers([page])
        self.assertEqual(removed, 0)
        self.assertIn("9999", text)

    def test_invalid_geometry_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "INVALID_PAGE_GEOMETRY"):
            page_number_block_indices([block(0, 0, 1, 1, "1")],
                                      width=0, height=792, page_count=1)
        with self.assertRaisesRegex(ValueError, "INVALID_PAGE_COUNT"):
            page_number_block_indices([block(0, 0, 1, 1, "1")],
                                      width=612, height=792, page_count=0)

    def test_removed_folio_restores_a_note_split_across_a_page_break(self):
        expected = ["〔注：甲〕", "〔注：甲〕", "〔注：乙〕"]
        # The folio sits inside the second annotation, so its label no longer
        # occurs as one string.
        split = "〔注：甲〕接续〔注：乙" + "222" + "〕〔注：甲〕"
        broken = pdf_note_multiplicity(expected, split)
        self.assertEqual(broken["status"], "PDF_NOTE_OCCURRENCE_MULTIPLICITY_INCOMPLETE")
        self.assertEqual(broken["missing"], 1)
        repaired = pdf_note_multiplicity(expected, split.replace("222", ""))
        self.assertEqual(repaired["status"], "PDF_NOTE_OCCURRENCE_MULTIPLICITY_PASS")
        self.assertEqual((repaired["matched"], repaired["missing"], repaired["extra"]),
                         (3, 0, 0))

    def test_genuinely_missing_or_duplicated_annotations_still_fail(self):
        missing = pdf_note_multiplicity(["〔注：甲〕", "〔注：甲〕", "〔注：乙〕"],
                                        "〔注：甲〕〔注：乙〕")
        self.assertEqual(missing["status"], "PDF_NOTE_OCCURRENCE_MULTIPLICITY_INCOMPLETE")
        self.assertEqual((missing["matched"], missing["missing"]), (2, 1))
        extra = pdf_note_multiplicity(["〔注：甲〕", "〔注：乙〕"],
                                      "〔注：甲〕〔注：乙〕〔注：甲〕")
        self.assertEqual(extra["status"], "PDF_NOTE_OCCURRENCE_MULTIPLICITY_INCOMPLETE")
        self.assertEqual((extra["matched"], extra["extra"]), (2, 1))


    def test_unicode_digit_symbols_are_preserved_without_conversion_errors(self):
        # isdigit() accepts superscripts/circled numbers, but int() cannot parse
        # them. They are body text, not page-number folios, and must survive.
        for symbol in ("²", "①"):
            with self.subTest(symbol=symbol):
                page = FakePage([
                    block(298.5, 747.9, 313.5, 764.5, symbol),
                    block(77.0, 71.9, 535.0, 700.0, "正文含有Unicode数字符号"),
                ])
                text, removed = pdf_text_without_page_numbers([page])
                self.assertEqual(removed, 0)
                self.assertIn(symbol, text)

    def test_rotated_page_transforms_block_boxes_before_folio_detection(self):
        # A 792x612 page rotated 90 degrees displays as 612x792. The raw
        # blocks are in unrotated coordinates; the folio maps to a centred
        # bottom block only after applying the page rotation matrix.
        page = FakePage([
            block(748.0, 298.0, 764.0, 314.0, "1"),
            block(71.9, 77.0, 400.0, 535.0, "〔注：旋转页跨页注释〕"),
        ], width=612.0, height=792.0, rotation=90,
           rotation_matrix=FakeMatrix(0, 1, -1, 0, 612, 0))
        text, removed = pdf_text_without_page_numbers([page])
        self.assertEqual(removed, 1)
        self.assertIn("〔注：旋转页跨页注释〕", text)
        self.assertNotIn("1", text)

    def test_rotated_page_without_matrix_fails_closed(self):
        page = FakePage([
            block(748.0, 298.0, 764.0, 314.0, "1"),
            block(71.9, 77.0, 400.0, 535.0, "正文"),
        ], width=612.0, height=792.0, rotation=90)
        with self.assertRaisesRegex(ValueError, "ROTATED_PAGE_MATRIX_REQUIRED"):
            pdf_text_without_page_numbers([page])



if __name__ == "__main__":
    unittest.main()
