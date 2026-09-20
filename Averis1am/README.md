# SDOC — Shipping Document Verification

Reads a shipping-operations inbox and, for each email, decides what it is and
what to do with it:

| category        | action                                                        |
|-----------------|---------------------------------------------------------------|
| `BL_COMPARISON` | read SI + draft-BL attachments, compare 7 shipment fields     |
| `SI_REQUEST`    | classify only                                                 |
| `INVOICE_QUERY` | classify only                                                 |
| `GENERAL`       | classify only                                                 |
| `SPAM`          | classify only                                                 |

Comparison outcomes: `OK` (all fields agree), `MISMATCH` (with
`defect_fields`), or `NEEDS_REVIEW` (with `review_reason`:
`wrong_doc_type` | `missing_attachment` | `unreadable` | `missing_value`).

Compared fields: **shipper, consignee, notify_party, port_of_loading,
port_of_discharge, container_count, gross_weight_kg** — aligned by meaning,
not header text ("Load Port" ≡ "Port of Loading").

## Usage

```bash
# static bundle (folder with inbox/ + attachments/)
python pipeline.py sdoc-hackathon-bundle -o submission.json

# the docker server — same pipeline over HTTP, then self-score
python pipeline.py http://localhost:8080 -o submission.json --submit

# full audit trail
python pipeline.py sdoc-hackathon-bundle -o submission.json \
    --report report.json --html report.html --csv results.csv

# options for messier/real-world data
python pipeline.py data --fuzzy 0.95      # tolerate typos in string fields
python pipeline.py data --ocr             # OCR scanned PDFs/images (needs tesseract)
python pipeline.py data --config rules.json
python pipeline.py data --workers 8       # parallel document parsing
python pipeline.py data --db audit.db     # append run to SQLite audit trail
python pipeline.py data --llm-endpoint http://localhost:11434 --llm-model qwen2.5
python pipeline.py data --emails email_004,email_407   # subset (debugging)
```

### `--config rules.json`

```json
{
  "labels":      {"consignee": ["Ship To", "Deliver To"]},
  "spam_domains": ["new-scam.example"],
  "si_body":      ["BOOKING CONFIRMATION"],
  "fields": {
    "vessel": {"kind": "text", "labels": ["Vessel", "Vessel/VOY"]},
    "marks":  ["Marks and Numbers", "Shipping Marks"]
  },
  "tolerances":  {"gross_weight_kg": 0.005}
}
```

- `fields` adds **new compared fields** — `kind` is one of
  `party | port | count | weight | text` and drives normalization;
  `labels` merge into the synonym map. Shorthand `"marks": [labels]` works.
- `tolerances` gives numeric kinds a relative tolerance (`0.005` = within
  0.5% — covers VGM-vs-gross-weight rounding).
- Classifier keys: `spam_domains`, `general_senders`, `spam_subj`,
  `general_subj`, `invoice_subj`, `invoice_body`, `si_body`, `bl_body`.

Score locally with the organizer's CLI:

```bash
python sdoc-hackathon-docker/server/score_cli.py submission.json
```

Current result on the v2 dataset: **final score 1.0000** — 100% classification
macro-F1, 46/46 defects caught end-to-end, 20/20 review cases escalated with
zero false escalations.

## Architecture (`sdoc/` package)

| module        | responsibility                                                        |
|---------------|-----------------------------------------------------------------------|
| `schema.py`   | canonical fields, label-synonym map, value normalisation (units, codes) |
| `readers.py`  | per-format document readers + extension registry + OCR hooks          |
| `docs.py`     | document typing (SI/BL/OTHER), field extraction, SI/BL pair identity  |
| `classify.py` | email category rules (sender/subject/body/attachments)                |
| `compare.py`  | field diff + per-field evidence (si/bl/match/similarity)              |
| `sources.py`  | `DirSource` (bundle folder) / `HttpSource` (docker server)            |
| `core.py`     | orchestration; per-email isolation — a crash = one NEEDS_REVIEW       |
| `llm.py`      | optional LLM fallback extractor for unreadable docs (pluggable)       |
| `audit.py`    | SQLite audit trail: runs, per-email results, human corrections        |
| `report.py`   | JSON report, HTML discrepancy report, CSV export, review queue        |
| `cli.py`      | argparse front end (also `pipeline.py` at the repo root)              |

## Multilingual support

The pipeline is Unicode-aware end to end:

- **Labels** — normalization is script-agnostic (NFKC + Unicode word chars),
  and `RAW_LABELS` carries synonyms in English, 中文 （发货人/收货人/装货港/卸货港/
  箱数/毛重…), French, German, Spanish and Bahasa. Bilingual labels like
  `Shipper (发货人)` resolve through either half. Add more languages via
  `--config` `labels`.
- **Values** — party/port names in any script compare correctly; full-width
  digits/punctuation normalize to ASCII (`２４３,５８８ KG` → `243,588 KG`).
- **Encodings** — `.txt` readers try utf-8 → gb18030 → big5 → latin-1.
- **Doc typing** — SI/BL/OTHER titles recognised in English and Chinese
  （装货指示/托运指示 → SI, 提单 → BL, 商业发票/装箱单/原产地证 → OTHER).
- **Emails** — CJK keywords for invoice （发票）, SI （装货指示） and BL
  （提单， plus a compare-intent pattern like 核对…提单）. Blank tokens cover
  待定/待确认/未定/无.

Caveat: label coverage is only as broad as the synonym tables — a language not
represented there will escalate as `missing_value` (safe failure) rather than
guess. Extend via `RAW_LABELS` or `--config` as new languages appear.

## Future-proofing / extension points

