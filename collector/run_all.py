from __future__ import annotations

import argparse
import asyncio
import signal
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from . import storage
from .enricher import enrich_pending
from .settings import ensure_runtime_dirs, get_settings


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        try:
            self.process.terminate()
            self.process.wait(timeout=8)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def start_process(name: str, args: list[str]) -> ManagedProcess:
    print(f"启动 {name}: {' '.join(args)}", flush=True)
    proc = subprocess.Popen(args, cwd=str(project_root()))
    return ManagedProcess(name=name, process=proc)


def build_web_command(host: str, port: int) -> list[str]:
    return [sys.executable, "-m", "collector.main", "web", "--host", host, "--port", str(port)]


def build_listener_command(backfill_on_start: bool, backfill_limit: int, include_mentions: bool, debug: bool) -> list[str]:
    cmd = [sys.executable, "-m", "collector.main", "listen"]
    if backfill_on_start:
        cmd.extend(["--backfill-on-start", "--backfill-limit", str(backfill_limit)])
    if not include_mentions:
        cmd.append("--no-mentions")
    if debug:
        cmd.append("--debug")
    return cmd


async def enrich_loop(limit: int, interval: int) -> None:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    storage.init_db(settings.collector_db)
    print(f"自动公开页 enrich 已启动：每 {interval} 秒处理最多 {limit} 条。不使用 Telegram 登录账号。", flush=True)
    while True:
        try:
            result = await enrich_pending(settings, limit=limit)
            print(
                "自动公开页 enrich 完成："
                f"total={result.get('total', 0)} "
                f"updated={result.get('updated', 0)} "
                f"with_count={result.get('with_count', 0)} "
                f"invalid={result.get('invalid', 0)} "
                f"failed={result.get('failed', 0)}",
                flush=True,
            )
        except Exception as exc:
            print(f"自动公开页 enrich 出错：{exc}", flush=True)
        await asyncio.sleep(max(int(interval), 10))


async def supervise(args: argparse.Namespace) -> None:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    storage.init_db(settings.collector_db)

    processes: list[ManagedProcess] = []
    stop_event = asyncio.Event()

    def request_stop(*_):
        stop_event.set()

    try:
        signal.signal(signal.SIGINT, request_stop)
        signal.signal(signal.SIGTERM, request_stop)
    except Exception:
        pass

    processes.append(start_process("Web 面板", build_web_command(args.host, args.port)))

    if args.open_browser:
        await asyncio.sleep(2)
        webbrowser.open(f"http://{args.host}:{args.port}/")

    if not args.no_telegram_listener:
        processes.append(
            start_process(
                "Telegram 登录监听",
                build_listener_command(
                    backfill_on_start=args.backfill_on_start,
                    backfill_limit=args.backfill_limit,
                    include_mentions=not args.no_mentions,
                    debug=args.debug,
                ),
            )
        )
        print("Telegram 登录账号只用于读取已加入群/频道消息；候选资源类型和人数只用公开网页解析。", flush=True)
    else:
        print("已按参数跳过 Telegram 登录监听；仅运行 Web 和公开页 enrich。", flush=True)

    enrich_task = None
    if not args.no_enrich:
        enrich_task = asyncio.create_task(enrich_loop(limit=args.enrich_limit, interval=args.enrich_interval))

    print("一键服务已启动。按 Ctrl+C 可全部停止。", flush=True)
    print(f"Web 地址：http://{args.host}:{args.port}/", flush=True)

    while not stop_event.is_set():
        for managed in list(processes):
            code = managed.process.poll()
            if code is not None:
                print(f"{managed.name} 已退出，退出码={code}。其他服务继续运行。", flush=True)
                processes.remove(managed)
        await asyncio.sleep(2)

    print("正在停止一键服务...", flush=True)
    if enrich_task:
        enrich_task.cancel()
    for managed in processes:
        managed.stop()
    print("已停止。", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start web, Telegram listener, and public-page enrichment together")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8008)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--no-telegram-listener", action="store_true", help="不启动登录账号监听，只运行 Web 和公开页 enrich")
    parser.add_argument("--no-enrich", action="store_true")
    parser.add_argument("--no-mentions", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--backfill-on-start", action="store_true", default=True)
    parser.add_argument("--backfill-limit", type=int, default=10)
    parser.add_argument("--enrich-limit", type=int, default=300)
    parser.add_argument("--enrich-interval", type=int, default=180)
    args = parser.parse_args()

    try:
        asyncio.run(supervise(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
