from __future__ import annotations

from .maintenance import normalize_database
from .settings import ensure_runtime_dirs, get_settings


def main() -> None:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    result = normalize_database(settings)
    print(result)


if __name__ == "__main__":
    main()
