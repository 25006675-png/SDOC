"""Correct Extraction: the human action of v2 §9.

A worker replaces a wrongly extracted value; the correction keeps before/after
evidence and the case is re-decided by the same comparison rules that produced
the original result.
"""
import unittest

from sdoc.casework import CaseStore


def _fields(si_count="6", bl_count="7"):
    """Seven-field evidence where container_count is the only difference."""
    same = {
        "shipper": "APRIL FAR EAST",
        "consignee": "EAST BRIGHT FZ-LLC",
        "notify_party": "EAST BRIGHT FZ-LLC",
        "port_of_loading": "NANTONG, CHINA",
        "port_of_discharge": "KARACHI, PAKISTAN",
        "gross_weight_kg": "131,058 KG",
    }
    fields = {
        f: {"si": v, "bl": v, "si_norm": v, "bl_norm": v, "match": True, "sim": 1.0}
        for f, v in same.items()
    }
    fields["container_count"] = {
        "si": si_count, "bl": bl_count, "match": False, "sim": 0.0,
        "si_source": {"page": 1, "source_text": f"Total Containers: {si_count}"},
        "bl_source": {"page": 1, "source_text": f"Total Containers: {bl_count}"},
    }
    return fields


def _email(email_id="e1"):
    return {
        "email_id": email_id,
        "from": "ops@example.com",
        "subject": "Draft check / SHIP-1",
        "body": "Please compare SHIP-1.",
        "attachments": ["attachments/SHIP-1_SI.pdf", "attachments/SHIP-1_BL.pdf"],
    }


def _record(status="MISMATCH", defects=("container_count",)):
    return {
        "category": "BL_COMPARISON",
        "status": status,
        "review_reason": None,
        "defect_fields": list(defects),
        "has_defect": status == "MISMATCH",
        "decided_by": "rule",
    }


class TestCorrectExtraction(unittest.TestCase):
    def setUp(self):
        self.store = CaseStore(":memory:")
        self.store.ingest_result(
            _email(), _record(),
            {"fields": _fields(), "si_doc": "attachments/SHIP-1_SI.pdf",
             "bl_doc": "attachments/SHIP-1_BL.pdf"},
        )
        self.case_id = self.store.list_cases()[0]["case_id"]

    def tearDown(self):
        self.store.close()

    def test_case_starts_as_a_discrepancy(self):
        case = self.store.get_case(self.case_id)
        self.assertEqual(case["state"], "DISCREPANCY")
        self.assertEqual(len(case["review_tasks"]), 1)

    def test_correcting_the_misread_value_clears_the_case(self):
        case = self.store.correct_field(
            self.case_id, "container_count", "bl", "6", "worker@example.com",
            "BL actually reads 6; extractor misread the table.",
        )
        self.assertEqual(case["state"], "VERIFIED")
        self.assertEqual(case["comparisons"][-1]["defect_fields"], [])

    def test_correction_keeps_before_and_after(self):
        self.store.correct_field(self.case_id, "container_count", "bl", "6",
                                 "worker@example.com", "misread")
        correction = self.store.get_case(self.case_id)["corrections"][0]
        self.assertEqual(correction["field"], "container_count")
        self.assertEqual(correction["side"], "bl")
        self.assertEqual(correction["old_value"], "7")
        self.assertEqual(correction["new_value"], "6")
        self.assertEqual(correction["actor"], "worker@example.com")

    def test_correction_is_marked_on_the_field_evidence(self):
        case = self.store.correct_field(self.case_id, "container_count", "bl",
                                        "6", "worker@example.com")
        marked = case["comparisons"][-1]["evidence"]["fields"]["container_count"]
        self.assertEqual(marked["corrected"]["from"], "7")
        self.assertEqual(marked["corrected"]["to"], "6")
        self.assertTrue(marked["match"])

    def test_correction_preserves_source_evidence(self):
        case = self.store.correct_field(self.case_id, "container_count", "si",
                                        "7", "worker@example.com")
        field = case["comparisons"][-1]["evidence"]["fields"]["container_count"]
        self.assertEqual(field["si_source"]["page"], 1)
        self.assertEqual(field["bl_source"]["page"], 1)

    def test_a_wrong_correction_can_still_leave_a_discrepancy(self):
        case = self.store.correct_field(self.case_id, "container_count", "bl",
                                        "9", "worker@example.com")
        self.assertEqual(case["state"], "DISCREPANCY")
        self.assertEqual(case["comparisons"][-1]["defect_fields"],
                         ["container_count"])

    def test_resolving_the_case_closes_its_review_task(self):
        self.store.correct_field(self.case_id, "container_count", "bl", "6",
                                 "worker@example.com")
        tasks = self.store.get_case(self.case_id)["review_tasks"]
        self.assertTrue(all(t["status"] != "OPEN" for t in tasks))

    def test_correction_is_audited(self):
        self.store.correct_field(self.case_id, "container_count", "bl", "6",
                                 "worker@example.com", "misread")
        events = [e for e in self.store.get_case(self.case_id)["audit_events"]
                  if e["event_type"] == "EXTRACTION_CORRECTED"]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["actor"], "worker@example.com")

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.correct_field(self.case_id, "not_a_field", "bl", "6",
                                     "worker@example.com")

    def test_unknown_side_is_rejected(self):
        with self.assertRaises(ValueError):
            self.store.correct_field(self.case_id, "container_count", "middle",
                                     "6", "worker@example.com")


if __name__ == "__main__":
    unittest.main()
