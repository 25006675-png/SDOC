"""Provider-neutral mailbox factory and registry.

Each provider keeps its own token and state files, so several can be connected
at once. What used to prevent that was routing, not storage: one global
provider setting and one service instance. The registry removes both.

Per-organisation mailbox records in the database remain the production step
described in the add-ons; this keeps the same shape at the API so that change
does not ripple outward.
"""
from __future__ import annotations

import os

from .gmail import GmailSyncService
from .outlook import OutlookSyncService

PROVIDERS = {
    "gmail": {
        "key": "gmail",
        "label": "Gmail",
        "service": GmailSyncService,
        "aliases": ("gmail", "google"),
    },
    "outlook": {
        "key": "outlook",
        "label": "Outlook",
        "service": OutlookSyncService,
        "aliases": ("outlook", "microsoft", "graph", "office365", "m365"),
    },
}

_ALIASES = {
    alias: spec["key"]
    for spec in PROVIDERS.values()
    for alias in spec["aliases"]
}


def normalise_provider(provider):
    """-> canonical provider key, or None when unrecognised."""
    return _ALIASES.get(str(provider or "").strip().lower())


def mailbox_provider():
    """The provider used where a single default is still needed."""
    return normalise_provider(os.environ.get("SDOC_MAILBOX_PROVIDER", "gmail")) or "gmail"


def create_mailbox_sync(store, provider=None):
    key = normalise_provider(provider or mailbox_provider())
    if key is None:
        raise ValueError(f"Unsupported mailbox provider: {provider}")
    return PROVIDERS[key]["service"](store)


def create_mailbox_registry(store):
    """-> {provider_key: sync service} for every supported provider.

    Constructing a service is cheap -- it reads configuration and touches its
    token file only when asked -- so all providers are available and each
    reports its own connection status.
    """
    return {key: spec["service"](store) for key, spec in PROVIDERS.items()}


def provider_label(provider):
    key = normalise_provider(provider)
    return PROVIDERS[key]["label"] if key else str(provider)


def provider_for_attachment(path):
    """-> the provider that owns an attachment path, or None."""
    text = str(path or "").replace("\\", "/")
    for key in PROVIDERS:
        if text.startswith(f"attachments/{key}/"):
            return key
    return None
