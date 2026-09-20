"""Preflight security and resource controls.

Covers the guarantees stated in SDOC_v2_Plan_Addons.md A3: untrusted filenames
cannot escape the attachment root, content that was never read is never
reported as content the document lacks, and nothing reaches a model before it
has passed the gate.
"""
import pathlib
import unittest

from sdoc.casework import product_state
from sdoc.core import prepare_cfg, process_email
from sdoc.gmail import safe_filename
from sdoc.preflight import (
    MALFORMED,
    OVERSIZE,
    TOO_MANY_ATTACHMENTS,
    TOO_MANY_PAGES,
    TYPE_MISMATCH,
    GateConfig,
    inspect_attachment,
    screen_attachments,
)
from sdoc.verification import (
    VERIFIER_TEXT_LIMIT,
    GeminiVerifier,
    TruncatedDocumentError,
    verify_documents,
)

_PDF = (pathlib.Path(__file__).resolve().parents[2] / "gmail-test" /
        "attachments" / "GMAIL-STD-0001_SI.pdf")


def real_pdf():
    """A genuine single-page shipping document from the demo set."""
    return _PDF.read_bytes()


class _Bytes:
    """Serves attachment bytes from a dict."""

    def __init__(self, files):
        self.files = files

    def read_bytes(self, path):
        return self.files[path]


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


class _OversizeSource:
    """Serves a document larger than one verifier read can cover."""

    def __init__(self, size):
        self.size = size

    def read_bytes(self, path):
        return b"x" * self.size


class TestLoudTruncation(unittest.TestCase):
    def _verifier(self):
        return GeminiVerifier(api_key="test-key", client=object())

    def test_oversized_text_raises_instead_of_truncating(self):
        with self.assertRaises(TruncatedDocumentError):
            self._verifier()(b"y" * (VERIFIER_TEXT_LIMIT + 1),
                             "manifest.txt", "BL")

    def test_text_within_the_limit_is_not_rejected(self):
        # Reaching the transport means the size gate let it through; the stub
        # client has no .post, so the failure proves we got past truncation.
        with self.assertRaises(AttributeError):
            self._verifier()(b"y" * (VERIFIER_TEXT_LIMIT - 1),
                             "manifest.txt", "BL")

    def test_truncation_fails_verification_rather_than_passing_silently(self):
        result = verify_documents(_OversizeSource(VERIFIER_TEXT_LIMIT + 1),
                                  "si.txt", "bl.txt", {"fields": {}},
                                  self._verifier())
        self.assertEqual(result["status"], "FAILED")
        self.assertIn("TruncatedDocumentError", result["error"])


class TestPreflightGate(unittest.TestCase):
    """Addendum A3: nothing reaches a model until it has passed the gate."""

    def setUp(self):
        self.cfg = GateConfig(max_bytes=4096, max_pages=3, max_attachments=3,
                              max_expansion=10, max_archive_entries=20)

    def test_ordinary_text_passes(self):
        self.assertTrue(inspect_attachment(b"Shipper: ACME\n", "si.txt",
                                           self.cfg)["ok"])

    def test_oversized_attachment_is_rejected(self):
        verdict = inspect_attachment(b"x" * 5000, "si.txt", self.cfg)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["reason"], OVERSIZE)

    def test_empty_attachment_is_rejected(self):
        self.assertEqual(inspect_attachment(b"", "si.pdf", self.cfg)["reason"],
                         MALFORMED)

    def test_extension_is_not_trusted(self):
        # A zip archive wearing a .pdf name must not reach the PDF reader.
        verdict = inspect_attachment(b"PK\x03\x04payload", "invoice.pdf",
                                     self.cfg)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["reason"], TYPE_MISMATCH)
        self.assertEqual(verdict["detail"],
                         {"declared": ".pdf", "detected": "zip"})

    def test_binary_wearing_a_text_extension_is_rejected(self):
        self.assertEqual(
            inspect_attachment(b"\x00\x01\x02\x03", "si.txt", self.cfg)["reason"],
            TYPE_MISMATCH)

    def test_real_pdf_within_the_page_limit_passes(self):
        verdict = inspect_attachment(real_pdf(), "GMAIL-STD-0001_SI.pdf",
                                     GateConfig(max_bytes=10 ** 7, max_pages=1))
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual(verdict["detail"]["pages"], 1)

    def test_pdf_over_the_page_limit_is_rejected(self):
        tight = GateConfig(max_bytes=10 ** 7, max_pages=1)
        tight.max_pages = 0                      # below any real document
        self.assertEqual(
            inspect_attachment(real_pdf(), "big.pdf", tight)["reason"],
            TOO_MANY_PAGES)

    def test_corrupt_pdf_is_rejected_before_reading(self):
        verdict = inspect_attachment(b"%PDF-1.4 truncated", "si.pdf", self.cfg)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["reason"], MALFORMED)

    def test_too_many_attachments_is_rejected_without_reading_any(self):
        gate = screen_attachments(_Bytes({}), ["a", "b", "c", "d"], self.cfg)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["reason"], TOO_MANY_ATTACHMENTS)

    def test_screening_reports_every_rejection(self):
        source = _Bytes({"ok.txt": b"Shipper: ACME\n",
                         "bad.pdf": b"PK\x03\x04zip-in-disguise"})
        gate = screen_attachments(source, ["ok.txt", "bad.pdf"], self.cfg)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["reason"], TYPE_MISMATCH)
        self.assertIn("ok.txt", gate["accepted"])
        self.assertEqual(gate["rejected"][0]["document"], "bad.pdf")

    def test_clean_message_passes_the_gate(self):
        source = _Bytes({"si.txt": b"Shipper: ACME\n",
                         "bl.txt": b"Shipper: ACME\n"})
        gate = screen_attachments(source, ["si.txt", "bl.txt"], self.cfg)
        self.assertTrue(gate["ok"])
        self.assertEqual(gate["rejected"], [])


class TestGateBlocksThePipeline(unittest.TestCase):
    def test_gated_message_never_reaches_extraction(self):
        source = _Bytes({"a_SI.pdf": b"PK\x03\x04not-a-pdf",
                         "a_BL.pdf": b"%PDF-1.4 truncated"})
        email = {"email_id": "g1", "from": "x@y.z", "subject": "compare DOC-1",
                 "body": "please compare",
                 "attachments": ["a_SI.pdf", "a_BL.pdf"]}
        record, evidence = process_email(
            email, source, prepare_cfg({"gate": GateConfig(max_bytes=4096)}))
        self.assertEqual(record["status"], "NEEDS_REVIEW")
        self.assertEqual(record["gate_reason"], TYPE_MISMATCH)
        self.assertNotIn("fields", evidence)     # nothing was extracted
        self.assertEqual(product_state(record), "BLOCKED")

    def test_gated_message_keeps_the_organizer_reason_vocabulary(self):
        source = _Bytes({"a_SI.pdf": b"PK\x03\x04not-a-pdf",
                         "a_BL.pdf": b"%PDF-1.4 truncated"})
        email = {"email_id": "g2", "from": "x@y.z", "subject": "compare DOC-2",
                 "body": "please compare",
                 "attachments": ["a_SI.pdf", "a_BL.pdf"]}
        record, _ = process_email(email, source, prepare_cfg({}))
        self.assertIn(record["review_reason"],
                      {"wrong_doc_type", "missing_attachment", "unreadable",
                       "missing_value"})


if __name__ == "__main__":
    unittest.main()
