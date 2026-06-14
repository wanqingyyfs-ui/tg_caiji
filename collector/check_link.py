from __future__ import annotations

import argparse

from .normalizer import normalize_tg_link


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Telegram link normalization")
    parser.add_argument("links", nargs="+")
    args = parser.parse_args()

    for raw in args.links:
        result = normalize_tg_link(raw)
        if result.rejected:
            print(f"{raw} -> rejected: {result.reject_reason}")
        else:
            print(f"{raw} -> {result.url} username={result.username}")


if __name__ == "__main__":
    main()
