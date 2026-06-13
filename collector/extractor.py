from __future__ import annotations

import re
from dataclasses import dataclass
from .normalizer import normalize_tg_link, NormalizedLink

URL_RE = re.compile(
    r"(?:(?:https?://)?(?:t\.me|telegram\.me)/[A-Za-z0-9_+/][A-Za-z0-9_+/\-?=&%.]*)",
    re.IGNORECASE,
)

MENTION_RE = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_])")

TYPE_CONTEXT = {
    "channel": ("频道", "订阅", "channel", "广播"),
    "group": ("群组", "群聊", "交流群", "group", "megagroup"),
    "bot": ("机器人", "bot"),
}


@dataclass
class ExtractedCandidate:
    raw: str
    url: str
    username: str
    type_hint: str | None
    confidence: float
    reject_reason: str = ""


def infer_type_hint(text: str) -> str | None:
    lowered = (text or "").lower()
    scores: dict[str, int] = {}
    for kind, keywords in TYPE_CONTEXT.items():
        scores[kind] = sum(1 for kw in keywords if kw.lower() in lowered)
    best = max(scores.items(), key=lambda item: item[1])
    return best[0] if best[1] > 0 else None


def score_candidate(text: str, link: NormalizedLink, from_mention: bool = False) -> float:
    score = 0.45 if from_mention else 0.60
    context = (text or "").lower()

    if "https://t.me/" in context or "t.me/" in context:
        score += 0.12
    if any(word in context for word in ("频道", "群组", "群聊", "资源", "导航", "订阅", "telegram")):
        score += 0.12
    if link.username and link.username.lower() in context:
        score += 0.08
    if "广告" in context:
        score -= 0.05

    return max(0.0, min(score, 0.99))


def extract_candidates(text: str, include_mentions: bool = False) -> list[ExtractedCandidate]:
    text = text or ""
    found: dict[str, ExtractedCandidate] = {}
    type_hint = infer_type_hint(text)

    for match in URL_RE.finditer(text):
        raw = match.group(0)
        link = normalize_tg_link(raw)
        if link.rejected:
            continue
        found[link.url.lower()] = ExtractedCandidate(
            raw=raw,
            url=link.url,
            username=link.username,
            type_hint=type_hint,
            confidence=score_candidate(text, link),
        )

    if include_mentions:
        for match in MENTION_RE.finditer(text):
            raw = "@" + match.group(1)
            link = normalize_tg_link(raw)
            if link.rejected:
                continue
            key = link.url.lower()
            found.setdefault(
                key,
                ExtractedCandidate(
                    raw=raw,
                    url=link.url,
                    username=link.username,
                    type_hint=type_hint,
                    confidence=score_candidate(text, link, from_mention=True),
                ),
            )

    return list(found.values())
