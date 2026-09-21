"""Microsoft Outlook / Graph mailbox source and sync orchestration."""
from __future__ import annotations

import base64
import html
import os
import re
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .budget import BudgetExceeded, SpendLedger
from .casework import CaseService
from .classify import GeminiEmailClassifier
from .gmail import _json_load, _json_save, _native_tls, safe_filename
from .verification import GeminiVerifier

GRAPH_URL = "https://graph.microsoft.com/v1.0"
SCOPES = ("offline_access", "User.Read", "Mail.Read")
GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _strip_html(value):
    text = re.sub(r"<\s*br\s*/?>", "\n", value or "", flags=re.I)
    text = re.sub(r"</\s*p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


class OutlookConfig:
    def __init__(self):
        self.client_id = os.environ.get("MICROSOFT_CLIENT_ID", "")
        self.client_secret = os.environ.get("MICROSOFT_CLIENT_SECRET", "")
        self.tenant = os.environ.get("MICROSOFT_TENANT", "common") or "common"
        self.redirect_uri = os.environ.get(
            "MICROSOFT_REDIRECT_URI", "http://localhost:8001/api/mailbox/oauth/callback"
        )
        self.query = os.environ.get("SDOC_OUTLOOK_QUERY", os.environ.get("SDOC_MAILBOX_QUERY", "hasAttachments eq true"))
        self.max_results = max(1, min(50, int(os.environ.get("SDOC_OUTLOOK_MAX_RESULTS", os.environ.get("SDOC_MAILBOX_MAX_RESULTS", "10")))))
        self.token_path = Path(os.environ.get("SDOC_OUTLOOK_TOKEN_PATH", "data/outlook_token.json"))
        self.state_path = Path(os.environ.get("SDOC_OUTLOOK_STATE_PATH", "data/outlook_state.json"))
        self.attachment_root = Path(os.environ.get("SDOC_ATTACHMENT_ROOT", "data"))

    @property
    def client_id_is_guid(self):
        return bool(GUID_RE.fullmatch(self.client_id or ""))

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and self.redirect_uri and self.client_id_is_guid)

    @property
    def authorize_url(self):
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/authorize"

    @property
    def token_url(self):
        return f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"


