"""P2-C: assemble individually verified chapter EPUBs in the frozen catalog order.

No WeRead network calls. Verifies per-chapter SHA256 from SQLite and EPUB
structure, refuses to produce a book when any selected chapter is incomplete.
Source chapter files are retained untouched. Missing CSS-only decorations are
recorded and omitted explicitly rather than leaving broken URLs silently.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import posixpath
import re
import sqlite3
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
import zipfile

from tools.chapter_worker import file_sha256, GOOD_EPUB

IMAGE_TAG = re.compile(r"<(?:img|image)\b[^>]*>", re.I | re.S)
STYLE_LINK = re.compile(r"<link\b[^>]*>", re.I | re.S)
SOURCE_ATTRIBUTE = re.compile(r"(?<![\w:-])(?:src|(?:xlink:)?href)\s*=\s*(['\"])(.*?)\1", re.I | re.S)
STYLESHEET_URL = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.I | re.S)

MIME_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".avif": "image/avif", ".woff": "font/woff", ".woff2": "font/woff2",
    ".otf": "font/otf", ".ttf": "font/ttf",
}


def _xml(value: object) -> str:
    return html.escape(str(value), quote=True)


def _resolve_relative(source: str, reference: str) -> str | None:
    part = urllib.parse.urlsplit(reference)
    if part.scheme or reference.startswith("//") or reference.startswith("#"):
        return None
    return posixpath.normpath(posixpath.join(
        posixpath.dirname(source), urllib.parse.unquote(part.path)
    ))


def _find_package(z: zipfile.ZipFile) -> tuple[str, dict[str, dict], list[str]]:
    container = ET.fromstring(z.read("META-INF/container.xml"))
    rootfile = next(
        n.attrib["full-path"] for n in container.iter()
        if n.tag.endswith("rootfile")
    )
    package = ET.fromstring(z.read(rootfile))
    manifest = {
        el.attrib["id"]: el.attrib for el in package.iter()
        if el.tag.endswith("item") and "id" in el.attrib
    }
    spine = [el.attrib["idref"] for el in package.iter() if el.tag.endswith("itemref")]
    return rootfile, manifest, spine


def _rewrite_src(tag: str, original_document: str, new_document: str,
                 resource_map: dict[str, str], *, kind: str) -> str:
    match = SOURCE_ATTRIBUTE.search(tag)
    if match is None:
        return tag
    ref = html.unescape(match.group(2))
    resolved = _resolve_relative(original_document, ref)
    if resolved is None or resolved not in resource_map:
        raise ValueError(f"{kind}_REFERENCE_NOT_RESOLVED")
    target = resource_map[resolved]
    rewritten = posixpath.relpath(target, posixpath.dirname(new_document))
    attr = match.group(0).split("=", 1)[0].rstrip()
    quote = match.group(1)
    replacement = attr + "=" + quote + _xml(rewritten) + quote
    return tag[:match.start()] + replacement + tag[match.end():]


def _rewrite_css(css: str, original_css: str, new_css: str,
                 resource_map: dict[str, str], warnings: list[dict], ordinal: int) -> str:
    def update(m: re.Match[str]) -> str:
        ref = html.unescape(m.group(2).strip())
        if not ref:
            return "none"
        if ref.startswith("data:"):
            return m.group(0)
        origin = _resolve_relative(original_css, ref)
        if origin is None or origin not in resource_map:
            warnings.append({"ordinal": ordinal, "kind": "CSS_DECORATION_UNAVAILABLE"})
            # Retain the underlying source EPUB unchanged, explicitly remove
            # a broken decorative reference from the assembled presentation.
            return "none"
        dest = posixpath.relpath(resource_map[origin], posixpath.dirname(new_css))
        return "url(" + _xml(dest) + ")"
    return STYLESHEET_URL.sub(update, css)


def _read_validated_sources(db_path: Path, catalog_path: Path, inspector) -> tuple[list[dict], dict]:
    if not db_path.is_file() or not catalog_path.is_file():
        raise FileNotFoundError("QUEUE_OR_CATALOG_NOT_FOUND")
    raw = catalog_path.read_bytes()
    cat = json.loads(raw.decode("utf-8"))
    if cat.get("schema_version") != 1:
        raise ValueError("CATALOG_SCHEMA_MISMATCH")
    conn = sqlite3.connect(db_path)
    try:
        recorded = conn.execute(
            "SELECT value FROM queue_info WHERE key='catalog_sha256'"
        ).fetchone()
        if not recorded or recorded[0] != hashlib.sha256(raw).hexdigest():
            raise ValueError("CATALOG_HASH_MISMATCH")
        rows = conn.execute(
            """SELECT ordinal, chapter_uid, chapter_title, state, artifact_path,
                      artifact_sha256 FROM chapters ORDER BY ordinal"""
        ).fetchall()
    finally:
        conn.close()
    selected = [r for r in cat["chapters"] if r["selected_for_export"]]
    if len(selected) != len(rows) or not selected:
        raise ValueError("QUEUE_CATALOG_COVERAGE_MISMATCH")
    items = []
    for i, (ordinal, uid, title, state, artifact, sha) in enumerate(rows):
        row = selected[i]
        if (ordinal != i + 1 or str(uid) != str(row["chapter_uid"])
                or int(row["order"]) != int(cat["chapters"].index(row)) + 1):
            raise ValueError("CHAPTER_ORDER_MISMATCH")
        if state != "COMPLETE":
            raise ValueError("CHAPTERS_NOT_ALL_COMPLETE")
        if not artifact or not sha:
            raise ValueError("CHAPTER_MISSING_ARTIFACT_HASH")
        location = (db_path.parent / artifact).resolve()
        if not location.is_relative_to(db_path.parent.resolve()) or not location.is_file():
            raise ValueError("CHAPTER_ARTIFACT_PATH_INVALID")
        if file_sha256(location) != sha:
            raise ValueError("CHAPTER_ARTIFACT_SHA_MISMATCH")
        check = inspector(location, expected=1)
        if check["status"] != GOOD_EPUB:
            raise ValueError("CHAPTER_EPUB_STRUCTURE_INCOMPLETE")
        items.append({
            "ordinal": ordinal,
            "chapter_uid": uid,
            "chapter_title": title,
            "file": location,
            "text_characters": check["text_characters"],
            "image_references": check["image_references"],
        })
    return items, cat


def _extract_chapter(item: dict, warnings: list[dict]) -> tuple[str, str, list[tuple[str,str,Path,str]]]:
    ordinal = item["ordinal"]
    file = item["file"]
    with zipfile.ZipFile(file) as z:
        original_opf, manifest, spine = _find_package(z)
        if len(spine) != 1 or spine[0] not in manifest:
            raise ValueError("SOURCE_CHAPTER_SPINE_INVALID")
        old_document = posixpath.normpath(posixpath.join(
            posixpath.dirname(original_opf), manifest[spine[0]]["href"]
        ))
        names = set(z.namelist())
        if old_document not in names:
            raise ValueError("SOURCE_CHAPTER_XHTML_MISSING")
        new_document = f"OEBPS/text/chapter_{ordinal:04d}.xhtml"
        old_style = None
        new_style = f"OEBPS/styles/chapter_{ordinal:04d}.css"
        assets = []
        asset_map: dict[str,str] = {}
        for item_id, info in manifest.items():
            media_type = str(info.get("media-type", ""))
            old = posixpath.normpath(posixpath.join(
                posixpath.dirname(original_opf), info.get("href", "")
            ))
            if media_type == "text/css":
                if old in names and old_style is None:
                    old_style = old
                continue
            if old not in names or not (media_type.startswith("image/") or
                                         media_type.startswith("font/") or
                                         "font" in media_type):
                continue
            fingerprint = hashlib.sha256(old.encode("utf-8")).hexdigest()[:12]
            extension = Path(old).suffix
            target = f"OEBPS/assets/{ordinal:04d}/{fingerprint}{extension}"
            if old in asset_map:
                continue
            asset_map[old] = target
            assets.append((old, target, file, media_type))

        xhtml = z.read(old_document).decode("utf-8-sig")
        xhtml = IMAGE_TAG.sub(
            lambda m: _rewrite_src(
                m.group(0), old_document, new_document, asset_map, kind="IMAGE"
            ), xhtml
        )
        css_text = ""
        if old_style:
            css_text = z.read(old_style).decode("utf-8-sig")
            css_text = _rewrite_css(
                css_text, old_style, new_style, asset_map, warnings, ordinal
            )
            style_mapping = {old_style: new_style}
            def change_style(m: re.Match[str]) -> str:
                if "stylesheet" not in m.group(0).lower():
                    return m.group(0)
                return _rewrite_src(m.group(0), old_document, new_document,
                                    style_mapping, kind="STYLESHEET")
            xhtml = STYLE_LINK.sub(change_style, xhtml)
        return xhtml, css_text, assets


def _epub_markup(cat: dict, items: list[dict], assets: list[tuple[str,str,Path,str]]) -> tuple[str,str,str]:
    title = _xml(cat["book"]["title"])
    author = _xml(cat["book"].get("author", ""))
    private_id = uuid.uuid5(
        uuid.NAMESPACE_URL, "weread-personal:" + str(cat["book"]["formal_book_id"])
    )
    nav_rows = "\n".join(
        f'<li><a href="text/chapter_{row["ordinal"]:04d}.xhtml">{_xml(row["chapter_title"])}</a></li>'
        for row in items
    )
    nav = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="zh-CN">'
        '<head><title>Table of Contents</title></head><body>'
        '<nav epub:type="toc" id="toc"><h1>目录</h1><ol>'
        + nav_rows + '</ol></nav></body></html>'
    )
    points = "\n".join(
        f'<navPoint id="pt-{row["ordinal"]}" playOrder="{row["ordinal"]}">'
        f'<navLabel><text>{_xml(row["chapter_title"])}</text></navLabel>'
        f'<content src="text/chapter_{row["ordinal"]:04d}.xhtml"/></navPoint>'
        for row in items
    )
    ncx = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f'<head><meta name="dtb:uid" content="urn:uuid:{private_id}"/></head>'
        f'<docTitle><text>{title}</text></docTitle><navMap>{points}</navMap></ncx>'
    )
    manifest_rows = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
    ]
    for row in items:
        n = row["ordinal"]
        manifest_rows.append(
            f'<item id="ch{n}" href="text/chapter_{n:04d}.xhtml" '
            'media-type="application/xhtml+xml"/>'
        )
        manifest_rows.append(
            f'<item id="css{n}" href="styles/chapter_{n:04d}.css" media-type="text/css"/>'
        )
    for seq, (_old, name, _file, mime) in enumerate(assets, 1):
        manifest_rows.append(
            f'<item id="asset{seq}" href="{_xml(name.removeprefix("OEBPS/"))}" media-type="{_xml(mime)}"/>'
        )
    spine = "\n".join(f'<itemref idref="ch{x["ordinal"]}"/>' for x in items)
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    package = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:identifier id="bookid">urn:uuid:{private_id}</dc:identifier>'
        f'<dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>'
        f'<dc:language>zh-CN</dc:language><meta property="dcterms:modified">{modified}</meta>'
        '</metadata><manifest>'+"".join(manifest_rows)+'</manifest><spine toc="ncx">'
        + spine + '</spine></package>'
    )
    return package, nav, ncx


def assemble_book(
    *, db_path: Path, catalog_path: Path, output: Path,
    inspector, max_total_assets: int = 4000,
) -> dict:
    import sqlite3
    if max_total_assets < 1:
        raise ValueError("ASSET_LIMIT_INVALID")
    if not db_path.is_file():
        raise FileNotFoundError("QUEUE_MISSING")
    with sqlite3.connect(db_path) as connection:
        statuses = dict(connection.execute(
            "SELECT state, count(*) FROM chapters GROUP BY state"
        ).fetchall())
    if any(statuses.get(s, 0) for s in ("PENDING", "RUNNING", "FAILED")):
        return {
            "status": "ASSEMBLY_NOT_READY",
            "pending": statuses.get("PENDING", 0),
            "running": statuses.get("RUNNING", 0),
            "failed": statuses.get("FAILED", 0),
            "complete": statuses.get("COMPLETE", 0),
        }
    items, cat = _read_validated_sources(db_path, catalog_path, inspector)
    output.parent.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "status": "ASSEMBLY_RUNNING",
        "chapter_count": len(items),
        "book_title": cat["book"]["title"],
        "css_unavailable": [],
        "total_chapter_text_chars": sum(i["text_characters"] for i in items),
    }
    chapter_data = []
    media: list[tuple[str,str,Path,str]] = []
    for item in items:
        text, css, assets = _extract_chapter(item, report["css_unavailable"])
        chapter_data.append((item["ordinal"], text, css))
        media.extend(assets)
    if len(media) > max_total_assets:
        raise ValueError("ASSET_LIMIT_EXCEEDED")
    package, nav, ncx = _epub_markup(cat, items, media)
    container = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    staged = output.with_name(output.name + ".partial")
    with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as dest:
        dest.writestr("mimetype", "application/epub+zip",
                      compress_type=zipfile.ZIP_STORED)
        dest.writestr("META-INF/container.xml", container)
        dest.writestr("OEBPS/content.opf", package)
        dest.writestr("OEBPS/nav.xhtml", nav)
        dest.writestr("OEBPS/toc.ncx", ncx)
        for ordinal, xhtml, css in chapter_data:
            dest.writestr(f"OEBPS/text/chapter_{ordinal:04d}.xhtml", xhtml)
            dest.writestr(f"OEBPS/styles/chapter_{ordinal:04d}.css", css)
        for old, new, source, _mime in media:
            with zipfile.ZipFile(source) as z:
                dest.writestr(new, z.read(old))
    verification = inspector(staged, expected=len(items))
    if verification["status"] != GOOD_EPUB:
        raise ValueError("ASSEMBLED_EPUB_STRUCTURE_INCOMPLETE")
    os.replace(staged, output)
    report.update(
        status="BOOK_EPUB_READY_COMPLETENESS_UNVERIFIED",
        epub=str(output),
        sha256=file_sha256(output),
        epub_bytes=output.stat().st_size,
        images_packed=len(media),
        css_warning_count=len(report["css_unavailable"]),
        validation=verification,
        note="22等全部被选章节与队列一一对应且结构通过；未完成与原网页逐字/逐图视觉比对。",
    )
    return report
