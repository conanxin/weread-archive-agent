"""P2-D3 private source-to-artifact textual parity audit.

Requires an explicit --live opt-in and the already authorized local session.
Re-fetches a few source chapters from the pinned upstream, compares text with
the local verified chapter EPUB, and writes *only* aggregate measurements.
Never prints/saves text, cookie values, chapter URLs or raw screenshots.
Same-source re-fetch is NOT an independent source-reader visual comparison.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
import zipfile

from tools.catalog_snapshot import load_provider
from tools.chapter_worker import file_sha256
from tools.checkpoint_queue import inspect_queue

_BODY = re.compile(r"<body\b[^>]*>", re.I)
_FIRST_H1 = re.compile(r"\s*<h1\b[^>]*>.*?</h1>", re.I | re.S)
_NONSPACE = re.compile(r"\s+", re.UNICODE)
_NOTE_WRAPPER = re.compile(r"〔注：(.*?)〕", re.S)


class BodyText(HTMLParser):
    def __init__(self, *, include_note_alt: bool = False):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.skip = 0
        self.include_note_alt = include_note_alt
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "body":
            self.in_body = True
        elif self.in_body and tag in {"style", "script", "noscript"}:
            self.skip += 1
        elif self.in_body and not self.skip and tag == "img" and self.include_note_alt:
            data = dict(attrs)
            path = str(data.get("src") or "").split("?", 1)[0].lower()
            alt = str(data.get("alt") or "")
            if path.endswith("note.png") and alt:
                self.parts.append(alt)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"style", "script", "noscript"} and self.skip:
            self.skip -= 1
        elif tag == "body":
            self.in_body = False

    def handle_data(self, data):
        if self.in_body and not self.skip:
            self.parts.append(data)


def normalized_body(xhtml: str, *, exported: bool = False) -> str:
    if exported:
        body = _BODY.search(xhtml)
        if body:
            suffix = xhtml[body.end():]
            first = _FIRST_H1.match(suffix)
            if first:
                xhtml = xhtml[:body.end()] + suffix[first.end():]
    collector = BodyText(include_note_alt=not exported)
    collector.feed(xhtml)
    s = unicodedata.normalize("NFC", "".join(collector.parts))
    if exported:
        # Visible substitution in exported EPUB is "〔注：alt〕"; compare the alt
        # text itself, not that presentation wrapper.
        s = _NOTE_WRAPPER.sub(lambda m: m.group(1), s)
    return _NONSPACE.sub("", s)


def compare_xhtml(source_xhtml: str, saved_xhtml: str) -> dict:
    src = normalized_body(source_xhtml)
    dest = normalized_body(saved_xhtml, exported=True)
    prefix = 0
    for a, b in zip(src, dest):
        if a != b:
            break
        prefix += 1
    suffix = 0
    for a, b in zip(reversed(src), reversed(dest)):
        if a != b:
            break
        suffix += 1
    match = src == dest
    return {
        "status": "SOURCE_TEXT_EXACT_AFTER_DEFINED_NORMALIZATION" if match
                  else "SOURCE_TEXT_DIFFERENCE_REVIEW_REQUIRED",
        "source_characters": len(src),
        "artifact_characters": len(dest),
        "exact": match,
        "same_prefix_characters": prefix,
        "same_suffix_characters": suffix,
        "similarity_ratio": 1.0 if match else round(
            SequenceMatcher(None, src, dest, autojunk=True).ratio(), 6
        ),
        "normalization": "NFC + Unicode whitespace removal + exported synthetic first h1 removed + note alt wrapper stripped",
    }


def _chapter_xhtml(epub: Path) -> str:
    with zipfile.ZipFile(epub) as z:
        if z.testzip() is not None:
            raise ValueError("EPUB_ZIP_CRC_FAIL")
        # Our chapter writer stores one source body in one text/chapter_0001.xhtml
        paths = [p for p in z.namelist()
                 if p.startswith("OEBPS/text/") and p.endswith(".xhtml")]
        if len(paths) != 1:
            raise ValueError("EXPECTED_SINGLE_CHAPTER")
        return z.read(paths[0]).decode("utf-8-sig", errors="strict")


def parse_checks(value: str, *, maximum: int = 6) -> list[tuple[int, str]]:
    checks = []
    for part in value.split(","):
        fragment = part.strip().split(":")
        if len(fragment) != 2:
            raise ValueError("CHECKS_EXPECT_ORDINAL_COLON_MODE")
        ordinal, mode = fragment
        n = int(ordinal)
        if not 1 <= n <= 500 or mode not in {"txt", "epub"}:
            raise ValueError("INVALID_CHAPTER_MODE")
        checks.append((n, mode))
    if not 1 <= len(checks) <= maximum or len({n for n, _ in checks}) != len(checks):
        raise ValueError("CHECK_COUNT_OR_DUPLICATE")
    return checks


def audit_live(
    *,
    book_dir: Path,
    cookie_file: Path,
    upstream_script: Path,
    upstream_sha: str,
    checks: list[tuple[int, str]],
    provider=None,
) -> dict:
    book_dir = book_dir.resolve()
    catalog_file = book_dir / "catalog.json"
    db_file = book_dir / "chapters.sqlite"
    if not catalog_file.is_file() or not db_file.is_file():
        raise FileNotFoundError("CATALOG_OR_QUEUE_MISSING")
    if not cookie_file.is_file():
        raise RuntimeError("LOGIN_REQUIRED")
    catalog = json.loads(catalog_file.read_text(encoding="utf-8"))
    if (catalog.get("upstream_sha") != upstream_sha or
            catalog.get("schema_version") != 1):
        raise RuntimeError("PINNED_SOURCE_SHA_OR_CATALOG_MISMATCH")
    selected = [r for r in catalog["chapters"] if r["selected_for_export"]]
    if not all(n <= len(selected) for n, _ in checks):
        raise ValueError("ORDINAL_OUT_OF_CATALOG_RANGE")

    with closing(sqlite3.connect(db_file)) as con:
        rows = con.execute(
            "SELECT ordinal,state,artifact_path,artifact_sha256 FROM chapters ORDER BY ordinal"
        ).fetchall()
    if len(rows) != len(selected) or any(r[0] != i+1 for i,r in enumerate(rows)):
        raise RuntimeError("QUEUE_ORDER_MISMATCH")
    info = inspect_queue(db_file)
    if info["complete"] != info["total_chapters"] or info["failed"] or info["pending"]:
        raise RuntimeError("INCOMPLETE_QUEUE")

    provider = provider or load_provider(upstream_script)
    client = provider.WeReadClient(
        cookie_file=cookie_file, cookie_string=None, save_cookies=cookie_file
    )
    if not client.renew():
        raise RuntimeError("LOGIN_REQUIRED")
    reader_url = "https://weread.qq.com/web/reader/" + str(catalog["book"]["reader_id"])
    state = provider.read_reader_state(client.get_text(reader_url, referer=reader_url))
    book_id = str(state.book_id)
    if book_id != str(catalog["book"]["formal_book_id"]):
        raise RuntimeError("FORMAL_BOOK_ID_CHANGED")
    raw_chapters = client.post_json(
        "https://weread.qq.com/web/book/chapterInfos",
        {"bookIds": [book_id]}, referer=reader_url
    )
    _, remote_chapters = provider.normalize_chapter_infos(raw_chapters, book_id)
    online_selected = [
        r for r in remote_chapters
        if int(r.get("wordCount") or 0) > 0 and r.get("title") != "封面"
    ]
    if [str(x["chapterUid"]) for x in online_selected] != [
        str(x["chapter_uid"]) for x in selected
    ]:
        raise RuntimeError("CHAPTER_CATALOG_DRIFT")

    results = []
    for ordinal, mode in checks:
        row = rows[ordinal - 1]
        _, saved_state, relative, sha = row
        if saved_state != "COMPLETE" or not relative or not sha:
            raise RuntimeError("CHAPTER_NOT_COMPLETE")
        target = (book_dir / relative).resolve()
        if not target.is_relative_to(book_dir) or not target.is_file():
            raise RuntimeError("ARTIFACT_MISSING")
        if file_sha256(target) != sha:
            raise RuntimeError("ARTIFACT_SHA_MISMATCH")
        record = online_selected[ordinal-1]
        title, source_xhtml, _css, _assets = provider.fetch_chapter(
            client, book_id=book_id, chapter=record,
            sleep_seconds=0.4, content_format=[mode]
        )
        data = compare_xhtml(source_xhtml, _chapter_xhtml(target))
        results.append({
            "ordinal": ordinal,
            "mode": mode,
            "source_kind": "live_authenticated_same_upstream",
            **data,
        })
    try:
        client.persist_cookies()
    except Exception:
        # Does not impact the read-only audit findings.
        pass

    passed = sum(1 for r in results if r["exact"])
    return {
        "status": "SOURCE_PARITY_EXACT_FOR_CHECKED_CHAPTERS" if passed == len(results)
                  else "SOURCE_PARITY_DIFFERENCES_REQUIRE_REVIEW",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "chapters_checked": len(results),
        "chapters_exact": passed,
        "chapters_with_differences": len(results) - passed,
        "results": results,
        "note": (
            "The comparison re-fetches text using the same authenticated upstream "
            "endpoints; it does not certify the full book or independently verify "
            "figure placement, note typography, or pixel-perfect reader parity."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Private source text parity audit")
    parser.add_argument("--book-dir", type=Path, required=True)
    parser.add_argument("--cookie-file", type=Path, required=True)
    parser.add_argument("--upstream-script", type=Path, required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--checks", default="19:txt,20:txt,21:txt")
    parser.add_argument("--live", action="store_true",
                        help="Explicitly permit bounded authenticated source requests")
    parser.add_argument("--output", type=Path, help="Private local JSON report")
    args = parser.parse_args()
    if not args.live:
        raise SystemExit("LIVE_SOURCE_FETCH_REQUIRES_EXPLICIT_FLAG")
    results = audit_live(
        book_dir=args.book_dir,
        cookie_file=args.cookie_file,
        upstream_script=args.upstream_script,
        upstream_sha=args.upstream_sha,
        checks=parse_checks(args.checks),
    )
    if args.output:
        dest = args.output.resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
