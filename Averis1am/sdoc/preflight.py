"""Preflight security and resource gate (Addendum A3).

Full-page coverage means an untrusted sender controls how much work arrives,
so every attachment passes a cheap gate before any expensive AI processing.
A document that fails is never read by a model: it becomes an action for a
human, with the reason recorded.

Check order is the protection. Parsing is itself the attack surface -- you
cannot count pages without opening the file -- so the checks run in strictly
increasing cost:

    1. byte length      free, no parse
    2. magic bytes      free, first few bytes
    3. structure        only now is parsing permitted

Isolated/sandboxed parsing is a deployment requirement and is deliberately
out of scope here; see A3's deferred controls.
"""
import io
import os
import zipfile
from pathlib import Path

# Reasons are stable identifiers; they surface in the queue and in analytics.
OVERSIZE = "attachment_too_large"
TYPE_MISMATCH = "attachment_type_mismatch"
TOO_MANY_PAGES = "attachment_too_many_pages"
ENCRYPTED = "attachment_encrypted"
MALFORMED = "attachment_malformed"
ARCHIVE_BOMB = "attachment_expansion_limit"
TOO_MANY_ATTACHMENTS = "too_many_attachments"

GATE_REASONS = frozenset({
    OVERSIZE, TYPE_MISMATCH, TOO_MANY_PAGES, ENCRYPTED, MALFORMED,
    ARCHIVE_BOMB, TOO_MANY_ATTACHMENTS,
})

# Signature -> the family the bytes actually belong to.
_SIGNATURES = (
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),
    (b"\x89PNG\r\n\x1a\n", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"II*\x00", "image"),
    (b"MM\x00*", "image"),
    (b"\xd0\xcf\x11\xe0", "ole"),               # legacy .doc/.xls
)

# Extension -> the family its bytes must belong to. Text formats have no
# signature, so they are checked by decodability instead.
_EXPECTED = {
    ".pdf": "pdf",
    ".docx": "zip", ".xlsx": "zip", ".xlsm": "zip",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".tif": "image", ".tiff": "image", ".bmp": "image",
    ".doc": "ole", ".xls": "ole",
}
_TEXT_EXTENSIONS = {".txt", ".text", ".csv", ".md"}
_OOXML = {".docx", ".xlsx", ".xlsm"}


def _int_env(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


class GateConfig:
    """Resource limits. Deployment tunes these per organization."""

    def __init__(self, max_bytes=None, max_pages=None, max_attachments=None,
                 max_expansion=None, max_archive_entries=None):
        self.max_bytes = max_bytes or _int_env("SDOC_MAX_ATTACHMENT_BYTES",
                                               25 * 1024 * 1024)
        self.max_pages = max_pages or _int_env("SDOC_MAX_PAGES", 200)
        self.max_attachments = max_attachments or _int_env(
            "SDOC_MAX_ATTACHMENTS", 20)
        self.max_expansion = max_expansion or _int_env("SDOC_MAX_EXPANSION", 200)
        self.max_archive_entries = max_archive_entries or _int_env(
            "SDOC_MAX_ARCHIVE_ENTRIES", 2000)


def detected_family(data):
    """The file family the bytes actually belong to, or None."""
    for signature, family in _SIGNATURES:
        if data.startswith(signature):
            return family
    return None


def _decodes_as_text(data):
    for encoding in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        return "\x00" not in text
    return False


def _reject(reason, **detail):
    return {"ok": False, "reason": reason, "detail": detail}


def _pdf_pages(data):
    """-> (pages, problem). Only called once cheap checks have passed."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        return None, None
    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:
        if "password" in str(exc).lower() or "encrypt" in str(exc).lower():
            return None, ENCRYPTED
        return None, MALFORMED
    try:
        return len(pdf), None
    finally:
        with_close = getattr(pdf, "close", None)
        if with_close:
            with_close()


def _archive_expansion(data, cfg):
    """-> problem or None, for the zip-backed OOXML formats."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > cfg.max_archive_entries:
                return ARCHIVE_BOMB
            uncompressed = sum(item.file_size for item in entries)
    except zipfile.BadZipFile:
        return MALFORMED
    except Exception:
        return MALFORMED
    if uncompressed > cfg.max_bytes * cfg.max_expansion:
        return ARCHIVE_BOMB
    if len(data) and uncompressed / max(len(data), 1) > cfg.max_expansion:
        return ARCHIVE_BOMB
    return None


def inspect_attachment(data, filename, cfg=None):
    """Gate one attachment -> {'ok', 'reason', 'detail'}."""
    cfg = cfg or GateConfig()
    suffix = Path(str(filename)).suffix.lower()
    size = len(data or b"")

    # 1. size, free
    if size > cfg.max_bytes:
        return _reject(OVERSIZE, size=size, limit=cfg.max_bytes)
    if not size:
        return _reject(MALFORMED, size=0)

    # 2. real type, free
    family = detected_family(data)
    expected = _EXPECTED.get(suffix)
    if expected and family != expected:
        return _reject(TYPE_MISMATCH, declared=suffix or "none",
                       detected=family or "unknown")
    if suffix in _TEXT_EXTENSIONS and not _decodes_as_text(data):
        return _reject(TYPE_MISMATCH, declared=suffix, detected=family or "binary")

    # 3. structure, the first check that parses anything
    if expected == "pdf":
        pages, problem = _pdf_pages(data)
        if problem:
            return _reject(problem)
        if pages is not None and pages > cfg.max_pages:
            return _reject(TOO_MANY_PAGES, pages=pages, limit=cfg.max_pages)
        return {"ok": True, "reason": None,
                "detail": {"size": size, "pages": pages}}
    if suffix in _OOXML:
        problem = _archive_expansion(data, cfg)
        if problem:
            return _reject(problem)

    return {"ok": True, "reason": None, "detail": {"size": size}}


def screen_attachments(source, attachments, cfg=None):
    """Gate every attachment on a message.

    -> {'ok', 'reason', 'rejected': [...], 'accepted': {path: detail}}. The
    first rejection decides the message, so nothing over the limit is read.
    """
    cfg = cfg or GateConfig()
    attachments = list(attachments or [])
    if len(attachments) > cfg.max_attachments:
        return {
            "ok": False,
            "reason": TOO_MANY_ATTACHMENTS,
            "rejected": [{"document": None, "reason": TOO_MANY_ATTACHMENTS,
                          "detail": {"count": len(attachments),
                                     "limit": cfg.max_attachments}}],
            "accepted": {},
        }

    rejected, accepted = [], {}
    for path in attachments:
        try:
            data = source.read_bytes(path)
        except Exception:
            rejected.append({"document": path, "reason": MALFORMED,
                             "detail": {"error": "unreadable"}})
            continue
        verdict = inspect_attachment(data, path, cfg)
        if verdict["ok"]:
            accepted[path] = verdict["detail"]
        else:
            rejected.append({"document": path, "reason": verdict["reason"],
                             "detail": verdict["detail"]})
    return {
        "ok": not rejected,
        "reason": rejected[0]["reason"] if rejected else None,
        "rejected": rejected,
        "accepted": accepted,
    }
