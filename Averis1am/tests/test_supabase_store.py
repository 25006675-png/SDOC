"""Supabase adapter request-shape tests without contacting a real project."""
import unittest

import httpx

from sdoc.supabase_store import SupabaseStore


class TestSupabaseStore(unittest.TestCase):
    def test_postgrest_base_path_is_preserved(self):
        seen = []

        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json=[])

        client = httpx.Client(
            base_url="https://example.supabase.co/rest/v1/",
            transport=httpx.MockTransport(handler),
        )
        store = SupabaseStore("https://example.supabase.co", "secret", client=client)
        store.list_cases()
        self.assertEqual(seen, ["/rest/v1/shipment_cases"])
        client.close()


if __name__ == "__main__":
    unittest.main()
