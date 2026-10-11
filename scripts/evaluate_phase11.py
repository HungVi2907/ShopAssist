"""Reproduce the frozen, local-only Phase 11 ranking comparison.

This script uses the checked-in product embeddings, canonical catalog text, and
Phase 6 TF-IDF files only. It never creates a database connection. The BGE
query encoder is loaded with local_files_only=True.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import platform
import statistics
import time
from typing import Any

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput, QueryUnderstandingResult
from shopassist.preferences.schemas import PreferenceRepresentationResult, RepresentationStatus
from shopassist.retrieval.hybrid import CandidateSource, HybridCandidate, HybridRetrievalResult, HybridRetrievalStatus
from shopassist.retrieval.tfidf import TFIDFIndex
from shopassist.reranking import MappingProductTextProvider, RerankingConfig, RerankingMethod, RerankingService
from shopassist.reranking import load_canonical_product_texts, load_local_cross_encoder


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "data/interim/phase11/phase11_reranking_cases.json"
CATALOG = ROOT / "data/processed/products.parquet"
TFIDF = ROOT / "data/processed/tfidf"
OUT_DIR = ROOT / "data/interim/phase11"
MODEL_ID = "BAAI/bge-small-en-v1.5"
MODEL_PROMPT = "Represent this sentence for searching relevant passages: "


def _ndcg(grades: list[int], k: int) -> float:
    gains = [(2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades[:k])]
    ideal = sorted(grades, reverse=True)[:k]
    ideal_dcg = sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(ideal))
    return sum(gains) / ideal_dcg if ideal_dcg else 0.0


def _metrics(ids: list[str], qrels: dict[str, int], k: int = 5) -> dict[str, float]:
    grades = [int(qrels.get(pid, 0)) for pid in ids[:k]]
    rel = [grade >= 2 for grade in grades]
    reciprocal = next((1 / (idx + 1) for idx, yes in enumerate(rel) if yes), 0.0)
    return {
        f"ndcg@{k}": _ndcg(grades, k),
        "mrr": reciprocal,
        f"precision@{k}": sum(rel) / k,
    }


def _load() -> tuple[dict[str, Any], pd.DataFrame, MappingProductTextProvider, TFIDFIndex, SentenceTransformer]:
    fixture = json.loads(CASES.read_text(encoding="utf-8"))
    frame = pd.read_parquet(CATALOG, columns=[
        "product_id", "product_name", "category", "brand", "discounted_price", "rating", "retrieval_text", "embedding"
    ])
    if frame.product_id.isna().any() or frame.product_id.astype(str).duplicated().any():
        raise ValueError("Catalog must contain unique, non-null product IDs")
    if frame.retrieval_text.isna().any() or (frame.retrieval_text.astype(str).str.strip() == "").any():
        raise ValueError("Catalog contains missing canonical product text")
    provider = load_canonical_product_texts(str(CATALOG))
    lexical_index = TFIDFIndex.load(TFIDF)
    model = SentenceTransformer(MODEL_ID, device="cuda" if _cuda_available() else "cpu", local_files_only=True)
    return fixture, frame, provider, lexical_index, model


def _cuda_available() -> bool:
    import torch
    return bool(torch.cuda.is_available())


def _candidate_set(case: dict[str, Any], frame: pd.DataFrame, index: TFIDFIndex, model: SentenceTransformer) -> list[HybridCandidate]:
    query = case["query"]
    query_vector = model.encode(MODEL_PROMPT + query, normalize_embeddings=True, convert_to_numpy=True)
    embedding_matrix = np.stack(frame.embedding.to_list()).astype(np.float32)
    norms = np.linalg.norm(embedding_matrix, axis=1)
    if not np.isfinite(embedding_matrix).all() or (norms == 0).any():
        raise ValueError("Saved product embedding matrix has invalid values")
    embedding_matrix = embedding_matrix / norms[:, None]
    ids = frame.product_id.astype(str).tolist()
    dense_scores = embedding_matrix @ query_vector
    dense_order = sorted(range(len(ids)), key=lambda i: (-float(dense_scores[i]), ids[i]))[:20]
    dense_rank = {ids[i]: pos for pos, i in enumerate(dense_order, 1)}
    dense_score = {ids[i]: float(dense_scores[i]) for i in dense_order}
    lexical_rows = index.search(query, top_k=20)
    lexical_rank = {row.product_id: row.rank for row in lexical_rows}
    lexical_score = {row.product_id: float(row.tfidf_score) for row in lexical_rows}

    rrf = {pid: 1.0 / (60 + rank) for pid, rank in dense_rank.items()}
    for pid, rank in lexical_rank.items():
        rrf[pid] = rrf.get(pid, 0.0) + 1.0 / (60 + rank)
    expected_order = sorted(rrf, key=lambda pid: (-rrf[pid], pid))[:10]
    if expected_order != case["candidate_ids_in_phase10_order"]:
        raise ValueError(f"Frozen candidate pool drift for {case['query_id']}")

    rows = frame.set_index(frame.product_id.astype(str), drop=False)
    candidates = []
    for rank, pid in enumerate(expected_order, 1):
        row = rows.loc[pid]
        sources = {}
        if pid in dense_rank:
            sources["dense"] = CandidateSource(dense_rank[pid], dense_score[pid])
        if pid in lexical_rank:
            sources["lexical"] = CandidateSource(lexical_rank[pid], lexical_score[pid])
        expected_dense = case["dense_ranks"].get(pid)
        expected_lexical = case["lexical_ranks"].get(pid)
        if expected_dense != dense_rank.get(pid) or expected_lexical != lexical_rank.get(pid):
            raise ValueError(f"Frozen retrieval ranks drift for {case['query_id']} / {pid}")
        rating = None if pd.isna(row.rating) else float(row.rating)
        candidates.append(HybridCandidate(
            rank=rank,
            product_id=pid,
            product_name=str(row.product_name),
            category=str(row.category),
            brand=None if pd.isna(row.brand) else str(row.brand),
            discounted_price=float(row.discounted_price),
            rating=rating,
            rrf_score=rrf[pid],
            sources=sources,
            metadata={"retrieval_text_source": "canonical_products.parquet", "retrieval_scope": "offline_fixture"},
        ))
    return candidates


def run() -> dict[str, Any]:
    fixture, frame, provider, index, model = _load()
    methods: list[RerankingMethod] = [RerankingMethod.RRF, RerankingMethod.MULTI_SIGNAL]
    cross_encoder = None
    cross_encoder_load_ms = None
    cross_encoder_status: dict[str, str] = {"status": "NOT_RUN", "reason": "Pinned checkpoint is not installed locally."}
    model_dir = Path(os.getenv("SHOPASSIST_PHASE11_MODEL_DIR", ROOT / ".models/phase11/ms-marco-MiniLM-L2-v2"))
    model_path = str(model_dir) if model_dir.joinpath("model.safetensors").exists() else None
    try:
        started = time.perf_counter()
        cross_encoder = load_local_cross_encoder(model_path=model_path, max_length=512, device="cpu")
        cross_encoder_load_ms = (time.perf_counter() - started) * 1000
        methods.append(RerankingMethod.CROSS_ENCODER)
        cross_encoder_status = {"status": "REAL_MODEL_LOADED", "reason": "Pinned CPU model loaded locally."}
    except Exception as exc:
        cross_encoder_status = {"status": "NOT_RUN", "reason": f"Local model load unavailable ({type(exc).__name__}); no network fallback attempted."}
    per_query: list[dict[str, Any]] = []
    samples: dict[str, list[float]] = {method.value: [] for method in methods}
    aggregate: dict[str, list[dict[str, float]]] = {method.value: [] for method in methods}
    for case in fixture["cases"]:
        candidates = _candidate_set(case, frame, index, model)
        q8 = QueryUnderstandingResult(
            query=case["query"],
            output=QueryUnderstandingOutput(semantic_query=case["query"], hard_constraints=HardConstraints(), soft_preferences=[]),
        )
        q9 = PreferenceRepresentationResult(
            semantic_query=case["query"], has_preferences=False, status=RepresentationStatus.NO_PREFERENCES
        )
        retrieval = HybridRetrievalResult(status=HybridRetrievalStatus.SUCCESS, candidates=candidates)
        result_row: dict[str, Any] = {"query_id": case["query_id"], "query": case["query"], "methods": {}}
        for method in methods:
            service = RerankingService(
                provider,
                config=RerankingConfig(top_k=5, method=method),
                cross_encoder=cross_encoder if method == RerankingMethod.CROSS_ENCODER else None,
            )
            measured_ms: list[float] = []
            result = None
            for _ in range(25):
                started = time.perf_counter()
                result = service.rerank(q8, q9, retrieval)
                measured_ms.append((time.perf_counter() - started) * 1000)
            if result is None or result.status.value != "SUCCESS":
                raise RuntimeError(f"Reranker failed for {case['query_id']} with {method.value}")
            ranked_ids = [product.product_id for product in result.products]
            metric = _metrics(ranked_ids, case["qrels"], k=5)
            metric["reranking_latency_median_ms_25_warm"] = statistics.median(measured_ms)
            samples[method.value].append(metric["reranking_latency_median_ms_25_warm"])
            aggregate[method.value].append(metric)
            result_row["methods"][method.value] = {
                "ranked_product_ids": ranked_ids,
                "score_components": {p.product_id: p.score_components for p in result.products},
                "metrics": metric,
            }
        per_query.append(result_row)

    comparisons: dict[str, Any] = {}
    for method, rows in aggregate.items():
        keys = rows[0].keys()
        comparisons[method] = {key: statistics.mean(row[key] for row in rows) for key in keys}
    import torch
    return {
        "status": "MEASURED_OFFLINE_COMPONENT_EVALUATION",
        "dataset_id": fixture["dataset_id"],
        "case_count": len(fixture["cases"]),
        "catalog_product_count": len(frame),
        "candidate_pool_size": 10,
        "top_k": 5,
        "methods": list(comparisons),
        "metric_definitions": {
            "ndcg@5": "Graded gain 2^relevance-1, logarithmic rank discount, idealized over the judged fixed candidate pool.",
            "mrr": "Reciprocal rank of first candidate with grade >= 2.",
            "precision@5": "Fraction of top-five candidates with grade >= 2.",
        },
        "annotation_limitations": fixture["annotation_method"],
        "candidate_pool_method": fixture["pool_method"],
        "catalog_snapshot": provider.manifest,
        "model": {"id": MODEL_ID, "revision": "local cache revision not recorded", "device": str(model.device)},
        "runtime": {"python": platform.python_version(), "torch": torch.__version__, "cuda_available": torch.cuda.is_available(), "processor": platform.processor()},
        "comparison": comparisons,
        "per_query": per_query,
        "cross_encoder": {
            **cross_encoder_status,
            "repository": "cross-encoder/ms-marco-MiniLM-L2-v2",
            "revision": "1b5cd67b15209f24824c50370e0397743aa9b787",
            "device": "cpu",
            "load_time_ms": cross_encoder_load_ms,
        },
        "combined": {"status": "NOT_RUN", "reason": "No development split exists to select weights; combined remains disabled."},
        "statistical_inference": "Not estimated: four curated queries are too few and judgments are from one engineer.",
    }


if __name__ == "__main__":
    report = run()
    (OUT_DIR / "phase11_evaluation_report_current.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT_DIR / "phase11_per_query_results_current.json").write_text(json.dumps(report["per_query"], indent=2), encoding="utf-8")
    (OUT_DIR / "phase11_method_comparison_current.json").write_text(json.dumps(report["comparison"], indent=2), encoding="utf-8")
    performance = {
        "status": "MEASURED_OFFLINE_COMPONENT_TIMINGS",
        "candidate_count": report["candidate_pool_size"],
        "top_k": report["top_k"],
        "repetitions_per_query_method": 25,
        "measurement": "Warm service wall time per candidate set; excludes Phase 10 retrieval and BGE query encoding.",
        "methods": {
            method: {"median_ms_mean_across_queries": values["reranking_latency_median_ms_25_warm"]}
            for method, values in report["comparison"].items()
        },
        "cross_encoder": report["cross_encoder"],
        "runtime": report["runtime"],
    }
    (OUT_DIR / "phase11_performance_report_current.json").write_text(json.dumps(performance, indent=2), encoding="utf-8")
    print(json.dumps({"comparison": report["comparison"], "runtime": report["runtime"], "model": report["model"]}, indent=2))
