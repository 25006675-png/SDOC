"""Operational analytics distinguish model disagreement from provider failure."""
import unittest

from sdoc.analytics import build_metrics


class TestAnalytics(unittest.TestCase):
    def test_verifier_outcomes_are_separate(self):
        comparisons = [
            {"evidence_json": {"verification": {"status": "AGREED"}}},
            {"evidence_json": {"verification": {"status": "DISAGREED"}}},
            {"evidence_json": {"verification": {"status": "FAILED"}}},
        ]
        metrics = build_metrics([], [], [], comparisons, 0, now=100)
        self.assertEqual(metrics["verifier_checks"], 3)
        self.assertEqual(metrics["verifier_disagreements"], 1)
        self.assertEqual(metrics["verifier_failures"], 1)
        self.assertEqual(metrics["verifier_agreement_rate"], 0.5)

    def test_classification_review_messages_are_counted(self):
        routed = [
            {"category": "GENERAL", "payload_json": {
                "classification": {"classification_status": "needs_review"}
            }},
            {"category": "GENERAL", "payload_json": {
                "classification": {"classification_status": "resolved"}
            }},
        ]
        metrics = build_metrics([], routed, [], [], 0, now=100)
        self.assertEqual(metrics["classification_review_messages"], 1)


if __name__ == "__main__":
    unittest.main()


class TestExtractionStatusMetrics(unittest.TestCase):
    """v2 §7.3 statuses reach §12.3's first-pass and recovery rates."""

    def _metrics(self, *statuses):
        comparisons = [
            {"defect_fields": [], "evidence": {"validation": {
                "si": {"status": si}, "bl": {"status": bl}}}}
            for si, bl in statuses
        ]
        return build_metrics([], [], [], comparisons, 0, 0)

    def test_reads_are_counted_per_document_not_per_case(self):
        metrics = self._metrics(("FIRST_PASS_VALIDATED", "FIRST_PASS_VALIDATED"))
        self.assertEqual(metrics["extraction_reads"], 2)

    def test_first_pass_and_recovery_rates(self):
        metrics = self._metrics(
            ("FIRST_PASS_VALIDATED", "FIRST_PASS_VALIDATED"),
            ("RECOVERED", "NEEDS_REVIEW"),
        )
        self.assertEqual(metrics["extraction_statuses"], {
            "FIRST_PASS_VALIDATED": 2, "RECOVERED": 1, "NEEDS_REVIEW": 1})
        self.assertEqual(metrics["first_pass_validated_rate"], 0.5)
        self.assertEqual(metrics["recovered_rate"], 0.25)

    def test_absent_validation_evidence_is_not_counted(self):
        metrics = build_metrics([], [], [], [{"defect_fields": []}], 0, 0)
        self.assertEqual(metrics["extraction_reads"], 0)
        self.assertEqual(metrics["first_pass_validated_rate"], 0.0)
