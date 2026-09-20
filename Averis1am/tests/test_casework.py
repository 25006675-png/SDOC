"""Operational shipment-case tests; separate from evaluator contract tests."""
import unittest

from sdoc.casework import (
    CaseStore,
    document_version,
    product_state,
    shipment_reference,
    stable_case_id,
)


def email(email_id, subject, attachments=None, body=""):
    return {
        "email_id": email_id,
        "from": "ops@example.com",
        "subject": subject,
        "body": body,
        "attachments": attachments or [],
    }


def record(status="OK", reason=None, defects=None, category="BL_COMPARISON"):
    return {
        "category": category,
        "status": status,
        "review_reason": reason,
        "defect_fields": defects or [],
        "has_defect": status == "MISMATCH",
        "decided_by": "rule",
    }


class TestCaseIdentity(unittest.TestCase):
    def test_reference_from_subject_then_fallback(self):
        self.assertEqual(
            shipment_reference(email("e1", "Draft check / 5AKR-57059")),
            "5AKR-57059",
        )
        self.assertEqual(
            shipment_reference(email(
                "e3",
                "TO CONFIRM DOCS _ GMAIL-STD-0001",
                ["attachments/GMAIL-STD-0001_Draft_BL.pdf"],
                "Please compare GMAIL-STD-0001.",
            )),
            "GMAIL-STD-0001",
        )
        self.assertEqual(shipment_reference(email("e2", "No reference")), "EMAIL:E2")
        self.assertEqual(stable_case_id("ABC"), stable_case_id("ABC"))

    def test_product_state_mapping(self):
        self.assertEqual(product_state(record()), "VERIFIED")
        self.assertEqual(product_state(record("MISMATCH")), "DISCREPANCY")
        self.assertEqual(
            product_state(record("NEEDS_REVIEW", "missing_attachment")), "WAITING"
        )
        self.assertEqual(
            product_state(record("NEEDS_REVIEW", "unreadable")), "NEEDS_REVIEW"
        )

    def test_document_version(self):
        self.assertEqual(document_version("Draft_BL_v2.pdf"), (2, "v2"))
        self.assertEqual(document_version("BL Revision 12.docx"), (12, "Revision 12"))
        self.assertEqual(document_version("email_004_BL.txt"), (None, None))


class TestCaseStore(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore(":memory:")

    def tearDown(self):
        self.store.close()

    def test_non_comparison_is_routed_without_creating_case(self):
        msg = email("e1", "Invoice question")
        result = self.store.ingest_result(
            msg, record(category="INVOICE_QUERY"), {}, now=100
        )
        self.assertIsNone(result)
        self.assertEqual(self.store.list_cases(), [])
        self.assertEqual(self.store.list_routed_messages()[0]["category"], "INVOICE_QUERY")

    def test_idempotent_case_and_document_versions(self):
        first = email(
            "e1",
            "Check 5AKR-57059",
            ["attachments/SI.pdf", "attachments/Draft_BL_v1.pdf"],
        )
        evidence1 = {
            "si_doc": "attachments/SI.pdf",
            "bl_doc": "attachments/Draft_BL_v1.pdf",
            "doc_kinds": {
                "attachments/SI.pdf": "SI",
                "attachments/Draft_BL_v1.pdf": "BL",
            },
        }
        case = self.store.ingest_result(first, record(), evidence1, now=100)
        duplicate = self.store.ingest_result(first, record(), evidence1, now=101)
        self.assertEqual(case["case_id"], duplicate["case_id"])
        self.assertEqual(len(duplicate["emails"]), 1)
        self.assertEqual(len(duplicate["documents"]), 2)

        revision = email(
            "e2", "Revised draft 5AKR-57059", ["attachments/Draft_BL_v2.pdf"]
        )
        evidence2 = {
            "bl_doc": "attachments/Draft_BL_v2.pdf",
            "doc_kinds": {"attachments/Draft_BL_v2.pdf": "BL"},
        }
        updated = self.store.ingest_result(revision, record(), evidence2, now=200)
        bl_versions = [d for d in updated["documents"] if d["role"] == "BL"]
        self.assertEqual([d["version_index"] for d in bl_versions], [1, 2])
        self.assertEqual([d["is_active"] for d in bl_versions], [0, 1])
        self.assertEqual(updated["state"], "VERIFIED")

    def test_missing_document_waits_then_blocks(self):
        msg = email("e1", "Please compare 5AKR-57059", ["attachments/SI.pdf"])
        case = self.store.ingest_result(
            msg,
            record("NEEDS_REVIEW", "missing_attachment"),
            {"doc_kinds": {"attachments/SI.pdf": "SI"}},
            now=100,
        )
        self.assertEqual(case["state"], "WAITING")
        self.assertEqual(case["review_tasks"], [])
        self.assertEqual(self.store.mark_overdue(60, now=159), [])

        blocked = self.store.mark_overdue(60, now=161)
        self.assertEqual(blocked, [case["case_id"]])
        case = self.store.get_case(case["case_id"])
        self.assertEqual(case["state"], "BLOCKED")
        self.assertEqual(case["review_tasks"][0]["kind"], "BLOCKED")
        self.assertEqual(case["review_tasks"][0]["reason"], "missing_document_timeout")

    def test_discrepancy_creates_and_resolves_review_task(self):
        msg = email(
            "e1",
            "Check 5AKR-57059",
            ["attachments/SI.pdf", "attachments/BL.pdf"],
        )
        evidence = {
            "si_doc": "attachments/SI.pdf",
            "bl_doc": "attachments/BL.pdf",
            "doc_kinds": {"attachments/SI.pdf": "SI", "attachments/BL.pdf": "BL"},
        }
        case = self.store.ingest_result(
            msg,
            record("MISMATCH", defects=["container_count"]),
            evidence,
            now=100,
        )
        self.assertEqual(case["state"], "DISCREPANCY")
        task = case["review_tasks"][0]
        self.assertEqual(task["status"], "OPEN")

        self.store.resolve_task(task["task_id"], "reviewer@example.com", "Confirmed", 110)
        case = self.store.get_case(case["case_id"])
        self.assertEqual(case["review_tasks"][0]["status"], "RESOLVED")
        self.assertEqual(case["audit_events"][-1]["actor"], "reviewer@example.com")

    def test_new_clean_result_cancels_stale_open_task(self):
        msg1 = email("e1", "Check 5AKR-57059")
        case = self.store.ingest_result(
            msg1, record("NEEDS_REVIEW", "unreadable"), {}, now=100
        )
        self.assertEqual(case["review_tasks"][0]["status"], "OPEN")
        msg2 = email("e2", "Retry 5AKR-57059")
        case = self.store.ingest_result(msg2, record(), {}, now=120)
        self.assertEqual(case["state"], "VERIFIED")
        self.assertEqual(case["review_tasks"][0]["status"], "CANCELLED")


if __name__ == "__main__":
    unittest.main()
