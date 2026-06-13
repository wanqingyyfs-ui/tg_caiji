from __future__ import annotations

from typing import Any
from telethon import events

from . import storage
from .extractor import extract_candidates
from .safety import safe_snippet
from .settings import Settings
from .telegram_client import build_client


async def _resolve_enabled_sources(client, settings: Settings) -> list[tuple[dict[str, Any], Any]]:
    resolved = []
    for source in storage.list_sources(settings.collector_db, enabled=True):
        try:
            entity = await client.get_input_entity(source["chat_ref"])
            resolved.append((source, entity))
            storage.update_source_error(settings.collector_db, int(source["id"]), None)
        except Exception as exc:
            storage.update_source_error(settings.collector_db, int(source["id"]), str(exc))
    return resolved


async def listen(settings: Settings, include_mentions: bool = False) -> None:
    client = build_client(settings)

    async with client:
        resolved = await _resolve_enabled_sources(client, settings)
        if not resolved:
            raise SystemExit("没有可监听的启用来源。请先在面板或命令行添加 sources。")

        chats = [entity for _, entity in resolved]

        @client.on(events.NewMessage(chats=chats, incoming=True))
        async def handler(event):
            text = event.raw_text or ""
            candidates = extract_candidates(text, include_mentions=include_mentions)
            if not candidates:
                return

            try:
                chat = await event.get_chat()
                source_name = getattr(chat, "title", "") or str(event.chat_id)
            except Exception:
                source_name = str(event.chat_id)

            for item in candidates:
                storage.upsert_candidate(
                    settings.collector_db,
                    {
                        "url": item.url,
                        "username": item.username,
                        "name": item.username,
                        "type_hint": item.type_hint,
                        "source_chat": source_name,
                        "source_message_id": event.message.id,
                        "source_message_date": event.message.date.isoformat() if event.message.date else None,
                        "text_snippet": safe_snippet(text),
                        "confidence": item.confidence,
                    },
                )

        print(f"正在监听 {len(chats)} 个来源。按 Ctrl+C 停止。")
        await client.run_until_disconnected()
