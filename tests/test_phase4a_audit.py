import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_phase4a_audit_sample import FAMILIES, MATCH_SOURCES, generate_sample  # noqa: E402


class Phase4AAuditTests(unittest.TestCase):
    def test_sample_is_reproducible_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "candidates.jsonl"
            records = []
            for family in FAMILIES:
                for match in MATCH_SOURCES:
                    for number in range(5):
                        evidence = {"title_only": ["title"], "taxonomy_only": ["taxonomy"],
                                    "both": ["title", "taxonomy"]}[match]
                        records.append({
                            "parent_asin": f"{family}-{match}-{number}",
                            "candidate_family": family,
                            "candidate_families": [family],
                            "matched_by": evidence,
                            "match_details": {family: {"matched_by": evidence}},
                            "title": f"{family} {number}",
                            "categories": ["Kitchen"], "features": [], "description": [], "details": {},
                            "possible_accessory": number == 0,
                            "possible_manual_product": family == "coffee_maker" and number == 1,
                            "possible_stovetop_kettle": family == "electric_kettle" and number == 1,
                            "ambiguous_family": False,
                        })
            for number in range(5):
                records.append({
                    "parent_asin": f"multi-{number}", "candidate_family": None,
                    "candidate_families": ["coffee_maker", "blender"],
                    "matched_by": ["title", "taxonomy"], "ambiguous_family": True,
                    "title": "Combo", "possible_accessory": False,
                    "possible_manual_product": False, "possible_stovetop_kettle": False,
                })
            source.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
            source_before = hashlib.sha256(source.read_bytes()).hexdigest()
            output = root / "sample.csv"
            profile_path = root / "profile.json"
            report = root / "profile.md"
            profile = generate_sample(source, output, profile_path, report, seed=19,
                                      per_stratum=2, per_target=2)
            sample_before = output.read_bytes()
            profile_before = profile_path.read_bytes()
            generate_sample(source, output, profile_path, report, seed=19,
                            per_stratum=2, per_target=2)
            self.assertEqual(output.read_bytes(), sample_before)
            self.assertEqual(profile_path.read_bytes(), profile_before)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_before)
            with output.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            asins = [row["parent_asin"] for row in rows]
            self.assertEqual(len(asins), len(set(asins)))
            self.assertEqual(set(asins).issubset({row["parent_asin"] for row in records}), True)
            self.assertEqual(profile["sample_count"], len(rows))
            self.assertEqual(profile["unique_sample_asins"], len(set(asins)))
            self.assertEqual(set(FAMILIES).issubset({row["candidate_family"] for row in rows}), True)
            self.assertEqual(set(MATCH_SOURCES).issubset({row["match_source"] for row in rows}), True)
            self.assertTrue(all(profile["primary_strata_counts"].values()))
            self.assertTrue(all(row[key] == "" for row in rows for key in
                                ("audit_label", "audit_family", "audit_reason", "audit_notes")))
            self.assertEqual(set(profile["targeted_oversample_counts"]),
                             {"multi_family", "manual_coffee", "stovetop_kettle", "accessory"})
            self.assertGreater(profile["high_risk_counts"]["ambiguous"], 0)
            self.assertGreater(profile["high_risk_counts"]["manual_flag"], 0)
            self.assertGreater(profile["high_risk_counts"]["stovetop_flag"], 0)
            self.assertGreater(profile["high_risk_counts"]["accessory_flag"], 0)
            self.assertTrue(report.exists())


if __name__ == "__main__":
    unittest.main()
