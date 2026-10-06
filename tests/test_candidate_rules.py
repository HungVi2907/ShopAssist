import sys
from pathlib import Path
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from candidate_rules import detect_candidate  # noqa: E402


class CandidateRulesTests(unittest.TestCase):
    def test_blender(self):
        match = detect_candidate({"title": "Ninja Professional Blender", "categories": []})
        self.assertEqual(match["candidate_families"], ["blender"])
        self.assertEqual(match["matched_by"], ["title"])
        self.assertFalse(match["possible_accessory"])

    def test_blender_replacement(self):
        match = detect_candidate({"title": "Replacement Blade for Ninja Blender", "categories": []})
        self.assertTrue(match["possible_accessory"])
        self.assertIn("replacement", match["matched_accessory_keywords"])

    def test_manual_coffee(self):
        match = detect_candidate({"title": "French Press Coffee Maker", "categories": []})
        self.assertTrue(match["possible_manual_product"])

    def test_stovetop_kettle(self):
        match = detect_candidate({"title": "Whistling Stovetop Tea Kettle", "categories": []})
        self.assertEqual(match["candidate_families"], ["electric_kettle"])
        self.assertTrue(match["possible_stovetop_kettle"])

    def test_air_fryer(self):
        match = detect_candidate({"title": "Digital Air Fryer 5QT", "categories": []})
        self.assertEqual(match["candidate_families"], ["air_fryer"])

    def test_taxonomy_only_and_missing_fields(self):
        match = detect_candidate({"categories": ["Kitchen & Dining", "Rice Cookers"]})
        self.assertEqual(match["matched_by"], ["taxonomy"])
        self.assertEqual(match["candidate_family"], "rice_cooker")
        self.assertIsNone(detect_candidate({"title": None, "categories": None}))

    def test_multi_family(self):
        match = detect_candidate({"title": "Coffee Maker and Blender Combo", "categories": []})
        self.assertEqual(match["candidate_families"], ["coffee_maker", "blender"])
        self.assertTrue(match["ambiguous_family"])
        self.assertIsNone(match["candidate_family"])


if __name__ == "__main__":
    unittest.main()
