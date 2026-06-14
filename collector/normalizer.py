from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
MESSAGE_ID_RE = re.compile(r"^[0-9]+$")

REJECTED_FIRST_SEGMENTS = {
    "+",
    "joinchat",
    "c",
    "share",
    "addstickers",
    "setlanguage",
    "proxy",
    "iv",
    "addemoji",
    "addlist",
    "login",
    "bg",
}


@dataclass(frozen=True)
class NormalizedLink:
    url: str
    username: str
    rejected: bool = False
    reject_reason: str = ""


def canonical_username(username: str | None) -> str | None:
    value = (username or "").strip().lstrip("@")
    if not value:
        return None
    if not USERNAME_RE.match(value):
        return None
    return value.lower()


def canonical_url_from_username(username: str) -> str:
    return f"https://t.me/{username.lower()}"


def clean_raw_link(value: str) -> str:
    value = (value or "").strip()
    value = value.strip(" \t\r\n<>[](){}'\"“”‘’，。；;、")
    value = value.replace("telegram.me/", "t.me/")
    if value.startswith("@"):
        return value
    if value.startswith("t.me/"):
        value = "https://" + value
    if value.startswith("http://"):
        value = "https://" + value.removeprefix("http://")
    return value


def username_from_path_parts(parts: list[str]) -> str | None:
    """Return public username from Telegram paths.

    Supported examples:
    - /username
    - /username/1190
    - /username/1190?single
    - /s/username
    - /s/username/1190

    Unsupported examples are intentionally rejected elsewhere:
    - /c/123456/789 private/internal channel links
    - /+invite private invite links
    - /joinchat/... private invite links
    """
    if not parts:
        return None
    if parts[0].lower() == "s" and len(parts) >= 2:
        return parts[1]
    return parts[0]


def is_message_link(path_parts: list[str]) -> bool:
    if len(path_parts) >= 2 and MESSAGE_ID_RE.match(path_parts[1]):
        return True
    if len(path_parts) >= 3 and path_parts[0].lower() == "s" and MESSAGE_ID_RE.match(path_parts[2]):
        return True
    return False


def normalize_tg_link(raw: str) -> NormalizedLink:
    value = clean_raw_link(raw)
    if not value:
        return NormalizedLink("", "", True, "空链接")

    if value.startswith("@"):
        username = canonical_username(value[1:])
        if username:
            return NormalizedLink(canonical_url_from_username(username), username)
        return NormalizedLink("", "", True, "无效 @username")

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        return NormalizedLink("", "", True, "非 Telegram 链接")

    path = parsed.path.strip("/")
    if not path:
        return NormalizedLink("", "", True, "缺少路径")

    parts = [p for p in path.split("/") if p]
    if not parts:
        return NormalizedLink("", "", True, "缺少 username")

    raw_username = username_from_path_parts(parts)
    if not raw_username:
        return NormalizedLink("", "", True, "缺少 username")

    first_lower = raw_username.lower()
    if raw_username.startswith("+"):
        return NormalizedLink("", "", True, "私密邀请链接")
    if first_lower in REJECTED_FIRST_SEGMENTS:
        return NormalizedLink("", "", True, f"不支持的 Telegram 链接类型: {raw_username}")

    username = canonical_username(raw_username)
    if not username:
        return NormalizedLink("", "", True, "无效 username")

    return NormalizedLink(canonical_url_from_username(username), username)


def normalize_type_hint(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    aliases = {
        "频道": "channel",
        "channel": "channel",
        "群组": "group",
        "群": "group",
        "group": "group",
        "supergroup": "group",
        "机器人": "bot",
        "bot": "bot",
    }
    return aliases.get(v)
