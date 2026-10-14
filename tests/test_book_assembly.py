"""Offline tests for ordered full-book assembly. No real account or content."""
from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock
import zipfile

import wereadlab as app
from test_chapter_worker import FixtureProvider, fixture_workspace, run
from tools.book_assembly import assemble_book


class BookAssemblyTests(unittest.TestCase):
    def test_incomplete_queue_creates_no_book_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            book, cat, db, cookie = fixture_workspace(Path(tmp))
            provider = FixtureProvider()
            run(provider, cat, db, cookie, limit=1)
            target = book / "final" / "book.epub"
            result = assemble_book(db_path=db, catalog_path=cat,
                                   output=target, inspector=app.inspect_epub)
            self.assertEqual(result["status"], "ASSEMBLY_NOT_READY")
            self.assertEqual(result["complete"], 1)
            self.assertEqual(result["pending"], 1)
            self.assertFalse(target.exists())

    def test_complete_chapters_produce_ordered_epub(self):
        with tempfile.TemporaryDirectory() as tmp:
            book, cat, db, cookie = fixture_workspace(Path(tmp))
            provider = FixtureProvider()
            done = run(provider, cat, db, cookie, limit=2)
            self.assertEqual(done["status"], "CHAPTERS_FETCHED_PENDING_FULL_QA")
            target = book / "final" / "book.epub"
            result = assemble_book(db_path=db, catalog_path=cat,
                                   output=target, inspector=app.inspect_epub)
            self.assertEqual(result["status"], "BOOK_EPUB_READY_COMPLETENESS_UNVERIFIED")
            self.assertEqual(result["chapter_count"], 2)
            self.assertTrue(target.is_file())
            final = app.inspect_epub(target, expected=2)
            self.assertEqual(final["status"], "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED")
            with zipfile.ZipFile(target) as z:
                toc = z.read("OEBPS/nav.xhtml").decode("utf-8")
                self.assertLess(toc.index("第一章"), toc.index("第二章"))
                self.assertIn("OEBPS/text/chapter_0002.xhtml", z.namelist())
            md = app.markdown_from_epub(target, book/"final"/"book", include_text=True)
            self.assertTrue(Path(md["md"]).is_file())
            self.assertTrue(Path(md["txt"]).is_file())
            self.assertEqual(run(provider, cat, db, cookie)["status"], "WORKER_IDLE")

    def test_corrupted_source_hash_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            book, cat, db, cookie = fixture_workspace(Path(tmp))
            provider=FixtureProvider()
            run(provider, cat, db, cookie, limit=2)
            (book / "chapters" / "0001.epub").write_bytes(b"corrupt")
            target = book/"final"/"book.epub"
            with self.assertRaisesRegex(ValueError, "CHAPTER_ARTIFACT_SHA_MISMATCH"):
                assemble_book(db_path=db, catalog_path=cat, output=target,
                              inspector=app.inspect_epub)
            self.assertFalse(target.exists())

    def test_css_degradation_is_explicit_and_local_assets_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            book, cat, db, cookie = fixture_workspace(Path(tmp))
            provider = FixtureProvider()
            run(provider, cat, db, cookie, limit=2)
            # Rebuild two tiny validated source EPUB fixtures with a *local*
            # image of the same name in each chapter. This tests name collision.
            for ordinal in (1,2):
                path = book/"chapters"/f"{ordinal:04d}.epub"
                with zipfile.ZipFile(path) as src:
                    existing={name:src.read(name) for name in src.namelist()}
                xml=existing["OEBPS/content.opf"].decode()
                xml=xml.replace("</manifest>",
                    '<item id="style" href="styles/weread.css" media-type="text/css"/>'
                    '<item id="img" href="images/common.png" media-type="image/png"/>'
                    '</manifest>')
                doc=existing["OEBPS/c1.xhtml"].decode()
                doc=doc.replace('<body>', '<head><link rel="stylesheet" href="styles/weread.css"/></head><body>')
                doc=doc.replace('</body>', '<img src="images/common.png"/></body>')
                existing["OEBPS/content.opf"]=xml.encode()
                existing["OEBPS/c1.xhtml"]=doc.encode()
                existing["OEBPS/styles/weread.css"]=b"body { background-image: url(../Images/missing.png); }"
                existing["OEBPS/images/common.png"]=b"\x89PNG\r\n\x1a\n"+b"\0"*80
                with zipfile.ZipFile(path,"w") as target:
                    for name,data in existing.items():
                        target.writestr(name,data)
                import hashlib
                with closing(sqlite3.connect(db)) as conn:
                    conn.execute("UPDATE chapters SET artifact_sha256=? WHERE ordinal=?",
                        (hashlib.sha256(path.read_bytes()).hexdigest(),ordinal))
                    conn.commit()
            result=assemble_book(db_path=db,catalog_path=cat,
                                 output=book/"final/book.epub",inspector=app.inspect_epub)
            self.assertEqual(result["status"],"BOOK_EPUB_READY_COMPLETENESS_UNVERIFIED")
            self.assertEqual(result["css_warning_count"],2)
            with zipfile.ZipFile(book/"final/book.epub") as z:
                names=z.namelist()
                self.assertEqual(len([n for n in names if n.startswith("OEBPS/assets/")]),2)
                self.assertEqual(len([n for n in names if n.startswith("OEBPS/styles/chapter_")]),2)
                chapter=z.read("OEBPS/text/chapter_0001.xhtml").decode()
                self.assertIn("../assets/0001/",chapter)
                css=z.read("OEBPS/styles/chapter_0001.css").decode()
                self.assertIn("background-image: none",css)
            self.assertEqual(app.inspect_epub(book/"final/book.epub",expected=2)["status"],
                             "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED")

    def test_cli_assemble_offline_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            book, cat, db, cookie = fixture_workspace(Path(tmp))
            provider = FixtureProvider()
            run(provider, cat, db, cookie, limit=2)
            with mock.patch.object(app,"LIBRARY",Path(tmp)/"library"):
                buffer=io.StringIO()
                with redirect_stdout(buffer):
                    code=app.main(["book","assemble","--latest","--json"])
                self.assertEqual(code,0)
                data=json.loads(buffer.getvalue())
                self.assertEqual(data["status"],"BOOK_FILES_READY_COMPLETENESS_UNVERIFIED")
                self.assertEqual(data["chapter_count"],2)


if __name__=="__main__":
    unittest.main()
