"""Offline-only tests for catalog snapshot and privacy boundaries."""
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock

import wereadlab as app
from tools.catalog_snapshot import build_catalog, fetch_catalog, save_catalog


class CatalogTests(unittest.TestCase):
    def sample_chapters(self):
        return [
            {"chapterUid": 1, "title": "封面", "wordCount": 1, "chapterIdx": 0},
            {"chapterUid": 2, "title": "版权信息", "wordCount": 110, "chapterIdx": 1},
            {"chapterUid": 3, "title": "空白页", "wordCount": 0, "chapterIdx": 2},
            {"chapterUid": "four", "title": "第一节 千里通波", "wordCount": "9750", "chapterIdx": 3},
        ]

    def test_catalog_filters_like_upstream_but_retains_excluded_rows(self):
        doc = build_catalog(
            self.sample_chapters(), title="合成运河书", author="匿名",
            book_id="formal-id", reader_id="reader-id", upstream_sha="pin123"
        )
        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["totals"]["catalog_entries"], 4)
        self.assertEqual(doc["totals"]["selected_for_export"], 2)
        self.assertEqual(doc["totals"]["excluded_entries"], 2)
        self.assertEqual(doc["totals"]["selected_provider_word_count"], 9860)
        self.assertEqual([row["order"] for row in doc["chapters"]], [1, 2, 3, 4])
        self.assertEqual([row["selected_for_export"] for row in doc["chapters"]],
                         [False, True, False, True])

    def test_duplicate_and_invalid_ids_cannot_claim_catalog_ready(self):
        chapters = self.sample_chapters()
        chapters[1]["chapterUid"] = 1
        with self.assertRaisesRegex(ValueError, "DUPLICATE_CHAPTER_UID"):
            build_catalog(chapters, title="T", author="", book_id="b", reader_id="r", upstream_sha=None)
        chapters[1]["chapterUid"] = None
        with self.assertRaisesRegex(ValueError, "MISSING_CHAPTER_UID"):
            build_catalog(chapters, title="T", author="", book_id="b", reader_id="r", upstream_sha=None)

    def test_local_snapshot_is_atomic_and_excludes_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            doc = build_catalog(
                self.sample_chapters(), title="合成书", author="",
                book_id="formal", reader_id="reader", upstream_sha="sha"
            )
            save_catalog(doc, path)
            self.assertTrue(path.exists())
            self.assertFalse(path.with_suffix(".json.tmp").exists())
            self.assertNotIn("cookie", path.read_text(encoding="utf-8").lower())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["totals"]["selected_for_export"], 2)

    def test_fetch_uses_only_reader_html_and_catalog_endpoint(self):
        calls = []
        chapters = self.sample_chapters()
        class FakeClient:
            def __init__(self, **kw):
                calls.append(("init", kw["cookie_file"].name))
            def renew(self):
                calls.append(("renew",))
                return True
            def get_text(self, url, **kw):
                calls.append(("html",))
                return "<html></html>"
            def post_json(self, url, data, **kw):
                calls.append(("catalog", url, data))
                return {"fixture": True}
            def persist_cookies(self):
                calls.append(("persist",))
        provider = types.SimpleNamespace(
            WeReadClient=FakeClient,
            read_reader_state=lambda html: types.SimpleNamespace(
                book_id="formal", book_title="合成书", author="匿名"
            ),
            normalize_chapter_infos=lambda payload, book_id: (
                {"book": {"title": "合成书", "author": "匿名"}}, chapters
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            cookie = Path(tmp) / "cookies.txt"
            cookie.write_text("synthetic; not real cookies", encoding="utf-8")
            doc = fetch_catalog(
                reader_url="https://weread.qq.com/web/reader/fixture",
                reader_id="fixture", cookie_file=cookie,
                upstream_script=Path(tmp) / "not-loaded.py",
                upstream_sha="pinned", provider=provider
            )
            self.assertEqual(doc["totals"]["selected_for_export"], 2)
        self.assertEqual([x[0] for x in calls], ["init", "renew", "html", "catalog", "persist"])
        self.assertEqual(calls[3][2], {"bookIds": ["formal"]})

    def test_catalog_without_cookie_is_structured_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            with mock.patch.object(app, "COOKIE", home / "no.cookies"), \
                 mock.patch.object(app, "LIBRARY", home / "library"):
                args=app.argparse.Namespace(
                    url="https://weread.qq.com/web/reader/fixture",
                    output_dir=None
                )
                status=app.catalog_book(args)
                self.assertEqual(status["status"], "LOGIN_REQUIRED")
                self.assertTrue((home / "library" / "fixture" / "catalog.report.json").exists())


if __name__ == "__main__":
    unittest.main()
