#!/usr/bin/env python3
"""Generate deterministic advanced-stage demo documents.

The shipment values are derived from organizer case email_405. The generated
files live outside the official bundle so benchmark inputs remain untouched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


BASE = {
    "Shipper": "APRIL FINE PAPER TRADING",
    "Consignee": "HABRAS INTERNATIONAL LIMITED",
    "Notify Party": "HABRAS INTERNATIONAL LIMITED",
    "Port of Loading": "NHAVA SHEVA, INDIA (INNSA)",
    "Port of Discharge": "LONG BEACH, US (USLGB)",
    "Container Count": "4 x 20'FCL",
    "Gross Weight": "82,932 KG",
}


def write_pdf(path, kind, fields):
    title = "SHIPPING INSTRUCTION" if kind == "SI" else "BILL OF LADING (DRAFT)"
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    pdf.setTitle(title)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(54, height - 64, title)
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(width - 54, height - 62, "DERIVED DEMO DOCUMENT")
    y = height - 118
    for label, value in fields.items():
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(54, y, label)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(205, y, str(value))
        pdf.line(54, y - 7, width - 54, y - 7)
        y -= 46
    pdf.setFont("Helvetica", 8)
    pdf.drawString(54, 44, "Derived from organizer sample email_405 for controlled validation.")
    pdf.save()


def _font(name, size):
    candidates = [
        Path("C:/Windows/Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu") / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def write_scanned_pdf(path, kind, fields):
    title = "SHIPPING INSTRUCTION" if kind == "SI" else "BILL OF LADING (DRAFT)"
    page = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(page)
    title_font = _font("arialbd.ttf", 48)
    body_font = _font("arial.ttf", 30)
    draw.text((130, 130), title, fill="#111111", font=title_font)
    y = 280
    for label, value in fields.items():
        draw.text((130, y), f"{label}: {value}", fill="#111111", font=body_font)
        y += 120
    draw.text(
        (130, 2020),
        "DERIVED DEMO SCAN / SOURCE EMAIL 405",
        fill="#444444",
        font=body_font,
    )
    page.save(path, "PDF", resolution=150.0)


def email_record(email_id, reference, attachments, note):
    return {
        "email_id": email_id,
        "from": "shipping.documentation@example.com",
        "subject": f"Document verification / {reference}",
        "body": f"Please compare the SI and draft BL for {reference}. {note}",
        "attachments": [f"attachments/{name}" for name in attachments],
    }


def generate(root):
    root = Path(root)
    inbox = root / "inbox"
    attachments = root / "attachments"
    inbox.mkdir(parents=True, exist_ok=True)
    attachments.mkdir(parents=True, exist_ok=True)
    cases = []

    def add(email_id, reference, si_fields, bl_fields, expected, *, scan=False,
            si_name=None, bl_name=None, note=""):
        si_name = si_name or f"{email_id}_SI.pdf"
        bl_name = bl_name or f"{email_id}_BL.pdf"
        writer = write_scanned_pdf if scan else write_pdf
        writer(attachments / si_name, "SI", si_fields)
        writer(attachments / bl_name, "BL", bl_fields)
        message = email_record(email_id, reference, [si_name, bl_name], note)
        (inbox / f"{email_id}.json").write_text(
            json.dumps(message, indent=2), encoding="utf-8"
        )
        cases.append({
            "email_id": email_id,
            "shipment_reference": reference,
            "expected_status": expected[0],
            "expected_review_reason": expected[1],
            "expected_defect_fields": expected[2],
        })

    add("demo_001", "9DMO-10001", BASE, BASE, ("OK", None, []), note="Clean pair.")

    si_units = dict(BASE, **{"Gross Weight": "82.932 MT"})
    add("demo_002", "9DMO-10002", si_units, BASE, ("OK", None, []),
        note="Equivalent weight units.")

    bl_mismatch = dict(BASE, **{"Container Count": "5 x 20'FCL"})
    add("demo_003", "9DMO-10003", BASE, bl_mismatch,
        ("MISMATCH", None, ["container_count"]), note="Container mismatch.")

    add("demo_004", "9DMO-10004", BASE, BASE, ("OK", None, []), scan=True,
        note="Image-only scanned PDFs.")

    add(
        "demo_005a", "9DMO-10005", BASE, bl_mismatch,
        ("MISMATCH", None, ["container_count"]),
        si_name="demo_005a_SI.pdf", bl_name="demo_005a_v1_BL.pdf",
        note="Initial draft version.",
    )
    add(
        "demo_005b", "9DMO-10005", BASE, BASE, ("OK", None, []),
        si_name="demo_005b_SI.pdf", bl_name="demo_005b_v2_BL.pdf",
        note="Corrected draft version.",
    )

    si_ambiguous = dict(BASE)
    si_ambiguous.pop("Gross Weight")
    add("demo_006", "9DMO-10006", si_ambiguous, BASE,
        ("NEEDS_REVIEW", "missing_value", []), note="Required value absent.")

    missing_si_name = "demo_007_SI.pdf"
    write_pdf(attachments / missing_si_name, "SI", BASE)
    missing = email_record(
        "demo_007", "9DMO-10007", [missing_si_name], "Draft BL is missing."
    )
    (inbox / "demo_007.json").write_text(json.dumps(missing, indent=2), encoding="utf-8")
    cases.append({
        "email_id": "demo_007",
        "shipment_reference": "9DMO-10007",
        "expected_status": "NEEDS_REVIEW",
        "expected_review_reason": "missing_attachment",
        "expected_defect_fields": [],
    })

    manifest = {
        "name": "SDOC derived advanced validation set",
        "source": "Organizer bundle email_405 values",
        "official_dataset_modified": False,
        "cases": cases,
        "expected_final_states": {
            "9DMO-10001": "VERIFIED",
            "9DMO-10002": "VERIFIED",
            "9DMO-10003": "DISCREPANCY",
            "9DMO-10004": "VERIFIED",
            "9DMO-10005": "VERIFIED",
            "9DMO-10006": "NEEDS_REVIEW",
            "9DMO-10007": "WAITING",
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {len(cases)} email records in {root}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="demo-data")
    generate(parser.parse_args().output)
