from __future__ import annotations

from pathlib import Path
from typing import Any

from . import storage
from .normalizer import canonical_url_from_username, canonical_username, normalize_tg_link

REVIEWED_STATUSES = {"approved", "rejected", "exported"}


def ensure_review_memory(db_path: Path) -> None:
    with storage.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviewed_resources (
                username TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                status TEXT NOT NULL,
                reason TEXT,
                title TEXT,
                type TEXT,
                count INTEGER,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reviewed_resources_status ON reviewed_resources(status)")

        rows = conn.execute("SELECT username, url, reason, created_at, last_seen_at FROM rejected_resources").fetchall()
        for row in rows:
            username = canonical_username(row["username"])
            if not username:
                continue
            conn.execute(
                """
                INSERT INTO reviewed_resources (username, url, status, reason, first_seen_at, last_seen_at)
                VALUES (?, ?, 'rejected', ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    status='rejected',
                    reason=COALESCE(excluded.reason, reviewed_resources.reason),
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    username,
                    row["url"] or canonical_url_from_username(username),
                    row["reason"] or "rejected",
                    row["created_at"],
                    row["last_seen_at"],
                ),
            )


def username_from_row(row: dict[str, Any]) -> str | None:
    username = canonical_username(row.get("username"))
    if not username and row.get("url"):
        link = normalize_tg_link(str(row.get("url") or ""))
        if not link.rejected:
            username = link.username
    return username


def remember_username(
    db_path: Path,
    username: str | None,
    status: str,
    reason: str | None = None,
    title: str | None = None,
    type_value: str | None = None,
    count: int | None = None,
) -> bool:
    username = canonical_username(username)
    if not username or status not in REVIEWED_STATUSES:
        return False
    now = storage.utc_now()
    ensure_review_memory(db_path)
    with storage.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reviewed_resources (username, url, status, reason, title, type, count, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                status=excluded.status,
                reason=COALESCE(excluded.reason, reviewed_resources.reason),
                title=COALESCE(excluded.title, reviewed_resources.title),
                type=COALESCE(excluded.type, reviewed_resources.type),
                count=COALESCE(excluded.count, reviewed_resources.count),
                last_seen_at=excluded.last_seen_at
            """,
            (
                username,
                canonical_url_from_username(username),
                status,
                reason,
                title,
                type_value,
                count,
                now,
                now,
            ),
        )
    return True


def remember_candidate_ids(db_path: Path, ids: list[int], status: str, reason: str | None = None) -> int:
    if not ids or status not in REVIEWED_STATUSES:
        return 0
    ensure_review_memory(db_path)
    placeholders = ",".join("?" for _ in ids)
    remembered = 0
    with storage.connect(db_path) as conn:
        rows = conn.execute(f"SELECT * FROM candidates WHERE id IN ({placeholders})", ids).fetchall()
    for row in rows:
        data = dict(row)
        username = username_from_row(data)
        if remember_username(
            db_path,
            username,
            status,
            reason or data.get("reject_reason") or status,
            title=data.get("title") or data.get("name"),
            type_value=data.get("type") or data.get("type_hint"),
            count=data.get("count"),
        ):
            remembered += 1
    return remembered


def reviewed_status(db_path: Path, username: str | None) -> str | None:
    username = canonical_username(username)
    if not username:
        return None
    ensure_review_memory(db_path)
    with storage.connect(db_path) as conn:
        row = conn.execute("SELECT status FROM reviewed_resources WHERE username=?", (username,)).fetchone()
        if not row:
            return None
        conn.execute("UPDATE reviewed_resources SET last_seen_at=? WHERE username=?", (storage.utc_now(), username))
        return str(row["status"])


def bootstrap_from_candidates(db_path: Path) -> dict[str, int]:
    ensure_review_memory(db_path)
    rows_total = 0
    remembered = 0
    with storage.connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM candidates WHERE status IN ('approved', 'rejected', 'exported')").fetchall()
    for row in rows:
        rows_total += 1
        data = dict(row)
        username = username_from_row(data)
        status = data.get("status") or "rejected"
        if remember_username(
            db_path,
            username,
            status,
            data.get("reject_reason") or status,
            title=data.get("title") or data.get("name"),
            type_value=data.get("type") or data.get("type_hint"),
            count=data.get("count"),
        ):
            remembered += 1
    return {"reviewed_rows": rows_total, "remembered": remembered}
