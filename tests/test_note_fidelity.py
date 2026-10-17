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
from tools.note_fidelity import PASS, INCOMPLETE, check_notes


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

    def test_invalid_heading_policy_fails_closed(self):
        book,compiled=self.case()
        with self.assertRaisesRegex(ValueError,"UNKNOWN_HEADING_POLICY"):
            check_notes(book,compiled,heading_policy="../unsafe",inspector=app.inspect_epub)


if __name__ == "__main__":
    unittest.main()
