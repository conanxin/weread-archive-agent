import base64
import io
import json
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest import mock
import zipfile

import wereadlab as app
from tools.check_upstreams import changed_heads
from tools.repair_epub_images import repair_epub_images, _safe_image_url


def make_book(target: Path, *, broken=False, words='第一章 这是测试文字、用于构造一份完全合成的电子书。', extra_images=''):
    doc = f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>测试章节</h1><p>{words}</p><img src="images/a.jpg"/>{extra_images}</body></html>'
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

    def test_placeholder_reader_link_reports_next_step(self):
        for value in ("微信读书实际阅读器URL",
                      "https://weread.qq.com/web/reader/这里替换成真实ID"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "占位符"):
                app.reader_id(value)

        stream = io.StringIO()
        with redirect_stdout(stream):
            rc = app.main(["export", "微信读书实际阅读器URL", "--json"])
        self.assertEqual(rc, 2)
        response = json.loads(stream.getvalue())
        self.assertEqual(response["status"], "INVALID_URL")
        self.assertIn("start.cmd", response["action"])

    def test_valid_epub_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            book = root / 'good.epub'
            make_book(book)
            report = app.inspect_epub(book, expected=1)
            self.assertEqual(report['status'], 'STRUCTURE_PASS_COMPLETENESS_UNVERIFIED')
            self.assertEqual(report['image_references'], 1)
            self.assertEqual(report['chapter_summaries'][0]['heading'], '测试章节')
            self.assertGreater(report['chapter_summaries'][0]['text_characters'], 0)
            converted = app.markdown_from_epub(book, root / 'md', include_text=True)
            text = Path(converted['md']).read_text(encoding='utf-8')
            self.assertIn('这是测试文字', text)
            self.assertIn('![image](images/0001.jpg)', text)
            self.assertEqual(converted['images'], 1)
            self.assertTrue((root / 'md/images/0001.jpg').exists())
            self.assertTrue(Path(converted['txt']).exists())

    def test_markdown_ignores_xhtml_head_and_scripts(self):
        html = (
            '<html><head><title>页面内部标题</title>'
            '<style>.a{color:red;}秘密样式文字</style>'
            '</head><body><h1>正文章节</h1>'
            '<p>第一段文字。</p><script>秘密脚本代码</script>'
            '<p>最后一段。</p></body></html>'
        )
        writer = app.MarkdownWriter("OEBPS/text/chapter.xhtml", set(), {})
        writer.feed(html)
        rendered = "".join(writer.parts)
        self.assertIn("正文章节", rendered)
        self.assertIn("第一段文字。", rendered)
        self.assertIn("最后一段。", rendered)
        self.assertNotIn("页面内部标题", rendered)
        self.assertNotIn("秘密样式文字", rendered)
        self.assertNotIn("秘密脚本代码", rendered)

    def test_markdown_body_only_with_realistic_duplicate_title(self):
        html = (
            '<html><head><meta charset="utf-8"/><title>版权信息</title></head>'
            '<body><h1>版权信息</h1><p>合成版权信息。</p></body></html>'
        )
        writer = app.MarkdownWriter("OEBPS/text/chapter.xhtml", set(), {})
        writer.feed(html)
        rendered = "".join(writer.parts)
        self.assertEqual(rendered.count("版权信息"), 2)
        self.assertEqual(rendered.count("合成版权信息。"), 1)

    def test_inspect_cli_is_offline_and_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / 'demo.epub'
            make_book(book)
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = app.main(['inspect', str(book), '--json'])
            self.assertEqual(code, 0)
            result = json.loads(stream.getvalue())
            self.assertEqual(result['status'], 'STRUCTURE_PASS_COMPLETENESS_UNVERIFIED')
            self.assertEqual(result['validation']['spine_chapters'], 1)
            self.assertEqual(result['validation']['chapter_summaries'][0]['heading'], '测试章节')

    def test_offset_sample_uses_distinct_file_and_skip_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cookie = home / 'cookies.txt'
            cookie.write_text('dummy, not real credentials', encoding='utf-8')
            commands = []
            def fake_run(argv, **kwargs):
                commands.append(argv)
                output = Path(argv[argv.index('--output') + 1])
                make_book(output)
                return app.subprocess.CompletedProcess(argv, 0, 'ok', '')
            with mock.patch.object(app, 'COOKIE', cookie), \
                 mock.patch.object(app, 'LIBRARY', home / 'library'), \
                 mock.patch.object(app, 'ensure_upstream', return_value=home / 'fetch.py'), \
                 mock.patch.object(app, 'git_commit', return_value='test-sha'), \
                 mock.patch.object(app, 'run', side_effect=fake_run):
                args = app.argparse.Namespace(url='https://weread.qq.com/web/reader/fixture',
                    output_dir=None, sample=1, full=False, skip=4,
                    format=['epub'], force=False, sleep=0.4, expected_chapters=None)
                result = app.export_book(args)
                self.assertEqual(result['status'], 'FILES_READY_COMPLETENESS_UNVERIFIED')
                self.assertEqual(result['skipped_chapters'], 4)
                self.assertTrue((home/'library'/'fixture'/'sample-1-skip-4.epub').is_file())
                self.assertIn('--skip', commands[0])
                self.assertEqual(commands[0][commands[0].index('--skip') + 1], '4')

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

    def test_repair_missing_note_and_dedupe_remote_cdn_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            url = 'https://res.weread.qq.com/wrepub/fixture001.jpg'
            extra = ('<img src="Images/note.png"/>' * 3
                     + f'<img src="{url}"/>' * 2)
            source = folder / 'partial.epub'
            dest = folder / 'repaired.epub'
            make_book(source, extra_images=extra)
            prior = app.inspect_epub(source)
            self.assertEqual(prior['status'], 'STRUCTURE_INCOMPLETE')
            self.assertEqual(prior['broken_image_references'], 3)
            self.assertEqual(prior['broken_images'], ['OEBPS/Images/note.png'])
            self.assertEqual(prior['remote_image_references'], 2)
            self.assertEqual(prior['remote_images'], [url])
            calls = []
            png = base64.b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+8r70AAAAASUVORK5CYII=')
            def fake_download(image_url):
                calls.append(image_url)
                return png, '.png', 'image/png'
            report = repair_epub_images(source, dest, downloader=fake_download)
            self.assertEqual(calls, [url])
            self.assertEqual(report['note_markers_substituted'], 3)
            self.assertEqual(report['downloaded_unique_images'], 1)
            self.assertEqual(report['remote_image_references'], 2)
            self.assertEqual(report['download_failure_count'], 0)
            validation = app.inspect_epub(dest)
            self.assertEqual(validation['status'], 'STRUCTURE_PASS_COMPLETENESS_UNVERIFIED')
            self.assertEqual(validation['remote_images'], [])
            self.assertEqual(validation['broken_images'], [])
            with zipfile.ZipFile(dest) as z:
                self.assertTrue(any(n.startswith('OEBPS/images/wr_') for n in z.namelist()))
                chapter = z.read('OEBPS/c1.xhtml').decode('utf-8')
                self.assertEqual(chapter.count('〔注〕'), 3)
                self.assertNotIn('res.weread.qq.com', chapter)
            self.assertEqual(source.exists(), True)

    def test_cdn_redirect_allowlist_and_annotation_not_truncated(self):
        redirected = 'https://wrco-40036.sh.gfp.tencent-cloud.com/path/photo.jpg'
        self.assertFalse(_safe_image_url(redirected))
        self.assertTrue(_safe_image_url(redirected, redirected=True))
        self.assertFalse(_safe_image_url('https://gfp.tencent-cloud.com.evil.example/test',
                                         redirected=True))
        self.assertTrue(_safe_image_url('https://res.weread.qq.com/wrepub/x.jpg'))
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp)/'source.epub', Path(tmp)/'repaired.epub'
            detailed_annotation = '对古代运河研究的长注释文字' * 35
            make_book(source, extra_images='<img src="Images/note.png" alt="' +
                      detailed_annotation + '"/>')
            report = repair_epub_images(source, dest, downloader=lambda _: self.fail('unexpected network'))
            self.assertEqual(report['note_markers_substituted'], 1)
            self.assertEqual(app.inspect_epub(dest)['status'], 'STRUCTURE_PASS_COMPLETENESS_UNVERIFIED')
            with zipfile.ZipFile(dest) as z:
                chapter = z.read('OEBPS/c1.xhtml').decode('utf-8')
            self.assertIn(detailed_annotation, chapter)
            self.assertIn('〔注：', chapter)

    def test_repair_failure_preserves_unresolved_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            url = 'https://res.weread.qq.com/wrepub/unavailable.jpg'
            source, dest = folder / 'source.epub', folder / 'output.epub'
            make_book(source, extra_images=f'<img src="{url}"/>')
            def fail(_url):
                raise ValueError('fixture image unavailable')
            report = repair_epub_images(source, dest, downloader=fail)
            self.assertEqual(report['download_failure_count'], 1)
            self.assertEqual(report['downloaded_unique_images'], 0)
            self.assertEqual(app.inspect_epub(dest)['status'], 'STRUCTURE_INCOMPLETE')
            self.assertTrue(source.is_file())

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