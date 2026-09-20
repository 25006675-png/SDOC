"""Command-line interface.

    python pipeline.py sdoc-hackathon-bundle -o submission.json
    python pipeline.py http://localhost:8080 --submit
    python pipeline.py data --report report.json --html report.html --csv out.csv

Options that matter for future/messier data:
    --fuzzy 0.95        treat near-identical strings as matches (typos)
    --ocr               OCR scanned PDFs/images when tesseract is installed
    --config c.json     extend labels, keywords, fields, tolerances
    --workers 8         parallel document parsing
    --db audits.db      append the run to a SQLite audit trail
    --llm-endpoint URL  LLM fallback for docs the rule readers can't parse
    --emails a,b        only process a subset (debugging)
"""
import argparse
import json
import os
import sys

from .core import run, summarize
from .report import build_report, write_csv, write_html, write_json
from .sources import open_source


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pipeline.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="bundle folder or http://host:port server")
    ap.add_argument("-o", "--out", default="submission.json",
                    help="submission JSON path (default submission.json)")
    ap.add_argument("--report", help="write detailed JSON report (evidence + review queue)")
    ap.add_argument("--html", help="write a human-readable HTML discrepancy report")
    ap.add_argument("--csv", help="write a flat CSV of per-email results")
    ap.add_argument("--submit", action="store_true",
                    help="POST the submission to the server (http source only)")
    ap.add_argument("--fuzzy", type=float, default=None,
                    help="0..1 similarity threshold for text fields (default: exact)")
    ap.add_argument("--ocr", action="store_true",
                    help="OCR image-only PDFs/images when tesseract is installed")
    ap.add_argument("--config", help="JSON file extending labels/keywords/fields/tolerances")
    ap.add_argument("--workers", type=int, default=1,
                    help="parallel document parsing threads (default 1)")
    ap.add_argument("--db", help="append this run to a SQLite audit database")
    ap.add_argument("--llm-endpoint",
                    help="OpenAI-compatible endpoint for unreadable docs "
                         "(e.g. http://localhost:11434 for Ollama)")
    ap.add_argument("--llm-model", default="gpt-4o-mini",
                    help="model name for --llm-endpoint")
    ap.add_argument("--llm-key", default=None,
                    help="API key (default: env SDOC_LLM_KEY)")
    ap.add_argument("--emails", help="comma-separated email_ids to process only")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    cfg = {"fuzzy": args.fuzzy, "ocr": args.ocr}
    if args.config:
        c = json.loads(open(args.config, encoding="utf-8").read())
        cfg.update(c)
    if args.llm_endpoint:
        from .llm import openai_extractor
        cfg["llm_extractor"] = openai_extractor(
            args.llm_endpoint, api_key=args.llm_key or os.getenv("SDOC_LLM_KEY"),
            model=args.llm_model)

    source = open_source(args.source)
    only = set(args.emails.split(",")) if args.emails else None
    submission, records, evidence = run(source, cfg, only=only,
                                        workers=args.workers)

    write_json(submission, args.out)
    if not args.quiet:
        print(f"{len(records)} emails -> {args.out}")
        for k, v in summarize(records).items():
            print(f"  {k}: {v}")

    if args.report or args.html or args.csv or args.db:
        report = build_report(source, submission, records, evidence)
        if args.report:
            write_json(report, args.report)
        if args.html:
            write_html(report, args.html)
        if args.csv:
            write_csv(records, evidence, args.csv)
        if args.db:
            from .audit import log_run
            run_id = log_run(args.db, report, cfg)
            if not args.quiet:
                print(f"  audited to {args.db} (run #{run_id})")

    if args.submit:
        result = source.submit(submission)
        print(json.dumps(result, indent=2))

    return submission


if __name__ == "__main__":
    main(sys.argv[1:])
