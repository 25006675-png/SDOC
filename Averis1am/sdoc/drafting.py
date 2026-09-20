"""Deterministic, review-only message drafting for shipment cases."""
from __future__ import annotations


FIELD_LABELS = {
    "shipper": "Shipper",
    "consignee": "Consignee",
    "notify_party": "Notify party",
    "port_of_loading": "Port of loading",
    "port_of_discharge": "Port of discharge",
    "container_count": "Container count",
    "gross_weight_kg": "Gross weight",
}


def _latest_comparison(case):
    comparisons = case.get("comparisons") or []
    return comparisons[-1] if comparisons else {}


def _evidence(comparison):
    return comparison.get("evidence") or comparison.get("evidence_json") or {}


def _document_roles(case):
    roles = set()
    for document in case.get("documents") or []:
        if document.get("role"):
            roles.add(document["role"])
    return roles


def draft_case_message(case):
    """Return a draft that must be reviewed; this function never sends mail."""
    reference = case["shipment_reference"]
    state = case["state"]
    greeting = "Hello,\n\n"
    signoff = "\n\nPlease review and advise.\n\nRegards,\nShipping Operations"

    if state == "DISCREPANCY":
        comparison = _latest_comparison(case)
        fields = _evidence(comparison).get("fields", {})
        defects = comparison.get("defect_fields") or [
            name for name, values in fields.items() if values.get("match") is False
        ]
        lines = []
        for field in defects:
            values = fields.get(field, {})
            label = FIELD_LABELS.get(field, field.replace("_", " ").title())
            lines.append(
                f'- {label}: SI "{values.get("si", "not available")}"; '
                f'draft BL "{values.get("bl", "not available")}"'
            )
        details = "\n".join(lines) or "- A verified SI / draft BL difference was recorded."
        return {
            "kind": "CORRECTION_REQUEST",
            "subject": f"Correction required for draft BL – {reference}",
            "body": greeting + f"We identified the following verified difference(s) for shipment {reference}:\n\n{details}"
            + "\n\nPlease issue a corrected draft bill of lading." + signoff,
            "send_allowed": False,
        }

    if state in {"WAITING", "BLOCKED"}:
        missing = [role for role in ("SI", "BL") if role not in _document_roles(case)]
        names = {"SI": "shipping instruction", "BL": "draft bill of lading"}
        requested = " and ".join(names[role] for role in missing) if missing else "required readable document"
        return {
            "kind": "MISSING_DOCUMENT_REQUEST",
            "subject": f"Document required – {reference}",
            "body": greeting + f"We are unable to complete verification for shipment {reference}. "
            f"Please provide the {requested}." + signoff,
            "send_allowed": False,
        }

    if state == "VERIFIED":
        return {
            "kind": "VERIFICATION_CONFIRMATION",
            "subject": f"Draft BL verification complete – {reference}",
            "body": greeting + f"The shipping instruction and draft bill of lading for shipment {reference} "
            "have been verified across all seven required fields, with no discrepancy found." + signoff,
            "send_allowed": False,
        }

    raise ValueError("human verification is required before preparing an external message")
