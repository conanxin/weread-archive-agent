"""Synthetic, offline-only checks for EPUB CSS resource audit."""
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.fidelity_audit import audit_css_sources, audit_book_directory


def make_chapter(path: Path, css: str, xhtml: str, *, add_present=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("OEBPS/text/chapter.xhtml", xhtml)
        z.writestr("OEBPS/styles/book.css", css)
        if add_present:
            z.writestr("OEBPS/images/present.png", b"\x89PNG\r\n\x1a\nsynthetic")


class FidelityAuditTests(unittest.TestCase):
    def test_identical_missing_background_is_one_resource_not_two_images(self):
        css = (
            ".unused {background-image:url(../Images/missing-background.png);}"
            ".used {background-image: url('../Images/missing-in-used.png');}"
            ".complex > p {background-image: url(../Images/unknown.png);}"
            ".okay {background-image: url(../images/present.png);}"
            ".inline {background-image:url(data:image/png;base64,AAAA);}"
        )
        html = ('<html><body><p class="used other">Synthetic body</p>'
                '<div class="okay"></div></body></html>')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            paths = [folder / f"{i:04d}.epub" for i in (1, 2)]
            for path in paths:
                make_chapter(path, css, html)
            report = audit_css_sources(paths)
            self.assertEqual(report["chapters_audited"], 2)
            self.assertEqual(report["missing_reference_occurrences"], 6)
            self.assertEqual(report["unique_missing_resources"], 3)
            self.assertEqual(report["usage_classification"]["UNUSED_SIMPLE_CLASS"], 2)
            self.assertEqual(report["usage_classification"]["USED_SIMPLE_CLASS"], 2)
            self.assertEqual(report["usage_classification"]["UNKNOWN_OR_COMPLEX_SELECTOR"], 2)
            self.assertEqual(sorted(r["occurrences"] for r in report["resources"]), [2, 2, 2])
            self.assertNotIn("missing-in-used", str(report))
            self.assertNotIn("Synthetic body", str(report))

    def test_only_contiguous_complete_chapters_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            chapter_dir=folder / "chapters"
            make_chapter(chapter_dir / "0001.epub", ".unused{background:url(a.png)}", "<p/>")
            make_chapter(chapter_dir / "0002.partial.epub", ".unused{background:url(a.png)}", "<p/>")
            self.assertEqual(audit_book_directory(folder)["chapters_audited"], 1)
            make_chapter(chapter_dir / "0003.epub", ".unused{background:url(a.png)}", "<p/>")
            with self.assertRaisesRegex(ValueError, "CHAPTER_EPUB_ORDINAL_GAPS"):
                audit_book_directory(folder)

    def test_class_list_is_tokenized_not_substring_guessed(self):
        css = ".short{background-image:url(missing.png)}"
        html = '<p class="shortened">not matching .short</p>'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"0001.epub"
            make_chapter(path,css,html)
            report=audit_css_sources([path])
            self.assertEqual(report["usage_classification"]["UNUSED_SIMPLE_CLASS"],1)


if __name__ == "__main__":
    unittest.main()
