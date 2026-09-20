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
