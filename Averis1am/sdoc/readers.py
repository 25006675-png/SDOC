"""Attachment readers.

Every reader takes raw bytes and returns ``(title, [(label, value), ...])``
or ``None`` when the file cannot be read at all (-> 'unreadable').

Readers are looked up by file extension in ``READERS`` — new formats plug in
via ``register_reader('.ext', fn)`` without touching the pipeline.
"""
import io
import re


def _cfg_flag(cfg, name, default=False):
    """Read a feature flag from the pipeline's dict config or an object."""
    if isinstance(cfg, dict):
        return cfg.get(name, default)
    return getattr(cfg, name, default)

# ---------------------------------------------------------------------------
# Optional OCR (scanned PDFs / image attachments). Enabled per-run via cfg.ocr
# and only used when the native text layer is absent.
# ---------------------------------------------------------------------------
def ocr_available():
    try:
        import pytesseract  # noqa: F401
        from PIL import Image  # noqa: F401
        return bool(pytesseract.get_tesseract_version())
    except Exception:
        return False


def _ocr_pdf(data):
    """-> one text block per page, so extracted values keep a page number."""
    import pypdfium2 as pdfium
    import pytesseract
    pdf = pdfium.PdfDocument(data)
    return [pytesseract.image_to_string(page.render(scale=2).to_pil())
            for page in pdf]


def _ocr_image(data):
    import pytesseract
    from PIL import Image
    return pytesseract.image_to_string(Image.open(io.BytesIO(data)))


def _pairs_from_ocr(pages):
    """Parse OCR'd page texts like a .txt document, keeping page numbers."""
    pages = [pages] if isinstance(pages, str) else list(pages or [])
    title, pairs = "", []
    for page_no, text in enumerate(pages, start=1):
        if not text or not text.strip():
            continue
        page_title, page_pairs = _txt_pairs(text.splitlines(), page=page_no)
        title = title or page_title
        pairs.extend(page_pairs)
    if not title and not pairs:
        return None
    return title, pairs


# ---------------------------------------------------------------------------
def _pair(label, value, source=None):
    """A label/value pair carrying optional source evidence.

    Consumers read pairs through docs.pair_label/pair_value/pair_source, which
    still accept plain (label, value) tuples from third-party readers.
    """
    pair = {"label": label, "value": value}
    if source:
        pair["source"] = source
    return pair


def _txt_pairs(lines, page=None):
    title = ""
    for l in lines:
        s = l.strip()
        if s and not set(s) <= set("=-_*#"):
            title = s
            break
    pairs = []
    for idx, l in enumerate(lines, start=1):
        if not l.strip() or l[0] in " \t":      # indented lines are continuations
            continue
        if ":" in l:
            lab, val = l.split(":", 1)
            source = {"line": idx, "source_text": l.strip()}
            if page:
                source["page"] = page
            pairs.append(_pair(lab.strip(), val.strip(), source))
    return title, pairs


def read_txt(data, cfg=None):
    # try encodings in order: utf-8 -> CJK legacy -> latin-1 (never fails)
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if not text.strip():
        return None
    return _txt_pairs(text.splitlines())


# ---------------------------------------------------------------------------
def _join_chars(cs):
    """Rebuild text from pdf chars, inserting spaces at >1.5pt gaps."""
    out, prev = "", None
    for c in cs:
        if prev is not None and c["x0"] - prev["x1"] > 1.5:
            out += " "
        out += c["text"]
        prev = c
    return out


def _row_source(rchars, text):
    """Page, bounding box and snippet for one clustered row of pdf chars.

    Coordinates are PDF points with a top-left origin (pdfplumber's 'top'), and
    page dimensions travel with them so a viewer can place the box without
    knowing the document.
    """
    first = rchars[0]
    source = {
        "page": first.get("page_number") or 1,
        "bbox": [round(min(c["x0"] for c in rchars), 2),
                 round(min(c["top"] for c in rchars), 2),
                 round(max(c["x1"] for c in rchars), 2),
                 round(max(c["bottom"] for c in rchars), 2)],
        "source_text": text,
    }
    if first.get("page_width") and first.get("page_height"):
        source["page_width"] = round(first["page_width"], 2)
        source["page_height"] = round(first["page_height"], 2)
    return source


