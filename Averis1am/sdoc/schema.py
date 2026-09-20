"""Field schema: canonical fields, label synonyms, value normalisation.

The same information appears under different headers across SI and BL
layouts ("Port of Loading" vs "Load Port", "Gross Wt (kgs)" vs
"Gross Weight毛重(KGS)"), so every raw label is normalised before lookup.
Extend coverage by adding synonyms to RAW_LABELS or via --config labels.
"""
import re
import unicodedata
from difflib import SequenceMatcher

# The 7 fields compared between the Shipping Instruction and the draft BL.
COMPARE_FIELDS = [
    "shipper", "consignee", "notify_party",
    "port_of_loading", "port_of_discharge",
    "container_count", "gross_weight_kg",
]

# Canonical field -> label synonyms seen across layouts.
RAW_LABELS = {
    "shipper":           ["Shipper", "Shipper/Exporter", "Shipper (Principal or Seller)",
                          "SHIPPER", "Sender", "Exporter",
                          # 中文 / FR / DE / ES / Bahasa
                          "发货人", "托运人", "Expéditeur", "Versender",
                          "Remitente", "Pengirim"],
    "consignee":         ["Consignee", "Consignee (Non-Negotiable)", "CONSIGNEE",
                          "To the Order of", "Receiver",
                          "收货人", "Destinataire", "Empfänger",
                          "Consignatario", "Penerima"],
    "notify_party":      ["Notify Party", "Notify", "Notify Party/Intermediate Consignee",
                          "NOTIFY PARTY", "通知人", "通知方"],
    "port_of_loading":   ["Port of Loading", "Port of Loading (POL)", "Load Port",
                          "POL", "PORT OF LOADING", "Place of Receipt",
                          "装货港", "装运港", "Port de chargement", "Ladehafen",
                          "Puerto de carga", "Pelabuhan muat"],
    "port_of_discharge": ["Port of Discharge", "Port of Discharge (POD)", "Discharge Port",
                          "POD", "PORT OF DISCHARGE", "Place of Delivery",
                          "卸货港", "Port de déchargement", "Löschhafen",
                          "Puerto de descarga", "Pelabuhan bongkar"],
    "container_count":   ["No. of Containers", "Total Containers",
                          "No. of Containers or Packages", "Container Count",
                          "Number of Containers",
                          "箱数", "集装箱数", "Nombre de conteneurs",
                          "Anzahl Container", "Número de contenedores"],
    "gross_weight_kg":   ["Gross Weight (KG)", "Gross Wt (kgs)", "Gross Weight毛重(KGS)",
                          "GROSS WEIGHT", "Total Gross Weight", "Gross Weight",
                          "毛重", "Poids brut", "Bruttogewicht",
                          "Peso bruto", "Berat kasar"],
    # Non-compared fields — parsed only for context / doc-type cues.
    "vessel":            ["Vessel", "Ocean Vessel", "Vessel Name",
                          "Export Carrier (vessel, voyage)", "船名"],
    "voyage":            ["Voyage No.", "Voy.", "Voy. No", "Voyage", "航次"],
    "commodity":         ["Commodity", "Description of Goods", "Description",
                          "Kinds of Packages; Description of Goods", "货名"],
    "booking":           ["Booking Reference", "Booking No.", "Booking Ref",
                          "BOOKING NO.", "订舱号", "订舱单号"],
    "bl_no":             ["B/L No.", "BL No.", "Bill of Lading No.", "B/L NUMBER",
                          "提单号"],
}

PARTY_FIELDS = ("shipper", "consignee", "notify_party")
PORT_FIELDS = ("port_of_loading", "port_of_discharge")

# Normalisation kind per canonical field. Config-declared fields (see
# field_specs()) pick one of: party | port | count | weight | text.
FIELD_KINDS = {
    "shipper": "party", "consignee": "party", "notify_party": "party",
    "port_of_loading": "port", "port_of_discharge": "port",
    "container_count": "count", "gross_weight_kg": "weight",
}


def norm_label(s):
    """NFKC-normalise (full-width -> half-width), lowercase, drop punctuation.

    Unicode-aware: letters/digits in ANY script are kept, so CJK and accented
    labels match their synonyms; bilingual labels like 'Shipper (发货人)' fall
    back to the English part via right-trimming in field_for_label().
    """
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = re.sub(r"[\W_]+", " ", s)          # \W = non-word char (any script)
    return " ".join(s.split())


def build_label_map(extra=None):
    """{normalised label: field}. `extra` may add {field: [labels]} (--config)."""
    m = {}
    for f, labs in RAW_LABELS.items():
        for lab in labs:
            m[norm_label(lab)] = f
    for f, labs in (extra or {}).items():
        for lab in labs:
            m[norm_label(lab)] = f
    return m


LABEL2FIELD = build_label_map()


