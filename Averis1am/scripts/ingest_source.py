#!/usr/bin/env python3
"""Ingest a local organizer/demo source into SQLite or Supabase."""
from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT.parent / ".env")

from sdoc.casework import CaseService, CaseStore
from sdoc.sources import DirSource
from sdoc.supabase_store import SupabaseStore
from sdoc.verification import GeminiVerifier


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source",
        nargs="?",
        default=os.environ.get("SDOC_BUNDLE_PATH", str(ROOT / "sdoc-hackathon-bundle")),
    )
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    store = (
        SupabaseStore()
        if os.environ.get("SDOC_STORE", "sqlite").lower() == "supabase"
        else CaseStore(os.environ.get("SDOC_DB_PATH", str(ROOT / "data" / "sdoc.db")))
    )
    verifier = GeminiVerifier() if args.verify else None
    try:
        source = DirSource(args.source)
        only = None
        if args.limit:
            only = {
                (email.get("email_id") or email.get("id"))
                for email in source.emails()[: args.limit]
            }
        results = CaseService(
            store, {"ocr": args.ocr, "verifier": verifier}
        ).ingest_source(source, only=only)
        states = collections.Counter(
            result["case"]["state"] for result in results if result["case"]
        )
        print({
            "source": str(args.source),
            "processed": len(results),
            "states": dict(states),
            "metrics": store.metrics(),
        })
    finally:
        if verifier:
            verifier.close()
        store.close()


if __name__ == "__main__":
    main()
