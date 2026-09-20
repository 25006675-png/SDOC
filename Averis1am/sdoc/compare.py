"""SI-vs-BL comparison: extract fields, normalise, diff, explain."""
from .docs import extract_field_sources, extract_fields
from .schema import COMPARE_FIELDS, FIELD_KINDS, norm_value, similarity


def _within_tol(a, b, tol):
    """Relative-tolerance numeric match: |a-b| <= tol * max(|a|,|b|).

    Catches real-world noise like VGM-vs-gross-weight rounding where an exact
    integer match is too strict. tol=0.005 means 'within half a percent'.
    """
    if not tol or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    return abs(a - b) <= tol * max(abs(a), abs(b), 1)


def compare_documents(si_pairs, bl_pairs, label_map=None, fuzzy=None,
                      fields=None, field_kinds=None, tolerances=None):
    """Compare one SI against one draft BL.

    Returns a result dict:
        status        'OK' | 'MISMATCH' | 'NEEDS_REVIEW'
        review_reason 'missing_value' when a needed value can't be read
        defect_fields canonical fields whose values differ
        fields        per-field evidence {si, bl, si_norm, bl_norm, match, sim}
        missing       fields that were blank/absent on either side
        confidence    distance from the decision boundary (min field margin)

    `fields` overrides the built-in seven (config-driven extra fields).
    `field_kinds` maps field -> normalisation kind for config fields.
    `tolerances` maps field -> relative tolerance for numeric kinds.
    `fuzzy` (0..1, default off) lets near-identical strings count as matches —
    useful on messier real-world data where typos shouldn't raise a defect.
    """
    return compare_values(
        extract_fields(si_pairs, label_map),
        extract_fields(bl_pairs, label_map),
        fuzzy=fuzzy, fields=fields, field_kinds=field_kinds,
        tolerances=tolerances,
        si_sources=extract_field_sources(si_pairs, label_map),
        bl_sources=extract_field_sources(bl_pairs, label_map),
    )


def compare_values(si_fields, bl_fields, fuzzy=None, fields=None,
                   field_kinds=None, tolerances=None,
                   si_sources=None, bl_sources=None):
    """Compare already-extracted field values.

    Split out of compare_documents so a human correction re-runs exactly the
    same rules against the corrected value, rather than a second code path
    that could disagree with the automated one.
    """
    fields = fields or COMPARE_FIELDS
    kinds = field_kinds or {}
    tolerances = tolerances or {}
    si_sources = si_sources or {}
    bl_sources = bl_sources or {}

    si_vals = {f: norm_value(f, si_fields.get(f), kinds.get(f)) for f in fields}
    bl_vals = {f: norm_value(f, bl_fields.get(f), kinds.get(f)) for f in fields}
    missing = [f for f in fields if si_vals[f] is None or bl_vals[f] is None]

    ev_fields, defects = {}, []
    for f in fields:
        sim = similarity(si_fields.get(f), bl_fields.get(f))
        if si_vals[f] is None or bl_vals[f] is None:
            match, tol_hit = None, False
        elif si_vals[f] == bl_vals[f]:
            match, tol_hit = True, False
        elif _within_tol(si_vals[f], bl_vals[f], tolerances.get(f)):
            match, tol_hit = True, True
        elif (fuzzy and sim >= fuzzy
              and (kinds.get(f) or FIELD_KINDS.get(f, "text"))
                  not in ("count", "weight")):
            match, tol_hit = True, False
        else:
            match, tol_hit = False, False
            defects.append(f)
        ev_fields[f] = {"si": si_fields.get(f), "bl": bl_fields.get(f),
                        "si_norm": si_vals[f], "bl_norm": bl_vals[f],
                        "match": match, "sim": round(sim, 3)}
        if si_sources.get(f):
            ev_fields[f]["si_source"] = si_sources[f]
        if bl_sources.get(f):
            ev_fields[f]["bl_source"] = bl_sources[f]
        if tol_hit:
            ev_fields[f]["within_tolerance"] = True

    # margin = how far each field sits from flipping the decision: matched
    # fields contribute sim (want high), defects contribute 1-sim (want low
    # similarity to be a confident defect). Min over fields = worst case.
    margins = [e["sim"] if e["match"] else 1 - e["sim"]
               for e in ev_fields.values() if e["match"] is not None]
    confidence = round(min(margins), 3) if margins else None

    base = {"defect_fields": defects, "fields": ev_fields,
            "missing": missing, "confidence": confidence}
    if missing:
        return {**base, "status": "NEEDS_REVIEW", "review_reason": "missing_value",
                "defect_fields": []}
    if defects:
        return {**base, "status": "MISMATCH", "review_reason": None}
    return {**base, "status": "OK", "review_reason": None}
