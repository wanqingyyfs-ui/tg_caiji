from __future__ import annotations

from . import storage
from .extractor import extract_candidates
from .safety import safe_snippet
from .settings import Settings
from .telegram_client import build_client


async def backfill(settings: Settings, limit: int | None = None, include_mentions: bool = False) -> dict[str, int]:
    client = build_client(settings)
    total_messages = 0
    total_candidates = 0
    sources_done = 0

    async with client:
        sources = storage.list_sources(settings.collector_db, enabled=True)
        for source in sources:
            current_limit = int(limit or source.get("backfill_limit") or 500)
            max_message_id = None
            try:
                entity = await client.get_input_entity(source["chat_ref"])
                storage.update_source_error(settings.collector_db, int(source["id"]), None)
            except Exception as exc:
                storage.update_source_error(settings.collector_db, int(source["id"]), str(exc))
                continue

            async for message in client.iter_messages(entity, limit=current_limit):
                total_messages += 1
                text = message.raw_text or ""
                items = extract_candidates(text, include_mentions=include_mentions)
                if not items:
                    continue
                max_message_id = max(max_message_id or 0, int(message.id))
                for item in items:
                    storage.upsert_candidate(
                        settings.collector_db,
                        {
                            "url": item.url,
                            "username": item.username,
                            "name": item.username,
                            "type_hint": item.type_hint,
                            "source_chat": source["name"],
                            "source_message_id": message.id,
                            "source_message_date": message.date.isoformat() if message.date else None,
                            "text_snippet": safe_snippet(text),
                            "confidence": item.confidence,
                        },
                    )
                    total_candidates += 1

            storage.update_source_backfill(settings.collector_db, int(source["id"]), max_message_id)
            sources_done += 1

    return {"sources": sources_done, "messages": total_messages, "candidates": total_candidates}
