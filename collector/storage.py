from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .normalizer import normalize_type_hint

VALID_STATUSES = {"new", "approved", "rejected", "exported"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                chat_ref TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                backfill_limit INTEGER NOT NULL DEFAULT 500,
                last_backfill_message_id INTEGER,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL UNIQUE,
                username TEXT,
                name TEXT,
                type_hint TEXT,
                source_chat TEXT,
                source_message_id INTEGER,
                source_message_date TEXT,
                text_snippet TEXT,
                confidence REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'new',
                reject_reason TEXT,
                review_note TEXT,
                title TEXT,
                description TEXT,
                type TEXT,
                count INTEGER,
                telegram_id INTEGER,
                private INTEGER DEFAULT 0,
                valid INTEGER DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                enriched_at TEXT,
                exported_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
            CREATE INDEX IF NOT EXISTS idx_candidates_type ON candidates(type, type_hint);
            CREATE INDEX IF NOT EXISTS idx_candidates_count ON candidates(count);
            CREATE INDEX IF NOT EXISTS idx_candidates_username ON candidates(username);
            CREATE INDEX IF NOT EXISTS idx_candidates_seen ON candidates(last_seen_at);

            CREATE TABLE IF NOT EXISTS export_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL,
                total INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )


def upsert_source(db_path: Path, name: str, chat_ref: str, enabled: bool = True, backfill_limit: int = 500) -> int:
    now = utc_now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sources (name, chat_ref, enabled, backfill_limit, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_ref) DO UPDATE SET
                name=excluded.name,
                enabled=excluded.enabled,
                backfill_limit=excluded.backfill_limit,
                updated_at=excluded.updated_at
            """,
            (name.strip(), chat_ref.strip(), 1 if enabled else 0, int(backfill_limit or 500), now, now),
        )
        row = conn.execute("SELECT id FROM sources WHERE chat_ref=?", (chat_ref.strip(),)).fetchone()
        return int(row["id"])


def list_sources(db_path: Path, enabled: bool | None = None) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        sql = "SELECT * FROM sources"
        params: list[Any] = []
        if enabled is not None:
            sql += " WHERE enabled=?"
            params.append(1 if enabled else 0)
        sql += " ORDER BY enabled DESC, id DESC"
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def get_source(db_path: Path, source_id: int) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
        return dict(row) if row else None


def set_source_enabled(db_path: Path, source_id: int, enabled: bool) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE sources SET enabled=?, updated_at=? WHERE id=?",
            (1 if enabled else 0, utc_now(), source_id),
        )


def delete_source(db_path: Path, source_id: int) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))


def update_source_error(db_path: Path, source_id: int, error: str | None) -> None:
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE sources SET last_error=?, updated_at=? WHERE id=?",
            (error, utc_now(), source_id),
        )


def update_source_backfill(db_path: Path, source_id: int, last_message_id: int | None) -> None:
    if last_message_id is None:
        return
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE sources SET last_backfill_message_id=?, updated_at=? WHERE id=?",
            (last_message_id, utc_now(), source_id),
        )


def upsert_candidate(db_path: Path, item: dict[str, Any]) -> int:
    now = utc_now()
    url = item["url"].strip()
    username = (item.get("username") or "").strip() or None
    type_hint = normalize_type_hint(item.get("type_hint"))
    confidence = float(item.get("confidence") or 0)

    with connect(db_path) as conn:
        existing = conn.execute("SELECT id FROM candidates WHERE url=?", (url,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE candidates SET
                    username=COALESCE(?, username),
                    name=COALESCE(?, name),
                    type_hint=COALESCE(?, type_hint),
                    source_chat=COALESCE(?, source_chat),
                    source_message_id=COALESCE(?, source_message_id),
                    source_message_date=COALESCE(?, source_message_date),
                    text_snippet=COALESCE(?, text_snippet),
                    confidence=MAX(confidence, ?),
                    last_seen_at=?
                WHERE url=?
                """,
                (
                    username,
                    item.get("name"),
                    type_hint,
                    item.get("source_chat"),
                    item.get("source_message_id"),
                    item.get("source_message_date"),
                    item.get("text_snippet"),
                    confidence,
                    now,
                    url,
                ),
            )
            return int(existing["id"])

        conn.execute(
            """
            INSERT INTO candidates (
                url, username, name, type_hint, source_chat, source_message_id,
                source_message_date, text_snippet, confidence, status,
                first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
            """,
            (
                url,
                username,
                item.get("name"),
                type_hint,
                item.get("source_chat"),
                item.get("source_message_id"),
                item.get("source_message_date"),
                item.get("text_snippet"),
                confidence,
                now,
                now,
            ),
        )
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def update_candidate_meta(db_path: Path, url: str, meta: dict[str, Any]) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE candidates SET
                title=COALESCE(?, title),
                description=COALESCE(?, description),
                type=COALESCE(?, type),
                type_hint=COALESCE(?, type_hint),
                count=COALESCE(?, count),
                telegram_id=COALESCE(?, telegram_id),
                username=COALESCE(?, username),
                valid=?,
                private=?,
                enriched_at=?
            WHERE url=?
            """,
            (
                meta.get("title"),
                meta.get("description"),
                meta.get("type"),
                meta.get("type"),
                meta.get("count"),
                meta.get("telegram_id"),
                meta.get("username"),
                1 if meta.get("valid") else 0,
                1 if meta.get("private") else 0,
                utc_now(),
                url,
            ),
        )


def get_candidate(db_path: Path, candidate_id: int) -> dict[str, Any] | None:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        return dict(row) if row else None


def set_candidate_status(db_path: Path, candidate_id: int, status: str, note: str = "", reject_reason: str = "") -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"无效状态: {status}")
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE candidates
            SET status=?, review_note=?, reject_reason=?
            WHERE id=?
            """,
            (status, note.strip(), reject_reason.strip(), candidate_id),
        )


