"""Synthetic-only checks for P2-D3 source-to-exported-text parity audit."""
from pathlib import Path
import tempfile
import unittest

from tools.source_parity_audit import (
    normalized_body, compare_xhtml, parse_checks, audit_live
)
from test_chapter_worker import FixtureProvider, fixture_workspace, run


class TestCompare(unittest.TestCase):
    def test_exporter_synthetic_chapter_heading_is_ignored(self):
        source = (
            '<html><head><title>metadata only</title></head>'
            '<body><p>繁體與简体之间。</p><p>第二段！</p></body></html>'
        )
        exported = (
            '<html><head><title>metadata only</title></head><body>'
            '<h1>第一章</h1><p>繁體與简体之间。</p>'
            '<p>第二段！</p></body></html>'
        )
        check = compare_xhtml(source, exported)
        self.assertTrue(check["exact"])
        self.assertEqual(check["status"], "SOURCE_TEXT_EXACT_AFTER_DEFINED_NORMALIZATION")

    def test_punctuation_change_is_visible(self):
        src = "<html><body><p>运河文字，历史叙述。</p></body></html>"
        target = "<html><body><h1>历史</h1><p>运河文字。历史叙述。</p></body></html>"
        result = compare_xhtml(src, target)
        self.assertFalse(result["exact"])
        self.assertLess(result["similarity_ratio"], 1)
        self.assertGreater(result["same_prefix_characters"], 0)

    def test_note_alt_is_preserved_and_wrappers_ignored(self):
        source = (
            '<html><body><p>原文</p>'
            '<img src="Images/note.png" alt="这是一条重要的史料注释"/>'
            '<p>续文。</p></body></html>'
        )
        exported = (
            '<html><body><h1>第一章</h1><p>原文</p>'
            '<span class="weread-note-marker">〔注：这是一条重要的史料注释〕</span>'
            '<p>续文。</p></body></html>'
        )
        self.assertTrue(compare_xhtml(source, exported)["exact"])

    def test_checks_bounded_and_typed(self):
        self.assertEqual(parse_checks("19:txt,20:txt,5:epub"),
                         [(19, "txt"), (20, "txt"), (5, "epub")])
        for invalid in ("", "1", "1:pdf", "1:txt,1:epub",
                        "0:txt", "501:txt", "a:txt",
                        "1:txt,2:txt,3:txt,4:txt,5:txt,6:txt,7:txt"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                parse_checks(invalid)

    def test_source_text_not_exposed_in_result(self):
        phrase = "不应当输出的合成正文秘密"
        source = "<html><body><p>" + phrase + "</p></body></html>"
        exported = "<html><body><h1>章节名</h1><p>" + phrase + "</p></body></html>"
        report = repr(compare_xhtml(source, exported))
        self.assertNotIn(phrase, report)
        self.assertNotIn("章节名", report)


class FakeAuditProvider(FixtureProvider):
    def fetch_chapter(self, client, *, book_id, chapter, sleep_seconds, content_format):
        title, text, css, assets = super().fetch_chapter(
            client, book_id=book_id, chapter=chapter,
            sleep_seconds=sleep_seconds, content_format=content_format
        )
        return title, "<html><body><p>" + text + "</p></body></html>", css, assets


class TestLiveFake(unittest.TestCase):
    def test_bounded_re_fetch_compares_existing_synthetic_chapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory, catalog, db, cookie = fixture_workspace(Path(tmp))
            provider = FakeAuditProvider()
            result = run(provider, catalog, db, cookie, limit=2)
            self.assertEqual(result["complete"], 2)
            checked = audit_live(
                book_dir=directory,
                cookie_file=cookie,
                upstream_script=Path(tmp) / "unused.py",
                upstream_sha="pinned",
                checks=[(1, "txt"), (2, "epub")],
                provider=provider
            )
            self.assertEqual(checked["status"], "SOURCE_PARITY_EXACT_FOR_CHECKED_CHAPTERS")
            self.assertEqual(checked["chapters_checked"], 2)
            self.assertEqual(checked["chapters_exact"], 2)
            self.assertEqual(checked["chapters_with_differences"], 0)
            self.assertNotIn("合成文字", repr(checked))

    def test_changed_source_detects_difference_without_text_leak(self):
        class EditedProvider(FakeAuditProvider):
            def fetch_chapter(self, client, *, book_id, chapter, sleep_seconds, content_format):
                title, source, css, assets = super().fetch_chapter(
                    client, book_id=book_id, chapter=chapter,
                    sleep_seconds=sleep_seconds, content_format=content_format
                )
                return title, source.replace("合成文字", "样本更改", 1), css, assets

        with tempfile.TemporaryDirectory() as tmp:
            folder, catalog, db, cookie = fixture_workspace(Path(tmp))
            baseline = FakeAuditProvider()
            run(baseline, catalog, db, cookie, limit=2)
            result = audit_live(
                book_dir=folder, cookie_file=cookie,
                upstream_script=Path(tmp) / "unused.py",
                upstream_sha="pinned", checks=[(1, "txt")],
                provider=EditedProvider()
            )
            self.assertEqual(result["status"], "SOURCE_PARITY_DIFFERENCES_REQUIRE_REVIEW")
            self.assertFalse(result["results"][0]["exact"])

    def test_artifact_corruption_is_blocked_before_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder, catalog, db, cookie = fixture_workspace(Path(tmp))
            provider = FakeAuditProvider()
            run(provider, catalog, db, cookie, limit=2)
            target = folder / "chapters/0001.epub"
            target.write_bytes(b"corrupt")
            with self.assertRaisesRegex(RuntimeError, "ARTIFACT_SHA_MISMATCH"):
                audit_live(
                    book_dir=folder, cookie_file=cookie,
                    upstream_script=Path(tmp) / "unused.py",
                    upstream_sha="pinned", checks=[(1, "txt")],
                    provider=provider
                )


if __name__ == "__main__":
    unittest.main()
