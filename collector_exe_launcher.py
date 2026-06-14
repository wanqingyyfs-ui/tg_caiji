from __future__ import annotations

import os
import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def main() -> None:
    root = app_root()
    os.chdir(root)

    for folder in ("data", "data/sessions", "exports", "logs"):
        (root / folder).mkdir(parents=True, exist_ok=True)

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
