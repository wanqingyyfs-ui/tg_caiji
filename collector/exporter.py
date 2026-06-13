from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from . import storage


def candidate_to_import_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": row.get("url") or "",
        "username": row.get("username") or "",
        "name": row.get("title") or row.get("name") or row.get("username") or "",
        "type_hint": row.get("type") or row.get("type_hint") or "",
        "source_chat": row.get("source_chat") or "",
        "source_message_id": row.get("source_message_id"),
        "discovered_at": row.get("first_seen_at") or "",
        "confidence": row.get("confidence") or 0,
    }


def export_jsonl(db_path: Path, output_path: Path, status: str = "approved", min_confidence: float = 0.0, mark_exported: bool = False) -> dict[str, Any]:
    rows, _ = storage.list_candidates(
        db_path=db_path,
        status=status,
        min_confidence=min_confidence,
        limit=100000,
        offset=0,
    )

    export_rows = []
    ids = []
    for row in rows:
        if not row.get("url") or not row.get("username"):
            continue
        if row.get("private"):
            continue
        item = candidate_to_import_item(row)
        export_rows.append(item)
        ids.append(int(row["id"]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for item in export_rows:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    if mark_exported:
        storage.mark_exported(db_path, ids, str(output_path), status)

    return {"path": str(output_path), "count": len(export_rows)}


def export_csv(db_path: Path, output_path: Path, status: str = "approved", min_confidence: float = 0.0) -> dict[str, Any]:
    rows, _ = storage.list_candidates(
        db_path=db_path,
        status=status,
        min_confidence=min_confidence,
        limit=100000,
        offset=0,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["url", "username", "name", "type_hint", "source_chat", "source_message_id", "discovered_at", "confidence"]
    count = 0
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            if not row.get("url") or not row.get("username") or row.get("private"):
                continue
            writer.writerow(candidate_to_import_item(row))
            count += 1
    return {"path": str(output_path), "count": count}
