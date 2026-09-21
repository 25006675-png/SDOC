"""Small JSON documents the server has to keep across restarts.

Mailbox OAuth tokens, sync state and the spend ledger are files under data/.
On a host whose disk is thrown away on every restart (Render), that meant the
mailbox disconnected and sync lost its place each time the service slept.

With ``SDOC_STATE_BACKEND=supabase`` each document is a row in the private
``sdoc_runtime_state`` table instead, keyed by its file name
(``gmail_token.json``). Anything else keeps the files, so local runs and the
tests never touch the database. Run
``supabase/migrations/20260921_003_sdoc_runtime_state.sql`` first.
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
from pathlib import Path

import httpx
import truststore

TABLE = "sdoc_runtime_state"

_client = None
_client_lock = threading.Lock()


def backend():
    return os.environ.get("SDOC_STATE_BACKEND", "file").strip().lower()


def _supabase():
    global _client
    with _client_lock:
        if _client is None:
            url = os.environ.get("SUPABASE_URL", "").rstrip("/")
            key = os.environ.get("SUPABASE_SECRET_KEY", "")
            if not url or not key:
                raise ValueError("SDOC_STATE_BACKEND=supabase needs SUPABASE_URL and SUPABASE_SECRET_KEY")
            _client = httpx.Client(
                base_url=f"{url}/rest/v1",
                headers={"apikey": key, "Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                timeout=20.0,
                verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
            )
        return _client


def load(path, default):
    """-> the stored document, or ``default`` when there is none yet.

    A database error is raised, not swallowed: returning the default would let
    the next save overwrite real state (a token, the list of seen messages)
    with an empty document.
    """
    if backend() != "supabase":
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default
    response = _supabase().get(
        f"/{TABLE}", params={"key": f"eq.{Path(path).name}", "select": "value"})
    response.raise_for_status()
    rows = response.json()
    return rows[0]["value"] if rows else default


def save(path, data):
    if backend() != "supabase":
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        return
    response = _supabase().post(
        f"/{TABLE}",
        params={"on_conflict": "key"},
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        json={"key": Path(path).name, "value": data,
              "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
    )
    response.raise_for_status()
