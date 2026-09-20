"""Configurable document extraction stage.

The pipeline is single-path: classification, document identity, validation,
comparison, casework and evidence all call this stage. ``cfg['extractor']`` only
selects the primary extractor implementation for stage 2.
"""
from __future__ import annotations

from . import readers
from .llm import llm_extractor


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


def llm_extract(data, att_path, cfg=None, problems=None):
    extractor = llm_extractor(cfg)
    if not extractor:
        return None
    try:
        return _call_llm(extractor, data, att_path, problems)
    except Exception:
        return None


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
