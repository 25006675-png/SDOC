"""Backend API tests against the local repository implementation."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from sdoc.api import create_app
from sdoc.casework import CaseStore


class TestApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = patch.dict(
            "os.environ",
            {
                "GOOGLE_CLIENT_ID": "",
                "GOOGLE_CLIENT_SECRET": "",
                "SDOC_GMAIL_TOKEN_PATH": str(root / "gmail_token.json"),
                "SDOC_GMAIL_STATE_PATH": str(root / "gmail_state.json"),
                "SDOC_ATTACHMENT_ROOT": str(root),
            },
            clear=False,
        )
        self.env.start()
        self.store = CaseStore(":memory:")
        email = {
            "email_id": "api_001",
            "from": "ops@example.com",
            "subject": "Check 9API-10001",
            "body": "Please compare the SI and draft BL.",
            "attachments": ["attachments/a_SI.pdf", "attachments/a_BL.pdf"],
        }
        record = {
            "category": "BL_COMPARISON",
            "status": "MISMATCH",
            "review_reason": None,
            "defect_fields": ["container_count"],
            "has_defect": True,
            "decided_by": "rule",
        }
        evidence = {
            "si_doc": "attachments/a_SI.pdf",
            "bl_doc": "attachments/a_BL.pdf",
            "doc_kinds": {
                "attachments/a_SI.pdf": "SI",
                "attachments/a_BL.pdf": "BL",
            },
        }
        self.case = self.store.ingest_result(email, record, evidence, now=100)
        self.app = create_app(self.store, start_scheduler=False)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.store.close()
        self.env.stop()
        self.tmp.cleanup()

    def test_health_metrics_and_case_detail(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["store"], "CaseStore")

        metrics = self.client.get("/api/metrics").json()
        self.assertEqual(metrics["states"], {"DISCREPANCY": 1})
        self.assertEqual(metrics["open_review_tasks"], 1)
        self.assertEqual(metrics["processed_messages"], 1)
        self.assertEqual(metrics["manual_review_rate"], 1.0)
        self.assertEqual(metrics["discrepancy_fields"], {"container_count": 1})

        cases = self.client.get("/api/cases", params={"state": "DISCREPANCY"})
        self.assertEqual(cases.status_code, 200)
        self.assertEqual(cases.json()["items"][0]["case_id"], self.case["case_id"])

        detail = self.client.get(f"/api/cases/{self.case['case_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["documents"][0]["role"], "BL")
        self.assertEqual(detail.json()["emails"][0]["payload_json"]["email_id"], "api_001")
        self.assertEqual(detail.json()["comparisons"][0]["defect_fields"], ["container_count"])
        draft = self.client.get(f"/api/cases/{self.case['case_id']}/draft")
        self.assertEqual(draft.status_code, 200)
        self.assertEqual(draft.json()["kind"], "CORRECTION_REQUEST")
        self.assertFalse(draft.json()["send_allowed"])
        self.assertIn("Container count", draft.json()["body"])
        self.assertEqual(self.client.get("/app/").status_code, 200)
        self.assertEqual(self.client.get("/app/admin.html").status_code, 200)

    def test_attachment_preview_and_download(self):
        root = Path(self.tmp.name)
        attachment = root / "attachments" / "a_SI.pdf"
        attachment.parent.mkdir(parents=True, exist_ok=True)
        attachment.write_bytes(b"%PDF-test")

        preview = self.client.get("/api/attachments/preview", params={"path": "attachments/a_SI.pdf"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content, b"%PDF-test")

        download = self.client.get("/api/attachments/download", params={"path": "attachments/a_SI.pdf"})
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["content-disposition"])

        self.assertEqual(
            self.client.get("/api/attachments/preview", params={"path": "../gmail_token.json"}).status_code,
            404,
        )

    def test_mailbox_status_without_oauth_config(self):
        status = self.client.get("/api/mailbox/status")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["configured"])
        self.assertFalse(status.json()["connected"])

        self.assertEqual(self.client.get("/api/mailbox/connect").status_code, 409)
        self.assertEqual(self.client.post("/api/mailbox/sync").status_code, 409)

    def test_invalid_state_and_missing_case(self):
        self.assertEqual(self.client.get("/api/cases", params={"state": "NOPE"}).status_code, 422)
        self.assertEqual(self.client.get("/api/cases/missing").status_code, 404)

    def test_resolve_review_task(self):
        task_id = self.case["review_tasks"][0]["task_id"]
        response = self.client.post(
            f"/api/review-tasks/{task_id}/resolve",
            json={"actor": "reviewer@example.com", "note": "Confirmed"},
        )
        self.assertEqual(response.status_code, 200)
        case = self.store.get_case(self.case["case_id"])
        self.assertEqual(case["review_tasks"][0]["status"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
