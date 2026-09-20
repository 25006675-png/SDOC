"""Persistent shipment-case workflow built around the evaluator pipeline.

The original :mod:`sdoc.core` module intentionally remains stateless and keeps
the organizer's submission contract.  This module adds the product concerns
around it: stable shipment cases, document version lineage, operational states,
review tasks, waiting timeouts, and audit events.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

from .analytics import build_metrics
from .core import prepare_cfg, process_email


CASE_STATES = {"VERIFIED", "DISCREPANCY", "NEEDS_REVIEW", "WAITING", "BLOCKED"}
ACTION_STATES = {"DISCREPANCY", "NEEDS_REVIEW", "BLOCKED"}

_SHIPMENT_PATTERNS = (
    re.compile(r"\b[0-9][A-Z]{3}-[0-9]{5}\b", re.I),
    re.compile(r"\b(?:booking|shipment|case|oc)\s*(?:no\.?|number|#|:)?\s*([A-Z0-9][A-Z0-9._/-]{4,})", re.I),
)
_REFERENCE_TOKEN_RE = re.compile(r"\b(?=[A-Z0-9-]*\d)[A-Z][A-Z0-9]+(?:-[A-Z0-9]+){1,3}\b", re.I)
_VERSION_RE = re.compile(r"(?:^|[_ .-])(?:v|ver|version|rev|revision)[_ .-]*(\d+)\b", re.I)


_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS shipment_cases (
    case_id             TEXT PRIMARY KEY,
    shipment_reference  TEXT NOT NULL UNIQUE,
    state               TEXT NOT NULL,
    state_reason        TEXT,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    waiting_since       REAL
);

CREATE TABLE IF NOT EXISTS routed_messages (
    email_id       TEXT PRIMARY KEY,
    sender         TEXT,
    subject        TEXT,
    category       TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS case_emails (
    email_id       TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES shipment_cases(case_id),
    sender         TEXT,
    subject        TEXT,
    received_at    TEXT,
    category       TEXT NOT NULL,
    evaluator_status TEXT NOT NULL,
    payload_json   TEXT NOT NULL,
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    document_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id        TEXT NOT NULL REFERENCES shipment_cases(case_id),
    role           TEXT NOT NULL,
    created_at     REAL NOT NULL,
    UNIQUE(case_id, role)
);

CREATE TABLE IF NOT EXISTS document_versions (
    version_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    INTEGER NOT NULL REFERENCES documents(document_id),
    email_id       TEXT NOT NULL REFERENCES case_emails(email_id),
    source_path    TEXT NOT NULL,
    version_index  INTEGER NOT NULL,
    version_label  TEXT,
    is_active      INTEGER NOT NULL DEFAULT 0,
    created_at     REAL NOT NULL,
    UNIQUE(document_id, source_path)
);

CREATE TABLE IF NOT EXISTS comparisons (
    comparison_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id        TEXT NOT NULL REFERENCES shipment_cases(case_id),
    email_id       TEXT NOT NULL REFERENCES case_emails(email_id),
    state          TEXT NOT NULL,
    defect_fields  TEXT NOT NULL,
    evidence_json  TEXT NOT NULL,
    created_at     REAL NOT NULL,
    UNIQUE(email_id)
);

CREATE TABLE IF NOT EXISTS review_tasks (
    task_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id        TEXT NOT NULL REFERENCES shipment_cases(case_id),
    kind           TEXT NOT NULL,
    reason         TEXT,
    status         TEXT NOT NULL DEFAULT 'OPEN',
    assignee       TEXT,
    resolution_note TEXT,
    created_at     REAL NOT NULL,
    resolved_at    REAL
);

CREATE UNIQUE INDEX IF NOT EXISTS one_open_task_per_case
ON review_tasks(case_id) WHERE status = 'OPEN';

CREATE TABLE IF NOT EXISTS field_corrections (
    correction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id        TEXT NOT NULL REFERENCES shipment_cases(case_id),
    comparison_id  INTEGER NOT NULL REFERENCES comparisons(comparison_id),
    field          TEXT NOT NULL,
    side           TEXT NOT NULL,
    old_value      TEXT,
    new_value      TEXT,
    actor          TEXT NOT NULL,
    note           TEXT,
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id        TEXT NOT NULL REFERENCES shipment_cases(case_id),
    event_type     TEXT NOT NULL,
    actor          TEXT NOT NULL,
    detail_json    TEXT NOT NULL,
    created_at     REAL NOT NULL
);
"""


