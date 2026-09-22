import json
import unittest

import httpx

from sdoc.verification import (
    GeminiVerifier,
    check_independent_extraction,
    verify_documents,
)


FIELDS = {
    "shipper": {"si": "APRIL FINE PAPER TRADING", "bl": "APRIL FINE PAPER TRADING"},
    "consignee": {"si": "HABRAS INTERNATIONAL LIMITED", "bl": "HABRAS INTERNATIONAL LIMITED"},
    "notify_party": {"si": "HABRAS INTERNATIONAL LIMITED", "bl": "HABRAS INTERNATIONAL LIMITED"},
    "port_of_loading": {"si": "NHAVA SHEVA, INDIA", "bl": "NHAVA SHEVA, INDIA"},
    "port_of_discharge": {"si": "LONG BEACH, US", "bl": "LONG BEACH, US"},
    "container_count": {"si": "4 x 20'FCL", "bl": "4"},
    "gross_weight_kg": {"si": "82.932 MT", "bl": "82,932 KG"},
}

VERIFIED = {
    "shipper": "APRIL FINE PAPER TRADING",
    "consignee": "HABRAS INTERNATIONAL LIMITED",
    "notify_party": "HABRAS INTERNATIONAL LIMITED",
    "port_of_loading": "NHAVA SHEVA, INDIA",
    "port_of_discharge": "LONG BEACH, US",
    "container_count": "4",
    "gross_weight_kg": "82932 KG",
}


class Source:
    def read_bytes(self, path):
        return path.encode()


class TestIndependentVerification(unittest.TestCase):
    def test_normalized_equivalents_agree(self):
        self.assertEqual(check_independent_extraction(FIELDS, VERIFIED, "si"), [])
        self.assertEqual(check_independent_extraction(FIELDS, VERIFIED, "bl"), [])

    def test_disagreement_is_field_specific(self):
        wrong = dict(VERIFIED, container_count="5")
        self.assertEqual(
            check_independent_extraction(FIELDS, wrong, "si"), ["container_count"]
        )

    def test_documents_are_read_independently(self):
        calls = []

        def verifier(data, filename, role):
            calls.append((data, filename, role))
            return VERIFIED

        result = verify_documents(
            Source(), "shipment_SI.pdf", "shipment_BL.pdf",
            {"fields": FIELDS}, verifier,
        )
        self.assertEqual(result["status"], "AGREED")
        self.assertEqual([call[2] for call in calls], ["SI", "BL"])

    def test_gemini_uses_structured_output_and_inline_pdf(self):
        seen = {}

        def handler(request):
            seen["headers"] = request.headers
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": json.dumps(VERIFIED)}]}}]},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        verifier = GeminiVerifier("test-key", "gemini-test", client=client)
        result = verifier(b"%PDF-test", "sample.pdf", "SI")
        self.assertEqual(result["container_count"], "4")
        self.assertEqual(seen["headers"]["x-goog-api-key"], "test-key")
        config = seen["body"]["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertNotIn("additionalProperties", config["responseSchema"])
        self.assertEqual(
            seen["body"]["contents"][0]["parts"][1]["inlineData"]["mimeType"],
            "application/pdf",
        )
        client.close()

    def test_gemini_retries_transient_provider_errors(self):
        statuses = iter([429, 503, 200])
        sleeps = []

        def handler(request):
            status = next(statuses)
            if status != 200:
                return httpx.Response(status, headers={"Retry-After": "0"})
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": json.dumps(VERIFIED)}]}}]},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        verifier = GeminiVerifier(
            "test-key", "gemini-test", client=client, max_retries=2, sleep=sleeps.append
        )
        self.assertEqual(verifier(b"%PDF-test", "sample.pdf", "SI")["container_count"], "4")
        self.assertEqual(sleeps, [0.0, 0.0])
        client.close()

    def test_gemini_rotates_keys_after_quota_response(self):
        seen_keys = []

        def handler(request):
            seen_keys.append(request.headers["x-goog-api-key"])
            if len(seen_keys) == 1:
                return httpx.Response(429)
            return httpx.Response(
                200,
                json={"candidates": [{"content": {"parts": [{"text": json.dumps(VERIFIED)}]}}]},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        verifier = GeminiVerifier(
            ["first-key", "second-key"], "gemini-test", client=client,
            max_retries=1, sleep=lambda _: None,
        )
        verifier(b"%PDF-test", "sample.pdf", "SI")
        self.assertEqual(seen_keys, ["first-key", "second-key"])
        client.close()


if __name__ == "__main__":
    unittest.main()
