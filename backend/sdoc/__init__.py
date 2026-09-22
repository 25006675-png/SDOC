"""SDOC — shipping document verification pipeline.

Package layout:
    schema.py    field schema, label synonyms, value normalisation
    readers.py   attachment readers (.txt/.pdf/.docx/.xlsx/images) + registry
    docs.py      document typing, field extraction, SI/BL pairing
    classify.py  email categorisation rules
    compare.py   SI-vs-BL field comparison + evidence
    sources.py   data sources: local bundle dir or the HTTP server
    report.py    JSON/HTML/CSV reporting
    core.py      per-email pipeline orchestration
    llm.py       optional LLM fallback extractor for unreadable docs
    audit.py     SQLite audit trail for runs + human corrections
    cli.py       command-line entry point
"""

__version__ = "2.2.0"
