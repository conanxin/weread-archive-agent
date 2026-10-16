"""P3-H synthetic EPUB parity regressions; never uses real books/accounts."""
from contextlib import closing
import hashlib
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile

import wereadlab as app
from test_chapter_worker import FixtureProvider, fixture_workspace, run
from tools.book_assembly import assemble_book
from tools.cached_source_parity import PASS, INCOMPLETE, verify_cached_source


class CachedSourceParityTests(unittest.TestCase):
    def build_case(self, *, with_images=True, wrapped_title=False, second_title=False):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        book, cat, db, cookie = fixture_workspace(root)
        self.assertEqual(run(FixtureProvider(), cat, db, cookie, limit=2)["complete"], 2)
        if with_images or wrapped_title or second_title:
            for ordinal in (1, 2):
                source = book / "chapters" / f"{ordinal:04d}.epub"
                with ZipFile(source) as old:
                    files = {n: old.read(n) for n in old.namelist()}
                if with_images:
                    opf = files["OEBPS/content.opf"].decode()
                    opf = opf.replace("</manifest>",
                        '<item id="image1" href="images/pic.png" media-type="image/png"/>'
                        "</manifest>")
                    files["OEBPS/content.opf"] = opf.encode()
                xhtml = files["OEBPS/c1.xhtml"].decode()
                if with_images:
                    xhtml = xhtml.replace("</body>",
                        f'<figure><img src="images/pic.png" alt="图注{ordinal}"/>'
                        f'<figcaption>图注说明{ordinal}</figcaption></figure>'
                        '<p>〔注〕合成脚注文本</p></body>')
                    files["OEBPS/images/pic.png"] = (
                        b"\x89PNG\r\n\x1a\n" + bytes([ordinal]) * 90
                    )
                if wrapped_title and ordinal == 1:
                    xhtml = xhtml.replace(
                        "<h1>合成章节</h1>",
                        '<h1>第一章</h1>'
                        '<div class="newCopyRightTitleWrapper">'
                        '<h1 class="newCopyRightTitle">第一章</h1></div>',
                    )
                if second_title and ordinal == 1:
                    xhtml = xhtml.replace(
                        "<h1>合成章节</h1>",
                        '<h1>第一章</h1>'
                        '<h2 class="secondTitle" id="heading_id_2">第一章</h2>'
                    )
                files["OEBPS/c1.xhtml"] = xhtml.encode()
                with ZipFile(source, "w") as dest:
                    for name, data in files.items():
                        dest.writestr(name, data)
                with closing(sqlite3.connect(db)) as conn:
                    conn.execute(
                        "UPDATE chapters SET artifact_sha256=? WHERE ordinal=?",
                        (hashlib.sha256(source.read_bytes()).hexdigest(), ordinal),
                    )
                    conn.commit()
        compiled = book / "final" / "book.epub"
        res = assemble_book(db_path=db, catalog_path=cat,
                            output=compiled, inspector=app.inspect_epub)
        self.assertEqual(res["status"], "BOOK_EPUB_READY_COMPLETENESS_UNVERIFIED")
        if wrapped_title or second_title:
            self.rewrite_epub(compiled, {
                "OEBPS/text/chapter_0001.xhtml":
                lambda raw: raw.replace(b"<h1>\xe7\xac\xac\xe4\xb8\x80\xe7\xab\xa0</h1>", b"", 1)
            })
        return book, compiled

    @staticmethod
    def rewrite_epub(path, transforms=None, *, drop=None):
        transforms = transforms or {}
        with ZipFile(path) as z:
            items = [(info, z.read(info.filename)) for info in z.infolist()]
        staged = path.with_name(path.name + ".rewrite")
        with ZipFile(staged, "w") as out:
            for info, raw in items:
                if info.filename == drop:
                    continue
                changed = transforms.get(info.filename)
                out.writestr(info, changed(raw) if changed else raw)
        staged.replace(path)

    @staticmethod
    def changed_member(path, match, fn):
        with ZipFile(path) as z:
            member = next(x for x in z.namelist() if match(x))
        CachedSourceParityTests.rewrite_epub(path, {member: fn})

    @staticmethod
    def kinds(report):
        return set(report["issue_codes"])

    def test_full_text_image_caption_note_and_manifest_match(self):
        book, compiled = self.build_case()
        report = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertEqual(report["status"], PASS)
        self.assertEqual(report["chapters_text_exact"], 2)
        self.assertEqual(report["image_reference_pairs_checked"], 2)
        self.assertEqual(report["source_manifest_image_entries"], 2)
        self.assertEqual(report["compiled_manifest_image_entries"], 2)
        self.assertEqual(report["unique_source_image_hashes"], 2)
        self.assertEqual(report["issue_count"], 0)
        self.assertFalse(report["full_book_confirmed"])
        self.assertNotIn("合成正文", str(report))

    def test_wrapped_source_heading_is_removed_only_when_proven(self):
        book, compiled = self.build_case(with_images=False, wrapped_title=True)
        result = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertEqual(result["status"], PASS)
        self.assertEqual(result["source_proven_generated_h1_removed"], 1)

    def test_second_title_h2_requires_explicit_v4_heading_policy(self):
        book, compiled = self.build_case(with_images=False, second_title=True)
        legacy = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertEqual(legacy["status"], INCOMPLETE)
        self.assertIn("BODY_TEXT_MISMATCH", self.kinds(legacy))
        upgraded = verify_cached_source(
            book, compiled, inspector=app.inspect_epub, heading_policy="v4")
        self.assertEqual(upgraded["status"], PASS)
        self.assertEqual(upgraded["source_proven_generated_h1_removed"], 1)
        self.assertEqual(upgraded["chapters_text_exact"], 2)
        self.assertFalse(upgraded["full_book_confirmed"])

    def test_unknown_heading_policy_fails_closed(self):
        book, compiled = self.build_case(with_images=False)
        with self.assertRaisesRegex(ValueError, "UNKNOWN_HEADING_POLICY"):
            verify_cached_source(book, compiled, inspector=app.inspect_epub,
                                 heading_policy="unsafe")

    def test_character_change_is_detected(self):
        book, compiled = self.build_case()
        self.changed_member(compiled, lambda n: n.endswith("chapter_0002.xhtml"),
                            lambda b: b.replace("合成文字".encode(), "错误文字".encode(), 1))
        report = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertEqual(report["status"], INCOMPLETE)
        self.assertIn("BODY_TEXT_MISMATCH", self.kinds(report))

    def test_figure_caption_change_is_detected(self):
        book, compiled = self.build_case()
        self.changed_member(compiled, lambda n: n.endswith("chapter_0001.xhtml"),
                            lambda b: b.replace("图注说明1".encode(), "错误说明1".encode(), 1))
        report = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertIn("BODY_TEXT_MISMATCH", self.kinds(report))

    def test_image_alt_change_is_detected(self):
        book, compiled = self.build_case()
        self.changed_member(compiled, lambda n: n.endswith("chapter_0001.xhtml"),
                            lambda b: b.replace('alt="图注1"'.encode(),
                                                'alt="换了描述"'.encode(), 1))
        report = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertIn("IMAGE_ALT_MISMATCH", self.kinds(report))

    def test_missing_image_reference_is_detected(self):
        book, compiled = self.build_case()
        self.changed_member(compiled, lambda n: n.endswith("chapter_0001.xhtml"),
                            lambda b: re.sub(rb"<img\b[^>]*?/>", b"", b, count=1))
        report = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertIn("IMAGE_REFERENCE_COUNT_MISMATCH", self.kinds(report))

    def test_image_bytes_change_is_detected(self):
        book, compiled = self.build_case()
        self.changed_member(compiled, lambda n: "/0001/" in n and n.endswith(".png"),
                            lambda b: b[:-1] + b"X")
        report = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertIn("IMAGE_CONTENT_MISMATCH", self.kinds(report))
        self.assertIn("IMAGE_MANIFEST_HASH_MULTISET_MISMATCH", self.kinds(report))

    def test_missing_manifest_asset_is_detected(self):
        book, compiled = self.build_case()
        with ZipFile(compiled) as z:
            member = next(x for x in z.namelist()
                          if x.endswith(".png") and "/assets/" in x)
        self.rewrite_epub(compiled, drop=member)
        report = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertIn("COMPILED_IMAGE_MANIFEST_MISSING", self.kinds(report))
        self.assertIn("IMAGE_REFERENCE_UNRESOLVED", self.kinds(report))

    def test_wrong_chapter_spine_order_is_detected(self):
        book, compiled = self.build_case(with_images=False)
        self.changed_member(compiled, lambda n: n.endswith("content.opf"),
                            lambda b: re.sub(
                                rb'(<itemref idref="ch1"/>)(\s*)(<itemref idref="ch2"/>)',
                                lambda m: m.group(3) + m.group(2) + m.group(1),
                                b, count=1))
        report = verify_cached_source(book, compiled, inspector=app.inspect_epub)
        self.assertIn("SPINE_ORDER_MISMATCH", self.kinds(report))

    def test_source_checkpoint_hash_change_fails_closed(self):
        book, compiled = self.build_case(with_images=False)
        source = book / "chapters" / "0001.epub"
        source.write_bytes(source.read_bytes() + b"tampered")
        with self.assertRaisesRegex(ValueError, "CHAPTER_ARTIFACT_SHA_MISMATCH"):
            verify_cached_source(book, compiled, inspector=app.inspect_epub)


if __name__ == "__main__":
    unittest.main()
