from __future__ import annotations

import asyncio
from telethon import events

from .dialog_sources import list_joined_collect_sources
from .extractor import extract_candidates_from_message
from .gate import handle_link
from .safety import safe_snippet
from .settings import Settings
from .telegram_client import build_client


async def listen(
    settings: Settings,
    include_mentions: bool = True,
    debug: bool = False,
    backfill_on_start: bool = False,
    backfill_limit: int = 100,
) -> None:
    if backfill_on_start:
        from .backfill import backfill

        print(f"启动监听前先自动回补每个已加入群/频道最近 {backfill_limit} 条消息...")
        result = await backfill(settings, limit=backfill_limit, include_mentions=include_mentions)
        print(
            "启动回补完成："
            f"dialogs={result.get('sources', 0)} messages={result['messages']} "
            f"approved={result.get('approved', result.get('candidates', 0))} skipped_reviewed={result.get('skipped_reviewed', 0)} "
            f"skipped_invalid={result.get('skipped_invalid', 0)}"
        )

    client = build_client(settings)

    async with client:
        sources = await list_joined_collect_sources(client)
        if not sources:
            raise SystemExit("当前登录账号没有可监听的群组/频道。请先让该账号加入群组或频道。")

        groups = sum(1 for source in sources if source.kind == "group")
        channels = sum(1 for source in sources if source.kind == "channel")
        print(f"自动监听当前账号已加入对话：总数={len(sources)} 群组={groups} 频道={channels}")
        if debug:
            for source in sources:
                username = f" @{source.username}" if source.username else ""
                print(f"监听对话：kind={source.kind} name={source.name}{username}")

        chats = [source.entity for source in sources]

        @client.on(events.NewMessage(chats=chats))
        async def handler(event):
            message = event.message
            text = message.raw_text or ""
            found = extract_candidates_from_message(message, include_mentions=include_mentions)

            try:
                chat = await event.get_chat()
                source_name = getattr(chat, "title", "") or str(event.chat_id)
            except Exception:
                source_name = str(event.chat_id)

            if debug:
                text_preview = safe_snippet(text, max_len=120)
                print(
                    f"收到消息：chat={source_name} message_id={message.id} "
                    f"links={len(found)} text={text_preview}"
                )

            if not found:
                return

            for item in found:
                result = handle_link(
                    settings.collector_db,
                    item,
                    source_chat=source_name,
                    source_message_id=message.id,
                    source_message_date=message.date.isoformat() if message.date else None,
                    text=text,
                )
                if result.action == "approved":
                    count_text = result.count if result.count is not None else "-"
                    print(
                        f"自动通过资源：id={result.candidate_id} url={result.url} "
                        f"type={result.type_hint or '-'} count={count_text}"
                    )
                elif debug:
                    print(f"跳过资源：url={result.url} action={result.action} reason={result.reason}")

        print(f"正在自动监听 {len(chats)} 个已加入群/频道。include_mentions={include_mentions}。按 Ctrl+C 停止。")
        print("监听账号只用于读取已加入群/频道的消息；候选资源类型和人数仍然只用公开网页解析。")
        if debug:
            print("调试模式已开启：会打印收到消息、跳过原因和自动通过资源。")
        try:
            await client.run_until_disconnected()
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("监听已停止。")
