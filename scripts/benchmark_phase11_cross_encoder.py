"""Measure real Cross-Encoder load, token truncation, and warm CPU inference."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import time
from typing import Any

import pandas as pd
import torch

from shopassist.reranking import CrossEncoderScorer, load_local_cross_encoder


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/processed/products.parquet"
CASES = ROOT / "data/interim/phase11/phase11_reranking_cases.json"
OUT = ROOT / "data/interim/phase11/phase11_cross_encoder_benchmark.json"
MODEL_ID = "cross-encoder/ms-marco-MiniLM-L2-v2"
REVISION = "1b5cd67b15209f24824c50370e0397743aa9b787"
MODEL_DIR = Path(os.getenv("SHOPASSIST_PHASE11_MODEL_DIR", ROOT / ".models/phase11/ms-marco-MiniLM-L2-v2"))


def _load_scorer() -> tuple[CrossEncoderScorer, float]:
    try:
        import psutil
        process = psutil.Process()
        rss_before = process.memory_info().rss
    except ImportError:
        process = None
        rss_before = None
    start = time.perf_counter()
    scorer = load_local_cross_encoder(
        MODEL_ID, revision=REVISION, model_path=str(MODEL_DIR), max_length=512, device="cpu"
    )
    load_ms = (time.perf_counter() - start) * 1000
    rss_after = process.memory_info().rss if process is not None else None
    scorer._load_memory_mb = {
        "process_rss_before_mb": rss_before / (1024 * 1024) if rss_before is not None else None,
        "process_rss_after_mb": rss_after / (1024 * 1024) if rss_after is not None else None,
        "process_rss_delta_mb": (rss_after - rss_before) / (1024 * 1024) if rss_after is not None and rss_before is not None else None,
        "measurement": "Process RSS via psutil; null when psutil is unavailable.",
    }
    return scorer, load_ms


def run(iterations: int = 30) -> dict[str, Any]:
    scorer, load_ms = _load_scorer()
    catalog = pd.read_parquet(CATALOG, columns=["product_id", "retrieval_text"])
    if catalog.product_id.isna().any() or catalog.product_id.astype(str).duplicated().any():
        raise ValueError("Catalog product IDs must be present and unique")
    if catalog.retrieval_text.isna().any() or (catalog.retrieval_text.astype(str).str.strip() == "").any():
        raise ValueError("Canonical retrieval_text must be present for every catalog product")
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    # Use real queries and real catalog text. This benchmark is for runtime/token
    # behavior; it does not imply relevance judgments for these constructed pairs.
    queries = [item["query"] for item in cases]
    lengths: list[int] = []
    truncation_examples: list[dict[str, Any]] = []
    for query in queries:
        for row in catalog.itertuples(index=False):
            count = scorer.token_length(query, str(row.retrieval_text))
            lengths.append(count)
            if count > 512 and len(truncation_examples) < 100:
                truncated = scorer.model.tokenizer(
                    query, str(row.retrieval_text), truncation=True, max_length=512, add_special_tokens=True
                )["input_ids"]
                text_tokens = scorer.model.tokenizer(
                    str(row.retrieval_text), add_special_tokens=False, truncation=False
                )["input_ids"]
                truncation_examples.append({
                    "query": query,
                    "product_id": str(row.product_id),
                    "full_pair_tokens": count,
                    "truncated_pair_tokens": len(truncated),
                    "canonical_text_tokens": len(text_tokens),
                    "canonical_tail_token_loss_estimate": max(0, len(text_tokens) - max(0, len(truncated) - 3)),
                    "canonical_text_tail_preview": str(row.retrieval_text)[-500:],
                })
    counts = sorted(lengths)
    text_rows = catalog.set_index(catalog.product_id.astype(str), drop=False)
    per_pool: dict[str, Any] = {}
    for pool_size in (10, 20, 25):
        records: list[dict[str, Any]] = []
        samples: list[float] = []
        for case in cases:
            ids = case["candidate_ids_in_phase10_order"][:pool_size]
            # Existing frozen candidate fixtures contain ten candidates. For the
            # larger latency pools, extend from distinct real catalog products;
            # these extensions are explicitly performance-only, not Phase 10 evidence.
            ids.extend(pid for pid in text_rows.index if pid not in set(ids) and len(ids) < pool_size)
            texts = [str(text_rows.loc[pid].retrieval_text) for pid in ids]
            pairs = [(case["query"], value) for value in texts]
            for _ in range(5):
                scorer.predict(pairs, batch_size=16)
            for _ in range(iterations):
                start = time.perf_counter()
                scores = scorer.predict(pairs, batch_size=16)
                samples.append((time.perf_counter() - start) * 1000)
                if len(scores) != len(pairs):
                    raise ValueError("Cross-Encoder returned a score count different from the input pair count")
            records.append({"query_id": case["query_id"], "candidate_count": len(pairs), "iterations": iterations})
        per_pool[str(pool_size)] = {
            "batch_size": 16,
            "device": "cpu",
            "query_count": len(records),
            "iterations_per_query": iterations,
            "median_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[min(len(samples) - 1, int(0.95 * len(samples)))],
            "scope": "Cross-Encoder inference only; 20/25 pools extend frozen Phase 10 fixtures with canonical catalog rows and are performance-only.",
        }
    manifest_path = ROOT / "data/interim/phase11/phase11_model_manifest.json"
    model_manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    return {
        "status": "MEASURED_REAL_MODEL_CPU_BENCHMARK",
        "model": {"repository": MODEL_ID, "revision": REVISION, "device": "cpu", "batch_size": 16, "load_time_ms": load_ms, "memory": scorer._load_memory_mb, "artifact_manifest": str(manifest_path), "artifact_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest() if manifest_path.exists() else None},
        "catalog": {"path": str(CATALOG.relative_to(ROOT)), "product_count": len(catalog)},
        "runtime": {"python": platform.python_version(), "torch": torch.__version__, "processor": platform.processor(), "cuda_available": torch.cuda.is_available(), "iterations_per_query": iterations},
        "tokenization": {
            "pair_count": len(lengths), "max_length": 512,
            "token_count_p50": statistics.median(counts),
            "token_count_p95": counts[min(len(counts) - 1, int(.95 * len(counts)))],
            "token_count_max": max(counts),
            "truncated_pair_count": sum(value > 512 for value in lengths),
            "truncated_pair_fraction": sum(value > 512 for value in lengths) / len(lengths),
            "tail_loss_sample": truncation_examples,
            "important_specification_review": "Requires human review of tail_loss_sample against canonical text; tokenizer statistics alone cannot determine semantic importance.",
        },
        "warm_inference": per_pool,
        "model_config": model_manifest.get("configuration") if model_manifest else None,
        "limitations": ["CPU load memory footprint not measured in this runner", "no Phase 10 retrieval or full Phase 10-to-11 latency", "token truncation semantic impact requires human review"],
    }


if __name__ == "__main__":
    report = run()
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "model": report["model"], "warm_inference": report["warm_inference"], "tokenization": {k: v for k, v in report["tokenization"].items() if k != "tail_loss_sample"}}, indent=2))
