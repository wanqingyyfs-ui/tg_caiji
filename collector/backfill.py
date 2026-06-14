from __future__ import annotations

from .dialog_sources import list_joined_collect_sources
from .extractor import extract_candidates_from_message
from .gate import handle_link
from .settings import Settings
from .telegram_client import build_client


async def backfill(settings: Settings, limit: int | None = None, include_mentions: bool = False) -> dict[str, int]:
    client = build_client(settings)
    total_messages = 0
    total_approved = 0
    skipped_reviewed = 0
    skipped_invalid = 0
    sources_done = 0
    failed_sources = 0
    per_dialog_limit = int(limit or 10)

    async with client:
        sources = await list_joined_collect_sources(client)
        print(f"自动回补当前账号已加入群/频道：dialogs={len(sources)} per_dialog_limit={per_dialog_limit}", flush=True)
        for index, source in enumerate(sources, start=1):
            dialog_messages = 0
            dialog_links = 0
            dialog_approved = 0
            print(f"开始回补对话 {index}/{len(sources)}：{source.name}", flush=True)
            try:
                async for message in client.iter_messages(source.entity, limit=per_dialog_limit):
                    dialog_messages += 1
                    total_messages += 1
                    text = message.raw_text or ""
                    items = extract_candidates_from_message(message, include_mentions=include_mentions)
                    if not items:
                        continue
                    dialog_links += len(items)
                    for item in items:
                        result = handle_link(
                            settings.collector_db,
                            item,
                            source_chat=source.name,
                            source_message_id=message.id,
                            source_message_date=message.date.isoformat() if message.date else None,
                            text=text,
                        )
                        if result.action == "approved":
                            total_approved += 1
                            dialog_approved += 1
                        elif result.reason in {"approved", "rejected", "exported", "reviewed"}:
                            skipped_reviewed += 1
                        else:
                            skipped_invalid += 1
                sources_done += 1
                print(
                    f"完成回补对话 {index}/{len(sources)}：{source.name} "
                    f"messages={dialog_messages} links={dialog_links} approved={dialog_approved}",
                    flush=True,
                )
            except Exception as exc:
                failed_sources += 1
                print(f"回补对话跳过 {index}/{len(sources)}：{source.name} / {exc}", flush=True)
                continue

    return {
        "sources": sources_done,
        "failed_sources": failed_sources,
        "messages": total_messages,
        "approved": total_approved,
        "candidates": total_approved,
        "skipped_reviewed": skipped_reviewed,
        "skipped_invalid": skipped_invalid,
    }
