"""Phase 14 — Educational Retrieval & Reranking Evaluation Runner.

Executes the complete experimental evaluation for the ShopAssist AI Engineering project:
1. Validates the frozen AI-Silver v4 benchmark (`data/evaluation/phase13/ai_silver/v4_full_silver/`).
2. Computes mathematically rigorous ranking metrics for TF-IDF, Dense, and Hybrid RRF
   across All (174), Development (140), and Held-Out (60) splits.
3. Evaluates Phase 11 reranking methods (RRF vs Multi-Signal vs Cross-Encoder).
4. Generates an authentic RAG execution trace (Phase 8 -> 9 -> 10 -> 11 -> 12).
5. Runs the LLM-as-a-Judge evaluation rubric demonstration.
6. Writes versioned machine-readable artifacts and summary report to `data/evaluation/phase14/v1/`.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time

from shopassist.evaluation.phase14_evaluator import (
    Phase14Dataset,
    build_rag_educational_trace,
    evaluate_deterministic_grounding,
    evaluate_reranking,
    evaluate_retrieval_runs,
)
from shopassist.evaluation.phase14_judge import (
    JUDGE_PROMPT_VERSION,
    JUDGING_RUBRIC_VERSION,
    LLMJudgeResponseSchema,
    run_llm_judge,
    run_llm_judge_with_gateway,
)
from shopassist.evaluation.silver import file_sha256, validate_silver_dataset
from shopassist.llm.schemas import QueryUnderstandingOutput
from shopassist.recommendation.schemas import LLMRecommendationPayload
from shopassist.llm_gateway.adapters.gemini import GeminiAdapter
from shopassist.llm_gateway.adapters.groq import GroqAdapter
from shopassist.llm_gateway.adapters.openrouter import OpenRouterAdapter
from shopassist.llm_gateway.config import GatewaySettings
from shopassist.llm_gateway.gateway import Gateway
from shopassist.llm_gateway.registry import ProviderRegistry
from shopassist.llm_gateway.schemas import SCHEMA_IDS, TaskType
from shopassist.llm_gateway.telemetry import TelemetrySink

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("phase14_runner")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_DIR = ROOT / "data/evaluation/phase13/ai_silver/v4_full_silver"
DEFAULT_CATALOG_PATH = ROOT / "data/processed/products.parquet"
DEFAULT_CASES_PATH = ROOT / "data/interim/phase11/phase11_reranking_cases.json"
DEFAULT_OUTPUT_DIR = ROOT / "data/evaluation/phase14/v1"


async def _run_gateway_judge_if_eligible(query: str, evidence: str, recommendation: str):
    """Return (result, diagnostics); None result means safely skipped pre-dispatch."""
    settings = GatewaySettings()
    registry = ProviderRegistry(settings, {
        SCHEMA_IDS[TaskType.QUERY_UNDERSTANDING]: QueryUnderstandingOutput,
        SCHEMA_IDS[TaskType.RECOMMENDATION_GENERATION]: LLMRecommendationPayload,
        SCHEMA_IDS[TaskType.LLM_JUDGE]: LLMJudgeResponseSchema,
    })
    route = registry.primary_route(TaskType.LLM_JUDGE)
    reason = registry.ineligibility(route.route_id, TaskType.LLM_JUDGE) if route else None
    if reason is not None:
        return None, {"status": "LIVE_SKIPPED", "reason": reason.value}
    if route is None or not os.environ.get(route.credential_env, "").strip():
        return None, {"status": "LIVE_SKIPPED", "reason": "CREDENTIAL_UNAVAILABLE"}

    gateway = Gateway(settings, registry, {
        "gemini": GeminiAdapter(), "openrouter": OpenRouterAdapter(), "groq": GroqAdapter(),
    }, telemetry=TelemetrySink(settings))
    try:
        result = await run_llm_judge_with_gateway(gateway, query, evidence, recommendation)
        return result, {"status": "LIVE_SUCCESS", "execution_mode": "LIVE_API"}
    finally:
        await gateway.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 14 AI Engineering Evaluation Runner")
    parser.add_argument("--benchmark-dir", type=Path, default=DEFAULT_BENCHMARK_DIR)
    parser.add_argument("--catalog-path", type=Path, default=DEFAULT_CATALOG_PATH)
    parser.add_argument("--cases-path", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=14014)
    parser.add_argument("--skip-reranking", action="store_true", help="Skip reranking benchmarks")
    parser.add_argument("--run-live-judge", action="store_true", help="Attempt live Gemini LLM Judge call")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 78)
    print("SHOPASSIST PHASE 14: AI ENGINEERING EXPERIMENTAL EVALUATION")
    print("=" * 78)
    print(f"Benchmark Dir: {args.benchmark_dir}")
    print(f"Output Dir:    {args.output_dir}")
    print(f"Random Seed:   {args.seed}")
    print(f"Timestamp:     {datetime.now(timezone.utc).isoformat()}")

    # -------------------------------------------------------------------------
    # Step 1: Validate Frozen Benchmark Foundation
    # -------------------------------------------------------------------------
    print("\n[Step 1] Validating frozen AI-Silver v4 benchmark...")
    validation = validate_silver_dataset(args.benchmark_dir, catalog_path=args.catalog_path)
    if validation.get("status") != "PASS":
        print(f"ERROR: AI-Silver v4 validation failed: {validation.get('errors')}")
        return 1
    print("  -> AI-Silver v4 benchmark validated: PASS (0 errors, 0 warnings)")

    # -------------------------------------------------------------------------
    # Step 2: Load In-Memory Dataset
    # -------------------------------------------------------------------------
    print("\n[Step 2] Loading dataset and catalog into memory...")
    dataset = Phase14Dataset.load(args.benchmark_dir, catalog_path=args.catalog_path)
    print(f"  -> Queries: {len(dataset.queries)}")
    print(f"  -> Qrels: {len(dataset.qrels)}")
    print(f"  -> Candidate Pools: {len(dataset.candidate_pools)}")
    print(f"  -> Retrieval Runs: {len(dataset.retrieval_runs)}")
    print(f"  -> Catalog Items: {len(dataset.catalog)}")
    print(f"  -> Splits: dev={len(dataset.splits.get('development', []))}, held_out={len(dataset.splits.get('held_out', []))}")

    # -------------------------------------------------------------------------
    # Step 3: Evaluate Baseline Retrieval Methods Across Splits
    # -------------------------------------------------------------------------
    print("\n[Step 3] Evaluating Baseline Retrieval (TF-IDF vs Dense vs Hybrid RRF)...")
    retrieval_eval = evaluate_retrieval_runs(dataset, k_values=(3, 5), seed=args.seed)

    # Save retrieval evaluation summary
    retrieval_file = args.output_dir / "retrieval_evaluation_summary.json"
    retrieval_file.write_text(json.dumps(retrieval_eval, indent=2), encoding="utf-8")
    print(f"  -> Saved retrieval results: {retrieval_file.name}")

    # Print summary table for All queries at K=5
    all_methods = retrieval_eval["partitions"]["all"]["methods"]
    print("\n  --- RETRIEVAL RESULTS (All 174 Pools, Cutoff K=5) ---")
    print(f"  {'Method':<12} | {'nDCG@5 (mean)':<14} | {'MRR (mean)':<12} | {'P@5 (judged)':<14} | {'P@5 (cons)':<12} | {'Coverage':<10}")
    print("  " + "-" * 84)
    for m, m_data in all_methods.items():
        k5 = m_data["metrics_by_k"]["k_5"]
        ndcg_m = k5["ndcg"]["mean"]
        mrr_m = k5["mrr"]["mean"]
        pj_m = k5["precision_judged"]["mean"]
        pc_m = k5["precision_conservative"]["mean"]
        cov = k5["judgment_coverage"]
        print(f"  {m:<12} | {ndcg_m:<14.4f} | {mrr_m:<12.4f} | {pj_m:<14.4f} | {pc_m:<12.4f} | {cov:<10.4f}")

    # Print summary table for Development vs Held-Out
    print("\n  --- RETRIEVAL GENERALIZATION (nDCG@5: Dev vs Held-Out) ---")
    dev_methods = retrieval_eval["partitions"]["development"]["methods"]
    held_methods = retrieval_eval["partitions"]["held_out"]["methods"]
    print(f"  {'Method':<12} | {'Dev nDCG@5 (140)':<18} | {'Held-Out nDCG@5 (60)':<22} | {'Generalization Diff':<16}")
    print("  " + "-" * 74)
    for m in all_methods.keys():
        dev_score = dev_methods[m]["metrics_by_k"]["k_5"]["ndcg"]["mean"] or 0.0
        held_score = held_methods[m]["metrics_by_k"]["k_5"]["ndcg"]["mean"] or 0.0
        diff = held_score - dev_score
        print(f"  {m:<12} | {dev_score:<18.4f} | {held_score:<22.4f} | {diff:+16.4f}")

    # Save per-query metrics jsonl
    per_query_file = args.output_dir / "per_query_metrics.jsonl"
    all_per_query = []
    for m, m_data in all_methods.items():
        for q_row in m_data.get("per_query", []):
            all_per_query.append(q_row)
    with per_query_file.open("w", encoding="utf-8") as f:
        for row in all_per_query:
            f.write(json.dumps(row) + "\n")
    print(f"  -> Saved per-query metrics: {per_query_file.name} ({len(all_per_query)} records)")

    # Save constraint satisfaction report
    constraint_report = {
        "report_version": "phase14-v1",
        "description": "Hard constraint satisfaction rate across evaluated retrieval methods at K=5",
        "methods": {
            m: {
                "constraint_satisfaction_rate": m_data["metrics_by_k"]["k_5"]["constraint_satisfaction_rate"],
            }
            for m, m_data in all_methods.items()
        },
    }
    constraint_file = args.output_dir / "constraint_satisfaction_report.json"
    constraint_file.write_text(json.dumps(constraint_report, indent=2), encoding="utf-8")
    print(f"  -> Saved constraint report: {constraint_file.name}")

    # -------------------------------------------------------------------------
    # Step 4: Evaluate Reranking Methods (Phase 11)
    # -------------------------------------------------------------------------
    reranking_summary = {}
    if not args.skip_reranking:
        print("\n[Step 4] Evaluating Phase 11 Reranking (RRF vs Multi-Signal vs Cross-Encoder)...")
        reranking_summary = evaluate_reranking(
            dataset, cases_path=args.cases_path, k=5, seed=args.seed
        )
        rerank_file = args.output_dir / "reranking_evaluation_summary.json"
        rerank_file.write_text(json.dumps(reranking_summary, indent=2), encoding="utf-8")
        print(f"  -> Saved reranking results: {rerank_file.name}")

        if "methods" in reranking_summary:
            print("\n  --- RERANKING RESULTS (Cutoff K=5) ---")
            print(f"  {'Method':<16} | {'nDCG@5':<10} | {'MRR':<10} | {'P@5':<10} | {'Latency (ms)':<16} | {'Mean Rank Shifts':<16}")
            print("  " + "-" * 86)
            for m, m_data in reranking_summary["methods"].items():
                m_metrics = m_data["metrics"]
                ndcg_m = m_metrics["ndcg"]["mean"] or 0.0
                mrr_m = m_metrics["mrr"]["mean"] or 0.0
                p_m = m_metrics["precision_conservative"]["mean"] or 0.0
                lat_m = m_data["latency_ms"]["mean"] or 0.0
                shifts = m_data["mean_rank_shift_sum"]
                print(f"  {m:<16} | {ndcg_m:<10.4f} | {mrr_m:<10.4f} | {p_m:<10.4f} | {lat_m:<16.2f} | {shifts:<16.2f}")
    else:
        print("\n[Step 4] Reranking evaluation skipped via flag.")

    # -------------------------------------------------------------------------
    # Step 5: Educational RAG Trace Demonstration
    # -------------------------------------------------------------------------
    print("\n[Step 5] Building educational RAG execution trace (Q0001)...")
    rag_trace = build_rag_educational_trace(dataset, query_id="Q0001")
    rag_trace_file = args.output_dir / "rag_trace_demonstration.json"
    rag_trace_file.write_text(json.dumps(rag_trace, indent=2), encoding="utf-8")
    print(f"  -> Saved RAG trace: {rag_trace_file.name}")

    # -------------------------------------------------------------------------
    # Step 6: LLM-as-a-Judge Evaluation Demonstration
    # -------------------------------------------------------------------------
    print("\n[Step 6] Running LLM-as-a-Judge demonstration...")
    sample_query = "lightweight running shoes for men"
    sample_evidence = (
        "[7ae33aaf60fc1ffa5d2601c92ec11304-E1] (product_name): Puma Carson 2 Concave Running Shoes\n"
        "[7ae33aaf60fc1ffa5d2601c92ec11304-E2] (price): 1899 INR\n"
        "[7ae33aaf60fc1ffa5d2601c92ec11304-E3] (category): Footwear >> Men's Shoes\n"
        "[7ae33aaf60fc1ffa5d2601c92ec11304-E4] (description): Breathable mesh upper, lightweight EVA midsole for running."
    )
    sample_recommendation = (
        "We recommend the Puma Carson 2 Concave Running Shoes [7ae33aaf60fc1ffa5d2601c92ec11304-E1]. "
        "At 1899 INR [7ae33aaf60fc1ffa5d2601c92ec11304-E2], it features a breathable mesh upper "
        "and a lightweight EVA midsole designed specifically for jogging [7ae33aaf60fc1ffa5d2601c92ec11304-E4]."
    )

    client = None
    judge_diagnostics = {"live_requested": bool(args.run_live_judge)}
    gateway_enabled = args.run_live_judge and GatewaySettings().enabled
    if gateway_enabled:
        try:
            judge_result, detail = asyncio.run(_run_gateway_judge_if_eligible(
                sample_query, sample_evidence, sample_recommendation
            ))
            judge_diagnostics.update(detail)
            if judge_result is None:
                judge_result = run_llm_judge(
                    sample_query, sample_evidence, sample_recommendation, mock_mode=True
                )
                judge_diagnostics["execution_mode"] = "OFFLINE_DEMONSTRATION"
        except Exception as exc:
            diagnostics_file = args.output_dir / "phase14_run_diagnostics.json"
            diagnostics_file.write_text(json.dumps({
                **judge_diagnostics, "execution_mode": "LIVE_API",
                "status": "LIVE_FAILURE", "error_type": type(exc).__name__,
            }, indent=2), encoding="utf-8")
            print(f"  -> Gateway judge failed ({type(exc).__name__}); no demo result was written.", file=sys.stderr)
            return 1
    else:
        if args.run_live_judge:
            try:
                from shopassist.llm.gemini_client import GeminiClient
                client = GeminiClient()
                print("  -> Connected to legacy live GeminiClient for LLM Judge.")
            except Exception as exc:
                judge_diagnostics.update({"status": "LIVE_SKIPPED", "reason": type(exc).__name__})
                print(f"  -> Live GeminiClient unavailable ({type(exc).__name__}); using offline demonstration.")
        try:
            judge_result = run_llm_judge(
                user_query=sample_query,
                evidence_text=sample_evidence,
                recommendation_output=sample_recommendation,
                client=client,
                mock_mode=(client is None),
            )
        except Exception as exc:
            diagnostics_file = args.output_dir / "phase14_run_diagnostics.json"
            diagnostics_file.write_text(json.dumps({
                **judge_diagnostics, "execution_mode": "LIVE_API",
                "status": "LIVE_FAILURE", "error_type": type(exc).__name__,
            }, indent=2), encoding="utf-8")
            print(f"  -> Live judge failed after dispatch ({type(exc).__name__}); no demo result was written.", file=sys.stderr)
            return 1
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if callable(close):
                    try:
                        close_result = close()
                        if asyncio.iscoroutine(close_result):
                            asyncio.run(close_result)
                    except Exception as exc:
                        logger.warning("Could not close Phase 14 judge client (%s).", type(exc).__name__)
        judge_diagnostics.setdefault(
            "status", "LIVE_SUCCESS" if judge_result.execution_mode == "LIVE_API" else "OFFLINE_DEMONSTRATION"
        )
        judge_diagnostics["execution_mode"] = judge_result.execution_mode
    diagnostics_file = args.output_dir / "phase14_run_diagnostics.json"
    diagnostics_file.write_text(json.dumps(judge_diagnostics, indent=2), encoding="utf-8")
    judge_file = args.output_dir / "llm_judge_evaluation.json"
    judge_file.write_text(json.dumps(judge_result.to_dict(), indent=2), encoding="utf-8")
    print(f"  -> LLM Judge Result: Decision={judge_result.overall_decision}, Groundedness={judge_result.groundedness_score}/5, ExecutionMode={judge_result.execution_mode}")
    print(f"  -> Saved LLM Judge report: {judge_file.name}")

    # -------------------------------------------------------------------------
    # Step 7: Create Master Manifest & Verification
    # -------------------------------------------------------------------------
    manifest = {
        "evaluation_release": "phase14_v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase14_learning_status": "COMPLETE",
        "benchmark_source": str(args.benchmark_dir),
        "seed": args.seed,
        "files": {
            "retrieval_evaluation_summary.json": file_sha256(retrieval_file),
            "per_query_metrics.jsonl": file_sha256(per_query_file),
            "constraint_satisfaction_report.json": file_sha256(constraint_file),
            "rag_trace_demonstration.json": file_sha256(rag_trace_file),
            "llm_judge_evaluation.json": file_sha256(judge_file),
            "phase14_run_diagnostics.json": file_sha256(diagnostics_file),
        },
        "notes": "Educational AI Engineering benchmark evaluation completed without requiring human gold annotations.",
    }
    if reranking_summary and (args.output_dir / "reranking_evaluation_summary.json").is_file():
        manifest["files"]["reranking_evaluation_summary.json"] = file_sha256(
            args.output_dir / "reranking_evaluation_summary.json"
        )

    manifest_file = args.output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\n[Step 7] Master manifest written to: {manifest_file}")

    print("\n" + "=" * 78)
    print("PHASE 14 EVALUATION COMPLETE: SUCCESS")
    print("phase14_learning_status = COMPLETE")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
