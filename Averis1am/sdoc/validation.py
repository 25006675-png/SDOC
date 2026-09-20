"""Deterministic validation and one bounded recovery cycle.

Implements v2 §7.2-7.4. The validator checks structure, not truth: required
fields present, values parseable under their canonical kind. A well-formed but
wrong value passes here by design and is caught by the independent verifier
instead.

Recovery is bounded to a single cycle. Re-running the same read without
feedback is not a retry, so the retry always changes something: it feeds the
specific validation failures back to the extractor, or takes one alternate
reading route.

The statuses here describe the extraction, not the shipment case. Case state
(VERIFIED / DISCREPANCY / NEEDS REVIEW / WAITING / BLOCKED) is decided
separately in casework, and the submission contract is unaffected.
"""
from . import readers
from .docs import extract_bytes, extract_fields, load_doc
from .schema import COMPARE_FIELDS, is_blank, norm_value

FIRST_PASS_VALIDATED = "FIRST_PASS_VALIDATED"
RECOVERED = "RECOVERED"
NEEDS_REVIEW = "NEEDS_REVIEW"


def validate_extraction(pairs, fields=None, label_map=None, field_kinds=None):
    """-> {field: 'missing' | 'unparseable'} for everything that fails."""
    fields = fields or COMPARE_FIELDS
    kinds = field_kinds or {}
    values = extract_fields(pairs, label_map)
    problems = {}
    for field in fields:
        raw = values.get(field)
        if is_blank(raw):
            problems[field] = "missing"
        elif norm_value(field, raw, kinds.get(field)) is None:
            problems[field] = "unparseable"
    return problems


def _as_dict(cfg):
    return dict(cfg) if isinstance(cfg, dict) else {}


def _call_extractor(extractor, data, att_path, problems):
    """Offer the validation failures; fall back for 2-argument extractors."""
    try:
        return extractor(data, att_path, problems)
    except TypeError:
        return extractor(data, att_path)


def _alternate_read(source, att_path, cfg, problems):
    """One alternate reading route -> (doc, route_name) or (None, None).

    A PDF that parsed from its text layer is re-read through OCR; anything
    else is offered to the configured LLM extractor with the failures named.
    """
    try:
        data = source.read_bytes(att_path)
    except Exception:
        return None, None
    if not data:
        return None, None

    if str(att_path).lower().endswith(".pdf") and readers.ocr_available():
        doc = extract_bytes(data, att_path, {**_as_dict(cfg), "ocr": True,
                                             "force_ocr": True}, problems)
        if doc is not None:
            return doc, "ocr"

    cfgd = _as_dict(cfg)
    if cfgd.get("llm_extractor") or cfgd.get("llm_endpoint"):
        llm_cfg = {**cfgd, "extractor": "llm"}
        doc = extract_bytes(data, att_path, llm_cfg, problems)
        if doc is not None:
            return doc, "llm"
    return None, None


def read_with_recovery(source, att_path, cfg=None, doc=None, fields=None):
    """Read and validate one document, allowing a single recovery cycle.

    -> (doc, status, trace). The trace records what the retry changed so the
    recovery is auditable rather than invisible.
    """
    cfg = cfg or {}
    label_map = cfg.get("label_map") if isinstance(cfg, dict) else None
    kinds = cfg.get("field_kinds") if isinstance(cfg, dict) else None
    fields = fields or (cfg.get("field_list") if isinstance(cfg, dict) else None)

    if doc is None:
        doc = load_doc(source, att_path, cfg)
    if doc is None:
        return None, NEEDS_REVIEW, {"reason": "unreadable", "routes": []}

    problems = validate_extraction(doc[1], fields, label_map, kinds)
    if not problems:
        return doc, FIRST_PASS_VALIDATED, {"routes": []}

    trace = {"first_pass_problems": problems, "routes": []}
    retry_doc, route = _alternate_read(source, att_path, cfg, problems)
    if retry_doc is None:
        return doc, NEEDS_REVIEW, trace

    trace["routes"].append(route)
    retry_problems = validate_extraction(retry_doc[1], fields, label_map, kinds)
    trace["retry_problems"] = retry_problems
    if not retry_problems:
        return retry_doc, RECOVERED, trace
    if len(retry_problems) < len(problems):
        # The alternate route read more of the document but not all of it.
        # Keep the better read; a human still has to finish the job.
        return retry_doc, NEEDS_REVIEW, trace
    return doc, NEEDS_REVIEW, trace
