"""Gmail mailbox source and sync orchestration."""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import ssl
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import truststore

from .casework import CaseService
from .budget import BudgetExceeded, SpendLedger
from .classify import GeminiEmailClassifier


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_URL = "https://gmail.googleapis.com/gmail/v1"
SCOPES = ("https://www.googleapis.com/auth/gmail.readonly",)
DECORATIVE_ATTACHMENT_NAMES = {
    "icon.png", "logo.png", "facebook.png", "twitter.png", "linkedin.png",
    "instagram.png", "youtube.png",
}


def _native_tls():
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _json_load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _json_save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _b64decode(data):
    if not data:
        return b""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _part_headers(part):
    return {
        item.get("name", "").lower(): item.get("value", "").lower()
        for item in part.get("headers") or []
    }


def _skip_attachment(filename, mime, headers, payload):
    name = filename.lower()
    if name in DECORATIVE_ATTACHMENT_NAMES:
        return True
    if mime.startswith("image/"):
        disposition = headers.get("content-disposition", "")
        return "inline" in disposition or len(payload) < 12 * 1024
    return False


def safe_filename(name):
    """Attachment filenames come from untrusted MIME headers.

    Keep the basename only: a crafted name like '../../x.py' must never escape
    the attachment root. The serve path in api.py is already defended; this is
    the matching guard for the write path.
    """
    base = re.split(r"[\\/]", str(name or ""))[-1].replace("\x00", "")
    if base in ("", ".", ".."):
        return "attachment"
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base).lstrip(".")
    return base[:128] or "attachment"


class GmailConfig:
    def __init__(self):
        self.client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
        self.client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
        self.redirect_uri = os.environ.get(
            "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8001/api/mailbox/oauth/callback"
        )
        self.query = os.environ.get(
            "SDOC_GMAIL_QUERY", "has:attachment newer_than:30d"
        )
        self.max_results = max(1, min(50, int(os.environ.get("SDOC_GMAIL_MAX_RESULTS", "10"))))
        self.token_path = Path(os.environ.get("SDOC_GMAIL_TOKEN_PATH", "data/gmail_token.json"))
        self.state_path = Path(os.environ.get("SDOC_GMAIL_STATE_PATH", "data/gmail_state.json"))
        self.attachment_root = Path(os.environ.get("SDOC_ATTACHMENT_ROOT", "data"))

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and self.redirect_uri)


class GmailSource:
    """Expose Gmail messages through the source interface used by CaseService."""

    def __init__(self, access_token, query, max_results=10, client=None, attachment_root=None):
        self.query = query
        self.max_results = max_results
        self.attachment_root = Path(attachment_root or os.environ.get("SDOC_ATTACHMENT_ROOT", "data"))
        self.client = client or httpx.Client(
            base_url=GMAIL_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30.0,
            verify=_native_tls(),
        )
        self._owns_client = client is None
        self._attachments = {}

    def close(self):
        if self._owns_client:
            self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

    def profile(self):
        return self._request("GET", "/users/me/profile")

    def emails(self):
        listing = self._request(
            "GET",
            "/users/me/messages",
            params={"q": self.query, "maxResults": self.max_results},
        )
        records = []
        for item in listing.get("messages", []):
            records.append(self._message_record(item["id"]))
        return records

    def read_bytes(self, att_path):
        if att_path in self._attachments:
            return self._attachments[att_path]
        return (self.attachment_root / att_path).read_bytes()

    def submit(self, submission):
        raise RuntimeError("Gmail source is read-only")

    def _message_record(self, message_id):
        message = self._request(
            "GET",
            f"/users/me/messages/{message_id}",
            params={"format": "full"},
        )
        headers = {
            item.get("name", "").lower(): item.get("value", "")
            for item in message.get("payload", {}).get("headers", [])
        }
        body = []
        attachments = []
        self._walk_parts(message_id, message.get("payload", {}), body, attachments)
        return {
            "email_id": f"gmail_{message_id}",
            "gmail_message_id": message_id,
            "gmail_thread_id": message.get("threadId"),
            "message_url": f"https://mail.google.com/mail/u/0/#all/{message.get('threadId') or message_id}",
            "thread_id": message.get("threadId"),
            "label_ids": message.get("labelIds") or [],
            "from": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "received_at": headers.get("date"),
            "body": "\n".join(part for part in body if part).strip() or message.get("snippet", ""),
            "attachments": attachments,
        }

    def _walk_parts(self, message_id, part, body, attachments):
        filename = part.get("filename") or ""
        body_data = part.get("body") or {}
        mime = part.get("mimeType", "")
        if filename:
            data = body_data.get("data")
            if not data and body_data.get("attachmentId"):
                attachment = self._request(
                    "GET",
                    f"/users/me/messages/{message_id}/attachments/{body_data['attachmentId']}",
                )
                data = attachment.get("data")
            payload = _b64decode(data)
            if _skip_attachment(filename, mime, _part_headers(part), payload):
                return
            path = f"attachments/gmail/{message_id}/{safe_filename(filename)}"
            self._attachments[path] = payload
            disk_path = self.attachment_root / path
            disk_path.parent.mkdir(parents=True, exist_ok=True)
            disk_path.write_bytes(payload)
            attachments.append(path)
        elif mime == "text/plain" and body_data.get("data"):
            body.append(_b64decode(body_data["data"]).decode("utf-8", "replace"))
        for child in part.get("parts") or []:
            self._walk_parts(message_id, child, body, attachments)


