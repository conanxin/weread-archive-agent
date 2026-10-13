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
    parts = urllib.parse.urlsplit(url.strip())
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
                  note="READY 表示本地依赖齐备，不表示账户权限或真实全文导出已经通过")


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
                          note="会话只保存在本机，不会随项目提交")
        finally:
            await ctx.close()


class BodyScanner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_chars = 0
        self.images: list[str] = []
        self.in_hidden = 0

    def handle_starttag(self, tag, attrs):
        name = tag.lower()
        if name in {"script", "style"}:
            self.in_hidden += 1
        if name in {"img", "image"}:
            a = dict(attrs)
            src = a.get("src") or a.get("href") or a.get("xlink:href")
            if src:
                self.images.append(html.unescape(src))

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style"} and self.in_hidden:
            self.in_hidden -= 1

    def handle_data(self, data):
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
                          very_short_chapters=[])
            for index, item_id in enumerate(spine, 1):
                item = items.get(item_id)
                path_in_zip = posixpath.normpath(posixpath.join(opfdir, item.get("href", ""))) if item else ""
                if not item or path_in_zip not in files:
                    report["broken_spine"].append(item_id)
                    continue
                scanner = BodyScanner()
                scanner.feed(z.read(path_in_zip).decode("utf-8-sig", errors="replace"))
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

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
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

    def handle_data(self, data):
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
    prefix = "full" if args.full else f"sample-{args.sample}"
    epub = destination / f"{prefix}.epub"
    job_path = destination / f"{prefix}.report.json"
    formats = set(args.format or ["epub"])
    formats.add("epub")
    data = result("RUNNING", reader_url=args.url, reader_id=book_key,
                  created_at=datetime.now(timezone.utc).isoformat(),
                  scope=prefix, formats_requested=sorted(formats), provider="finlater-epub",
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
            proc = run(command, cwd=UPSTREAM)
            # The upstream output is locally retained; never commit this file.
            (destination / f"{prefix}.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
            if proc.returncode or not staged.is_file():
                return save_report(job_path, {**data, "status": classify_error(proc.stdout + proc.stderr),
                                              "action": "Inspect local report/log and fix the indicated cause"})
            validated = inspect_epub(staged, args.expected_chapters or (None if args.full else args.sample))
            if validated["status"] != "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED":
                return save_report(job_path, {**data, "status": "STRUCTURE_INCOMPLETE", "validation": validated})
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wereadlab", description="微信读书个人归档 Agent 工具（本地运行）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor").add_argument("--json", action="store_true")
    login = sub.add_parser("login", help="首次扫码登录；必须在人可操作的桌面运行")
    login.add_argument("--json", action="store_true")
    install = sub.add_parser("upstream", help="下载或显式更新提取引擎")
    install.add_argument("--update", action="store_true")
    install.add_argument("--json", action="store_true")
    exp = sub.add_parser("export", help="试导出两章，或用 --full 处理整本可读章节")
    exp.add_argument("url", help="https://weread.qq.com/web/reader/... ")
    scope = exp.add_mutually_exclusive_group()
    scope.add_argument("--sample", type=int, default=2)
    scope.add_argument("--full", action="store_true")
    exp.add_argument("--format", action="append", choices=["epub", "pdf", "md", "txt"])
    exp.add_argument("--expected-chapters", type=int)
    exp.add_argument("--sleep", type=float, default=0.4)
    exp.add_argument("--output-dir")
    exp.add_argument("--force", action="store_true")
    exp.add_argument("--json", action="store_true")
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
    elif args.command == "export":
        if args.sample < 1 or args.sleep < 0 or (args.expected_chapters is not None and args.expected_chapters < 1):
            parser.error("--sample 和 --expected-chapters 必须大于 0，--sleep 不得为负数")
        try:
            data = export_book(args)
        except ValueError as exc:
            data = result("INVALID_URL", reason=str(exc))
    else:
        reports = sorted(LIBRARY.glob("*/*.report.json")) if LIBRARY.exists() else []
        data = result("STATUS", jobs=[json.loads(p.read_text(encoding="utf-8")) for p in reports[-30:]])
    emit(data, as_json=args.json)
    good = {"READY", "UPSTREAM_READY", "SESSION_SAVED", "FILES_READY_COMPLETENESS_UNVERIFIED", "STATUS"}
    return 0 if data["status"] in good else 2


if __name__ == "__main__":
    raise SystemExit(main())