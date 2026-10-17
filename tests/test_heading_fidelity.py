"""Synthetic regression for provenance-gated duplicate heading audit."""
from pathlib import Path
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile

import wereadlab as app
from test_chapter_worker import FixtureProvider, fixture_workspace, run
from tools.book_assembly import assemble_book
from tools.heading_fidelity import dedupe_one_chapter, audit_and_build


class HeadingTransformTests(unittest.TestCase):
    def test_immediate_duplicate_generated_heading_only(self):
        source=(
            '<html><head><title>mock</title></head><body>\n'
            '  <h1>章节　标题</h1>\n'
            '  <h1 class="source">章节 标题</h1>'
            '  <p>保留的正文。</p><img src="images/sample.png"/></body></html>'
        )
        fixed, changed=dedupe_one_chapter(source,catalog_title="章节 标题")
        self.assertTrue(changed)
        self.assertNotIn('<h1>章节　标题</h1>',fixed)
        self.assertIn('<h1 class="source">章节 标题</h1>',fixed)
        self.assertIn("保留的正文。",fixed)
        self.assertIn('src="images/sample.png"',fixed)
        self.assertEqual(source.replace('<h1>章节　标题</h1>','',1),fixed)

    def test_wrapped_copyright_title_only_removes_generated_h1(self):
        source=(
            '<html><body>\n<h1>合成版权页</h1>\n'
            '<div class="newCopyRightTitleWrapper">'
            '<h1 class="newCopyRightTitle">合成版权页</h1></div>'
            '<p>保留出版资料。</p></body></html>'
        )
        fixed,changed=dedupe_one_chapter(source,catalog_title="合成版权页")
        self.assertTrue(changed)
        self.assertEqual(fixed,source.replace("<h1>合成版权页</h1>","",1))
        self.assertIn('<h1 class="newCopyRightTitle">合成版权页</h1>',fixed)
        self.assertIn("保留出版资料",fixed)

    def test_wrapped_copyright_fails_closed_without_exact_provenance(self):
        pairs=[
            ("newOtherTitle","newCopyRightTitle","合成版权页"),
            ("newCopyRightTitleWrapper","wrongClass","合成版权页"),
            ("newCopyRightTitleWrapper","newCopyRightTitle","另一个标题"),
        ]
        for wrapper,cls,body_title in pairs:
            with self.subTest(wrapper=wrapper,cls=cls,body_title=body_title):
                source=(
                    '<body><h1>合成版权页</h1>'
                    f'<div class="{wrapper}"><h1 class="{cls}">{body_title}</h1></div>'
                    '<p>不要改动</p></body>'
                )
                self.assertEqual(dedupe_one_chapter(source,catalog_title="合成版权页"),
                                 (source,False))

    def test_second_title_h2_is_proven_only_in_v4(self):
        source=(
            '<html><body>\n<h1>第二节</h1>\n'
            '<h2 class="secondTitle" id="heading_id_2">第二节</h2>'
            '<p>保留原文与注释。</p></body></html>'
        )
        self.assertEqual(dedupe_one_chapter(source,catalog_title="第二节"),
                         (source,False))
        fixed,changed=dedupe_one_chapter(
            source,catalog_title="第二节",include_source_h2=True
        )
        self.assertTrue(changed)
        self.assertEqual(fixed,source.replace("<h1>第二节</h1>","",1))
        self.assertIn('<h2 class="secondTitle" id="heading_id_2">第二节</h2>',fixed)
        self.assertIn("保留原文与注释",fixed)

    def test_city_txtheading_h2_needs_explicit_v5_policy(self):
        source=(
            '<body><h1>第一节</h1>'
            '<h2 class="txtheading-1-15" id="pre3_3_1_2">第一节</h2>'
            '<p>合成运河城市正文。</p></body>'
        )
        self.assertEqual(
            dedupe_one_chapter(source,catalog_title="第一节",include_source_h2=True),
            (source,False)
        )
        fixed,changed=dedupe_one_chapter(
            source,catalog_title="第一节",include_source_h2=True,
            include_city_h2=True
        )
        self.assertTrue(changed)
        self.assertEqual(fixed,source.replace("<h1>第一节</h1>","",1))
        self.assertIn('class="txtheading-1-15"',fixed)
        self.assertIn("合成运河城市正文",fixed)

    def test_city_h2_different_title_class_or_intervening_content_refused(self):
        invalid=[
            '<h2 class="other-heading" id="c1">第一节</h2>',
            '<h2 class="txtheading-1-15">第一节</h2>',
            '<h2 class="txtheading-1-15" id="c1">第二节</h2>',
            '<img src="genuine.jpg"/><h2 class="txtheading-1-15" id="c1">第一节</h2>',
        ]
        for suffix in invalid:
            raw='<body><h1>第一节</h1>'+suffix+'</body>'
            with self.subTest(suffix=suffix[:45]):
                self.assertEqual(dedupe_one_chapter(
                    raw,catalog_title="第一节",include_source_h2=True,
                    include_city_h2=True),(raw,False))

    def test_v6_secondtitle_dash_one_h2_strict_generated_h1_removal(self):
        source=(
            '<body><h1>遗迹考察</h1>'
            '<h2 class="secondTitle-1">遗迹考察</h2>'
            '<p>合成学术考察正文与照片说明。</p></body>'
        )
        for previous in [
            {},
            {"include_source_h2":True},
            {"include_source_h2":True,"include_city_h2":True},
        ]:
            with self.subTest(previous=previous):
                self.assertEqual(
                    dedupe_one_chapter(source,catalog_title="遗迹考察",**previous),
                    (source,False))
        amended,changed=dedupe_one_chapter(
            source,catalog_title="遗迹考察",include_source_h2=True,
            include_city_h2=True,include_dash_one_h2=True)
        self.assertTrue(changed)
        self.assertEqual(amended,source.replace("<h1>遗迹考察</h1>","",1))
        self.assertIn('class="secondTitle-1"',amended)
        self.assertIn("合成学术考察正文与照片说明。",amended)

    def test_v6_dash_one_h2_does_not_remove_unverified_source(self):
        invalid=[
            '<h2 class="secondTitle-2">遗迹考察</h2>',
            '<h2 class="secondTitle-1" id="extra">遗迹考察</h2>',
            '<h2 class="secondTitle-1">另一个标题</h2>',
            '<p>真实内容</p><h2 class="secondTitle-1">遗迹考察</h2>',
            '<img src="true-figure.jpg"/><h2 class="secondTitle-1">遗迹考察</h2>'
        ]
        for original in invalid:
            raw='<body><h1>遗迹考察</h1>'+original+'</body>'
            with self.subTest(original=original[:50]):
                self.assertEqual(dedupe_one_chapter(
                    raw,catalog_title="遗迹考察",include_source_h2=True,
                    include_city_h2=True,include_dash_one_h2=True),(raw,False))

    def test_v7_requires_explicit_no_id_secondtitle_policy(self):
        source = (
            '<body><h1>第二节</h1>'
            '<h2 class="secondTitle">第二节</h2>'
            '<p>正文〔注：一〕。</p></body>'
        )
        self.assertEqual(dedupe_one_chapter(
            source, catalog_title="第二节", include_source_h2=True,
            include_city_h2=True, include_dash_one_h2=True), (source, False))
        result, changed = dedupe_one_chapter(
            source, catalog_title="第二节", include_source_h2=True,
            include_city_h2=True, include_dash_one_h2=True,
            include_no_id_h2=True)
        self.assertTrue(changed)
        self.assertEqual(result, source.replace("<h1>第二节</h1>", "", 1))
        self.assertIn("正文〔注：一〕", result)

    def test_v7_no_id_secondtitle_refuses_unproven_sources(self):
        invalid = [
            '<h2 class="secondTitle" id="real">第二节</h2>',
            '<h2 class="secondTitle-1">第二节</h2>',
            '<h2 class="secondTitle other">第二节</h2>',
            '<h2 class="secondTitle">另一节</h2>',
            '<p>真正正文</p><h2 class="secondTitle">第二节</h2>',
            '<img src="genuine-photo.jpg"/><h2 class="secondTitle">第二节</h2>',
        ]
        for fragment in invalid:
            source = '<body><h1>第二节</h1>' + fragment + '</body>'
            with self.subTest(fragment=fragment):
                self.assertEqual(dedupe_one_chapter(
                    source, catalog_title="第二节", include_no_id_h2=True),
                    (source, False))
        source = '<body><h1 class="genuine">第二节</h1><h2 class="secondTitle">第二节</h2></body>'
        self.assertEqual(dedupe_one_chapter(
            source, catalog_title="第二节", include_no_id_h2=True), (source, False))

    def test_untrusted_h2_or_different_catalog_stays_unchanged(self):
        variations=[
            '<h2 class="anotherTitle" id="bw1">第二节</h2>',
            '<h2 class="secondTitle">第二节</h2>',
            '<h2 class="secondTitle" id="bw1">第三节</h2>',
            '<p>有内容隔断</p><h2 class="secondTitle" id="bw1">第二节</h2>',
        ]
        for text in variations:
            source='<body><h1>第二节</h1>'+text+'</body>'
            with self.subTest(shape=text[:30]):
                self.assertEqual(
                    dedupe_one_chapter(source,catalog_title="第二节",include_source_h2=True),
                    (source,False)
                )

    def test_difference_or_intervening_content_is_not_removed(self):
        variants=[
            '<body><h1>第一节</h1><p>有字</p><h1>第一节</h1></body>',
            '<body><h1>第一节</h1><img src="x"/><h1>第一节</h1></body>',
            '<body><h1 class="source">第一节</h1><h1>第一节</h1></body>',
            '<body><h1>第一节</h1><h1>其它</h1></body>',
            '<body><h1>第一节</h1><h1>第一节</h1></body>',
        ]
        for i,source in enumerate(variants):
            with self.subTest(i=i):
                title="不是第一节" if i==4 else "第一节"
                self.assertEqual(dedupe_one_chapter(source,catalog_title=title),
                                 (source,False))


