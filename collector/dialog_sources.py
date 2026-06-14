from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DialogSource:
    name: str
    entity: Any
    kind: str
    username: str | None = None


def _entity_name(entity: Any, fallback: str = "unknown") -> str:
    return (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or getattr(entity, "first_name", None)
        or str(getattr(entity, "id", fallback))
    )


def _dialog_kind(entity: Any) -> str | None:
    if getattr(entity, "bot", False):
        return None
    if getattr(entity, "megagroup", False):
        return "group"
    if getattr(entity, "broadcast", False):
        return "channel"
    class_name = entity.__class__.__name__.lower()
    if class_name == "chat":
        return "group"
    if class_name == "channel":
        return "channel"
    return None


async def list_joined_collect_sources(client) -> list[DialogSource]:
    sources: list[DialogSource] = []
    seen_ids: set[int] = set()
    async for dialog in client.iter_dialogs(limit=None):
        entity = dialog.entity
        kind = _dialog_kind(entity)
        if not kind:
            continue
        entity_id = int(getattr(entity, "id", 0) or 0)
        if entity_id and entity_id in seen_ids:
            continue
        if entity_id:
            seen_ids.add(entity_id)
        sources.append(
            DialogSource(
                name=getattr(dialog, "name", None) or _entity_name(entity),
                entity=entity,
                kind=kind,
                username=getattr(entity, "username", None),
            )
        )
    return sources
