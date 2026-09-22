# SDOC live demo kit (batch 0)

Six scenarios. Each folder holds the documents to attach and the email text to send.
Shipment references in this batch: 5PKG-93101 to 5PKG-93103.

## Before you present

1. **Use a fresh batch for every run-through.** A reference that already has a case joins that case. Rehearse with `--batch 2`, `--batch 3`, and present with a batch you have never sent:
   `python backend/scripts/generate_demo_kit.py --batch 4 --check`
2. **Send to one mailbox only** (the default Outlook mailbox). Sending to both creates duplicates.
3. **No signature images.** Outlook passes signature logos through as attachments, and an extra image breaks the SI + BL pair. Send plain emails.
4. **Attach the files as ordinary attachments**, not as links or inline images.
5. **Keep the subjects exactly as written.** Words like 'invoice', 'freight', 'THC' or 'reminder' in the subject route an email away from comparison.
6. After sending, press **Sync now** (or wait up to a minute). Each comparison makes two Gemini reads, so allow 10 to 30 seconds per email.
7. For two-email scenarios, wait until the first result is on screen before sending the second.

**If the mailbox fails on the day**, load the same scenarios without email. Use a batch you have not sent, or these cases join the live ones. From the repository root:

```powershell
Copy-Item -Recurse -Force demo-kit/_offline/attachments/* backend/data/attachments/
cd backend; python scripts/ingest_source.py ../demo-kit/_offline --verify
```

The copy step lets the evidence pane render the pages; without it the crops show 'page could not be rendered'.

## Scenarios

### 1. Case 1 - Verified - `case-1-verified/`

**Result:** VERIFIED: 7/7 fields matched

SI and draft BL agree on every field. The normal path.

**Send:** `email.txt`

**Show:**
- Incoming email, identified as a comparison request.
- SI + BL linked into one shipment case.
- 7 fields, 7/7 matched, source evidence for each.

**Say:** "What you just saw is the normal path."

### 2. Case 2 - Discrepancy - `case-2-discrepancy/`

**Result:** DISCREPANCY on container count only: SI 3 x 40HC, BL 4

The SI says three containers, the draft BL says four. Everything else matches.

**Send:** `email.txt`

**Show:**
- Container count is the only highlighted row: SI 3 x 40HC, BL 4.
- View source: both values boxed on their pages.

**Say:** "SDOC doesn't just produce a red warning. It shows where both values came from."

### 3. Case 3 - Blocked, then resume - `case-3-blocked-then-resume/`

**Result:** BLOCKED (draft BL password-protected), then VERIFIED on the same case once a usable copy arrives

The carrier's draft BL is password-protected, so SDOC cannot use it. It blocks the case and asks for the document. The carrier resends an unprotected copy and the same case resumes.

**Send:** `email-1.txt` (BLOCKED) then `email-2.txt` (VERIFIED)

**Show:**
- After email 1: Blocked, next action is to obtain the required document.
- After email 2 (optional): the same case turns Verified.

**Say:** "Blocked does not mean failed. It means a prerequisite is missing or unusable."

## Honest limits (for questions)

- Container **count** is compared, container **type** is not: '2 x 40'HC' and '2 x 20'GP' match. Type can be added as a configured field.
- Each email is compared on its own attachments. A draft BL sent alone after an SI-only email keeps the case Waiting, which is why scenario 4's second email carries both files.
- The Gemini second read accepts PDFs and images, so the SI and BL must be PDFs for a live result. Word and Excel files are read as supporting documents.
- SDOC drafts messages but never sends them. A person reviews and sends.
- All companies, vessels and values in this kit are fictitious.
