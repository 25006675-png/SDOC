"""Username/password sessions and role separation.

Two roles, matching v2 Table 14:

- ``worker``  works the case queue; may trigger a sync but not configure one.
- ``admin``   configures mailboxes and sees organisation analytics.

Sessions are HMAC-signed tokens in an HttpOnly cookie. Passwords are stored as
PBKDF2 hashes. No new dependency: this is enough to keep a deployed instance
from being world-readable, which is the actual requirement. Organisation
membership and row-level policies remain the P2 work described in v2 §15.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

SESSION_COOKIE = "sdoc_session"
ROLES = ("worker", "admin")
_ITERATIONS = 120_000


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds, salt, digest = stored.split("$")
        if scheme != "pbkdf2":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _unb64(salt), int(rounds))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(_b64(candidate), digest)


def session_secret() -> bytes:
    """Signing key for session cookies.

    A generated key is fine for a single process, but every restart then
    invalidates existing sessions and separate instances cannot validate each
    other's cookies -- set SDOC_SESSION_SECRET before deploying.
    """
    configured = os.environ.get("SDOC_SESSION_SECRET")
    if configured:
        return configured.encode("utf-8")
    global _EPHEMERAL_SECRET
    if _EPHEMERAL_SECRET is None:
        _EPHEMERAL_SECRET = secrets.token_bytes(32)
    return _EPHEMERAL_SECRET


_EPHEMERAL_SECRET: bytes | None = None


def default_users() -> dict[str, dict]:
    """Seeded demo accounts; passwords are overridable by environment."""
    accounts = {
        "admin": (os.environ.get("SDOC_ADMIN_PASSWORD", "admin123"), "admin",
                  "Operations Manager"),
        "worker": (os.environ.get("SDOC_WORKER_PASSWORD", "worker123"), "worker",
                   "Documentation Officer"),
    }
    return {
        username: {
            "username": username,
            "role": role,
            "display_name": display,
            "password_hash": hash_password(password),
        }
        for username, (password, role, display) in accounts.items()
    }


class UserStore:
    def __init__(self, users=None):
        self.users = users if users is not None else default_users()

    def authenticate(self, username, password):
        user = self.users.get(str(username or "").strip().lower())
        if not user or not verify_password(str(password or ""),
                                           user["password_hash"]):
            return None
        return {k: v for k, v in user.items() if k != "password_hash"}

    def get(self, username):
        user = self.users.get(username)
        if not user:
            return None
        return {k: v for k, v in user.items() if k != "password_hash"}


def issue_session(username, role, ttl_seconds=None, now=None):
    """-> a signed opaque token carrying the username, role and expiry."""
    ttl = int(ttl_seconds or os.environ.get("SDOC_SESSION_TTL", 12 * 3600))
    expires = int(now or time.time()) + ttl
    payload = f"{username}:{role}:{expires}"
    signature = hmac.new(session_secret(), payload.encode("utf-8"),
                         hashlib.sha256).digest()
    return f"{_b64(payload.encode('utf-8'))}.{_b64(signature)}"


def read_session(token, now=None):
    """-> {'username', 'role'} for a valid unexpired token, else None."""
    if not token or "." not in str(token):
        return None
    encoded, signature = str(token).split(".", 1)
    try:
        payload = _unb64(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    expected = hmac.new(session_secret(), payload.encode("utf-8"),
                        hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_unb64(signature), expected):
            return None
    except (ValueError, TypeError):
        return None
    try:
        username, role, expires = payload.rsplit(":", 2)
        expires = int(expires)
    except ValueError:
        return None
    if expires <= int(now or time.time()):
        return None
    if role not in ROLES:
        return None
    return {"username": username, "role": role}
