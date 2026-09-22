"""Inbox data sources.

Two interchangeable sources behind one interface (emails / read_bytes /
submit), mirroring the kit's loader.py:

    DirSource   a static bundle folder containing inbox/ + attachments/;
                inbox records may be .json or .eml (real MIME mail: HTML
                bodies stripped, MIME attachments exposed under virtual
                paths attachments/<eml-stem>/<filename>)
    HttpSource  the docker server (GET /emails, /attachments/{path},
                POST /submit)
"""
import email as _email
import email.utils
import json
import re
import urllib.request
from email import policy
from html.parser import HTMLParser
from pathlib import Path


class _HtmlToText(HTMLParser):
    """Minimal HTML -> text: keeps character data, drops script/style."""
    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "tr", "li") and not self._skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self):
        return re.sub(r"\n{3,}", "\n\n",
                      re.sub(r"[ \t]+", " ", "".join(self.parts))).strip()


def html_to_text(markup):
    p = _HtmlToText()
    p.feed(markup or "")
    return p.text()


def _eml_body(msg):
    """text/plain body preferred; HTML part stripped to text otherwise."""
    plain = msg.get_body(("plain",))
    if plain is not None:
        try:
            return plain.get_content()
        except Exception:
            pass
    html = msg.get_body(("html",))
    if html is not None:
        try:
            return html_to_text(html.get_content())
        except Exception:
            pass
    try:                                    # single-part non-multipart
        return msg.get_content()
    except Exception:
        return ""


def _part_bytes(part):
    try:
        payload = part.get_payload(decode=True)
        if payload is not None:
            return payload
    except Exception:
        pass
    try:
        c = part.get_content()
        return c if isinstance(c, bytes) else str(c).encode("utf-8", "replace")
    except Exception:
        return b""


def eml_to_record(path):
    """Parse a .eml file into an inbox record + virtual attachment payloads.

    Attachments are exposed as attachments/<stem>/<filename> and their bytes
    returned in the second element so the source can serve read_bytes().
    """
    with open(path, "rb") as f:
        msg = _email.message_from_binary_file(f, policy=policy.default)
    _, addr = email.utils.parseaddr(str(msg.get("from", "")))
    attachments, payloads = [], {}
    for i, part in enumerate(msg.iter_attachments()):
        fn = part.get_filename() or f"attachment_{i}.bin"
        virt = f"attachments/{path.stem}/{fn}"
        payloads[virt] = _part_bytes(part)
        attachments.append(virt)
    record = {"email_id": path.stem,
              "subject": str(msg.get("subject", "")),
              "from": addr or str(msg.get("from", "")),
              "body": _eml_body(msg),
              "attachments": attachments}
    return record, payloads


class DirSource:
    def __init__(self, root):
        self.root = Path(root)
        self._eml_atts = {}                     # virtual path -> bytes

    def __str__(self):
        return str(self.root)

    def emails(self):
        records = []
        inbox = self.root / "inbox"
        for p in sorted(inbox.glob("*.json")):
            records.append(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(inbox.glob("*.eml")):
            rec, payloads = eml_to_record(p)
            self._eml_atts.update(payloads)
            records.append(rec)
        return sorted(records, key=lambda r: str(r.get("email_id") or r.get("id")))

    def read_bytes(self, att_path):
        if att_path in self._eml_atts:
            return self._eml_atts[att_path]
        return (self.root / att_path).read_bytes()

    def submit(self, submission):
        raise RuntimeError("submit() needs an HTTP source; "
                           "score locally with score_cli.py or run the docker server")


class HttpSource:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def __str__(self):
        return self.base

    def _get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.read()

    def _get_json(self, path):
        return json.loads(self._get(path))

    def emails(self):
        return self._get_json("/emails")

    def read_bytes(self, att_path):
        return self._get("/" + att_path.lstrip("/"))

    def submit(self, submission):
        req = urllib.request.Request(
            self.base + "/submit", data=json.dumps(submission).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())


def open_source(src):
    """'http://...'/'https://...' -> HttpSource, anything else -> DirSource."""
    if str(src).startswith(("http://", "https://")):
        return HttpSource(src)
    return DirSource(src)
