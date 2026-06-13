from __future__ import annotations

from telethon import TelegramClient
from .settings import Settings, PROJECT_ROOT, require_telegram_credentials


def build_client(settings: Settings) -> TelegramClient:
    require_telegram_credentials(settings)
    session_dir = PROJECT_ROOT / "data" / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / settings.tg_session_name
    return TelegramClient(str(session_path), int(settings.tg_api_id), str(settings.tg_api_hash))