def batch_set_status(db_path: Path, ids: Iterable[int], status: str) -> int:
    if status not in VALID_STATUSES:
        raise ValueError(f"无效状态: {status}")
    id_list = [int(i) for i in ids if str(i).strip()]
    if not id_list:
        return 0
    placeholders = ",".join("?" for _ in id_list)
    with connect(db_path) as conn:
        cur = conn.execute(
            f"UPDATE candidates SET status=? WHERE id IN ({placeholders})",
            [status, *id_list],
        )
        return int(cur.rowcount or 0)


def list_candidates(
    db_path: Path,
    status: str | None = None,
    type_value: str | None = None,
    q: str | None = None,
    min_count: int | None = None,
    max_count: int | None = None,
    min_confidence: float | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where = []
    params: list[Any] = []

    if status:
        where.append("status=?")
        params.append(status)
    if type_value:
        where.append("(type=? OR type_hint=?)")
        params.extend([type_value, type_value])
    if q:
        like = f"%{q.strip()}%"
        where.append(
            "(url LIKE ? OR username LIKE ? OR name LIKE ? OR title LIKE ? OR description LIKE ? OR text_snippet LIKE ?)"
        )
        params.extend([like, like, like, like, like, like])
    if min_count is not None:
        where.append("COALESCE(count, 0) >= ?")
        params.append(int(min_count))
    if max_count is not None:
        where.append("COALESCE(count, 0) <= ?")
        params.append(int(max_count))
    if min_confidence is not None:
        where.append("confidence >= ?")
        params.append(float(min_confidence))

    where_sql = " WHERE " + " AND ".join(where) if where else ""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))

    with connect(db_path) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM candidates{where_sql}", params).fetchone()[0])
        rows = conn.execute(
            f"""
            SELECT *
            FROM candidates
            {where_sql}
            ORDER BY
                CASE status
                    WHEN 'new' THEN 1
                    WHEN 'approved' THEN 2
                    WHEN 'rejected' THEN 3
                    WHEN 'exported' THEN 4
                    ELSE 5
                END,
                confidence DESC,
                COALESCE(count, 0) DESC,
                last_seen_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
        return [dict(row) for row in rows], total


def stats(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        by_status = {
            row["status"]: int(row["count"])
            for row in conn.execute("SELECT status, COUNT(*) AS count FROM candidates GROUP BY status").fetchall()
        }
        total = int(conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0])
        sources = int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        enabled_sources = int(conn.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0])
        return {
            "total": total,
            "new": by_status.get("new", 0),
            "approved": by_status.get("approved", 0),
            "rejected": by_status.get("rejected", 0),
            "exported": by_status.get("exported", 0),
            "sources": sources,
            "enabled_sources": enabled_sources,
        }


def mark_exported(db_path: Path, ids: list[int], file_path: str, status: str) -> None:
    if not ids:
        return
    now = utc_now()
    placeholders = ",".join("?" for _ in ids)
    with connect(db_path) as conn:
        conn.execute(
            f"UPDATE candidates SET status='exported', exported_at=? WHERE id IN ({placeholders})",
            [now, *ids],
        )
        conn.execute(
            "INSERT INTO export_runs (file_path, status, total, created_at) VALUES (?, ?, ?, ?)",
            (file_path, status, len(ids), now),
        )
