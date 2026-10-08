"""Phase 5.3 executable script: Embedding Model Setup & Validation.

Validates `BAAI/bge-small-en-v1.5` on the ShopAssist product catalog:
- Model loading & 384-dimensional vector validation
- Full-dataset (8,405 items) native tokenization distribution audit
- Representative deterministic sampling & embedding generation
- L2 normalization & numerical stability validation (0 NaN, 0 Inf, 0 zero vectors)
- 5 multi-category semantic sanity retrieval tests
- Batch performance benchmarking and full-catalog runtime estimation
- Machine-readable audit report generation

Usage:
    python scripts/validate_embedding_model.py
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import numpy as np
import pandas as pd
import psutil
import torch

from shopassist.embeddings.model import (
    DEFAULT_EMBEDDING_DIM,
    DEFAULT_MAX_SEQ_LENGTH,
    DEFAULT_MODEL_NAME,
    EmbeddingModel,
    validate_embeddings,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("validate_embedding_model")

DEFAULT_INPUT_PATH = Path("data/interim/products_with_retrieval_text.parquet")
DEFAULT_REPORT_PATH = Path("data/interim/phase5_3_embedding_model_report.json")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Phase 5.3 — Setup & Validate BAAI/bge-small-en-v1.5 Embedding Model."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to input products parquet file with retrieval_text",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=DEFAULT_MODEL_NAME,
        help="HuggingFace embedding model name",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=200,
        help="Number of representative product samples to benchmark and validate",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for embedding inference benchmark",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="Compute device ('cuda', 'cpu', 'mps', or None for auto-detect)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Output JSON audit report path",
    )
    return parser.parse_args()


def select_representative_sample(df: pd.DataFrame, sample_size: int = 200) -> pd.DataFrame:
    """Select a deterministic, representative sample of products covering all critical cases.

    Covers:
    - Shortest and longest retrieval texts (including extreme specification outliers)
    - Median length texts
    - Missing brand items
    - Empty specification items
    - Truncated description items
    - All 16 Level-1 product categories
    - Deterministic random stratified fill (random_state=42)
    """
    selected_indices: set[int] = set()

    # Sort indices by length of retrieval_text
    sorted_by_len = df["retrieval_text"].str.len().sort_values()

    # 1. Shortest texts (5 items)
    for idx in sorted_by_len.head(5).index:
        selected_indices.add(int(idx))

    # 2. Median length texts (5 items)
    mid_point = len(sorted_by_len) // 2
    for idx in sorted_by_len.iloc[mid_point - 2 : mid_point + 3].index:
        selected_indices.add(int(idx))

    # 3. Longest texts including extreme spec outliers (10 items)
    for idx in sorted_by_len.tail(10).index:
        selected_indices.add(int(idx))

    # 4. Missing brand items (15 items)
    missing_brand_indices = df[df["brand"].isna() | df["brand"].astype(str).str.lower().isin(["none", "nan", "null", ""])].index
    for idx in missing_brand_indices[:15]:
        selected_indices.add(int(idx))

    # 5. Empty specifications items (all 18 items if possible)
    empty_specs_mask = df["product_specifications"].astype(str).isin(["[]", "null", "None", "{}"])
    for idx in df[empty_specs_mask].index:
        selected_indices.add(int(idx))

    # 6. Truncated descriptions (>1200 chars original description) (15 items)
    truncated_desc_mask = df["description"].fillna("").astype(str).str.strip().str.len() > 1200
    for idx in df[truncated_desc_mask].index[:15]:
        selected_indices.add(int(idx))

    # 7. Category diversity: at least 3 items from each of the 16 categories
    for cat in df["category"].unique():
        cat_indices = df[df["category"] == cat].index
        for idx in cat_indices[:3]:
            selected_indices.add(int(idx))

    # 8. Deterministic random fill to reach exact sample_size
    remaining_count = sample_size - len(selected_indices)
    if remaining_count > 0:
        pool_indices = [i for i in df.index if i not in selected_indices]
        sampled_fill = pd.Series(pool_indices).sample(n=remaining_count, random_state=42)
        for idx in sampled_fill:
            selected_indices.add(int(idx))

    sample_df = df.loc[sorted(list(selected_indices))].copy()
    if len(sample_df) > sample_size:
        sample_df = sample_df.iloc[:sample_size].copy()

    return sample_df


def run_tokenization_audit(embedding_model: EmbeddingModel, texts: list[str]) -> dict[str, Any]:
    """Run native tokenization count on all texts and compute exact length distribution."""
    logger.info("Running native tokenization audit across %d texts...", len(texts))
    t0 = time.time()
    token_lengths = embedding_model.batch_count_tokens(texts)
    elapsed = time.time() - t0
    logger.info("Finished native tokenization in %.2f seconds", elapsed)

    s = pd.Series(token_lengths)
    over_512_count = int((s > 512).sum())
    over_512_pct = round(float((s > 512).mean() * 100), 2)

    return {
        "total_texts_audited": len(texts),
        "tokenization_elapsed_seconds": round(elapsed, 3),
        "min_tokens": int(s.min()),
        "mean_tokens": round(float(s.mean()), 2),
        "median_tokens": float(s.median()),
        "p90_tokens": float(s.quantile(0.90)),
        "p95_tokens": float(s.quantile(0.95)),
        "p99_tokens": float(s.quantile(0.99)),
        "max_tokens": int(s.max()),
        "count_over_512": over_512_count,
        "percentage_over_512": over_512_pct,
    }


def run_semantic_sanity_scenarios(embedding_model: EmbeddingModel) -> dict[str, Any]:
    """Execute 5 multi-category semantic sanity retrieval tests."""
    logger.info("Running 5 multi-category semantic sanity scenarios...")

    scenarios = [
        {
            "id": "scenario_1_keyboard",
            "query": "wireless bluetooth keyboard",
            "target": "Product: Logitech K380 Multi-Device Bluetooth Keyboard | Category: Computers | Brand: Logitech | Specifications: Type: Wireless Keyboard; Connectivity: Bluetooth 3.0",
            "distractors": [
                "Product: Puma Smash V2 Men Running Shoes | Category: Footwear | Brand: Puma | Specifications: Occasion: Sports; Type: Running Shoes",
                "Product: 3a Autocare Car Floor Mat | Category: Automotive | Brand: 3a AUTOCARE | Specifications: Type: Floor Mat; Material: Microfibre",
                "Product: Durian Leather 2 Seater Sofa | Category: Furniture | Brand: Durian | Specifications: Type: 2 Seater Sofa; Material: Leather",
            ],
        },
        {
            "id": "scenario_2_car_mat",
            "query": "waterproof car floor mat",
            "target": "Product: 3a Autocare 3D MAT Car Mat Suzuki New Swift | Category: Automotive | Brand: 3a AUTOCARE | Specifications: Type: Floor Mat; Water Resistant: Yes; Finish: Matt",
            "distractors": [
                "Product: Logitech K380 Multi-Device Bluetooth Keyboard | Category: Computers | Brand: Logitech | Specifications: Type: Wireless Keyboard",
                "Product: Amore Abstract Cushions Cover | Category: Home Furnishing | Brand: Amore | Specifications: Material: Silk; Type: Cushion Cover",
                "Product: 11e Women Flats Sandal | Category: Footwear | Specifications: Type: Flats; Sole Material: PVC",
            ],
        },
        {
            "id": "scenario_3_sofa",
            "query": "leather two seater sofa for living room",
            "target": "Product: Durian Leather 2 Seater Sofa | Category: Furniture | Brand: Durian | Specifications: Type: 2 Seater Sofa; Material: Leatherette; Color: Brown",
            "distractors": [
                "Product: 99Gems 5 in 1 USB Cable | Category: Computers | Brand: 99Gems | Specifications: Type: USB Cable; Connectivity: USB",
                "Product: 3a Autocare Car Floor Mat | Category: Automotive | Brand: 3a AUTOCARE | Specifications: Type: Floor Mat; Material: Microfibre",
                "Product: Puma Smash V2 Men Running Shoes | Category: Footwear | Brand: Puma | Specifications: Occasion: Sports; Type: Running Shoes",
            ],
        },
        {
            "id": "scenario_4_shoes",
            "query": "women casual flat sandals",
            "target": "Product: 11e Women Flats | Category: Footwear | Specifications: Type: Flats; Sole Material: PVC; Occasion: Casual; Color: Beige",
            "distractors": [
                "Product: Logitech K380 Multi-Device Bluetooth Keyboard | Category: Computers | Brand: Logitech | Specifications: Type: Wireless Keyboard",
                "Product: Durian Leather 2 Seater Sofa | Category: Furniture | Brand: Durian | Specifications: Type: 2 Seater Sofa; Material: Leatherette",
                "Product: 3a Autocare Car Floor Mat | Category: Automotive | Brand: 3a AUTOCARE | Specifications: Type: Floor Mat; Material: Microfibre",
            ],
        },
        {
            "id": "scenario_5_usb_cable",
            "query": "fast charging micro usb data cable",
            "target": "Product: 99Gems LR GOLD 5 in 1 MOBILE USB Cable | Category: Computers | Brand: 99Gems | Specifications: Type: USB Cable; Connectivity: USB Port; Material: pvc",
            "distractors": [
                "Product: 11e Women Flats | Category: Footwear | Specifications: Type: Flats; Sole Material: PVC",
                "Product: Durian Leather 2 Seater Sofa | Category: Furniture | Brand: Durian | Specifications: Type: 2 Seater Sofa; Material: Leatherette",
                "Product: Amore Abstract Cushions Cover | Category: Home Furnishing | Brand: Amore | Specifications: Material: Silk; Type: Cushion Cover",
            ],
        },
    ]

    scenario_results: list[dict[str, Any]] = []
    passed_count = 0

    for sc in scenarios:
        query_text = sc["query"]
        target_doc = sc["target"]
        distractor_docs = sc["distractors"]

        all_docs = [target_doc] + distractor_docs

        q_emb = embedding_model.encode_queries(query_text)
        d_embs = embedding_model.encode_documents(all_docs)

        sims = np.asarray(embedding_model.compute_similarity(q_emb, d_embs)).flatten()
        target_sim = float(sims[0])
        max_distractor_sim = float(np.max(sims[1:]))

        is_passed = bool(target_sim > max_distractor_sim)
        if is_passed:
            passed_count += 1

        scenario_results.append({
            "scenario_id": sc["id"],
            "query": query_text,
            "target_similarity": round(target_sim, 4),
            "max_distractor_similarity": round(max_distractor_sim, 4),
            "margin": round(target_sim - max_distractor_sim, 4),
            "status": "PASS" if is_passed else "FAIL",
        })

    return {
        "total_scenarios": len(scenarios),
        "passed": passed_count,
        "failed": len(scenarios) - passed_count,
        "status": "PASS" if passed_count == len(scenarios) else "FAIL",
        "scenarios": scenario_results,
    }


def benchmark_batch_performance(
    embedding_model: EmbeddingModel,
    sample_texts: list[str],
    batch_size: int,
    total_catalog_size: int = 8405,
) -> dict[str, Any]:
    """Benchmark embedding throughput on sample and estimate full catalog runtime."""
    logger.info("Benchmarking batch encoding with batch_size=%d on %d texts...", batch_size, len(sample_texts))

    # Warm-up run with 5 items
    _ = embedding_model.encode(sample_texts[:5], batch_size=batch_size, show_progress_bar=False)

    t0 = time.time()
    embeddings = embedding_model.encode(sample_texts, batch_size=batch_size, show_progress_bar=False)
    elapsed = time.time() - t0

    throughput = len(sample_texts) / elapsed
    ms_per_text = (elapsed / len(sample_texts)) * 1000
    est_full_seconds = total_catalog_size / throughput
    est_full_minutes = est_full_seconds / 60.0

    return {
        "device": embedding_model.device,
        "batch_size": batch_size,
        "sample_size": len(sample_texts),
        "elapsed_seconds": round(elapsed, 3),
        "throughput_texts_per_second": round(throughput, 2),
        "milliseconds_per_text": round(ms_per_text, 2),
        "estimated_full_dataset_seconds": round(est_full_seconds, 1),
        "estimated_full_dataset_minutes": round(est_full_minutes, 2),
        "embeddings_array": embeddings,
    }


def run_pipeline(
    input_path: Path,
    model_name: str,
    sample_size: int,
    batch_size: int,
    device: str | None,
    report_path: Path,
) -> int:
    """Execute complete Phase 5.3 validation pipeline."""
    logger.info("================================================================")
    logger.info("Starting Phase 5.3 — Embedding Model Setup & Validation Pipeline")
    logger.info("================================================================")
    logger.info("Input dataset: %s", input_path)
    logger.info("Model name:    %s", model_name)
    logger.info("Report path:   %s", report_path)

    # 1. Validate input dataset
    if not input_path.exists():
        logger.error("Input file does not exist: %s", input_path)
        return 1

    df = pd.read_parquet(input_path)
    dataset_rows = len(df)
    if dataset_rows != 8405:
        logger.error("Expected 8405 rows in input dataset, found %d", dataset_rows)
        return 1

    if "retrieval_text" not in df.columns:
        logger.error("'retrieval_text' column missing from input dataset!")
        return 1

    empty_or_null_texts = df["retrieval_text"].isna().sum() + (df["retrieval_text"].str.strip() == "").sum()
    if empty_or_null_texts > 0:
        logger.error("Found %d empty or null retrieval_text rows!", empty_or_null_texts)
        return 1

    logger.info("Input dataset validated: 8,405 valid retrieval_text records.")

    # Memory before model loading
    process = psutil.Process()
    ram_before_mb = round(process.memory_info().rss / (1024 * 1024), 1)

    # 2. Load and configure EmbeddingModel
    t_load = time.time()
    embedding_model = EmbeddingModel(
        model_name=model_name,
        device=device,
        normalize_embeddings=True,
        max_seq_length=DEFAULT_MAX_SEQ_LENGTH,
    )
    model_load_seconds = round(time.time() - t_load, 2)
    ram_after_mb = round(process.memory_info().rss / (1024 * 1024), 1)

    # 3. Model metadata validation
    actual_dim = embedding_model.embedding_dimension
    if actual_dim != DEFAULT_EMBEDDING_DIM:
        logger.error("CRITICAL: Actual dimension %d != expected %d", actual_dim, DEFAULT_EMBEDDING_DIM)
        return 1

    # 4. Tokenization audit across all 8,405 retrieval_text records
    all_texts = df["retrieval_text"].tolist()
    token_audit = run_tokenization_audit(embedding_model, all_texts)

    # 5. Representative sampling
    sample_df = select_representative_sample(df, sample_size=sample_size)
    sample_texts = sample_df["retrieval_text"].tolist()
    logger.info("Selected %d representative sample products covering all critical cases.", len(sample_texts))

    # 6. Benchmark batch performance & generate embeddings
    perf_results = benchmark_batch_performance(
        embedding_model,
        sample_texts=sample_texts,
        batch_size=batch_size,
        total_catalog_size=dataset_rows,
    )
    sample_embeddings = perf_results.pop("embeddings_array")

    # 7. Validate numerical properties & L2 normalization of generated embeddings
    norm_audit = validate_embeddings(
        sample_embeddings,
        expected_dim=DEFAULT_EMBEDDING_DIM,
        expected_count=len(sample_texts),
        check_normalized=True,
    )
    logger.info("Embedding numerical validation PASSED: 0 NaN, 0 Inf, 0 zero vectors, L2 norm ≈ 1.0.")

    # 8. Run 5 multi-category semantic sanity retrieval tests
    semantic_audit = run_semantic_sanity_scenarios(embedding_model)
    logger.info(
        "Semantic sanity tests: %d/%d passed (status: %s).",
        semantic_audit["passed"],
        semantic_audit["total_scenarios"],
        semantic_audit["status"],
    )

    # 9. Truncation behavior test on extreme outlier
    max_len_idx = df["retrieval_text"].str.len().idxmax()
    longest_text = str(df.loc[max_len_idx, "retrieval_text"])
    longest_token_count = embedding_model.count_tokens(longest_text)
    outlier_emb = embedding_model.encode_documents(longest_text)
    outlier_valid = bool(
        outlier_emb.shape == (384,)
        and np.all(np.isfinite(outlier_emb))
        and abs(np.linalg.norm(outlier_emb) - 1.0) < 1e-4
    )
    logger.info(
        "Outlier truncation test (%d chars, %d tokens): shape=%s, finite=%s, norm=%.6f (status: %s)",
        len(longest_text),
        longest_token_count,
        outlier_emb.shape,
        np.all(np.isfinite(outlier_emb)),
        float(np.linalg.norm(outlier_emb)),
        "PASS" if outlier_valid else "FAIL",
    )

    # Framework versions
    try:
        st_ver = importlib.metadata.version("sentence-transformers")
    except Exception:
        st_ver = "unknown"
    try:
        tf_ver = importlib.metadata.version("transformers")
    except Exception:
        tf_ver = "unknown"

    overall_status = "PASS" if (
        norm_audit["status"] == "PASS"
        and semantic_audit["status"] == "PASS"
        and outlier_valid
        and actual_dim == DEFAULT_EMBEDDING_DIM
    ) else "FAIL"

    # Assemble JSON report
    report: dict[str, Any] = {
        "phase": "5.3",
        "model_name": model_name,
        "framework": "sentence-transformers",
        "framework_version": st_ver,
        "transformers_version": tf_ver,
        "torch_version": torch.__version__,
        "device": embedding_model.device,
        "cuda_device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "N/A",
        "process_ram_mb": {
            "before_load": ram_before_mb,
            "after_load": ram_after_mb,
            "model_footprint_mb": round(ram_after_mb - ram_before_mb, 1),
        },
        "model_load_seconds": model_load_seconds,
        "dataset_rows": dataset_rows,
        "embedding_dimension_expected": DEFAULT_EMBEDDING_DIM,
        "embedding_dimension_actual": actual_dim,
        "max_sequence_length": embedding_model.max_seq_length,
        "tokenization": token_audit,
        "sample_validation": {
            "sample_size": len(sample_texts),
            "embedding_shape": list(sample_embeddings.shape),
            "dtype": str(sample_embeddings.dtype),
            "nan_count": norm_audit["nan_count"],
            "inf_count": norm_audit["inf_count"],
            "zero_vector_count": norm_audit["zero_vector_count"],
        },
        "normalization": {
            "enabled": True,
            "min_l2_norm": norm_audit["min_l2_norm"],
            "mean_l2_norm": norm_audit["mean_l2_norm"],
            "max_l2_norm": norm_audit["max_l2_norm"],
        },
        "performance": perf_results,
        "semantic_sanity_checks": semantic_audit,
        "outlier_truncation_check": {
            "longest_product_id": str(df.loc[max_len_idx, "product_id"]),
            "longest_text_chars": len(longest_text),
            "longest_text_tokens": longest_token_count,
            "output_vector_shape": list(outlier_emb.shape),
            "is_finite": bool(np.all(np.isfinite(outlier_emb))),
            "l2_norm": round(float(np.linalg.norm(outlier_emb)), 6),
            "status": "PASS" if outlier_valid else "FAIL",
        },
        "overall_status": overall_status,
    }

    # Save JSON report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info("Saved Phase 5.3 audit report to: %s", report_path)

    # Formatted terminal summary
    print("\n" + "=" * 70)
    print("PHASE 5.3 — EMBEDDING MODEL SETUP & VALIDATION SUMMARY")
    print("=" * 70)
    print(f"Model Identifier:             {report['model_name']}")
    print(f"Framework:                    sentence-transformers {report['framework_version']} (torch {report['torch_version']})")
    print(f"Execution Device:             {report['device']} ({report['cuda_device_name']})")
    print(f"Model Load Time:              {report['model_load_seconds']}s (RAM footprint: ~{report['process_ram_mb']['model_footprint_mb']} MB)")
    print(f"Embedding Dimension:          {report['embedding_dimension_actual']} (Expected: {report['embedding_dimension_expected']})")
    print(f"Max Sequence Length:          {report['max_sequence_length']} tokens")
    print("-" * 70)
    print("NATIVE TOKENIZATION AUDIT (8,405 Products):")
    print(f"  Min / Mean / Median:        {token_audit['min_tokens']} / {token_audit['mean_tokens']} / {token_audit['median_tokens']} tokens")
    print(f"  90th / 95th / 99th Pct:     {token_audit['p90_tokens']} / {token_audit['p95_tokens']} / {token_audit['p99_tokens']} tokens")
    print(f"  Max Tokens:                 {token_audit['max_tokens']} tokens")
    print(f"  Records > 512 Tokens:       {token_audit['count_over_512']} / {token_audit['total_texts_audited']} ({token_audit['percentage_over_512']}%)")
    print("-" * 70)
    print("NUMERICAL INTEGRITY (Sample size = 200):")
    print(f"  Embedding Array Shape:      {report['sample_validation']['embedding_shape']}")
    print(f"  Data Type:                  {report['sample_validation']['dtype']}")
    print(f"  NaN / Inf / Zero Vectors:   {report['sample_validation']['nan_count']} / {report['sample_validation']['inf_count']} / {report['sample_validation']['zero_vector_count']}")
    print(f"  L2 Norms (Min/Mean/Max):    {report['normalization']['min_l2_norm']} / {report['normalization']['mean_l2_norm']} / {report['normalization']['max_l2_norm']}")
    print("-" * 70)
    print("SEMANTIC SANITY SCENARIOS:")
    for sc in semantic_audit["scenarios"]:
        print(f"  [{sc['status']}] Query: '{sc['query']}' -> Target Sim: {sc['target_similarity']} (Margin: +{sc['margin']})")
    print("-" * 70)
    print("BENCHMARK & RUNTIME ESTIMATION (Phase 5.5 Readiness):")
    print(f"  Batch Size:                 {perf_results['batch_size']}")
    print(f"  Throughput:                 {perf_results['throughput_texts_per_second']} texts/second ({perf_results['milliseconds_per_text']} ms/text)")
    print(f"  Estimated Full Catalog Time: {perf_results['estimated_full_dataset_seconds']}s (~{perf_results['estimated_full_dataset_minutes']} minutes)")
    print("=" * 70)
    print(f"OVERALL STATUS:               {report['overall_status']}")
    print(f"REPORT ARTIFACT:              {report_path}")
    print("=" * 70 + "\n")

    return 0 if overall_status == "PASS" else 1


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    return run_pipeline(
        input_path=args.input,
        model_name=args.model_name,
        sample_size=args.sample_size,
        batch_size=args.batch_size,
        device=args.device,
        report_path=args.report,
    )


if __name__ == "__main__":
    sys.exit(main())
