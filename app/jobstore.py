"""SQLite-backed job store: 24h TTL dedup guard + processing history.

Replaces the old DynamoDB-backed app/history.py now that this runs as a
plain k3s service instead of AWS Lambda — single file (settings.db_path),
no external database needed. A module-level threading.Lock serializes
claim()/mark_*() calls; simple and plenty fast for the job volumes this
runs (a handful of concurrent yt-dlp/AssemblyAI jobs, not a high-throughput
table).

Same two jobs as before:
1. **Dedup guard** — ``claim()`` atomically checks-and-writes a row with a
   24h TTL (``expires_at``, checked explicitly — nothing here auto-deletes
   expired rows, so re-claiming an expired id just overwrites it).
2. **History for filtering** — ``get()``/``list_recent()`` back the API's
   GET /jobs and GET /jobs/{id} endpoints directly.
"""

import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.config import settings

_TTL_SECONDS = 24 * 60 * 60
_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    transcript_source TEXT,
    data_dir TEXT,
    s3_uri TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
"""

_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN s3_uri TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists — db file predates S3 sync being added
    conn.commit()
    return conn


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect()
    return _conn


def claim(
    id_: str, source: str, title: str, conn: sqlite3.Connection | None = None
) -> bool:
    """Atomically claims id_ for processing.

    Returns True if this call claimed it (no unexpired row existed) —
    processing should proceed. Returns False if it's a duplicate within the
    last 24h — the caller should skip processing entirely.
    """
    conn = conn or _db()
    now = int(time.time())
    with _lock:
        row = conn.execute(
            "SELECT expires_at FROM jobs WHERE id = ?", (id_,)
        ).fetchone()
        if row is not None and row["expires_at"] >= now:
            return False

        iso_now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO jobs (id, source, title, status, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, 'processing', ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source = excluded.source,
                title = excluded.title,
                status = 'processing',
                transcript_source = NULL,
                data_dir = NULL,
                error_message = NULL,
                updated_at = excluded.updated_at,
                expires_at = excluded.expires_at
            """,
            (id_, source, title, iso_now, iso_now, now + _TTL_SECONDS),
        )
        conn.commit()
    return True


def mark_completed(
    id_: str,
    transcript_source: str,
    data_dir: str,
    s3_uri: str | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    conn = conn or _db()
    now = int(time.time())
    with _lock:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'completed', transcript_source = ?, data_dir = ?,
                s3_uri = ?, updated_at = ?, expires_at = ?
            WHERE id = ?
            """,
            (
                transcript_source,
                str(data_dir),
                s3_uri,
                datetime.now(timezone.utc).isoformat(),
                now + _TTL_SECONDS,
                id_,
            ),
        )
        conn.commit()


def mark_failed(id_: str, error: str, conn: sqlite3.Connection | None = None) -> None:
    """Upserts an error record — also covers failures before claim() ran."""
    conn = conn or _db()
    now = int(time.time())
    iso_now = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn.execute(
            """
            INSERT INTO jobs (id, source, title, status, error_message, created_at, updated_at, expires_at)
            VALUES (?, '', '', 'error', ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = 'error',
                error_message = excluded.error_message,
                updated_at = excluded.updated_at,
                expires_at = excluded.expires_at
            """,
            (id_, error, iso_now, iso_now, now + _TTL_SECONDS),
        )
        conn.commit()


def get(id_: str, conn: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    conn = conn or _db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (id_,)).fetchone()
    return dict(row) if row is not None else None


def list_recent(
    limit: int = 50, conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    conn = conn or _db()
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]
