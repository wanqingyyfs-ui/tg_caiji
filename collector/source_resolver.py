from __future__ import annotations

from typing import Any

from .normalizer import canonical_username, normalize_tg_link


def username_from_ref(chat_ref: str) -> str | None:
    value = (chat_ref or "").strip()
    if not value:
        return None
    link = normalize_tg_link(value)
    if not link.rejected and link.username:
        return link.username
    return canonical_username(value)


def entity_username(entity: Any) -> str | None:
    return canonical_username(getattr(entity, "username", None))


def entity_title(entity: Any) -> str:
    return (
        getattr(entity, "title", None)
        or getattr(entity, "first_name", None)
        or getattr(entity, "username", None)
        or str(getattr(entity, "id", "unknown"))
    )


async def build_dialog_username_map(client) -> dict[str, Any]:
    by_username: dict[str, Any] = {}
    async for dialog in client.iter_dialogs(limit=None):
        entity = dialog.entity
        username = entity_username(entity)
        if username:
            by_username[username] = entity
    return by_username


async def resolve_source_from_dialogs(client, chat_ref: str, dialog_map: dict[str, Any] | None = None) -> Any:
    username = username_from_ref(chat_ref)
    if username:
        if dialog_map is None:
            dialog_map = await build_dialog_username_map(client)
        entity = dialog_map.get(username)
        if entity is None:
            raise ValueError(f"source_not_in_joined_dialogs:{username}")
        return entity
    return await client.get_input_entity(chat_ref)
