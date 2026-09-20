# SDOC — Evidence-driven Shipping Document Verification

A polished, responsive, dependency-free landing page concept for the Averis × Monash Hackathon. Designed around SDOC's proposal: inbox-native classification, SI/BL seven-field extraction and comparison, source evidence, deterministic business rules, and human review.

## Run

Open `index.html` in any modern browser. No Node, package installation, environment variables, or build step needed.

For a local HTTP development server, run `python3 -m http.server 8000` from this folder and visit `http://localhost:8000`.

## Files

- `index.html`: semantic page sections and product preview markup
- `styles.css`: responsive design, interface components, CSS illustrations, and motion
- `app.js`: accessible demo scenario switcher, source evidence dialog, mobile menu, and scroll reveal
- `assets/favicon.svg`: SDOC favicon

## Product preview

The preview has three clickable scenarios: Discrepancy, Verified, and Needs review. Each updates the seven-field comparison table and the Source Evidence dialog. All shipping data, case IDs, document names, and status values are *illustrative*, not output from a connected mailbox or a working document-extraction backend. The landing page does **not** process real documents or send email.

## Integrating a real SDOC engine later

Keep the site as the marketing surface and replace the `scenarios` dataset in `app.js` with API-driven results. The backend should return field-level evidence, explicit result states, and reviewer actions. See the accompanying proposal for design rationale.

## Design notes

- Keyboard-operated scenario tabs and dismissible native modal
- `prefers-reduced-motion` support
- Mobile layout down to narrow phones
- No external JS libraries or runtime dependencies. Google Fonts are optional: system fallbacks work offline.
