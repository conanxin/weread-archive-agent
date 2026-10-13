import json
import tempfile
from pathlib import Path
import unittest
from unittest import mock
import zipfile

import wereadlab as app
from tools.check_upstreams import changed_heads


def make_book(target: Path, *, broken=False, words='第一章 这是测试文字、用于构造一份完全合成的电子书。'):
    doc = f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>测试章节</h1><p>{words}</p><img src="images/a.jpg"/></body></html>'
    opf = '''<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>测试书</dc:title></metadata><manifest><item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/><item id="pic" href="images/a.jpg" media-type="image/jpeg"/></manifest><spine><itemref idref="c1"/></spine></package>'''
    container = '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
    with zipfile.ZipFile(target, 'w') as z:
        z.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', container)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/c1.xhtml', doc)
        if not broken:
            z.writestr('OEBPS/images/a.jpg', b'fake-jpg-for-offline-test')


class ValidationTests(unittest.TestCase):
    def test_weekly_watch_issue_deduplicates(self):
        pinned = {"repo/example": "aaaa"}
        current = {"repo/example": "1234567890"}
        plan = changed_heads(pinned, current, set())
        self.assertEqual(len(plan), 1)
        self.assertEqual(changed_heads(pinned, current, {plan[0][3]}), [])
        self.assertEqual(changed_heads(pinned, pinned, set()), [])

    def test_url_strictly_scoped(self):
        self.assertEqual(app.reader_id('https://weread.qq.com/web/reader/abc123'), 'abc123')
        for url in ['https://example.com/web/reader/abc', 'http://weread.qq.com/web/reader/a',
                    'https://weread.qq.com/web/bookDetail/abc',
                    'https://weread.qq.com.evil.test/web/reader/a',
                    'https://weread.qq.com/web/reader/../shelf']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                app.reader_id(url)

    def test_valid_epub_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / 'good.epub'
            make_book(book)
            report = app.inspect_epub(book, expected=1)
            self.assertEqual(report['status'], 'STRUCTURE_PASS_COMPLETENESS_UNVERIFIED')
            self.assertEqual(report['image_references'], 1)
            converted = app.markdown_from_epub(book, root / 'md', include_text=True)
            text = Path(converted['md']).read_text(encoding='utf-8')
            self.assertIn('这是测试文字', text)
            self.assertIn('![image](images/0001.jpg)', text)
            self.assertEqual(converted['images'], 1)
            self.assertTrue((root / 'md/images/0001.jpg').exists())
            self.assertTrue(Path(converted['txt']).exists())

    def test_missing_image_and_count_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'broken.epub'
            make_book(path, broken=True)
            report = app.inspect_epub(path)
            self.assertEqual(report['status'], 'STRUCTURE_INCOMPLETE')
            self.assertEqual(len(report['broken_images']), 1)
            complete = Path(tmp) / 'complete.epub'
            make_book(complete)
            self.assertEqual(app.inspect_epub(complete, expected=2)['status'], 'STRUCTURE_INCOMPLETE')

    def test_corrupt_epub_is_reported_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'oops.epub'
            f.write_bytes(b'garbage')
            self.assertEqual(app.inspect_epub(f)['status'], 'INVALID_EPUB')

    def test_no_login_produces_machine_readable_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with mock.patch.object(app, 'COOKIE', home / 'absent.cookies'), \
                 mock.patch.object(app, 'LIBRARY', home / 'library'):
                args = app.argparse.Namespace(url='https://weread.qq.com/web/reader/example',
                                              output_dir=None, sample=2, full=False,
                                              format=['epub'], force=False, sleep=0.4,
                                              expected_chapters=None)
                result = app.export_book(args)
                self.assertEqual(result['status'], 'LOGIN_REQUIRED')
                self.assertTrue((home / 'library/example/sample-2.report.json').is_file())

    def test_external_adapter_integration_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            cookie = folder / 'cookie'
            cookie.write_text('dummy, no network test', encoding='utf-8')
            def mock_run(argv, **kwargs):
                staged = Path(argv[argv.index('--output') + 1])
                make_book(staged)
                return app.subprocess.CompletedProcess(argv, 0, '{"ok":true,"chapters":1}', '')
            with mock.patch.object(app, 'COOKIE', cookie), \
                 mock.patch.object(app, 'LIBRARY', folder / 'library'), \
                 mock.patch.object(app, 'ensure_upstream', return_value=folder / 'fetch.py'), \
                 mock.patch.object(app, 'git_commit', return_value='fixture-sha'), \
                 mock.patch.object(app, 'run', side_effect=mock_run):
                args = app.argparse.Namespace(url='https://weread.qq.com/web/reader/example',
                                              output_dir=None, sample=1, full=False,
                                              format=['epub','md','txt'], force=False, sleep=0.4,
                                              expected_chapters=None)
                first = app.export_book(args)
                self.assertEqual(first['status'], 'FILES_READY_COMPLETENESS_UNVERIFIED')
                self.assertIn('md', first['artifacts'])
                second = app.export_book(args)
                self.assertEqual(second['status'], first['status'])
                self.assertEqual(first['upstream_sha'], 'fixture-sha')


if __name__ == '__main__':
    unittest.main()