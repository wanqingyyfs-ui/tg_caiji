from __future__ import annotations

import asyncio
from typing import Any
from telethon import events

from . import storage
from .extractor import extract_candidates
from .resource_pipeline import process_candidate_link
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
            f"sources={result['sources']} messages={result['messages']} "
            f"candidates={result['candidates']} skipped_reviewed={result.get('skipped_reviewed', 0)} "
            f"skipped_invalid={result.get('skipped_invalid', 0)}"
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
            found = extract_candidates(text, include_mentions=include_mentions)

            try:
                chat = await event.get_chat()
                source_name = getattr(chat, "title", "") or str(event.chat_id)
            except Exception:
                source_name = str(event.chat_id)

            if debug:
                text_preview = safe_snippet(text, max_len=120)
                print(
                    f"收到消息：chat={source_name} message_id={event.message.id} "
                    f"links={len(found)} text={text_preview}"
                )

            if not found:
                return

            for item in found:
                result = process_candidate_link(
                    settings.collector_db,
                    item,
                    source_chat=source_name,
                    source_message_id=event.message.id,
                    source_message_date=event.message.date.isoformat() if event.message.date else None,
                    text=text,
                )
                if result.action == "candidate":
                    count_text = result.count if result.count is not None else "-"
                    print(
                        f"新增候选资源：id={result.candidate_id} url={result.url} "
                        f"type={result.type_hint or '-'} count={count_text}"
                    )
                elif debug:
                    print(f"跳过资源：url={result.url} action={result.action} reason={result.reason}")

        print(f"正在监听 {len(chats)} 个来源。include_mentions={include_mentions}。按 Ctrl+C 停止。")
        if debug:
            print("调试模式已开启：会打印收到消息、跳过原因和新增候选。")
        try:
            await client.run_until_disconnected()
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("监听已停止。")
