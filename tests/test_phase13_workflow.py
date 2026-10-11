"""Negative and round-trip checks for Phase 13 review and release gates."""

from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.assemble_phase13_ground_truth import assemble_claims, assemble_qrels, assemble_queries, assemble_version
from scripts.expand_phase13_dataset import NEW_QUERIES, TYPES
from scripts.plan_phase13_splits import freeze, freeze_version, plan
from scripts.prepare_phase13_annotation_tasks import export
from scripts.promote_phase13_capture import promote
from scripts.validate_phase13_dataset import ROOT, read_jsonl, validate, weighted_kappa


V2 = ROOT / "data/evaluation/phase13/v2"


class Phase13WorkflowTests(unittest.TestCase):
    def test_expansion_preserves_pilot_and_covers_taxonomy(self):
        pilot = read_jsonl(ROOT / "data/evaluation/phase13/v1/queries.jsonl")
        queries = read_jsonl(V2 / "queries.jsonl")
        self.assertEqual(queries[:40], pilot)
        self.assertEqual(len(queries), 200)
        self.assertEqual(len({q["raw_query"].casefold() for q in queries}), 200)
        self.assertEqual({q["planning_category"] for q in queries[40:]}, set(NEW_QUERIES))
        self.assertEqual({q["query_type"] for q in queries[40:]}, set(TYPES))
        self.assertTrue(all(q["annotation_status"] == "UNREVIEWED_DRAFT" and q["expected_status"] is None for q in queries))
        report = validate(V2)
        self.assertEqual(report["status"], "PASS", report["errors"])
        self.assertFalse(report["phase14_ready"])
        self.assertFalse(report["readiness_gates"]["interpretations_adjudicated"])
        self.assertFalse(report["readiness_gates"]["regression_tests"])

    def test_query_adjudication_requires_two_real_reviews_and_disagreement_reason(self):
        query = {"query_id": "Q0001", "raw_query": "red shoes"}
        base = {"query_id": "Q0001", "semantic_query": "red shoes", "category": "Footwear",
                "brand": "", "min_price": "", "max_price": "", "min_rating": "", "currency": "INR",
                "min_operator": "", "max_operator": "", "soft_preferences_json": "[]",
                "needs_clarification": "false", "clarification_reason": "", "expected_status": "SUCCESS"}
        reviews = [dict(base, annotator_id="human_a"), dict(base, annotator_id="human_b")]
        decision = dict(base, adjudicator_id="adjudicator")
        result = assemble_queries([query], reviews, [decision])
        self.assertEqual(result[0]["annotation_status"], "ADJUDICATED")
        self.assertEqual(result[0]["expected_query_understanding"]["hard_constraints"]["category"], "Footwear")
        with self.assertRaisesRegex(ValueError, "two distinct"):
            assemble_queries([query], [reviews[0], dict(reviews[1], annotator_id="human_a")], [decision])
        with self.assertRaisesRegex(ValueError, "disagreement"):
            assemble_queries([query], [reviews[0], dict(reviews[1], expected_status="NO_RESULTS")], [decision])
        with self.assertRaisesRegex(ValueError, "two distinct"):
            assemble_queries([query], reviews[:1], [decision])

    def test_qrel_adjudication_rejects_unjudged_and_constraint_conflict(self):
        pools = [{"query_id": "Q0001", "candidates": [{"product_id": "p1"}]}]
        base = {"query_id": "Q0001", "product_id": "p1", "relevance_grade": "2",
                "category_violation": "false", "brand_violation": "false", "price_violation": "false",
                "rating_violation": "false", "other_violation": "false"}
        reviews = [dict(base, annotator_id="human_a"), dict(base, annotator_id="human_b")]
        decision = dict(base, adjudicator_id="adjudicator", adjudicated_grade="2")
        self.assertEqual(assemble_qrels(pools, reviews, [decision])[0]["adjudicated_grade"], "2")
        with self.assertRaisesRegex(ValueError, "Every frozen candidate"):
            assemble_qrels(pools, reviews, [])
        with self.assertRaisesRegex(ValueError, "hard violation"):
            assemble_qrels(pools, reviews, [dict(decision, price_violation="true")])
        with self.assertRaisesRegex(ValueError, "disagreement"):
            assemble_qrels(pools, [reviews[0], dict(reviews[1], relevance_grade="1")], [decision])

    def test_claim_adjudication_requires_independent_review(self):
        claims = [{"claim_id": "c1", "claim": "Battery lasts 12 hours"}]
        review = {"claim_id": "c1", "support_label": "UNSUPPORTED", "factual_correctness": "INCORRECT",
                  "recommendation_relevance": "RELEVANT", "missing_information_handling": "NOT_APPLICABLE"}
        reviews = [dict(review, annotator_id="human_a"), dict(review, annotator_id="human_b")]
        decision = {"claim_id": "c1", "adjudicator_id": "adjudicator", "adjudicated_support": "UNSUPPORTED",
                    "adjudicated_factual": "INCORRECT", "adjudicated_relevance": "RELEVANT",
                    "missing_information_handling": "NOT_APPLICABLE"}
        self.assertEqual(assemble_claims(claims, reviews, [decision])[0]["adjudicated_support"], "UNSUPPORTED")
        with self.assertRaisesRegex(ValueError, "two distinct"):
            assemble_claims(claims, [reviews[0], dict(reviews[1], annotator_id="human_a")], [decision])
        with self.assertRaisesRegex(ValueError, "disagreement"):
            assemble_claims(claims, [reviews[0], dict(reviews[1], support_label="SUPPORTED")], [decision])

    def test_split_is_reproducible_grouped_and_cannot_freeze_draft(self):
        queries = read_jsonl(V2 / "queries.jsonl")
        rows = copy.deepcopy(queries[:12])
        rows[1]["intent_group"] = rows[0]["intent_group"]
        first = plan(rows, seed=73)
        self.assertEqual(first, plan(list(reversed(rows)), seed=73))
        part = {qid: "development" for qid in first["development"]} | {qid: "held_out" for qid in first["held_out"]}
        self.assertEqual(part[rows[0]["query_id"]], part[rows[1]["query_id"]])
        with self.assertRaisesRegex(ValueError, "ineligible"):
            freeze(V2, plan(queries))
        with tempfile.TemporaryDirectory() as temporary:
            release = Path(temporary) / "unreviewed_release"
            with self.assertRaisesRegex(ValueError, "ineligible"):
                freeze_version(V2, release, plan(queries))
            self.assertFalse(release.exists())

    def test_export_reviewer_ids_and_preflight(self):
        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary) / "tasks"
            with self.assertRaisesRegex(ValueError, "distinct"):
                export(V2, dest, ("same", "same"))
            counts = export(V2, dest, ("reviewer_a", "reviewer_b"))
            self.assertEqual(counts["queries"], 200)
            self.assertTrue((dest / "query_tasks_reviewer_a.csv").is_file())
            self.assertTrue((dest / "query_tasks_reviewer_b.csv").is_file())
            with self.assertRaises(FileExistsError):
                export(V2, dest)

    def test_hash_tampering_and_kappa_small_sample(self):
        self.assertIsNone(weighted_kappa([(2, 2)]))
        self.assertEqual(weighted_kappa([(0, 0), (3, 3)]), 1.0)
        with tempfile.TemporaryDirectory() as temporary:
            dest = Path(temporary)
            for name in ("queries.jsonl", "candidate_pools.jsonl", "qrels.csv", "query_annotations.csv",
                         "relevance_annotations.csv", "generation_claims.csv", "splits.json", "dataset_manifest.json"):
                (dest / name).write_bytes((V2 / name).read_bytes())
            with (dest / "queries.jsonl").open("a", encoding="utf-8") as handle:
                handle.write("\n")
            report = validate(dest)
            self.assertEqual(report["status"], "FAIL")
            self.assertTrue(any("artifact hash mismatch" in error for error in report["errors"]))

    def test_file_assembly_round_trip_and_capture_gate(self):
        queries = read_jsonl(V2 / "queries.jsonl")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reviews_path = root / "query_reviews.csv"
            fields = ["query_id", "annotator_id", "semantic_query", "category", "brand", "min_price", "max_price",
                      "min_rating", "currency", "min_operator", "max_operator", "soft_preferences_json",
                      "needs_clarification", "clarification_reason", "expected_status", "comment"]
            with reviews_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for q in queries:
                    for reviewer in ("synthetic_test_a", "synthetic_test_b"):
                        writer.writerow({"query_id": q["query_id"], "annotator_id": reviewer,
                                         "semantic_query": q["raw_query"], "category": q["planning_category"],
                                         "currency": "INR", "soft_preferences_json": "[]",
                                         "needs_clarification": "false", "expected_status": "SUCCESS"})
            decisions_path = root / "query_decisions.jsonl"
            decisions_path.write_text("".join(json.dumps({"query_id": q["query_id"],
                "semantic_query": q["raw_query"], "category": q["planning_category"], "brand": "",
                "min_price": "", "max_price": "", "min_rating": "", "currency": "INR",
                "min_operator": "", "max_operator": "", "soft_preferences_json": "[]",
                "needs_clarification": "false", "clarification_reason": "", "expected_status": "SUCCESS",
                "adjudicator_id": "synthetic_test_adjudicator"}) + "\n" for q in queries), encoding="utf-8")
            blank = root / "blank.csv"
            blank.write_text("query_id,product_id,annotator_id,relevance_grade\n", encoding="utf-8")
            empty_decision = root / "empty_decision.csv"
            empty_decision.write_text("query_id,product_id,adjudicator_id,adjudicated_grade\n", encoding="utf-8")
            empty_claim_review = root / "empty_claim_review.csv"
            empty_claim_review.write_text("claim_id,annotator_id,support_label\n", encoding="utf-8")
            empty_claim_decision = root / "empty_claim_decision.csv"
            empty_claim_decision.write_text("claim_id,adjudicator_id,adjudicated_support\n", encoding="utf-8")
            out = root / "synthetic_version"
            result = assemble_version(V2, out, query_reviews=reviews_path, query_decisions=decisions_path,
                                      relevance_reviews=blank, relevance_decisions=empty_decision,
                                      claim_reviews=empty_claim_review, claim_decisions=empty_claim_decision)
            self.assertEqual(result["queries"], 200)
            self.assertEqual(validate(out)["status"], "PASS")
            self.assertFalse(validate(out)["phase14_ready"])
            capture = root / "empty_capture.jsonl"
            capture.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "every eligible"):
                promote(out, capture, root / "invalid_promoted", kind="candidates")


if __name__ == "__main__":
    unittest.main()
