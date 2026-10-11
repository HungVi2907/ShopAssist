"""Deterministic Phase 13 utility checks; synthetic test data are not labels."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_phase13_dataset import build
from scripts.capture_phase13_generation import capture as capture_generation
from scripts.prepare_phase13_annotation_tasks import export as export_tasks
from scripts.validate_phase13_dataset import near_duplicates, read_csv, read_jsonl, validate


class Phase13DatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dataset = Path(self.temp.name) / "v1"
        build(self.dataset)

    def _queries(self):
        return read_jsonl(self.dataset / "queries.jsonl")

    def _put_queries(self, rows):
        (self.dataset / "queries.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    def _put_csv(self, name, rows):
        path = self.dataset / name
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def test_pilot_shape_unicode_and_round_trip(self):
        report = validate(self.dataset)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["statistics"]["queries"], 40)
        self.assertEqual(report["statistics"]["by_language"], {"en": 30, "vi": 10})
        self.assertIn("Tôi cần", self._queries()[2]["raw_query"])
        self.assertEqual(read_csv(self.dataset / "qrels.csv"), [])
        self.assertFalse(report["phase14_ready"])

    def test_duplicate_id_and_query(self):
        rows = self._queries()
        rows[1]["query_id"] = rows[0]["query_id"]
        rows[1]["raw_query"] = rows[0]["raw_query"]
        self._put_queries(rows)
        errors = validate(self.dataset)["errors"]
        self.assertTrue(any("Duplicate query IDs" in e for e in errors))
        self.assertTrue(any("Exact duplicate" in e for e in errors))

    def test_taxonomy_and_boundary_metadata(self):
        rows = self._queries()
        rows[0]["query_type"] = "WRONG"
        rows[0]["expected_query_understanding"] = {"semantic_query": "running shoes", "hard_constraints": {"category": "Footwear", "max_price": 2000}, "soft_preferences": [], "needs_clarification": False}
        rows[0]["expected_status"] = "SUCCESS"
        self._put_queries(rows)
        errors = validate(self.dataset)["errors"]
        self.assertTrue(any("taxonomy" in e for e in errors))
        self.assertTrue(any("max_operator" in e for e in errors))

    def test_invalid_product_id_grade_and_duplicate_qrel(self):
        row = {"query_id": "Q0001", "product_id": "missing", "reviewer_a_grade": "4", "reviewer_b_grade": "2", "adjudicated_grade": "4",
               "category_violation": "false", "brand_violation": "false", "price_violation": "false", "rating_violation": "false", "other_violation": "false", "disagreement_reason": ""}
        self._put_csv("qrels.csv", [row, row])
        manifest = json.loads((self.dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
        manifest["qrel_count"] = 2
        (self.dataset / "dataset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        errors = validate(self.dataset, catalog_ids={"known"})["errors"]
        self.assertTrue(any("Duplicate qrel" in e for e in errors))
        self.assertTrue(any("Invalid qrel query or product" in e for e in errors))
        self.assertTrue(any("invalid adjudicated_grade" in e for e in errors))

    def test_split_leakage_and_missing_reviews(self):
        rows = self._queries()
        rows[1]["intent_group"] = rows[0]["intent_group"]
        self._put_queries(rows)
        (self.dataset / "splits.json").write_text(json.dumps({"status": "FROZEN", "development": ["Q0001"], "held_out": ["Q0002"]}), encoding="utf-8")
        errors = validate(self.dataset)["errors"]
        self.assertTrue(any("intent group crosses" in e for e in errors))
        self.assertTrue(any("unadjudicated" in e for e in errors))

    def test_lexical_near_duplicate_cross_split(self):
        rows = self._queries()
        rows[1]["raw_query"] = "for jogging running shoes"
        self._put_queries(rows)
        (self.dataset / "splits.json").write_text(json.dumps({"status": "NOT_FROZEN", "development": ["Q0001"], "held_out": ["Q0002"]}), encoding="utf-8")
        self.assertTrue(any("Near-duplicate queries cross split" in e for e in validate(self.dataset)["errors"]))

    def test_missing_annotation_schema_columns(self):
        (self.dataset / "qrels.csv").write_text("query_id,product_id\n", encoding="utf-8")
        self.assertTrue(any("qrels.csv: missing columns" in e for e in validate(self.dataset)["errors"]))

    def test_near_duplicate_flag_and_manifest_mismatch(self):
        examples = [{"query_id": "Q0001", "raw_query": "running shoes for daily jogging"}, {"query_id": "Q0002", "raw_query": "daily jogging running shoes for"}]
        self.assertEqual(len(near_duplicates(examples)), 1)
        manifest = json.loads((self.dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
        manifest["catalog_sha256"] = "0" * 64
        (self.dataset / "dataset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertTrue(any("Catalog SHA-256" in e for e in validate(self.dataset)["errors"]))

    def test_blind_task_export(self):
        task_dir = Path(self.temp.name) / "tasks"
        counts = export_tasks(self.dataset, task_dir)
        self.assertEqual(counts, {"queries": 40, "candidate_pairs": 0, "claims": 0})
        self.assertNotIn("rrf_score", (task_dir / "relevance_tasks.csv").read_text(encoding="utf-8-sig"))
        self.assertEqual(len(read_csv(task_dir / "query_tasks.csv")), 40)

    def test_real_result_claim_flattening_and_evidence_round_trip(self):
        source = Path(self.temp.name) / "saved.jsonl"
        source.write_text(json.dumps({
            "query_id": "Q0001", "generation_snapshot": "sha256:test-snapshot",
            "result": {"status": "SUCCESS", "products": [{
                "product_id": "P1", "summary_reason": "Suitable for jogging.", "comparison_note": None,
                "available_evidence": [{"evidence_id": "P1-E1", "product_id": "P1", "text": "Running shoe"}],
                "strengths": [{"claim": "Running shoe", "evidence_ids": ["P1-E1"]}], "limitations": [],
            }]},
        }) + "\n", encoding="utf-8")
        output = Path(self.temp.name) / "claim-capture.csv"
        self.assertEqual(capture_generation(source, self.dataset, output), 2)
        rows = read_csv(output)
        self.assertEqual(json.loads(rows[0]["evidence_text_json"]), {"P1-E1": "Running shoe"})
        self.assertEqual(rows[0]["reviewer_a_support"], "")


    def test_price_boundary_operators_strict_and_inclusive(self):
        rows = self._queries()
        rows[0]["expected_query_understanding"] = {
            "semantic_query": "running shoes",
            "hard_constraints": {"category": "Footwear", "min_price": 500, "max_price": 2000},
            "soft_preferences": [],
            "needs_clarification": False,
        }
        rows[0]["expected_status"] = "SUCCESS"
        rows[0]["price_boundary_semantics"] = {"min_operator": "=", "max_operator": "<="}
        self._put_queries(rows)
        errors = validate(self.dataset)["errors"]
        self.assertTrue(any("min_operator inconsistent with min_price" in e for e in errors))

        # Test valid strict and inclusive operators
        rows[0]["price_boundary_semantics"] = {"min_operator": ">", "max_operator": "<"}
        self._put_queries(rows)
        errors = validate(self.dataset)["errors"]
        self.assertFalse(any("operator inconsistent" in e for e in errors))

    def test_zero_result_semantics_and_catalog_boundary_verification(self):
        pools = [{
            "query_id": "Q0001",
            "phase10_status": "NO_RESULTS",
            "catalog_sha256": json.loads((self.dataset / "dataset_manifest.json").read_text(encoding="utf-8"))["catalog_sha256"],
            "candidate_count": 1,
            "candidates": [{"product_id": "p1", "rank": 1, "retrieval_text": "text"}],
            "no_result_verified": True,
            "catalog_eligible_count": 0,
            "provenance": {"service": "HybridRetrievalService"},
        }]
        (self.dataset / "candidate_pools.jsonl").write_text(json.dumps(pools[0]) + "\n", encoding="utf-8")
        errors = validate(self.dataset, catalog_ids={"p1"})["errors"]
        self.assertTrue(any("invalid catalog-verified no-result claim" in e for e in errors))

    def test_claim_evidence_semantics_and_invalid_labels(self):
        claims = [{
            "claim_id": "CLM-0001",
            "query_id": "Q0001",
            "product_id": "p1",
            "claim": "12 hours battery life",
            "evidence_ids_json": json.dumps(["EVID-01", "EVID-02"]),
            "evidence_text_json": json.dumps({"EVID-01": "Long lasting battery"}),
            "generation_snapshot": "test-snapshot",
            "reviewer_a_id": "rev_a",
            "reviewer_b_id": "rev_b",
            "adjudicated_support": "UNSUPPORTED",
        }]
        self._put_csv("generation_claims.csv", claims)
        errors = validate(self.dataset, catalog_ids={"p1"})["errors"]
        self.assertTrue(any("Claim evidence mismatch" in e for e in errors))

    def test_readiness_gates_strictly_enforced(self):
        report = validate(self.dataset)
        self.assertEqual(report["status"], "PASS")
        self.assertFalse(report["phase14_ready"])
        gates = report["readiness_gates"]
        self.assertFalse(gates["interpretations_adjudicated"])
        self.assertFalse(gates["candidate_pools_frozen"])
        self.assertFalse(gates["relevance_complete"])
        self.assertFalse(gates["claims_adjudicated"])
        self.assertFalse(gates["split_frozen"])


if __name__ == "__main__":
    unittest.main()

