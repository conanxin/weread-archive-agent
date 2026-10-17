"""Synthetic, fully offline regression of fourth-book chapter risk preflight."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from zipfile import ZipFile

from test_chapter_worker import FixtureProvider, fixture_workspace, run
from tools.preassembly_risk_audit import (
    audit_epub, audit_book, image_dimensions,
)


def faux_png(w=720, h=436):
    return (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" +
            w.to_bytes(4, "big") + h.to_bytes(4, "big"))


def faux_jpeg(w=630, h=456):
    sof=(b"\x00\x11" + b"\x08" + h.to_bytes(2, "big") + w.to_bytes(2, "big") +
         b"\x03" + b"\x01\x11\x00\x02\x11\x00\x03\x11\x00")
    return b"\xff\xd8\xff\xc0" + sof + b"\xff\xd9"


def make_chapter(path, body, images=None):
    images=images or {}
    opf=(
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata/><manifest><item id="ch1" href="text/c.xhtml" media-type="application/xhtml+xml"/>'
        + "".join(
            f'<item id="img{i}" href="{name}" media-type="image/{("png" if name.endswith(".png") else "jpeg")}"/>'
            for i,name in enumerate(images,1)
        )+
        '</manifest><spine><itemref idref="ch1"/></spine></package>'
    )
    container=(
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles></container>'
    )
    with ZipFile(path,"w") as zipfile:
        zipfile.writestr("mimetype","application/epub+zip")
        zipfile.writestr("META-INF/container.xml",container)
        zipfile.writestr("OEBPS/content.opf",opf)
        zipfile.writestr("OEBPS/text/c.xhtml",f'<html><body>{body}</body></html>')
        for member,data in images.items():
            zipfile.writestr("OEBPS/"+member,data)


class PreassemblyRiskTests(unittest.TestCase):
    def fixture(self,body,images=None):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        target=Path(temp.name)/"sample.epub"
        make_chapter(target,body,images)
        return target

    def test_dimensions_png_jpeg_and_nonimage(self):
        self.assertEqual(image_dimensions(faux_png()),(720,436))
        self.assertEqual(image_dimensions(faux_jpeg()),(630,456))
        self.assertIsNone(image_dimensions(b"invalid"))

    def test_provider_short_text_is_review_flag_not_false_pass(self):
        f=self.fixture("<h1>小节</h1><p>文字</p>")
        value=audit_epub(f,ordinal=1,provider_words=600)
        self.assertIn("TEXT_BELOW_PROVIDER_ESTIMATE",value["risk_codes"])
        self.assertEqual(value["large_unreferenced_images"],0)

    def test_unreferenced_route_jpeg_with_png_placeholder_detected(self):
        f=self.fixture(
            '<h1>第一章</h1><img src="../images/placeholder.png"/>',
            {"images/placeholder.png":faux_png(),
             "images/map.jpg":faux_jpeg()}
        )
        out=audit_epub(f,ordinal=4,provider_words=50)
        self.assertIn("UNREFERENCED_LARGE_IMAGE",out["risk_codes"])
        self.assertEqual(out["large_unreferenced_images"],1)

    def test_linked_map_with_orphan_legacy_placeholder_does_not_warn(self):
        f=self.fixture(
            '<h1>第一章</h1><p>文字信息</p><img src="../images/map.jpg"/>',
            {"images/map.jpg":faux_jpeg(),
             "images/old-placeholder.png":faux_png()}
        )
        out=audit_epub(f,ordinal=4,provider_words=4)
        self.assertNotIn("UNREFERENCED_LARGE_IMAGE",out["risk_codes"])

    def test_duplicate_unlinked_image_bytes_does_not_invent_missing_map(self):
        jpg=faux_jpeg()
        f=self.fixture(
            '<h1>照片</h1><img src="../images/used.jpg"/>',
            {"images/used.jpg":jpg,"images/duplicate.jpg":jpg}
        )
        out=audit_epub(f,ordinal=2,provider_words=2)
        self.assertEqual(out["large_unreferenced_images"],0)

    def test_partial_queue_check_uses_individual_frozen_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            book,cat,db,cookie=fixture_workspace(Path(tmp))
            r=run(FixtureProvider(),cat,db,cookie,limit=1)
            self.assertEqual(r["complete"],1)
            result=audit_book(book)
            self.assertEqual(result["chapters_checked"],1)
            self.assertEqual(result["chapters_not_complete"],1)
            self.assertEqual(result["status"],"PREASSEMBLY_PARTIAL_QUEUE")
            with closing(sqlite3.connect(db)) as con:
                self.assertEqual(con.execute("SELECT count(*) FROM chapters WHERE state='COMPLETE'").fetchone()[0],1)

    def test_completed_queue_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            book,cat,db,cookie=fixture_workspace(Path(tmp))
            run(FixtureProvider(),cat,db,cookie,limit=1)
            src=book/"chapters"/"0001.epub"
            src.write_bytes(src.read_bytes()+b"tamper")
            with self.assertRaisesRegex(ValueError,"CHAPTER_ARTIFACT_SHA_MISMATCH"):
                audit_book(book)


if __name__=="__main__":
    unittest.main()