def field_for_label(label, label_map=None):
    """Resolve a raw label string to a canonical field name (or None).

    Exact match first; then progressively drop trailing words so suffix junk
    (CJK unit annotations, trailing codes) doesn't break the lookup.
    """
    lmap = label_map or LABEL2FIELD
    n = norm_label(label)
    cands = [n, n[6:]] if n.startswith("total ") else [n]  # "TOTAL Gross Wt (kgs):"
    for cand in cands:
        while cand:
            if cand in lmap:
                return lmap[cand]
            cand = cand.rpartition(" ")[0]
    return None


# ---------------------------------------------------------------------------
# Value normalisation
# ---------------------------------------------------------------------------
BLANK_TOKENS = {"tba", "tbc", "n/a", "na", "none", "-",
                "待定", "待确认", "未定", "无"}


def is_blank(v):
    """'???', '_______', 'TBA', 'N/A', '____MT', '', '待定' -> True."""
    s = str(v).strip().lower()
    return (re.fullmatch(r"[\s?_/\-]*", s) is not None
            or s in BLANK_TOKENS
            or re.fullmatch(r"_+\s*[\w]*", s) is not None)


def _norm_party(v):
    v = unicodedata.normalize("NFKC", v)
    v = v.split("\n")[0].split("|")[0]           # name line only (addr follows)
    v = v.replace("&", " and ")
    v = re.sub(r"[^\w ]+|_", " ", v)             # punctuation never distinguishes
    v = re.sub(r"\s+", " ", v).strip().upper()   # keeps letters in any script
    return v or None


def _norm_port(v):
    v = unicodedata.normalize("NFKC", v)
    v = v.split("\n")[0]
    v = re.sub(r"\s*\([A-Z0-9]{2,6}\)\s*$", "", v)   # trailing UN/LOCODE e.g. (SGSIN)
    v = re.sub(r"\s+", " ", v).strip().upper().rstrip(".,")
    return v or None


_KG_PER = {"kg": 1.0, "kgs": 1.0, "mt": 1000.0, "mts": 1000.0,
           "ton": 1000.0, "tons": 1000.0, "tonne": 1000.0, "tonnes": 1000.0,
           "lb": 0.45359237, "lbs": 0.45359237}


def _norm_weight(v):
    """Gross weight -> kg (int). Handles '131,058 KG', '243588', '243.6 MT'."""
    m = re.search(r"([\d][\d,]*(?:\.\d+)?)\s*([a-zA-Z]*)", v)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower().rstrip(".")
    if unit and unit not in _KG_PER:
        return int(round(num))                   # unknown unit: compare raw number
    return int(round(num * _KG_PER.get(unit, 1.0)))


def _norm_count(v):
    m = re.search(r"(\d+)\s*[xX×]", v) or re.search(r"(\d+)", v)
    return int(m.group(1)) if m else None


_NORM_BY_KIND = {"party": _norm_party, "port": _norm_port,
                 "count": _norm_count, "weight": _norm_weight}


def norm_value(field, raw, kind=None):
    """Canonical comparison value; None when the value is missing/blank."""
    if raw is None:
        return None
    v = unicodedata.normalize("NFKC", str(raw)).strip()  # ２４３ -> 243
    if is_blank(v):
        return None
    fn = _NORM_BY_KIND.get(kind or FIELD_KINDS.get(field, "text"))
    if fn:
        return fn(v)
    return re.sub(r"\s+", " ", v).strip() or None


# ---------------------------------------------------------------------------
# Config-driven fields (--config fields): extend the comparison set without
# code changes. Accepts either form:
#   {"fields": {"vessel": {"kind": "text", "labels": ["Vessel", "Vessel/VOY"],
#                          "tolerance": 0}}}
#   {"fields": {"vessel": ["Vessel", "Vessel/VOY"]}}          # kind = text
# ---------------------------------------------------------------------------
def field_specs(cfg=None):
    """{field: {"kind": str, "labels": [..], "tolerance": float|None}} merged
    over the built-in COMPARE_FIELDS."""
    specs = {f: {"kind": FIELD_KINDS.get(f, "text"), "labels": [],
                 "tolerance": None} for f in COMPARE_FIELDS}
    for f, s in ((cfg or {}).get("fields") or {}).items():
        if not isinstance(s, dict):
            s = {"labels": list(s or [])}
        specs[f] = {"kind": s.get("kind") or specs.get(f, {}).get("kind", "text"),
                    "labels": list(s.get("labels") or []),
                    "tolerance": s.get("tolerance")}
    return specs


def compare_fields(cfg=None):
    """Ordered canonical field list: built-ins first, then config fields."""
    return COMPARE_FIELDS + [f for f in ((cfg or {}).get("fields") or {})
                             if f not in COMPARE_FIELDS]


def similarity(a, b):
    """0..1 textual similarity of two raw values (for evidence/fuzzy mode)."""
    if a is None or b is None:
        return 0.0
    return SequenceMatcher(None, str(a).upper(), str(b).upper()).ratio()
