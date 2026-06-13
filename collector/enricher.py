from __future__ import annotations

import asyncio

from . import storage
from .normalizer import canonical_username
from .public_page import fetch_public_page_meta
from .review_memory import remember_username
from .settings import Settings


ALLOWED_PUBLIC_TYPES = {"channel", "group", "bot"}


def fetch_meta_from_public_page(username: str) -> dict:
    username = canonical_username(username) or username.strip().lstrip("@").lower()
    public_meta = fetch_public_page_meta(username)
    meta = {
        "valid": False,
        "private": False,
        "username": username,
        "title": public_meta.title or username,
        "description": public_meta.description,
        "type": public_meta.type_hint,
        "type_hint": public_meta.type_hint,
        "count": public_meta.count,
        "telegram_id": None,
        "fetched": public_meta.fetched,
    }

    if not public_meta.fetched:
        meta["description"] = "public_page_unreachable"
        return meta

    if public_meta.type_hint in ALLOWED_PUBLIC_TYPES:
        meta["valid"] = True
        return meta

    meta["description"] = public_meta.description or "not_public_channel_group_or_bot"
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

    updated = 0
    failed = 0
    with_count = 0
    invalid = 0

    for row in rows:
        try:
            meta = fetch_meta_from_public_page(row["username"])
            if not meta.get("fetched"):
                failed += 1
                print(f"公开页暂时无法访问，跳过：{row['username']}")
                await asyncio.sleep(max(float(settings.request_delay_seconds), 0.5))
                continue

            storage.update_candidate_meta(settings.collector_db, row["url"], meta)

            if not meta.get("valid"):
                remember_username(
                    settings.collector_db,
                    row.get("username"),
                    "rejected",
                    reason=meta.get("description") or "not_public_channel_group_or_bot",
                    title=meta.get("title"),
                    type_value=meta.get("type"),
                    count=meta.get("count"),
                )
                storage.set_candidate_status(
                    settings.collector_db,
                    int(row["id"]),
                    "rejected",
                    reject_reason=meta.get("description") or "not_public_channel_group_or_bot",
                )
                invalid += 1
                print(f"已拒绝非公开群组/频道/机器人：{row['username']}")
            else:
                updated += 1
                if meta.get("count"):
                    with_count += 1
                    print(f"已补充人数：{row['username']} -> {meta['count']}")
                else:
                    print(f"人数未知：{row['username']}，公开页没有返回人数")
        except Exception as exc:
            failed += 1
            print(f"补充失败：{row.get('username')} / {exc}")

        await asyncio.sleep(max(float(settings.request_delay_seconds), 0.5))

    return {"total": len(rows), "updated": updated, "failed": failed, "with_count": with_count, "invalid": invalid}