class OutlookSource:
    """Expose Outlook messages through the source interface used by CaseService."""

    def __init__(self, access_token, query, max_results=10, client=None, attachment_root=None):
        self.query = query
        self.max_results = max_results
        self.attachment_root = Path(attachment_root or os.environ.get("SDOC_ATTACHMENT_ROOT", "data"))
        self.client = client or httpx.Client(
            base_url=GRAPH_URL,
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
        return self._request("GET", "/me", params={"$select": "mail,userPrincipalName"})

    def emails(self):
        params = {
            "$top": self.max_results,
            "$orderby": "receivedDateTime desc",
            "$select": "id,conversationId,subject,from,receivedDateTime,body,bodyPreview,hasAttachments,webLink,parentFolderId",
        }
        if self.query == "hasAttachments eq true":
            # Graph rejects $filter + $orderby on messages as InefficientFilter
            # (HTTP 400) unless the sort property also appears in the filter,
            # and first. An always-true bound on receivedDateTime satisfies it.
            params["$filter"] = ("receivedDateTime ge 1900-01-01T00:00:00Z "
                                 "and hasAttachments eq true")
        listing = self._request("GET", "/me/messages", params=params)
        return [self._message_record(item) for item in listing.get("value", [])]

    def read_bytes(self, att_path):
        if att_path in self._attachments:
            return self._attachments[att_path]
        return (self.attachment_root / att_path).read_bytes()

    def submit(self, submission):
        raise RuntimeError("Outlook source is read-only")

    def _message_record(self, message):
        message_id = message["id"]
        attachments = []
        if message.get("hasAttachments"):
            self._load_attachments(message_id, attachments)
        sender = ((message.get("from") or {}).get("emailAddress") or {})
        body = message.get("body") or {}
        content = body.get("content") or ""
        if (body.get("contentType") or "").lower() == "html":
            content = _strip_html(content)
        return {
            "email_id": f"outlook_{message_id}",
            "outlook_message_id": message_id,
            "outlook_conversation_id": message.get("conversationId"),
            "message_url": message.get("webLink"),
            "thread_id": message.get("conversationId"),
            "label_ids": [message.get("parentFolderId")] if message.get("parentFolderId") else [],
            "from": sender.get("address") or sender.get("name") or "",
            "subject": message.get("subject") or "",
            "received_at": message.get("receivedDateTime"),
            "body": content or message.get("bodyPreview") or "",
            "attachments": attachments,
        }

    def _load_attachments(self, message_id, attachments):
        listing = self._request("GET", f"/me/messages/{message_id}/attachments")
        for item in listing.get("value", []):
            if item.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue
            filename = safe_filename(item.get("name") or "attachment")
            data = item.get("contentBytes")
            if not data:
                continue
            payload = base64.b64decode(data)
            path = f"attachments/outlook/{safe_filename(message_id)}/{filename}"
            self._attachments[path] = payload
            disk_path = self.attachment_root / path
            disk_path.parent.mkdir(parents=True, exist_ok=True)
            disk_path.write_bytes(payload)
            attachments.append(path)


def _fetch_account(source, attempts=3, sleep=time.sleep):
    """-> the signed-in address, or None when Graph keeps failing.

    Graph's /me can answer 504 moments after sign-in. The token is already
    valid by then, so a slow profile lookup must not undo the connection.
    Client errors (4xx) are real problems and still raise.
    """
    for attempt in range(attempts):
        try:
            profile = source.profile()
            return profile.get("mail") or profile.get("userPrincipalName")
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise
            if attempt + 1 < attempts:
                sleep(2 ** attempt)
    return None


class OutlookSyncService:
    def __init__(self, store, cfg=None, client=None, ledger=None):
        self.store = store
        self.cfg = cfg or OutlookConfig()
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
            "provider": "outlook",
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
        if self.cfg.client_id and not self.cfg.client_id_is_guid:
            return "MICROSOFT_CLIENT_ID must be the Azure Application (client) ID GUID, not the client secret value."
        if not self.cfg.configured:
            return "Set MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, MICROSOFT_TENANT, and MICROSOFT_REDIRECT_URI on the API server."
        if not connected:
            return "Connect Outlook to start live inbox analysis."
        return "Ready to sync Outlook."

    def authorization_url(self):
        if self.cfg.client_id and not self.cfg.client_id_is_guid:
            raise ValueError("MICROSOFT_CLIENT_ID must be the Azure Application (client) ID GUID, not the client secret value")
        if not self.cfg.configured:
            raise ValueError("MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, and MICROSOFT_REDIRECT_URI are required")
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
            "response_mode": "query",
            # Always show the account chooser so an admin can pick (or switch) mailboxes.
            "prompt": "select_account",
            "state": state,
        }
        return f"{self.cfg.authorize_url}?{urlencode(params)}"

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
            "scope": " ".join(SCOPES),
        })
        token["created_at"] = time.time()
        if "expires_in" in token:
            token["expires_at"] = token["created_at"] + int(token["expires_in"]) - 60
        existing = _json_load(self.cfg.token_path, {})
        if existing.get("refresh_token") and not token.get("refresh_token"):
            token["refresh_token"] = existing["refresh_token"]
        _json_save(self.cfg.token_path, token)
        with OutlookSource(token["access_token"], self.cfg.query, self.cfg.max_results, attachment_root=self.cfg.attachment_root) as source:
            account = _fetch_account(source)
        data.pop("oauth_state", None)
        data["oauth_states"] = [item for item in data.get("oauth_states", []) if item != state]
        data["account"] = account
        data["last_error"] = None if account else (
            "Connected. Microsoft did not return the account name yet; "
            "it is filled in on the next sync.")
        _json_save(self.cfg.state_path, data)
        return self.status()

    def sync_once(self):
        if not self.cfg.configured:
            raise ValueError(self._next_action(False))
        token = self._access_token()
        state = _json_load(self.cfg.state_path, {})
        seen = set(state.get("seen_message_ids", []))
        processed = 0
        classifier = None
        verifier = None
        budget_stop = None
        try:
            setting = os.environ.get("SDOC_AI_CLASSIFIER", "auto").lower()
            has_keys = bool(os.environ.get("GEMINI_KEYS") or os.environ.get("GEMINI_KEY"))
            if setting not in {"0", "false", "no", "off"} and has_keys:
                classifier = GeminiEmailClassifier()
            verify_setting = os.environ.get("SDOC_VERIFY", "auto").lower()
            if verify_setting not in {"0", "false", "no", "off"} and has_keys:
                verifier = GeminiVerifier()
            case_cfg = {
                "extractor": os.environ.get("SDOC_DOCUMENT_EXTRACTOR", "deterministic"),
                "reader_isolation": os.environ.get("SDOC_READER_ISOLATION", "1").lower() not in {"0", "false", "no", "off"},
                "reader_workers": int(os.environ.get("SDOC_READER_WORKERS", "2")),
                "reader_timeout_seconds": float(os.environ.get("SDOC_READER_TIMEOUT", "8")),
            }
            endpoint = os.environ.get("SDOC_LLM_ENDPOINT")
            if endpoint:
                case_cfg["llm_endpoint"] = endpoint
                case_cfg["llm_key"] = os.environ.get("SDOC_LLM_KEY")
                case_cfg["llm_model"] = os.environ.get("SDOC_LLM_MODEL", "gpt-4o-mini")
            if classifier:
                case_cfg["ai_email_classifier"] = classifier
            if verifier:
                case_cfg["verifier"] = verifier
            with OutlookSource(token, self.cfg.query, self.cfg.max_results, attachment_root=self.cfg.attachment_root) as source:
                if not state.get("account"):
                    state["account"] = _fetch_account(source, attempts=1)
                service = CaseService(self.store, case_cfg)
                for email in source.emails():
                    message_id = email.get("outlook_message_id")
                    if message_id in seen:
                        continue
                    try:
                        self.ledger.check(email.get("from"))
                    except BudgetExceeded as exc:
                        budget_stop = str(exc)
                        break
                    if state.get("account"):
                        email["outlook_account"] = state["account"]
                    service.ingest_email(email, source)
                    self.ledger.record(email.get("from"))
                    seen.add(message_id)
                    processed += 1
        finally:
            if classifier:
                classifier.close()
            if verifier:
                verifier.close()
        state.update({
            "last_sync_at": time.time(),
            "last_error": budget_stop,
            "processed": int(state.get("processed", 0)) + processed,
            "seen_message_ids": sorted(seen),
        })
        _json_save(self.cfg.state_path, state)
        return {**self.status(), "processed_now": processed, "budget_stop": budget_stop}

    def record_error(self, error):
        state = _json_load(self.cfg.state_path, {})
        state["last_error"] = str(error)
        _json_save(self.cfg.state_path, state)

    def fetch_attachment(self, source_path):
        path = self.cfg.attachment_root / str(source_path).replace("\\", "/").lstrip("/")
        if path.is_file():
            return path
        raise FileNotFoundError(source_path)

    def _access_token(self):
        token = _json_load(self.cfg.token_path, {})
        if not token:
            raise ValueError("Outlook is not connected")
        if token.get("access_token") and token.get("expires_at", 0) > time.time():
            return token["access_token"]
        if not token.get("refresh_token"):
            raise ValueError("Outlook refresh token is missing; reconnect Outlook")
        refreshed = self._token_request({
            "client_id": self.cfg.client_id,
            "client_secret": self.cfg.client_secret,
            "refresh_token": token["refresh_token"],
            "grant_type": "refresh_token",
            "scope": " ".join(SCOPES),
        })
        token.update(refreshed)
        token["created_at"] = time.time()
        if "expires_in" in token:
            token["expires_at"] = token["created_at"] + int(token["expires_in"]) - 60
        _json_save(self.cfg.token_path, token)
        return token["access_token"]

    def _token_request(self, data):
        response = self.client.post(self.cfg.token_url, data=data)
        response.raise_for_status()
        return response.json()
