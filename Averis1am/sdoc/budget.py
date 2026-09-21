"""AI spend ceilings (Addendum A3).

A per-case budget bounds one runaway document. It does not bound horizontal
amplification: a thousand individually compliant messages all pass a per-case
check and still add up to unbounded spend. So the ledger counts per sender and
globally, per UTC day, and refuses work once a ceiling is reached.

Counts persist to disk so a restart does not reset an attacker's allowance.
Refusal is loud: the caller stops and the message waits for a human, rather
than processing continuing quietly at a lower quality.
"""
import os
import time
from pathlib import Path

from . import runtime_state


class BudgetExceeded(RuntimeError):
    """A spend ceiling was reached; the caller must stop, not degrade."""

    def __init__(self, scope, used, limit):
        super().__init__(
            f"{scope} budget reached: {used} of {limit} messages today")
        self.scope = scope
        self.used = used
        self.limit = limit


def _int_env(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _day(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


class SpendLedger:
    """Per-sender and global daily message ceilings."""

    def __init__(self, path=None, per_sender=None, per_day=None):
        self.path = Path(path or os.environ.get(
            "SDOC_BUDGET_PATH", "data/spend_ledger.json"))
        self.per_sender = per_sender or _int_env("SDOC_MAX_PER_SENDER_DAY", 200)
        self.per_day = per_day or _int_env("SDOC_MAX_MESSAGES_DAY", 2000)

    def _load(self):
        data = runtime_state.load(self.path, {})
        return data if isinstance(data, dict) else {}

    def _save(self, data):
        runtime_state.save(self.path, data)

    def _today(self, data, now):
        day = _day(now)
        if data.get("day") != day:
            return {"day": day, "total": 0, "senders": {}}
        return data

    def usage(self, sender=None, now=None):
        data = self._today(self._load(), now or time.time())
        return {
            "day": data["day"],
            "total": data.get("total", 0),
            "total_limit": self.per_day,
            "sender": (data.get("senders") or {}).get(
                _normalise_sender(sender), 0) if sender else None,
            "sender_limit": self.per_sender,
        }

    def check(self, sender=None, now=None):
        """Raise BudgetExceeded when either ceiling is already reached."""
        data = self._today(self._load(), now or time.time())
        total = data.get("total", 0)
        if total >= self.per_day:
            raise BudgetExceeded("daily", total, self.per_day)
        if sender:
            key = _normalise_sender(sender)
            used = (data.get("senders") or {}).get(key, 0)
            if used >= self.per_sender:
                raise BudgetExceeded(f"sender {key}", used, self.per_sender)

    def record(self, sender=None, now=None, count=1):
        """Count work that was actually done."""
        now = now or time.time()
        data = self._today(self._load(), now)
        data["total"] = data.get("total", 0) + count
        if sender:
            key = _normalise_sender(sender)
            senders = data.setdefault("senders", {})
            senders[key] = senders.get(key, 0) + count
        self._save(data)
        return data


def _normalise_sender(sender):
    """Group by address, falling back to the raw header."""
    from email.utils import parseaddr

    address = parseaddr(str(sender or ""))[1].strip().lower()
    return address or str(sender or "unknown").strip().lower()
