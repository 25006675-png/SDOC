"""Preflight security and resource controls.

Covers the guarantees stated in SDOC_v2_Plan_Addons.md A3: untrusted filenames
cannot escape the attachment root, and content that was never read is never
reported as content the document lacks.
"""
import unittest

from sdoc.gmail import safe_filename
from sdoc.verification import (
    VERIFIER_TEXT_LIMIT,
    GeminiVerifier,
    TruncatedDocumentError,
    verify_documents,
)


class TestSafeFilename(unittest.TestCase):
    def test_ordinary_names_are_unchanged(self):
        self.assertEqual(safe_filename("GMAIL-STD-0001_SI.pdf"),
                         "GMAIL-STD-0001_SI.pdf")

    def test_posix_traversal_is_stripped(self):
        self.assertEqual(safe_filename("../../../../evil.py"), "evil.py")

    def test_windows_traversal_is_stripped(self):
        self.assertEqual(safe_filename(chr(92) * 2 + "evil.py"), "evil.py")

    def test_embedded_traversal_is_stripped(self):
        self.assertEqual(safe_filename("a/../../b.pdf"), "b.pdf")

    def test_degenerate_names_get_a_fallback(self):
        for name in ("", ".", "..", None):
            self.assertEqual(safe_filename(name), "attachment")

    def test_nul_byte_is_removed(self):
        self.assertEqual(safe_filename("evil" + chr(0) + ".pdf"), "evil.pdf")

    def test_result_never_escapes_a_single_path_segment(self):
        hostile = ["../x", "..\\x", "/etc/passwd", "C:/Windows/x.dll",
                   "....//....//x", "a/b/c/d.pdf"]
        for name in hostile:
            cleaned = safe_filename(name)
            self.assertNotIn("/", cleaned)
            self.assertNotIn(chr(92), cleaned)
            self.assertNotIn("..", cleaned)


class _Source:
    """Serves a document larger than one verifier read can cover."""

    def __init__(self, size):
        self.size = size

    def read_bytes(self, path):
        return b"x" * self.size


class TestLoudTruncation(unittest.TestCase):
    def _verifier(self):
        return GeminiVerifier(api_key="test-key", client=object())

    def test_oversized_text_raises_instead_of_truncating(self):
        verifier = self._verifier()
        payload = b"y" * (VERIFIER_TEXT_LIMIT + 1)
        with self.assertRaises(TruncatedDocumentError):
            verifier(payload, "manifest.txt", "BL")

    def test_text_within_the_limit_is_not_rejected(self):
        verifier = self._verifier()
        payload = b"y" * (VERIFIER_TEXT_LIMIT - 1)
        # Reaching the transport means the size gate let it through; the stub
        # client has no .post, so the failure proves we got past truncation.
        with self.assertRaises(AttributeError):
            verifier(payload, "manifest.txt", "BL")

    def test_truncation_fails_verification_rather_than_passing_silently(self):
        source = _Source(VERIFIER_TEXT_LIMIT + 1)
        verifier = self._verifier()
        result = verify_documents(source, "si.txt", "bl.txt",
                                  {"fields": {}}, verifier)
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("TruncatedDocumentError", result["error"])


if __name__ == "__main__":
    unittest.main()
