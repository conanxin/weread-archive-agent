#!/usr/bin/env python3
"""WeRead Archive Agent: local, reproducible, agent-friendly ebook workflow.

This original orchestration code invokes optional upstream adapters as separate
programs; it does not vendor their implementation or store credentials in git.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import html
from html.parser import HTMLParser
import http.cookiejar
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from tools.repair_epub_images import repair_epub_images
from tools.catalog_snapshot import fetch_catalog, save_catalog
from tools.checkpoint_queue import init_queue, inspect_queue
from tools.chapter_worker import run_chapter_worker
from tools.book_assembly import assemble_book
from tools.source_parity_audit import audit_live as audit_source_parity, parse_checks as parse_source_checks

VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parent
HOME = Path(os.environ.get("WEREADLAB_HOME", str(ROOT / ".local"))).expanduser().resolve()
UPSTREAM_REPO = "https://github.com/finlater/weread.koplugin.git"
UPSTREAM = HOME / "upstream" / "weread.koplugin"
COOKIE = HOME / "session" / "weread.cookies.txt"
BROWSER = HOME / "session" / "chromium-profile"
LIBRARY = HOME / "library"


def result(status: str, **extra) -> dict:
    return {"status": status, "version": VERSION, **extra}


def emit(data: dict, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"[{data.get('status')}] " + json.dumps(
            {k: v for k, v in data.items() if k != 'version'}, ensure_ascii=False, indent=2))


def reader_id(url: str) -> str:
    value = url.strip()
    # Copyable documentation placeholders are not a real reader page.
    if value == "微信读书实际阅读器URL" or "这里替换成真实ID" in value or "实际阅读器ID" in value:
        raise ValueError("当前输入是文档示例占位符，不是真实书籍链接。请在微信读书网页版打开一本书的阅读页面，从浏览器地址栏复制完整 https://weread.qq.com/web/reader/... 链接")
    parts = urllib.parse.urlsplit(value)
    if parts.scheme != "https" or parts.hostname != "weread.qq.com" or parts.port is not None:
        raise ValueError("需要 https://weread.qq.com/web/reader/... 的真实阅读页面 URL")
    match = re.fullmatch(r"/web/reader/([A-Za-z0-9_-]+)", parts.path)
    if not match or parts.username or parts.password:
        raise ValueError("阅读器 URL 路径无效；请复制地址栏里的实际 /web/reader/... 链接")
    return match.group(1)


def run(argv: list[str], *, cwd: Path | None = None, capture: bool = True):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(argv, cwd=cwd, env=env, text=True, encoding="utf-8",
                          errors="replace", capture_output=capture, check=False)


def git_commit(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    proc = run(["git", "-C", str(path), "rev-parse", "HEAD"])
    return proc.stdout.strip() if proc.returncode == 0 else None


def ensure_upstream(*, update: bool = False) -> Path:
    if not shutil.which("git"):
        raise RuntimeError("未安装 Git。请先安装 https://git-scm.com/")
    if not UPSTREAM.exists():
        UPSTREAM.parent.mkdir(parents=True, exist_ok=True)
        proc = run(["git", "clone", "--depth", "1", UPSTREAM_REPO, str(UPSTREAM)])
        if proc.returncode:
            raise RuntimeError("获取 EPUB 适配器失败：" + proc.stderr[-500:])
    elif update:
        proc = run(["git", "-C", str(UPSTREAM), "pull", "--ff-only"])
        if proc.returncode:
            raise RuntimeError("上游更新失败：" + proc.stderr[-500:])
    script = UPSTREAM / "scripts" / "fetch_weread_epub.py"
    if not script.is_file():
        raise RuntimeError("上游仓库中找不到 scripts/fetch_weread_epub.py")
    return script


def calibre() -> str | None:
    executable = shutil.which("ebook-convert")
    if executable:
        return executable
    if sys.platform == "win32":
        for key in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(key)
            if base:
                candidate = Path(base) / "Calibre2" / "ebook-convert.exe"
                if candidate.is_file():
                    return str(candidate)
    return None


def doctor() -> dict:
    try:
        import playwright  # noqa: F401
        playwright_installed = True
    except ImportError:
        playwright_installed = False
    return result("READY" if COOKIE.is_file() and shutil.which("git") else "NEEDS_SETUP",
                  python=sys.version.split()[0], git=bool(shutil.which("git")),
                  playwright=playwright_installed, calibre=bool(calibre()),
                  cookie_file_exists=COOKIE.is_file(), upstream_installed=(UPSTREAM / "scripts" / "fetch_weread_epub.py").is_file(),
                  upstream_sha=git_commit(UPSTREAM), data_home=str(HOME),
                  note="Cookie 文件存在只证明会话曾保存，不代表当前仍已登录；READY 也不表示实际书籍全文导出已验证")


def _cookie_from_browser(c: dict) -> http.cookiejar.Cookie:
    expires = c.get("expires")
    expiry = int(expires) if isinstance(expires, (float, int)) and expires > 0 else None
    domain = c["domain"]
    return http.cookiejar.Cookie(version=0, name=c["name"], value=c["value"], port=None,
        port_specified=False, domain=domain, domain_specified=True,
        domain_initial_dot=domain.startswith("."), path=c.get("path", "/"),
        path_specified=True, secure=bool(c.get("secure")), expires=expiry,
        discard=expiry is None, comment=None, comment_url=None,
        rest={"HttpOnly": None} if c.get("httpOnly") else {}, rfc2109=False)


async def _login() -> dict:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        proc = run([sys.executable, "-m", "pip", "install", "playwright"])
        if proc.returncode:
            return result("DEPENDENCY_ERROR", message="安装 Playwright 失败", detail=proc.stderr[-500:])
        from playwright.async_api import async_playwright
    # Chromium is installed lazily; explicit failure points user to needed command.
    COOKIE.parent.mkdir(parents=True, exist_ok=True)
    BROWSER.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        try:
            ctx = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER), headless=False, viewport={"width": 1200, "height": 850})
        except Exception:
            installation = run([sys.executable, "-m", "playwright", "install", "chromium"])
            if installation.returncode:
                return result("BROWSER_REQUIRED", action=f"{sys.executable} -m playwright install chromium")
            try:
                ctx = await playwright.chromium.launch_persistent_context(
                    user_data_dir=str(BROWSER), headless=False, viewport={"width": 1200, "height": 850})
            except Exception:
                return result("BROWSER_REQUIRED", action="无法启动 Chromium，请检查桌面环境")
        try:
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            await page.goto("https://weread.qq.com/web/shelf", wait_until="domcontentloaded", timeout=60000)
            print("请在弹出的浏览器扫码登录微信读书，确认能看到自己的书架，然后回到终端按回车。", flush=True)
            await asyncio.to_thread(input)
            browser_cookies = await ctx.cookies()
            selected = [c for c in browser_cookies if c.get("domain", "").lstrip(".").endswith("qq.com")]
            if not selected:
                return result("LOGIN_REQUIRED", message="没有发现微信读书相关 Cookie，请检查扫码结果")
            jar = http.cookiejar.MozillaCookieJar(str(COOKIE))
            for c in selected:
                jar.set_cookie(_cookie_from_browser(c))
            jar.save(ignore_discard=True, ignore_expires=True)
            return result("SESSION_SAVED", cookie_path=str(COOKIE), saved_cookie_count=len(selected),
                          note="已保存本机 Cookie，但尚未验证目标书籍的实际阅读权限；Cookie 不会随项目提交")
        finally:
            await ctx.close()


class BodyScanner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_chars = 0
        self.images: list[str] = []
        self.in_hidden = 0
        self.headings: list[str] = []
        self.heading_tag: str | None = None
        self.heading_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        name = tag.lower()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"} and self.heading_tag is None:
            self.heading_tag = name
            self.heading_parts = []
        if name in {"script", "style"}:
            self.in_hidden += 1
        if name in {"img", "image"}:
            a = dict(attrs)
            src = a.get("src") or a.get("href") or a.get("xlink:href")
            if src:
                self.images.append(html.unescape(src))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == self.heading_tag:
            heading = " ".join("".join(self.heading_parts).split())
            if heading:
                self.headings.append(heading[:160])
            self.heading_tag = None
            self.heading_parts = []
        if tag in {"script", "style"} and self.in_hidden:
            self.in_hidden -= 1

    def handle_data(self, data):
        if self.heading_tag is not None:
            self.heading_parts.append(data)
        if not self.in_hidden:
            self.text_chars += len("".join(data.split()))


def epub_index(z: zipfile.ZipFile):
    container = ET.fromstring(z.read("META-INF/container.xml"))
    opf = next(node.attrib["full-path"] for node in container.iter() if node.tag.endswith("rootfile"))
    package = ET.fromstring(z.read(opf))
    manifest = {node.attrib["id"]: node.attrib for node in package.iter()
                if node.tag.endswith("item") and "id" in node.attrib}
    spine = [node.attrib["idref"] for node in package.iter() if node.tag.endswith("itemref")]
    opfdir = posixpath.dirname(opf)
    title = next((n.text for n in package.iter() if n.tag.endswith("}title") and n.text), "Untitled")
    return opfdir, manifest, spine, title


def zip_local_ref(document: str, ref: str) -> str | None:
    if urllib.parse.urlsplit(ref).scheme or ref.startswith("//") or ref.startswith("#"):
        return None
    parsed = urllib.parse.urlsplit(ref)
    return posixpath.normpath(posixpath.join(posixpath.dirname(document),
                                             urllib.parse.unquote(parsed.path)))


def inspect_epub(path: Path, expected: int | None = None) -> dict:
    report = {"file": str(path), "expected_chapters": expected, "status": "INVALID_EPUB"}
    try:
        with zipfile.ZipFile(path) as z:
            files = set(z.namelist())
            report["zip_crc_ok"] = z.testzip() is None
            report["mimetype_ok"] = z.read("mimetype") == b"application/epub+zip"
            opfdir, items, spine, title = epub_index(z)
            report.update(title=title, spine_chapters=len(spine), text_characters=0,
                          manifest_images=sum(x.get("media-type", "").startswith("image/") for x in items.values()),
                          broken_spine=[], broken_images=[], remote_images=[], image_references=0,
                          very_short_chapters=[], chapter_summaries=[])
            for index, item_id in enumerate(spine, 1):
                item = items.get(item_id)
                path_in_zip = posixpath.normpath(posixpath.join(opfdir, item.get("href", ""))) if item else ""
                if not item or path_in_zip not in files:
                    report["broken_spine"].append(item_id)
                    continue
                scanner = BodyScanner()
                scanner.feed(z.read(path_in_zip).decode("utf-8-sig", errors="replace"))
                scanner.close()
                report["chapter_summaries"].append({
                    "index": index,
                    "heading": scanner.headings[0] if scanner.headings else "",
                    "text_characters": scanner.text_chars,
                    "image_references": len(scanner.images),
                })
                report["text_characters"] += scanner.text_chars
                if scanner.text_chars < 30:
                    report["very_short_chapters"].append(index)
                for src in scanner.images:
                    report["image_references"] += 1
                    local = zip_local_ref(path_in_zip, src)
                    if local is None:
                        report["remote_images"].append(src)
                    elif local not in files:
                        report["broken_images"].append(local)
            # Each missing shared note icon can occur dozens of times. Keep
            # unique references in the JSON, while retaining occurrence counts.
            report["broken_image_references"] = len(report["broken_images"])
            report["remote_image_references"] = len(report["remote_images"])
            report["broken_images"] = sorted(set(report["broken_images"]))
            report["remote_images"] = sorted(set(report["remote_images"]))
            ok = (report["zip_crc_ok"] and report["mimetype_ok"] and bool(spine) and
                  not report["broken_spine"] and not report["broken_images"] and
                  not report["remote_images"] and (report["text_characters"] > 0 or report["image_references"] > 0) and
                  (expected is None or len(spine) == expected))
            report["status"] = "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED" if ok else "STRUCTURE_INCOMPLETE"
    except (OSError, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile, StopIteration) as exc:
        report["error"] = str(exc)
    return report


class MarkdownWriter(HTMLParser):
    def __init__(self, document: str, names: set[str], image_map: dict[str, str]):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.document = document
        self.names = names
        self.image_map = image_map
        self.missing_images: list[str] = []
        self.in_body = False
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "body":
            self.in_body = True
            return
        if self.in_body and tag in {"script", "style", "noscript"}:
            self.skip_depth += 1
            return
        if not self.in_body or self.skip_depth:
            return
        if tag in {"p", "div", "blockquote", "li"}:
            self.parts.append("\n\n" + ("- " if tag == "li" else ""))
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        if tag == "br":
            self.parts.append("\n")
        if tag in {"img", "image"}:
            a = dict(attrs)
            src = a.get("src") or a.get("xlink:href") or a.get("href")
            if not src:
                return
            original = zip_local_ref(self.document, src)
            if original is None or original not in self.names:
                self.missing_images.append(src)
                return
            local = self.image_map.setdefault(original, f"images/{len(self.image_map)+1:04d}{Path(original).suffix or '.jpg'}")
            self.parts.append(f"\n\n![image]({local})\n\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag == "body":
            self.in_body = False

    def handle_data(self, data):
        if self.in_body and not self.skip_depth:
            self.parts.append(data)


def markdown_from_epub(path: Path, directory: Path, *, include_text: bool = False) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    output_md = directory / "fulltext.md"
    fragments = []
    image_map: dict[str, str] = {}
    missing = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        opfdir, manifest, spine, book_title = epub_index(z)
        fragments.append("# " + book_title + "\n")
        for ident in spine:
            entry = manifest.get(ident)
            if not entry:
                continue
            document = posixpath.normpath(posixpath.join(opfdir, entry["href"]))
            if document not in names:
                continue
            writer = MarkdownWriter(document, names, image_map)
            writer.feed(z.read(document).decode("utf-8-sig", errors="replace"))
            fragments.append("".join(writer.parts).strip())
            missing.extend(writer.missing_images)
        for original, local in image_map.items():
            dest = directory / local
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(original))
    text = re.sub(r"\n{4,}", "\n\n\n", "\n\n".join(fragments)).strip() + "\n"
    output_md.write_text(text, encoding="utf-8")
    produced = {"md": str(output_md), "images": len(image_map), "unresolved_images": missing}
    if include_text:
        txt = directory / "fulltext.txt"
        txt.write_text(re.sub(r"!\[[^\]]*\]\([^)]*\)", "", re.sub(r"(?m)^#{1,6} ", "", text)), encoding="utf-8")
        produced["txt"] = str(txt)
    return produced


def classify_error(log: str) -> str:
    s = log.lower()
    if any(t in s for t in ("renewal failed", "cookie expired", "login required", "未登录", "登录失效")):
        return "LOGIN_REQUIRED"
    if any(t in s for t in ("permission denied", "forbidden", "403", "access denied", "需要购买", "去app阅读")):
        return "ACCESS_RESTRICTED"
    if any(t in s for t in ("404 not found", "unexpected html", "no chapters selected")):
        return "WEB_UNAVAILABLE"
    if any(t in s for t in ("captcha", "验证码", "verify your identity", "-2041")):
        return "MANUAL_VERIFICATION_REQUIRED"
    return "UPSTREAM_ERROR"


def save_report(path: Path, data: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def export_book(args) -> dict:
    book_key = reader_id(args.url)
    destination = (Path(args.output_dir).resolve() if args.output_dir else LIBRARY / book_key)
    destination.mkdir(parents=True, exist_ok=True)
    skipped = int(getattr(args, "skip", 0))
    prefix = "full" if args.full else f"sample-{args.sample}" + (f"-skip-{skipped}" if skipped else "")
    epub = destination / f"{prefix}.epub"
    job_path = destination / f"{prefix}.report.json"
    formats = set(args.format or ["epub"])
    formats.add("epub")
    data = result("RUNNING", reader_url=args.url, reader_id=book_key,
                  created_at=datetime.now(timezone.utc).isoformat(),
                  scope=prefix, skipped_chapters=skipped, formats_requested=sorted(formats), provider="finlater-epub",
                  upstream_repo=UPSTREAM_REPO)
    if not COOKIE.is_file() and not epub.is_file():
        return save_report(job_path, {**data, "status": "LOGIN_REQUIRED", "action": "python wereadlab.py login"})
    try:
        if args.force or not epub.exists():
            script = ensure_upstream()
            data["upstream_sha"] = git_commit(UPSTREAM)
            staged = destination / f"{prefix}.partial.epub"
            command = [sys.executable, str(script), "--reader-url", args.url,
                       "--cookie-file", str(COOKIE), "--save-cookies", str(COOKIE),
                       "--output", str(staged), "--sleep", str(args.sleep)]
            if not args.full:
                command.extend(["--limit", str(args.sample)])
                if skipped:
                    command.extend(["--skip", str(skipped)])
            proc = run(command, cwd=UPSTREAM)
            # The upstream output is locally retained; never commit this file.
            (destination / f"{prefix}.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
            if proc.returncode or not staged.is_file():
                return save_report(job_path, {**data, "status": classify_error(proc.stdout + proc.stderr),
                                              "action": "Inspect local report/log and fix the indicated cause"})
            validated = inspect_epub(staged, args.expected_chapters or (None if args.full else args.sample))
            if validated["status"] != "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED" and (
                validated.get("broken_images") or validated.get("remote_images")
            ):
                # Keep the raw partial EPUB. Repair only image references, not
                # chapter content, and do not discard a failed partial result.
                repaired = destination / f"{prefix}.images.partial.epub"
                data["image_repair"] = repair_epub_images(
                    staged, repaired, cookie_file=COOKIE
                )
                validated = inspect_epub(repaired, args.expected_chapters or (None if args.full else args.sample))
                if validated["status"] == "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED":
                    staged = repaired
            if validated["status"] != "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED":
                status = "IMAGE_ASSETS_INCOMPLETE" if data.get("image_repair") else "STRUCTURE_INCOMPLETE"
                return save_report(job_path, {**data, "status": status, "validation": validated})
            staged.replace(epub)
        elif job_path.is_file():
            try:
                prior = json.loads(job_path.read_text(encoding="utf-8"))
                data["upstream_sha"] = prior.get("upstream_sha")
            except (OSError, json.JSONDecodeError):
                pass
        validated = inspect_epub(epub, args.expected_chapters or (None if args.full else args.sample))
        if validated["status"] != "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED":
            return save_report(job_path, {**data, "status": "STRUCTURE_INCOMPLETE", "validation": validated})
        artifacts = {"epub": str(epub)}
        missing_formats = []
        if "md" in formats or "txt" in formats:
            converted = markdown_from_epub(epub, destination / prefix,
                                           include_text="txt" in formats)
            artifacts.update({k: v for k, v in converted.items() if k in formats})
            data["markdown_image_count"] = converted["images"]
            if converted["unresolved_images"]:
                data["markdown_unresolved_images"] = converted["unresolved_images"][:20]
        if "pdf" in formats:
            converter = calibre()
            if converter:
                pdf = destination / f"{prefix}.pdf"
                proc = run([converter, str(epub), str(pdf), "--paper-size", "a4"])
                if proc.returncode == 0 and pdf.is_file() and pdf.stat().st_size:
                    artifacts["pdf"] = str(pdf)
                else:
                    missing_formats.append("pdf: calibre conversion failed")
            else:
                missing_formats.append("pdf: install Calibre")
        data.update(status="FORMAT_PARTIAL" if missing_formats else "FILES_READY_COMPLETENESS_UNVERIFIED",
                    validation=validated, artifacts=artifacts, missing_formats=missing_formats,
                    note="EPUB 结构校验通过不代表已证明所有章节全文完整；请与书籍目录、首中末章核对")
        return save_report(job_path, data)
    except (OSError, ValueError, RuntimeError) as exc:
        return save_report(job_path, {**data, "status": "ERROR", "reason": str(exc)[:500]})


def catalog_book(args) -> dict:
    book_key = reader_id(args.url)
    destination = (Path(args.output_dir).resolve() if args.output_dir
                   else LIBRARY / book_key)
    report_file = destination / "catalog.report.json"
    if not COOKIE.is_file():
        return save_report(report_file, result(
            "LOGIN_REQUIRED", action="python wereadlab.py login"
        ))
    try:
        script = ensure_upstream()
        sha = git_commit(UPSTREAM)
        snapshot = fetch_catalog(
            reader_url=args.url,
            reader_id=book_key,
            cookie_file=COOKIE,
            upstream_script=script,
            upstream_sha=sha,
        )
        catalog_file = destination / "catalog.json"
        save_catalog(snapshot, catalog_file)
        totals = snapshot["totals"]
        status = "CATALOG_READY" if totals["selected_for_export"] > 0 else "CATALOG_EMPTY"
        data = result(
            status,
            book_title=snapshot["book"]["title"],
            catalog_file=str(catalog_file),
            upstream_sha=sha,
            **totals,
            note="仅完成目录快照；还没有获取整本正文、图片或最终 PDF。",
        )
        return save_report(report_file, data)
    except RuntimeError as exc:
        status = "LOGIN_REQUIRED" if str(exc) == "LOGIN_REQUIRED" else "CATALOG_ERROR"
        return save_report(report_file, result(
            status, error_type="RuntimeError",
            action="请检查本地目录报告和登录状态；没有开始全书采集。"
        ))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return save_report(report_file, result(
            "CATALOG_ERROR", error_type=type(exc).__name__,
            action="请检查本地登录会话及上游章节目录格式；没有开始全书采集。"
        ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wereadlab", description="微信读书个人归档 Agent 工具（本地运行）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor").add_argument("--json", action="store_true")
    login = sub.add_parser("login", help="首次扫码登录；必须在人可操作的桌面运行")
    login.add_argument("--json", action="store_true")
    install = sub.add_parser("upstream", help="下载或显式更新提取引擎")
    install.add_argument("--update", action="store_true")
    install.add_argument("--json", action="store_true")
    cat = sub.add_parser("catalog", help="只获取目录和章节元数据，不下载整本正文")
    cat.add_argument("url", help="从微信读书阅读页面复制的真实 URL")
    cat.add_argument("--output-dir", help="只保存到本地私人目录")
    cat.add_argument("--json", action="store_true")
    q = sub.add_parser("queue", help="本地章节任务表：只建队与查看状态，不抓正文")
    qsub = q.add_subparsers(dest="queue_action", required=True)
    qinit = qsub.add_parser("init", help="根据已有 catalog.json 建 SQLite 待处理表")
    qinit.add_argument("--latest", action="store_true")
    qinit.add_argument("--catalog", help="catalog.json 的本地路径")
    qinit.add_argument("--json", action="store_true")
    qstatus = qsub.add_parser("status", help="只读查看章节任务表状态")
    qstatus.add_argument("--latest", action="store_true")
    qstatus.add_argument("--db", help="chapters.sqlite 的本地路径")
    qstatus.add_argument("--json", action="store_true")
    qrun = qsub.add_parser("run", help="逐章采集，默认每次最多一章；不会合并整书")
    qrun.add_argument("--latest", action="store_true", help="选取最近初始化的本地章节队列")
    qrun.add_argument("--db", help="章节 SQLite 任务表路径")
    qrun.add_argument("--limit", type=int, default=1, help="本次最多处理几章（1-10）")
    qrun.add_argument("--retry-failed", action="store_true", help="允许重试 FAILED/INTERRUPTED 章节")
    qrun.add_argument("--sleep", type=float, default=0.4)
    qrun.add_argument("--max-images", type=int, default=500)
    qrun.add_argument("--json", action="store_true")
    book = sub.add_parser("book", help="从已完成章节合并 EPUB；不访问微信读书")
    book_sub = book.add_subparsers(dest="book_action", required=True)
    book_assemble = book_sub.add_parser("assemble", help="严格核验章数、UID、SHA 后合并")
    book_assemble.add_argument("--latest", action="store_true")
    book_assemble.add_argument("--db", help="章节任务数据库路径")
    book_assemble.add_argument("--max-assets", type=int, default=4000)
    book_assemble.add_argument("--format", action="append", choices=["epub","pdf","md","txt"])
    book_assemble.add_argument("--json", action="store_true")
    source_audit = sub.add_parser("source-audit", help="私有少量章节来源重读与归档正文对照")
    source_audit.add_argument("--latest", action="store_true")
    source_audit.add_argument("--book-dir", help="已有私有书籍目录；与 --latest 二选一")
    source_audit.add_argument("--checks", default="19:txt,20:txt,21:txt",
                              help="格式：19:txt,20:txt,21:txt；最多6章")
    source_audit.add_argument("--live", action="store_true",
                              help="明确允许向已授权书籍来源发起少量核验请求")
    source_audit.add_argument("--json", action="store_true")
    exp = sub.add_parser("export", help="试导出两章，或用 --full 处理整本可读章节")
    exp.add_argument("url", help="https://weread.qq.com/web/reader/... ")
    scope = exp.add_mutually_exclusive_group()
    scope.add_argument("--sample", type=int, default=2)
    scope.add_argument("--full", action="store_true")
    exp.add_argument("--format", action="append", choices=["epub", "pdf", "md", "txt"])
    exp.add_argument("--expected-chapters", type=int)
    exp.add_argument("--sleep", type=float, default=0.4)
    exp.add_argument("--skip", type=int, default=0,
                     help="跳过目录中前 N 个可读章节后再试导出（只适用于 --sample）")
    exp.add_argument("--output-dir")
    exp.add_argument("--force", action="store_true")
    exp.add_argument("--json", action="store_true")
    repair = sub.add_parser("repair", help="修复已有 EPUB 的 CDN 图片及注释图标，不重新抓取正文")
    repair.add_argument("file", nargs="?", help="已有 EPUB（可以是 .partial.epub）")
    repair.add_argument("--latest", action="store_true", help="选择最近生成的本地部分 EPUB")
    repair.add_argument("--output", help="指定修复后的新 EPUB 路径；不会覆盖原文件")
    repair.add_argument("--max-images", type=int, default=500)
    repair.add_argument("--format", action="append", choices=["epub", "pdf", "md", "txt"],
                        help="修复成功后直接转换为指定格式")
    repair.add_argument("--json", action="store_true")
    inspector = sub.add_parser("inspect", help="本地 EPUB 逐章结构与字数检查；不访问微信读书")
    inspector.add_argument("file", nargs="?", help="已有 EPUB 文件路径")
    inspector.add_argument("--latest", action="store_true", help="自动检查本机最近生成的 EPUB")
    inspector.add_argument("--expected-chapters", type=int)
    inspector.add_argument("--json", action="store_true")
    status = sub.add_parser("status", help="无需账号联网即可查看已有本地任务状态")
    status.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        data = doctor()
    elif args.command == "login":
        try:
            data = asyncio.run(_login())
        except (EOFError, OSError, TimeoutError) as exc:
            data = result("LOGIN_REQUIRED", reason=str(exc), action="在本机可操作桌面扫码登录")
    elif args.command == "upstream":
        try:
            ensure_upstream(update=args.update)
            data = result("UPSTREAM_READY", sha=git_commit(UPSTREAM))
        except RuntimeError as exc:
            data = result("UPSTREAM_ERROR", reason=str(exc))
    elif args.command == "source-audit":
        if args.book_dir and args.latest:
            parser.error("--book-dir 与 --latest 不能同时使用")
        if not args.live:
            data = result("SOURCE_AUDIT_REQUIRES_EXPLICIT_LIVE",
                          action="只有明确执行 --live 才会访问微信读书章节来源")
        else:
            selected_dir = Path(args.book_dir).expanduser() if args.book_dir else None
            if args.latest:
                catalogs = list(LIBRARY.glob("*/catalog.json")) if LIBRARY.exists() else []
                selected_dir = max(catalogs, key=lambda p: p.stat().st_mtime).parent if catalogs else None
            if selected_dir is None:
                data = result("CATALOG_NOT_FOUND", action="先运行 catalog 并使用 --latest")
            elif not COOKIE.is_file():
                data = result("LOGIN_REQUIRED", action="需要本机已授权的微信读书会话")
            else:
                try:
                    checks = parse_source_checks(args.checks)
                    script = ensure_upstream()
                    report = audit_source_parity(
                        book_dir=selected_dir,
                        cookie_file=COOKIE,
                        upstream_script=script,
                        upstream_sha=git_commit(UPSTREAM),
                        checks=checks
                    )
                    out = selected_dir / "final" / "source_parity_audit.json"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                    data = result(**report, report_file=str(out))
                except (ValueError, RuntimeError, OSError, KeyError, TypeError, zipfile.BadZipFile) as exc:
                    code = str(exc) if str(exc) in {
                        "LOGIN_REQUIRED", "PINNED_SOURCE_SHA_OR_CATALOG_MISMATCH",
                        "INCOMPLETE_QUEUE", "FORMAL_BOOK_ID_CHANGED",
                        "CHAPTER_CATALOG_DRIFT", "ARTIFACT_SHA_MISMATCH",
                        "CATALOG_OR_QUEUE_MISSING"
                    } else type(exc).__name__
                    data = result("SOURCE_AUDIT_BLOCKED", reason_code=code,
                                  action="检查登录状态、上游SHA与已完成章节; 不会将未验证结果标记通过")
    elif args.command == "book":
        if args.db and args.latest:
            parser.error("--db 与 --latest 不可同时使用")
        if args.max_assets < 1:
            parser.error("--max-assets 必须大于 0")
        db = Path(args.db).expanduser() if args.db else None
        if args.latest:
            candidates = list(LIBRARY.glob("*/chapters.sqlite")) if LIBRARY.exists() else []
            db = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
        if db is None:
            data = result("QUEUE_NOT_FOUND", action="先运行 catalog 与 queue init")
        else:
            target = db.parent / "final" / "book.epub"
            report_path = db.parent / "final" / "book.report.json"
            formats = set(args.format or ["epub"])
            formats.add("epub")
            try:
                data = result(**assemble_book(
                    db_path=db, catalog_path=db.with_name("catalog.json"),
                    output=target, inspector=inspect_epub, max_total_assets=args.max_assets
                ))
                if data["status"] == "BOOK_EPUB_READY_COMPLETENESS_UNVERIFIED":
                    artifacts = {"epub": str(target)}
                    failures = []
                    if "md" in formats or "txt" in formats:
                        converted = markdown_from_epub(
                            target, target.with_suffix(""),
                            include_text="txt" in formats
                        )
                        artifacts.update({k:v for k,v in converted.items() if k in formats})
                        if converted["unresolved_images"]:
                            failures.append("MARKDOWN_UNRESOLVED_IMAGE")
                    if "pdf" in formats:
                        converter = calibre()
                        if converter is None:
                            failures.append("CALIBRE_NOT_FOUND")
                        else:
                            pdf = target.with_suffix(".pdf")
                            proc = run([converter, str(target), str(pdf), "--paper-size", "a4"])
                            if proc.returncode == 0 and pdf.is_file() and pdf.stat().st_size > 0:
                                artifacts["pdf"] = str(pdf)
                            else:
                                failures.append("PDF_CONVERSION_FAILED")
                    data["status"] = "FORMAT_PARTIAL" if failures else "BOOK_FILES_READY_COMPLETENESS_UNVERIFIED"
                    data["artifacts"] = artifacts
                    data["missing_formats"] = failures
                save_report(report_path, data)
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ET.ParseError) as exc:
                data = result("ASSEMBLY_ERROR", error_code=(
                    str(exc) if str(exc).isupper() and len(str(exc)) < 80
                    else type(exc).__name__
                ), note="未标记整书完成；请检查本地章节队列和报告") 
                save_report(report_path, data)
    elif args.command == "queue":
        try:
            if args.queue_action == "init":
                if args.catalog and args.latest:
                    parser.error("--catalog 与 --latest 不可同时使用")
                source = Path(args.catalog).expanduser() if args.catalog else None
                if args.latest:
                    candidates = list(LIBRARY.glob("*/catalog.json")) if LIBRARY.exists() else []
                    source = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
                if source is None:
                    data = result("CATALOG_NOT_FOUND",
                                  action="先运行 wereadlab.py catalog <阅读页URL> --json，再 queue init --latest")
                else:
                    data = result(**init_queue(source, source.with_name("chapters.sqlite")))
            elif args.queue_action == "status":
                if args.db and args.latest:
                    parser.error("--db 与 --latest 不可同时使用")
                source = Path(args.db).expanduser() if args.db else None
                if args.latest:
                    candidates = list(LIBRARY.glob("*/chapters.sqlite")) if LIBRARY.exists() else []
                    source = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
                data = result(**inspect_queue(source)) if source else result("QUEUE_NOT_FOUND")
            else:
                if args.db and args.latest:
                    parser.error("--db 与 --latest 不可同时使用")
                if not 1 <= args.limit <= 10 or args.sleep < 0 or args.max_images < 1:
                    parser.error("--limit 必须在 1-10，--sleep >= 0，--max-images > 0")
                db = Path(args.db).expanduser() if args.db else None
                if args.latest:
                    candidates = list(LIBRARY.glob("*/chapters.sqlite")) if LIBRARY.exists() else []
                    db = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
                if db is None:
                    data = result("QUEUE_NOT_FOUND", action="先执行 catalog 和 queue init --latest")
                else:
                    cat = db.with_name("catalog.json")
                    if not cat.is_file():
                        data = result("CATALOG_NOT_FOUND", action="请检查本地目录快照")
                    else:
                        info = json.loads(cat.read_text(encoding="utf-8"))
                        saved_reader = str(info["book"]["reader_id"])
                        saved_url = "https://weread.qq.com/web/reader/" + saved_reader
                        reader_id(saved_url)
                        script = ensure_upstream()
                        data = result(**run_chapter_worker(
                            db_path=db,
                            catalog_path=cat,
                            reader_url=saved_url,
                            cookie_file=COOKIE,
                            upstream_script=script,
                            upstream_sha=git_commit(UPSTREAM),
                            inspector=inspect_epub,
                            repairer=repair_epub_images,
                            limit=args.limit,
                            retry_failed=args.retry_failed,
                            sleep=args.sleep,
                            max_images=args.max_images,
                        ))
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, json.JSONDecodeError) as exc:
            code = str(exc) if str(exc) in {
                "WORKER_BUSY", "CATALOG_SNAPSHOT_HASH_MISMATCH",
                "CATALOG_CHANGED_RECONCILIATION_REQUIRED", "UPSTREAM_SHA_MISMATCH",
                "CATALOG_OR_QUEUE_MISSING",
            } else type(exc).__name__
            data = result("QUEUE_ERROR", error_code=code,
                          action="检查本地目录/队列与上游版本，勿自动重置已完成章节")
    elif args.command == "catalog":
        try:
            data = catalog_book(args)
        except ValueError as exc:
            data = result("INVALID_URL", reason=str(exc), action="复制微信读书真实阅读页面 URL")
    elif args.command == "export":
        if args.sample < 1 or args.sleep < 0 or args.skip < 0 or (args.expected_chapters is not None and args.expected_chapters < 1):
            parser.error("--sample 和 --expected-chapters 必须大于 0，--skip 和 --sleep 不得为负数")
        if args.full and args.skip:
            parser.error("--full 不支持 --skip；请使用 --sample N --skip M 验证中段章节")
        try:
            data = export_book(args)
        except ValueError as exc:
            data = result("INVALID_URL", reason=str(exc),
                          action="先在 https://weread.qq.com/ 打开书架中的一本书，点击阅读并复制浏览器地址栏中的真实 /web/reader/... 链接；或双击 start.cmd 按提示输入。不要复制示例文字。")
    elif args.command == "repair":
        if args.file and args.latest:
            parser.error("repair 的文件路径和 --latest 只能选择一种")
        if args.max_images < 1:
            parser.error("--max-images 必须大于 0")
        source = Path(args.file).expanduser() if args.file else None
        if args.latest:
            candidates = list(LIBRARY.glob("*/*.partial.epub")) if LIBRARY.exists() else []
            source = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
        if source is None:
            data = result("NO_EPUB_FOUND", action="用 repair --latest 或 repair <EPUB文件路径> 提供待修复文件")
        else:
            output = Path(args.output).expanduser() if args.output else source.with_name(
                source.name.replace(".partial.epub", ".repaired.epub").replace(".epub", ".repaired.epub")
                if ".partial.epub" not in source.name else source.name.replace(".partial.epub", ".repaired.epub")
            )
            try:
                details = repair_epub_images(source, output, cookie_file=COOKIE, max_images=args.max_images)
                validation = inspect_epub(output)
                ready = validation["status"] == "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED"
                artifacts = {"epub": str(output)} if ready else {}
                missing_formats = []
                formats = set(args.format or ["epub"])
                if ready and ("md" in formats or "txt" in formats):
                    converted = markdown_from_epub(output, output.with_suffix(""),
                                                   include_text="txt" in formats)
                    artifacts.update({k: v for k, v in converted.items() if k in formats})
                    if converted["unresolved_images"]:
                        missing_formats.append("unresolved markdown image references")
                if ready and "pdf" in formats:
                    converter = calibre()
                    if not converter:
                        missing_formats.append("pdf: install Calibre")
                    else:
                        pdf_file = output.with_suffix(".pdf")
                        proc = run([converter, str(output), str(pdf_file), "--paper-size", "a4"])
                        if proc.returncode == 0 and pdf_file.is_file() and pdf_file.stat().st_size:
                            artifacts["pdf"] = str(pdf_file)
                        else:
                            missing_formats.append("pdf: Calibre conversion failed")
                status = ("FORMAT_PARTIAL" if missing_formats else "IMAGES_REPAIRED") if ready else "IMAGE_ASSETS_INCOMPLETE"
                data = result(status, image_repair=details, validation=validation,
                              artifacts=artifacts, missing_formats=missing_formats,
                              note="不会重新抓取章节；EPUB 结构通过仍需核对原书目录和图像内容")
            except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, ET.ParseError) as exc:
                data = result("IMAGE_REPAIR_ERROR", reason=str(exc)[:300])
    elif args.command == "inspect":
        if args.file and args.latest:
            parser.error("inspect 的文件路径和 --latest 只能选择一种")
        if args.expected_chapters is not None and args.expected_chapters < 1:
            parser.error("--expected-chapters 必须大于 0")
        target = Path(args.file).expanduser() if args.file else None
        if args.latest:
            candidates = list(LIBRARY.glob("*/*.epub")) if LIBRARY.exists() else []
            target = max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None
        if target is None:
            data = result("NO_EPUB_FOUND", action="提供 EPUB 路径，或在试导出后运行 inspect --latest --json")
        else:
            validation = inspect_epub(target, expected=args.expected_chapters)
            data = result(validation["status"], validation=validation,
                          note="逐章字数、标题和资源仅用于诊断；与网页版目录比对后才能确认全文完整")
    else:
        reports = sorted(LIBRARY.glob("*/*.report.json")) if LIBRARY.exists() else []
        data = result("STATUS", jobs=[json.loads(p.read_text(encoding="utf-8")) for p in reports[-30:]])
    emit(data, as_json=args.json)
    good = {"READY", "UPSTREAM_READY", "SESSION_SAVED", "FILES_READY_COMPLETENESS_UNVERIFIED",
            "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED", "IMAGES_REPAIRED", "CATALOG_READY",
            "QUEUE_READY", "WORKER_PROGRESS", "WORKER_IDLE",
            "CHAPTERS_FETCHED_PENDING_FULL_QA",
            "BOOK_FILES_READY_COMPLETENESS_UNVERIFIED",
            "SOURCE_PARITY_EXACT_FOR_CHECKED_CHAPTERS", "STATUS"}
    return 0 if data["status"] in good else 2


if __name__ == "__main__":
    raise SystemExit(main())