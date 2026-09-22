import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from sdoc import runtime_state


class TestFileBackend(unittest.TestCase):
    def test_default_backend_round_trips_through_a_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SDOC_STATE_BACKEND", None)
            path = Path(tmp) / "nested" / "gmail_token.json"
            self.assertEqual(runtime_state.load(path, {"none": True}), {"none": True})
            runtime_state.save(path, {"refresh_token": "r"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"refresh_token": "r"})
            self.assertEqual(runtime_state.load(path, {}), {"refresh_token": "r"})


class TestSupabaseBackend(unittest.TestCase):
    def setUp(self):
        self.rows = {}
        self.requests = []

        def handler(request):
            self.requests.append(request)
            if request.method == "GET":
                key = request.url.params["key"].removeprefix("eq.")
                rows = [{"value": self.rows[key]}] if key in self.rows else []
                return httpx.Response(200, json=rows)
            body = json.loads(request.content)
            self.rows[body["key"]] = body["value"]
            return httpx.Response(201)

        client = httpx.Client(base_url="https://db.example/rest/v1",
                              transport=httpx.MockTransport(handler))
        patches = [
            mock.patch.dict(os.environ, {"SDOC_STATE_BACKEND": "supabase"}),
            mock.patch.object(runtime_state, "_client", client),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(client.close)

    def test_rows_are_keyed_by_file_name_and_upserted(self):
        path = Path("/anywhere/data/gmail_state.json")
        self.assertEqual(runtime_state.load(path, {"fresh": True}), {"fresh": True})
        runtime_state.save(path, {"seen_message_ids": ["a"]})
        runtime_state.save(path, {"seen_message_ids": ["a", "b"]})
        self.assertEqual(self.rows, {"gmail_state.json": {"seen_message_ids": ["a", "b"]}})
        self.assertEqual(runtime_state.load(path, {}), {"seen_message_ids": ["a", "b"]})
        post = next(r for r in self.requests if r.method == "POST")
        self.assertIn("merge-duplicates", post.headers["Prefer"])
        self.assertEqual(post.url.params["on_conflict"], "key")

    def test_a_database_error_is_raised_not_read_as_empty_state(self):
        # Returning the default here would let the next save wipe the real token.
        failing = httpx.Client(base_url="https://db.example/rest/v1",
                               transport=httpx.MockTransport(lambda r: httpx.Response(503)))
        self.addCleanup(failing.close)
        with mock.patch.object(runtime_state, "_client", failing):
            with self.assertRaises(httpx.HTTPStatusError):
                runtime_state.load(Path("gmail_token.json"), {})


if __name__ == "__main__":
    unittest.main()
