from __future__ import annotations

import logging
import secrets
import shutil
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .config import SETTINGS_MODEL
from .errors import ValidationError
from .io_utils import load_json, save_json
from .main import (
    ROOT,
    SETTINGS,
    _duplicate_report,
    approve_output_file,
    evergreen_cmd,
    rag_store,
    regenerate_output_field,
    release_cmd,
    today_cmd,
    update_output_drafts,
)
from .ollama_client import OllamaError
from .preview import render_post_preview_html
from .web_helpers import history_items, history_mode, safe_output, serialize_output, website_push_status
from .web_push_gate import consume as consume_push_gate
from .web_push_gate import get_prepared, issue_token
from .website import WebsiteError, prepare_website_update, push_website_branch

LOG = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).with_name("web_static")
OUTPUT_DIR = ROOT / "output"
UPLOAD_DIR = OUTPUT_DIR / "web_uploads"

app = FastAPI(title="Author Agent Local UI", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

# In-memory cache backed by a short-lived persisted gate under output/.
_PREPARED: dict[str, dict] = {}


def _error(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


def _safe_output(name: str) -> Path:
    return safe_output(OUTPUT_DIR, name)


def _serialize_output(path: Path) -> dict:
    return serialize_output(path)


def _history_mode(data: dict) -> str:
    return history_mode(data)


def _website_push_status(data: dict) -> str:
    return website_push_status(data)


def _history_items(filter_name: str = "all") -> list[dict]:
    return history_items(OUTPUT_DIR, filter_name)


async def _save_upload(upload: UploadFile | None, *, required: bool = False) -> str:
    if upload is None or not upload.filename:
        if required:
            raise ValidationError("A manuscript file is required.")
        return ""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload.filename).name
    target = UPLOAD_DIR / f"{uuid4().hex[:10]}-{safe_name}"
    with target.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return str(target)


@app.exception_handler(OllamaError)
async def ollama_error_handler(_request, exc: OllamaError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(WebsiteError)
async def website_error_handler(_request, exc: WebsiteError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
@app.get("/api/health")
def health():
    rag_ready = False
    rag_error = ""
    try:
        rag_store().stats()
        rag_ready = True
    except Exception as exc:
        rag_error = str(exc)
    return {
        "status": "ok" if rag_ready else "degraded",
        "local_only": True,
        "date": date.today().isoformat(),
        "config_loaded": SETTINGS_MODEL is not None,
        "rag_db_reachable": rag_ready,
        "rag_error": rag_error,
    }


@app.post("/api/release")
async def generate_release(
    book: UploadFile = File(...),
    image: UploadFile | None = File(None),
    release_date: str = Form(...),
    book_url: str = Form(""),
    published: bool = Form(False),
):
    try:
        book_path = await _save_upload(book, required=True)
        image_path = await _save_upload(image)
        args = SimpleNamespace(
            book=book_path,
            image=image_path,
            date=release_date,
            url=book_url,
            published=published,
            dry_run=False,
            # Web generation previews the website patch only; Prepare is the explicit mutation gate.
            website_dry_run=True,
        )
        _result, out = release_cmd(args, emit=False)
        return _serialize_output(out)
    except (ValueError, OllamaError, WebsiteError) as exc:
        raise _error(exc, 503 if isinstance(exc, OllamaError) else 400) from exc


@app.post("/api/evergreen")
async def generate_evergreen(
    post_date: str = Form(...),
    image: UploadFile | None = File(None),
):
    try:
        image_path = await _save_upload(image)
        args = SimpleNamespace(date=post_date, image=image_path, dry_run=False)
        _result, out = evergreen_cmd(args, emit=False)
        return _serialize_output(out)
    except (ValueError, OllamaError) as exc:
        raise _error(exc, 503 if isinstance(exc, OllamaError) else 400) from exc


@app.post("/api/today")
def generate_today(payload: dict = Body(default_factory=dict)):
    try:
        args = SimpleNamespace(
            date=str(payload.get("date", "")),
            window=int(payload.get("window", SETTINGS.get("orchestrator", {}).get("window_days", 1))),
            force=bool(payload.get("force", False)),
            dry_run=False,
            website_dry_run=True,
        )
        manifest = today_cmd(args)
        out = Path(str(manifest["output"]))
        if not out.is_file():
            raise ValidationError(f"Today output was not found: {out}")
        return {"manifest": manifest, **_serialize_output(out)}
    except (ValueError, OllamaError, WebsiteError) as exc:
        raise _error(exc, 503 if isinstance(exc, OllamaError) else 400) from exc


@app.get("/api/history")
def history(filter: str = "all"):
    try:
        items = _history_items(filter)
        return {"filter": filter, "count": len(items), "items": items}
    except ValueError as exc:
        raise _error(exc) from exc


@app.get("/api/output/{name}")
def get_output(name: str):
    try:
        return _serialize_output(_safe_output(name))
    except ValueError as exc:
        raise _error(exc, 404) from exc


@app.patch("/api/output/{name}/drafts")
def save_drafts(name: str, payload: dict = Body(...)):
    try:
        path = _safe_output(name)
        drafts = payload.get("drafts", payload)
        if not isinstance(drafts, dict):
            raise ValidationError("drafts must be an object.")
        data = update_output_drafts(path, drafts)
        return {"output_file": name, "data": data}
    except ValueError as exc:
        raise _error(exc) from exc


@app.post("/api/output/{name}/regenerate/{field}")
def regenerate(name: str, field: str):
    try:
        return regenerate_output_field(_safe_output(name), field)
    except (ValueError, OllamaError) as exc:
        raise _error(exc, 503 if isinstance(exc, OllamaError) else 400) from exc


@app.post("/api/output/{name}/check/{field}")
def duplicate_check(name: str, field: str, payload: dict = Body(...)):
    try:
        if field not in {"facebook", "instagram", "teaser"}:
            raise ValidationError("Field must be facebook, instagram, or teaser.")
        path = _safe_output(name)
        text = str(payload.get("text", ""))
        data = update_output_drafts(path, {field: text})
        platform = "instagram" if field == "teaser" else field
        check = _duplicate_report(rag_store(), text, platform)
        data.setdefault("duplicate_check", {})[field] = check
        save_json(path, data)
        return check
    except (ValueError, OllamaError) as exc:
        raise _error(exc, 503 if isinstance(exc, OllamaError) else 400) from exc


@app.get("/api/output/{name}/preview", response_class=HTMLResponse)
def preview(name: str):
    try:
        path = _safe_output(name)
        data = load_json(path, {})
        image_src = f"/api/output/{name}/image" if data.get("image") else ""
        return HTMLResponse(render_post_preview_html(data, image_src=image_src))
    except ValueError as exc:
        raise _error(exc, 404) from exc


@app.get("/api/output/{name}/image")
def output_image(name: str):
    try:
        data = load_json(_safe_output(name), {})
        image = Path(str(data.get("image", ""))).expanduser()
        if not image.is_file():
            raise ValidationError("Promotional image is not available.")
        if image.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            raise ValidationError("Unsupported preview image format.")
        return FileResponse(image)
    except ValueError as exc:
        raise _error(exc, 404) from exc


@app.post("/api/output/{name}/website/prepare")
def website_prepare(name: str):
    try:
        path = _safe_output(name)
        data = load_json(path, {})
        if not isinstance(data.get("profile"), dict):
            raise ValidationError("Website updates are only available for release outputs.")
        if not data.get("published"):
            raise ValidationError("Website Prepare is only available for a published release, not a scheduled teaser.")
        wc = SETTINGS.get("website", {})
        result = prepare_website_update(
            wc.get("repo_path", ""),
            data["profile"].get("title", Path(data.get("book", "book")).stem),
            data.get("release_date", data.get("date", "")),
            data.get("url", ""),
            calendar_data_file=wc.get("calendar_data_file", ""),
            branch_prefix=wc.get("branch_prefix", "author-agent"),
            commit=True,
            dry_run=False,
        )
        data["website"] = result
        save_json(path, data)
        if result.get("status") not in {"prepared", "unchanged"}:
            raise ValidationError(result.get("reason") or "Website preparation did not create a prepared branch.")
        token = issue_token(
            OUTPUT_DIR,
            _PREPARED,
            name,
            str(result.get("branch", "")),
            ttl_seconds=SETTINGS_MODEL.web.push_token_ttl_seconds,
        )
        return {"website": result, "push_token": token}
    except (ValueError, WebsiteError) as exc:
        raise _error(exc) from exc


@app.post("/api/output/{name}/website/push")
def website_push(name: str, payload: dict = Body(...)):
    try:
        _safe_output(name)
        prepared = get_prepared(OUTPUT_DIR, _PREPARED, name)
        if not prepared:
            raise ValidationError("Push is disabled until Prepare succeeds and its approval token is still valid.")
        token = str(payload.get("push_token", ""))
        if not token or not secrets.compare_digest(token, str(prepared["token"])):
            raise ValidationError("Invalid or expired push approval token. Run Prepare again.")
        wc = SETTINGS.get("website", {})
        result = push_website_branch(wc.get("repo_path", ""), prepared["branch"])
        path = _safe_output(name)
        data = load_json(path, {})
        website = data.setdefault("website", {})
        if isinstance(website, dict):
            website.update(result)
            website["push_performed"] = bool(result.get("push_performed", True))
            website["pushed_at"] = datetime.now(timezone.utc).isoformat()
        save_json(path, data)
        consume_push_gate(OUTPUT_DIR, _PREPARED, name)
        return result
    except (ValueError, WebsiteError) as exc:
        raise _error(exc) from exc


@app.post("/api/output/{name}/approve")
def approve(name: str):
    try:
        return approve_output_file(_safe_output(name))
    except (ValueError, OllamaError) as exc:
        raise _error(exc, 503 if isinstance(exc, OllamaError) else 400) from exc
