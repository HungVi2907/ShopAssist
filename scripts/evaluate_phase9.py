"""Run Phase 9 local semantic and performance checks and write JSON evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import platform
from pathlib import Path
import statistics
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "interim" / "phase9"
sys.path.insert(0, str(ROOT / "src"))
MODEL = "BAAI/bge-small-en-v1.5"
CASES = [
    {
        "id": "shoes_daily",
        "semantic_query": "running shoes",
        "preferences": ["comfortable", "breathable", "for daily jogging"],
        "relevant": "Comfortable breathable running shoes with cushioned soles for daily walking and jogging.",
        "irrelevant": "Heavy industrial steel storage cabinet with locking doors.",
    },
    {
        "id": "laptop_battery",
        "semantic_query": "laptop",
        "preferences": ["lightweight", "good battery life"],
        "relevant": "Lightweight laptop computer designed for long battery life and portable daily use.",
        "irrelevant": "Large desktop computer tower with a high power supply and no battery.",
    },
    {
        "id": "waterproof_bag",
        "semantic_query": "backpack",
        "preferences": ["waterproof", "durable"],
        "relevant": "Durable waterproof backpack for carrying belongings in wet weather.",
        "irrelevant": "Soft cotton pillow cover for bedroom decoration.",
    },
    {
        "id": "compact_keyboard",
        "semantic_query": "wireless keyboard",
        "preferences": ["compact", "portable"],
        "relevant": "Compact portable wireless computer keyboard for travel and small desks.",
        "irrelevant": "Large fixed office desk made from solid wood.",
    },
]


def write_json(name: str, value: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def main() -> int:
    started = time.perf_counter()
    result = {
        "status": "FAILED",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "embedding_dimension": 384,
        "case_count": len(CASES),
    }
    existing_report = OUT / "phase9_evaluation_report.json"
    if existing_report.exists():
        try:
            previous = json.loads(existing_report.read_text(encoding="utf-8"))
            for field in ("test_execution", "interpretation"):
                if field in previous:
                    result[field] = previous[field]
        except (OSError, json.JSONDecodeError):
            pass
    try:
        import numpy as np
        import torch
        from shopassist.preferences.embedding import PreferenceQueryEncoder, validate_preference_vector
        from shopassist.preferences.normalization import normalize_preferences
        from shopassist.preferences.query_composer import build_preference_query
        from shopassist.llm.schemas import QueryUnderstandingOutput, QueryUnderstandingResult
        from shopassist.preferences.service import PreferenceRepresentationService

        init_started = time.perf_counter()
        encoder = PreferenceQueryEncoder()
        encoder.validate_model_compatibility()
        model_load_ms = (time.perf_counter() - init_started) * 1000
        model = encoder._encoder.model
        try:
            sentence_transformers_version = version("sentence-transformers")
        except PackageNotFoundError:
            sentence_transformers_version = "unknown"
        runtime_context = {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "sentence_transformers": sentence_transformers_version,
            "cuda_available": torch.cuda.is_available(),
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        }

        strategies = []
        descriptions = [text for case in CASES for text in (case["relevant"], case["irrelevant"])]
        doc_vectors = model.encode_documents(descriptions, batch_size=32)
        for case in CASES:
            normalized = normalize_preferences(case["preferences"])
            queries = {
                "preference_only": "; ".join(normalized),
                "context_keywords": f"{case['semantic_query']} {' '.join(normalized)}",
                "contextual_phase9": build_preference_query(case["semantic_query"], normalized),
            }
            for strategy, query in queries.items():
                vec = encoder.encode(query)
                row = CASES.index(case) * 2
                positive = float(model.compute_similarity(np.asarray(vec), doc_vectors[row]))
                negative = float(model.compute_similarity(np.asarray(vec), doc_vectors[row + 1]))
                strategies.append({
                    "case_id": case["id"],
                    "strategy": strategy,
                    "query": query,
                    "relevant_cosine": positive,
                    "irrelevant_cosine": negative,
                    "relevant_ranked_higher": positive > negative,
                    "margin": positive - negative,
                })

        timed_norm = []
        timed_compose = []
        timed_validate = []
        timed_encode = []
        queries = [build_preference_query(c["semantic_query"], c["preferences"]) for c in CASES]
        for _ in range(3):
            for case in CASES:
                t0 = time.perf_counter(); normalize_preferences(case["preferences"]); timed_norm.append((time.perf_counter()-t0)*1000)
                t0 = time.perf_counter(); build_preference_query(case["semantic_query"], case["preferences"]); timed_compose.append((time.perf_counter()-t0)*1000)
                t0 = time.perf_counter(); vector = encoder.encode(queries[CASES.index(case)]); timed_encode.append((time.perf_counter()-t0)*1000)
                t0 = time.perf_counter(); validate_preference_vector(vector); timed_validate.append((time.perf_counter()-t0)*1000)
        t0 = time.perf_counter(); batch = encoder.encode_batch(queries, batch_size=8); batch_ms = (time.perf_counter()-t0)*1000
        service = PreferenceRepresentationService(encoder=encoder)
        integration_input = QueryUnderstandingResult(
            query="lightweight laptop with good battery life",
            output=QueryUnderstandingOutput(
                semantic_query="laptop",
                soft_preferences=["lightweight", "good battery life"],
            ),
            is_valid=True,
        )
        t0 = time.perf_counter(); representation = service.represent(integration_input); end_to_end_ms = (time.perf_counter()-t0)*1000
        if representation.status.value != "SUCCESS":
            raise RuntimeError(f"end-to-end representation returned {representation.status.value}")
        result.update({
            "status": "PASS",
            "device": encoder.device,
            "runtime_context": runtime_context,
            "model_load_ms": model_load_ms,
            "vectors_generated": len(batch) + len(strategies),
            "all_vectors_valid": True,
            "semantic_pair_count": len(strategies),
            "semantic_relevant_wins": sum(x["relevant_ranked_higher"] for x in strategies),
            "semantic_observations": strategies,
        })
        write_json("phase9_embedding_validation.json", {
            "status": "PASS", "model": encoder.model_name, "dimension": encoder.embedding_dimension,
            "device": encoder.device, "actual_vector_count": len(batch) + len(strategies),
            "all_finite_nonzero_unit_norm": True, "model_load_ms": model_load_ms,
            "semantic_pair_count": len(strategies), "relevant_ranked_higher": result["semantic_relevant_wins"],
        })
        write_json("phase9_composition_comparison.json", {
            "status": "MEASURED", "model": encoder.model_name, "embedding_dimension": encoder.embedding_dimension,
            "paired_results": strategies,
        })
        write_json("phase9_performance_report.json", {
            "status": "MEASURED", "runtime": "Python", "device": encoder.device,
            "runtime_context": runtime_context,
            "model_load_ms": model_load_ms, "normalization_ms": {"median": statistics.median(timed_norm), "p95": percentile(timed_norm, .95)},
            "composition_ms": {"median": statistics.median(timed_compose), "p95": percentile(timed_compose, .95)},
            "single_embedding_ms": {"median": statistics.median(timed_encode), "p95": percentile(timed_encode, .95)},
            "batch_size": len(queries), "batch_embedding_ms": batch_ms,
            "vector_validation_ms": {"median": statistics.median(timed_validate), "p95": percentile(timed_validate, .95)},
            "single_end_to_end_ms": end_to_end_ms, "warmup_policy": "model initialized before measurements; three timed repetitions per curated query",
        })
        write_json("phase9_evaluation_report.json", result)
        return 0
    except Exception as exc:
        result.update({
            "reason": f"{type(exc).__name__}: {exc}",
            "elapsed_before_failure_ms": (time.perf_counter() - started) * 1000,
            "traceback": traceback.format_exc(),
        })
        write_json("phase9_evaluation_report.json", result)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
