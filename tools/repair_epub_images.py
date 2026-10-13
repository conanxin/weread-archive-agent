"""Repair image references in an already-generated local WeRead EPUB.

No chapter fetches and no content text is printed. Original EPUB remains untouched.
Only HTTPS images from res.weread.qq.com are fetched; synthetic fixtures can pass
a downloader callback for fully offline tests.
"""
from __future__ import annotations

import hashlib
import html
import http.cookiejar
from pathlib import Path
import posixpath
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ALLOWED_IMAGE_HOSTS = {"res.weread.qq.com"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024
IMAGE_TAG = re.compile(r"<(?:img|image)\b[^>]*>", re.I | re.S)
IMAGE_SOURCE = re.compile(r"(?<![\w:-])(?:src|(?:xlink:)?href)\s*=\s*(['\"])(.*?)\1", re.I | re.S)
IMAGE_ALT = re.compile(r"(?<![\w:-])alt\s*=\s*(['\"])(.*?)\1", re.I | re.S)
PACKAGE_NS = "http://www.idpf.org/2007/opf"
IMAGE_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0 Safari/537.36"


def _safe_image_url(url: str, *, redirected: bool = False) -> bool:
    p = urllib.parse.urlsplit(url)
    hostname = p.hostname or ""
    # Image URLs originate on WeRead; the actual image CDN can issue an HTTP
    # redirect to a Tencent Cloud host. Never accept arbitrary user-provided
    # third-party URLs as initial image sources.
    trusted_origin = hostname in ALLOWED_IMAGE_HOSTS
    trusted_redirect = redirected and hostname.endswith(".gfp.tencent-cloud.com")
    return (p.scheme == "https" and (trusted_origin or trusted_redirect)
            and p.port is None and p.username is None and p.password is None)


class _RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _safe_image_url(newurl, redirected=True):
            raise ValueError("Image redirect outside trusted CDN")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _media_type(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if len(data) > 12 and data[4:8] == b"ftyp" and data[8:12] in {b"avif", b"avis"}:
        return ".avif", "image/avif"
    raise ValueError("Downloaded response is not a supported image")


def make_downloader(cookie_file: Path | None):
    jar = http.cookiejar.MozillaCookieJar()
    if cookie_file and cookie_file.is_file():
        jar.load(str(cookie_file), ignore_discard=True, ignore_expires=True)
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar), _RestrictedRedirect()
    )

    def download(url: str) -> tuple[bytes, str, str]:
        if not _safe_image_url(url):
            raise ValueError("Untrusted image URL")
        request = urllib.request.Request(url, headers={
            "User-Agent": IMAGE_USER_AGENT,
            "Referer": "https://weread.qq.com/",
            "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif,*/*;q=0.8",
        })
        with opener.open(request, timeout=25) as response:
            if not _safe_image_url(response.geturl(), redirected=True):
                raise ValueError("Image host changed")
            data = response.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Image exceeds per-file size limit")
        extension, media_type = _media_type(data)
        return data, extension, media_type

    return download


def _opf_metadata(z: zipfile.ZipFile):
    container = ET.fromstring(z.read("META-INF/container.xml"))
    opf_path = next(
        el.attrib["full-path"] for el in container.iter()
        if el.tag.rsplit("}", 1)[-1] == "rootfile"
    )
    package = ET.fromstring(z.read(opf_path))
    manifest = next(
        el for el in package.iter() if el.tag.rsplit("}", 1)[-1] == "manifest"
    )
    return opf_path, package, manifest


