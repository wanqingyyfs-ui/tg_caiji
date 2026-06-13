from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import storage
from .normalizer import canonical_username
from .public_page import fetch_public_page_meta
from .review_memory import remember_username, reviewed_status
from .safety import safe_snippet

RESOURCE_TYPES = {"channel", "group", "bot"}


@dataclass(frozen=True)
class GateResult:
    action: str
    username: str
    url: str
    reason: str = ""
    candidate_id: int = 0
    count: int | None = None
    type_hint: str | None = None


def handle_link(
    db_path: Path,
    item: Any,
    source_chat: str,
    source_message_id: int | None,
    source_message_date: str | None,
    text: str,
) -> GateResult:
    username = canonical_username(getattr(item, "username", None))
    url = str(getattr(item, "url", ""))
    if not username:
        return GateResult("ignored", "", url, "bad_username")

    status = reviewed_status(db_path, username)
    if status:
        return GateResult("ignored", username, url, status)

    meta = fetch_public_page_meta(username)
    if not meta.fetched:
        return GateResult("ignored", username, url, "page_unreachable")

    if meta.type_hint not in RESOURCE_TYPES:
        remember_username(
            db_path,
            username,
            "rejected",
            reason="not_resource",
            title=meta.title,
            type_value=meta.type_hint,
            count=meta.count,
        )
        return GateResult("ignored", username, url, "not_resource", count=meta.count, type_hint=meta.type_hint)

    candidate_id = storage.upsert_candidate(
        db_path,
        {
            "url": url,
            "username": username,
            "name": meta.title or username,
            "type_hint": meta.type_hint or getattr(item, "type_hint", None),
            "source_chat": source_chat,
            "source_message_id": source_message_id,
            "source_message_date": source_message_date,
            "text_snippet": safe_snippet(text),
            "confidence": float(getattr(item, "confidence", 0) or 0),
        },
    )
    if not candidate_id:
        return GateResult("ignored", username, url, "reviewed")

    storage.update_candidate_meta(
        db_path,
        url,
        {
            "valid": True,
            "private": False,
            "username": username,
            "title": meta.title or username,
            "description": meta.description,
            "type": meta.type_hint,
            "count": meta.count,
        },
    )
    return GateResult("candidate", username, url, candidate_id=candidate_id, count=meta.count, type_hint=meta.type_hint)
