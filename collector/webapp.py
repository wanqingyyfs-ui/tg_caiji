from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import storage
from .exporter import export_jsonl
from .settings import PROJECT_ROOT, get_settings, ensure_runtime_dirs

settings = get_settings()
ensure_runtime_dirs(settings)
storage.init_db(settings.collector_db)

app = FastAPI(title="TG Suoyin Collector Admin")
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "collector" / "static")), name="static")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "collector" / "templates"))


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def candidates_url(page: int = 1, **filters: Any) -> str:
    params: dict[str, str | int | float] = {"page": max(1, int(page))}
    for key, value in filters.items():
        if value is None or value == "":
            continue
        params[key] = value
    if params == {"page": 1}:
        return "/candidates"
    return "/candidates?" + urlencode(params)


@app.get("/", response_class=HTMLResponse)
async def home():
    return redirect("/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
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
    msg: str | None = Query(default=None),
):
    limit = 50
    offset = (page - 1) * limit
    rows, total = storage.list_candidates(
        settings.collector_db,
        status=status or None,
        type_value=type_value or None,
        q=q or None,
        min_count=min_count,
        max_count=max_count,
        min_confidence=min_confidence,
        limit=limit,
        offset=offset,
    )
    filters = {
        "status": status or "",
        "type": type_value or "",
        "q": q or "",
        "min_count": min_count or "",
        "max_count": max_count or "",
        "min_confidence": min_confidence or "",
    }
    url_filters = {
        "status": status or None,
        "type": type_value or None,
        "q": q or None,
        "min_count": min_count,
        "max_count": max_count,
        "min_confidence": min_confidence,
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
    updated = storage.batch_set_status(settings.collector_db, ids, status)
    return redirect(candidates_url(msg=f"批量操作完成：更新 {updated} 条"))


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
    storage.set_candidate_status(settings.collector_db, candidate_id, status, note=note, reject_reason=reject_reason)
    return redirect(f"/candidates/{candidate_id}")


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
