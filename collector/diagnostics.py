from __future__ import annotations

from typing import Any

from . import storage
from .extractor import extract_candidates
from .settings import Settings
from .telegram_client import build_client


def _entity_name(entity: Any) -> str:
    return (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or getattr(entity, "first_name", None)
        or str(getattr(entity, "id", "unknown"))
    )


async def doctor(settings: Settings, sample_limit: int = 30, include_mentions: bool = True) -> dict[str, int]:
    client = build_client(settings)
    result = {"sources": 0, "resolved": 0, "failed": 0, "messages": 0, "candidates": 0}

    async with client:
        sources = storage.list_sources(settings.collector_db, enabled=None)
        result["sources"] = len(sources)
        if not sources:
            print("没有监听源。请先在面板 /sources 添加群组或频道。")
            return result

        print(f"共发现监听源：{len(sources)} 个")
        for source in sources:
            print("-" * 72)
            print(f"ID={source['id']} enabled={source['enabled']} name={source['name']} chat_ref={source['chat_ref']}")
            if not source["enabled"]:
                print("  状态：未启用，listen/backfill 会跳过它。")
                continue

            try:
                entity = await client.get_entity(source["chat_ref"])
                result["resolved"] += 1
                storage.update_source_error(settings.collector_db, int(source["id"]), None)
                print(f"  解析成功：{_entity_name(entity)} / id={getattr(entity, 'id', '')}")
            except Exception as exc:
                result["failed"] += 1
                storage.update_source_error(settings.collector_db, int(source["id"]), str(exc))
                print(f"  解析失败：{exc}")
                continue

            message_count = 0
            candidate_count = 0
            try:
                async for message in client.iter_messages(entity, limit=sample_limit):
                    message_count += 1
                    items = extract_candidates(message.raw_text or "", include_mentions=include_mentions)
                    candidate_count += len(items)
                    if items:
                        links = ", ".join(item.url for item in items[:5])
                        print(f"  命中消息 id={message.id} links={links}")
            except Exception as exc:
                storage.update_source_error(settings.collector_db, int(source["id"]), str(exc))
                print(f"  读取最近消息失败：{exc}")
                continue

            result["messages"] += message_count
            result["candidates"] += candidate_count
            print(f"  最近 {sample_limit} 条消息：读取 {message_count} 条，发现候选链接 {candidate_count} 个")

    print("-" * 72)
    print(
        "诊断完成："
        f"sources={result['sources']} resolved={result['resolved']} failed={result['failed']} "
        f"messages={result['messages']} candidates={result['candidates']}"
    )
    return result
