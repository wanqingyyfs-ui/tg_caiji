from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ensure_dirs(root: Path) -> None:
    for folder in ("data", "data/sessions", "exports", "logs"):
        (root / folder).mkdir(parents=True, exist_ok=True)


def run_collector_main_from_embedded_python_args() -> bool:
    """Route internal subprocess calls made as: exe -m collector.main <command>.

    In a normal Python run, collector.run_all starts subprocesses with
    [sys.executable, "-m", "collector.main", ...]. After PyInstaller packaging,
    sys.executable points to this exe, not python.exe. If the launcher always
    starts run_all, each child process opens another browser and recursively
    spawns more children. This router makes the frozen exe behave like
    python -m collector.main for those internal child calls.
    """
    if len(sys.argv) >= 3 and sys.argv[1] == "-m" and sys.argv[2] == "collector.main":
        from collector.main import main as collector_main

        sys.argv = ["collector.main", *sys.argv[3:]]
        collector_main()
        return True
    return False


def main() -> None:
    root = app_root()
    os.chdir(root)
    ensure_dirs(root)

    if run_collector_main_from_embedded_python_args():
        return

    from collector.run_all import main as run_all_main

    sys.argv = [
        "tg_caiji.exe",
        "--open-browser",
        "--debug",
        "--backfill-limit",
        "10",
    ]
    run_all_main()


if __name__ == "__main__":
    main()
