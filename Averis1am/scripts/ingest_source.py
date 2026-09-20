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
    parser.add_argument("--extractor", choices=["deterministic", "llm"], default=os.environ.get("SDOC_DOCUMENT_EXTRACTOR", "deterministic"))
    parser.add_argument("--llm-endpoint", default=os.environ.get("SDOC_LLM_ENDPOINT"))
    parser.add_argument("--llm-model", default=os.environ.get("SDOC_LLM_MODEL", "gpt-4o-mini"))
    parser.add_argument("--llm-key", default=os.environ.get("SDOC_LLM_KEY"))
    parser.add_argument("--isolated-reader", action="store_true", default=os.environ.get("SDOC_READER_ISOLATION", "1").lower() not in {"0", "false", "no", "off"})
    parser.add_argument("--reader-workers", type=int, default=int(os.environ.get("SDOC_READER_WORKERS", "2")))
    parser.add_argument("--reader-timeout", type=float, default=float(os.environ.get("SDOC_READER_TIMEOUT", "8")))
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
        cfg = {
            "ocr": args.ocr,
            "extractor": args.extractor,
            "verifier": verifier,
            "reader_isolation": args.isolated_reader,
            "reader_workers": args.reader_workers,
            "reader_timeout_seconds": args.reader_timeout,
        }
        if args.llm_endpoint:
            cfg["llm_endpoint"] = args.llm_endpoint
            cfg["llm_key"] = args.llm_key
            cfg["llm_model"] = args.llm_model
        results = CaseService(store, cfg).ingest_source(source, only=only)
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
