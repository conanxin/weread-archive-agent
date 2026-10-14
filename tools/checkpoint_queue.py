"""Local resumable chapter queue metadata. Does not fetch book content.

A queue is not an extraction engine: P2-B1 only persists the worklist with stable
chapter UIDs and statuses. Later workers may claim and complete chapter rows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS queue_info (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chapters (
  ordinal INTEGER PRIMARY KEY,
  chapter_uid TEXT UNIQUE NOT NULL,
  catalog_order INTEGER NOT NULL,
  chapter_title TEXT NOT NULL,
  provider_words INTEGER NOT NULL,
  state TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (state IN ('PENDING','RUNNING','FAILED','COMPLETE')),
  attempts INTEGER NOT NULL DEFAULT 0,
  artifact_path TEXT,
  artifact_sha256 TEXT,
  updated_at TEXT NOT NULL
);
"""


def _catalog_worklist(catalog: dict) -> list[dict]:
    if catalog.get("schema_version") != 1:
        raise ValueError("UNSUPPORTED_CATALOG_SCHEMA")
    chapters = catalog.get("chapters")
    totals = catalog.get("totals")
    if not isinstance(chapters, list) or not isinstance(totals, dict):
        raise ValueError("CATALOG_MALFORMED")
    seen: set[str] = set()
    work: list[dict] = []
    for row in chapters:
        if not row.get("selected_for_export", False):
            continue
        uid = str(row.get("chapter_uid") or "")
        if not uid or uid in seen:
            raise ValueError("DUPLICATE_OR_EMPTY_CHAPTER_UID")
        seen.add(uid)
        work.append(row)
    if len(work) != totals.get("selected_for_export") or not work:
        raise ValueError("CATALOG_SELECTION_MISMATCH")
    return work


def queue_report(conn: sqlite3.Connection, *, db_path: Path) -> dict:
    state_counts = {r[0]: r[1] for r in conn.execute(
        "SELECT state, COUNT(*) FROM chapters GROUP BY state"
    ).fetchall()}
    total = sum(state_counts.values())
    catalog_sha = conn.execute(
        "SELECT value FROM queue_info WHERE key='catalog_sha256'"
    ).fetchone()
    return {
        "status": "QUEUE_READY" if total else "QUEUE_EMPTY",
        "database": str(db_path),
        "total_chapters": total,
        "pending": state_counts.get("PENDING", 0),
        "running": state_counts.get("RUNNING", 0),
        "failed": state_counts.get("FAILED", 0),
        "complete": state_counts.get("COMPLETE", 0),
        "catalog_sha256": catalog_sha[0] if catalog_sha else None,
        "note": "QUEUE_READY 只代表持久化待处理目录；不是整本书已经提取或验收。",
    }


def init_queue(catalog_path: Path, db_path: Path) -> dict:
    if not catalog_path.is_file():
        raise FileNotFoundError("CATALOG_NOT_FOUND")
    raw = catalog_path.read_bytes()
    catalog = json.loads(raw.decode("utf-8"))
    work = _catalog_worklist(catalog)
    sha = hashlib.sha256(raw).hexdigest()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        conn.executescript(SCHEMA_SQL)
        old = [
            (r[0], r[1]) for r in conn.execute(
                "SELECT chapter_uid, catalog_order FROM chapters ORDER BY ordinal"
            ).fetchall()
        ]
        new = [(str(row["chapter_uid"]), int(row["order"])) for row in work]
        if old and old != new:
            raise ValueError("CATALOG_CHANGED_RECONCILIATION_REQUIRED")
        if not old:
            with conn:
                for ordinal, row in enumerate(work, 1):
                    conn.execute(
                        """INSERT INTO chapters
                        (ordinal,chapter_uid,catalog_order,chapter_title,provider_words,updated_at)
                        VALUES (?,?,?,?,?,?)""",
                        (ordinal, str(row["chapter_uid"]), int(row["order"]),
                         str(row["title"]), int(row["word_count"]), _now())
                    )
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO queue_info (key,value) VALUES (?,?)",
                ("catalog_sha256", sha),
            )
            conn.execute(
                "INSERT OR REPLACE INTO queue_info (key,value) VALUES (?,?)",
                ("book_title", str(catalog.get("book", {}).get("title") or "")),
            )
        return queue_report(conn, db_path=db_path)
    finally:
        conn.close()


def inspect_queue(db_path: Path) -> dict:
    if not db_path.is_file():
        raise FileNotFoundError("QUEUE_NOT_FOUND")
    conn = sqlite3.connect(db_path, timeout=10)
    try:
        return queue_report(conn, db_path=db_path)
    finally:
        conn.close()