def _local_image_path(document: str, url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme or url.startswith("//") or url.startswith("#"):
        return None
    return posixpath.normpath(posixpath.join(
        posixpath.dirname(document), urllib.parse.unquote(parts.path)
    ))


def _error_reason(exc: Exception) -> str:
    # Do not leak image URLs, cookies or HTTP response bodies into reports.
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP_{exc.code}"
    if isinstance(exc, ValueError):
        message = str(exc)
        if "redirect outside trusted CDN" in message or "host changed" in message:
            return "REDIRECT_HOST_NOT_ALLOWLISTED"
        if "not a supported image" in message:
            return "NOT_AN_IMAGE_RESPONSE"
        if "exceeds" in message:
            return "IMAGE_EXCEEDS_SIZE_LIMIT"
        return "IMAGE_VALUE_ERROR"
    if isinstance(exc, urllib.error.URLError):
        return "NETWORK_REQUEST_ERROR"
    return type(exc).__name__


def repair_epub_images(
    source: Path,
    destination: Path,
    *,
    cookie_file: Path | None = None,
    downloader=None,
    max_images: int = 500,
) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError("The repaired EPUB must use a different file path")
    if max_images < 1:
        raise ValueError("max_images must be >= 1")
    destination.parent.mkdir(parents=True, exist_ok=True)
    download = downloader or make_downloader(cookie_file)
    fetched: dict[str, tuple[str, Path, str]] = {}
    failures: dict[str, str] = {}
    modified: dict[str, bytes] = {}
    note_markers = 0
    remote_occurrences = 0
    remote_urls: set[str] = set()

    # Temporary image files avoid retaining a complete illustrated book in RAM.
    with tempfile.TemporaryDirectory(prefix="weread-images-", dir=destination.parent) as td:
        temp_root = Path(td)
        with zipfile.ZipFile(source) as src:
            names = set(src.namelist())
            opf_path, package, manifest = _opf_metadata(src)
            opf_dir = posixpath.dirname(opf_path)
            documents = [
                n for n in src.namelist()
                if n.lower().endswith((".xhtml", ".html", ".htm"))
            ]
            def transform_tag(tag: str, document: str) -> str:
                nonlocal note_markers, remote_occurrences
                source_attr = IMAGE_SOURCE.search(tag)
                if not source_attr:
                    return tag
                raw_src = html.unescape(source_attr.group(2).strip())
                local = _local_image_path(document, raw_src)
                if local and local not in names and local.lower().endswith("/images/note.png"):
                    note_markers += 1
                    alt_attr = IMAGE_ALT.search(tag)
                    alt = html.unescape(alt_attr.group(2).strip()) if alt_attr else ""
                    label = ("〔注：" + alt + "〕") if alt and alt.lower() not in {"image", "note", "icon"} else "〔注〕"
                    # Some annotations contain paragraphs in the alt attribute.
                    # Preserve the complete annotation text, never truncate it.
                    return '<span class="weread-note-marker">' + html.escape(label) + '</span>'
                parts = urllib.parse.urlsplit(raw_src)
                if parts.scheme not in {"http", "https"}:
                    return tag
                remote_occurrences += 1
                remote_urls.add(raw_src)
                if not _safe_image_url(raw_src):
                    failures.setdefault(raw_src, "URL_NOT_ALLOWLISTED")
                    return tag
                if raw_src not in fetched and raw_src not in failures:
                    if len(fetched) >= max_images:
                        failures[raw_src] = "IMAGE_LIMIT_REACHED"
                    else:
                        try:
                            data, ext, mime = download(raw_src)
                            if len(data) > MAX_IMAGE_BYTES:
                                raise ValueError("Image exceeds size limit")
                            # Verify even injected test callbacks by content signature.
                            verified_ext, verified_mime = _media_type(data)
                            ext, mime = verified_ext, verified_mime
                            digest = hashlib.sha256(raw_src.encode("utf-8")).hexdigest()[:20]
                            asset = posixpath.join(opf_dir, "images", f"wr_{digest}{ext}")
                            temp = temp_root / f"wr_{digest}{ext}"
                            temp.write_bytes(data)
                            fetched[raw_src] = (asset, temp, mime)
                        except (OSError, ValueError, urllib.error.URLError) as exc:
                            failures[raw_src] = _error_reason(exc)
                if raw_src not in fetched:
                    return tag
                asset_path = fetched[raw_src][0]
                relative = posixpath.relpath(asset_path, start=posixpath.dirname(document))
                quoted = source_attr.group(1)
                attr = source_attr.group(0)
                key = attr.split("=", 1)[0].rstrip()
                replacement = f"{key}={quoted}{html.escape(relative, quote=True)}{quoted}"
                return tag[:source_attr.start()] + replacement + tag[source_attr.end():]

            for document in documents:
                body = src.read(document).decode("utf-8-sig", errors="replace")
                rewritten = IMAGE_TAG.sub(lambda m: transform_tag(m.group(0), document), body)
                if rewritten != body:
                    modified[document] = rewritten.encode("utf-8")

            if fetched:
                existing_ids = {
                    el.attrib.get("id") for el in manifest
                    if el.tag.rsplit("}", 1)[-1] == "item"
                }
                for url, (path, _temp, mime) in fetched.items():
                    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
                    asset_id = f"wr_img_{digest}"
                    if asset_id in existing_ids:
                        raise ValueError("EPUB asset ID collision")
                    ET.SubElement(manifest, f"{{{PACKAGE_NS}}}item", {
                        "id": asset_id,
                        "href": posixpath.relpath(path, start=opf_dir),
                        "media-type": mime,
                    })
                ET.register_namespace("", PACKAGE_NS)
                ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
                modified[opf_path] = ET.tostring(
                    package, encoding="utf-8", xml_declaration=True
                )

            with zipfile.ZipFile(destination, "w") as dest:
                for info in src.infolist():
                    dest.writestr(info, modified.get(info.filename, src.read(info.filename)))
                for _url, (path, temp, _mime) in fetched.items():
                    if path in names:
                        raise ValueError("EPUB asset path collision")
                    dest.writestr(path, temp.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)

    return {
        "source": str(source),
        "output": str(destination),
        "remote_image_references": remote_occurrences,
        "remote_unique_urls": len(remote_urls),
        "downloaded_unique_images": len(fetched),
        "note_markers_substituted": note_markers,
        "download_failures": [
            {"url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
             "reason": reason}
            for url, reason in list(failures.items())[:30]
        ],
        "download_failure_count": len(failures),
        "note": "注释图标使用文字标记代替；此操作不代表恢复原始图标或证明全书完整",
    }
