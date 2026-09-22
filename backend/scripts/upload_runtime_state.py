#!/usr/bin/env python3
"""Copy local mailbox state files into the Supabase runtime-state table.

Lets a deployed server start already connected, using the login made locally:

    python scripts/upload_runtime_state.py data/gmail_token.json data/gmail_state.json

Each file becomes the row keyed by its file name. Run the
20260921_003_sdoc_runtime_state.sql migration first.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT.parent / ".env")
os.environ["SDOC_STATE_BACKEND"] = "supabase"

from sdoc import runtime_state  # noqa: E402


def main(paths):
    if not paths:
        sys.exit(__doc__)
    for name in paths:
        path = Path(name)
        runtime_state.save(path, json.loads(path.read_text(encoding="utf-8")))
        print(f"uploaded {path.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
