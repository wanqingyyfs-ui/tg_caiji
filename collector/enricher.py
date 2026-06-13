from __future__ import annotations

import asyncio
from typing import Any

from telethon.errors import FloodWaitError, RPCError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel, Chat, User

from . import storage
from .settings import Settings
from .telegram_client import build_client


def type_from_entity(entity: Any) -> str | None:
    if isinstance(entity, User):
        return "bot" if getattr(entity, "bot", False) else None
    if isinstance(entity, Chat):
        return "group"
    if isinstance(entity, Channel):
        if getattr(entity, "broadcast", False):
            return "channel"
        if getattr(entity, "megagroup", False) or getattr(entity, "gigagroup", False):
            return "group"
        return "channel"
    return None


def telegram_id_from_entity(entity: Any) -> int | None:
    raw_id = getattr(entity, "id", None)
    if raw_id is None:
        return None
    if isinstance(entity, Channel):
        return int(f"-100{raw_id}")
    return int(raw_id)


async def fetch_meta_for_username(client, username: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"valid": False, "private": False, "username": username}
    try:
        entity = await client.get_entity(username)
        detected_type = type_from_entity(entity)
        title = getattr(entity, "title", None) or getattr(entity, "first_name", None) or username
        count = getattr(entity, "participants_count", None)
        description = None

        if isinstance(entity, Channel):
            try:
                full = await client(GetFullChannelRequest(entity))
                full_chat = getattr(full, "full_chat", None)
                description = getattr(full_chat, "about", None)
                count = getattr(full_chat, "participants_count", None) or count
            except RPCError:
                pass

        meta.update(
            {
                "valid": True,
                "private": False,
                "title": title,
                "description": description,
                "type": detected_type,
                "count": count,
                "telegram_id": telegram_id_from_entity(entity),
                "username": getattr(entity, "username", None) or username,
            }
        )
    except FloodWaitError:
        raise
    except ValueError as exc:
        meta.update({"valid": False, "private": True, "description": str(exc)})
    except RPCError as exc:
        meta.update({"valid": False, "description": f"{exc.__class__.__name__}: {exc}"})
    return meta


async def enrich_pending(settings: Settings, limit: int = 100) -> dict[str, int]:
    rows, _ = storage.list_candidates(settings.collector_db, status=None, limit=limit, offset=0)
    rows = [row for row in rows if row.get("username") and not row.get("enriched_at")][:limit]

    if not rows:
        return {"total": 0, "updated": 0, "failed": 0}

    client = build_client(settings)
    updated = 0
    failed = 0

    async with client:
        for row in rows:
            try:
                meta = await fetch_meta_for_username(client, row["username"])
                storage.update_candidate_meta(settings.collector_db, row["url"], meta)
                updated += 1
            except FloodWaitError as exc:
                await asyncio.sleep(min(int(exc.seconds), 60))
                failed += 1
            except Exception:
                failed += 1
            await asyncio.sleep(max(float(settings.request_delay_seconds), 0.5))

    return {"total": len(rows), "updated": updated, "failed": failed}
