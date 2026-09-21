"""FastAPI backend for worker and admin clients."""
from __future__ import annotations

import asyncio
from functools import lru_cache
import base64
import hashlib
import hmac
import html
import io
import mimetypes
import os
import time
from urllib.parse import parse_qs, quote
import httpx
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import auth
from .pdfium_guard import PDFIUM_LOCK
from .casework import CASE_STATES, CaseStore
from .drafting import draft_case_message
from .mailbox import (
    PROVIDERS,
    create_mailbox_registry,
    create_mailbox_sync,
    mailbox_provider,
    normalise_provider,
    provider_for_attachment,
)
from .supabase_store import SupabaseStore


ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT.parent / ".env")



AUTH_COOKIE = auth.SESSION_COOKIE


def auth_enabled():
    """On unless explicitly disabled; the test suite disables it."""
    return os.environ.get("SDOC_AUTH", "on").strip().lower() not in {
        "0", "off", "false", "no"}


def user_store(request: Request):
    """Accounts belong to the app instance, not the module."""
    store = getattr(request.app.state, "users", None)
    if store is None:
        store = auth.UserStore()
        request.app.state.users = store
    return store


def make_session(username, role):
    return auth.issue_session(username, role)


def read_identity(request: Request):
    """-> {'username', 'role', 'display_name'} for a signed-in caller."""
    if not auth_enabled():
        return {"username": "demo", "role": "admin",
                "display_name": "Authentication disabled"}
    session = auth.read_session(request.cookies.get(AUTH_COOKIE))
    if not session:
        return None
    account = user_store(request).get(session["username"]) or {}
    return {**session,
            "display_name": account.get("display_name", session["username"])}


def read_role(request: Request):
    identity = read_identity(request)
    return identity["role"] if identity else None