- **New file format** → `sdoc.readers.register_reader('.ext', fn)` where
  `fn(bytes, cfg) -> (title, [(label, value), ...]) or None`.
- **New compared field** → `--config fields` (above) — kind drives
  normalization, labels drive extraction; no code change.
- **Unparseable docs** → an LLM extractor gets one chance to rescue what the
  rule readers can't (it can only improve on `unreadable`, never regress).
  Built-in client for OpenAI-compatible endpoints via `--llm-endpoint`, or
  plug any callable: `sdoc.llm.register_llm_extractor(fn)` /
  `cfg["llm_extractor"]` where `fn(bytes, filename) -> (title, pairs)|None`.
- **Real mailbox files** → `DirSource` reads `inbox/*.eml` (MIME) as well as
  `.json`: From/Subject/body (plain or HTML-stripped), MIME attachments
  exposed as `attachments/<eml-stem>/<filename>`.
- **New label spelling** → add to `RAW_LABELS` in `schema.py`, or ship a
  `--config` JSON: `{"labels": {"consignee": ["Ship To", "Deliver To"]}}`.
- **New classifier signals** → `--config` keys: `spam_domains`,
  `general_senders`, `spam_subj`, `general_subj`, `invoice_subj`,
  `invoice_body`, `si_body`, `bl_body` (all extend the built-ins).
- **Odd filename conventions** → `identify_pair()` falls back to content-based
  doc typing when `_SI`/`_BL` suffixes are absent.
- **Scanned docs** → `--ocr` renders image-only PDFs via pypdfium2 and OCRs
  with tesseract (if installed); otherwise escalates as `unreadable`.
- **Typos/messy data** → `--fuzzy T` lets text fields match on similarity;
  every comparison records its similarity score in the evidence report.
- **Numeric noise** → `--config tolerances` (relative, per field).
- **Weight units** → `MT`/`TONNE`/`LB` are converted to kg before comparison.
- **Throughput** → `--workers N` parallelises parsing across threads;
  results stay in deterministic order.
- **Failure visibility** → every email is processed in isolation; unexpected
  errors become `NEEDS_REVIEW` + an `error` entry in the report, never a crash.

## Human-in-the-loop

`report.json` carries a `review_queue`: every NEEDS_REVIEW email with its
reason, detected doc types, missing fields, and any error — the context a
person needs to confirm or correct the case. `report.html` renders the same
information plus side-by-side SI/BL field tables with **character-level diffs**
(`<mark>` shows exactly what changed inside a mismatched value), and the
review queue is **sorted by decision confidence** so the riskiest calls
surface first. `--db audit.db` persists every run (per-email results +
evidence) in SQLite; `sdoc.audit.record_correction()` stores reviewer
overrides for audit and future synonym learning.

## Tests

```bash
python -m unittest tests.test_sdoc -v
```

## Local product workflow

The evaluator pipeline remains stateless. `sdoc.casework` adds persistent
shipment cases around it without changing the organizer submission contract:

- stable grouping by shipment reference;
- idempotent email ingestion;
- SI/BL document lineage and active-version selection;
- `VERIFIED`, `DISCREPANCY`, `NEEDS_REVIEW`, `WAITING`, and `BLOCKED` states;
- review tasks, waiting timeouts, human resolutions, and audit events;
- SQLite locally or Supabase through the same service boundary.

Generate and validate the derived advanced-stage PDF set:

```bash
python scripts/generate_demo_data.py demo-data
python scripts/validate_demo_data.py demo-data --db data/sdoc.db
```

The set contains clean, unit-normalized, discrepancy, scanned/OCR, revised-BL,
missing-value, and missing-document cases. It is derived from organizer
`email_405`; it does not modify the official bundle.

Ingest any local source through the persistent workflow:

```bash
python scripts/ingest_source.py                 # official bundle from .env
python scripts/ingest_source.py demo-data --ocr
python scripts/ingest_source.py demo-data --ocr --verify
```

`--verify` performs a second independent Gemini read of each valid SI and BL.
Pass 2 never sees Pass 1's answer. Normalized disagreement becomes
`NEEDS_REVIEW / verifier_disagreement`; provider or parsing failure becomes
`NEEDS_REVIEW / verifier_failed`.

## Backend API

Start the local API after loading the demo data:

```bash
python run_api.py
```

OpenAPI documentation is available at `http://127.0.0.1:8001/docs`.

The worker workspace is at `http://127.0.0.1:8001/app/`; its Admin metrics
view is linked in the sidebar. The UI opens the highest-priority case, shows
side-by-side field evidence and document lineage, records review resolutions,
and prepares review-only external message drafts. It does not send email.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Process and repository health |
| `GET /api/metrics` | Case, route, and open-review counts |
| `GET /api/cases?state=DISCREPANCY` | Worker case queue |
| `GET /api/cases/{case_id}` | Evidence, documents, versions, tasks, and audit history |
| `GET /api/cases/{case_id}/draft` | Prepare a correction, missing-document, or confirmation draft without sending |
| `POST /api/cases/mark-overdue` | Promote stale waiting cases to blocked |
| `POST /api/review-tasks/{task_id}/resolve` | Record a human review resolution |

The backend periodically marks overdue cases using `SDOC_WAIT_SECONDS` and
`SDOC_TIMER_INTERVAL`. No mailbox connection is required.

### Supabase

1. Review and apply
   `supabase/migrations/20260920_001_sdoc_casework.sql` in Supabase SQL Editor
   or through the Supabase CLI.
2. Keep `SUPABASE_SECRET_KEY` on the server only.
3. Set `SDOC_STORE=supabase` and start `python run_api.py`.

Row-level security is enabled without browser policies. The migration grants
the ingestion and review RPC functions only to `service_role`; the landing
page never receives the secret key.