def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def shipment_reference(email):
    """Return the best stable shipment reference available in an email."""
    haystack = "\n".join(
        [
            str(email.get("subject", "")),
            str(email.get("body", "")),
            "\n".join(str(path) for path in email.get("attachments") or []),
        ]
    )
    for pattern in _SHIPMENT_PATTERNS:
        match = pattern.search(haystack)
        if match:
            return (match.group(1) if match.lastindex else match.group(0)).upper()
    for match in _REFERENCE_TOKEN_RE.finditer(haystack):
        token = match.group(0).upper().strip("_-.")
        if token not in {"DRAFT-BL", "BILL-OF-LADING"}:
            return token
    email_id = email.get("email_id") or email.get("id")
    return f"EMAIL:{email_id}".upper()


def stable_case_id(reference):
    digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:12]
    return f"case_{digest}"


def product_state(record):
    """Translate evaluator states into the product lifecycle."""
    status = record.get("status")
    reason = record.get("review_reason")
    if status == "MISMATCH":
        return "DISCREPANCY"
    if status == "NEEDS_REVIEW" and reason == "missing_attachment":
        return "WAITING"
    if status == "NEEDS_REVIEW":
        return "NEEDS_REVIEW"
    return "VERIFIED"


def apply_correction(evidence, field, side, value, actor, now):
    """Recompute a stored comparison with one corrected extracted value.

    Shared by both stores so the Correct Extraction action runs the same
    comparison rules as the automated path, whichever backend persists it.

    -> (evidence, result); raises ValueError for an unknown field or side.
    """
    from .compare import compare_values

    if side not in ("si", "bl"):
        raise ValueError("side must be 'si' or 'bl'")
    evidence = dict(evidence or {})
    fields = evidence.get("fields") or {}
    if field not in fields:
        raise ValueError(f"unknown field: {field}")

    before = fields[field].get(side)
    si_vals = {f: v.get("si") for f, v in fields.items()}
    bl_vals = {f: v.get("bl") for f, v in fields.items()}
    (si_vals if side == "si" else bl_vals)[field] = value
    result = compare_values(
        si_vals, bl_vals, fields=list(fields),
        si_sources={f: v["si_source"] for f, v in fields.items()
                    if v.get("si_source")},
        bl_sources={f: v["bl_source"] for f, v in fields.items()
                    if v.get("bl_source")},
    )
    result["fields"][field]["corrected"] = {
        "side": side, "from": before, "to": value, "actor": actor, "at": now,
    }
    evidence["fields"] = result["fields"]
    evidence["confidence"] = result.get("confidence")
    result["old_value"] = before
    return evidence, result


def document_version(path):
    """Return an explicit version number/label, or ``(None, None)``."""
    name = Path(path).stem
    match = _VERSION_RE.search(name)
    if not match:
        return None, None
    return int(match.group(1)), match.group(0).strip(" _.-")


