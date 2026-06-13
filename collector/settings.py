from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    tg_api_id: int | None = Field(default=None, alias="TG_API_ID")
    tg_api_hash: str | None = Field(default=None, alias="TG_API_HASH")
    tg_session_name: str = Field(default="collector", alias="TG_SESSION_NAME")

    collector_db: Path = Field(default=Path("data/collector.db"), alias="COLLECTOR_DB")
    export_path: Path = Field(default=Path("exports/tg_suoyin_links.jsonl"), alias="EXPORT_PATH")

    admin_host: str = Field(default="127.0.0.1", alias="ADMIN_HOST")
    admin_port: int = Field(default=8008, alias="ADMIN_PORT")

    min_export_confidence: float = Field(default=0.6, alias="MIN_EXPORT_CONFIDENCE")
    auto_enrich_on_discovery: bool = Field(default=False, alias="AUTO_ENRICH_ON_DISCOVERY")
    request_delay_seconds: float = Field(default=2.0, alias="REQUEST_DELAY_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


def resolve_path(path: Path | str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return PROJECT_ROOT / p


def get_settings() -> Settings:
    settings = Settings()
    settings.collector_db = resolve_path(settings.collector_db)
    settings.export_path = resolve_path(settings.export_path)
    return settings


def ensure_runtime_dirs(settings: Settings) -> None:
    settings.collector_db.parent.mkdir(parents=True, exist_ok=True)
    settings.export_path.parent.mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "data" / "sessions").mkdir(parents=True, exist_ok=True)
    (PROJECT_ROOT / "logs").mkdir(parents=True, exist_ok=True)


def require_telegram_credentials(settings: Settings) -> None:
    if not settings.tg_api_id or not settings.tg_api_hash:
        raise SystemExit(
            "TG_API_ID / TG_API_HASH 未配置。请复制 .env.example 为 .env 后填写 Telegram API 信息。"
        )
