"""SQLite audit trail for pipeline runs and human corrections.

Every --db run appends one `runs` row plus one `results` row per email —
shipping ops needs to answer 'what did the machine decide, when, and did a
person override it' after the fact. `corrections` is written by the review
workflow (record_correction) and read back as new label synonyms / label
history for future runs.
"""
import json
import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    source    TEXT,
    n_emails  INTEGER,
    summary   TEXT,            -- JSON summary counts
    config    TEXT             -- JSON-serialisable cfg (callables dropped)
);
CREATE TABLE IF NOT EXISTS results (
    run_id        INTEGER NOT NULL,
    email_id      TEXT NOT NULL,
    category      TEXT,
    status        TEXT,
    review_reason TEXT,
    defect_fields TEXT,        -- JSON array
    has_defect    INTEGER,
    confidence    REAL,
    evidence      TEXT,        -- JSON evidence blob
    PRIMARY KEY (run_id, email_id)
);
CREATE TABLE IF NOT EXISTS corrections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         REAL NOT NULL,
    email_id   TEXT NOT NULL,
    field      TEXT,
    old_value  TEXT,
    new_value  TEXT,
    actor      TEXT,
    note       TEXT
);
"""


def _safe_json(obj):
    """JSON-dump best effort; non-serialisable values (callables) become str."""
    try:
        return json.dumps(obj, default=str)
    except Exception:
        return "{}"


def log_run(db_path, report, cfg=None):
    """Append one run + all per-email results. Returns run_id."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(_SCHEMA)
        cfg_view = {k: v for k, v in (cfg or {}).items()
                    if isinstance(v, (str, int, float, bool, list, dict,
                                      type(None)))}
        cur = con.execute(
            "INSERT INTO runs(ts, source, n_emails, summary, config)"
            " VALUES (?,?,?,?,?)",
            (time.time(), str(report.get("source")),
             report.get("n_emails"), _safe_json(report.get("summary")),
             _safe_json(cfg_view)))
        run_id = cur.lastrowid
        records, evidence = report["records"], report.get("evidence", {})
        con.executemany(
            "INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?,?,?)",
            [(run_id, eid, r["category"], r["status"], r["review_reason"],
              json.dumps(r["defect_fields"]), int(r["has_defect"]),
              (evidence.get(eid) or {}).get("confidence"),
              _safe_json(evidence.get(eid)))
             for eid, r in records.items()])
        con.commit()
        return run_id
    finally:
        con.close()


def record_correction(db_path, email_id, field, old_value, new_value,
                      actor="human", note=None):
    """A reviewer overrode a value — stored for audit and future synonym
    learning. Called by the review UI / CLI tooling, not the pipeline."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(_SCHEMA)
        con.execute("INSERT INTO corrections(ts,email_id,field,old_value,"
                    "new_value,actor,note) VALUES (?,?,?,?,?,?,?)",
                    (time.time(), email_id, field, old_value, new_value,
                     actor, note))
        con.commit()
    finally:
        con.close()


def history(db_path, limit=10):
    """Recent runs (newest first): [(run_id, ts, source, n_emails, summary)]."""
    con = sqlite3.connect(db_path)
    try:
        con.executescript(_SCHEMA)
        return con.execute(
            "SELECT run_id, ts, source, n_emails, summary FROM runs"
            " ORDER BY run_id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        con.close()
