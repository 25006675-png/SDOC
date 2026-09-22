"""Deterministic validation and the single bounded recovery cycle (v2 §7.2-7.4)."""
import unittest

from sdoc.core import prepare_cfg
from sdoc.validation import (
    FIRST_PASS_VALIDATED,
    NEEDS_REVIEW,
    RECOVERED,
    read_with_recovery,
    validate_extraction,
)

COMPLETE = [
    ("Shipper", "APRIL FAR EAST (M) SDN BHD"),
    ("Consignee", "EAST BRIGHT FZ-LLC"),
    ("Notify", "EAST BRIGHT FZ-LLC"),
    ("POL", "NANTONG, CHINA (CNNTG)"),
    ("POD", "KARACHI, PAKISTAN (PKKHI)"),
    ("Total Containers", "6 x 40'HC"),
    ("Gross Wt (kgs)", "131,058 KG"),
]
INCOMPLETE = COMPLETE[:-1]


class _Source:
    def read_bytes(self, path):
        return b"raw-document-bytes"


class _Extractor:
    """Records what the recovery cycle fed back to it."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, data, filename, problems=None):
        self.calls.append(problems)
        return self.result


class TestValidateExtraction(unittest.TestCase):
    def test_complete_extraction_has_no_problems(self):
        self.assertEqual(validate_extraction(COMPLETE), {})

    def test_absent_field_is_missing(self):
        self.assertEqual(validate_extraction(INCOMPLETE),
                         {"gross_weight_kg": "missing"})

    def test_unparseable_value_is_caught(self):
        pairs = INCOMPLETE + [("Gross Wt (kgs)", "not a weight")]
        self.assertEqual(validate_extraction(pairs),
                         {"gross_weight_kg": "unparseable"})

    def test_validation_checks_structure_not_truth(self):
        # A well-formed but wrong value passes by design; the independent
        # verifier is what catches it.
        wrong = COMPLETE[:-1] + [("Gross Wt (kgs)", "999,999 KG")]
        self.assertEqual(validate_extraction(wrong), {})


class TestRecoveryCycle(unittest.TestCase):
    def setUp(self):
        self.cfg = prepare_cfg({})
        self.source = _Source()

    def test_complete_first_read_is_first_pass_validated(self):
        doc, status, trace = read_with_recovery(
            self.source, "si.txt", self.cfg, doc=("SI", COMPLETE))
        self.assertEqual(status, FIRST_PASS_VALIDATED)
        self.assertEqual(trace["routes"], [])

    def test_successful_retry_is_recovered(self):
        extractor = _Extractor(("SI", COMPLETE))
        cfg = dict(self.cfg, llm_extractor=extractor)
        doc, status, trace = read_with_recovery(
            self.source, "si.txt", cfg, doc=("SI", INCOMPLETE))
        self.assertEqual(status, RECOVERED)
        self.assertEqual(trace["routes"], ["llm"])
        self.assertEqual(doc[1], COMPLETE)

    def test_retry_receives_the_validation_failures(self):
        extractor = _Extractor(("SI", COMPLETE))
        cfg = dict(self.cfg, llm_extractor=extractor)
        read_with_recovery(self.source, "si.txt", cfg,
                           doc=("SI", INCOMPLETE))
        self.assertEqual(extractor.calls, [{"gross_weight_kg": "missing"}])

    def test_recovery_runs_at_most_once(self):
        extractor = _Extractor(("SI", INCOMPLETE))
        cfg = dict(self.cfg, llm_extractor=extractor)
        doc, status, trace = read_with_recovery(
            self.source, "si.txt", cfg, doc=("SI", INCOMPLETE))
        self.assertEqual(status, NEEDS_REVIEW)
        self.assertEqual(len(extractor.calls), 1)
        self.assertEqual(trace["retry_problems"], {"gross_weight_kg": "missing"})

    def test_no_recovery_route_still_needs_review(self):
        doc, status, trace = read_with_recovery(
            self.source, "si.txt", self.cfg, doc=("SI", INCOMPLETE))
        self.assertEqual(status, NEEDS_REVIEW)
        self.assertEqual(trace["routes"], [])
        self.assertEqual(doc[1], INCOMPLETE)

    def test_unreadable_document_needs_review(self):
        class Dead:
            def read_bytes(self, path):
                raise OSError("gone")

        doc, status, trace = read_with_recovery(Dead(), "si.txt", self.cfg)
        self.assertIsNone(doc)
        self.assertEqual(status, NEEDS_REVIEW)
        self.assertEqual(trace["reason"], "unreadable")

    def test_partial_improvement_keeps_the_better_read(self):
        worse = COMPLETE[:4]                       # three fields short
        extractor = _Extractor(("SI", COMPLETE[:6]))   # one field short
        cfg = dict(self.cfg, llm_extractor=extractor)
        doc, status, trace = read_with_recovery(
            self.source, "si.txt", cfg, doc=("SI", worse))
        self.assertEqual(status, NEEDS_REVIEW)
        self.assertEqual(doc[1], COMPLETE[:6])
        self.assertLess(len(trace["retry_problems"]),
                        len(trace["first_pass_problems"]))


if __name__ == "__main__":
    unittest.main()
