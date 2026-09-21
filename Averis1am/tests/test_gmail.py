"""Tests for Gmail source shaping."""
import base64
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from unittest.mock import patch

from sdoc import gmail
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

    def test_authorization_url_lets_admin_choose_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = GmailConfig()
            cfg.client_id = "client"
            cfg.client_secret = "secret"
            cfg.redirect_uri = "http://127.0.0.1/callback"
            cfg.state_path = Path(tmp) / "gmail_state.json"
            cfg.token_path = Path(tmp) / "gmail_token.json"
            service = GmailSyncService(store=None, cfg=cfg, client=httpx.Client())

            query = parse_qs(urlparse(service.authorization_url()).query)
            # Google skips the chooser for a single signed-in session unless asked;
            # consent is still needed so every connect returns a refresh token.
            self.assertEqual(query["prompt"][0].split(), ["select_account", "consent"])
            service.close()



class _Stub:
    """Stands in for a Gemini client; the real one needs keys."""

    def close(self):
        pass


class TestSyncWiring(unittest.TestCase):
    """Live mail must get the same independent second read as the demo import."""

    def _case_cfg(self, env):
        """Capture the config sync_once hands to CaseService."""
        captured = {}

        class _StopSync(RuntimeError):
            pass

        def fake_case_service(store, cfg=None):
            captured.update(cfg or {})
            raise _StopSync

        with patch.dict("os.environ", env, clear=False), \
             patch.object(gmail, "CaseService", fake_case_service), \
             patch.object(gmail.GmailSyncService, "_access_token",
                          return_value="token"), \
             patch.object(gmail, "GmailSource"), \
             patch.object(gmail, "GeminiEmailClassifier"), \
             patch.object(gmail, "GeminiVerifier") as verifier:
            verifier.return_value = _Stub()
            service = gmail.GmailSyncService(
                store=None, cfg=gmail.GmailConfig(), client=object())
            with self.assertRaises(_StopSync):
                service.sync_once()
        return captured

    def test_verifier_is_configured_when_keys_are_present(self):
        cfg = self._case_cfg({"GEMINI_KEYS": "k1", "SDOC_VERIFY": "auto",
                              "GOOGLE_CLIENT_ID": "id",
                              "GOOGLE_CLIENT_SECRET": "secret"})
        self.assertIsInstance(cfg.get("verifier"), _Stub)

    def test_verifier_can_be_switched_off(self):
        cfg = self._case_cfg({"GEMINI_KEYS": "k1", "SDOC_VERIFY": "off",
                              "GOOGLE_CLIENT_ID": "id",
                              "GOOGLE_CLIENT_SECRET": "secret"})
        self.assertIsNone(cfg.get("verifier"))

    def test_no_verifier_without_keys(self):
        cfg = self._case_cfg({"GEMINI_KEYS": "", "GEMINI_KEY": "",
                              "GOOGLE_CLIENT_ID": "id",
                              "GOOGLE_CLIENT_SECRET": "secret"})
        self.assertIsNone(cfg.get("verifier"))

if __name__ == "__main__":
    unittest.main()
