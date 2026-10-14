"""Offline SQLite queue tests; no WeRead account or chapter text."""
from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import wereadlab as app
from tools.catalog_snapshot import build_catalog, save_catalog
from tools.checkpoint_queue import init_queue, inspect_queue


def sample_catalog(tmp: Path, *, uid_suffix=""):
    rows = [
        {"chapterUid": "cover", "title": "封面", "wordCount": 1},
        {"chapterUid": "one", "title": "第一章", "wordCount": 230},
        {"chapterUid": "two"+uid_suffix, "title": "第二章", "wordCount": 500},
    ]
    catalog = build_catalog(
        rows, title="合成测试书", author="合成作者",
        book_id="not-real", reader_id="fake", upstream_sha="fixture-sha"
    )
    path = tmp / "catalog.json"
    save_catalog(catalog, path)
    return path


class QueueTests(unittest.TestCase):
    def test_init_and_status_use_selected_chapters_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            catalog = sample_catalog(home)
            db = home / "chapters.sqlite"
            result = init_queue(catalog, db)
            self.assertEqual(result["status"], "QUEUE_READY")
            self.assertEqual(result["total_chapters"], 2)
            self.assertEqual(result["pending"], 2)
            self.assertEqual(result["complete"], 0)
            with closing(sqlite3.connect(db)) as conn:
                items = conn.execute(
                    "SELECT chapter_uid, catalog_order, state FROM chapters ORDER BY ordinal"
                ).fetchall()
            self.assertEqual(items, [("one",2,"PENDING"),("two",3,"PENDING")])
            self.assertEqual(inspect_queue(db)["pending"], 2)

    def test_reinitialization_preserves_completed_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            catalog = sample_catalog(home)
            db = home / "chapters.sqlite"
            init_queue(catalog, db)
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("UPDATE chapters SET state='COMPLETE', attempts=1 WHERE chapter_uid='one'")
                conn.commit()
            again = init_queue(catalog, db)
            self.assertEqual(again["complete"], 1)
            self.assertEqual(again["pending"], 1)

    def test_catalog_change_requires_explicit_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            catalog = sample_catalog(home)
            db = home / "chapters.sqlite"
            init_queue(catalog, db)
            sample_catalog(home, uid_suffix="new")
            with self.assertRaisesRegex(ValueError, "CATALOG_CHANGED_RECONCILIATION_REQUIRED"):
                init_queue(catalog, db)
            self.assertEqual(inspect_queue(db)["pending"], 2)

    def test_cli_init_latest_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            book = home / "library" / "synthetic"
            book.mkdir(parents=True)
            sample_catalog(book)
            with mock.patch.object(app, "LIBRARY", home / "library"):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    exit_code = app.main(["queue","init","--latest","--json"])
                self.assertEqual(exit_code, 0)
                response = json.loads(buf.getvalue())
                self.assertEqual(response["status"], "QUEUE_READY")
                self.assertEqual(response["total_chapters"], 2)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    exit_code = app.main(["queue","status","--latest","--json"])
                self.assertEqual(exit_code, 0)
                self.assertEqual(json.loads(buf.getvalue())["pending"], 2)


if __name__ == "__main__":
    unittest.main()
