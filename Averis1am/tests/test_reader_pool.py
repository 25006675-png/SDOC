"""Reusable helper-process reader tests."""
import time
import unittest

from sdoc.docs import extract_bytes
from sdoc.reader_pool import ReaderPool, ReaderTimeoutError


def slow_reader(data, att_path, cfg=None, problems=None):
    time.sleep(2)
    return "SLOW", [("Shipper", "TOO LATE")]


class TestReaderPool(unittest.TestCase):
    def test_isolated_read_matches_deterministic_read(self):
        with ReaderPool(workers=1, timeout=5) as pool:
            doc = extract_bytes(
                b"SHIPPING INSTRUCTION\nShipper: ACME",
                "sample.txt",
                {"reader_pool": pool},
            )
        self.assertEqual(doc[0], "SHIPPING INSTRUCTION")
        self.assertEqual(doc[1][0]["value"], "ACME")

    def test_timeout_terminates_pool_and_next_read_succeeds(self):
        with ReaderPool(workers=1, timeout=1) as pool:
            with self.assertRaises(ReaderTimeoutError):
                pool.extract(b"raw", "slow.bin", {"_test_sleep_seconds": 2})
            doc = pool.extract(b"SHIPPING INSTRUCTION\nShipper: ACME", "sample.txt", {})
        self.assertEqual(doc[0], "SHIPPING INSTRUCTION")



class TestReaderFailureIsVisible(unittest.TestCase):
    """A helper-process timeout must not look like a corrupt file (A6/A10)."""

    class _Source:
        def read_bytes(self, path):
            return b"Shipper: ACME\nGross Wt (kgs): 1 KG\n"

    def _run(self, **cfg_extra):
        from sdoc.core import prepare_cfg, process_email
        from sdoc.reader_pool import ReaderPool
        pool = ReaderPool(workers=1, timeout=1)
        try:
            cfg = prepare_cfg({"reader_pool": pool, **cfg_extra})
            email = {"email_id": "t1", "from": "x@y.z",
                     "subject": "compare DOC-9", "body": "please compare",
                     "attachments": ["a_SI.txt", "a_BL.txt"]}
            return process_email(email, self._Source(), cfg)
        finally:
            pool.close()

    def test_timeout_is_named_in_the_evidence(self):
        _, evidence = self._run(_test_sleep_seconds=3)
        failures = evidence.get("reader_failures") or []
        self.assertTrue(failures, "timeout left no trace in the evidence")
        self.assertEqual(failures[0]["kind"], "ReaderTimeoutError")
        self.assertIn("timed out", failures[0]["error"])

    def test_a_healthy_read_records_no_failures(self):
        _, evidence = self._run()
        self.assertNotIn("reader_failures", evidence)

if __name__ == "__main__":
    unittest.main()
