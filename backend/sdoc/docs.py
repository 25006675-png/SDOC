"""Document typing, field extraction, and SI/BL pairing."""
import re
from pathlib import Path

from .schema import COMPARE_FIELDS, field_for_label, is_blank, norm_label

# Titles that mean "this is NOT an SI/BL document" (EN + 中文 + FR).
OTHER_DOC_TITLES = ("commercial invoice", "packing list", "certificate of origin",
                    "商业发票", "发票", "装箱单", "原产地证", "产地证",
                    "facture commerciale", "liste de colisage")
# SI markers checked before BL — "提单指示"/"bill of lading instruction" contain
# "提单"/"bill of lading" and must win.
SI_TITLES = ("shipping instruction", "lading instruction", "bl instruction",
             "装货指示", "托运指示", "货运指示", "提单指示")
BL_TITLES = ("bill of lading", "提单")


def pair_label(pair):
    if isinstance(pair, dict):
        return pair.get("label", "")
    return pair[0]


def pair_value(pair):
    if isinstance(pair, dict):
        return pair.get("value", "")
    return pair[1]


def pair_source(pair):
    if isinstance(pair, dict):
        return pair.get("source") or {}
    return {}


def doc_kind(title, pairs):
    """SI | BL | OTHER | UNKNOWN from the document title/labels."""
    t = norm_label(title)
    lab_text = " ".join(norm_label(pair_label(p)) for p in pairs[:8])
    hay = f"{t} {lab_text}"
    if any(k in hay for k in OTHER_DOC_TITLES):
        return "OTHER"
    if any(k in hay for k in SI_TITLES) or t in {"s i", "si"}:
        return "SI"
    if any(k in hay for k in BL_TITLES) or t in {"bl", "b l"}:
        return "BL"
    return "UNKNOWN"


def extract_fields(pairs, label_map=None):
    """Map raw (label, value) pairs to canonical fields. First non-blank wins."""
    fields = {}
    for pair in pairs:
        lab, val = pair_label(pair), pair_value(pair)
        f = field_for_label(lab, label_map)
        if f and (f not in fields or is_blank(fields[f])):
            fields[f] = val
    return fields


def extract_field_sources(pairs, label_map=None):
    """Map canonical fields to optional source metadata for the selected value."""
    sources = {}
    seen_values = {}
    for pair in pairs:
        lab, val = pair_label(pair), pair_value(pair)
        f = field_for_label(lab, label_map)
        if f and (f not in seen_values or is_blank(seen_values[f])):
            seen_values[f] = val
            source = pair_source(pair)
            if source:
                sources[f] = source
    return sources




def _note(notes, att_path, exc):
    """Record why a document could not be read.

    A helper-process timeout and a corrupt file both end as 'unreadable';
    without this the reviewer cannot tell which happened (Addendum A6/A10).
    """
    if notes is None:
        return
    notes.append({"document": att_path, "kind": type(exc).__name__,
                  "error": str(exc)})


def extract_bytes(data, att_path, cfg=None, problems=None, notes=None):
    """Single document extraction stage, optionally through a helper process."""
    cfg = cfg or {}
    pool = cfg.get("reader_pool") if isinstance(cfg, dict) else None
    if pool is not None:
        try:
            return pool.extract(data, att_path, cfg, problems=problems)
        except Exception as exc:
            _note(notes, att_path, exc)
            return None
    from .extractors import extract_document
    try:
        return extract_document(data, att_path, cfg, problems=problems)
    except ValueError:
        raise
    except Exception as exc:
        _note(notes, att_path, exc)
        return None


def load_doc(source, att_path, cfg=None, notes=None):
    """Read an attachment -> (title, pairs) or None when unreadable.

    When the deterministic reader fails, a configured LLM extractor
    (cfg['llm_extractor'] or llm.register_llm_extractor) gets one chance to
    rescue the document — it can only improve on 'unreadable', never regress.
    """
    try:
        data = source.read_bytes(att_path)
    except Exception as exc:
        _note(notes, att_path, exc)
        return None
    if not data:
        return None
    return extract_bytes(data, att_path, cfg, notes=notes)


def find_pair(attachments):
    """Locate the SI and BL attachments by _SI./_BL. filename suffix."""
    si = next((a for a in attachments if re.search(r"_SI\.[a-z]+$", a, re.I)), None)
    bl = next((a for a in attachments if re.search(r"_BL\.[a-z]+$", a, re.I)), None)
    rest = [a for a in attachments if a not in (si, bl)]
    if si is None and rest:
        si = rest.pop(0)
    if bl is None and rest:
        bl = rest.pop(0)
    return si, bl


def identify_pair(attachments, source, cfg=None, notes=None):
    """Decide which attachments are the SI and the BL.

    Returns (si_path, bl_path, docs, problem) where docs maps path ->
    (title, pairs) for every attachment read, and problem is None or
    ('unreadable' | 'wrong_doc_type' | 'missing_attachment').

    Filename suffixes win when present; otherwise documents are identified
    by content type so swapped or arbitrarily named files still work.
    """
    docs = {a: load_doc(source, a, cfg, notes=notes) for a in attachments}

    si_path, bl_path = find_pair(attachments)
    if si_path and bl_path:
        if docs[si_path] is None or docs[bl_path] is None:
            return None, None, docs, "unreadable"
        for path, expect in ((si_path, "SI"), (bl_path, "BL")):
            kind = doc_kind(*docs[path])
            if kind == "OTHER" or (kind in ("SI", "BL") and kind != expect):
                return None, None, docs, "wrong_doc_type"
        return si_path, bl_path, docs, None

    # No reliable suffixes — identify by document content.
    if any(d is None for d in docs.values()):
        return None, None, docs, "unreadable"
    kinds = {a: doc_kind(*d) for a, d in docs.items()}
    sis = [a for a, k in kinds.items() if k == "SI"]
    bls = [a for a, k in kinds.items() if k == "BL"]
    others = [a for a, k in kinds.items() if k == "OTHER"]
    if others:
        return None, None, docs, "wrong_doc_type"
    if len(sis) == 1 and len(bls) == 1:
        return sis[0], bls[0], docs, None
    return None, None, docs, "wrong_doc_type"
