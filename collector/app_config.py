from __future__ import annotations

from pathlib import Path

from . import storage

DEFAULT_MIN_MEMBER_COUNT = 0


def ensure_app_config(db_path: Path) -> None:
    with storage.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def get_setting(db_path: Path, key: str, default: str = "") -> str:
    ensure_app_config(db_path)
    with storage.connect(db_path) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        return str(row["value"])


def set_setting(db_path: Path, key: str, value: str) -> None:
    ensure_app_config(db_path)
    now = storage.utc_now()
    with storage.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value,
                updated_at=excluded.updated_at
            """,
            (key, value, now),
        )


def get_min_member_count(db_path: Path) -> int:
    raw = get_setting(db_path, "min_member_count", str(DEFAULT_MIN_MEMBER_COUNT))
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_MIN_MEMBER_COUNT


def set_min_member_count(db_path: Path, value: int) -> int:
    cleaned = max(0, int(value or 0))
    set_setting(db_path, "min_member_count", str(cleaned))
    return cleaned