class CaseStore:
    """SQLite repository for operational case state.

    A long-lived connection makes ``:memory:`` useful in tests and keeps each
    multi-table ingestion transaction atomic.
    """

    def __init__(self, db_path):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(self.db_path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(_SCHEMA)
        self.con.commit()

    def close(self):
        self.con.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _event(self, case_id, event_type, detail=None, actor="system", now=None):
        self.con.execute(
            "INSERT INTO audit_events(case_id,event_type,actor,detail_json,created_at) VALUES (?,?,?,?,?)",
            (case_id, event_type, actor, _json(detail or {}), now or time.time()),
        )

    def ensure_case(self, reference, now=None):
        now = now or time.time()
        case_id = stable_case_id(reference)
        found = self.con.execute(
            "SELECT case_id FROM shipment_cases WHERE shipment_reference=?", (reference,)
        ).fetchone()
        if found:
            return found["case_id"], False
        self.con.execute(
            "INSERT INTO shipment_cases VALUES (?,?,?,?,?,?,?)",
            (case_id, reference, "WAITING", "awaiting_processing", now, now, now),
        )
        self._event(case_id, "CASE_CREATED", {"shipment_reference": reference}, now=now)
        return case_id, True

    def _set_state(self, case_id, state, reason=None, now=None):
        if state not in CASE_STATES:
            raise ValueError(f"invalid case state: {state}")
        now = now or time.time()
        previous = self.con.execute(
            "SELECT state,state_reason FROM shipment_cases WHERE case_id=?", (case_id,)
        ).fetchone()
        waiting_since = now if state == "WAITING" and previous["state"] != "WAITING" else None
        if state == "WAITING" and previous["state"] == "WAITING":
            current = self.con.execute(
                "SELECT waiting_since FROM shipment_cases WHERE case_id=?", (case_id,)
            ).fetchone()
            waiting_since = current["waiting_since"] or now
        self.con.execute(
            "UPDATE shipment_cases SET state=?,state_reason=?,updated_at=?,waiting_since=? WHERE case_id=?",
            (state, reason, now, waiting_since, case_id),
        )
        if previous["state"] != state or previous["state_reason"] != reason:
            self._event(
                case_id,
                "STATE_CHANGED",
                {"from": previous["state"], "to": state, "reason": reason},
                now=now,
            )

    def _record_email(self, case_id, email, record, now):
        email_id = email.get("email_id") or email.get("id")
        cursor = self.con.execute(
            "INSERT OR IGNORE INTO case_emails VALUES (?,?,?,?,?,?,?,?,?)",
            (
                email_id,
                case_id,
                email.get("from"),
                email.get("subject"),
                email.get("received_at") or email.get("date"),
                record["category"],
                record["status"],
                _json(email),
                now,
            ),
        )
        return cursor.rowcount == 1

    def _document_role(self, path, evidence):
        if path == evidence.get("si_doc"):
            return "SI"
        if path == evidence.get("bl_doc"):
            return "BL"
        role = (evidence.get("doc_kinds") or {}).get(path)
        if role in {"SI", "BL", "OTHER"}:
            return role
        name = Path(path).stem.upper()
        if re.search(r"(?:^|[_ .-])SI(?:$|[_ .-])", name):
            return "SI"
        if re.search(r"(?:^|[_ .-])BL(?:$|[_ .-])", name):
            return "BL"
        return "UNKNOWN"

    def _record_documents(self, case_id, email_id, attachments, evidence, now):
        for path in attachments:
            role = self._document_role(path, evidence)
            self.con.execute(
                "INSERT OR IGNORE INTO documents(case_id,role,created_at) VALUES (?,?,?)",
                (case_id, role, now),
            )
            document_id = self.con.execute(
                "SELECT document_id FROM documents WHERE case_id=? AND role=?",
                (case_id, role),
            ).fetchone()["document_id"]
            explicit, label = document_version(path)
            current = self.con.execute(
                "SELECT COALESCE(MAX(version_index),0) AS n FROM document_versions WHERE document_id=?",
                (document_id,),
            ).fetchone()["n"]
            version_index = explicit if explicit is not None else current + 1
            inserted = self.con.execute(
                "INSERT OR IGNORE INTO document_versions(document_id,email_id,source_path,version_index,version_label,is_active,created_at) VALUES (?,?,?,?,?,0,?)",
                (document_id, email_id, path, version_index, label, now),
            ).rowcount
            if not inserted:
                continue
            active = self.con.execute(
                "SELECT COALESCE(MAX(version_index),0) AS n FROM document_versions WHERE document_id=? AND is_active=1",
                (document_id,),
            ).fetchone()["n"]
            if version_index >= active:
                self.con.execute(
                    "UPDATE document_versions SET is_active=0 WHERE document_id=?", (document_id,)
                )
                self.con.execute(
                    "UPDATE document_versions SET is_active=1 WHERE document_id=? AND source_path=?",
                    (document_id, path),
                )
            self._event(
                case_id,
                "DOCUMENT_VERSION_ADDED",
                {"role": role, "source_path": path, "version_index": version_index},
                now=now,
            )

    def _sync_review_task(self, case_id, state, reason, now):
        open_task = self.con.execute(
            "SELECT task_id FROM review_tasks WHERE case_id=? AND status='OPEN'", (case_id,)
        ).fetchone()
        if state in ACTION_STATES:
            if open_task:
                self.con.execute(
                    "UPDATE review_tasks SET kind=?,reason=? WHERE task_id=?",
                    (state, reason, open_task["task_id"]),
                )
            else:
                self.con.execute(
                    "INSERT INTO review_tasks(case_id,kind,reason,created_at) VALUES (?,?,?,?)",
                    (case_id, state, reason, now),
                )
                self._event(case_id, "REVIEW_TASK_CREATED", {"kind": state, "reason": reason}, now=now)
        elif open_task:
            self.con.execute(
                "UPDATE review_tasks SET status='CANCELLED',resolved_at=?,resolution_note=? WHERE task_id=?",
                (now, "Superseded by a new automated result", open_task["task_id"]),
            )

    def ingest_result(self, email, record, evidence, now=None):
        """Persist one already-processed email; safe to call repeatedly."""
        now = now or time.time()
        if record["category"] != "BL_COMPARISON":
            email_id = email.get("email_id") or email.get("id")
            with self.con:
                self.con.execute(
                    "INSERT OR IGNORE INTO routed_messages VALUES (?,?,?,?,?,?)",
                    (
                        email_id,
                        email.get("from"),
                        email.get("subject"),
                        record["category"],
                        _json(email),
                        now,
                    ),
                )
            return None
        reference = shipment_reference(email)
        with self.con:
            case_id, _ = self.ensure_case(reference, now)
            if not self._record_email(case_id, email, record, now):
                return self.get_case(case_id)
            email_id = email.get("email_id") or email.get("id")
            self._event(
                case_id,
                "EMAIL_INGESTED",
                {"email_id": email_id, "category": record["category"]},
                now=now,
            )
            self._record_documents(
                case_id, email_id, email.get("attachments") or [], evidence, now
            )
            state = product_state(record)
            reason = record.get("review_reason")
            self.con.execute(
                "INSERT INTO comparisons(case_id,email_id,state,defect_fields,evidence_json,created_at) VALUES (?,?,?,?,?,?)",
                (case_id, email_id, state, _json(record.get("defect_fields") or []), _json(evidence), now),
            )
            self._set_state(case_id, state, reason, now)
            self._sync_review_task(case_id, state, reason, now)
        return self.get_case(case_id)

    def mark_overdue(self, wait_seconds, now=None):
        """Move stale WAITING cases to BLOCKED and create action tasks."""
        now = now or time.time()
        cutoff = now - wait_seconds
        rows = self.con.execute(
            "SELECT case_id FROM shipment_cases WHERE state='WAITING' AND waiting_since<=?",
            (cutoff,),
        ).fetchall()
        with self.con:
            for row in rows:
                case_id = row["case_id"]
                self._set_state(case_id, "BLOCKED", "missing_document_timeout", now)
                self._sync_review_task(case_id, "BLOCKED", "missing_document_timeout", now)
        return [row["case_id"] for row in rows]

    def correct_field(self, case_id, field, side, value, actor, note=None,
                      now=None):
        """Replace one extracted value and re-decide the case.

        The Correct Extraction action of v2 §9: the previous value is kept as
        evidence, and the corrected values go back through the same comparison
        rules that produced the original result rather than a second code path
        that could disagree with it.
        """
        now = now or time.time()
        with self.con:
            row = self.con.execute(
                "SELECT * FROM comparisons WHERE case_id=? "
                "ORDER BY created_at DESC, comparison_id DESC LIMIT 1",
                (case_id,),
            ).fetchone()
            if not row:
                raise ValueError("case has no comparison to correct")
            evidence, result = apply_correction(
                json.loads(row["evidence_json"]), field, side, value, actor, now)
            before = result["old_value"]

            state = product_state(result)
            reason = result.get("review_reason")
            self.con.execute(
                "UPDATE comparisons SET state=?,defect_fields=?,evidence_json=? "
                "WHERE comparison_id=?",
                (state, _json(result["defect_fields"]), _json(evidence),
                 row["comparison_id"]),
            )
            self.con.execute(
                "INSERT INTO field_corrections(case_id,comparison_id,field,side,"
                "old_value,new_value,actor,note,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (case_id, row["comparison_id"], field, side, before, value,
                 actor, note, now),
            )
            self._set_state(case_id, state, reason, now)
            self._sync_review_task(case_id, state, reason, now)
            self._event(
                case_id,
                "EXTRACTION_CORRECTED",
                {"field": field, "side": side, "from": before, "to": value,
                 "note": note, "new_state": state},
                actor=actor,
                now=now,
            )
        return self.get_case(case_id)

    def resolve_task(self, task_id, actor, note=None, now=None):
        now = now or time.time()
        with self.con:
            task = self.con.execute(
                "SELECT * FROM review_tasks WHERE task_id=? AND status='OPEN'", (task_id,)
            ).fetchone()
            if not task:
                raise ValueError("open review task not found")
            self.con.execute(
                "UPDATE review_tasks SET status='RESOLVED',assignee=?,resolution_note=?,resolved_at=? WHERE task_id=?",
                (actor, note, now, task_id),
            )
            self._event(
                task["case_id"],
                "REVIEW_TASK_RESOLVED",
                {"task_id": task_id, "note": note},
                actor=actor,
                now=now,
            )

    def list_cases(self, state=None):
        sql = "SELECT * FROM shipment_cases"
        args = ()
        if state:
            sql += " WHERE state=?"
            args = (state,)
        sql += " ORDER BY updated_at DESC, case_id"
        return [dict(row) for row in self.con.execute(sql, args)]

    def list_routed_messages(self, category=None):
        sql = "SELECT email_id,sender,subject,category,payload_json,created_at FROM routed_messages"
        args = ()
        if category:
            sql += " WHERE category=?"
            args = (category,)
        sql += " ORDER BY created_at,email_id"
        rows = []
        for row in self.con.execute(sql, args):
            item = dict(row)
            item["payload_json"] = json.loads(item["payload_json"])
            rows.append(item)
        return rows

    def metrics(self):
        cases = [dict(row) for row in self.con.execute("SELECT * FROM shipment_cases")]
        routed = [dict(row) for row in self.con.execute("SELECT * FROM routed_messages")]
        tasks = [dict(row) for row in self.con.execute("SELECT * FROM review_tasks")]
        comparisons = [dict(row) for row in self.con.execute("SELECT * FROM comparisons")]
        email_count = self.con.execute("SELECT COUNT(*) AS count FROM case_emails").fetchone()["count"]
        return build_metrics(cases, routed, tasks, comparisons, email_count, time.time())

    def get_case(self, case_id):
        case = self.con.execute(
            "SELECT * FROM shipment_cases WHERE case_id=?", (case_id,)
        ).fetchone()
        if not case:
            return None
        data = dict(case)
        data["emails"] = [
            {**dict(row), "payload_json": json.loads(row["payload_json"])}
            for row in self.con.execute(
                "SELECT email_id,sender,subject,received_at,category,evaluator_status,payload_json,created_at FROM case_emails WHERE case_id=? ORDER BY created_at,email_id",
                (case_id,),
            )
        ]
        data["documents"] = [
            dict(row)
            for row in self.con.execute(
                "SELECT d.role,v.source_path,v.version_index,v.version_label,v.is_active,v.created_at FROM documents d JOIN document_versions v ON v.document_id=d.document_id WHERE d.case_id=? ORDER BY d.role,v.version_index,v.version_id",
                (case_id,),
            )
        ]
        data["review_tasks"] = [
            dict(row)
            for row in self.con.execute(
                "SELECT * FROM review_tasks WHERE case_id=? ORDER BY task_id", (case_id,)
            )
        ]
        data["corrections"] = [
            dict(row)
            for row in self.con.execute(
                "SELECT * FROM field_corrections WHERE case_id=? ORDER BY correction_id",
                (case_id,),
            )
        ]
        data["comparisons"] = []
        for row in self.con.execute(
            "SELECT comparison_id,email_id,state,defect_fields,evidence_json,created_at FROM comparisons WHERE case_id=? ORDER BY comparison_id",
            (case_id,),
        ):
            comparison = dict(row)
            comparison["defect_fields"] = json.loads(comparison["defect_fields"])
            comparison["evidence"] = json.loads(comparison.pop("evidence_json"))
            data["comparisons"].append(comparison)
        data["audit_events"] = [
            {**dict(row), "detail": json.loads(row["detail_json"])}
            for row in self.con.execute(
                "SELECT * FROM audit_events WHERE case_id=? ORDER BY event_id", (case_id,)
            )
        ]
        for event in data["audit_events"]:
            event.pop("detail_json", None)
        return data


class CaseService:
    """Application service that runs the existing engine and persists cases."""

    def __init__(self, store, cfg=None):
        self.store = store
        self.cfg = prepare_cfg(cfg)

    def ingest_email(self, email, source, now=None):
        record, evidence = process_email(email, source, self.cfg)
        case = self.store.ingest_result(email, record, evidence, now=now)
        return {"record": record, "evidence": evidence, "case": case}

    def ingest_source(self, source, only=None):
        results = []
        for email in source.emails():
            email_id = email.get("email_id") or email.get("id")
            if only and email_id not in only:
                continue
            results.append(self.ingest_email(email, source))
        return results
