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

        # Inline, or the browser downloads the file instead of showing it.
        self.assertIn("inline", preview.headers["content-disposition"])

        download = self.client.get("/api/attachments/download", params={"path": "attachments/a_SI.pdf"})
        self.assertEqual(download.status_code, 200)
        self.assertIn("attachment", download.headers["content-disposition"])

        self.assertEqual(
            self.client.get("/api/attachments/preview", params={"path": "../gmail_token.json"}).status_code,
            404,
        )

    def test_attachment_page_render_matches_pdf_point_size(self):
        """The evidence overlay needs the page raster and its own point size."""
        source = (Path(__file__).resolve().parents[2] / "gmail-test" /
                  "attachments" / "GMAIL-STD-0001_SI.pdf")
        attachment = Path(self.tmp.name) / "attachments" / "a_SI.pdf"
        attachment.parent.mkdir(parents=True, exist_ok=True)
        attachment.write_bytes(source.read_bytes())

        page = self.client.get("/api/attachments/page", params={"path": "attachments/a_SI.pdf"})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["content-type"], "image/png")
        self.assertTrue(page.content.startswith(bytes.fromhex("89504e47")))
        # Same coordinate space the readers store bounding boxes in.
        self.assertEqual(page.headers["x-page-width"], "595.28")
        self.assertEqual(page.headers["x-page-height"], "841.89")

        self.assertEqual(
            self.client.get("/api/attachments/page",
                            params={"path": "attachments/a_SI.pdf", "page": 99}).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/api/attachments/page",
                            params={"path": "../gmail_token.json"}).status_code,
            404,
        )

    def test_attachment_page_rejects_non_pdf(self):
        attachment = Path(self.tmp.name) / "attachments" / "a_SI.docx"
        attachment.parent.mkdir(parents=True, exist_ok=True)
        attachment.write_bytes(bytes.fromhex("504b0304"))
        response = self.client.get("/api/attachments/page", params={"path": "attachments/a_SI.docx"})
        self.assertEqual(response.status_code, 415)

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



class TestCorrectFieldEndpoint(unittest.TestCase):
    """The Correct Extraction action over HTTP (v2 §9)."""

    def setUp(self):
        self.store = CaseStore(":memory:")
        same = {
            "shipper": "APRIL FAR EAST",
            "consignee": "EAST BRIGHT FZ-LLC",
            "notify_party": "EAST BRIGHT FZ-LLC",
            "port_of_loading": "NANTONG, CHINA",
            "port_of_discharge": "KARACHI, PAKISTAN",
            "gross_weight_kg": "131,058 KG",
        }
        fields = {f: {"si": v, "bl": v, "match": True, "sim": 1.0}
                  for f, v in same.items()}
        fields["container_count"] = {"si": "6", "bl": "7", "match": False,
                                     "sim": 0.0}
        self.store.ingest_result(
            {"email_id": "c_001", "from": "ops@example.com",
             "subject": "Check 9API-20002", "body": "compare",
             "attachments": ["attachments/b_SI.pdf", "attachments/b_BL.pdf"]},
            {"category": "BL_COMPARISON", "status": "MISMATCH",
             "review_reason": None, "defect_fields": ["container_count"],
             "has_defect": True, "decided_by": "rule"},
            {"fields": fields, "si_doc": "attachments/b_SI.pdf",
             "bl_doc": "attachments/b_BL.pdf"},
            now=100,
        )
        self.case_id = self.store.list_cases()[0]["case_id"]
        self.app = create_app(self.store, start_scheduler=False)
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.store.close()

    def _correct(self, **kw):
        payload = {"field": "container_count", "side": "bl", "value": "6",
                   "actor": "worker@example.com", "note": "misread"}
        payload.update(kw)
        return self.client.post(f"/api/cases/{self.case_id}/correct",
                                json=payload)

    def test_correction_clears_the_discrepancy(self):
        response = self._correct()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "VERIFIED")

    def test_correction_is_returned_with_before_and_after(self):
        correction = self._correct().json()["corrections"][0]
        self.assertEqual(correction["old_value"], "7")
        self.assertEqual(correction["new_value"], "6")

    def test_unknown_field_is_a_client_error(self):
        self.assertEqual(self._correct(field="nope").status_code, 400)

    def test_invalid_side_is_rejected_by_validation(self):
        self.assertEqual(self._correct(side="middle").status_code, 422)

    def test_unknown_case_is_a_client_error(self):
        response = self.client.post(
            "/api/cases/case_missing/correct",
            json={"field": "container_count", "side": "bl", "value": "6",
                  "actor": "worker@example.com"},
        )
        self.assertEqual(response.status_code, 400)


