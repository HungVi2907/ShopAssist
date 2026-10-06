import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cleaning_rules import resolve_candidate  # noqa: E402
from phase4b_common import normalize_text  # noqa: E402
from validate_phase4b_rules import evaluate  # noqa: E402


def product(title, family, categories=None, features=None, description=None, **flags):
    row = {"parent_asin": "TEST", "title": title, "candidate_family": family,
           "candidate_families": [family], "categories": categories or [],
           "features": features or [], "description": description or [], "details": {}}
    row.update(flags)
    return row


class CleaningRuleTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(normalize_text("  AIR-Fryer\u00a0 15–Bar!  "), "air fryer 15 bar")

    def test_replacement_blade_beats_compatible_wattage(self):
        row = product("Extractor Blade Blender 900W for Ninja", "blender",
                      ["Blender Replacement Parts"], ["Replacement blade for 900W blender"])
        self.assertEqual(resolve_candidate(row)["predicted_label"], "ACCESSORY")

    def test_complete_appliance_with_accessory_terms_is_kept(self):
        coffee = product("Programmable Coffee Maker with Reusable Filter and Carafe", "coffee_maker",
                         ["Coffee Makers"], ["Automatic brewing and 900 watts"], possible_accessory=True)
        fryer = product("Digital Air Fryer with Basket and 1-Pack Parchment Paper", "air_fryer",
                        ["Air Fryers"], ["1700 watts, hot air cooking"], possible_accessory=True)
        for row in (coffee, fryer):
            self.assertEqual(resolve_candidate(row)["decision"], "KEEP")

    def test_manual_coffee_and_electric_moka(self):
        manual = product("French Press Coffee Maker", "coffee_maker", ["French Presses"])
        electric = product("Electric Moka Coffee Maker", "coffee_maker", ["Coffee Makers"],
                           ["Electric base with heat control"], possible_manual_product=True)
        self.assertEqual(resolve_candidate(manual)["predicted_label"], "MANUAL_DEVICE")
        self.assertEqual(resolve_candidate(electric)["decision"], "KEEP")

    def test_stovetop_and_electric_kettle(self):
        stove = product("Whistling Tea Kettle for Gas Stovetop", "electric_kettle", ["Cookware", "Tea Kettles"])
        electric = product("Digital Electric Tea Kettle", "electric_kettle", ["Electric Kettles"],
                           ["Boils water faster than the stovetop with a built-in electric heater"], possible_stovetop_kettle=True)
        self.assertEqual(resolve_candidate(stove)["predicted_label"], "STOVETOP")
        self.assertEqual(resolve_candidate(electric)["decision"], "KEEP")

    def test_rice_warmer_and_multicooker(self):
        warmer = product("Electric Rice Warmer", "rice_cooker", ["Rice Cookers"], ["Keeps cooked rice warm"])
        cooker = product("Electric Pressure Cooker with Rice Program", "rice_cooker", ["Rice Cookers"],
                         ["1200W motor, cooks rice"])
        self.assertEqual(resolve_candidate(warmer)["predicted_label"], "OTHER_NOISE")
        self.assertEqual(resolve_candidate(cooker)["decision"], "KEEP")

    def test_ambiguous_abstention_and_structure(self):
        row = product("Kettle", "electric_kettle", ["Electric Kettles"])
        result = resolve_candidate(row)
        self.assertEqual(result["decision"], "REVIEW")
        self.assertEqual(result["predicted_label"], "REVIEW")
        self.assertTrue(result["rule_id"])
        self.assertIsInstance(result["matched_signals"], list)
        self.assertTrue(result["reason"])
        self.assertEqual(result, resolve_candidate(row))

    def test_ambiguous_rows_excluded_from_binary_metrics(self):
        valid = product("Electric Blender", "blender", ["Blenders"], ["600 watts"])
        unknown = product("Kettle", "electric_kettle", ["Electric Kettles"])
        valid["parent_asin"] = "A"
        unknown["parent_asin"] = "B"
        profile, predictions = evaluate([
            ({"parent_asin": "A", "candidate_family": "blender", "title": "Electric Blender", "audit_label": "VALID_PRODUCT"}, valid),
            ({"parent_asin": "B", "candidate_family": "electric_kettle", "title": "Kettle", "audit_label": "AMBIGUOUS"}, unknown),
        ])
        self.assertEqual(profile["evaluated_rows_excluding_ambiguous"], 1)
        self.assertEqual(profile["ambiguous_true_rows"], 1)
        self.assertEqual(len(predictions), 2)


if __name__ == "__main__":
    unittest.main()
