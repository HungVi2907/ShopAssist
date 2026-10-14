"""Offline fixtures for the Phase 13 AI-Silver evaluation boundary."""

from __future__ import annotations

import asyncio
import collections
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import shopassist.evaluation.codex_native as codex_native
import shopassist.evaluation.silver as silver_module
from shopassist.evaluation.silver import (
    PROJECT_ROOT,
    ProviderResponse,
    adjudicate_pair,
    audit_query_with_judges,
    blind_judging_input,
    build_candidate_pool,
    capture_real_generation_claims,
    deterministic_audit,
    evaluate_retrieval_runs,
    extract_negative_intent,
    extract_price_constraints,
    initialise_silver_dataset,
    plan_grouped_split,
    judge_frozen_pools,
    select_pilot_queries,
    validate_silver_dataset,
    weighted_kappa,
)


class FixtureProvider:
    """Clearly synthetic provider used only by this offline test module."""

    def __init__(self, value: dict, *, provider_id: str = "fixture", model: str = "fixture-model") -> None:
        self.value = value
        self.provider_id = provider_id
        self.model = model
        self.calls = 0

    async def complete(self, *, system_prompt: str, payload: dict, schema_name: str) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(value=dict(self.value), request_metadata={"provider": self.provider_id, "model": self.model, "fixture": True})


def query(query_id: str = "Q0001", raw: str = "running shoes under 2000 INR") -> dict:
    return {
        "query_id": query_id, "raw_query": raw, "language": "en", "query_type": "MULTI_CONSTRAINT",
        "planning_category": "Footwear", "expected_status": "SUCCESS", "expected_query_understanding": {
            "semantic_query": "running shoes", "hard_constraints": {"category": "Footwear", "brand": None, "min_price": None,
                "max_price": None, "min_rating": None, "currency": "INR"}, "soft_preferences": [], "needs_clarification": False,
        }, "price_boundary_semantics": {"min_operator": None, "max_operator": None},
    }


def candidate(product_id: str = "P1", *, price: float = 1500.0, category: str = "Footwear") -> dict:
    return {"product_id": product_id, "product_name": "Trail runner", "category": category, "brand": "Acme",
            "discounted_price": price, "rating": 4.4, "retrieval_text": "Acme Trail runner running shoe", "product_specifications": "lightweight"}


