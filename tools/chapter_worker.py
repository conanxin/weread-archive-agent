"""P2-B2: one-chapter-at-a-time, resumable local WeRead worker.

The worker reuses the pinned upstream chapter extractor. Every chapter has a
separate raw EPUB checkpoint. Failed image repair never discards fetched text.
A chapter becomes COMPLETE only after EPUB structural validation and SHA256.
No whole-book merge, cloud upload, credential export, or public publication.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import posixpath
import shutil
import sqlite3
import sys
from typing import Any, Callable

from tools.catalog_snapshot import load_provider
from tools.checkpoint_queue import queue_report

GOOD_EPUB = "STRUCTURE_PASS_COMPLETENESS_UNVERIFIED"
BLOCK_CODES = {"LOGIN_REQUIRED", "ACCESS_RESTRICTED", "MANUAL_VERIFICATION_REQUIRED"}
MAX_RUN_CHAPTERS = 10


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def file_sha256(file: Path) -> str:
    h = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@contextmanager
def book_worker_lock(db_path: Path):
    """OS-level advisory single-book process lock, released even after crash."""
    lock_file = db_path.with_suffix(".worker.lock")
    with lock_file.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"1")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("WORKER_BUSY") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _ensure_error_code_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(chapters)")}
    if "error_code" not in cols:
        with conn:
            conn.execute("ALTER TABLE chapters ADD COLUMN error_code TEXT")


def _validate_local_identity(conn: sqlite3.Connection, catalog_path: Path) -> tuple[dict, list[dict]]:
    raw = catalog_path.read_bytes()
    catalog_sha = hashlib.sha256(raw).hexdigest()
    recorded = conn.execute(
        "SELECT value FROM queue_info WHERE key='catalog_sha256'"
    ).fetchone()
    if not recorded or recorded[0] != catalog_sha:
        raise ValueError("CATALOG_SNAPSHOT_HASH_MISMATCH")
    catalog = json.loads(raw.decode("utf-8"))
    if catalog.get("schema_version") != 1:
        raise ValueError("UNSUPPORTED_CATALOG_SCHEMA")
    eligible = [row for row in catalog["chapters"] if row.get("selected_for_export")]
    if not eligible or len(eligible) != catalog.get("totals", {}).get("selected_for_export"):
        raise ValueError("CATALOG_SELECTION_MISMATCH")
    existing = conn.execute(
        "SELECT ordinal, chapter_uid, catalog_order FROM chapters ORDER BY ordinal"
    ).fetchall()
    expected = [
        (i, str(row["chapter_uid"]), int(row["order"]))
        for i, row in enumerate(eligible, 1)
    ]
    if existing != expected:
        raise ValueError("CATALOG_CHANGED_RECONCILIATION_REQUIRED")
    return catalog, eligible


def _online_chapter_map(provider, client, reader_url: str, catalog: dict) -> dict[str, dict]:
    html = client.get_text(reader_url, referer=reader_url)
    state = provider.read_reader_state(html)
    book_id = str(state.book_id)
    if book_id != str(catalog["book"]["formal_book_id"]):
        raise ValueError("FORMAL_BOOK_ID_MISMATCH")
    payload = client.post_json(
        "https://weread.qq.com/web/book/chapterInfos",
        {"bookIds": [book_id]}, referer=reader_url,
    )
    _, chapters = provider.normalize_chapter_infos(payload, book_id)
    selected = [
        row for row in chapters
        if int(row.get("wordCount") or 0) > 0
        and str(row.get("title") or "") != "封面"
    ]
    want = [
        str(row["chapter_uid"])
        for row in catalog["chapters"] if row.get("selected_for_export")
    ]
    actual = [str(row["chapterUid"]) for row in selected]
    if actual != want:
        raise ValueError("UPSTREAM_CATALOG_CHANGED")
    return {str(row["chapterUid"]): row for row in selected}


def _error_code(exc: Exception) -> str:
    """Stable non-sensitive categories. Never output exception text or URLs."""
    message = str(exc).lower()
    for code in (
        "IMAGE_ASSETS_INCOMPLETE", "CONTENT_SUSPICIOUS", "STRUCTURE_INCOMPLETE",
        "CATALOG_CHANGED_RECONCILIATION_REQUIRED", "UPSTREAM_CATALOG_CHANGED",
        "FORMAL_BOOK_ID_MISMATCH", "WORKER_BUSY",
    ):
        if code.lower() in message:
            return code
    if any(x in message for x in ("login", "cookie", "renewal", "未登录", "登录失效", "401")):
        return "LOGIN_REQUIRED"
    if any(x in message for x in ("captcha", "verify your identity", "验证码", "-2041")):
        return "MANUAL_VERIFICATION_REQUIRED"
    if any(x in message for x in ("403", "forbidden", "permission denied", "access denied", "需要购买")):
        return "ACCESS_RESTRICTED"
    if "404" in message or "no chapters" in message:
        return "WEB_UNAVAILABLE"
    return "UPSTREAM_ERROR"


def _set_state(
    conn: sqlite3.Connection, ordinal: int, state: str,
    *, error_code: str | None = None, artifact_path: str | None = None,
    artifact_sha256: str | None = None,
) -> None:
    with conn:
        conn.execute(
            """UPDATE chapters
            SET state=?, error_code=?, artifact_path=COALESCE(?, artifact_path),
                artifact_sha256=COALESCE(?, artifact_sha256), updated_at=?
            WHERE ordinal=?""",
            (state, error_code, artifact_path, artifact_sha256, utc_now(), ordinal),
        )


def _valid_chapter(
    file: Path, *, inspector: Callable, provider_words: int,
) -> tuple[bool, dict, str | None]:
    inspected = inspector(file, expected=1)
    if inspected["status"] != GOOD_EPUB:
        return False, inspected, "STRUCTURE_INCOMPLETE"
    # The provider's wordCount estimate is not an exact text length. Only
    # reject extreme truncation in a substantive chapter; do not reject
    # 7-character divider chapters or 100-character copyright notices.
    if provider_words >= 1000 and inspected.get("text_characters", 0) < provider_words * 0.10:
        return False, inspected, "CONTENT_SUSPICIOUS"
    return True, inspected, None


def _chapter_paths(directory: Path, ordinal: int) -> tuple[Path, Path, Path]:
    chapter_dir = directory / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{ordinal:04d}"
    return (
        chapter_dir / f"{stem}.partial.epub",
        chapter_dir / f"{stem}.images.partial.epub",
        chapter_dir / f"{stem}.epub",
    )


def _resume_or_capture(
    *,
    directory: Path, row: dict, chapter: dict, provider,
    client, book_id: str, sleep: float, inspector: Callable,
    repairer: Callable, cookie_file: Path, max_images: int,
) -> tuple[Path, dict, bool]:
    ordinal = int(row["ordinal"])
    provider_words = int(row["provider_words"])
    raw, image_partial, final = _chapter_paths(directory, ordinal)
    if final.is_file():
        ok, checked, code = _valid_chapter(
            final, inspector=inspector, provider_words=provider_words
        )
        if ok:
            return final, checked, True
        raise ValueError(code or "STRUCTURE_INCOMPLETE")

    # A checkpoint from a previous attempt is usable without refetching text.
    raw_usable = False
    if raw.is_file():
        checked = inspector(raw, expected=1)
        raw_usable = checked.get("zip_crc_ok") and checked.get("spine_chapters") == 1

    if not raw_usable:
        title, xhtml, css, assets = provider.fetch_chapter(
            client, book_id=book_id, chapter=chapter,
            sleep_seconds=sleep, content_format=["auto"],
        )
        # Persist raw chapter atomically. Interrupted raw writes are not adopted.
        staged = raw.with_name(raw.name + ".writing")
        provider.write_epub(
            staged, title=title, author="", chapters=[(title, xhtml, assets)],
            css=css,
        )
        checked = inspector(staged, expected=1)
        if not checked.get("zip_crc_ok") or checked.get("spine_chapters") != 1:
            raise ValueError("STRUCTURE_INCOMPLETE")
        os.replace(staged, raw)

    checked = inspector(raw, expected=1)
    source = raw
    if checked["status"] != GOOD_EPUB and (
        checked.get("broken_images") or checked.get("remote_images")
    ):
        repairer(
            raw, image_partial, cookie_file=cookie_file,
            max_images=max_images,
        )
        source = image_partial

    ok, checked, code = _valid_chapter(
        source, inspector=inspector, provider_words=provider_words
    )
    if not ok:
        if checked.get("broken_images") or checked.get("remote_images"):
            raise ValueError("IMAGE_ASSETS_INCOMPLETE")
        raise ValueError(code or "STRUCTURE_INCOMPLETE")

    # Original .partial.epub is retained as the text-fetch checkpoint.
    staged_final = final.with_name(final.name + ".writing")
    shutil.copyfile(source, staged_final)
    os.replace(staged_final, final)
    return final, checked, False


def run_chapter_worker(
    *,
    db_path: Path,
    catalog_path: Path,
    reader_url: str,
    cookie_file: Path,
    upstream_script: Path,
    upstream_sha: str | None,
    inspector: Callable,
    repairer: Callable,
    limit: int = 1,
    retry_failed: bool = False,
    sleep: float = 0.4,
    max_images: int = 500,
    provider=None,
) -> dict:
    if not (1 <= limit <= MAX_RUN_CHAPTERS):
        raise ValueError("INVALID_CHAPTER_LIMIT")
    if sleep < 0 or max_images < 1:
        raise ValueError("INVALID_WORKER_OPTIONS")
    if not db_path.is_file() or not catalog_path.is_file():
        raise FileNotFoundError("CATALOG_OR_QUEUE_MISSING")
    if not cookie_file.is_file():
        return {"status": "LOGIN_REQUIRED", "attempted": 0}
    with book_worker_lock(db_path):
        conn = sqlite3.connect(db_path, timeout=10)
        try:
            _ensure_error_code_column(conn)
            catalog, rows = _validate_local_identity(conn, catalog_path)
            pinned = catalog.get("upstream_sha")
            if pinned and upstream_sha != pinned:
                raise ValueError("UPSTREAM_SHA_MISMATCH")
            # Never automatically reset a finished chapter. Re-check recorded
            # SHA256 and file presence on each resumed invocation.
            invalid_completed = []
            existing = conn.execute(
                "SELECT ordinal,artifact_path,artifact_sha256 FROM chapters WHERE state='COMPLETE'"
            ).fetchall()
            for ordinal, relpath, digest in existing:
                path = db_path.parent / relpath if relpath else None
                if (path is None or not path.is_file() or not digest
                        or file_sha256(path) != digest):
                    invalid_completed.append(ordinal)
            if invalid_completed:
                return {
                    "status": "COMPLETED_ARTIFACT_INTEGRITY_ERROR",
                    "affected_ordinals": invalid_completed,
                    **queue_report(conn, db_path=db_path),
                }

            # Book-level OS lock ensures these states are left over from a
            # previously interrupted process rather than an active peer.
            with conn:
                conn.execute(
                    """UPDATE chapters SET state='FAILED',error_code='INTERRUPTED',
                        updated_at=? WHERE state='RUNNING'""", (utc_now(),)
                )
            candidates = conn.execute(
                """SELECT ordinal,chapter_uid,chapter_title,provider_words,
                          state,attempts FROM chapters
                   WHERE state='PENDING' OR (state='FAILED' AND ?=1)
                   ORDER BY ordinal""", (int(retry_failed),)
            ).fetchall()
            if not candidates:
                return {
                    "status": "WORKER_IDLE",
                    "attempted": 0, "completed_now": 0,
                    **queue_report(conn, db_path=db_path),
                }

            provider = provider or load_provider(upstream_script)
            client = provider.WeReadClient(
                cookie_file=cookie_file, cookie_string=None,
                save_cookies=cookie_file,
            )
            try:
                if not client.renew():
                    return {"status": "LOGIN_REQUIRED", "attempted": 0}
                chapters_by_uid = _online_chapter_map(
                    provider, client, reader_url, catalog
                )
            except Exception as exc:
                return {
                    "status": "WORKER_BLOCKED",
                    "reason_code": _error_code(exc),
                    "attempted": 0,
                    **queue_report(conn, db_path=db_path),
                }

            attempted = 0
            completed_now = 0
            reused_checkpoints = 0
            failures: list[dict] = []
            book_id = str(catalog["book"]["formal_book_id"])
            for ordinal, uid, title, provider_words, state, attempts in candidates[:limit]:
                with conn:
                    conn.execute(
                        """UPDATE chapters SET state='RUNNING', attempts=attempts+1,
                            error_code=NULL,updated_at=? WHERE ordinal=?""",
                        (utc_now(), ordinal),
                    )
                attempted += 1
                try:
                    path, checked, reused = _resume_or_capture(
                        directory=db_path.parent,
                        row={"ordinal": ordinal, "provider_words": provider_words},
                        chapter=chapters_by_uid[uid], provider=provider,
                        client=client, book_id=book_id, sleep=sleep,
                        inspector=inspector, repairer=repairer,
                        cookie_file=cookie_file, max_images=max_images,
                    )
                    rel_path = path.relative_to(db_path.parent).as_posix()
                    digest = file_sha256(path)
                    _set_state(
                        conn, ordinal, "COMPLETE",
                        artifact_path=rel_path, artifact_sha256=digest,
                    )
                    completed_now += 1
                    if reused:
                        reused_checkpoints += 1
                except Exception as exc:
                    code = _error_code(exc)
                    _set_state(conn, ordinal, "FAILED", error_code=code)
                    failures.append({"ordinal": ordinal, "reason_code": code})
                    # No high-rate retry loops or continued calls after an
                    # access, login, chapter, or image issue.
                    break
            try:
                client.persist_cookies()
            except Exception:
                # A failed cookie refresh must not erase validated local files.
                pass
            summary = queue_report(conn, db_path=db_path)
            status = "WORKER_PARTIAL" if failures else "WORKER_PROGRESS"
            if not failures and summary["complete"] == summary["total_chapters"]:
                status = "CHAPTERS_FETCHED_PENDING_FULL_QA"
            return {
                **summary,
                "status": status,
                "attempted": attempted,
                "completed_now": completed_now,
                "reused_finished_artifacts": reused_checkpoints,
                "failures": failures,
                "note": (
                    "章节存储通过门禁不代表整书完整；本阶段没有 EPUB 合并/出版/云盘上传。"
                ),
            }
        finally:
            conn.close()
