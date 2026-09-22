"""Configurable document extraction stage.

The pipeline is single-path: classification, document identity, validation,
comparison, casework and evidence all call this stage. ``cfg['extractor']`` only
selects the primary extractor implementation for stage 2.
"""
from __future__ import annotations

from . import readers
from .llm import llm_extractor
from .schema import norm_label, similarity


def _as_dict(cfg):
    return cfg if isinstance(cfg, dict) else {}


def deterministic_extract(data, att_path, cfg=None):
    reader = readers.reader_for(att_path)
    if reader is None:
        return None
    try:
        return reader(data, cfg)
    except Exception:
        return None


def _call_llm(extractor, data, att_path, problems=None):
    try:
        return extractor(data, att_path, problems)
    except TypeError:
        return extractor(data, att_path)


def _resolve_sources(doc, data, att_path, cfg):
    """Give LLM-extracted values the provenance the readers produce.

    A model cannot be trusted to report page coordinates -- it produces
    plausible wrong numbers. Instead it reports the snippet it read a value
    from, and the snippet is located in the deterministic transcription, which
    already carries page, line and box. The model does semantics; rules do
    positioning (v2 §6.3, Addendum A4/A9).
    """
    from .docs import pair_label, pair_source, pair_value

    transcription = deterministic_extract(data, att_path, cfg)
    if not transcription:
        return doc
    rows = [(pair_source(p), norm_label(f"{pair_label(p)} {pair_value(p)}"))
            for p in transcription[1] if pair_source(p)]
    if not rows:
        return doc

    resolved = []
    for pair in doc[1]:
        label, value = pair_label(pair), pair_value(pair)
        existing = pair_source(pair)
        needle = norm_label(str(existing.get("source_snippet") or "") or
                            f"{label} {value}")
        source = None
        if needle:
            best, score = None, 0.0
            for row_source, haystack in rows:
                if not haystack:
                    continue
                hit = 1.0 if needle in haystack or haystack in needle else similarity(needle, haystack)
                if hit > score:
                    best, score = row_source, hit
            if best and score >= 0.6:
                source = {**best, **{k: v for k, v in existing.items()
                                     if k == "source_snippet"}}
        resolved.append({"label": label, "value": value,
                         **({"source": source} if source else
                            {"source": existing} if existing else {})})
    return doc[0], resolved


def llm_extract(data, att_path, cfg=None, problems=None):
    extractor = llm_extractor(cfg)
    if not extractor:
        return None
    try:
        doc = _call_llm(extractor, data, att_path, problems)
    except Exception:
        return None
    if not doc:
        return None
    try:
        return _resolve_sources(doc, data, att_path, cfg)
    except Exception:
        return doc          # evidence is a bonus; never lose the extraction


def extract_document(data, att_path, cfg=None, problems=None):
    """Return ``(title, pairs)`` or ``None`` using the configured stage.

    ``extractor='deterministic'`` is the default and performs no model calls.
    If an LLM extractor is configured, deterministic mode may use it only as a
    fallback after the deterministic reader fails. ``extractor='llm'`` makes
    the LLM primary and deterministic fallback, so real-mail/demo runs share
    the same downstream pipeline while allowing semantic extraction.
    """
    cfgd = _as_dict(cfg)
    mode = str(cfgd.get("extractor") or "deterministic").lower()
    if mode == "llm":
        return llm_extract(data, att_path, cfg, problems) or deterministic_extract(data, att_path, cfg)
    if mode != "deterministic":
        raise ValueError("extractor must be 'deterministic' or 'llm'")
    return deterministic_extract(data, att_path, cfg) or llm_extract(data, att_path, cfg, problems)
