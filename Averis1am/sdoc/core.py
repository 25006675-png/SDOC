"""Per-email pipeline orchestration: classify -> read docs -> compare."""
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .classify import classify_result
from .compare import compare_documents
from .docs import doc_kind, identify_pair
from .schema import build_label_map, compare_fields, field_specs
from .validation import read_with_recovery


def process_email(email, source, cfg=None):
    """-> (record, evidence).

    record follows the submission schema; evidence carries everything needed
    to explain the decision (doc kinds, per-field values, errors) for the
    human-review report.
    """
    cfg = cfg or {}
    classification = classify_result(email, cfg)
    cat = classification["category"]
    email = {
        **email,
        "classification": classification,
    }
    rec = {"category": cat, "status": "OK", "review_reason": None,
           "defect_fields": [], "has_defect": False, "decided_by": "rule"}
    ev = {
        "attachments": list(email.get("attachments") or []),
        "classification": classification,
    }
    if cat != "BL_COMPARISON":
        return rec, ev
    try:
        status, reason, defects = _process_bl(email, source, cfg, ev)
    except Exception as e:                       # visible failure, not a crash
        status, reason, defects = "NEEDS_REVIEW", "unreadable", []
        ev["error"] = f"{type(e).__name__}: {e}"
    rec.update(status=status, review_reason=reason, defect_fields=defects,
               has_defect=status == "MISMATCH")
    return rec, ev


def _process_bl(email, source, cfg, ev):
    """-> (status, review_reason, defect_fields); fills ev."""
    atts = email.get("attachments") or []

    if len(atts) < 2:
        if len(atts) == 1:
            ev["note"] = "single attachment only"
            return "NEEDS_REVIEW", "missing_attachment", []
        # nothing attached: a genuine comparison request missing its files,
        # or simply a "please send the draft BL" request (nothing to check yet)
        body = re.sub(r"WARNING:.*?attachments\.", "",
                      str(email.get("body", "")), flags=re.S)
        if re.search(r"compare|dropped|missing|附件|比较|核对", body, re.I):
            ev["note"] = "request expects attachments that are not there"
            return "NEEDS_REVIEW", "missing_attachment", []
        ev["note"] = "draft-BL request, no documents to compare yet"
        return "OK", None, []

    si_path, bl_path, docs, problem = identify_pair(atts, source, cfg)
    ev["doc_kinds"] = {a: (doc_kind(*d) if d else "UNREADABLE")
                       for a, d in docs.items()}
    if problem:
        return "NEEDS_REVIEW", problem, []

    # Deterministic validation plus at most one recovery cycle, on the two
    # documents that actually get compared (v2 §7.2-7.4). The extraction
    # status is evidence; it does not override the submission status below.
    validation = {}
    for side, path in (("si", si_path), ("bl", bl_path)):
        recovered, status, trace = read_with_recovery(
            source, path, cfg, doc=docs[path], fields=cfg.get("field_list"))
        if recovered is not None:
            docs[path] = recovered
        validation[side] = {"document": path, "status": status, **trace}
    ev["validation"] = validation

    result = compare_documents(docs[si_path][1], docs[bl_path][1],
                               label_map=cfg.get("label_map"),
                               fuzzy=cfg.get("fuzzy"),
                               fields=cfg.get("field_list"),
                               field_kinds=cfg.get("field_kinds"),
                               tolerances=cfg.get("tolerances"))
    ev["si_doc"], ev["bl_doc"] = si_path, bl_path
    for values in result["fields"].values():
        if values.get("si_source"):
            values["si_source"] = {**values["si_source"], "document": si_path}
        if values.get("bl_source"):
            values["bl_source"] = {**values["bl_source"], "document": bl_path}
    ev["fields"] = result["fields"]
    ev["confidence"] = result.get("confidence")
    if result["missing"]:
        ev["missing"] = result["missing"]
    verifier = cfg.get("verifier")
    if verifier and result["status"] != "NEEDS_REVIEW":
        from .verification import verify_documents
        verification = verify_documents(
            source, si_path, bl_path, result, verifier,
            fields=cfg.get("field_list"), field_kinds=cfg.get("field_kinds"),
        )
        ev["verification"] = verification
        if verification["status"] == "FAILED":
            return "NEEDS_REVIEW", "verifier_failed", []
        if verification["status"] == "DISAGREED":
            return "NEEDS_REVIEW", "verifier_disagreement", []
    return result["status"], result["review_reason"], result["defect_fields"]


def prepare_cfg(cfg):
    """Normalise user config into the internal shape once per run.

    - 'labels' + per-field 'labels' inside cfg['fields'] merge into label_map
    - cfg['fields'] declares extra comparison fields (kind/labels/tolerance)
    - cfg['tolerances'] merges field-level and top-level tolerance maps
    """
    cfg = dict(cfg or {})
    specs = field_specs(cfg)
    extra_labels = dict(cfg.get("labels") or {})
    for f, s in specs.items():
        if s["labels"]:
            extra_labels.setdefault(f, []).extend(s["labels"])
    cfg["label_map"] = cfg.get("label_map") or build_label_map(extra_labels)
    cfg["field_list"] = compare_fields(cfg)
    cfg["field_kinds"] = {f: s["kind"] for f, s in specs.items()}
    tol = dict(cfg.get("tolerances") or {})
    tol.update({f: s["tolerance"] for f, s in specs.items()
                if s.get("tolerance") is not None})
    cfg["tolerances"] = tol
    return cfg


def run(source, cfg=None, only=None, workers=1):
    """Process the inbox -> (submission, records, evidence).

    workers > 1 parallelises document parsing (CPU/IO-bound) across threads;
    results stay in deterministic email order regardless of worker count.
    """
    cfg = prepare_cfg(cfg)
    emails = [e for e in source.emails()
              if not only or (e.get("email_id") or e.get("id")) in only]
    if workers and workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(
                lambda e: process_email(e, source, cfg), emails))
    else:
        results = [process_email(e, source, cfg) for e in emails]

    submission, records, evidence = {}, {}, {}
    for email, (rec, ev) in zip(emails, results):
        eid = email.get("email_id") or email.get("id")
        records[eid], evidence[eid] = rec, ev
        submission[eid] = {k: rec[k] for k in
                           ("category", "status", "review_reason",
                            "defect_fields", "has_defect")}
    return submission, records, evidence


def summarize(records):
    return {
        "categories": dict(Counter(r["category"] for r in records.values())),
        "statuses": dict(Counter(r["status"] for r in records.values())),
        "review_reasons": dict(Counter(r["review_reason"] for r in records.values()
                                       if r["review_reason"])),
        "defect_fields": dict(Counter(f for r in records.values()
                                      for f in r["defect_fields"])),
    }
