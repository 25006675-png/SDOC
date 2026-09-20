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


if __name__ == "__main__":
    unittest.main()
