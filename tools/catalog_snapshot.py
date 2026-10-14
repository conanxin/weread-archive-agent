"""Read-only chapter catalog snapshot for a locally authenticated WeRead book.

Uses the already pinned upstream EPUB provider's parser and logged-in cookie jar.
Fetches metadata only (reader HTML + chapterInfos): no chapter text, image, or PDF.
Private per-book catalog is stored under .local/library, never in the GitHub repo.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any

CHAPTER_INFOS_ENDPOINT = "https://weread.qq.com/web/book/chapterInfos"
CATALOG_SCHEMA = 1


def load_provider(upstream_script: Path):
    if not upstream_script.is_file():
        raise RuntimeError("UPSTREAM_SCRIPT_NOT_FOUND")
    module_name = "_weread_epub_provider_catalog"
    spec = importlib.util.spec_from_file_location(module_name, upstream_script)
    if spec is None or spec.loader is None:
        raise RuntimeError("UPSTREAM_IMPORT_UNAVAILABLE")
    provider = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = provider
    spec.loader.exec_module(provider)
    return provider


def _word_count(chapter: dict[str, Any]) -> int:
    value = chapter.get("wordCount") or 0
    count = int(value)
    if count < 0:
        raise ValueError("NEGATIVE_CHAPTER_WORD_COUNT")
    return count


def build_catalog(
    chapters: list[dict[str, Any]],
    *,
    title: str,
    author: str,
    book_id: str,
    reader_id: str,
    upstream_sha: str | None,
) -> dict:
    rows: list[dict] = []
    seen: set[str] = set()
    for order, chapter in enumerate(chapters, 1):
        uid = str(chapter.get("chapterUid") or "")
        if not uid:
            raise ValueError("MISSING_CHAPTER_UID")
        if uid in seen:
            raise ValueError("DUPLICATE_CHAPTER_UID")
        seen.add(uid)
        chapter_title = str(chapter.get("title") or "").strip()
        words = _word_count(chapter)
        enabled = words > 0 and chapter_title != "封面"
        row = {
            "order": order,
            "chapter_uid": uid,
            "title": chapter_title,
            "word_count": words,
            "selected_for_export": enabled,
        }
        # Keep the upstream catalog order; chapterIdx is reference-only.
        if chapter.get("chapterIdx") is not None:
            row["provider_chapter_idx"] = chapter["chapterIdx"]
        rows.append(row)
    selected = [row for row in rows if row["selected_for_export"]]
    return {
        "schema_version": CATALOG_SCHEMA,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "WeRead authenticated reader + chapterInfos via pinned upstream",
        "upstream_sha": upstream_sha,
        "book": {
            "title": title,
            "author": author,
            "formal_book_id": book_id,
            "reader_id": reader_id,
        },
        "totals": {
            "catalog_entries": len(rows),
            "selected_for_export": len(selected),
            "excluded_entries": len(rows) - len(selected),
            "selected_provider_word_count": sum(row["word_count"] for row in selected),
        },
        "chapters": rows,
        "note": "目录快照不证明正文或插图已取得；selected_for_export 与当前上游过滤规则一致。",
    }


def fetch_catalog(
    *,
    reader_url: str,
    reader_id: str,
    cookie_file: Path,
    upstream_script: Path,
    upstream_sha: str | None,
    provider=None,
) -> dict:
    if not cookie_file.is_file():
        raise RuntimeError("LOGIN_REQUIRED")
    provider = provider or load_provider(upstream_script)
    client = provider.WeReadClient(
        cookie_file=cookie_file, cookie_string=None, save_cookies=cookie_file
    )
    if not client.renew():
        raise RuntimeError("LOGIN_REQUIRED")
    reader_html = client.get_text(reader_url, referer=reader_url)
    reader_state = provider.read_reader_state(reader_html)
    book_id = reader_state.book_id
    payload = client.post_json(
        CHAPTER_INFOS_ENDPOINT,
        {"bookIds": [book_id]},
        referer=reader_url,
    )
    book_record, chapters = provider.normalize_chapter_infos(payload, book_id)
    meta = book_record.get("book") or {}
    if not isinstance(meta, dict):
        meta = {}
    result = build_catalog(
        chapters,
        title=meta.get("title") or book_record.get("title") or reader_state.book_title,
        author=meta.get("author") or book_record.get("author") or reader_state.author,
        book_id=book_id,
        reader_id=reader_id,
        upstream_sha=upstream_sha,
    )
    client.persist_cookies()
    return result


def save_catalog(snapshot: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    # A single local metadata file; never placed in the public repository.
    data = json.dumps(snapshot, ensure_ascii=False, indent=2)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, output)