class VersionedBuildTests(unittest.TestCase):
    def setup_book(self,root: Path):
        folder,cat,db,cookie=fixture_workspace(root)
        provider=FixtureProvider()
        self.assertEqual(run(provider,cat,db,cookie,limit=2)["complete"],2)
        output=folder/"final"/"book.epub"
        result=assemble_book(db_path=db,catalog_path=cat,output=output,
                             inspector=app.inspect_epub)
        self.assertEqual(result["chapter_count"],2)
        # Fake extra generated heading in assembled EPUB, but not in individual
        # source EPUBs; 100% private and synthetic, demonstrating immutability.
        temp=output.with_suffix(".tmp")
        with zipfile.ZipFile(output) as source, zipfile.ZipFile(temp,"w") as rewritten:
            for info in source.infolist():
                data=source.read(info.filename)
                if info.filename=="OEBPS/text/chapter_0001.xhtml":
                    data=data.replace(
                        b"<h1>\xe5\x90\x88\xe6\x88\x90\xe7\xab\xa0\xe8\x8a\x82</h1>",
                        "<h1>第一章</h1>\n<h1>第一章</h1>".encode("utf-8")
                    )
                rewritten.writestr(info,data)
        os.replace(temp,output)
        assert app.inspect_epub(output,expected=2)["status"]=="STRUCTURE_PASS_COMPLETENESS_UNVERIFIED"
        qa={"epub_chapters":2,"artifacts":{"book.epub":{
             "sha256":hashlib.sha256(output.read_bytes()).hexdigest()
        }}}
        (folder/"final"/"fullbook_QA_report.json").write_text(
            json.dumps(qa),encoding="utf8"
        )
        return folder, output

    def test_read_only_audit_and_versioned_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            folder,source=self.setup_book(Path(td))
            original=hashlib.sha256(source.read_bytes()).hexdigest()
            dry=audit_and_build(book_dir=folder,inspector=app.inspect_epub)
            self.assertEqual(dry["status"],"H1_AUDIT_READY")
            self.assertEqual(dry["deduplicated_ordinals"],[1])
            self.assertFalse((folder/"final/v2-headings/book.epub").exists())
            result=audit_and_build(
                book_dir=folder,inspector=app.inspect_epub,build_versioned=True
            )
            self.assertEqual(result["status"],
                             "H1_VERSIONED_CANDIDATE_READY_FIDELITY_UNVERIFIED")
            self.assertEqual(result["deduplicated_count"],1)
            self.assertEqual(result["spine_chapters"],2)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),original)
            new=folder/"final/v2-headings/book.epub"
            self.assertTrue(new.is_file())
            with zipfile.ZipFile(source) as old,zipfile.ZipFile(new) as versioned:
                for filename in old.namelist():
                    if filename!="OEBPS/text/chapter_0001.xhtml":
                        self.assertEqual(old.read(filename),versioned.read(filename))
                self.assertIn("<h1>第一章</h1>".encode("utf-8"),
                    versioned.read("OEBPS/text/chapter_0001.xhtml"))
            self.assertTrue((folder/"final/v2-headings/headings_qa.json").exists())
            with self.assertRaisesRegex(FileExistsError,"VERSIONED_OUTPUT_ALREADY_EXISTS"):
                audit_and_build(book_dir=folder,inspector=app.inspect_epub,
                                build_versioned=True)

    def test_v7_versioned_epub_removes_only_source_proven_no_id_h2(self):
        with tempfile.TemporaryDirectory() as td:
            folder, original = self.setup_book(Path(td))
            before = "<h1>第一章</h1>\n<h1>第一章</h1>".encode("utf-8")
            replacement = "<h1>第一章</h1>\n<h2 class=\"secondTitle\">第一章</h2>".encode("utf-8")
            staged = original.with_suffix(".replace")
            with zipfile.ZipFile(original) as z, zipfile.ZipFile(staged, "w") as out:
                for item in z.infolist():
                    data = z.read(item.filename)
                    if item.filename == "OEBPS/text/chapter_0001.xhtml":
                        self.assertIn(before, data)
                        data = data.replace(before, replacement, 1)
                    out.writestr(item, data)
            os.replace(staged, original)
            baseline = hashlib.sha256(original.read_bytes()).hexdigest()
            qa = folder / "final" / "fullbook_QA_report.json"
            metadata = json.loads(qa.read_text(encoding="utf-8"))
            metadata["artifacts"]["book.epub"]["sha256"] = baseline
            qa.write_text(json.dumps(metadata), encoding="utf-8")
            v6 = audit_and_build(book_dir=folder, inspector=app.inspect_epub,
                                 target_version="v6-headings")
            self.assertEqual(v6["deduplicated_count"], 0)
            result = audit_and_build(book_dir=folder, inspector=app.inspect_epub,
                                     build_versioned=True, target_version="v7-headings")
            self.assertEqual(result["deduplicated_ordinals"], [1])
            output = folder / "final" / "v7-headings" / "book.epub"
            self.assertTrue(output.is_file())
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), baseline)
            with zipfile.ZipFile(original) as z, zipfile.ZipFile(output) as out:
                source = z.read("OEBPS/text/chapter_0001.xhtml")
                candidate = out.read("OEBPS/text/chapter_0001.xhtml")
                self.assertEqual(candidate, source.replace("<h1>第一章</h1>".encode(), b"", 1))
                self.assertIn('class="secondTitle"'.encode(), candidate)

    def test_v3_versioned_output_keeps_existing_v2_and_original(self):
        with tempfile.TemporaryDirectory() as td:
            folder,original=self.setup_book(Path(td))
            result_v2=audit_and_build(
                book_dir=folder,inspector=app.inspect_epub,
                build_versioned=True,target_version="v2-headings"
            )
            v2=folder/"final/v2-headings/book.epub"
            v2_sha=hashlib.sha256(v2.read_bytes()).hexdigest()
            original_sha=hashlib.sha256(original.read_bytes()).hexdigest()
            result_v3=audit_and_build(
                book_dir=folder,inspector=app.inspect_epub,
                build_versioned=True,target_version="v3-headings"
            )
            v3=folder/"final/v3-headings/book.epub"
            self.assertEqual(result_v3["spine_chapters"],2)
            self.assertTrue(v3.is_file())
            self.assertEqual(hashlib.sha256(v2.read_bytes()).hexdigest(),v2_sha)
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(),original_sha)
            self.assertEqual(result_v3["epub_sha256"],hashlib.sha256(v3.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError,"UNKNOWN_VERSIONED_OUTPUT"):
                audit_and_build(book_dir=folder,inspector=app.inspect_epub,
                                target_version="../unsafe")

    def test_modified_source_book_hash_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            folder,source=self.setup_book(Path(td))
            source.write_bytes(b"invalid")
            with self.assertRaisesRegex(ValueError,"ORIGINAL_EPUB_SHA_MISMATCH"):
                audit_and_build(book_dir=folder,inspector=app.inspect_epub,
                                build_versioned=True)
            self.assertFalse((folder/"final/v2-headings/book.epub").exists())


if __name__=="__main__":
    unittest.main()
