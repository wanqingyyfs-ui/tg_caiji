from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import storage
from .exporter import candidate_to_import_item, export_jsonl
from .review_memory import bootstrap_from_candidates, ensure_review_memory, remember_candidate_ids
from .settings import PROJECT_ROOT, get_settings, ensure_runtime_dirs

settings = get_settings()
ensure_runtime_dirs(settings)
storage.init_db(settings.collector_db)
ensure_review_memory(settings.collector_db)
bootstrap_from_candidates(settings.collector_db)

app = FastAPI(title="TG Suoyin Collector Admin")
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "collector" / "static")), name="static")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "collector" / "templates"))


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def clean_status(value: str | None) -> str | None:
    if value in {"new", "approved", "rejected", "exported"}:
        return value
    if value == "all":
        return None
    return "new"


def candidates_url(page: int = 1, **filters: Any) -> str:
    params: dict[str, str | int | float] = {"page": max(1, int(page))}
    for key, value in filters.items():
        if value is None or value == "":
            continue
        params[key] = value
    if params == {"page": 1}:
        return "/candidates"
    return "/candidates?" + urlencode(params)


def _download_filename(status: str, fmt: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"tg_suoyin_{status}_{stamp}.{fmt}"


def _export_rows_for_download(status: str, min_confidence: float) -> tuple[list[dict[str, Any]], list[int]]:
    rows, _ = storage.list_candidates(
        settings.collector_db,
        status=status,
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


@app.get("/", response_class=HTMLResponse)
async def home():
    return redirect("/candidates")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    bootstrap_from_candidates(settings.collector_db)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"stats": storage.stats(settings.collector_db), "export_path": settings.export_path},
    )


@app.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="sources.html",
        context={"sources": storage.list_sources(settings.collector_db)},
    )


@app.post("/sources/add")
async def add_source(
    name: Annotated[str, Form()],
    chat_ref: Annotated[str, Form()],
    backfill_limit: Annotated[int, Form()] = 500,
    enabled: Annotated[str | None, Form()] = None,
):
    storage.upsert_source(
        settings.collector_db,
        name=name,
        chat_ref=chat_ref,
        backfill_limit=backfill_limit,
        enabled=enabled == "on",
    )
    return redirect("/sources")


@app.post("/sources/{source_id}/toggle")
async def toggle_source(source_id: int):
    row = storage.get_source(settings.collector_db, source_id)
    if row:
        storage.set_source_enabled(settings.collector_db, source_id, not bool(row["enabled"]))
    return redirect("/sources")


@app.post("/sources/{source_id}/delete")
async def delete_source(source_id: int):
    storage.delete_source(settings.collector_db, source_id)
    return redirect("/sources")


@app.get("/candidates", response_class=HTMLResponse)
async def candidates_page(
    request: Request,
    status: str | None = Query(default=None),
    type_value: str | None = Query(default=None, alias="type"),
    q: str | None = Query(default=None),
    min_count: int | None = Query(default=None),
    max_count: int | None = Query(default=None),
    min_confidence: float | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=20, le=200),
    msg: str | None = Query(default=None),
):
    bootstrap_from_candidates(settings.collector_db)
    current_status = clean_status(status)
    limit = max(20, min(int(page_size), 200))
    offset = (page - 1) * limit
    rows, total = storage.list_candidates(
        settings.collector_db,
        status=current_status,
        type_value=type_value or None,
        q=q or None,
        min_count=min_count,
        max_count=max_count,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    filters = {
        "status": current_status or "all",
        "type": type_value or "",
        "q": q or "",
        "min_count": min_count or "",
        "max_count": max_count or "",
        "min_confidence": min_confidence or "",
        "page_size": limit,
    }
    url_filters = {
        "status": current_status or "all",
        "type": type_value or None,
        "q": q or None,
        "min_count": min_count,
        "max_count": max_count,
        "min_confidence": min_confidence,
        "page_size": limit,
    }
    return templates.TemplateResponse(
        request=request,
        name="candidates.html",
        context={
            "items": rows,
            "total": total,
            "page": page,
            "limit": limit,
            "filters": filters,
            "message": msg or "",
            "current_url": str(request.url),
            "prev_url": candidates_url(page - 1, **url_filters) if page > 1 else "",
            "next_url": candidates_url(page + 1, **url_filters) if page * limit < total else "",
        },
    )


@app.post("/candidates/batch")
async def batch_candidates(request: Request):
    form = await request.form()
    raw_ids = form.getlist("ids")
    ids: list[int] = []
    for raw_id in raw_ids:
        try:
            ids.append(int(str(raw_id)))
        except ValueError:
            continue

    action = str(form.get("action") or "approve")
    status_map = {"approve": "approved", "reject": "rejected", "new": "new"}
    status = status_map.get(action, "approved")
    if status in {"approved", "rejected"}:
        remember_candidate_ids(settings.collector_db, ids, status)
    updated = storage.batch_set_status(settings.collector_db, ids, status)
    return_to = str(form.get("return_to") or "/candidates")
    sep = "&" if "?" in return_to else "?"
    return redirect(f"{return_to}{sep}msg=批量操作完成：更新 {updated} 条")


@app.get("/candidates/{candidate_id}", response_class=HTMLResponse)
async def candidate_detail(request: Request, candidate_id: int):
    item = storage.get_candidate(settings.collector_db, candidate_id)
    if not item:
        return redirect("/candidates")
    return templates.TemplateResponse(request=request, name="candidate_detail.html", context={"item": item})


@app.post("/candidates/{candidate_id}/review")
async def review_candidate(
    candidate_id: int,
    status: Annotated[str, Form()],
    note: Annotated[str, Form()] = "",
    reject_reason: Annotated[str, Form()] = "",
):
    if status in {"approved", "rejected"}:
        remember_candidate_ids(settings.collector_db, [candidate_id], status, reject_reason or note or status)
    storage.set_candidate_status(settings.collector_db, candidate_id, status, note=note, reject_reason=reject_reason)
    return redirect("/candidates")


@app.get("/export/download")
async def export_download(
    status: str = Query(default="approved", pattern="^(new|approved|rejected|exported)$"),
    format: str = Query(default="jsonl", pattern="^(jsonl|csv)$"),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    mark_exported: bool = Query(default=False),
):
    rows, ids = _export_rows_for_download(status, min_confidence)
    filename = _download_filename(status, format)

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
        storage.mark_exported(settings.collector_db, ids, f"browser-download:{filename}", status)

    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/export")
async def export(
    status: Annotated[str, Form()] = "approved",
    min_confidence: Annotated[float, Form()] = 0.0,
    mark_exported: Annotated[str | None, Form()] = None,
):
    result = export_jsonl(
        settings.collector_db,
        settings.export_path,
        status=status,
        min_confidence=min_confidence,
        mark_exported=mark_exported == "on",
    )
    return redirect(f"/dashboard?exported={result['count']}")


@app.get("/health")
async def health():
    return {"ok": True, "db": str(settings.collector_db)}
