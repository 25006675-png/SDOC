#!/usr/bin/env python3
"""Run the derived demo set through the real pipeline and case workflow."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdoc.casework import CaseService, CaseStore
from sdoc.sources import DirSource


def validate(root, db_path=":memory:"):
    root = Path(root)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    expected = {case["email_id"]: case for case in manifest["cases"]}
    errors = []
    with CaseStore(db_path) as store:
        source = DirSource(root)
        emails = source.emails()
        results = CaseService(store, {"ocr": True}).ingest_source(source)
        for email, result in zip(emails, results):
            email_id = email["email_id"]
            want = expected[email_id]
            got = result["record"]
            for key in ("status", "review_reason", "defect_fields"):
                expected_key = f"expected_{key}"
                if got[key] != want[expected_key]:
                    errors.append({
                        "email_id": email_id,
                        "field": key,
                        "expected": want[expected_key],
                        "actual": got[key],
                    })
        final = {case["shipment_reference"]: case["state"] for case in store.list_cases()}
        for reference, state in manifest["expected_final_states"].items():
            if final.get(reference) != state:
                errors.append({
                    "shipment_reference": reference,
                    "field": "final_state",
                    "expected": state,
                    "actual": final.get(reference),
                })
        summary = {
            "processed": len(results),
            "cases": len(final),
            "states": final,
            "errors": errors,
        }
    print(json.dumps(summary, indent=2))
    return not errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default="demo-data")
    parser.add_argument("--db", default=":memory:")
    args = parser.parse_args()
    raise SystemExit(0 if validate(args.root, args.db) else 1)