class GmailSyncService:
    def __init__(self, store, cfg=None, client=None, ledger=None):
        self.store = store
        self.cfg = cfg or GmailConfig()
        self.ledger = ledger or SpendLedger()
        self.client = client or httpx.Client(timeout=30.0, verify=_native_tls())
        self._owns_client = client is None

    def close(self):
        if self._owns_client:
            self.client.close()

    def status(self):
        token = _json_load(self.cfg.token_path, {})
        state = _json_load(self.cfg.state_path, {})
        connected = bool(token.get("refresh_token") or token.get("access_token"))
        return {
            "provider": "gmail",
            "configured": self.cfg.configured,
            "connected": connected,
            "account": state.get("account"),
            "query": self.cfg.query,
            "last_sync_at": state.get("last_sync_at"),
            "last_error": state.get("last_error"),
            "processed": state.get("processed", 0),
            "seen_messages": len(state.get("seen_message_ids", [])),
            "next_action": self._next_action(connected),
        }

    def _next_action(self, connected):
        if not self.cfg.configured:
            return "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET on the API server."
        if not connected:
            return "Connect Gmail to start live inbox analysis."
        return "Ready to sync Gmail."

    def authorization_url(self):
        if not self.cfg.configured:
            raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")
        state = secrets.token_urlsafe(24)
        data = _json_load(self.cfg.state_path, {})
        pending = list(data.get("oauth_states") or [])
        pending.append(state)
        data["oauth_states"] = pending[-5:]
        data["oauth_state"] = state
        _json_save(self.cfg.state_path, data)
        params = {
            "client_id": self.cfg.client_id,
            "redirect_uri": self.cfg.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def finish_oauth(self, code, state):
        data = _json_load(self.cfg.state_path, {})
        pending = set(data.get("oauth_states") or [])
        if data.get("oauth_state"):
            pending.add(data["oauth_state"])
        if not state or state not in pending:
            raise ValueError("OAuth state did not match")
        token = self._token_request({
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.cfg.redirect_uri,
        })
        token["created_at"] = time.time()
        if "expires_in" in token:
            token["expires_at"] = token["created_at"] + int(token["expires_in"]) - 60
        existing = _json_load(self.cfg.token_path, {})
        if existing.get("refresh_token") and not token.get("refresh_token"):
            token["refresh_token"] = existing["refresh_token"]
        _json_save(self.cfg.token_path, token)
        access_token = token["access_token"]
        with GmailSource(access_token, self.cfg.query, self.cfg.max_results, attachment_root=self.cfg.attachment_root) as source:
            profile = source.profile()
        data.pop("oauth_state", None)
        data["oauth_states"] = [item for item in data.get("oauth_states", []) if item != state]
        data["account"] = profile.get("emailAddress")
        data["last_error"] = None
        _json_save(self.cfg.state_path, data)
        return self.status()

    def sync_once(self):
        if not self.cfg.configured:
            raise ValueError("Gmail OAuth is not configured")
        token = self._access_token()
        state = _json_load(self.cfg.state_path, {})
        seen = set(state.get("seen_message_ids", []))
        processed = 0
        classifier = None
        ledger = self.ledger
        budget_stop = None
        try:
            setting = os.environ.get("SDOC_AI_CLASSIFIER", "auto").lower()
            has_keys = bool(os.environ.get("GEMINI_KEYS") or os.environ.get("GEMINI_KEY"))
            if setting not in {"0", "false", "no", "off"} and has_keys:
                classifier = GeminiEmailClassifier()
            with GmailSource(token, self.cfg.query, self.cfg.max_results, attachment_root=self.cfg.attachment_root) as source:
                service = CaseService(
                    self.store,
                    {"ai_email_classifier": classifier} if classifier else None,
                )
                for email in source.emails():
                    message_id = email.get("gmail_message_id")
                    if message_id in seen:
                        continue
                    # Spend ceiling before any model call (Addendum A3): a
                    # sender controls how much arrives, not how much we spend.
                    try:
                        ledger.check(email.get("from"))
                    except BudgetExceeded as exc:
                        budget_stop = str(exc)
                        break
                    if state.get("account"):
                        email["gmail_account"] = state["account"]
                        thread_id = email.get("gmail_thread_id") or email.get("thread_id") or message_id
                        email["message_url"] = (
                            "https://mail.google.com/mail/"
                            f"?authuser={state['account']}#all/{thread_id}"
                        )
                    service.ingest_email(email, source)
                    ledger.record(email.get("from"))
                    seen.add(message_id)
                    processed += 1
        finally:
            if classifier:
                classifier.close()
        state.update({
            "last_sync_at": time.time(),
            "last_error": budget_stop,
            "processed": int(state.get("processed", 0)) + processed,
            "seen_message_ids": sorted(seen),
        })
        _json_save(self.cfg.state_path, state)
        return {**self.status(), "processed_now": processed,
                "budget_stop": budget_stop}

    def record_error(self, error):
        state = _json_load(self.cfg.state_path, {})
        state["last_error"] = str(error)
        _json_save(self.cfg.state_path, state)

    def fetch_attachment(self, source_path):
        match = re.fullmatch(r"attachments/gmail/([^/]+)/(.+)", str(source_path).replace("\\", "/"))
        if not match:
            raise FileNotFoundError(source_path)
        message_id, filename = match.groups()
        token = self._access_token()
        with GmailSource(token, self.cfg.query, self.cfg.max_results, attachment_root=self.cfg.attachment_root) as source:
            message = source._request(
                "GET",
                f"/users/me/messages/{message_id}",
                params={"format": "full"},
            )
            payload = self._attachment_payload(source, message_id, message.get("payload", {}), filename)
        if payload is None:
            raise FileNotFoundError(source_path)
        disk_path = self.cfg.attachment_root / source_path
        disk_path.parent.mkdir(parents=True, exist_ok=True)
        disk_path.write_bytes(payload)
        return disk_path

    def _attachment_payload(self, source, message_id, part, filename):
        if safe_filename(part.get("filename") or "") == filename:
            body = part.get("body") or {}
            data = body.get("data")
            if not data and body.get("attachmentId"):
                attachment = source._request(
                    "GET",
                    f"/users/me/messages/{message_id}/attachments/{body['attachmentId']}",
                )
                data = attachment.get("data")
            return _b64decode(data)
        for child in part.get("parts") or []:
            payload = self._attachment_payload(source, message_id, child, filename)
            if payload is not None:
                return payload
        return None

    def _access_token(self):
        token = _json_load(self.cfg.token_path, {})
        if not token:
            raise ValueError("Gmail is not connected")
        if token.get("access_token") and token.get("expires_at", 0) > time.time():
            return token["access_token"]
        if not token.get("refresh_token"):
            raise ValueError("Gmail refresh token is missing; reconnect Gmail")
        refreshed = self._token_request({
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
        })
        token.update(refreshed)
        token["created_at"] = time.time()
        if "expires_in" in token:
            token["expires_at"] = token["created_at"] + int(token["expires_in"]) - 60
        _json_save(self.cfg.token_path, token)
        return token["access_token"]

    def _token_request(self, data):
        response = self.client.post(TOKEN_URL, data=data)
        response.raise_for_status()
        return response.json()
