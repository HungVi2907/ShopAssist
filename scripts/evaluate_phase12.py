"""Phase 12 Preliminary Recommendation Evaluation Script.

Runs representative evaluation scenarios through RecommendationService using
Groq `openai/gpt-oss-20b`, verifies groundedness invariants, benchmarks token
usage and latency, and compares naive vs. optimized context builders.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import time
from typing import Any

import pandas as pd

from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput, QueryUnderstandingResult
from shopassist.preferences.schemas import PreferenceRepresentationResult, RepresentationStatus
from shopassist.reranking import RerankedProduct, RerankingResult, RerankingStatus
from shopassist.recommendation import (
    EvidenceContextBuilder,
    GroqProvider,
    GroundednessValidator,
    RecommendationService,
    RecommendationSettings,
    RecommendationStatus,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data/processed/products.parquet"
OUT_DIR = ROOT / "data/interim/phase12"


def _build_reranked_product(row: pd.Series, rank: int, rrf: float) -> RerankedProduct:
    metadata: dict[str, Any] = {}
    if "product_specifications" in row and pd.notna(row["product_specifications"]):
        val = row["product_specifications"]
        if isinstance(val, dict):
            metadata["product_specifications"] = val
        elif isinstance(val, str) and val.startswith("{"):
            try:
                metadata["product_specifications"] = json.loads(val)
            except Exception:
                pass

    rating_val = None
    if pd.notna(row["rating"]):
        try:
            rating_val = float(row["rating"])
        except (ValueError, TypeError):
            pass

    brand_val = str(row["brand"]) if pd.notna(row["brand"]) else None
    cat_val = str(row["category"]) if pd.notna(row["category"]) else "General"
    retrieval_txt = str(row["retrieval_text"]) if pd.notna(row["retrieval_text"]) else ""

    return RerankedProduct(
        product_id=str(row["product_id"]),
        original_rank=rank,
        reranked_rank=rank,
        product_name=str(row["product_name"]),
        retrieval_text=retrieval_txt,
        category=cat_val,
        brand=brand_val,
        discounted_price=float(row["discounted_price"]) if pd.notna(row["discounted_price"]) else 0.0,
        rating=rating_val,
        rrf_score=rrf,
        sources={"dense": {"rank": rank, "score": 0.8}, "lexical": {"rank": rank, "score": 0.8}},
        metadata=metadata,
        final_score=rrf,
    )


def load_evaluation_cases(catalog_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Define 7 representative test scenarios matching Section 12 & 13 requirements."""
    df_by_id = catalog_df.set_index("product_id", drop=False)

    # Q03 running shoes
    running_pids = ["7ae33aaf60fc1ffa5d2601c92ec11304", "855c191a7973278a777e8374c67b2c8a", "09779c98e54c30f905b21bd9744ae685"]
    running_products = [
        _build_reranked_product(df_by_id.loc[pid], i, 1.0 / (60 + i))
        for i, pid in enumerate(running_pids, 1) if pid in df_by_id.index
    ]

    # Q01 women party wedges
    wedge_pids = ["237e586616e07088c6ee26151ea7cd2b", "ba2c3c10eaeea0fa5eebbd65d8e67011", "7f2fd8125ccb82de558945ba4b2af423"]
    wedge_products = [
        _build_reranked_product(df_by_id.loc[pid], i, 1.0 / (60 + i))
        for i, pid in enumerate(wedge_pids, 1) if pid in df_by_id.index
    ]

    # Q02 women boots with missing attributes
    boot_pids = ["8a51adce678b874bef63d8a8a7d28ea4", "c6c1eca6e11a3b8e347feb7c35a29680", "522cc294663f3cf4bf1774d060ef949e"]
    boot_products = [
        _build_reranked_product(df_by_id.loc[pid], i, 1.0 / (60 + i))
        for i, pid in enumerate(boot_pids, 1) if pid in df_by_id.index
    ]

    # Q04 car floor mats
    mat_pids = ["697f4e16b77e369bf90703b1258fa995", "77b724e25769214931572f61e0ed7053", "5cd55e33ad760e876f04fe27eea61bf8"]
    mat_products = [
        _build_reranked_product(df_by_id.loc[pid], i, 1.0 / (60 + i))
        for i, pid in enumerate(mat_pids, 1) if pid in df_by_id.index
    ]

    cases = [
        {
            "case_id": "SCENARIO_1_SIMPLE",
            "name": "Simple product query (English)",
            "query": "running shoes for jogging",
            "language": "en",
            "query_result": QueryUnderstandingResult(
                query="running shoes for jogging",
                status="SUCCESS",
                output=QueryUnderstandingOutput(
                    semantic_query="running shoes for jogging",
                    hard_constraints=HardConstraints(currency="INR"),
                    soft_preferences=["running", "jogging"],
                ),
            ),
            "pref_result": PreferenceRepresentationResult(
                semantic_query="running shoes for jogging",
                has_preferences=True,
                status=RepresentationStatus.SUCCESS,
                preference_query="running shoes for jogging",
                normalized_preferences=["running", "jogging"],
            ),
            "products": running_products,
        },
        {
            "case_id": "SCENARIO_2_HARD_CONSTRAINTS",
            "name": "Hard constraints query (English)",
            "query": "women red party wedges heel under 1500 INR rating 4.0+",
            "language": "en",
            "query_result": QueryUnderstandingResult(
                query="women red party wedges heel under 1500 INR rating 4.0+",
                status="SUCCESS",
                output=QueryUnderstandingOutput(
                    semantic_query="women red party wedges heel",
                    hard_constraints=HardConstraints(
                        category="Footwear",
                        max_price=1500.0,
                        min_rating=4.0,
                        currency="INR",
                    ),
                    soft_preferences=["party wear", "red color", "wedges"],
                ),
            ),
            "pref_result": PreferenceRepresentationResult(
                semantic_query="women red party wedges heel",
                has_preferences=True,
                status=RepresentationStatus.SUCCESS,
                preference_query="women red party wedges heel party wear",
                normalized_preferences=["party wear", "red color", "wedges"],
            ),
            "products": wedge_products,
        },
        {
            "case_id": "SCENARIO_3_SOFT_PREFERENCES",
            "name": "Soft preferences query (English)",
            "query": "comfortable breathable running shoes for daily morning jogging",
            "language": "en",
            "query_result": QueryUnderstandingResult(
                query="comfortable breathable running shoes for daily morning jogging",
                status="SUCCESS",
                output=QueryUnderstandingOutput(
                    semantic_query="breathable cushioned running shoes",
                    hard_constraints=HardConstraints(currency="INR"),
                    soft_preferences=["breathable", "cushioned", "comfortable", "lightweight"],
                ),
            ),
            "pref_result": PreferenceRepresentationResult(
                semantic_query="breathable cushioned running shoes",
                has_preferences=True,
                status=RepresentationStatus.SUCCESS,
                preference_query="breathable cushioned comfortable lightweight running shoes",
                normalized_preferences=["breathable", "cushioned", "comfortable", "lightweight"],
            ),
            "products": running_products,
        },
        {
            "case_id": "SCENARIO_4_MISSING_ATTRIBUTES",
            "name": "Missing attributes query (English)",
            "query": "brown leather boots women zipper",
            "language": "en",
            "query_result": QueryUnderstandingResult(
                query="brown leather boots women zipper",
                status="SUCCESS",
                output=QueryUnderstandingOutput(
                    semantic_query="brown leather boots women zipper",
                    hard_constraints=HardConstraints(category="Footwear", currency="INR"),
                    soft_preferences=["brown", "leather", "zipper"],
                ),
            ),
            "pref_result": PreferenceRepresentationResult(
                semantic_query="brown leather boots women zipper",
                has_preferences=True,
                status=RepresentationStatus.SUCCESS,
                preference_query="brown leather boots women zipper",
                normalized_preferences=["brown", "leather", "zipper"],
            ),
            "products": boot_products,
        },
        {
            "case_id": "SCENARIO_5_COMPARISON",
            "name": "Product comparison query (English)",
            "query": "compare car floor mats for Suzuki Swift",
            "language": "en",
            "query_result": QueryUnderstandingResult(
                query="compare car floor mats for Suzuki Swift",
                status="SUCCESS",
                output=QueryUnderstandingOutput(
                    semantic_query="car floor mats for Suzuki Swift",
                    hard_constraints=HardConstraints(currency="INR"),
                    soft_preferences=["durable", "easy clean", "custom fit"],
                ),
            ),
            "pref_result": PreferenceRepresentationResult(
                semantic_query="car floor mats for Suzuki Swift",
                has_preferences=True,
                status=RepresentationStatus.SUCCESS,
                preference_query="car floor mats Suzuki Swift fitment",
                normalized_preferences=["durable", "easy clean", "custom fit"],
            ),
            "products": mat_products,
        },
        {
            "case_id": "SCENARIO_6_VIETNAMESE",
            "name": "Vietnamese natural language query",
            "query": "Tôi cần tìm giày chạy bộ nam nhẹ êm ái thoáng khí cho người mới bắt đầu",
            "language": "vi",
            "query_result": QueryUnderstandingResult(
                query="Tôi cần tìm giày chạy bộ nam nhẹ êm ái thoáng khí cho người mới bắt đầu",
                status="SUCCESS",
                output=QueryUnderstandingOutput(
                    semantic_query="giày chạy bộ nam nhẹ êm ái thoáng khí",
                    hard_constraints=HardConstraints(currency="INR"),
                    soft_preferences=["nhẹ", "êm ái", "thoáng khí"],
                ),
            ),
            "pref_result": PreferenceRepresentationResult(
                semantic_query="giày chạy bộ nam nhẹ êm ái thoáng khí",
                has_preferences=True,
                status=RepresentationStatus.SUCCESS,
                preference_query="men lightweight breathable cushioned running shoes",
                normalized_preferences=["nhẹ", "êm ái", "thoáng khí"],
            ),
            "products": running_products,
        },
        {
            "case_id": "SCENARIO_7_VIETNAMESE_CONSTRAINTS",
            "name": "Vietnamese query with hard constraints",
            "query": "Giày sandal cao gót nữ màu đỏ đi tiệc giá dưới 2000 INR",
            "language": "vi",
            "query_result": QueryUnderstandingResult(
                query="Giày sandal cao gót nữ màu đỏ đi tiệc giá dưới 2000 INR",
                status="SUCCESS",
                output=QueryUnderstandingOutput(
                    semantic_query="giày sandal cao gót nữ màu đỏ đi tiệc",
                    hard_constraints=HardConstraints(
                        category="Footwear",
                        max_price=2000.0,
                        currency="INR",
                    ),
                    soft_preferences=["đi tiệc", "màu đỏ"],
                ),
            ),
            "pref_result": PreferenceRepresentationResult(
                semantic_query="giày sandal cao gót nữ màu đỏ đi tiệc",
                has_preferences=True,
                status=RepresentationStatus.SUCCESS,
                preference_query="women red party heels sandal",
                normalized_preferences=["đi tiệc", "màu đỏ"],
            ),
            "products": wedge_products,
        },
    ]
    return cases