def login_page(error="", next_path=""):
    # Empty means "send me to my own home": the sign-in handler then picks the
    # page for the role. Anything else must stay inside the app.
    if next_path and not next_path.startswith("/app"):
        next_path = ""
    message = f'<p class="error" id="login-error" role="alert">{html.escape(error)}</p>' if error else ""
    safe_next = html.escape(next_path, quote=True)
    return f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Sign in - SDOC</title>
      <link rel="icon" type="image/svg+xml" href="/assets/favicon.svg">
      <style>
        body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: "Segoe UI", Arial, sans-serif; background: #f6f6f4; color: #1c1c1c; }}
        main {{ width: min(1000px, calc(100vw - 40px)); box-sizing: border-box; display: grid; grid-template-columns: 1.1fr 1fr; border: 1px solid #e6e6e2; border-radius: 12px; overflow: hidden; background: #fff; }}
        .brand {{ display: inline-flex; align-items: center; gap: 10px; margin-bottom: 22px; color: #1c1c1c; font-weight: 800; font-size: 18px; text-decoration: none; }}
        .brand img {{ width: 28px; height: 28px; }}
        h1 {{ margin: 0 0 8px; font-size: 24px; font-style: italic; font-weight: 800; }} p {{ color: #666663; line-height: 1.6; }}
        label, input, button {{ display: block; width: 100%; box-sizing: border-box; }}
        label {{ margin-top: 20px; color: #1c1c1c; font-weight: 700; font-size: 13px; }}
        input {{ margin-top: 8px; min-height: 44px; border: 1px solid #cfcfca; border-radius: 6px; padding: 0 12px; background: #fff; color: #1c1c1c; font: inherit; }}
        input:focus {{ outline: 2px solid #d8741a; outline-offset: 1px; border-color: #d8741a; }}
        button {{ margin-top: 22px; min-height: 46px; border: 0; border-radius: 6px; background: #a9540d; color: #fff; font: inherit; font-weight: 700; font-size: 16px; cursor: pointer; }}
        button:hover {{ background: #8e4509; }}
        .error {{ color: #a2362e; background: #fbe8e6; padding: 10px 12px; border-radius: 6px; }} a {{ color: #9a4f0a; }}
        * {{ box-sizing: border-box; }}
        [hidden] {{ display: none !important; }}
        body {{ padding: 32px 0; }}
        .login-story {{ padding: 48px; background: #fdf0e3; display: flex; flex-direction: column; justify-content: space-between; }}
        .login-story h2 {{ margin: 26px 0 16px; font-size: 40px; font-weight: 800; font-style: italic; letter-spacing: -.03em; line-height: 1.12; text-wrap: balance; }}
        .login-story p {{ color: #694624; max-width: 34ch; font-size: 15px; }}
        .login-proof {{ margin-top: 36px; background: white; border-radius: 8px; padding: 20px; }}
        .login-proof p {{ font-size: 12px; margin: 0 0 14px; color: #666663; }}
        .proof-row {{ display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; font-size: 13px; border-top: 1px solid #e6e6e2; }}
        .proof-row strong {{ color: #26734a; }}
        .proof-row:last-child strong {{ color: #9a4f0a; }}
        .login-form {{ padding: 56px 44px 40px; align-self: center; }}
        .login-form h1 {{ font-size: 28px; font-style: normal; letter-spacing: -.02em; }}
        .login-form > p {{ font-size: 14px; }}
        .login-form .form-intro {{ margin-bottom: 28px; }}
        .password-field {{ position: relative; }}
        .password-field input {{ padding-right: 68px; }}
        .password-toggle {{ position: absolute; top: 0; right: 4px; width: 58px; margin: 0; min-height: 44px; background: transparent; color: #694624; font-size: 12px; }}
        .password-toggle:hover {{ background: #fdf0e3; }}
        button:disabled {{ opacity: .65; cursor: wait; }}
        :focus-visible {{ outline: 2px solid #9a4f0a; outline-offset: 3px; }}
        .login-form .login-help {{ margin-top: 20px; font-size: 12px; }}
        .login-form .login-back {{ margin-top: 32px; font-size: 13px; }}
        .error {{ font-size: 13px; }}
        @media (max-width: 720px) {{ main {{ max-width: 440px; grid-template-columns: 1fr; }} .login-story {{ padding: 24px 28px; }} .login-story .brand {{ margin: 0; }} .login-story h2, .login-story > p, .login-proof {{ display: none; }} .login-form {{ padding: 32px 28px; }} }}
      </style>
    </head>
    <body><main>
    <section class="login-story" aria-label="About SDOC">
      <a class="brand" href="/"><img src="/assets/favicon.svg" alt="">SDOC</a>
      <h2>Every shipment.<br>Accounted for.</h2>
      <p>Compare shipping documents, trace every value and give your team a clear next step.</p>
      <div class="login-proof" aria-label="Illustrative document check"><p>SI / Draft BL: example comparison</p><div class="proof-row"><span>Shipper</span><strong>Matches</strong></div><div class="proof-row"><span>Port of loading</span><strong>Matches</strong></div><div class="proof-row"><span>Gross weight</span><strong>Needs review</strong></div></div>
    </section>
    <section class="login-form" aria-labelledby="login-title">
      <h1 id="login-title">Welcome back</h1>
      <p class="form-intro">Sign in to your SDOC workspace.</p>
      {message}
      <form id="login-form" method="post" action="/login">
        <label>Username<input name="username" type="text" autocomplete="username" autofocus required></label>
        <label for="login-password">Password</label><div class="password-field"><input id="login-password" name="password" type="password" autocomplete="current-password" required><button class="password-toggle" id="password-toggle" type="button" aria-label="Show password" aria-controls="login-password" aria-pressed="false" hidden>Show</button></div>
        <input name="next" type="hidden" value="{safe_next}">
        <button id="sign-in" type="submit">Sign in</button>
      </form>
      <p class="login-help">Need access? Contact your workspace administrator.</p>
      <p class="login-back"><a href="/">&larr; Back to the SDOC overview</a></p>
    </section></main>
    <script>
      const form = document.getElementById('login-form');
      const toggle = document.getElementById('password-toggle');
      const password = document.getElementById('login-password');
      const submit = document.getElementById('sign-in');
      toggle.hidden = false;
      toggle.addEventListener('click', () => {{
        const visible = password.type === 'password';
        password.type = visible ? 'text' : 'password';
        toggle.textContent = visible ? 'Hide' : 'Show';
        toggle.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
        toggle.setAttribute('aria-pressed', String(visible));
      }});
      form.addEventListener('submit', () => {{ submit.disabled = true; submit.textContent = 'Signing in...'; form.setAttribute('aria-busy', 'true'); }});
      window.addEventListener('pageshow', () => {{ submit.disabled = false; submit.textContent = 'Sign in'; form.removeAttribute('aria-busy'); }});
    </script></body></html>
    """


def wants_html(path):
    return path.startswith("/app") or path.startswith("/login")


def is_public_path(path):
    return (
        path in {"/", "/index.html", "/styles.css", "/app.js", "/health", "/login", "/api/auth/status"}
        or path.startswith("/api/mailbox/oauth/callback")
        or path.startswith("/favicon")
        or path.startswith("/assets/")
    )


def required_role(path):
    if (path.startswith("/app/admin")
            or path in {"/api/metrics", "/api/mailbox/connect", "/api/mailboxes"}
            or (path.startswith("/api/mailbox/") and path.endswith("/connect"))):
        return "admin"
    if path.startswith("/api/") or path.startswith("/app"):
        return "worker"
    return None


def authorised(role, required):
    if required is None:
        return True
    if role == "admin":
        return True
    return role == required


class ResolveTaskRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


class OverdueRequest(BaseModel):
    wait_seconds: int = Field(default=86400, ge=1, le=60 * 60 * 24 * 90)


class CorrectFieldRequest(BaseModel):
    field: str = Field(min_length=1, max_length=100)
    side: Literal["si", "bl"]
    value: str = Field(max_length=1000)
    actor: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


def create_store():
    backend = os.environ.get("SDOC_STORE", "sqlite").lower()
    if backend == "supabase":
        return SupabaseStore()
    db_path = os.environ.get("SDOC_DB_PATH", str(ROOT / "data" / "sdoc.db"))
    return CaseStore(db_path)


MAX_PAGE = 2000


def render_pdf_page(file_path, page, scale):
    """Render one page of a PDF to PNG bytes.

    -> (png_bytes, page_width_pt, page_height_pt); the point size lets a
    viewer map stored bounding boxes onto the image without guessing.
    Raises ValueError for a non-PDF and IndexError for a page out of range.

    Cached by path, modification time, page and scale: the evidence pane asks
    for the same page on every case open, and a changed file re-renders.
    """
    if file_path.suffix.lower() != ".pdf":
        raise ValueError("page rendering is only available for PDF documents")
    stat = file_path.stat()
    return _render_pdf_page(str(file_path), stat.st_mtime_ns, page, float(scale))


@lru_cache(maxsize=64)
def _render_pdf_page(path, mtime_ns, page, scale):
    import pypdfium2 as pdfium

    # pdfium is not thread-safe; see pdfium_guard.
    with PDFIUM_LOCK:
        try:
            pdf = pdfium.PdfDocument(path)
        except Exception as exc:
            raise ValueError("document could not be opened") from exc
        try:
            if page > len(pdf):
                raise IndexError(page)
            sheet = pdf[page - 1]
            width, height = sheet.get_width(), sheet.get_height()
            image = sheet.render(scale=scale).to_pil()
        finally:
            pdf.close()
    # PNG encoding is pure Python and does not need the lock.
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), round(width, 2), round(height, 2)


def attachment_root():
    return Path(os.environ.get("SDOC_ATTACHMENT_ROOT", str(ROOT / "data"))).resolve()


def resolve_attachment_path(source_path: str, mailbox_sync=None):
    source_path = (source_path or "").replace("\\", "/").lstrip("/")
    if not source_path.startswith("attachments/") or ".." in Path(source_path).parts:
        raise HTTPException(404, "attachment not found")
    root = attachment_root()
    candidate = (root / source_path).resolve()
    if root not in candidate.parents and candidate != root:
        raise HTTPException(404, "attachment not found")
    if not candidate.is_file():
        owner = provider_for_attachment(source_path)
        service = mailbox_sync
        if isinstance(mailbox_sync, dict):
            service = mailbox_sync.get(owner)
        if owner and service:
            try:
                candidate = Path(service.fetch_attachment(source_path)).resolve()
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
        app.state.mailboxes = create_mailbox_registry(app.state.store)
        app.state.default_provider = mailbox_provider()
        # Kept for the single-mailbox routes and attachment lookups.
        app.state.mailbox_sync = app.state.mailboxes[app.state.default_provider]
        task = None
        mailbox_task = None
        if start_scheduler:
            interval = max(10, int(os.environ.get("SDOC_TIMER_INTERVAL", "60")))
            wait_seconds = max(1, int(os.environ.get("SDOC_WAIT_SECONDS", "86400")))
            mailbox_interval = int(os.environ.get("SDOC_MAILBOX_SYNC_INTERVAL", os.environ.get("SDOC_GMAIL_SYNC_INTERVAL", "60")))

            async def overdue_loop():
                while True:
                    await asyncio.sleep(interval)
                    await asyncio.to_thread(app.state.store.mark_overdue, wait_seconds)

            task = asyncio.create_task(overdue_loop())

            async def mailbox_loop():
                while True:
                    await asyncio.sleep(max(30, mailbox_interval))
                    for service in app.state.mailboxes.values():
                        status = service.status()
                        if not status["configured"] or not status["connected"]:
                            continue
                        try:
                            await asyncio.to_thread(service.sync_once)
                        except Exception as exc:
                            service.record_error(exc)

            if mailbox_interval > 0:
                mailbox_task = asyncio.create_task(mailbox_loop())
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if mailbox_task:
                mailbox_task.cancel()
                with suppress(asyncio.CancelledError):
                    await mailbox_task
            for service in app.state.mailboxes.values():
                service.close()
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


    app.state.users = auth.UserStore()

    @app.middleware("http")
    async def account_auth(request: Request, call_next):
        path = request.url.path
        if is_public_path(path):
            return await call_next(request)
        need = required_role(path)
        role = read_role(request)
        if authorised(role, need):
            return await call_next(request)
        if wants_html(path):
            return RedirectResponse(f"/login?next={quote(path)}", status_code=303)
        return JSONResponse(
            {"detail": "authentication required"},
            status_code=401 if role is None else 403,
        )

    @app.get("/login", response_class=HTMLResponse)
    def login(request: Request):
        if not auth_enabled():
            return RedirectResponse("/app/", status_code=303)
        return HTMLResponse(login_page(next_path=request.query_params.get("next", "")))

    @app.post("/login")
    async def login_submit(request: Request):
        body = (await request.body()).decode("utf-8", "replace")
        form = {key: values[-1] for key, values in parse_qs(body).items()}
        account = user_store(request).authenticate(
            str(form.get("username", "")), str(form.get("password", "")))
        if not account:
            return HTMLResponse(
                login_page("That username and password were not recognized.",
                           str(form.get("next") or "/app/")),
                status_code=401)
        role = account["role"]
        target = str(form.get("next") or ("/app/admin.html" if role == "admin" else "/app/"))
        if not target.startswith("/app") or target == "/app":
            target = "/app/"
        if role == "worker" and target.startswith("/app/admin"):
            target = "/app/"
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(AUTH_COOKIE, make_session(account["username"], role), httponly=True, samesite="lax", secure=os.environ.get("SDOC_COOKIE_SECURE", "0") == "1")
        return response

    @app.post("/logout")
    def logout():
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(AUTH_COOKIE)
        return response

    @app.get("/api/auth/status")
    def auth_status(request: Request):
        identity = read_identity(request)
        return {"auth_enabled": auth_enabled(), "role": (identity or {}).get("role"),
                "username": (identity or {}).get("username"),
                "display_name": (identity or {}).get("display_name")}

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
        return app.state.mailbox_sync.status()

    @app.get("/api/mailbox/connect")
    def mailbox_connect():
        try:
            return RedirectResponse(app.state.mailbox_sync.authorization_url(), status_code=302)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/mailbox/oauth/callback", response_class=HTMLResponse)
    def mailbox_oauth_callback(request: Request, code: str | None = None, state: str | None = None):
        if request.query_params.get("error"):
            raise HTTPException(400, request.query_params["error"])
        if not code:
            raise HTTPException(400, "missing OAuth code")
        try:
            finished = False
            errors = []
            for service in app.state.mailboxes.values():
                try:
                    service.finish_oauth(code, state)
                    finished = True
                    break
                except ValueError as exc:
                    # Not this provider's pending state; try the next one.
                    errors.append(exc)
            if not finished:
                raise errors[0] if errors else ValueError("OAuth state did not match")
        except ValueError as exc:
            app.state.mailbox_sync.record_error(exc)
            return HTMLResponse(f"""
            <!doctype html>
            <html lang="en">
            <head><meta charset="utf-8"><title>Mailbox connection issue</title></head>
            <body>
              <h1>Mailbox was not connected</h1>
              <p>{str(exc)}</p>
              <p>Return to <a href="/app/admin.html">SDOC Admin</a> and click Connect mailbox again.</p>
            </body>
            </html>
            """, status_code=400)
        except httpx.HTTPError as exc:
            app.state.mailbox_sync.record_error(exc)
            raise HTTPException(502, f"Mailbox OAuth exchange failed: {exc}") from exc
        return """
        <!doctype html>
        <html lang="en">
        <head><meta charset="utf-8"><title>Mailbox connected</title></head>
        <body>
          <script>location.replace('/app/admin.html?mailbox=connected')</script>
          <p>Mailbox connected. Return to <a href="/app/admin.html">SDOC Admin</a>.</p>
        </body>
        </html>
        """

    def mailbox_service(request: Request, provider: str):
        key = normalise_provider(provider)
        registry = getattr(request.app.state, "mailboxes", {})
        if key is None or key not in registry:
            raise HTTPException(404, f"unknown mailbox provider: {provider}")
        return key, registry[key]

    @app.get("/api/mailboxes")
    def list_mailboxes(request: Request):
        """Every supported provider with its own connection status."""
        registry = getattr(request.app.state, "mailboxes", {})
        items = []
        for key, service in registry.items():
            try:
                status = service.status()
            except Exception as exc:
                status = {"provider": key, "configured": False, "connected": False,
                          "last_error": str(exc), "next_action": "Provider unavailable."}
            items.append({**status, "provider": key,
                          "label": PROVIDERS[key]["label"],
                          "is_default": key == getattr(request.app.state,
                                                       "default_provider", None)})
        return {"items": items,
                "default": getattr(request.app.state, "default_provider", None)}

    @app.get("/api/mailbox/{provider}/connect")
    def mailbox_connect_provider(request: Request, provider: str):
        _, service = mailbox_service(request, provider)
        try:
            return RedirectResponse(service.authorization_url(), status_code=302)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/mailbox/{provider}/sync")
    def mailbox_sync_provider(request: Request, provider: str):
        _, service = mailbox_service(request, provider)
        try:
            return service.sync_once()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except Exception as exc:
            service.record_error(exc)
            raise HTTPException(502, f"Mailbox sync failed: {exc}") from exc

    @app.post("/api/mailbox/sync")
    def mailbox_sync():
        try:
            return app.state.mailbox_sync.sync_once()
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        except httpx.HTTPError as exc:
            app.state.mailbox_sync.record_error(exc)
            raise HTTPException(502, f"Mailbox sync failed: {exc}") from exc

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
        file_path = resolve_attachment_path(path, app.state.mailboxes)
        media_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        # Inline: a browser treats the default 'attachment' as a download, so an
        # iframe or preview tab would save the file instead of showing it.
        return FileResponse(
            file_path,
            media_type=media_type,
            filename=file_path.name,
            content_disposition_type="inline",
        )

    @app.get("/api/attachments/page")
    def attachment_page(path: str = Query(min_length=1),
                        page: int = Query(1, ge=1, le=MAX_PAGE),
                        scale: float = Query(2.0, ge=0.5, le=4.0)):
        """One PDF page as a PNG, with the page's own point size in the headers.

        The evidence viewer overlays extraction bounding boxes on this image.
        A browser's built-in PDF viewer adds a toolbar, margins and its own
        zoom, so a box placed over it lands in the wrong place; a bare page
        raster makes the mapping from PDF points exact.
        """
        file_path = resolve_attachment_path(path, app.state.mailboxes)
        try:
            png, width, height = render_pdf_page(file_path, page, scale)
        except IndexError:
            raise HTTPException(404, "page not found")
        except ValueError as exc:
            raise HTTPException(415, str(exc)) from exc
        return Response(
            content=png,
            media_type="image/png",
            headers={
                "X-Page-Width": str(width),
                "X-Page-Height": str(height),
                "Cache-Control": "private, max-age=300",
            },
        )

    @app.get("/api/attachments/download")
    def attachment_download(path: str = Query(min_length=1)):
        file_path = resolve_attachment_path(path, app.state.mailboxes)
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

    @app.post("/api/cases/{case_id}/correct")
    def correct_field(case_id: str, payload: CorrectFieldRequest):
        try:
            case = app.state.store.correct_field(
                case_id, payload.field, payload.side, payload.value,
                payload.actor, payload.note,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if case is None:
            raise HTTPException(404, "case not found")
        return case

    @app.post("/api/review-tasks/{task_id}/resolve")
    def resolve_task(task_id: int, payload: ResolveTaskRequest):
        try:
            app.state.store.resolve_task(task_id, payload.actor, payload.note)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"status": "resolved", "task_id": task_id}

    @app.get("/app")
    def app_root_slash():
        """Without this, /app 404s instead of reaching the mounted app."""
        return RedirectResponse("/app/", status_code=308)

    worker_app = ROOT.parent / "sdoc-app"
    if worker_app.exists():
        app.mount("/app", StaticFiles(directory=worker_app, html=True), name="worker-app")
    landing_app = ROOT.parent / "sdoc-landing"
    if landing_app.exists():
        app.mount("/", StaticFiles(directory=landing_app, html=True), name="landing-app")

    return app


app = create_app()
