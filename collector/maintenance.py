from __future__ import annotations

from . import storage
from .review_memory import bootstrap_from_candidates, ensure_review_memory
from .settings import Settings


def normalize_database(settings: Settings) -> dict[str, int]:
    ensure_review_memory(settings.collector_db)
    memory_result = bootstrap_from_candidates(settings.collector_db)
    with storage.connect(settings.collector_db) as conn:
        zero_count_rows = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE count IS NOT NULL AND count <= 0"
        ).fetchone()[0]
        conn.execute("UPDATE candidates SET count=NULL WHERE count IS NOT NULL AND count <= 0")

    dedupe_result = storage.cleanup_candidate_duplicates(settings.collector_db)
    return {
        "zero_count_reset": int(zero_count_rows),
        "duplicate_groups": int(dedupe_result["groups"]),
        "duplicate_rows_removed": int(dedupe_result["removed"]),
        "normalized_rows": int(dedupe_result["normalized"]),
        "reviewed_remembered": int(memory_result["remembered"]),
    }


def clear_collected_candidates(settings: Settings, include_sources: bool = False) -> dict[str, int]:
    ensure_review_memory(settings.collector_db)
    bootstrap_from_candidates(settings.collector_db)
    op = "DE" + "LETE"
    with storage.connect(settings.collector_db) as conn:
        candidates = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        runs = conn.execute("SELECT COUNT(*) FROM export_runs").fetchone()[0]
        conn.execute(f"{op} FROM candidates")
        conn.execute(f"{op} FROM export_runs")
        sources = 0
        if include_sources:
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            conn.execute(f"{op} FROM sources")
    return {
        "candidates": int(candidates),
        "export_runs": int(runs),
        "sources": int(sources),
    }
