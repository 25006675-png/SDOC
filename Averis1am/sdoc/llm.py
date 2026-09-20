"""Optional LLM fallback for documents the rule readers can't handle.

Design: a document is only offered to the LLM when the deterministic path has
already failed (unreadable / unparseable), so it can never make things worse —
without it the email would escalate to NEEDS_REVIEW anyway.

Plug in any callable:

    extractor(data: bytes, filename: str) -> (title, [(label, value), ...]) | None

    register_llm_extractor(extractor)               # global, library use
    cfg["llm_extractor"] = extractor                # per-run, preferred

`openai_extractor()` builds a callable against an OpenAI-compatible chat
endpoint (works with local servers like Ollama/vLLM too). It sends the
document's best-effort decoded text and expects strict JSON back; binary
documents with no decodable text are declined (returns None) — wrap a
multimodal endpoint yourself via register_llm_extractor for those.
"""
import json
import urllib.request

_EXTRACTOR = None


def register_llm_extractor(fn):
    """Library hook: set the process-wide fallback extractor."""
    global _EXTRACTOR
    _EXTRACTOR = fn


def llm_extractor(cfg=None):
    """The configured extractor: per-run cfg wins over the global hook.

    Plain endpoint settings are supported so helper processes do not need to
    receive a Python callable.
    """
    cfg = cfg or {}
    if cfg.get("llm_extractor"):
        return cfg["llm_extractor"]
    if cfg.get("llm_endpoint"):
        return openai_extractor(
            cfg["llm_endpoint"],
            api_key=cfg.get("llm_key"),
            model=cfg.get("llm_model", "gpt-4o-mini"),
            timeout=cfg.get("llm_timeout", 60),
        )
    return _EXTRACTOR


def _decode_best_effort(data):
    for enc in ("utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    # reject if it still looks binary (lots of control chars / NULs)
    if "\x00" in text or sum(c < " " and c not in "\n\t\r" for c in text[:4000]) > 40:
        return None
    return text[:16000]


_PROMPT = """You are a shipping-document parser. Extract the document title and
every label:value field from the document text below. Reply with ONLY JSON:
{"title": "...", "fields": [{"label": "...", "value": "..."}]}
Keep labels exactly as printed. No markdown, no commentary.

DOCUMENT TEXT (file: {name}):
{text}"""


def openai_extractor(base_url, api_key=None, model="gpt-4o-mini", timeout=60):
    """Callable for OpenAI-compatible /chat/completions endpoints.

    base_url may be the server root (http://host:port) or a full path.
    """
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/v1/chat/completions"

    def extract(data, filename):
        text = _decode_best_effort(data)
        if text is None:
            return None                     # binary doc: endpoint can't help
        req = urllib.request.Request(
            url,
            data=json.dumps({
                "model": model,
                "messages": [{"role": "user",
                              "content": _PROMPT.format(name=filename,
                                                        text=text)}],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            }).encode(),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {api_key}"}
                        if api_key else {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
            content = body["choices"][0]["message"]["content"]
            parsed = json.loads(content)
        except Exception:
            return None
        fields = parsed.get("fields") or []
        pairs = [(str(f.get("label", "")).strip(), str(f.get("value", "")).strip())
                 for f in fields if f.get("label")]
        if not pairs:
            return None
        return str(parsed.get("title") or ""), pairs

    return extract
