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


if __name__ == "__main__":
    unittest.main()
