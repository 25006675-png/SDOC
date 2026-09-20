"""Reporting: machine-readable JSON, human-readable HTML, flat CSV."""
import csv
import difflib
import html
import json
from pathlib import Path

from .core import summarize


def build_report(source, submission, records, evidence):
    """Everything needed to explain and audit the run."""
    review_queue = {eid: {"review_reason": r["review_reason"],
                          "confidence": evidence.get(eid, {}).get("confidence"),
                          "note": evidence.get(eid, {}).get("note"),
                          "doc_kinds": evidence.get(eid, {}).get("doc_kinds"),
                          "missing": evidence.get(eid, {}).get("missing"),
                          "error": evidence.get(eid, {}).get("error")}
                    for eid, r in records.items() if r["status"] == "NEEDS_REVIEW"}
    return {"source": str(source), "n_emails": len(records),
            "summary": summarize(records),
            "review_queue": review_queue,
            "records": records, "evidence": evidence}


def write_json(obj, path):
    Path(path).write_text(json.dumps(obj, indent=2), encoding="utf-8")


def write_csv(records, evidence, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["email_id", "category", "status", "review_reason",
                    "defect_fields", "has_defect", "attachments"])
        for eid in sorted(records):
            r = records[eid]
            w.writerow([eid, r["category"], r["status"], r["review_reason"] or "",
                        ";".join(r["defect_fields"]), r["has_defect"],
                        ";".join(evidence.get(eid, {}).get("attachments", []))])


_STATUS_STYLE = {"OK": "#2e7d32", "MISMATCH": "#c62828", "NEEDS_REVIEW": "#ef6c00"}


def _diff_mark(a, b):
    """(si_html, bl_html) — matching segments plain, differing ones <mark>'d.
    Shows *what* changed inside a mismatched field, not just that it differs."""
    a, b = str(a), str(b)
    ha, hb = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        sa, sb = html.escape(a[i1:i2]), html.escape(b[j1:j2])
        if tag == "equal":
            ha.append(sa)
            hb.append(sb)
        else:
            if sa:
                ha.append(f"<mark>{sa}</mark>")
            if sb:
                hb.append(f"<mark>{sb}</mark>")
    return "".join(ha), "".join(hb)


def write_html(report, path):
    """Self-contained discrepancy report: summary, review queue, and for every
    BL_COMPARISON email a side-by-side SI/BL field table."""
    s = report["summary"]
    parts = [
        "<html><head><meta charset='utf-8'><style>",
        "body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}",
        "h1{font-size:20px} h2{font-size:16px;margin-top:28px}",
        "table{border-collapse:collapse;margin:8px 0;font-size:13px}",
        "td,th{border:1px solid #ccc;padding:4px 10px;text-align:left;vertical-align:top}",
        "th{background:#f0f0f0}",
        ".chip{display:inline-block;padding:2px 8px;border-radius:8px;color:#fff;font-size:12px}",
        ".bad{background:#fdecea}.ok{background:#e8f5e9}mark{background:#ffd54f}",
        ".mono{font-family:Consolas,monospace;font-size:12px}",
        "details{margin:4px 0}summary{cursor:pointer}",
        "</style></head><body>",
        f"<h1>SDOC discrepancy report — {html.escape(str(report['source']))}</h1>",
        f"<p>{report['n_emails']} emails processed.</p>",
        "<h2>Summary</h2><table><tr><th>axis</th><th>counts</th></tr>",
    ]
    for k in ("categories", "statuses", "review_reasons", "defect_fields"):
        parts.append(f"<tr><td>{k}</td><td class='mono'>{html.escape(str(s[k]))}</td></tr>")
    parts.append("</table>")

    # review queue
    rq = report["review_queue"]
    parts.append(f"<h2>Review queue ({len(rq)} cases needing a person)</h2>")
    if rq:
        parts.append("<table><tr><th>email</th><th>reason</th><th>confidence</th>"
                     "<th>context</th></tr>")
        # lowest-confidence cases first — the risky decisions surface at the top
        for eid in sorted(rq, key=lambda e: (rq[e]["confidence"] is None,
                                             rq[e]["confidence"] or 0, e)):
            q = rq[eid]
            ctx = q["note"] or q["error"] or (
                "doc types: " + str(q["doc_kinds"]) if q["doc_kinds"] else "") or ""
            if q["missing"]:
                ctx += (" missing: " + ",".join(q["missing"]))
            conf = "—" if q["confidence"] is None else f"{q['confidence']:.2f}"
            parts.append(f"<tr><td class='mono'>{eid}</td><td>{q['review_reason']}</td>"
                         f"<td>{conf}</td><td>{html.escape(str(ctx))}</td></tr>")
        parts.append("</table>")

    # per-email table for BL_COMPARISON
    parts.append("<h2>Document comparisons</h2><table><tr><th>email</th>"
                 "<th>status</th><th>detail</th></tr>")
    for eid in sorted(report["records"]):
        r = report["records"][eid]
        if r["category"] != "BL_COMPARISON":
            continue
        color = _STATUS_STYLE.get(r["status"], "#666")
        ev = report["evidence"].get(eid, {})
        detail = ""
        if ev.get("fields"):
            def _row(n, f):
                if f["match"] is False and f["si"] and f["bl"]:
                    si_h, bl_h = _diff_mark(f["si"], f["bl"])   # show what changed
                else:
                    si_h, bl_h = (html.escape(str(f["si"])),
                                  html.escape(str(f["bl"])))
                return (f"<tr class='{'' if f['match'] else 'bad'}'><td>{n}</td>"
                        f"<td>{si_h}</td><td>{bl_h}</td></tr>")
            rows = "".join(_row(n, f) for n, f in ev["fields"].items())
            detail = ("<details><summary>SI vs BL side by side</summary>"
                      f"<table><tr><th>field</th><th>SI</th><th>BL</th></tr>{rows}</table></details>")
        if r["defect_fields"]:
            detail += " defects: " + ", ".join(r["defect_fields"])
        if r["review_reason"]:
            detail += " reason: " + r["review_reason"]
        parts.append(f"<tr><td class='mono'>{eid}</td>"
                     f"<td><span class='chip' style='background:{color}'>{r['status']}</span></td>"
                     f"<td>{detail}</td></tr>")
    parts.append("</table></body></html>")
    Path(path).write_text("".join(parts), encoding="utf-8")
