from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import storage
from .app_config import ensure_app_config, get_min_member_count, set_min_member_count
from .exporter import candidate_to_import_item
from .review_memory import bootstrap_from_candidates, ensure_review_memory
from .settings import PROJECT_ROOT, get_settings, ensure_runtime_dirs

settings = get_settings()
ensure_runtime_dirs(settings)
storage.init_db(settings.collector_db)
ensure_review_memory(settings.collector_db)
ensure_app_config(settings.collector_db)
bootstrap_from_candidates(settings.collector_db)

app = FastAPI(title="TG Suoyin Collector")
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "collector" / "static")), name="static")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "collector" / "templates"))


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def public_stats() -> dict[str, Any]:
    raw = storage.stats(settings.collector_db)
    exported = int(raw.get("exported", 0) or 0)
    unexported = int(raw.get("approved", 0) or 0)
    collected = exported + unexported
    raw.update({"collected": collected, "exported": exported, "unexported": unexported})
    return raw


def _download_filename(status: str, fmt: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"tg_suoyin_{status}_{stamp}.{fmt}"


def _export_rows_for_download(min_confidence: float) -> tuple[list[dict[str, Any]], list[int]]:
    rows, _ = storage.list_candidates(
        settings.collector_db,
        status="approved",
        min_confidence=min_confidence,
        limit=100000,
        offset=0,
    )
    export_rows: list[dict[str, Any]] = []
    ids: list[int] = []
    for row in rows:
        if not row.get("url") or not row.get("username"):
            continue
        if row.get("private"):
            continue
        export_rows.append(candidate_to_import_item(row))
        ids.append(int(row["id"]))
    return export_rows, ids


def dashboard_context(request: Request, message: str = "") -> dict[str, Any]:
    bootstrap_from_candidates(settings.collector_db)
    return {
        "request": request,
        "stats": public_stats(),
        "min_member_count": get_min_member_count(settings.collector_db),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "message": message,
    }


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, msg: str = ""):
    return templates.TemplateResponse(request=request, name="single_dashboard.html", context=dashboard_context(request, msg))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, msg: str = ""):
    return templates.TemplateResponse(request=request, name="single_dashboard.html", context=dashboard_context(request, msg))


@app.get("/candidates", response_class=HTMLResponse)
async def candidates_page(request: Request):
    return templates.TemplateResponse(request=request, name="single_dashboard.html", context=dashboard_context(request))


@app.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    return templates.TemplateResponse(request=request, name="single_dashboard.html", context=dashboard_context(request))


@app.post("/settings/min-member-count")
async def update_min_member_count(min_member_count: Annotated[int, Form()] = 0):
    value = set_min_member_count(settings.collector_db, min_member_count)
    return redirect(f"/?msg=最低人数门槛已保存：{value}")


@app.get("/export/download")
async def export_download(
    format: str = Query(default="jsonl", pattern="^(jsonl|csv)$"),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    mark_exported: bool = Query(default=True),
):
    rows, ids = _export_rows_for_download(min_confidence)
    filename = _download_filename("unexported", format)

    if format == "csv":
        output = io.StringIO()
        fields = ["url", "username", "name", "type_hint", "source_chat", "source_message_id", "discovered_at", "confidence"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        content = "\ufeff" + output.getvalue()
        media_type = "text/csv; charset=utf-8"
    else:
        content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        media_type = "application/x-ndjson; charset=utf-8"

    if mark_exported:
        storage.mark_exported(settings.collector_db, ids, f"browser-download:{filename}", "approved")

    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/stats")
async def api_stats():
    return {
        "stats": public_stats(),
        "min_member_count": get_min_member_count(settings.collector_db),
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/health")
async def health():
    return {"ok": True, "db": str(settings.collector_db), "stats": public_stats()}
