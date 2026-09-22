#!/usr/bin/env python3
"""SDOC pipeline — CLI entry point. Implementation lives in the sdoc package.

    python pipeline.py sdoc-hackathon-bundle -o submission.json
    python pipeline.py http://localhost:8080 --submit
    python pipeline.py data --report report.json --html report.html --csv out.csv
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sdoc.cli import main

if __name__ == "__main__":
    main(sys.argv[1:])
