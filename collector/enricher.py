from __future__ import annotations

import asyncio
from typing import Any

from telethon.errors import FloodWaitError, RPCError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import Channel, Chat, User

from . import storage
from .normalizer import canonical_username
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


def first_positive_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) > 0:
            return int(value)
    return None


def best_title(entity: Any, fallback: str) -> str:
    parts = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
    full_name = " ".join(part for part in parts if part)
    return getattr(entity, "title", None) or full_name or getattr(entity, "username", None) or fallback


async def fetch_meta_for_username(client, username: str) -> dict[str, Any]:
    username = canonical_username(username) or username.strip().lstrip("@").lower()
    meta: dict[str, Any] = {"valid": False, "private": False, "username": username, "count": None}
    try:
        entity = await client.get_entity(username)
        detected_type = type_from_entity(entity)
        title = best_title(entity, username)
        if detected_type is None:
            meta.update(
                {
                    "valid": False,
                    "private": False,
                    "title": title,
                    "description": "not_channel_group_or_bot",
                    "type": None,
                    "count": None,
                    "telegram_id": telegram_id_from_entity(entity),
                    "username": canonical_username(getattr(entity, "username", None)) or username,
                }
            )
            return meta

        description = None
        count = first_positive_int(
            getattr(entity, "participants_count", None),
            getattr(entity, "members_count", None),
            getattr(entity, "bot_active_users", None),
        )

        if isinstance(entity, Channel):
            try:
                full = await client(GetFullChannelRequest(entity))
                full_chat = getattr(full, "full_chat", None)
                description = getattr(full_chat, "about", None)
                count = first_positive_int(
                    getattr(full_chat, "participants_count", None),
                    getattr(full_chat, "members_count", None),
                    getattr(full_chat, "online_count", None),
                    count,
                )
            except RPCError as exc:
                description = description or f"GetFullChannel failed: {exc.__class__.__name__}"

        meta.update(
            {
                "valid": True,
                "private": False,
                "title": title,
                "description": description,
                "type": detected_type,
                "count": count,
                "telegram_id": telegram_id_from_entity(entity),
                "username": canonical_username(getattr(entity, "username", None)) or username,
            }
        )
    except FloodWaitError:
        raise
    except ValueError as exc:
        meta.update({"valid": False, "private": True, "description": str(exc)})
    except RPCError as exc:
        meta.update({"valid": False, "description": f"{exc.__class__.__name__}: {exc}"})
    return meta


async def enrich_pending(settings: Settings, limit: int = 100, force: bool = False) -> dict[str, int]:
    rows, _ = storage.list_candidates(settings.collector_db, status=None, limit=max(limit * 3, limit), offset=0)
    rows = [
        row
        for row in rows
        if row.get("username")
        and (
            force
            or not row.get("enriched_at")
            or row.get("count") is None
            or int(row.get("count") or 0) == 0
            or not row.get("type")
        )
    ][:limit]

    if not rows:
        return {"total": 0, "updated": 0, "failed": 0, "with_count": 0, "invalid": 0}

    client = build_client(settings)
    updated = 0
    failed = 0
    with_count = 0
    invalid = 0

    async with client:
        for row in rows:
            try:
                meta = await fetch_meta_for_username(client, row["username"])
                storage.update_candidate_meta(settings.collector_db, row["url"], meta)
                if not meta.get("valid"):
                    storage.set_candidate_status(settings.collector_db, int(row["id"]), "rejected", reject_reason=meta.get("description") or "invalid")
                    invalid += 1
                    print(f"已拒绝非资源链接：{row['username']}")
                else:
                    updated += 1
                    if meta.get("count"):
                        with_count += 1
                        print(f"已补充人数：{row['username']} -> {meta['count']}")
                    else:
                        print(f"人数未知：{row['username']}，已补充标题/类型但 Telegram 未返回人数")
            except FloodWaitError as exc:
                wait_seconds = min(int(exc.seconds), 60)
                print(f"触发 FloodWait，等待 {wait_seconds} 秒后继续")
                await asyncio.sleep(wait_seconds)
                failed += 1
            except Exception as exc:
                print(f"补充失败：{row.get('username')} / {exc}")
                failed += 1
            await asyncio.sleep(max(float(settings.request_delay_seconds), 0.5))

    return {"total": len(rows), "updated": updated, "failed": failed, "with_count": with_count, "invalid": invalid}
