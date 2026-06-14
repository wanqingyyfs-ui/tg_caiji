from __future__ import annotations

import argparse

from .extractor import extract_candidates
from .normalizer import normalize_tg_link


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Telegram link normalization and extraction")
    parser.add_argument("links", nargs="+")
    args = parser.parse_args()

    text = "\n".join(args.links)
    print("Normalizer:")
    for raw in args.links:
        result = normalize_tg_link(raw)
        if result.rejected:
            print(f"{raw} -> rejected: {result.reject_reason}")
        else:
            print(f"{raw} -> {result.url} username={result.username}")

    print("\nExtractor:")
    for item in extract_candidates(text, include_mentions=True):
        print(f"{item.raw} -> {item.url} username={item.username}")


if __name__ == "__main__":
    main()
