"""Provider-neutral mailbox factory."""
from __future__ import annotations

import os

from .gmail import GmailSyncService
from .outlook import OutlookSyncService


def mailbox_provider():
    return os.environ.get("SDOC_MAILBOX_PROVIDER", "gmail").strip().lower() or "gmail"


def create_mailbox_sync(store, provider=None):
    selected = (provider or mailbox_provider()).strip().lower()
    if selected == "gmail":
        return GmailSyncService(store)
    if selected in {"outlook", "microsoft", "graph", "office365", "m365"}:
        return OutlookSyncService(store)
    raise ValueError(f"Unsupported mailbox provider: {selected}")
