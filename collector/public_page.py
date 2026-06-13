from __future__ import annotations

import html
import re
import urllib.request
from dataclasses import dataclass

COUNT_RE = re.compile(
    r"([0-9][0-9\s,\.]*\s*[KkMm]?)\s+(subscribers|members|users|online)",
    re.IGNORECASE,
)
EXTRA_RE = re.compile(r'<div class="tgme_page_extra">(.*?)</div>', re.IGNORECASE | re.DOTALL)
TITLE_RE = re.compile(r'<div class="tgme_page_title"[^>]*>\s*<span[^>]*>(.*?)</span>', re.IGNORECASE | re.DOTALL)
DESC_RE = re.compile(r'<div class="tgme_page_description"[^>]*>(.*?)</div>', re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class PublicPageMeta:
    title: str | None = None
    description: str | None = None
    count: int | None = None
    type_hint: str | None = None


def _strip_tags(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<.*?>", "", value, flags=re.DOTALL)
    return html.unescape(value).strip()


def _parse_count(value: str) -> int | None:
    value = value.replace("\xa0", " ").strip()
    m = re.match(r"^([0-9][0-9\s,\.]*)([KkMm]?)$", value)
    if not m:
        return None
    number = m.group(1).replace(" ", "").replace(",", "")
    suffix = m.group(2).lower()
    try:
        base = float(number)
    except ValueError:
        return None
    if suffix == "k":
        base *= 1000
    elif suffix == "m":
        base *= 1000000
    return int(base)


def fetch_public_page_meta(username: str, timeout: float = 10.0) -> PublicPageMeta:
    username = username.strip().lstrip("@")
    if not username:
        return PublicPageMeta()

    req = urllib.request.Request(
        f"https://t.me/{username}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return PublicPageMeta()

    title = None
    desc = None
    count = None
    type_hint = None

    title_m = TITLE_RE.search(text)
    if title_m:
        title = _strip_tags(title_m.group(1)) or None

    desc_m = DESC_RE.search(text)
    if desc_m:
        desc = _strip_tags(desc_m.group(1)) or None

    extra_text = ""
    extra_m = EXTRA_RE.search(text)
    if extra_m:
        extra_text = _strip_tags(extra_m.group(1))
        m = COUNT_RE.search(extra_text)
        if m:
            count = _parse_count(m.group(1))
            word = m.group(2).lower()
            if word == "subscribers":
                type_hint = "channel"
            elif word in {"members", "online"}:
                type_hint = "group"
            elif word == "users":
                type_hint = "bot"

    return PublicPageMeta(title=title, description=desc, count=count, type_hint=type_hint)
