from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn

from . import storage
from .backfill import backfill
from .config_loader import import_sources_from_yaml
from .enricher import enrich_pending
from .exporter import export_csv, export_jsonl
from .listener import listen
from .settings import get_settings, ensure_runtime_dirs
from .telegram_client import build_client


async def login_command(settings):
    client = build_client(settings)
    async with client:
        me = await client.get_me()
        print(f"登录成功：{getattr(me, 'first_name', '')} / id={me.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="TG Suoyin Telegram resource collector")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="初始化采集器数据库")
    sub.add_parser("login", help="登录 Telegram 用户号并保存 session")

    add_source = sub.add_parser("add-source", help="添加监听源")
    add_source.add_argument("--name", required=True)
    add_source.add_argument("--chat", required=True)
    add_source.add_argument("--limit", type=int, default=500)
    add_source.add_argument("--disabled", action="store_true")

    import_sources = sub.add_parser("import-sources", help="从 YAML 导入监听源")
    import_sources.add_argument("--file", default="config/sources.yaml")

    backfill_cmd = sub.add_parser("backfill", help="回补历史消息")
    backfill_cmd.add_argument("--limit", type=int, default=None)
    backfill_cmd.add_argument("--include-mentions", action="store_true")

    listen_cmd = sub.add_parser("listen", help="实时监听消息")
    listen_cmd.add_argument("--include-mentions", action="store_true")

    enrich_cmd = sub.add_parser("enrich", help="补充候选资源元信息")
    enrich_cmd.add_argument("--limit", type=int, default=100)

    export_cmd = sub.add_parser("export", help="导出给 tg_suoyin 的导入文件")
    export_cmd.add_argument("--status", default="approved", choices=["new", "approved", "rejected", "exported"])
    export_cmd.add_argument("--output", default=None)
    export_cmd.add_argument("--format", default="jsonl", choices=["jsonl", "csv"])
    export_cmd.add_argument("--min-confidence", type=float, default=0.0)
    export_cmd.add_argument("--mark-exported", action="store_true")

    web_cmd = sub.add_parser("web", help="启动审核面板")
    web_cmd.add_argument("--host", default=None)
    web_cmd.add_argument("--port", type=int, default=None)

    args = parser.parse_args()
    settings = get_settings()
    ensure_runtime_dirs(settings)
    storage.init_db(settings.collector_db)

    if args.command == "init-db":
        print(f"数据库已初始化：{settings.collector_db}")
        return

    if args.command == "login":
        asyncio.run(login_command(settings))
        return

    if args.command == "add-source":
        storage.upsert_source(
            settings.collector_db,
            name=args.name,
            chat_ref=args.chat,
            backfill_limit=args.limit,
            enabled=not args.disabled,
        )
        print("监听源已保存")
        return

    if args.command == "import-sources":
        result = import_sources_from_yaml(settings, Path(args.file))
        print(f"已导入监听源：{result['imported']} 个")
        return

    if args.command == "backfill":
        result = asyncio.run(backfill(settings, limit=args.limit, include_mentions=args.include_mentions))
        print(f"回补完成：sources={result['sources']} messages={result['messages']} candidates={result['candidates']}")
        return

    if args.command == "listen":
        asyncio.run(listen(settings, include_mentions=args.include_mentions))
        return

    if args.command == "enrich":
        result = asyncio.run(enrich_pending(settings, limit=args.limit))
        print(f"元信息补充完成：total={result['total']} updated={result['updated']} failed={result['failed']}")
        return

    if args.command == "export":
        output = Path(args.output) if args.output else settings.export_path
        if args.format == "csv":
            result = export_csv(settings.collector_db, output, status=args.status, min_confidence=args.min_confidence)
        else:
            result = export_jsonl(
                settings.collector_db,
                output,
                status=args.status,
                min_confidence=args.min_confidence,
                mark_exported=args.mark_exported,
            )
        print(f"导出完成：{result['path']}，共 {result['count']} 条")
        return

    if args.command == "web":
        host = args.host or settings.admin_host
        port = args.port or settings.admin_port
        uvicorn.run("collector.webapp:app", host=host, port=port, reload=False)
        return


if __name__ == "__main__":
    main()
