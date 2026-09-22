"""Review-only external message draft tests."""
import unittest

from sdoc.drafting import draft_case_message


class TestDrafting(unittest.TestCase):
    def test_discrepancy_uses_source_values(self):
        draft = draft_case_message({
            "shipment_reference": "9ABC-10001",
            "state": "DISCREPANCY",
            "comparisons": [{
                "defect_fields": ["gross_weight_kg"],
                "evidence": {"fields": {"gross_weight_kg": {
                    "si": "10,000 KG", "bl": "11,000 KG", "match": False,
                }}},
            }],
        })
        self.assertEqual(draft["kind"], "CORRECTION_REQUEST")
        self.assertIn('SI "10,000 KG"', draft["body"])
        self.assertFalse(draft["send_allowed"])

    def test_waiting_requests_missing_role(self):
        draft = draft_case_message({
            "shipment_reference": "9ABC-10002", "state": "WAITING",
            "documents": [{"role": "SI"}],
        })
        self.assertIn("draft bill of lading", draft["body"])

    def test_verified_confirmation_and_review_guard(self):
        draft = draft_case_message({"shipment_reference": "9ABC-10003", "state": "VERIFIED"})
        self.assertEqual(draft["kind"], "VERIFICATION_CONFIRMATION")
        with self.assertRaises(ValueError):
            draft_case_message({"shipment_reference": "9ABC-10004", "state": "NEEDS_REVIEW"})


if __name__ == "__main__":
    unittest.main()
