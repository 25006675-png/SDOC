"""Unit tests for the sdoc package. Run: python -m unittest tests.test_sdoc -v"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sdoc import docs, schema
from sdoc.classify import classify, classify_result
from sdoc.compare import compare_documents
from sdoc.readers import read_txt
from sdoc.readers import read_pdf

BUNDLE = Path(__file__).resolve().parent.parent / "sdoc-hackathon-bundle"


class _BlankPdf:
    pages = [type("Page", (), {"chars": []})()]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class TestOcrConfig(unittest.TestCase):
    def test_dict_config_enables_scanned_pdf_ocr(self):
        with patch("pdfplumber.open", return_value=_BlankPdf()), \
             patch("sdoc.readers.ocr_available", return_value=True), \
             patch("sdoc.readers._ocr_pdf", return_value="SHIPPING INSTRUCTION\nShipper: ACME"):
            parsed = read_pdf(b"image-only-pdf", {"ocr": True})
        self.assertEqual(parsed[0], "SHIPPING INSTRUCTION")
        self.assertEqual(docs.extract_fields(parsed[1])["shipper"], "ACME")
        self.assertEqual(
            docs.extract_field_sources(parsed[1])["shipper"]["page"], 1)




class TestExtractorStage(unittest.TestCase):
    def test_llm_extractor_can_be_primary_with_deterministic_fallback(self):
        from sdoc.extractors import extract_document
        calls = []

        def fake_llm(data, filename, problems=None):
            calls.append((filename, problems))
            return ("LLM DOC", [("Shipper", "LLM SHIPPER")])

        doc = extract_document(
            b"SHIPPING INSTRUCTION\nShipper: RULE SHIPPER",
            "sample.txt",
            {"extractor": "llm", "llm_extractor": fake_llm},
        )
        self.assertEqual(doc[0], "LLM DOC")
        self.assertEqual(docs.pair_value(doc[1][0]), "LLM SHIPPER")
        self.assertEqual(len(calls), 1)

        doc2 = extract_document(
            b"SHIPPING INSTRUCTION\nShipper: RULE SHIPPER",
            "sample.txt",
            {"extractor": "llm"},
        )
        self.assertEqual(doc2[0], "SHIPPING INSTRUCTION")
        self.assertEqual(docs.extract_fields(doc2[1])["shipper"], "RULE SHIPPER")

    def test_pdf_reader_returns_source_metadata_for_plain_label_rows(self):
        from reportlab.pdfgen import canvas
        import io
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(72, 720, "SHIPPING INSTRUCTION")
        pdf.drawString(72, 700, "Gross Weight: 18,500 KG")
        pdf.save()
        title, pairs = read_pdf(buffer.getvalue())
        sources = docs.extract_field_sources(pairs)
        self.assertEqual(title, "SHIPPING INSTRUCTION")
        self.assertEqual(docs.extract_fields(pairs)["gross_weight_kg"], "18,500 KG")
        self.assertEqual(sources["gross_weight_kg"]["page"], 1)
        self.assertIn("bbox", sources["gross_weight_kg"])
        self.assertIn("Gross Weight", sources["gross_weight_kg"]["source_text"])


class TestLabels(unittest.TestCase):
    def f(self, lab):
        return schema.field_for_label(lab)

    def test_synonyms(self):
        self.assertEqual(self.f("Shipper"), "shipper")
        self.assertEqual(self.f("SHIPPER"), "shipper")
        self.assertEqual(self.f("Shipper/Exporter"), "shipper")
        self.assertEqual(self.f("To the Order of"), "consignee")
        self.assertEqual(self.f("NOTIFY PARTY"), "notify_party")
        self.assertEqual(self.f("Load Port"), "port_of_loading")
        self.assertEqual(self.f("POL"), "port_of_loading")
        self.assertEqual(self.f("Discharge Port"), "port_of_discharge")
        self.assertEqual(self.f("No. of Containers or Packages"), "container_count")

    def test_cjk_and_total(self):
        self.assertEqual(self.f("Gross Weight毛重(KGS)"), "gross_weight_kg")
        self.assertEqual(self.f("Gross Wt (kgs) (毛重 KGS)"), "gross_weight_kg")
        self.assertEqual(self.f("TOTAL Gross Wt (kgs)"), "gross_weight_kg")
        self.assertEqual(self.f("Total Containers"), "container_count")

    def test_non_labels(self):
        for lab in ("HS Code", "OC No.", "Freight", "CONTAINER NO.",
                    "NET WEIGHT", "Invoice No.", "Certificate No."):
            self.assertIsNone(self.f(lab), lab)


class TestValues(unittest.TestCase):
    def test_blank(self):
        for v in ("???", "_______", "TBA", "TBC", "", "N/A", "____MT", "   "):
            self.assertTrue(schema.is_blank(v), v)
        for v in ("0", "SINGAPORE", "12 x 40'HC"):
            self.assertFalse(schema.is_blank(v), v)

    def test_party(self):
        self.assertEqual(schema.norm_value("consignee", "KPP-ANTALIS (SINGAPORE) PTE. LTD."),
                         "KPP ANTALIS SINGAPORE PTE LTD")
        self.assertEqual(schema.norm_value("shipper", "A & B\nSUITE 1, TOWN"),
                         "A AND B")
        self.assertEqual(schema.norm_value("notify_party", "X | P.O. BOX 1; DUBAI"), "X")

    def test_port(self):
        self.assertEqual(schema.norm_value("port_of_loading", "NANTONG, CHINA (CNNTG)"),
                         "NANTONG, CHINA")
        self.assertEqual(schema.norm_value("port_of_discharge", "SINGAPORE (SGSIN)"),
                         "SINGAPORE")
        self.assertEqual(schema.norm_value("port_of_loading", "PORT KLANG (WESTPORT), MALAYSIA (MYPKG)"),
                         "PORT KLANG (WESTPORT), MALAYSIA")

    def test_numbers(self):
        self.assertEqual(schema.norm_value("container_count", "6 x 40'HC"), 6)
        self.assertEqual(schema.norm_value("container_count", "12"), 12)
        self.assertEqual(schema.norm_value("gross_weight_kg", "131,058 KG"), 131058)
        self.assertEqual(schema.norm_value("gross_weight_kg", 243588), 243588)
        self.assertEqual(schema.norm_value("gross_weight_kg", "243.588 MT"), 243588)
        self.assertEqual(schema.norm_value("gross_weight_kg", "2267.96 LB"), 1029)

    def test_missing(self):
        self.assertIsNone(schema.norm_value("gross_weight_kg", "???"))
        self.assertIsNone(schema.norm_value("consignee", None))


class TestDocParsing(unittest.TestCase):
    SI = ("SHIPPING INSTRUCTION\n========================================\n\n"
          "Shipper: APRIL FAR EAST (M) SDN BHD\n"
          "  TOWER 2, AVENUE 5, LEVEL 6; BANGSAR SOUTH CITY\n"
          "Consignee (Non-Negotiable): EAST BRIGHT FZ-LLC\n"
          "Notify: EAST BRIGHT FZ-LLC\n"
          "Port of Loading (POL): NANTONG, CHINA (CNNTG)\n"
          "POD: KARACHI, PAKISTAN (PKKHI)\n"
          "Total Containers: 6 x 40'HC\n"
          "Gross Wt (kgs): 131,058 KG\n"
          "Booking Ref: ONEYSINF32871\nFreight: PREPAID\n")

    def test_txt_pairs(self):
        title, pairs = read_txt(self.SI.encode())
        self.assertEqual(title, "SHIPPING INSTRUCTION")
        f = docs.extract_fields(pairs)
        self.assertEqual(f["shipper"], "APRIL FAR EAST (M) SDN BHD")
        self.assertEqual(f["consignee"], "EAST BRIGHT FZ-LLC")
        self.assertEqual(f["port_of_loading"], "NANTONG, CHINA (CNNTG)")
        self.assertEqual(f["container_count"], "6 x 40'HC")
        self.assertNotIn("consignee_addr", f)   # indented addr not a label

    def test_doc_kind(self):
        self.assertEqual(docs.doc_kind("SHIPPING INSTRUCTION", []), "SI")
        self.assertEqual(docs.doc_kind("BILL OF LADING (DRAFT)", []), "BL")
        self.assertEqual(docs.doc_kind("BILL OF LADING INSTRUCTION", []), "SI")
        self.assertEqual(docs.doc_kind("COMMERCIAL INVOICE", []), "OTHER")
        self.assertEqual(docs.doc_kind("PACKING LIST", []), "OTHER")
        self.assertEqual(docs.doc_kind("CERTIFICATE OF ORIGIN", []), "OTHER")
        self.assertEqual(docs.doc_kind("", []), "UNKNOWN")


class TestCompare(unittest.TestCase):
    def _pairs(self, **kw):
        base = {"Shipper": "APRIL FAR EAST", "Consignee": "EAST BRIGHT",
                "Notify": "EAST BRIGHT", "POL": "NANTONG, CHINA (CNNTG)",
                "POD": "KARACHI, PAKISTAN (PKKHI)", "Total Containers": "6 x 40'HC",
                "Gross Wt (kgs)": "131,058 KG"}
        base.update(kw)
        return list(base.items())

    def test_ok(self):
        si = self._pairs()
        bl = self._pairs()          # same values under identical labels -> OK
        r = compare_documents(si, bl)
        self.assertEqual(r["status"], "OK")

    def test_mismatch(self):
        si = self._pairs()
        bl = self._pairs(**{"Total Containers": "7 x 40'HC", "POD": "APAPA, NIGERIA (NGAPP)"})
        r = compare_documents(si, bl)
        self.assertEqual(r["status"], "MISMATCH")
        self.assertEqual(r["defect_fields"], ["port_of_discharge", "container_count"])
        self.assertFalse(r["fields"]["container_count"]["match"])

    def test_missing_value(self):
        bl = self._pairs(**{"Gross Wt (kgs)": "N/A"})
        r = compare_documents(self._pairs(), bl)
        self.assertEqual(r["status"], "NEEDS_REVIEW")
        self.assertEqual(r["review_reason"], "missing_value")
        self.assertEqual(r["missing"], ["gross_weight_kg"])

    def test_fuzzy(self):
        si = self._pairs()
        bl = self._pairs(**{"Consignee": "EAST  BRIGHT"})   # typo-ish spacing
        r = compare_documents(si, bl)                        # strict: matches anyway
        self.assertEqual(r["status"], "OK")
        bl2 = self._pairs(**{"Consignee": "EAST BRlGHT"})
        self.assertEqual(compare_documents(si, bl2)["status"], "MISMATCH")
        self.assertEqual(compare_documents(si, bl2, fuzzy=0.9)["status"], "OK")


class TestMultilingual(unittest.TestCase):
    def f(self, lab):
        return schema.field_for_label(lab)

    def test_cjk_labels(self):
        self.assertEqual(self.f("发货人"), "shipper")
        self.assertEqual(self.f("收货人"), "consignee")
        self.assertEqual(self.f("通知人"), "notify_party")
        self.assertEqual(self.f("装货港"), "port_of_loading")
        self.assertEqual(self.f("卸货港"), "port_of_discharge")
        self.assertEqual(self.f("箱数"), "container_count")
        self.assertEqual(self.f("毛重"), "gross_weight_kg")

    def test_eu_labels(self):
        self.assertEqual(self.f("Expéditeur"), "shipper")
        self.assertEqual(self.f("Port de chargement"), "port_of_loading")
        self.assertEqual(self.f("Poids brut"), "gross_weight_kg")

    def test_bilingual_labels(self):
        self.assertEqual(self.f("Shipper (发货人)"), "shipper")
        self.assertEqual(self.f("PORT OF LOADING (装货港)"), "port_of_loading")
        self.assertEqual(self.f("Consignee (收货人)"), "consignee")

    def test_unicode_values(self):
        self.assertEqual(schema.norm_value("consignee", "上海贸易有限公司"),
                         "上海贸易有限公司")
        self.assertEqual(schema.norm_value("gross_weight_kg", "２４３,５８８ KG"),
                         243588)
        self.assertTrue(schema.is_blank("待定"))
        self.assertTrue(schema.is_blank("待确认"))

    def test_gbk_txt(self):
        doc = "装货指示\n========\n发货人: 上海贸易有限公司\n收货人: 测试公司\n装货港: 上海\n卸货港: 新加坡\n箱数: 3 x 40'HC\n毛重: 61,000 KG\n"
        title, pairs = read_txt(doc.encode("gb18030"))
        self.assertEqual(title, "装货指示")
        f = docs.extract_fields(pairs)
        self.assertEqual(f["shipper"], "上海贸易有限公司")
        self.assertEqual(f["container_count"], "3 x 40'HC")

    def test_cjk_doc_kind(self):
        self.assertEqual(docs.doc_kind("提单 (草稿)", []), "BL")
        self.assertEqual(docs.doc_kind("装货指示", []), "SI")
        self.assertEqual(docs.doc_kind("提单指示", []), "SI")
        self.assertEqual(docs.doc_kind("商业发票", []), "OTHER")
        self.assertEqual(docs.doc_kind("装箱单", []), "OTHER")


class TestClassify(unittest.TestCase):
    def em(self, subject="", body="", frm="a@aprilasia.com", atts=None):
        return {"email_id": "x", "subject": subject, "body": body,
                "from": frm, "attachments": atts or []}

    def test_attachments_win(self):
        self.assertEqual(classify(self.em(atts=["a_SI.txt", "a_BL.txt"])), "BL_COMPARISON")

    def test_provider_spam_label_wins(self):
        msg = self.em(subject="TO CONFIRM DOCS _ 5X-1", atts=["a_SI.pdf", "a_BL.pdf"])
        msg["label_ids"] = ["SPAM"]
        result = classify_result(msg)
        self.assertEqual(result["category"], "SPAM")
        self.assertEqual(result["decision_source"], "provider")
        self.assertEqual(result["classification_status"], "resolved")

    def test_clear_rules_do_not_call_ai(self):
        calls = []
        result = classify_result(
            self.em(subject="TO CONFIRM DOCS _ 5X-1", atts=["a_SI.pdf", "a_BL.pdf"]),
            {"ai_email_classifier": lambda email: calls.append(email)},
        )
        self.assertEqual(result["category"], "BL_COMPARISON")
        self.assertEqual(result["decision_source"], "rule")
        self.assertEqual(calls, [])

    def test_unclear_attachment_uses_ai_when_configured(self):
        def ai(email):
            return {
                "category": "SI_REQUEST",
                "confidence": 0.82,
                "reason": "body asks for a new SI",
            }

        result = classify_result(
            self.em(subject="Documents", body="Please review attached file", atts=["request.pdf"]),
            {"ai_email_classifier": ai},
        )
        self.assertEqual(result["category"], "SI_REQUEST")
        self.assertEqual(result["decision_source"], "ai")
        self.assertEqual(result["classification_status"], "resolved")
        self.assertEqual(result["score"], 0.82)

    def test_unclear_attachment_without_ai_needs_review(self):
        result = classify_result(
            self.em(subject="Documents", body="Please review attached file", atts=["request.pdf"])
        )
        self.assertEqual(result["category"], "GENERAL")
        self.assertEqual(result["decision_source"], "rule_fallback")
        self.assertEqual(result["classification_status"], "needs_review")

    def test_unclear_ai_failure_needs_review(self):
        def ai(_):
            raise RuntimeError("provider unavailable")

        result = classify_result(
            self.em(subject="Documents", body="Please review attached file", atts=["request.pdf"]),
            {"ai_email_classifier": ai},
        )
        self.assertEqual(result["category"], "GENERAL")
        self.assertEqual(result["decision_source"], "ai_failed")
        self.assertEqual(result["classification_status"], "needs_review")

    def test_categories(self):
        self.assertEqual(classify(self.em(subject="REQUEST SI _ 5RCY-1")),
                         "SI_REQUEST")
        self.assertEqual(classify(self.em(subject="SI - MEDUUD1 - DIRECT(MSC) - x")),
                         "SI_REQUEST")
        self.assertEqual(classify(self.em(subject="2167 RAK BILLING 5070146715 MISSING GR")),
                         "INVOICE_QUERY")
        self.assertEqual(classify(self.em(subject="REQUEST TO CANCEL INVOICE -1")),
                         "INVOICE_QUERY")
        self.assertEqual(classify(self.em(subject="Bitcoin investment opportunity - guaranteed 300% returns")),
                         "SPAM")
        self.assertEqual(classify(self.em(frm="winner@prize-claims.info")), "SPAM")
        self.assertEqual(classify(self.em(subject="anything", frm="rpa.bot@aprilasia.com")),
                         "GENERAL")
        self.assertEqual(classify(self.em(subject="daily Berthing Report - 14 JAN 2026")),
                         "GENERAL")
        self.assertEqual(
            classify(self.em(
                subject="Delivery Status Notification (Failure)",
                frm="Mail Delivery Subsystem <mailer-daemon@googlemail.com>",
                atts=["icon.png"],
            )),
            "GENERAL",
        )
        self.assertEqual(classify(self.em(subject="TO CONFIRM DOCS _ 5X-1")),
                         "BL_COMPARISON")
        self.assertEqual(classify(self.em(subject="AIE - CALLAO_PERU - EVER(EGLV1) - 5X-1")),
                         "BL_COMPARISON")
        self.assertEqual(classify(self.em(subject="Draft BL VISION 202 NANTONG - amend BL 041")),
                         "BL_COMPARISON")


class TestConfigFields(unittest.TestCase):
    """--config fields: extra comparison fields + tolerances, no code change."""
    BASE = {"Shipper": "APRIL FAR EAST", "Consignee": "EAST BRIGHT",
            "Notify": "EAST BRIGHT", "POL": "NANTONG, CHINA (CNNTG)",
            "POD": "KARACHI, PAKISTAN (PKKHI)", "Total Containers": "6 x 40'HC",
            "Gross Wt (kgs)": "131,058 KG"}

    def _cmp(self, si_extra, bl_extra, **kw):
        si = list({**self.BASE, **si_extra}.items())
        bl = list({**self.BASE, **bl_extra}.items())
        return compare_documents(si, bl, **kw)

    def test_extra_field_detected(self):
        lm = schema.build_label_map({"vessel": ["Vessel/VOY"]})
        r = self._cmp({"Vessel/VOY": "EVER GIVEN 001E"},
                      {"Vessel/VOY": "EVER GIVEN 002E"},
                      fields=schema.COMPARE_FIELDS + ["vessel"],
                      field_kinds={"vessel": "text"}, label_map=lm)
        self.assertEqual(r["status"], "MISMATCH")
        self.assertEqual(r["defect_fields"], ["vessel"])

    def test_extra_field_ok_when_same(self):
        lm = schema.build_label_map({"vessel": ["Vessel/VOY"]})
        r = self._cmp({"Vessel/VOY": "EVER GIVEN 001E"},
                      {"Vessel/VOY": "EVER GIVEN 001E"},
                      fields=schema.COMPARE_FIELDS + ["vessel"],
                      field_kinds={"vessel": "text"}, label_map=lm)
        self.assertEqual(r["status"], "OK")

    def test_weight_tolerance(self):
        r = self._cmp({}, {"Gross Wt (kgs)": "131,500 KG"},
                      tolerances={"gross_weight_kg": 0.005})   # within 0.5%
        self.assertEqual(r["status"], "OK")
        self.assertTrue(r["fields"]["gross_weight_kg"]["within_tolerance"])
        r2 = self._cmp({}, {"Gross Wt (kgs)": "133,000 KG"},
                       tolerances={"gross_weight_kg": 0.005})   # 1.5% off: defect
        self.assertEqual(r2["status"], "MISMATCH")

    def test_field_specs_shorthand_and_dict(self):
        specs = schema.field_specs(
            {"fields": {"vessel": ["Vessel"],
                        "marks": {"kind": "text", "labels": ["Marks"],
                                  "tolerance": 0}}})
        self.assertEqual(specs["vessel"]["kind"], "text")
        self.assertEqual(specs["marks"]["labels"], ["Marks"])
        self.assertIn("shipper", specs)                      # built-ins kept
        self.assertIn("vessel", schema.compare_fields({"fields": {"vessel": []}}))


class TestConfidence(unittest.TestCase):
    PAIRS = [("Shipper", "APRIL FAR EAST"), ("Consignee", "EAST BRIGHT"),
             ("Notify", "EAST BRIGHT"), ("POL", "NANTONG"),
             ("POD", "KARACHI"), ("Total Containers", "6"),
             ("Gross Wt (kgs)", "131,058 KG")]

    def test_confident_ok(self):
        r = compare_documents(self.PAIRS, self.PAIRS)
        self.assertEqual(r["confidence"], 1.0)

    def test_fuzzy_match_lowers_confidence(self):
        bl = list(self.PAIRS)
        bl[0] = ("Shipper", "APRIL FAR E4ST")                # typo-ish
        strict = compare_documents(self.PAIRS, bl)
        fuzzy = compare_documents(self.PAIRS, bl, fuzzy=0.85)
        self.assertEqual(strict["status"], "MISMATCH")
        self.assertEqual(fuzzy["status"], "OK")
        self.assertLess(fuzzy["confidence"], 1.0)            # borderline decision


class TestLlmFallback(unittest.TestCase):
    def test_llm_rescues_unreadable_doc(self):
        import tempfile
        SI = [("Shipper", "A"), ("Consignee", "B"), ("Notify", "B"),
              ("POL", "NANTONG"), ("POD", "KARACHI"),
              ("Total Containers", "3"), ("Gross Wt (kgs)", "61,000 KG")]
        BL = [("Shipper", "A"), ("Consignee", "B"), ("Notify", "B"),
              ("POL", "NANTONG"), ("POD", "KARACHI"),
              ("Total Containers", "4"), ("Gross Wt (kgs)", "61,000 KG")]

        def fake_llm(data, filename):
            # a real extractor would send `data` to a model; here it just
            # proves the hook fires and its (title, pairs) are used.
            if "_SI." in filename:
                return "SHIPPING INSTRUCTION", SI
            return "BILL OF LADING", BL

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "inbox").mkdir(); (tmp / "attachments").mkdir()
            (tmp / "attachments/x_SI.bin").write_bytes(b"\x89\x00garbage")
            (tmp / "attachments/x_BL.bin").write_bytes(b"\x89\x00garbage")
            (tmp / "inbox/email_901.json").write_text(json.dumps(
                {"email_id": "email_901", "from": "a@aprilasia.com",
                 "subject": "TO CONFIRM DOCS _ X",
                 "body": "compare", "attachments":
                     ["attachments/x_SI.bin", "attachments/x_BL.bin"]}))
            from sdoc.core import run
            from sdoc.sources import DirSource
            sub, recs, evs = run(DirSource(tmp), cfg={})      # no LLM: unreadable
            self.assertEqual(sub["email_901"]["status"], "NEEDS_REVIEW")
            sub2, _, _ = run(DirSource(tmp), cfg={"llm_extractor": fake_llm})
            self.assertEqual(sub2["email_901"]["status"], "MISMATCH")
            self.assertEqual(sub2["email_901"]["defect_fields"], ["container_count"])


class TestEmlIngestion(unittest.TestCase):
    def test_eml_record_and_attachments(self):
        import tempfile
        from email.message import EmailMessage
        si = ("SHIPPING INSTRUCTION\nShipper: A CO\nConsignee: B CO\n"
              "Notify: B CO\nPOL: NANTONG\nPOD: KARACHI\n"
              "Total Containers: 3\nGross Wt (kgs): 61,000 KG\n")
        bl = si.replace("SHIPPING INSTRUCTION", "BILL OF LADING") \
               .replace("Total Containers: 3", "Total Containers: 4")
        msg = EmailMessage()
        msg["From"] = "Ops Team <ops@aprilasia.com>"
        msg["Subject"] = "TO CONFIRM DOCS _ 9X"
        msg.set_content("Please compare the SI and draft BL.")
        msg.add_alternative("<p>Please compare the SI and draft BL.</p>",
                            subtype="html")
        msg.add_attachment(si.encode(), maintype="text", subtype="plain",
                           filename="x_SI.txt")
        msg.add_attachment(bl.encode(), maintype="text", subtype="plain",
                           filename="x_BL.txt")

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "inbox").mkdir()
            (tmp / "inbox/email_901.eml").write_bytes(msg.as_bytes())
            from sdoc.core import run
            from sdoc.sources import DirSource
            src = DirSource(tmp)
            emails = src.emails()
            self.assertEqual(len(emails), 1)
            rec = emails[0]
            self.assertEqual(rec["email_id"], "email_901")
            self.assertEqual(rec["from"], "ops@aprilasia.com")
            self.assertEqual(len(rec["attachments"]), 2)
            sub, recs, _ = run(src)
            self.assertEqual(sub["email_901"]["status"], "MISMATCH")
            self.assertEqual(sub["email_901"]["defect_fields"], ["container_count"])

    def test_html_body_stripped(self):
        from sdoc.sources import html_to_text
        t = html_to_text("<p>Hello <b>world</b></p><script>bad()</script>"
                         "<style>x{}</style><p>line2</p>")
        self.assertIn("Hello world", t)
        self.assertIn("line2", t)
        self.assertNotIn("bad()", t)


class TestAudit(unittest.TestCase):
    def test_log_run_and_corrections(self):
        import sqlite3
        import tempfile
        report = {"source": "test", "n_emails": 2,
                  "summary": {"statuses": {"OK": 1, "MISMATCH": 1}},
                  "records": {"e1": {"category": "BL_COMPARISON", "status": "OK",
                                     "review_reason": None, "defect_fields": [],
                                     "has_defect": False},
                              "e2": {"category": "BL_COMPARISON", "status": "MISMATCH",
                                     "review_reason": None,
                                     "defect_fields": ["consignee"],
                                     "has_defect": True}},
                  "evidence": {"e1": {"confidence": 1.0}, "e2": {"confidence": 0.4}}}
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "audit.db"
            from sdoc.audit import history, log_run, record_correction
            rid = log_run(db, report, cfg={"fuzzy": None, "fields": {"vessel": {}}})
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM results").fetchone()[0], 2)
            self.assertEqual(con.execute(
                "SELECT defect_fields FROM results WHERE email_id='e2'"
            ).fetchone()[0], '["consignee"]')
            con.close()
            record_correction(db, "e2", "consignee", "B", "B LTD",
                              actor="reviewer")
            self.assertEqual(len(history(db)), 1)
            self.assertIsInstance(rid, int)


class TestHtmlReport(unittest.TestCase):
    def test_diff_marks(self):
        from sdoc.report import _diff_mark
        a, b = _diff_mark("PORT KLANG, MALAYSIA", "PORT KLANG WEST, MALAYSIA")
        self.assertIn("<mark>", b)
        self.assertIn("PORT KLANG", a)


@unittest.skipUnless(BUNDLE.is_dir(), "bundle not extracted")
class TestParallel(unittest.TestCase):
    def test_workers_same_results(self):
        from sdoc.core import run
        from sdoc.sources import DirSource
        only = {f"email_{i:03d}" for i in range(1, 60)}
        s1, _, _ = run(DirSource(BUNDLE), only=only, workers=1)
        s4, _, _ = run(DirSource(BUNDLE), only=only, workers=4)
        self.assertEqual(s1, s4)


@unittest.skipUnless(BUNDLE.is_dir(), "bundle not extracted")
class TestEndToEnd(unittest.TestCase):
    def test_bundle_smoke(self):
        from sdoc.core import run
        from sdoc.sources import DirSource
        sub, recs, evs = run(DirSource(BUNDLE))
        self.assertEqual(len(sub), 520)
        from collections import Counter
        cats = Counter(r["category"] for r in recs.values())
        self.assertEqual(cats["BL_COMPARISON"], 220)
        self.assertEqual(sum(1 for r in recs.values() if r["status"] == "MISMATCH"), 46)
        self.assertEqual(sum(1 for r in recs.values() if r["status"] == "NEEDS_REVIEW"), 20)


if __name__ == "__main__":
    unittest.main()