def _pairs_from_pdf_chars(chars):
    """Rows clustered by page/vertical overlap, with optional source boxes.

    Supports both generated forms used in the bundle: bold-label/regular-value
    rows and plain ``Label: value`` rows. The returned pairs stay compatible
    with tuple consumers through docs.pair_label/pair_value/pair_source.
    """
    chars.sort(key=lambda c: (c.get("page_number", 1), c["top"], c["x0"]))
    rows = []
    for c in chars:
        page = c.get("page_number", 1)
        if rows and rows[-1][2] == page and c["top"] <= rows[-1][1] + 1.5:
            rows[-1][0].append(c)
            rows[-1][1] = max(rows[-1][1], c["bottom"])
        else:
            rows.append([[c], c["bottom"], page])
    lines = []
    for rchars, _, _ in rows:
        rchars.sort(key=lambda c: c["x0"])
        bold = _join_chars([c for c in rchars if "bold" in c["fontname"].lower()])
        reg = _join_chars([c for c in rchars if "bold" not in c["fontname"].lower()])
        lines.append((bold.strip(), reg.strip(), _join_chars(rchars).strip(), rchars))
    title = next((t for _, _, t, _ in lines if t), "")
    pairs = []
    for bold, reg, full, rchars in lines:
        if ":" in bold:                          # "Label: value" in one draw run
            lab, val = bold.split(":", 1)
            pairs.append(_pair(lab.strip(), f"{val} {reg}".strip(),
                               _row_source(rchars, full)))
        elif bold and reg:                       # bold label col + regular value
            pairs.append(_pair(bold, reg, _row_source(rchars, full)))
        elif ":" in full:                         # non-bold "Label: value"
            lab, val = full.split(":", 1)
            pairs.append(_pair(lab.strip(), val.strip(), _row_source(rchars, full)))
    return title, pairs

def read_pdf(data, cfg=None):
    import pdfplumber
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            chars = []
            for idx, pg in enumerate(pdf.pages, start=1):
                for c in pg.chars:
                    item = dict(c)
                    item["page_number"] = getattr(pg, "page_number", idx) or idx
                    item["page_width"] = pg.width
                    item["page_height"] = pg.height
                    chars.append(item)
    except Exception:
        return None                                # corrupt / truncated file
    # force_ocr is the alternate reading route of the recovery cycle (v2 §7.4):
    # re-read a document whose text layer parsed but validated incomplete.
    if chars and not _cfg_flag(cfg, "force_ocr"):
        return _pairs_from_pdf_chars(chars)
    # no text layer: scanned copy — OCR if enabled, else unreadable
    if _cfg_flag(cfg, "ocr") and ocr_available():
        try:
            return _pairs_from_ocr(_ocr_pdf(data))
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
def read_docx(data, cfg=None):
    import docx
    try:
        d = docx.Document(io.BytesIO(data))
    except Exception:
        return None
    title = next((p.text.strip() for p in d.paragraphs if p.text.strip()), "")
    pairs = []
    for ti, t in enumerate(d.tables, start=1):
        for ri, row in enumerate(t.rows, start=1):
            if len(row.cells) >= 2:
                lab, val = row.cells[0].text.strip(), row.cells[1].text.strip()
                if lab and val:
                    pairs.append(_pair(lab, val, {
                        "table": ti, "row": ri,
                        "source_text": f"{lab}: {val}",
                    }))
    return title, pairs


def read_xlsx(data, cfg=None):
    import openpyxl
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
    except Exception:
        return None
    ws = wb.active
    pairs = []
    for ri, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if len(row) >= 2 and row[0] is not None and row[1] is not None:
            lab, val = str(row[0]).strip(), str(row[1]).strip()
            pairs.append(_pair(lab, val, {
                "sheet": ws.title, "row": ri,
                "source_text": f"{lab}: {val}",
            }))
    return (ws.title or ""), pairs


def read_image(data, cfg=None):
    """Image attachments are only readable via OCR."""
    if _cfg_flag(cfg, "ocr") and ocr_available():
        try:
            return _pairs_from_ocr(_ocr_image(data))
        except Exception:
            return None
    return None


def read_unsupported(data, cfg=None):
    return None


# ---------------------------------------------------------------------------
# Extension registry — plug new formats in with register_reader().
# ---------------------------------------------------------------------------
READERS = {
    ".txt": read_txt, ".text": read_txt, ".csv": read_txt, ".md": read_txt,
    ".pdf": read_pdf,
    ".docx": read_docx,
    ".xlsx": read_xlsx, ".xlsm": read_xlsx,
    ".png": read_image, ".jpg": read_image, ".jpeg": read_image,
    ".tif": read_image, ".tiff": read_image, ".bmp": read_image,
    ".doc": read_unsupported,                    # legacy binary Word
}


def register_reader(ext, fn):
    READERS[ext.lower()] = fn


def reader_for(path):
    """Reader function for a file path's extension, or None."""
    name = str(path).lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    return READERS.get(ext)
