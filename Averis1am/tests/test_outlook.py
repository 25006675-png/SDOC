"""Tests for Outlook / Microsoft Graph mailbox support."""
import base64
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from sdoc.mailbox import create_mailbox_sync
from sdoc.outlook import OutlookConfig, OutlookSource, OutlookSyncService


class TestOutlookSource(unittest.TestCase):
    def test_graph_message_maps_to_source_record_and_attachment_bytes(self):
        calls = []

        def handler(request):
            calls.append(str(request.url))
            if request.url.path.endswith("/me/messages"):
                return httpx.Response(200, json={"value": [{
                    "id": "m_123",
                    "conversationId": "c_1",
                    "subject": "TO CONFIRM DOCS _ 9X",
                    "from": {"emailAddress": {"address": "ops@example.com", "name": "Ops"}},
                    "receivedDateTime": "2026-09-20T10:00:00Z",
                    "body": {"contentType": "html", "content": "<p>Please compare attached SI and BL.</p>"},
                    "bodyPreview": "preview",
                    "hasAttachments": True,
                    "webLink": "https://outlook.office.com/mail/id/m_123",
                    "parentFolderId": "inbox",
                }]})
            if request.url.path.endswith("/me/messages/m_123/attachments"):
                return httpx.Response(200, json={"value": [{
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": "x_SI.txt",
                    "contentBytes": base64.b64encode(b"SHIPPING INSTRUCTION").decode(),
                }]})
            return httpx.Response(404)

        client = httpx.Client(
            base_url="https://graph.microsoft.com/v1.0",
            transport=httpx.MockTransport(handler),
        )
        with tempfile.TemporaryDirectory() as tmp:
            source = OutlookSource("token", "hasAttachments eq true", client=client, attachment_root=tmp)
            emails = source.emails()

            self.assertEqual(len(emails), 1)
            self.assertEqual(emails[0]["email_id"], "outlook_m_123")
            self.assertEqual(emails[0]["outlook_conversation_id"], "c_1")
            self.assertEqual(emails[0]["thread_id"], "c_1")
            self.assertEqual(emails[0]["label_ids"], ["inbox"])
            self.assertEqual(emails[0]["from"], "ops@example.com")
            self.assertEqual(emails[0]["subject"], "TO CONFIRM DOCS _ 9X")
            self.assertIn("Please compare", emails[0]["body"])
            self.assertEqual(emails[0]["attachments"], ["attachments/outlook/m_123/x_SI.txt"])
            self.assertEqual(source.read_bytes("attachments/outlook/m_123/x_SI.txt"), b"SHIPPING INSTRUCTION")
            self.assertEqual((Path(tmp) / "attachments" / "outlook" / "m_123" / "x_SI.txt").read_bytes(), b"SHIPPING INSTRUCTION")
            self.assertTrue(any("%24filter=hasAttachments" in url for url in calls))


class TestOutlookConfig(unittest.TestCase):
    def test_client_id_must_be_guid_and_error_is_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = OutlookConfig()
            cfg.client_id = "~looks-like-secret-value"
            cfg.client_secret = "secret"
            cfg.redirect_uri = "http://localhost:8001/api/mailbox/oauth/callback"
            cfg.state_path = Path(tmp) / "state.json"
            cfg.token_path = Path(tmp) / "token.json"
            service = OutlookSyncService(store=None, cfg=cfg, client=httpx.Client())

            self.assertFalse(service.status()["configured"])
            self.assertIn("Application (client) ID GUID", service.status()["next_action"])
            with self.assertRaisesRegex(ValueError, "Application"):
                service.authorization_url()
            service.close()

    def test_authorization_url_uses_microsoft_v2_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = OutlookConfig()
            cfg.client_id = "12345678-1234-1234-1234-123456789abc"
            cfg.client_secret = "secret"
            cfg.tenant = "common"
            cfg.redirect_uri = "http://localhost:8001/api/mailbox/oauth/callback"
            cfg.state_path = Path(tmp) / "state.json"
            cfg.token_path = Path(tmp) / "token.json"
            service = OutlookSyncService(store=None, cfg=cfg, client=httpx.Client())

            url = service.authorization_url()
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            self.assertEqual(parsed.netloc, "login.microsoftonline.com")
            self.assertEqual(parsed.path, "/common/oauth2/v2.0/authorize")
            self.assertEqual(query["client_id"], [cfg.client_id])
            self.assertEqual(query["redirect_uri"], [cfg.redirect_uri])
            self.assertIn("Mail.Read", query["scope"][0])
            service.close()


class TestMailboxFactory(unittest.TestCase):
    def test_factory_selects_outlook(self):
        service = create_mailbox_sync(store=None, provider="outlook")
        try:
            self.assertEqual(service.status()["provider"], "outlook")
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
