from __future__ import annotations

from pathlib import Path
import yaml

from . import storage
from .settings import Settings


def import_sources_from_yaml(settings: Settings, file_path: Path) -> dict[str, int]:
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    data = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or []
    count = 0
    for item in sources:
        name = str(item.get("name") or item.get("chat") or "").strip()
        chat = str(item.get("chat") or item.get("chat_ref") or "").strip()
        if not name or not chat:
            continue
        enabled = bool(item.get("enabled", True))
        backfill_limit = int(item.get("backfill_limit") or 500)
        storage.upsert_source(settings.collector_db, name=name, chat_ref=chat, enabled=enabled, backfill_limit=backfill_limit)
        count += 1
    return {"imported": count}