class TestAccountAuth(unittest.TestCase):
    """Username/password sign-in and worker/admin separation."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = patch.dict(
            "os.environ",
            {
                "SDOC_AUTH": "on",
                "SDOC_SESSION_SECRET": "test-signing-key",
                "SDOC_ADMIN_PASSWORD": "admin-pass",
                "SDOC_WORKER_PASSWORD": "worker-pass",
                "SDOC_MAILBOX_PROVIDER": "gmail",
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
        self.client = TestClient(create_app(self.store, start_scheduler=False))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.store.close()
        self.env.stop()
        self.tmp.cleanup()

    def _login(self, username, password, next_path="/app/"):
        return self.client.post(
            "/login",
            data=f"username={username}&password={password}&next={next_path}",
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )

    def test_landing_is_public_but_the_app_requires_sign_in(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        response = self.client.get("/app/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/login", response.headers["location"])
        self.assertEqual(self.client.get("/api/cases").status_code, 401)

    def test_bad_password_is_rejected(self):
        self.assertEqual(self._login("admin", "wrong").status_code, 401)
        self.assertEqual(self.client.get("/api/cases").status_code, 401)

    def test_unknown_user_is_rejected(self):
        self.assertEqual(self._login("nobody", "worker-pass").status_code, 401)

    def test_worker_signs_in_and_is_identified(self):
        self.assertEqual(self._login("worker", "worker-pass").status_code, 303)
        status = self.client.get("/api/auth/status").json()
        self.assertEqual(status["username"], "worker")
        self.assertEqual(status["role"], "worker")
        self.assertTrue(status["display_name"])

    def test_worker_cannot_reach_admin_surfaces(self):
        self._login("worker", "worker-pass")
        self.assertEqual(self.client.get("/app/").status_code, 200)
        self.assertEqual(self.client.get("/api/mailbox/status").status_code, 200)
        self.assertEqual(self.client.get("/api/metrics").status_code, 403)
        self.assertEqual(
            self.client.get("/api/mailbox/connect",
                            follow_redirects=False).status_code, 403)

    def test_worker_may_still_refresh_the_queue(self):
        self._login("worker", "worker-pass")
        # Unconfigured, so it cannot succeed -- but it must not be forbidden.
        self.assertNotEqual(self.client.post("/api/mailbox/sync").status_code, 403)

    def test_admin_reaches_admin_surfaces(self):
        login = self._login("admin", "admin-pass", "/app/admin.html")
        self.assertEqual(login.status_code, 303)
        self.assertEqual(login.headers["location"], "/app/admin.html")
        self.assertEqual(self.client.get("/app/admin.html").status_code, 200)
        self.assertEqual(self.client.get("/api/metrics").status_code, 200)

    def test_worker_is_not_sent_to_the_admin_page(self):
        login = self._login("worker", "worker-pass", "/app/admin.html")
        self.assertEqual(login.headers["location"], "/app/")

    def test_logout_ends_the_session(self):
        self._login("admin", "admin-pass")
        self.assertEqual(self.client.get("/api/metrics").status_code, 200)
        self.client.post("/logout", follow_redirects=False)
        self.assertEqual(self.client.get("/api/metrics").status_code, 401)

    def test_a_tampered_cookie_is_refused(self):
        self._login("worker", "worker-pass")
        self.client.cookies.set("sdoc_session", "forged.value")
        self.assertEqual(self.client.get("/api/cases").status_code, 401)

    def test_app_without_trailing_slash_reaches_the_workspace(self):
        self._login("worker", "worker-pass")
        response = self.client.get("/app", follow_redirects=False)
        self.assertEqual(response.status_code, 308)
        self.assertEqual(response.headers["location"], "/app/")
        self.assertEqual(self.client.get("/app", follow_redirects=True).status_code, 200)

    def test_signing_in_from_a_slashless_url_lands_somewhere_real(self):
        response = self._login("worker", "worker-pass", next_path="/app")
        self.assertEqual(response.headers["location"], "/app/")

    def test_plain_sign_in_lands_each_role_on_its_own_home(self):
        # The login form posts an empty next when opened directly, so the
        # role decides: an admin must not land on the worker queue.
        admin = self._login("admin", "admin-pass", next_path="")
        self.assertEqual(admin.headers["location"], "/app/admin.html")
        self.client.post("/logout", follow_redirects=False)
        worker = self._login("worker", "worker-pass", next_path="")
        self.assertEqual(worker.headers["location"], "/app/")

    def test_login_page_does_not_force_the_worker_queue(self):
        page = self.client.get("/login").text
        self.assertIn('name="next" type="hidden" value=""', page)