class SilverPipelineTests(unittest.TestCase):
    def test_price_operator_and_vietnamese_budget_audit(self):
        self.assertEqual(extract_price_constraints("shoes under 2000 INR")["max_operator"], "<")
        self.assertEqual(extract_price_constraints("shoes up to 2,000 INR")["max_operator"], "<=")
        self.assertEqual(extract_price_constraints("shoes above 500 INR")["min_operator"], ">")
        self.assertEqual(extract_price_constraints("shoes at least 500 INR")["min_operator"], ">=")
        vietnamese = deterministic_audit(query("Q0013", "Tôi cần giày dưới 2 triệu INR"), allowed_categories={"Footwear"})
        codes = {finding["code"] for finding in vietnamese["findings"]}
        self.assertIn("MISSING_PRICE_CONSTRAINT", codes)
        self.assertIn("INCORRECT_PRICE_BOUNDARY_OPERATOR", codes)
        self.assertEqual(vietnamese["deterministic_extraction"]["max_price"], 2_000_000)

    def test_exclusion_is_not_converted_to_positive_preference(self):
        negative = extract_negative_intent("phone case without glitter")
        self.assertEqual(negative["exclusions"], ["without glitter"])
        vietnamese_property = extract_negative_intent("Ốp điện thoại chống sốc, cầm không bị trơn")
        self.assertFalse(vietnamese_property["exclusions"])
        self.assertIn("non-slip", vietnamese_property["positive_preferences"])

    def test_pool_union_provenance_and_blinding(self):
        q = query()
        catalog = {"P1": candidate("P1"), "P2": candidate("P2", price=1800)}
        pool, runs = build_candidate_pool(q, catalog=catalog, catalog_sha256="a" * 64,
                                          method_results={"tfidf": [{"product_id": "P1", "rank": 1, "score": .8}],
                                                          "dense": [{"product_id": "P2", "rank": 1, "score": .9}, {"product_id": "P1", "rank": 2, "score": .7}]},
                                          method_configurations={"tfidf": {"version": 1}, "dense": {"version": 1}}, contribution_depth=2)
        self.assertEqual(pool["candidate_count"], 2)
        self.assertEqual(len(runs), 2)
        membership = next(row for row in pool["candidates"] if row["product_id"] == "P1")["pool_membership"]
        self.assertEqual({row["method"] for row in membership}, {"tfidf", "dense"})
        blind = blind_judging_input(q, pool["candidates"][0])
        encoded = json.dumps(blind)
        self.assertNotIn("rrf_score", encoded)
        self.assertNotIn("pool_membership", encoded)
        self.assertNotIn("rank", encoded)

    def test_malformed_judge_response_is_recorded_not_labeled(self):
        q, product = query(), candidate()
        bad = FixtureProvider({"relevance_grade": "not-a-grade"})
        from shopassist.evaluation.silver import judge_pair
        review = asyncio.run(judge_pair(q, product, bad, "A"))
        self.assertEqual(review["status"], "FAILED")
        self.assertNotIn("relevance_grade", review)

    def test_provider_request_options_are_scoped_to_safe_routing_metadata(self):
        from shopassist.evaluation.silver import OpenAICompatibleJudgeProvider
        provider = OpenAICompatibleJudgeProvider(
            provider_id="fixture", model="fixture-model", base_url="https://fixture.invalid/v1", api_key="fixture-key",
            request_options={"provider": {"allow_fallbacks": False, "data_collection": "deny", "zdr": True}},
        )
        self.assertEqual(provider.request_options["provider"]["data_collection"], "deny")
        with self.assertRaisesRegex(ValueError, "Unsupported evaluation request option"):
            OpenAICompatibleJudgeProvider(
                provider_id="fixture", model="fixture-model", base_url="https://fixture.invalid/v1", api_key="fixture-key",
                request_options={"model": "would-override-the-configured-model"},
            )

    def test_judge_cache_and_adjudication_hard_constraint_override(self):
        q = query()
        q["audited_query_understanding"] = q["expected_query_understanding"]
        q["audited_query_understanding"]["hard_constraints"]["max_price"] = 1000
        q["audited_price_boundary_semantics"] = {"min_operator": None, "max_operator": "<="}
        q["audited_expected_status"] = "SUCCESS"
        q["silver_audit_status"] = "COMPLETE"
        p = candidate(price=1500)
        pool = {"query_id": "Q0001", "candidates": [p]}
        response = {"relevance_grade": 3, "category_violation": False, "brand_violation": False, "price_violation": False,
                    "rating_violation": False, "other_violation": False, "missing_evidence": [], "relevant_evidence_references": ["metadata"],
                    "explanation": "fixture", "confidence": .8}
        a, b = FixtureProvider(response, provider_id="a"), FixtureProvider(response, provider_id="b")
        first_a, first_b = asyncio.run(judge_frozen_pools([q], [pool], judge_a=a, judge_b=b, max_requests=2, reusable_reviews=[]))
        self.assertEqual((a.calls, b.calls), (1, 1))
        asyncio.run(judge_frozen_pools([q], [pool], judge_a=a, judge_b=b, max_requests=1, reusable_reviews=[*first_a, *first_b]))
        self.assertEqual((a.calls, b.calls), (1, 1), "cache must avoid stale-looking re-calls only when fingerprint matches")
        decision = asyncio.run(adjudicate_pair(q, p, first_a[0], first_b[0], None))
        self.assertEqual(decision["final_grade"], 1)
        self.assertTrue(decision["price_violation"])
        self.assertTrue(decision["constraint_override"])

    def test_query_audit_requires_two_ai_calls_and_does_not_copy_v3(self):
        q = query()
        proposal = {"semantic_query": "independent shoes", "hard_constraints": {"category": "Footwear", "brand": None,
                    "min_price": None, "max_price": 2000, "min_rating": None, "currency": "INR"},
                    "price_boundary_semantics": {"min_operator": None, "max_operator": "<"}, "soft_preferences": ["comfortable"],
                    "exclusions": [], "needs_clarification": False, "clarification_reason": None, "expected_status": "SUCCESS", "limitations": []}
        row = asyncio.run(audit_query_with_judges(q, judge_a=FixtureProvider(proposal, provider_id="a"), judge_b=FixtureProvider(proposal, provider_id="b"),
                                                  adjudicator=None, allowed_categories={"Footwear"}))
        self.assertEqual(row["status"], "COMPLETE")
        self.assertEqual(row["final_interpretation"]["semantic_query"], "independent shoes")
        blocked = asyncio.run(audit_query_with_judges(q, judge_a=None, judge_b=None, adjudicator=None, allowed_categories={"Footwear"}))
        self.assertEqual(blocked["status"], "BLOCKED")

    def test_kappa_metrics_and_unjudged_results_not_zero_filled(self):
        self.assertEqual(weighted_kappa([(0, 0), (3, 3)]), 1.0)
        self.assertIsNone(weighted_kappa([(2, 2)]))
        report = evaluate_retrieval_runs([{"query_id": "Q0001", "method": "tfidf", "results": [
            {"product_id": "P1"}, {"product_id": "P2"}]}], [{"query_id": "Q0001", "product_id": "P1", "relevance_grade": "3"}], k=5)
        method = report["methods"]["tfidf"]
        self.assertEqual(method["unjudged_result_count"], 1)
        self.assertEqual(method["judgment_coverage"], .5)
        self.assertEqual(method["precision_at_k_judged"], 1.0)

    def test_real_generation_capture_refuses_synthetic_or_cross_pool_products(self):
        pool = {"query_id": "Q0001", "candidates": [candidate("P1")]}
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "real.jsonl"
            source.write_text(json.dumps({"query_id": "Q0001", "provider": "fixture-provider", "model_version": "fixture-v1",
                "prompt_configuration": "fixture-prompt", "result": {"status": "SUCCESS", "products": [{"product_id": "P1",
                "available_evidence": [{"evidence_id": "P1-E1", "product_id": "P1", "text": "Lightweight runner"}],
                "strengths": [{"claim": "It is lightweight", "evidence_ids": ["P1-E1"]}], "limitations": [],
                "summary_reason": "Good for jogging", "comparison_note": None}]}}) + "\n", encoding="utf-8")
            snapshots, claims = capture_real_generation_claims(source, [pool])
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(len(claims), 2)
            invalid = source.with_name("invalid.jsonl")
            invalid.write_text(source.read_text(encoding="utf-8").replace('"P1"', '"P999"'), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen pool"):
                capture_real_generation_claims(invalid, [pool])

    def test_pilot_selection_and_silver_validator_cannot_claim_human_readiness(self):
        source = [query(f"Q{i:04d}") for i in range(1, 50)]
        source[6]["query_id"] = "Q0007"
        source[7]["query_id"] = "Q0008"
        source[12]["query_id"] = "Q0013"
        selected = select_pilot_queries(source, size=20)
        self.assertEqual(len(selected), 20)
        self.assertTrue({"Q0007", "Q0008", "Q0013"}.issubset(selected))
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "silver"
            initialise_silver_dataset(PROJECT_ROOT / "data/evaluation/phase13/v3", target, source_git_commit="fixture")
            manifest_path = target / "dataset_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["human_verified"] = True
            manifest["phase14_ready"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = validate_silver_dataset(target)
            self.assertEqual(report["phase14_ready"], False)
            self.assertFalse(report["silver_ready"])
            self.assertTrue(any("human_verified" in error for error in report["errors"]))

    def test_validator_refuses_provisional_v3_retrieval_pool(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "silver"
            initialise_silver_dataset(PROJECT_ROOT / "data/evaluation/phase13/v3", target, source_git_commit="fixture")
            (target / "candidate_pools.jsonl").write_text(json.dumps({
                "query_id": "Q0001", "capture_status": "FROZEN", "catalog_sha256": "not-the-manifest-hash",
                "pool_fingerprint": "fixture", "input_reference_status": "UNVERIFIED_V3_REFERENCE",
                "candidate_count": 0, "candidates": [],
            }) + "\n", encoding="utf-8")
            report = validate_silver_dataset(target)
            self.assertFalse(report["silver_ready"])
            self.assertTrue(any("unverified v3 retrieval" in error for error in report["errors"]))

    def test_grouped_split_is_stable_and_does_not_cross_intent_groups(self):
        rows = [query("Q0001"), query("Q0002"), query("Q0003"), query("Q0004")]
        for index, row in enumerate(rows, 1):
            row["raw_query"] = f"running shoes model {index}"
        rows[0]["intent_group"] = rows[1]["intent_group"] = "A"
        rows[2]["intent_group"] = "B"
        rows[3]["intent_group"] = "C"
        first = plan_grouped_split(rows, held_out_fraction=.25, seed=9)
        second = plan_grouped_split(list(reversed(rows)), held_out_fraction=.25, seed=9)
        self.assertEqual(first["status"], "FROZEN")
        self.assertEqual(first["development"], second["development"])
        self.assertEqual(first["held_out"], second["held_out"])
        partition = {qid: "development" for qid in first["development"]} | {qid: "held_out" for qid in first["held_out"]}
        self.assertEqual(partition["Q0001"], partition["Q0002"])


class CodexNativeWorkflowTests(unittest.TestCase):
    """Filesystem-only checks for the interactive Codex-native import boundary."""

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _native_dataset(self, temporary: str, rows: list[dict] | None = None) -> Path:
        """Create a tiny source snapshot and a separate native namespace."""
        source = Path(temporary) / "source"
        source.mkdir()
        source_rows = rows or [query("Q0001", "running shoes under 2000 INR")]
        self._write_jsonl(source / "queries.jsonl", source_rows)
        (source / "dataset_manifest.json").write_text(json.dumps({
            "dataset_version": "fixture-source",
            "catalog_artifact": "data/processed/products.parquet",
            "catalog_sha256": "a" * 64,
            "catalog_product_count": 1,
        }), encoding="utf-8")
        dataset = Path(temporary) / "native"
        codex_native.initialise_codex_native_dataset(source, dataset, source_git_commit="fixture")
        return dataset

    @staticmethod
    def _interpretation() -> dict:
        return {
            "semantic_query": "running shoes",
            "hard_constraints": {
                "category": "Footwear", "brand": None, "min_price": None,
                "max_price": 2000, "min_rating": None, "currency": "INR",
            },
            "price_boundary_semantics": {"min_operator": None, "max_operator": "<"},
            "soft_preferences": ["running"],
            "exclusions": [],
            "needs_clarification": False,
            "clarification_reason": None,
            "expected_status": "SUCCESS",
            "limitations": [],
        }

    def _prepare_query_tasks(self, dataset: Path, query_ids: list[str]) -> dict:
        codex_native.prepare_native_query_tasks(
            dataset,
            query_ids=query_ids,
            allowed_categories={"Footwear", "Mobiles & Accessories"},
        )
        return self._read_jsonl(codex_native.query_task_path(dataset, "A"))[0]

    def _query_submission(self, task: dict, **overrides: object) -> dict:
        row = {
            "query_id": task["query_id"],
            "task_fingerprint": task["task_fingerprint"],
            "interpretation": self._interpretation(),
            "rationale": "The raw request explicitly asks for running shoes under 2000 INR.",
            "confidence": "MEDIUM",
        }
        row.update(overrides)
        return row

    def _prepare_relevance_tasks(self, temporary: str) -> tuple[Path, dict]:
        dataset = self._native_dataset(temporary)
        self._write_jsonl(dataset / "query_audit.jsonl", [{
            "query_id": "Q0001",
            "status": "COMPLETE",
            "input_fingerprint": "fixture-audit",
            "final_interpretation": self._interpretation(),
        }])
        frozen_candidate = {
            **candidate("P1"),
            "pool_membership": [{"method": "tfidf", "rank": 1, "score": 0.9}],
            "pool_position": 1,
        }
        self._write_jsonl(dataset / "candidate_pools.jsonl", [{
            "query_id": "Q0001",
            "capture_status": "FROZEN",
            "catalog_sha256": "a" * 64,
            "pool_fingerprint": "fixture-pool",
            "candidate_count": 1,
            "candidates": [frozen_candidate],
        }])
        codex_native.prepare_native_relevance_tasks(dataset, batch_size=5, max_pairs=90)
        return dataset, self._read_jsonl(codex_native.relevance_task_index_path(dataset))[0]

    @staticmethod
    def _relevance_submission(task: dict, **overrides: object) -> dict:
        row = {
            "query_id": task["query_id"],
            "product_id": task["product_id"],
            "task_fingerprint": task["task_fingerprint"],
            "relevance_grade": 3,
            "category_violation": False,
            "brand_violation": False,
            "price_violation": False,
            "rating_violation": False,
            "other_violation": False,
            "missing_evidence": [],
            "relevant_evidence_references": ["metadata"],
            "explanation": "The candidate is a running shoe within the stated budget.",
            "confidence": 0.9,
        }
        row.update(overrides)
        return row

    def test_native_query_packets_are_blind_and_identical_across_judges(self):
        with tempfile.TemporaryDirectory() as temporary:
            historical = query("Q0001", "running shoes under 2000 INR")
            historical["expected_query_understanding"]["semantic_query"] = "HISTORICAL_LABEL_MUST_NOT_LEAK"
            historical["expected_status"] = "NO_RESULTS"
            dataset = self._native_dataset(temporary, [historical])

            result = codex_native.prepare_native_query_tasks(
                dataset,
                query_ids=["Q0001"],
                allowed_categories={"Footwear", "Mobiles & Accessories"},
            )

            task_a = self._read_jsonl(codex_native.query_task_path(dataset, "A"))[0]
            task_b = self._read_jsonl(codex_native.query_task_path(dataset, "B"))[0]
            self.assertEqual(result["task_count"], 1)
            self.assertEqual(task_a["judge_slot"], "A")
            self.assertEqual(task_b["judge_slot"], "B")
            self.assertEqual(task_a["task_fingerprint"], task_b["task_fingerprint"])
            self.assertEqual(task_a["evidence"], task_b["evidence"])
            self.assertEqual(task_a["evidence"]["raw_query"], historical["raw_query"])
            self.assertEqual(task_a["evidence"]["allowed_categories"], ["Footwear", "Mobiles & Accessories"])
            encoded = json.dumps(task_a["evidence"], ensure_ascii=False)
            for forbidden in (
                "HISTORICAL_LABEL_MUST_NOT_LEAK", "expected_query_understanding",
                "existing_interpretation", "existing_expected_status", "deterministic_audit",
                '"rank"', '"score"', '"rrf_score"',
            ):
                self.assertNotIn(forbidden, encoded)

    def test_native_query_review_import_accepts_valid_blind_task_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = self._native_dataset(temporary)
            task = self._prepare_query_tasks(dataset, ["Q0001"])
            submission = Path(temporary) / "judge_a.jsonl"
            self._write_jsonl(submission, [self._query_submission(task)])

            result = codex_native.import_native_query_reviews(
                dataset, judge_slot="A", submission=submission, model="codex-session-model",
            )

            review = self._read_jsonl(dataset / "judge_a_query_reviews.jsonl")[0]
            self.assertEqual(result["review_count"], 1)
            self.assertEqual(review["task_fingerprint"], task["task_fingerprint"])
            self.assertEqual(review["evidence_fingerprint"], task["evidence_fingerprint"])
            self.assertEqual(review["dataset_fingerprint"], task["dataset_fingerprint"])
            self.assertEqual(review["judge_provider"], codex_native.CODEX_NATIVE_PROVIDER)
            self.assertEqual(review["judge_model"], "codex-session-model")
            self.assertFalse(review["session_provenance"]["external_api_called"])
            self.assertEqual(review["session_provenance"]["context_separation"], "SEPARATE_NATIVE_SUBAGENT_CONTEXT")

    def test_native_query_import_rejects_missing_wrong_duplicate_and_stale_outputs(self):
        cases = {
            "missing_query_id": (lambda task: self._query_submission(task, query_id=""), "missing query_id"),
            "wrong_query_id": (lambda task: self._query_submission(task, query_id="Q9999"), "unknown or unassigned"),
            "stale_fingerprint": (lambda task: self._query_submission(task, task_fingerprint="stale"), "Stale or mismatched"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for name, (build, error) in cases.items():
                with self.subTest(name=name):
                    case_root = Path(temporary) / name
                    case_root.mkdir()
                    dataset = self._native_dataset(str(case_root))
                    task = self._prepare_query_tasks(dataset, ["Q0001"])
                    submission = case_root / "submission.jsonl"
                    self._write_jsonl(submission, [build(task)])
                    with self.assertRaisesRegex(ValueError, error):
                        codex_native.import_native_query_reviews(dataset, judge_slot="A", submission=submission)

            duplicate_root = Path(temporary) / "duplicate"
            duplicate_root.mkdir()
            duplicate_dataset = self._native_dataset(str(duplicate_root))
            duplicate_task = self._prepare_query_tasks(duplicate_dataset, ["Q0001"])
            duplicate_submission = duplicate_root / "submission.jsonl"
            duplicate_row = self._query_submission(duplicate_task)
            self._write_jsonl(duplicate_submission, [duplicate_row, duplicate_row])
            with self.assertRaisesRegex(ValueError, "Duplicate native query review"):
                codex_native.import_native_query_reviews(
                    duplicate_dataset, judge_slot="A", submission=duplicate_submission,
                )

            incomplete_root = Path(temporary) / "incomplete"
            incomplete_root.mkdir()
            incomplete_dataset = self._native_dataset(str(incomplete_root), [
                query("Q0001", "running shoes under 2000 INR"),
                query("Q0002", "running shoes under 2000 INR"),
            ])
            task = self._prepare_query_tasks(incomplete_dataset, ["Q0001", "Q0002"])
            incomplete_submission = incomplete_root / "submission.jsonl"
            self._write_jsonl(incomplete_submission, [self._query_submission(task)])
            with self.assertRaisesRegex(ValueError, "must cover every prepared task; missing="):
                codex_native.import_native_query_reviews(
                    incomplete_dataset, judge_slot="A", submission=incomplete_submission,
                )

    def test_native_relevance_import_rejects_invalid_product_missing_evidence_and_duplicates(self):
        cases = {
            "invalid_product": (lambda task: [self._relevance_submission(task, product_id="P999")], "unknown query/product pair"),
            "missing_evidence": (lambda task: [{key: value for key, value in self._relevance_submission(task).items() if key != "missing_evidence"}], "lacks required evidence/judgment fields"),
            "duplicate": (lambda task: [self._relevance_submission(task), self._relevance_submission(task)], "Duplicate native relevance review"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            for name, (build, error) in cases.items():
                with self.subTest(name=name):
                    case_root = Path(temporary) / name
                    case_root.mkdir()
                    dataset, task = self._prepare_relevance_tasks(str(case_root))
                    submission = case_root / "submission.jsonl"
                    self._write_jsonl(submission, build(task))
                    with self.assertRaisesRegex(ValueError, error):
                        codex_native.import_native_relevance_reviews(
                            dataset, judge_slot="A", submission=submission,
                        )

    def test_native_relevance_import_preserves_native_task_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset, task = self._prepare_relevance_tasks(temporary)
            submission = Path(temporary) / "submission.jsonl"
            self._write_jsonl(submission, [self._relevance_submission(task)])

            result = codex_native.import_native_relevance_reviews(
                dataset, judge_slot="B", submission=submission, model="codex-session-model",
            )

            review = self._read_jsonl(dataset / "judge_b_relevance.jsonl")[0]
            self.assertEqual(result["review_count"], 1)
            self.assertEqual(review["task_fingerprint"], task["task_fingerprint"])
            self.assertEqual(review["evidence_fingerprint"], task["evidence_fingerprint"])
            self.assertEqual(review["prompt_version"], task["prompt_version"])
            self.assertEqual(review["judge_provider"], codex_native.CODEX_NATIVE_PROVIDER)
            self.assertEqual(review["judge_model"], "codex-session-model")
            self.assertFalse(review["session_provenance"]["external_api_called"])

    def test_native_candidate_cap_is_bounded_deterministic_and_method_balanced(self):
        def pooled_candidate(product_id: str, memberships: list[dict]) -> dict:
            return {**candidate(product_id), "pool_membership": memberships}

        pools = [
            {"query_id": "Q0002", "candidates": [
                pooled_candidate("P3", [{"method": "dense", "rank": 1, "score": .9}]),
                pooled_candidate("P4", [{"method": "hybrid", "rank": 2, "score": .8}]),
            ]},
            {"query_id": "Q0001", "candidates": [
                pooled_candidate("P1", [{"method": "hybrid", "rank": 1, "score": .9}]),
                pooled_candidate("P2", [{"method": "tfidf", "rank": 1, "score": .8}]),
            ]},
        ]

        capped, report = codex_native.cap_native_candidate_pools(pools, max_pairs=3)

        self.assertTrue(report["was_capped"])
        self.assertEqual(report["original_pair_count"], 4)
        self.assertEqual(report["selected_pair_count"], 3)
        self.assertEqual(sum(pool["candidate_count"] for pool in capped), 3)
        self.assertEqual([pool["query_id"] for pool in capped], ["Q0001", "Q0002"])
        selected_methods = {
            membership["method"]
            for pool in capped for row in pool["candidates"] for membership in row["pool_membership"]
        }
        self.assertTrue({"dense", "tfidf"}.issubset(selected_methods), "cap must not select by Hybrid rank alone")
        for pool in capped:
            self.assertEqual(
                [row["pool_position"] for row in pool["candidates"]],
                list(range(1, pool["candidate_count"] + 1)),
            )
        untrimmed, untrimmed_report = codex_native.cap_native_candidate_pools(pools, max_pairs=4)
        self.assertFalse(untrimmed_report["was_capped"])
        self.assertEqual(sum(len(pool["candidates"]) for pool in untrimmed), 4)

    def test_native_helpers_never_construct_an_external_provider(self):
        source = inspect.getsource(codex_native)
        self.assertNotIn("OpenAICompatibleJudgeProvider", source)
        self.assertNotIn("from_environment", source)
        self.assertNotIn(".complete(", source)

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                silver_module.OpenAICompatibleJudgeProvider,
                "__init__",
                side_effect=AssertionError("CODEX_NATIVE must not construct an external provider"),
            ) as provider_constructor:
                dataset = self._native_dataset(temporary)
                task = self._prepare_query_tasks(dataset, ["Q0001"])
                submission = Path(temporary) / "submission.jsonl"
                self._write_jsonl(submission, [self._query_submission(task)])
                codex_native.import_native_query_reviews(
                    dataset, judge_slot="A", submission=submission,
                )
            provider_constructor.assert_not_called()

    def test_audit_antigravity_10pair_validation_and_comparison(self):
        audit_dir = silver_module.PROJECT_ROOT / "data/evaluation/phase13/ai_silver/audit_antigravity_10pair"
        self.assertTrue(audit_dir.is_dir(), "Antigravity audit dataset must exist")
        validation = silver_module.validate_silver_dataset(audit_dir)
        self.assertEqual(validation["status"], "PASS")
        self.assertTrue(validation["silver_ready"])
        self.assertEqual(validation["statistics"]["qrels"], 10)
        self.assertEqual(validation["statistics"]["adjudications"], 10)
        self.assertEqual(validation["statistics"]["unresolved"], 0)

        # Cross-model report
        report_path = audit_dir / "cross_model_comparison_report.json"
        self.assertTrue(report_path.is_file(), "Cross-model comparison report must exist")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["metrics"]["total_pairs_compared"], 10)
        self.assertEqual(report["metrics"]["exact_matches"], 10)
        self.assertEqual(report["metrics"]["exact_agreement_rate"], 1.0)

    def test_metadata_consistency_and_silent_disagreement_detection(self):
        with tempfile.TemporaryDirectory() as temporary:
            dataset = Path(temporary) / "silver_test"
            silver_module.initialise_silver_dataset(PROJECT_ROOT / "data/evaluation/phase13/v3", dataset, source_git_commit="fixture")
            manifest_path = dataset / "dataset_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["silver_ready"])

            # Test 1: refresh_manifest explicitly synchronizes silver_ready
            silver_module.refresh_manifest(dataset, silver_ready=True)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["silver_ready"])

            # Test 2: validation_report_silver.json on disk with differing silver_ready is rejected as metadata inconsistency
            report_path = dataset / "validation_report_silver.json"
            report_path.write_text(json.dumps({"silver_ready": False}), encoding="utf-8")
            # Refresh hash so artifact hash itself matches, but content disagrees
            silver_module.refresh_manifest(dataset, silver_ready=True)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["silver_ready"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            validation = silver_module.validate_silver_dataset(dataset)
            disagreements = [e for e in validation["errors"] if "Silent metadata disagreement" in e]
            self.assertTrue(disagreements, "Validator must detect when manifest.silver_ready differs from validation_report_silver.silver_ready")

            # Test 3: Auto-sync from validation_report_silver.json when silver_ready is not explicitly provided
            report_path.write_text(json.dumps({"silver_ready": True}), encoding="utf-8")
            silver_module.refresh_manifest(dataset)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertTrue(manifest["silver_ready"])

    def test_v4_full_silver_integrity_and_frozen_splits(self):
        v4_dir = PROJECT_ROOT / "data/evaluation/phase13/ai_silver/v4_full_silver"
        self.assertTrue(v4_dir.is_dir(), "v4_full_silver dataset must exist")

        validation = silver_module.validate_silver_dataset(v4_dir)
        self.assertEqual(validation["status"], "PASS")
        self.assertEqual(validation["errors"], [])
        self.assertEqual(validation["warnings"], [])
        self.assertTrue(validation["silver_ready"])
        self.assertFalse(validation["phase14_ready"])

        stats = validation["statistics"]
        self.assertEqual(stats["queries"], 200)
        self.assertEqual(stats["query_audits"], 200)
        self.assertEqual(stats["frozen_pools"], 174)
        self.assertEqual(stats["frozen_candidate_pairs"], 2400)
        self.assertEqual(stats["judge_a_reviews"], 2400)
        self.assertEqual(stats["judge_b_reviews"], 2400)
        self.assertEqual(stats["adjudications"], 2400)
        self.assertEqual(stats["qrels"], 2400)
        self.assertEqual(stats["generation_snapshots"], 0)
        self.assertEqual(stats["unresolved"], 0)

        # Frozen split leakage verification
        splits_path = v4_dir / "splits.json"
        self.assertTrue(splits_path.is_file(), "splits.json must exist")
        splits = json.loads(splits_path.read_text(encoding="utf-8"))
        self.assertEqual(splits["status"], "FROZEN")
        self.assertEqual(len(splits["development"]), 140)
        self.assertEqual(len(splits["held_out"]), 60)
        self.assertEqual(splits["leakage_checks"]["intent_groups_crossing_partitions"], [])
        self.assertEqual(splits["leakage_checks"]["exact_duplicate_cross_partition"], [])

        # Human calibration sample export
        calib_path = v4_dir / "human_calibration_sample.jsonl"
        self.assertTrue(calib_path.is_file(), "human_calibration_sample.jsonl must exist")
        calib_rows = silver_module.read_jsonl(calib_path)
        self.assertEqual(len(calib_rows), 40)
        for row in calib_rows:
            self.assertIsNone(row["human_adjudication"]["human_grade"])
            self.assertIsNone(row["human_adjudication"]["reviewer_id"])

        # Grade 3 existence & hard violation capping
        qrels = silver_module.read_csv_rows(v4_dir / "qrels_silver.csv")
        grade_counts = collections.Counter(int(r["relevance_grade"]) for r in qrels)
        self.assertGreater(grade_counts[3], 0, "Expanded benchmark must contain genuine Grade 3 relevance labels")
        self.assertGreater(grade_counts[2], 0)
        self.assertGreater(grade_counts[1], 0)

        # Manifest metadata synchronization
        manifest = json.loads((v4_dir / "dataset_manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["silver_ready"])
        self.assertFalse(manifest["phase14_ready"])
        self.assertTrue(manifest["codex_native"]["split_frozen"])
        self.assertEqual(manifest["codex_native"]["human_calibration_status"], "PENDING")
        self.assertFalse(manifest["codex_native"]["generation_silver_complete"])
        self.assertFalse(manifest["codex_native"]["silver_benchmark_complete"])

    def test_hard_violations_distinguished_from_missing_soft_preference(self):
        intent = {
            "hard_constraints": {"category": "Footwear", "brand": None, "min_price": None, "max_price": 2000.0, "min_rating": None, "currency": "INR"},
            "price_boundary_semantics": {"max_operator": "<"},
            "soft_preferences": ["breathable mesh", "wet weather traction"],
        }
        # Case A: Missing soft preference is unknown/missing evidence, not a hard violation
        product_a = {
            "category": "Footwear",
            "discounted_price": 1500.0,
            "rating": 4.5,
            "product_name": "Running Shoe",
        }
        flags_a, missing_a = silver_module.deterministic_violations(intent, product_a)
        self.assertFalse(any(flags_a.values()), "Missing soft preference must not trigger hard constraint violation")

        # Case B: Price boundary violation strictly triggers price_violation
        product_b = {
            "category": "Footwear",
            "discounted_price": 2500.0,
            "rating": 4.5,
            "product_name": "Running Shoe",
        }
        flags_b, missing_b = silver_module.deterministic_violations(intent, product_b)
        self.assertTrue(flags_b["price_violation"])



if __name__ == "__main__":
    unittest.main()

