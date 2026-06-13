from __future__ import annotations

import argparse

from .maintenance import clear_collected_candidates, normalize_database
from .settings import ensure_runtime_dirs, get_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clear", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    ensure_runtime_dirs(settings)

    if args.clear:
        result = clear_collected_candidates(settings, include_sources=args.all)
    else:
        result = normalize_database(settings)

    print(result)


if __name__ == "__main__":
    main()
