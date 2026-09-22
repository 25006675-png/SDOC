"""Spend ceilings (Addendum A3).

A per-case budget bounds one runaway document; these bound the horizontal
case, where many individually compliant messages add up to unbounded spend.
"""
import tempfile
import unittest
from pathlib import Path

from sdoc.budget import BudgetExceeded, SpendLedger


class TestSpendLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "ledger.json"

    def tearDown(self):
        self.tmp.cleanup()

    def ledger(self, per_sender=3, per_day=5):
        return SpendLedger(self.path, per_sender=per_sender, per_day=per_day)

    def test_a_fresh_ledger_allows_work(self):
        self.ledger().check("ops@example.com")      # does not raise

    def test_sender_ceiling_stops_one_sender(self):
        ledger = self.ledger(per_sender=2)
        for _ in range(2):
            ledger.check("spam@bad.example")
            ledger.record("spam@bad.example")
        with self.assertRaises(BudgetExceeded) as caught:
            ledger.check("spam@bad.example")
        self.assertIn("spam@bad.example", caught.exception.scope)

    def test_one_sender_does_not_consume_anothers_allowance(self):
        ledger = self.ledger(per_sender=2)
        for _ in range(2):
            ledger.record("spam@bad.example")
        ledger.check("ops@example.com")             # unaffected

    def test_global_ceiling_stops_a_distributed_flood(self):
        ledger = self.ledger(per_sender=100, per_day=3)
        for i in range(3):
            ledger.record(f"sender{i}@bad.example")
        with self.assertRaises(BudgetExceeded) as caught:
            ledger.check("sender9@bad.example")
        self.assertEqual(caught.exception.scope, "daily")

    def test_counts_survive_a_restart(self):
        self.ledger(per_sender=2).record("spam@bad.example")
        self.ledger(per_sender=2).record("spam@bad.example")
        with self.assertRaises(BudgetExceeded):
            self.ledger(per_sender=2).check("spam@bad.example")

    def test_a_new_day_resets_the_allowance(self):
        ledger = self.ledger(per_sender=1)
        ledger.record("spam@bad.example", now=1_700_000_000)
        with self.assertRaises(BudgetExceeded):
            ledger.check("spam@bad.example", now=1_700_000_000)
        ledger.check("spam@bad.example", now=1_700_000_000 + 86_400 * 2)

    def test_display_name_and_address_are_the_same_sender(self):
        ledger = self.ledger(per_sender=1)
        ledger.record("Ops Team <ops@example.com>")
        with self.assertRaises(BudgetExceeded):
            ledger.check("ops@example.com")

    def test_usage_reports_both_ceilings(self):
        ledger = self.ledger(per_sender=3, per_day=5)
        ledger.record("ops@example.com")
        usage = ledger.usage("ops@example.com")
        self.assertEqual(usage["total"], 1)
        self.assertEqual(usage["sender"], 1)
        self.assertEqual(usage["sender_limit"], 3)
        self.assertEqual(usage["total_limit"], 5)

    def test_a_corrupt_ledger_file_does_not_block_work(self):
        self.path.write_text("not json", encoding="utf-8")
        self.ledger().check("ops@example.com")


if __name__ == "__main__":
    unittest.main()
