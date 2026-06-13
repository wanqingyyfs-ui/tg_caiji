from __future__ import annotations

from typing import Any
from telethon import events

from . import storage
from .extractor import extract_candidates
from .safety import safe_snippet
from .settings import Settings
from .telegram_client import build_client


def _entity_name(entity: Any) -> str:
    return (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or getattr(entity, "first_name", None)
        or str(getattr(entity, "id", "unknown"))
    )


async def _resolve_enabled_sources(client, settings: Settings) -> list[tuple[dict[str, Any], Any]]:
    resolved = []
    for source in storage.list_sources(settings.collector_db, enabled=True):
        try:
            entity = await client.get_entity(source["chat_ref"])
            resolved.append((source, entity))
            storage.update_source_error(settings.collector_db, int(source["id"]), None)
            print(f"监听源解析成功：{source['name']} -> {_entity_name(entity)} / id={getattr(entity, 'id', '')}")
        except Exception as exc:
            storage.update_source_error(settings.collector_db, int(source["id"]), str(exc))
            print(f"监听源解析失败：{source['name']} / {source['chat_ref']} / {exc}")
    return resolved


async def listen(
    settings: Settings,
    include_mentions: bool = True,
    debug: bool = False,
    backfill_on_start: bool = False,
    backfill_limit: int = 100,
) -> None:
    if backfill_on_start:
        from .backfill import backfill

        print(f"启动监听前先回补最近 {backfill_limit} 条消息...")
        result = await backfill(settings, limit=backfill_limit, include_mentions=include_mentions)
        print(
            "启动回补完成："
            f"sources={result['sources']} messages={result['messages']} candidates={result['candidates']}"
        )

    client = build_client(settings)

    async with client:
        resolved = await _resolve_enabled_sources(client, settings)
        if not resolved:
            raise SystemExit("没有可监听的启用来源，或所有来源都解析失败。请先运行 doctor 检查。")

        chats = [entity for _, entity in resolved]

        @client.on(events.NewMessage(chats=chats))
        async def handler(event):
            text = event.raw_text or ""
            candidates = extract_candidates(text, include_mentions=include_mentions)

            try:
                chat = await event.get_chat()
                source_name = getattr(chat, "title", "") or str(event.chat_id)
            except Exception:
                source_name = str(event.chat_id)

            if debug:
                text_preview = safe_snippet(text, max_len=120)
                print(
                    f"收到消息：chat={source_name} message_id={event.message.id} "
                    f"links={len(candidates)} text={text_preview}"
                )

            if not candidates:
                return

            for item in candidates:
                candidate_id = storage.upsert_candidate(
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
                print(f"发现候选资源：id={candidate_id} url={item.url} type={item.type_hint or '-'} score={item.confidence:.2f}")

        print(f"正在监听 {len(chats)} 个来源。include_mentions={include_mentions}。按 Ctrl+C 停止。")
        if debug:
            print("调试模式已开启：即使消息里没有链接，也会打印收到消息的记录。")
        try:
            await client.run_until_disconnected()
        except (KeyboardInterrupt, asyncio.CancelledError):  # type: ignore[name-defined]
            print("监听已停止。")
