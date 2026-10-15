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
                self.assertIn(b"<h1>\\xe7\\xac\\xac\\xe4\\xb8\\x80\\xe7\\xab\\xa0</h1>",
                    versioned.read("OEBPS/text/chapter_0001.xhtml"))
            self.assertTrue((folder/"final/v2-headings/headings_qa.json").exists())
            with self.assertRaisesRegex(FileExistsError,"VERSIONED_OUTPUT_ALREADY_EXISTS"):
                audit_and_build(book_dir=folder,inspector=app.inspect_epub,
                                build_versioned=True)

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
