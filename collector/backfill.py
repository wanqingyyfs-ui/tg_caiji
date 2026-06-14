from __future__ import annotations

from . import storage
from .extractor import extract_candidates_from_message
from .gate import handle_link
from .settings import Settings
from .source_resolver import build_dialog_username_map, resolve_source_from_dialogs
from .telegram_client import build_client


async def backfill(settings: Settings, limit: int | None = None, include_mentions: bool = False) -> dict[str, int]:
    client = build_client(settings)
    total_messages = 0
    total_approved = 0
    skipped_reviewed = 0
    skipped_invalid = 0
    sources_done = 0

    async with client:
        sources = storage.list_sources(settings.collector_db, enabled=True)
        dialog_map = await build_dialog_username_map(client)
        for source in sources:
            current_limit = int(limit or source.get("backfill_limit") or 500)
            max_message_id = None
            try:
                entity = await resolve_source_from_dialogs(client, source["chat_ref"], dialog_map)
                storage.update_source_error(settings.collector_db, int(source["id"]), None)
            except Exception as exc:
                storage.update_source_error(settings.collector_db, int(source["id"]), str(exc))
                print(f"回补源跳过：{source['name']} / {source['chat_ref']} / {exc}")
                continue

            async for message in client.iter_messages(entity, limit=current_limit):
                total_messages += 1
                text = message.raw_text or ""
                items = extract_candidates_from_message(message, include_mentions=include_mentions)
                if not items:
                    continue
                max_message_id = max(max_message_id or 0, int(message.id))
                for item in items:
                    result = handle_link(
                        settings.collector_db,
                        item,
                        source_chat=source["name"],
                        source_message_id=message.id,
                        source_message_date=message.date.isoformat() if message.date else None,
                        text=text,
                    )
                    if result.action == "approved":
                        total_approved += 1
                    elif result.reason in {"approved", "rejected", "exported", "reviewed"}:
                        skipped_reviewed += 1
                    else:
                        skipped_invalid += 1

            storage.update_source_backfill(settings.collector_db, int(source["id"]), max_message_id)
            sources_done += 1

    return {
        "sources": sources_done,
        "messages": total_messages,
        "approved": total_approved,
        "candidates": total_approved,
        "skipped_reviewed": skipped_reviewed,
        "skipped_invalid": skipped_invalid,
    }
