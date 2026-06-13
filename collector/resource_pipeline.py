from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import storage
from .extractor import CandidateLink
from .normalizer import canonical_username
from .public_page import fetch_public_page_meta
from .review_memory import remember_username, reviewed_status
from .safety import safe_snippet

ALLOWED_TYPES = {"channel", "group", "bot"}


@dataclass(frozen=True)
class ProcessResult:
    action: str
    username: str
    url: str
    reason: str = ""
    candidate_id: int = 0
    count: int | None = None
    type_hint: str | None = None


def process_candidate_link(
    db_path: Path,
    item: CandidateLink,
    source_chat: str,
    source_message_id: int | None,
    source_message_date: str | None,
    text: str,
) -> ProcessResult:
    username = canonical_username(item.username)
    if not username:
        return ProcessResult(action="skip_invalid", username="", url=item.url, reason="invalid_username")

    remembered = reviewed_status(db_path, username)
    if remembered:
        return ProcessResult(action="skip_reviewed", username=username, url=item.url, reason=remembered)

    public_meta = fetch_public_page_meta(username)
    if public_meta.type_hint not in ALLOWED_TYPES:
        remember_username(
            db_path,
            username,
            "rejected",
            reason="not_public_channel_group_or_bot",
            title=public_meta.title,
            type_value=public_meta.type_hint,
            count=public_meta.count,
        )
        return ProcessResult(
            action="skip_invalid_resource",
            username=username,
            url=item.url,
            reason="not_public_channel_group_or_bot",
            count=public_meta.count,
            type_hint=public_meta.type_hint,
        )

    candidate_id = storage.upsert_candidate(
        db_path,
        {
            "url": item.url,
            "username": username,
            "name": public_meta.title or username,
            "type_hint": public_meta.type_hint or item.type_hint,
            "source_chat": source_chat,
            "source_message_id": source_message_id,
            "source_message_date": source_message_date,
            "text_snippet": safe_snippet(text),
            "confidence": item.confidence,
        },
    )
    if not candidate_id:
        return ProcessResult(action="skip_reviewed", username=username, url=item.url, reason="reviewed_memory")

    storage.update_candidate_meta(
        db_path,
        item.url,
        {
            "valid": True,
            "private": False,
            "username": username,
            "title": public_meta.title or username,
            "description": public_meta.description,
            "type": public_meta.type_hint,
            "count": public_meta.count,
        },
    )
    return ProcessResult(
        action="candidate",
        username=username,
        url=item.url,
        candidate_id=candidate_id,
        count=public_meta.count,
        type_hint=public_meta.type_hint,
    )
