"""Source-traceable extraction.

Covers v2 §6.3 and Table 7: every extracted field carries the best available
source evidence, so a reviewer can see where the value came from. PDFs reach
the "approximate visual evidence" tier (page + box); text formats reach the
"text evidence" tier (location + snippet).
"""
import unittest

from sdoc import docs
from sdoc.compare import compare_documents
from sdoc.readers import read_txt

SI = ("SHIPPING INSTRUCTION\n"
      "Shipper: APRIL FAR EAST (M) SDN BHD\n"
      "Consignee: EAST BRIGHT FZ-LLC\n"
      "Notify: EAST BRIGHT FZ-LLC\n"
      "POL: NANTONG, CHINA (CNNTG)\n"
      "POD: KARACHI, PAKISTAN (PKKHI)\n"
      "Total Containers: 6 x 40'HC\n"
      "Gross Wt (kgs): 131,058 KG\n")


class TestTextEvidence(unittest.TestCase):
    def setUp(self):
        self.title, self.pairs = read_txt(SI.encode())
        self.sources = docs.extract_field_sources(self.pairs)

    def test_every_field_carries_evidence(self):
        fields = docs.extract_fields(self.pairs)
        for field in fields:
            self.assertIn(field, self.sources, f"{field} has no source")

    def test_evidence_locates_the_line(self):
        self.assertEqual(self.sources["shipper"]["line"], 2)
        self.assertEqual(self.sources["gross_weight_kg"]["line"], 8)

    def test_evidence_carries_the_source_snippet(self):
        self.assertEqual(self.sources["consignee"]["source_text"],
                         "Consignee: EAST BRIGHT FZ-LLC")

    def test_pairs_still_read_as_label_and_value(self):
        pair = self.pairs[0]
        self.assertEqual(docs.pair_label(pair), "Shipper")
        self.assertEqual(docs.pair_value(pair), "APRIL FAR EAST (M) SDN BHD")

    def test_plain_tuples_are_still_accepted(self):
        legacy = [("Shipper", "ACME"), ("Consignee", "WIDGETS")]
        self.assertEqual(docs.extract_fields(legacy)["shipper"], "ACME")
        self.assertEqual(docs.extract_field_sources(legacy), {})


class TestComparisonCarriesEvidence(unittest.TestCase):
    def test_both_sides_reach_the_comparison_payload(self):
        pairs = read_txt(SI.encode())[1]
        result = compare_documents(pairs, pairs)
        self.assertEqual(result["status"], "OK")
        for field, values in result["fields"].items():
            self.assertIn("si_source", values, f"{field} lost SI evidence")
            self.assertIn("bl_source", values, f"{field} lost BL evidence")

    def test_evidence_survives_a_mismatch(self):
        si = read_txt(SI.encode())[1]
        bl = read_txt(SI.replace("6 x 40'HC", "7 x 40'HC").encode())[1]
        result = compare_documents(si, bl)
        self.assertEqual(result["status"], "MISMATCH")
        self.assertEqual(result["defect_fields"], ["container_count"])
        evidence = result["fields"]["container_count"]
        self.assertEqual(evidence["si_source"]["source_text"],
                         "Total Containers: 6 x 40'HC")
        self.assertEqual(evidence["bl_source"]["source_text"],
                         "Total Containers: 7 x 40'HC")



class TestLlmExtractionKeepsEvidence(unittest.TestCase):
    """Addendum A9: selecting the LLM stage must not lose source evidence.

    The model reports the snippet it read a value from; deterministic code
    resolves that snippet to a position in the transcription.
    """

    RAW = b"SHIPPING INSTRUCTION\nShipper: APRIL FINE PAPER\nGross Wt (kgs): 100 KG\n"

    def _extract(self, extractor):
        from sdoc.extractors import extract_document
        return extract_document(self.RAW, "si.txt",
                                {"extractor": "llm", "llm_extractor": extractor})

    def test_reported_snippet_is_resolved_to_a_location(self):
        def model(data, filename, problems=None):
            return ("SI", [{"label": "Shipper", "value": "APRIL FINE PAPER",
                            "source": {"source_snippet": "Shipper: APRIL FINE PAPER"}}])

        sources = docs.extract_field_sources(self._extract(model)[1])
        self.assertEqual(sources["shipper"]["line"], 2)
        self.assertEqual(sources["shipper"]["source_text"],
                         "Shipper: APRIL FINE PAPER")

    def test_extractor_reporting_no_snippet_still_gets_evidence(self):
        def model(data, filename, problems=None):
            return ("SI", [("Gross Wt (kgs)", "100 KG")])

        sources = docs.extract_field_sources(self._extract(model)[1])
        self.assertEqual(sources["gross_weight_kg"]["line"], 3)

    def test_value_absent_from_the_document_gets_no_false_location(self):
        def model(data, filename, problems=None):
            return ("SI", [{"label": "Consignee", "value": "INVENTED LTD",
                            "source": {"source_snippet": "Consignee: INVENTED LTD"}}])

        source = docs.extract_field_sources(self._extract(model)[1]).get("consignee", {})
        # It may keep the model's own snippet, but must not claim a line it
        # never appeared on.
        self.assertNotIn("line", source)

    def test_extraction_survives_a_failure_to_resolve(self):
        def model(data, filename, problems=None):
            return ("SI", [("Shipper", "APRIL FINE PAPER")])

        doc = self._extract(model)
        self.assertEqual(docs.extract_fields(doc[1])["shipper"], "APRIL FINE PAPER")

if __name__ == "__main__":
    unittest.main()
