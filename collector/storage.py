from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .normalizer import canonical_url_from_username, canonical_username, normalize_tg_link, normalize_type_hint

VALID_STATUSES = {"new", "approved", "rejected", "exported"}
STATUS_PRIORITY = {"approved": 0, "new": 1, "exported": 2, "rejected": 3}


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


def _first_value(rows: list[sqlite3.Row], key: str) -> Any:
    for row in rows:
        value = row[key]
        if value not in (None, ""):
            return value
    return None


def _username_from_row(row: sqlite3.Row | dict[str, Any]) -> str | None:
    username = canonical_username(row["username"] if row["username"] else None)
    if not username and row["url"]:
        link = normalize_tg_link(str(row["url"]))
        if not link.rejected:
            username = link.username
    return username


def _resource_key(row: sqlite3.Row | dict[str, Any]) -> str:
    username = _username_from_row(row)
    if username:
        return f"username:{username}"
    return f"url:{str(row['url']).strip().lower()}"


def _status_sort_value(row: sqlite3.Row) -> tuple[int, int, int, float, int]:
    count = row["count"] if row["count"] is not None else -1
    return (
        STATUS_PRIORITY.get(row["status"], 9),
        -int(row["valid"] or 0),
        -int(count or 0),
        -float(row["confidence"] or 0),
        int(row["id"]),
    )


