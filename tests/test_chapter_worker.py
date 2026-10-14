"""Offline synthetic tests for P2-B2 chapter checkpoint/resume behavior."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import types
import unittest
from unittest import mock
import zipfile

import wereadlab as app
from tools.catalog_snapshot import build_catalog, save_catalog
from tools.checkpoint_queue import init_queue, inspect_queue
from tools.chapter_worker import run_chapter_worker
from tools.repair_epub_images import repair_epub_images

BOOK_ID = "FIXTURE_FORMAL_ID"
READER_URL = "https://weread.qq.com/web/reader/fixture_reader"


def make_one_chapter(target: Path, text: str, *, with_remote_image: bool):
    img = '<img src="https://res.weread.qq.com/wrepub/fixture.jpg"/>' if with_remote_image else ""
    source = ('<html xmlns="http://www.w3.org/1999/xhtml"><body>'
              '<h1>合成章节</h1><p>' + text + '</p>' + img + '</body></html>')
    package = ('<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
               '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
               '<dc:title>合成测试书</dc:title></metadata>'
               '<manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>'
               '</manifest><spine><itemref idref="c1"/></spine></package>')
    container = ('<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>')
    with zipfile.ZipFile(target, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", package)
        z.writestr("OEBPS/c1.xhtml", source)


class FixtureProvider:
    def __init__(self, *, image=False, chapters=None):
        self.use_image = image
        self.chapters = chapters or [
            {"chapterUid": 10, "title": "第一章", "wordCount": 1000},
            {"chapterUid": 20, "title": "第二章", "wordCount": 600},
        ]
        self.fetch_calls = []
        self.renew_count = 0
        self.parent = self

    def WeReadClient(self, **kwargs):
        outer = self
        class Client:
            def renew(self):
                outer.renew_count += 1
                return True
            def get_text(self, url, **kw):
                return "<html>synthetic reader</html>"
            def post_json(self, url, data, **kw):
                return {"synthetic": 1}
            def persist_cookies(self):
                pass
        return Client()

    def read_reader_state(self, html):
        return types.SimpleNamespace(book_id=BOOK_ID)

    def normalize_chapter_infos(self, payload, book_id):
        return {}, self.chapters

    def fetch_chapter(self, client, *, book_id, chapter, sleep_seconds, content_format):
        self.fetch_calls.append(chapter["chapterUid"])
        return chapter["title"], "合成文字" * 36, "", []

    def write_epub(self, target, *, title, author, chapters, css):
        make_one_chapter(target, "合成文字" * 36, with_remote_image=self.use_image)


def fixture_workspace(root: Path):
    book_dir = root / "library" / "fixture"
    book_dir.mkdir(parents=True)
    provider = FixtureProvider()
    cat = build_catalog(
        provider.chapters, title="合成测试书", author="作者",
        book_id=BOOK_ID, reader_id="fixture_reader", upstream_sha="pinned"
    )
    catalog = book_dir / "catalog.json"
    save_catalog(cat, catalog)
    db = book_dir / "chapters.sqlite"
    init_queue(catalog, db)
    cookie = root / "cookies.txt"
    cookie.write_text("synthetic fixture cookie, not a credential", encoding="utf-8")
    return book_dir, catalog, db, cookie


def run(provider, cat, db, cookie, *, limit=1, retry_failed=False, repairer=None):
    return run_chapter_worker(
        db_path=db,
        catalog_path=cat,
        reader_url=READER_URL,
        cookie_file=cookie,
        upstream_script=Path("/unused/fetch.py"),
        upstream_sha="pinned",
        inspector=app.inspect_epub,
        repairer=repairer or (lambda *args, **kwargs: None),
        limit=limit,
        retry_failed=retry_failed,
        provider=provider,
    )


class WorkerTests(unittest.TestCase):
    def test_one_chapter_then_resume_remaining_and_idle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            directory,cat,db,cookie=fixture_workspace(root)
            provider=FixtureProvider()
            first=run(provider,cat,db,cookie)
            self.assertEqual(first["status"],"WORKER_PROGRESS")
            self.assertEqual(first["completed_now"],1)
            self.assertEqual((first["complete"],first["pending"]),(1,1))
            self.assertTrue((directory/"chapters/0001.partial.epub").exists())
            self.assertTrue((directory/"chapters/0001.epub").exists())
            second=run(provider,cat,db,cookie)
            self.assertEqual(second["status"],"CHAPTERS_FETCHED_PENDING_FULL_QA")
            self.assertEqual((second["complete"],second["pending"]),(2,0))
            self.assertEqual(provider.fetch_calls,[10,20])
            idle=run(provider,cat,db,cookie)
            self.assertEqual(idle["status"],"WORKER_IDLE")
            self.assertEqual(provider.fetch_calls,[10,20])
            with closing(sqlite3.connect(db)) as conn:
                rows=conn.execute("SELECT state,artifact_sha256,attempts FROM chapters ORDER BY ordinal").fetchall()
            self.assertTrue(all(x[0]=="COMPLETE" and len(x[1])==64 and x[2]==1 for x in rows))

    def test_image_failure_retains_text_and_retry_does_not_fetch_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,cat,db,cookie=fixture_workspace(Path(tmp))
            provider=FixtureProvider(image=True)
            first=run(provider,cat,db,cookie,repairer=lambda *a,**kw: None)
            self.assertEqual(first["status"],"WORKER_PARTIAL")
            self.assertEqual(first["failed"],1)
            self.assertEqual(first["failures"][0]["reason_code"],"IMAGE_ASSETS_INCOMPLETE")
            self.assertTrue((directory/"chapters/0001.partial.epub").is_file())
            self.assertFalse((directory/"chapters/0001.epub").exists())
            good_bytes=b"\xff\xd8\xff"+b"\0"*50
            def successful_repair(source,output,**kwargs):
                return repair_epub_images(
                    source,output,
                    downloader=lambda url:(good_bytes,".jpg","image/jpeg")
                )
            resumed=run(provider,cat,db,cookie,retry_failed=True,repairer=successful_repair)
            self.assertEqual(resumed["status"],"WORKER_PROGRESS")
            self.assertEqual(resumed["complete"],1)
            self.assertEqual(provider.fetch_calls,[10]) # no duplicated chapter request
            self.assertEqual(app.inspect_epub(directory/"chapters/0001.epub")["remote_images"],[])

    def test_txt_fallback_recovers_truncated_epub_without_erasing_source(self):
        class TxtAwareProvider(FixtureProvider):
            def __init__(self, *, provide_txt=True):
                super().__init__()
                self.mode="auto"
                self.provide_txt=provide_txt
                self.modes=[]
            def fetch_chapter(self, client, *, book_id, chapter, sleep_seconds, content_format):
                mode=content_format[0]
                self.mode=mode
                self.modes.append(mode)
                self.fetch_calls.append(chapter["chapterUid"])
                text=("合成中文正文" * 180) if mode=="txt" and self.provide_txt else "短"
                return chapter["title"], text, "", []
            def write_epub(self, target, *, title, author, chapters, css):
                make_one_chapter(target, chapters[0][1], with_remote_image=(self.mode=="auto"))

        with tempfile.TemporaryDirectory() as tmp:
            book, cat, db, cookie = fixture_workspace(Path(tmp))
            provider=TxtAwareProvider(provide_txt=False)
            jpg=b"\xff\xd8\xff"+b"\0"*80
            def repair(source, output, **kw):
                return repair_epub_images(
                    source, output, downloader=lambda url:(jpg, ".jpg", "image/jpeg"))
            first=run(provider, cat, db, cookie, repairer=repair)
            self.assertEqual(first["status"],"WORKER_PARTIAL")
            self.assertEqual(first["failures"][0]["reason_code"],"TXT_FALLBACK_INCOMPLETE")
            self.assertTrue((book/"chapters/0001.partial.epub").exists())
            self.assertEqual(provider.modes,["auto","txt"])
            provider.provide_txt=True
            second=run(provider, cat, db, cookie, repairer=repair, retry_failed=True)
            self.assertEqual(second["status"],"WORKER_PROGRESS")
            self.assertEqual(second["txt_fallback_ordinals"],[1])
            self.assertEqual(provider.modes,["auto","txt","txt"]) # no epub refetch
            self.assertTrue((book/"chapters/0001.txt-fallback.partial.epub").exists())
            self.assertTrue((book/"chapters/0001.partial.epub").exists())
            self.assertEqual(app.inspect_epub(book/"chapters/0001.epub")["status"],
                             "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED")
            self.assertGreater(app.inspect_epub(book/"chapters/0001.epub")["text_characters"],1000)
            self.assertEqual(second["complete"],1)
            third=run(provider, cat, db, cookie, limit=1, repairer=repair)
            self.assertEqual(third["completed_now"],1) # process the second chapter
            self.assertEqual(third["txt_fallback_ordinals"],[2])
            self.assertEqual(provider.modes,["auto","txt","txt","auto","txt"])

    def test_invalid_complete_hash_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,cat,db,cookie=fixture_workspace(Path(tmp))
            provider=FixtureProvider()
            run(provider,cat,db,cookie)
            final=directory/"chapters/0001.epub"
            final.write_bytes(b"corrupt locally")
            outcome=run(provider,cat,db,cookie)
            self.assertEqual(outcome["status"],"COMPLETED_ARTIFACT_INTEGRITY_ERROR")
            self.assertEqual(outcome["affected_ordinals"],[1])
            self.assertEqual(provider.fetch_calls,[10])
            self.assertEqual(inspect_queue(db)["complete"],1)

    def test_catalog_drift_blocks_before_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,cat,db,cookie=fixture_workspace(Path(tmp))
            provider=FixtureProvider(chapters=[
                {"chapterUid":20,"title":"第二章","wordCount":600},
                {"chapterUid":10,"title":"第一章","wordCount":1000},
            ])
            outcome=run(provider,cat,db,cookie)
            self.assertEqual(outcome["status"],"WORKER_BLOCKED")
            self.assertEqual(outcome["reason_code"],"UPSTREAM_CATALOG_CHANGED")
            self.assertEqual(outcome["attempted"],0)
            self.assertEqual(inspect_queue(db)["pending"],2)

    def test_interrupted_row_must_be_explicitly_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,cat,db,cookie=fixture_workspace(Path(tmp))
            provider=FixtureProvider()
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("UPDATE chapters SET state='RUNNING' WHERE ordinal=1")
                conn.commit()
            first=run(provider,cat,db,cookie,limit=1)
            self.assertEqual(first["complete"],1)
            self.assertEqual(provider.fetch_calls,[20])
            with closing(sqlite3.connect(db)) as conn:
                self.assertEqual(conn.execute(
                    "SELECT error_code FROM chapters WHERE ordinal=1"
                ).fetchone()[0],"INTERRUPTED")
            resume=run(provider,cat,db,cookie,retry_failed=True)
            self.assertEqual(resume["status"],"CHAPTERS_FETCHED_PENDING_FULL_QA")
            self.assertEqual(provider.fetch_calls,[20,10])

    def test_catalog_hash_change_rejected_without_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory,cat,db,cookie=fixture_workspace(Path(tmp))
            provider=FixtureProvider()
            cat.write_text(cat.read_text(encoding="utf-8")+"\n",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"CATALOG_SNAPSHOT_HASH_MISMATCH"):
                run(provider,cat,db,cookie)
            self.assertEqual(provider.fetch_calls,[])
            self.assertEqual(inspect_queue(db)["pending"],2)


if __name__=="__main__":
    unittest.main()
