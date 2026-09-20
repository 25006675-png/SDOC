"""Supabase/PostgREST repository implementing the case-store API.

Run ``supabase/migrations/20260920_001_sdoc_casework.sql`` before selecting
this store. The secret key is server-only and must never be shipped to the
landing page or browser code.
"""
from __future__ import annotations

import os
import ssl
import time
from pathlib import Path

import httpx
import truststore

from .casework import document_version, product_state, shipment_reference, stable_case_id
from .analytics import build_metrics


class SupabaseStore:
    def __init__(self, url=None, secret_key=None, client=None):
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.secret_key = secret_key or os.environ.get("SUPABASE_SECRET_KEY", "")
        if not self.url or not self.secret_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY are required")
        headers = {
            "apikey": self.secret_key,
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }
        native_tls = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.client = client or httpx.Client(
            base_url=f"{self.url}/rest/v1", headers=headers, timeout=30.0,
            verify=native_tls,
        )
        self._owns_client = client is None

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
        if not response.content:
            return None
        return response.json()

    def _document_payload(self, email, evidence):
        documents = []
        for path in email.get("attachments") or []:
            if path == evidence.get("si_doc"):
                role = "SI"
            elif path == evidence.get("bl_doc"):
                role = "BL"
            else:
                role = (evidence.get("doc_kinds") or {}).get(path, "UNKNOWN")
                if role == "UNKNOWN":
                    name = Path(path).stem.upper()
                    role = "SI" if "_SI" in name else "BL" if "_BL" in name else "UNKNOWN"
            version_index, version_label = document_version(path)
            documents.append({
                "source_path": path,
                "role": role,
                "version_index": version_index,
                "version_label": version_label,
            })
        return documents

    def ingest_result(self, email, record, evidence, now=None):
        email = {
            **email,
            "classification": evidence.get("classification"),
        }
        reference = shipment_reference(email)
        result = self._request(
            "POST",
            "/rpc/ingest_sdoc_result",
            json={
                "p_email": email,
                "p_record": record,
                "p_evidence": evidence,
                "p_reference": reference,
                "p_case_id": stable_case_id(reference),
                "p_state": product_state(record),
                "p_documents": self._document_payload(email, evidence),
                "p_now": now or time.time(),
            },
        )
        return self.get_case(result) if result else None

    def list_cases(self, state=None):
        params = {"select": "*", "order": "updated_at.desc,case_id.asc"}
        if state:
            params["state"] = f"eq.{state}"
        return self._request("GET", "/shipment_cases", params=params) or []

    def list_routed_messages(self, category=None):
        params = {
            "select": "email_id,sender,subject,category,payload_json,created_at",
            "order": "created_at.asc,email_id.asc",
        }
        if category:
            params["category"] = f"eq.{category}"
        return self._request("GET", "/routed_messages", params=params) or []

    def get_case(self, case_id):
        cases = self._request(
            "GET", "/shipment_cases", params={"case_id": f"eq.{case_id}", "select": "*"}
        ) or []
        if not cases:
            return None
        case = cases[0]
        common = {"case_id": f"eq.{case_id}"}
        case["emails"] = self._request(
            "GET", "/case_emails", params={**common, "select": "*", "order": "created_at.asc,email_id.asc"}
        ) or []
        case["documents"] = self._request(
            "GET",
            "/documents",
            params={**common, "select": "role,document_versions(*)", "order": "role.asc"},
        ) or []
        case["review_tasks"] = self._request(
            "GET", "/review_tasks", params={**common, "select": "*", "order": "task_id.asc"}
        ) or []
        case["comparisons"] = self._request(
            "GET", "/comparisons", params={**common, "select": "*", "order": "comparison_id.asc"}
        ) or []
        case["audit_events"] = self._request(
            "GET", "/audit_events", params={**common, "select": "*", "order": "event_id.asc"}
        ) or []
        return case

    def mark_overdue(self, wait_seconds, now=None):
        return self._request(
            "POST",
            "/rpc/mark_sdoc_cases_overdue",
            json={"p_wait_seconds": wait_seconds, "p_now": now or time.time()},
        ) or []

    def resolve_task(self, task_id, actor, note=None, now=None):
        return self._request(
            "POST",
            "/rpc/resolve_sdoc_review_task",
            json={
                "p_task_id": task_id,
                "p_actor": actor,
                "p_note": note,
                "p_now": now or time.time(),
            },
        )

    def metrics(self):
        cases = self.list_cases()
        routed = self.list_routed_messages()
        tasks = self._request("GET", "/review_tasks", params={"select": "*"}) or []
        comparisons = self._request("GET", "/comparisons", params={"select": "*"}) or []
        emails = self._request("GET", "/case_emails", params={"select": "email_id"}) or []
        return build_metrics(cases, routed, tasks, comparisons, len(emails), time.time())