def _ensure_unique_indexes(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_url_lower_unique ON candidates(lower(url))")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_candidates_username_lower_unique ON candidates(lower(username)) WHERE username IS NOT NULL"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS rejected_resources (
            username TEXT PRIMARY KEY,
            url TEXT,
            reason TEXT,
            created_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rejected_resources_seen ON rejected_resources(last_seen_at)")


def _remember_rejected_username(conn: sqlite3.Connection, username: str | None, reason: str | None = None) -> None:
    username = canonical_username(username)
    if not username:
        return
    now = utc_now()
    conn.execute(
        """
        INSERT INTO rejected_resources (username, url, reason, created_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            reason=COALESCE(excluded.reason, rejected_resources.reason),
            last_seen_at=excluded.last_seen_at
        """,
        (username, canonical_url_from_username(username), reason or "rejected", now, now),
    )


def _remember_existing_rejected_candidates(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT username, url, reject_reason FROM candidates WHERE status='rejected'").fetchall()
    for row in rows:
        username = canonical_username(row["username"])
        if not username and row["url"]:
            link = normalize_tg_link(str(row["url"]))
            if not link.rejected:
                username = link.username
        _remember_rejected_username(conn, username, row["reject_reason"] or "rejected")


def _is_username_rejected(conn: sqlite3.Connection, username: str | None) -> bool:
    username = canonical_username(username)
    if not username:
        return False
    row = conn.execute("SELECT 1 FROM rejected_resources WHERE username=? LIMIT 1", (username,)).fetchone()
    if row:
        conn.execute("UPDATE rejected_resources SET last_seen_at=? WHERE username=?", (utc_now(), username))
        return True
    return False


def cleanup_candidate_duplicates_conn(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT * FROM candidates ORDER BY id ASC").fetchall()
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in rows:
        groups.setdefault(_resource_key(row), []).append(row)

    duplicate_groups = 0
    removed = 0
    normalized = 0

    for group_rows in groups.values():
        sorted_rows = sorted(group_rows, key=_status_sort_value)
        survivor = sorted_rows[0]
        duplicates = sorted_rows[1:]

        if duplicates:
            duplicate_groups += 1
            duplicate_ids = [int(row["id"]) for row in duplicates]
            placeholders = ",".join("?" for _ in duplicate_ids)
            conn.execute(f"DELETE FROM candidates WHERE id IN ({placeholders})", duplicate_ids)
            removed += len(duplicate_ids)

        username = canonical_username(_first_value(sorted_rows, "username"))
        if not username:
            for row in sorted_rows:
                link = normalize_tg_link(str(row["url"] or ""))
                if not link.rejected:
                    username = link.username
                    break

        canonical_url = canonical_url_from_username(username) if username else str(survivor["url"]).strip()
        counts = [int(row["count"]) for row in sorted_rows if row["count"] is not None]
        best_count = max(counts) if counts else None
        best_confidence = max(float(row["confidence"] or 0) for row in sorted_rows)
        valid = max(int(row["valid"] or 0) for row in sorted_rows)
        private = 1 if all(int(row["private"] or 0) for row in sorted_rows) else 0
        first_seen = min(str(row["first_seen_at"]) for row in sorted_rows if row["first_seen_at"])
        last_seen = max(str(row["last_seen_at"]) for row in sorted_rows if row["last_seen_at"])

        conn.execute(
            """
            UPDATE candidates SET
                url=?, username=COALESCE(?, username), name=COALESCE(?, name),
                type_hint=COALESCE(?, type_hint), source_chat=COALESCE(?, source_chat),
                source_message_id=COALESCE(?, source_message_id), source_message_date=COALESCE(?, source_message_date),
                text_snippet=COALESCE(?, text_snippet), confidence=?, status=?,
                reject_reason=COALESCE(?, reject_reason), review_note=COALESCE(?, review_note),
                title=COALESCE(?, title), description=COALESCE(?, description), type=COALESCE(?, type),
                count=COALESCE(?, count), telegram_id=COALESCE(?, telegram_id), private=?, valid=?,
                first_seen_at=?, last_seen_at=?, enriched_at=COALESCE(?, enriched_at), exported_at=COALESCE(?, exported_at)
            WHERE id=?
            """,
            (
                canonical_url, username, _first_value(sorted_rows, "name"), _first_value(sorted_rows, "type_hint"),
                _first_value(sorted_rows, "source_chat"), _first_value(sorted_rows, "source_message_id"),
                _first_value(sorted_rows, "source_message_date"), _first_value(sorted_rows, "text_snippet"),
                best_confidence, survivor["status"], _first_value(sorted_rows, "reject_reason"),
                _first_value(sorted_rows, "review_note"), _first_value(sorted_rows, "title"),
                _first_value(sorted_rows, "description"), _first_value(sorted_rows, "type"), best_count,
                _first_value(sorted_rows, "telegram_id"), private, valid, first_seen, last_seen,
                _first_value(sorted_rows, "enriched_at"), _first_value(sorted_rows, "exported_at"), int(survivor["id"]),
            ),
        )
        if survivor["status"] == "rejected":
            _remember_rejected_username(conn, username, _first_value(sorted_rows, "reject_reason") or "rejected")
        normalized += 1

    return {"groups": duplicate_groups, "removed": removed, "normalized": normalized}


def cleanup_candidate_duplicates(db_path: Path) -> dict[str, int]:
    with connect(db_path) as conn:
        _ensure_unique_indexes(conn)
        result = cleanup_candidate_duplicates_conn(conn)
        _remember_existing_rejected_candidates(conn)
        return result


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
        _ensure_unique_indexes(conn)
        cleanup_candidate_duplicates_conn(conn)
        _remember_existing_rejected_candidates(conn)


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
        conn.execute("UPDATE sources SET enabled=?, updated_at=? WHERE id=?", (1 if enabled else 0, utc_now(), source_id))


def delete_source(db_path: Path, source_id: int) -> None:
    with connect(db_path) as conn:
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))


def update_source_error(db_path: Path, source_id: int, error: str | None) -> None:
    with connect(db_path) as conn:
        conn.execute("UPDATE sources SET last_error=?, updated_at=? WHERE id=?", (error, utc_now(), source_id))


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
    raw_url = str(item["url"]).strip()
    link = normalize_tg_link(raw_url)
    if link.rejected:
        raise ValueError(f"无效 Telegram 链接：{raw_url} / {link.reject_reason}")
    url = link.url
    username = canonical_username(item.get("username")) or link.username
    type_hint = normalize_type_hint(item.get("type_hint"))
    confidence = float(item.get("confidence") or 0)

    with connect(db_path) as conn:
        _ensure_unique_indexes(conn)
        existing = conn.execute(
            """
            SELECT id, status FROM candidates
            WHERE lower(url)=lower(?) OR lower(username)=lower(?)
            ORDER BY id ASC
            LIMIT 1
            """,
            (url, username),
        ).fetchone()

        if existing and existing["status"] == "rejected":
            _remember_rejected_username(conn, username, "already_rejected")
            return int(existing["id"])

        if _is_username_rejected(conn, username):
            return 0

        if existing:
            conn.execute(
                """
                UPDATE candidates SET
                    url=?, username=COALESCE(?, username), name=COALESCE(?, name), type_hint=COALESCE(?, type_hint),
                    source_chat=COALESCE(?, source_chat), source_message_id=COALESCE(?, source_message_id),
                    source_message_date=COALESCE(?, source_message_date), text_snippet=COALESCE(?, text_snippet),
                    confidence=MAX(confidence, ?), last_seen_at=?
                WHERE id=?
                """,
                (
                    url, username, item.get("name"), type_hint, item.get("source_chat"), item.get("source_message_id"),
                    item.get("source_message_date"), item.get("text_snippet"), confidence, now, int(existing["id"]),
                ),
            )
            return int(existing["id"])

        conn.execute(
            """
            INSERT INTO candidates (
                url, username, name, type_hint, source_chat, source_message_id,
                source_message_date, text_snippet, confidence, status, first_seen_at, last_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
            """,
            (
                url, username, item.get("name") or username, type_hint, item.get("source_chat"), item.get("source_message_id"),
                item.get("source_message_date"), item.get("text_snippet"), confidence, now, now,
            ),
        )
        return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def update_candidate_meta(db_path: Path, url: str, meta: dict[str, Any]) -> None:
    username = canonical_username(meta.get("username"))
    link = normalize_tg_link(url)
    if not username and not link.rejected:
        username = link.username
    canonical_url = canonical_url_from_username(username) if username else (link.url if not link.rejected else url)
    count = meta.get("count")
    count_value = int(count) if isinstance(count, int) and count >= 0 else None

    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE candidates SET
                url=COALESCE(?, url), title=COALESCE(?, title), description=COALESCE(?, description),
                type=COALESCE(?, type), type_hint=COALESCE(?, type_hint),
                count=CASE
                    WHEN ? IS NULL THEN count
                    WHEN count IS NULL OR count=0 THEN ?
                    WHEN ? > count THEN ?
                    ELSE count
                END,
                telegram_id=COALESCE(?, telegram_id), username=COALESCE(?, username),
                valid=?, private=?, enriched_at=?
            WHERE lower(url)=lower(?) OR lower(username)=lower(?)
            """,
            (
                canonical_url, meta.get("title"), meta.get("description"), meta.get("type"), meta.get("type"),
                count_value, count_value, count_value, count_value, meta.get("telegram_id"), username,
                1 if meta.get("valid") else 0, 1 if meta.get("private") else 0, utc_now(), url, username or "",
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
            "UPDATE candidates SET status=?, review_note=?, reject_reason=? WHERE id=?",
            (status, note.strip(), reject_reason.strip(), candidate_id),
        )
        if status == "rejected":
            row = conn.execute("SELECT username, url, reject_reason FROM candidates WHERE id=?", (candidate_id,)).fetchone()
            if row:
                _remember_rejected_username(conn, _username_from_row(row), row["reject_reason"] or "rejected")


def batch_set_status(db_path: Path, ids: Iterable[int], status: str) -> int:
    if status not in VALID_STATUSES:
        raise ValueError(f"无效状态: {status}")
    id_list = [int(i) for i in ids if str(i).strip()]
    if not id_list:
        return 0
    placeholders = ",".join("?" for _ in id_list)
    with connect(db_path) as conn:
        if status == "rejected":
            rows = conn.execute(f"SELECT username, url, reject_reason FROM candidates WHERE id IN ({placeholders})", id_list).fetchall()
            for row in rows:
                _remember_rejected_username(conn, _username_from_row(row), row["reject_reason"] or "rejected")
        cur = conn.execute(f"UPDATE candidates SET status=? WHERE id IN ({placeholders})", [status, *id_list])
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
        where.append("(url LIKE ? OR username LIKE ? OR name LIKE ? OR title LIKE ? OR description LIKE ? OR text_snippet LIKE ?)")
        params.extend([like, like, like, like, like, like])
    if min_count is not None:
        where.append("count IS NOT NULL AND count >= ?")
        params.append(int(min_count))
    if max_count is not None:
        where.append("count IS NOT NULL AND count <= ?")
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
            SELECT * FROM candidates
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
        unknown_count = int(conn.execute("SELECT COUNT(*) FROM candidates WHERE count IS NULL").fetchone()[0])
        sources = int(conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
        enabled_sources = int(conn.execute("SELECT COUNT(*) FROM sources WHERE enabled=1").fetchone()[0])
        rejected_memory = int(conn.execute("SELECT COUNT(*) FROM rejected_resources").fetchone()[0])
        return {
            "total": total,
            "new": by_status.get("new", 0),
            "approved": by_status.get("approved", 0),
            "rejected": by_status.get("rejected", 0),
            "exported": by_status.get("exported", 0),
            "unknown_count": unknown_count,
            "sources": sources,
            "enabled_sources": enabled_sources,
            "rejected_memory": rejected_memory,
        }


def mark_exported(db_path: Path, ids: list[int], file_path: str, status: str) -> None:
    if not ids:
        return
    now = utc_now()
    placeholders = ",".join("?" for _ in ids)
    with connect(db_path) as conn:
        conn.execute(f"UPDATE candidates SET status='exported', exported_at=? WHERE id IN ({placeholders})", [now, *ids])
        conn.execute("INSERT INTO export_runs (file_path, status, total, created_at) VALUES (?, ?, ?, ?)", (file_path, status, len(ids), now))
