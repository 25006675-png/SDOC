"""FastAPI backend for worker and admin clients."""
from __future__ import annotations

import asyncio
import mimetypes
import os
import httpx
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .casework import CASE_STATES, CaseStore
from .drafting import draft_case_message
from .gmail import GmailSyncService
from .supabase_store import SupabaseStore


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT.parent / ".env")


class ResolveTaskRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class OverdueRequest(BaseModel):
    wait_seconds: int = Field(default=86400, ge=1, le=60 * 60 * 24 * 90)


def create_store():
    backend = os.environ.get("SDOC_STORE", "sqlite").lower()
    if backend == "supabase":
        return SupabaseStore()
    db_path = os.environ.get("SDOC_DB_PATH", str(ROOT / "data" / "sdoc.db"))
    return CaseStore(db_path)


def attachment_root():
    return Path(os.environ.get("SDOC_ATTACHMENT_ROOT", str(ROOT / "data"))).resolve()


def resolve_attachment_path(source_path: str, gmail_sync=None):
    source_path = (source_path or "").replace("\\", "/").lstrip("/")
    if not source_path.startswith("attachments/") or ".." in Path(source_path).parts:
        raise HTTPException(404, "attachment not found")
    root = attachment_root()
    candidate = (root / source_path).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(404, "attachment not found")
    if not candidate.is_file():
        if source_path.startswith("attachments/gmail/") and gmail_sync:
            try:
                candidate = Path(gmail_sync.fetch_attachment(source_path)).resolve()
            except Exception:
                raise HTTPException(404, "attachment not found")
        if not candidate.is_file():
            raise HTTPException(404, "attachment not found")
    return candidate


def create_app(store=None, start_scheduler=True):
    owns_store = store is None

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store or create_store()
        app.state.gmail_sync = GmailSyncService(app.state.store)
        task = None
        gmail_task = None
        if start_scheduler:
            interval = max(10, int(os.environ.get("SDOC_TIMER_INTERVAL", "60")))
            wait_seconds = max(1, int(os.environ.get("SDOC_WAIT_SECONDS", "86400")))
            gmail_interval = int(os.environ.get("SDOC_GMAIL_SYNC_INTERVAL", "60"))

            async def overdue_loop():
                while True:
                    await asyncio.sleep(interval)
                    await asyncio.to_thread(app.state.store.mark_overdue, wait_seconds)

            task = asyncio.create_task(overdue_loop())

            async def gmail_loop():
                while True:
                    await asyncio.sleep(max(30, gmail_interval))
                    status = app.state.gmail_sync.status()
                    if not status["configured"] or not status["connected"]:
                        continue
                    try:
                        await asyncio.to_thread(app.state.gmail_sync.sync_once)
                    except Exception as exc:
                        app.state.gmail_sync.record_error(exc)

            if gmail_interval > 0:
                gmail_task = asyncio.create_task(gmail_loop())
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if gmail_task:
                gmail_task.cancel()
                with suppress(asyncio.CancelledError):
                    await gmail_task
            app.state.gmail_sync.close()
            if owns_store:
                app.state.store.close()

    app = FastAPI(
        title="SDOC API",
        version="2.2.0",
        description="Persistent shipping-document verification case API",
        lifespan=lifespan,
    )
    origins = [
        value.strip()
        for value in os.environ.get(
            "SDOC_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
        ).split(",")
        if value.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok", "store": type(app.state.store).__name__}

    @app.get("/api/metrics")
    def metrics():
        return app.state.store.metrics()

    @app.get("/api/cases")
    def list_cases(state: str | None = Query(default=None)):
        if state and state not in CASE_STATES:
            raise HTTPException(422, f"state must be one of {sorted(CASE_STATES)}")
        return {"items": app.state.store.list_cases(state=state)}

    @app.get("/api/routed-messages")
    def routed_messages(category: str | None = Query(default=None)):
        return {"items": app.state.store.list_routed_messages(category=category)}

    @app.get("/api/mailbox/status")
    def mailbox_status():
        return app.state.gmail_sync.status()

    @app.get("/api/mailbox/connect")
    def mailbox_connect():
        try:
            return RedirectResponse(app.state.gmail_sync.authorization_url(), status_code=302)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/mailbox/oauth/callback", response_class=HTMLResponse)
    def mailbox_oauth_callback(request: Request, code: str | None = None, state: str | None = None):
        if request.query_params.get("error"):
            raise HTTPException(400, request.query_params["error"])
        if not code:
            raise HTTPException(400, "missing OAuth code")
        try:
            app.state.gmail_sync.finish_oauth(code, state)
        except ValueError as exc:
            app.state.gmail_sync.record_error(exc)
            return HTMLResponse(f"""
            <!doctype html>
            <html lang="en">
            <head><meta charset="utf-8"><title>Gmail connection issue</title></head>
            <body>
              <h1>Gmail was not connected</h1>
              <p>{str(exc)}</p>
              <p>Return to <a href="/app/">SDOC</a> and click Connect Gmail again.</p>
            </body>
            </html>
            """, status_code=400)
        except httpx.HTTPError as exc:
            app.state.gmail_sync.record_error(exc)
            raise HTTPException(502, f"Gmail OAuth exchange failed: {exc}") from exc
        return """
        <!doctype html>
        <html lang="en">
        <head><meta charset="utf-8"><title>Gmail connected</title></head>
        <body>
          <script>location.replace('/app/?mailbox=connected')</script>
          <p>Gmail connected. Return to <a href="/app/">SDOC</a>.</p>
        </body>
        </html>
        """

    @app.post("/api/mailbox/sync")
    def mailbox_sync():
        try:
            return app.state.gmail_sync.sync_once()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except httpx.HTTPError as exc:
            app.state.gmail_sync.record_error(exc)
            raise HTTPException(502, f"Gmail sync failed: {exc}") from exc

    @app.get("/api/cases/{case_id}")
    def get_case(case_id: str):
        case = app.state.store.get_case(case_id)
        if not case:
            raise HTTPException(404, "case not found")
        return case

    @app.get("/api/cases/{case_id}/draft")
    def case_draft(case_id: str):
        case = app.state.store.get_case(case_id)
        if not case:
            raise HTTPException(404, "case not found")
        try:
            return draft_case_message(case)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/attachments/preview")
    def attachment_preview(path: str = Query(min_length=1)):
        file_path = resolve_attachment_path(path, app.state.gmail_sync)
        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return FileResponse(file_path, media_type=media_type, filename=file_path.name)

    @app.get("/api/attachments/download")
    def attachment_download(path: str = Query(min_length=1)):
        file_path = resolve_attachment_path(path, app.state.gmail_sync)
        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return FileResponse(
            file_path,
            media_type=media_type,
            filename=file_path.name,
            headers={"Content-Disposition": f'attachment; filename="{file_path.name}"'},
        )

    @app.post("/api/cases/mark-overdue")
    def mark_overdue(payload: OverdueRequest):
        return {"blocked_case_ids": app.state.store.mark_overdue(payload.wait_seconds)}

    @app.post("/api/review-tasks/{task_id}/resolve")
    def resolve_task(task_id: int, payload: ResolveTaskRequest):
        try:
            app.state.store.resolve_task(task_id, payload.actor, payload.note)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "resolved", "task_id": task_id}

    worker_app = ROOT.parent / "sdoc-app"
    if worker_app.exists():
        app.mount("/app", StaticFiles(directory=worker_app, html=True), name="worker-app")

    return app


app = create_app()
