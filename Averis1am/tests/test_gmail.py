"""Tests for Gmail source shaping."""
import base64
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from sdoc.gmail import GmailConfig, GmailSource, GmailSyncService


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class TestGmailSource(unittest.TestCase):
    def test_full_message_maps_to_source_record_and_attachment_bytes(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            if request.url.path.endswith("/users/me/messages"):
                return httpx.Response(200, json={"messages": [{"id": "m_123"}]})
            if request.url.path.endswith("/users/me/messages/m_123"):
                return httpx.Response(200, json={
                    "id": "m_123",
                    "threadId": "t_1",
                    "labelIds": ["INBOX"],
                    "snippet": "snippet",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Ops <ops@example.com>"},
                            {"name": "Subject", "value": "TO CONFIRM DOCS _ 9X"},
                            {"name": "Date", "value": "Sun, 20 Sep 2026 10:00:00 +0800"},
                        ],
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {"data": b64("Please compare attached SI and BL.")},
                            },
                            {
                                "filename": "x_SI.txt",
                                "body": {"attachmentId": "att_1"},
                            },
                            {
                                "mimeType": "image/png",
                                "filename": "icon.png",
                                "body": {"data": b64("tiny")},
                            },
                        ],
                    },
                })
            if request.url.path.endswith("/users/me/messages/m_123/attachments/att_1"):
                return httpx.Response(200, json={"data": b64("SHIPPING INSTRUCTION")})
            return httpx.Response(404)

        client = httpx.Client(
            base_url="https://gmail.googleapis.com/gmail/v1",
            transport=httpx.MockTransport(handler),
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = GmailSource("token", "has:attachment", client=client, attachment_root=tmp)

            emails = source.emails()

            self.assertEqual(len(emails), 1)
            self.assertEqual(emails[0]["email_id"], "gmail_m_123")
            self.assertEqual(emails[0]["message_url"], "https://mail.google.com/mail/u/0/#all/t_1")
            self.assertEqual(emails[0]["gmail_thread_id"], "t_1")
            self.assertEqual(emails[0]["thread_id"], "t_1")
            self.assertEqual(emails[0]["label_ids"], ["INBOX"])
            self.assertEqual(emails[0]["subject"], "TO CONFIRM DOCS _ 9X")
            self.assertIn("Please compare", emails[0]["body"])
            self.assertEqual(emails[0]["attachments"], ["attachments/gmail/m_123/x_SI.txt"])
            self.assertEqual(
                source.read_bytes("attachments/gmail/m_123/x_SI.txt"),
                b"SHIPPING INSTRUCTION",
            )
            self.assertEqual(
                (Path(tmp) / "attachments" / "gmail" / "m_123" / "x_SI.txt").read_bytes(),
                b"SHIPPING INSTRUCTION",
            )
            self.assertTrue(any("q=has%3Aattachment" in url for url in calls))

    def test_multiple_authorization_urls_keep_pending_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = GmailConfig()
            cfg.client_id = "client"
            cfg.client_secret = "secret"
            cfg.redirect_uri = "http://127.0.0.1/callback"
            cfg.state_path = Path(tmp) / "gmail_state.json"
            cfg.token_path = Path(tmp) / "gmail_token.json"
            service = GmailSyncService(store=None, cfg=cfg, client=httpx.Client())

            first = parse_qs(urlparse(service.authorization_url()).query)["state"][0]
            second = parse_qs(urlparse(service.authorization_url()).query)["state"][0]

            pending = cfg.state_path.read_text(encoding="utf-8")
            self.assertIn(first, pending)
            self.assertIn(second, pending)
            service.close()


if __name__ == "__main__":
    unittest.main()