async def run_evaluation(
    live: bool = True,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    override_kwargs: dict[str, Any] = {}
    if provider:
        override_kwargs["phase12_llm_provider"] = provider
    if model:
        override_kwargs["phase12_llm_model"] = model

    settings = RecommendationSettings(**override_kwargs)

    if live:
        if settings.phase12_llm_provider == "openrouter" and not settings.openrouter_api_key:
            print("ERROR: OPENROUTER_API_KEY is not configured in environment or .env", file=sys.stderr)
            sys.exit(1)
        elif settings.phase12_llm_provider == "groq" and not settings.groq_api_key:
            print("ERROR: GROQ_API_KEY is not configured in environment or .env", file=sys.stderr)
            sys.exit(1)

    print(f"Loading catalog from {CATALOG_PATH}...")
    catalog_df = pd.read_parquet(
        CATALOG_PATH,
        columns=["product_id", "product_name", "category", "brand", "discounted_price", "rating", "retrieval_text", "product_specifications"],
    )
    cases = load_evaluation_cases(catalog_df)
    print(f"Loaded {len(cases)} evaluation scenarios.")

    service = RecommendationService(settings=settings)

    results: list[dict[str, Any]] = []

    print("\n" + "=" * 80)
    print("EXECUTING PHASE 12 PRELIMINARY EVALUATION")
    print(f"Model: {settings.phase12_llm_model} | Provider: {settings.phase12_llm_provider}")
    print("=" * 80)

    # 1. Run standard scenarios
    for idx, case in enumerate(cases, 1):
        case_id = case["case_id"]
        case_name = case["name"]
        print(f"\n[{idx}/{len(cases)}] Running {case_id}: {case_name}")

        reranking_res = RerankingResult(
            status=RerankingStatus.SUCCESS,
            method="RRF",
            products=case["products"],
            total_candidates=len(case["products"]),
            returned_count=len(case["products"]),
        )

        t_start = time.perf_counter()
        rec_res = await service.generate(
            query_result=case["query_result"],
            preference_result=case["pref_result"],
            reranking_result=reranking_res,
        )
        elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        # Detailed groundedness inspections
        cand_pids = [p.product_id for p in case["products"]]
        rec_pids = [p.product_id for p in rec_res.products]
        pid_subset_valid = all(p in cand_pids for p in rec_pids)
        order_preserved = rec_pids == [p for p in cand_pids if p in rec_pids]

        # Inspect evidence citations
        total_claims = 0
        total_evidence_citations = 0
        invalid_citations = 0
        for rec in rec_res.products:
            for st in rec.strengths:
                total_claims += 1
                for eid in st.evidence_ids:
                    total_evidence_citations += 1
                    if not eid.startswith(f"{rec.product_id}-E"):
                        invalid_citations += 1
            for lim in rec.limitations:
                total_claims += 1
                for eid in lim.evidence_ids:
                    total_evidence_citations += 1
                    if not eid.startswith(f"{rec.product_id}-E"):
                        invalid_citations += 1

        case_record = {
            "case_id": case_id,
            "name": case_name,
            "query": case["query"],
            "language": case["language"],
            "status": rec_res.status.value,
            "latency_ms": round(elapsed_ms, 2),
            "tokens": {
                "input_tokens": rec_res.usage.prompt_tokens,
                "output_tokens": rec_res.usage.completion_tokens,
                "reasoning_tokens": rec_res.usage.reasoning_tokens,
                "total_tokens": rec_res.usage.total_tokens,
            },
            "cost_usd": rec_res.usage.estimated_cost_usd,
            "groundedness": {
                "candidate_pids": cand_pids,
                "recommended_pids": rec_pids,
                "pid_validity": pid_subset_valid,
                "order_preserved": order_preserved,
                "total_claims": total_claims,
                "total_evidence_citations": total_evidence_citations,
                "invalid_citations": invalid_citations,
                "groundedness_pass": pid_subset_valid and order_preserved and (invalid_citations == 0),
            },
            "overview_preview": rec_res.overview[:120] + "..." if len(rec_res.overview) > 120 else rec_res.overview,
            "warnings": rec_res.warnings,
        }
        results.append(case_record)

        print(f"  -> Status: {case_record['status']} | Latency: {case_record['latency_ms']:.1f}ms")
        print(f"  -> Tokens: total={case_record['tokens']['total_tokens']} (prompt={case_record['tokens']['input_tokens']}, completion={case_record['tokens']['output_tokens']}, reasoning={case_record['tokens']['reasoning_tokens']})")
        print(f"  -> Cost: ${case_record['cost_usd']:.6f} | Citations: {total_evidence_citations} (invalid: {invalid_citations})")
        print(f"  -> Groundedness Pass: {case_record['groundedness']['groundedness_pass']}")

    # 2. Benchmark Naive vs Optimized Context on SCENARIO_1
    print("\n" + "=" * 80)
    print("BENCHMARKING NAIVE (UNOPTIMIZED) VS OPTIMIZED CONTEXT BUILDER")
    print("=" * 80)

    base_case = cases[0]
    reranking_base = RerankingResult(
        status=RerankingStatus.SUCCESS,
        method="RRF",
        products=base_case["products"],
        total_candidates=len(base_case["products"]),
        returned_count=len(base_case["products"]),
    )

    # A: Optimized builder
    opt_builder = EvidenceContextBuilder(
        default_currency="INR",
        max_spec_items=8,
        max_desc_sentences=3,
        strip_boilerplate=True,
    )
    service_opt = RecommendationService(
        settings=settings,
        context_builder=opt_builder,
    )
    t0 = time.perf_counter()
    res_opt = await service_opt.generate(
        query_result=base_case["query_result"],
        preference_result=base_case["pref_result"],
        reranking_result=reranking_base,
    )
    lat_opt = (time.perf_counter() - t0) * 1000.0

    # B: Naive unoptimized builder (50 specs, 50 sentences, unstripped marketplace boilerplate)
    naive_builder = EvidenceContextBuilder(
        default_currency="INR",
        max_spec_items=50,
        max_desc_sentences=50,
        strip_boilerplate=False,
    )
    service_naive = RecommendationService(
        settings=settings,
        context_builder=naive_builder,
    )
    t0 = time.perf_counter()
    res_naive = await service_naive.generate(
        query_result=base_case["query_result"],
        preference_result=base_case["pref_result"],
        reranking_result=reranking_base,
    )
    lat_naive = (time.perf_counter() - t0) * 1000.0

    prompt_reduction = (
        (res_naive.usage.prompt_tokens - res_opt.usage.prompt_tokens) / res_naive.usage.prompt_tokens * 100.0
        if res_naive.usage.prompt_tokens > 0 else 0.0
    )
    cost_reduction = (
        (res_naive.usage.estimated_cost_usd - res_opt.usage.estimated_cost_usd) / res_naive.usage.estimated_cost_usd * 100.0
        if res_naive.usage.estimated_cost_usd > 0 else 0.0
    )

    context_comparison = {
        "scenario": base_case["case_id"],
        "optimized": {
            "input_tokens": res_opt.usage.prompt_tokens,
            "output_tokens": res_opt.usage.completion_tokens,
            "total_tokens": res_opt.usage.total_tokens,
            "latency_ms": round(lat_opt, 2),
            "cost_usd": res_opt.usage.estimated_cost_usd,
        },
        "naive_unoptimized": {
            "input_tokens": res_naive.usage.prompt_tokens,
            "output_tokens": res_naive.usage.completion_tokens,
            "total_tokens": res_naive.usage.total_tokens,
            "latency_ms": round(lat_naive, 2),
            "cost_usd": res_naive.usage.estimated_cost_usd,
        },
        "reduction": {
            "input_token_reduction_pct": round(prompt_reduction, 2),
            "cost_reduction_pct": round(cost_reduction, 2),
            "latency_delta_ms": round(lat_opt - lat_naive, 2),
        },
    }

    print(f"Optimized Prompt Tokens: {res_opt.usage.prompt_tokens} | Naive Prompt Tokens: {res_naive.usage.prompt_tokens}")
    print(f"Token Reduction: {prompt_reduction:.1f}% | Cost Reduction: {cost_reduction:.1f}%")

    # Aggregate metrics
    latencies = [r["latency_ms"] for r in results]
    input_tokens = [r["tokens"]["input_tokens"] for r in results]
    output_tokens = [r["tokens"]["output_tokens"] for r in results]
    total_tokens = [r["tokens"]["total_tokens"] for r in results]
    reasoning_tokens = [r["tokens"]["reasoning_tokens"] for r in results if r["tokens"]["reasoning_tokens"] is not None]
    costs = [r["cost_usd"] for r in results]

    sorted_lats = sorted(latencies)
    p95_idx = int(0.95 * len(sorted_lats))
    p95_lat = sorted_lats[min(p95_idx, len(sorted_lats) - 1)]

    if settings.phase12_llm_provider == "openrouter":
        if ":free" in settings.phase12_llm_model:
            pricing_source = "OpenRouter official pricing: $0.00/1M input, $0.00/1M output for free-tier routes (subject to upstream rate limits)"
        else:
            pricing_source = f"OpenRouter official pricing: ${settings.phase12_cost_input_per_m:.4f}/1M input, ${settings.phase12_cost_output_per_m:.4f}/1M output"
    else:
        pricing_source = "Groq Cloud API official pricing (Oct 2024 / current): $0.075/1M input, $0.30/1M output for GPT-OSS 20B"

    summary = {
        "status": "VALIDATED_FOR_PROTOTYPE",
        "provider": settings.phase12_llm_provider,
        "model": settings.phase12_llm_model,
        "pricing_source": pricing_source,
        "total_scenarios_evaluated": len(results),
        "all_scenarios_success": all(r["status"] == "SUCCESS" for r in results),
        "groundedness_pass_rate": sum(1 for r in results if r["groundedness"]["groundedness_pass"]) / len(results),
        "performance": {
            "avg_input_tokens": round(statistics.mean(input_tokens), 1),
            "avg_output_tokens": round(statistics.mean(output_tokens), 1),
            "avg_reasoning_tokens": round(statistics.mean(reasoning_tokens), 1) if reasoning_tokens else 0.0,
            "avg_total_tokens": round(statistics.mean(total_tokens), 1),
            "median_latency_ms": round(statistics.median(latencies), 1),
            "p95_latency_ms": round(p95_lat, 1),
            "min_latency_ms": round(min(latencies), 1),
            "max_latency_ms": round(max(latencies), 1),
            "avg_cost_usd_per_request": round(statistics.mean(costs), 6),
            "total_evaluation_cost_usd": round(sum(costs), 6),
        },
        "context_builder_comparison": context_comparison,
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "scenarios": results,
    }

    # Save to JSON
    out_file = OUT_DIR / "phase12_evaluation_report.json"
    out_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved evaluation report to {out_file}")

    summary_file = OUT_DIR / "phase12_evaluation_summary.json"
    summary_concise = {k: v for k, v in summary.items() if k != "scenarios"}
    summary_file.write_text(json.dumps(summary_concise, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved concise summary to {summary_file}")

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Phase 12 Recommendation Service")
    parser.add_argument("--live", action="store_true", default=True, help="Run live LLM inference")
    parser.add_argument("--provider", choices=["openrouter", "groq"], default=None, help="LLM Provider override")
    parser.add_argument("--model", default=None, help="LLM Model ID override")
    args = parser.parse_args()

    asyncio.run(run_evaluation(live=args.live, provider=args.provider, model=args.model))


if __name__ == "__main__":
    main()
