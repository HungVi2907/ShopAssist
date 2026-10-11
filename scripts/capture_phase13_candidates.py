"""Capture real Phase 10 Top-20 output for reviewed Phase 13 query inputs.

Requires the project runtime and read-only Supabase credentials. This script
does not call the Phase 8 LLM or produce relevance labels.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.validate_phase13_dataset import DEFAULT_DATASET, ROOT, read_jsonl
except ModuleNotFoundError:  # direct script execution
    from validate_phase13_dataset import DEFAULT_DATASET, ROOT, read_jsonl


async def capture(dataset: Path, output: Path) -> None:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite frozen or staged pool: {output}")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    import pandas as pd
    from shopassist.core.config import settings
    from shopassist.db.connection import get_async_engine
    from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput, QueryUnderstandingResult
    from shopassist.preferences.service import PreferenceRepresentationService
    from shopassist.retrieval.hybrid import HybridRetrievalConfig, HybridRetrievalService
    from shopassist.retrieval.tfidf import TFIDFIndex
    from sqlalchemy import text

    manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
    catalog = ROOT / manifest["catalog_artifact"]
    digest = hashlib.sha256(catalog.read_bytes()).hexdigest()
    if digest != manifest["catalog_sha256"]:
        raise ValueError("Catalog differs from pinned Phase 13 snapshot")
    frame = pd.read_parquet(catalog, columns=["product_id", "product_name", "category", "brand", "discounted_price", "rating", "retrieval_text"])
    texts = dict(zip(frame.product_id.astype(str), frame.retrieval_text.astype(str)))
    if len(texts) != len(frame) or any(not value.strip() for value in texts.values()):
        raise ValueError("Catalog IDs or canonical text are invalid")
    catalog_rows = frame.set_index(frame.product_id.astype(str), drop=False)
    engine = get_async_engine(settings.get_raw_supabase_db_url(), pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            db_ids = {str(row[0]) for row in (await connection.execute(text("SELECT product_id FROM public.products"))).all()}
        if db_ids != set(texts):
            raise ValueError("Live products table IDs differ from the pinned catalog snapshot")
        service = HybridRetrievalService(engine, TFIDFIndex.load(ROOT / "data/processed/tfidf"), config=HybridRetrievalConfig(top_n=20))
        preference_service = PreferenceRepresentationService()
        rows = []
        for query in read_jsonl(dataset / "queries.jsonl"):
            expected = query.get("expected_query_understanding")
            if query.get("annotation_status") != "ADJUDICATED" or expected is None:
                continue
            if query.get("expected_status") not in {"SUCCESS", "NO_RESULTS"}:
                continue
            q8 = QueryUnderstandingResult(query=query["raw_query"], output=QueryUnderstandingOutput(
                semantic_query=expected["semantic_query"],
                hard_constraints=HardConstraints(**expected["hard_constraints"]),
                soft_preferences=expected["soft_preferences"],
                needs_clarification=expected["needs_clarification"],
                clarification_reason=expected.get("clarification_reason"),
            ))
            q9 = preference_service.represent(q8)
            operators = query.get("price_boundary_semantics") or {}
            price_semantics = {}
            if operators.get("min_operator"):
                price_semantics["min_inclusive"] = operators["min_operator"] == ">="
            if operators.get("max_operator"):
                price_semantics["max_inclusive"] = operators["max_operator"] == "<="
            result = await service.retrieve(q8, q9, top_n=20, price_boundary_semantics=price_semantics)
            if result.status.value not in {"SUCCESS", "NO_RESULTS"}:
                raise RuntimeError(f"{query['query_id']}: Phase 10 returned {result.status.value}: {result.diagnostic_reason}")
            candidates = []
            for candidate in result.candidates:
                if candidate.product_id not in texts:
                    raise ValueError(f"Phase 10 product absent from catalog: {candidate.product_id}")
                canonical = catalog_rows.loc[candidate.product_id]
                expected_brand = None if pd.isna(canonical.brand) else str(canonical.brand)
                expected_rating = None if pd.isna(canonical.rating) else float(canonical.rating)
                if (candidate.product_name != str(canonical.product_name) or candidate.category != str(canonical.category)
                        or candidate.brand != expected_brand or abs(candidate.discounted_price - float(canonical.discounted_price)) > 1e-6
                        or (candidate.rating is None) != (expected_rating is None)
                        or (candidate.rating is not None and abs(candidate.rating - expected_rating) > 1e-6)):
                    raise ValueError(f"Phase 10 metadata differs from pinned catalog: {candidate.product_id}")
                record = candidate.to_dict()
                record["retrieval_text"] = texts[candidate.product_id]
                candidates.append(record)
            eligible = frame
            hard = expected["hard_constraints"]
            if hard.get("category") is not None:
                eligible = eligible[eligible["category"] == hard["category"]]
            if hard.get("brand") is not None:
                eligible = eligible[eligible["brand"].astype(str).str.casefold() == str(hard["brand"]).casefold()]
            for field, op_key, default in (("min_price", "min_operator", ">="), ("max_price", "max_operator", "<=")):
                if hard.get(field) is not None:
                    operator = operators.get(op_key) or default
                    prices = eligible["discounted_price"]
                    value = float(hard[field])
                    eligible = eligible[{">": prices > value, ">=": prices >= value,
                                         "<": prices < value, "<=": prices <= value}[operator]]
            if hard.get("min_rating") is not None:
                eligible = eligible[eligible["rating"] >= float(hard["min_rating"])]
            catalog_eligible_count = len(eligible)
            rows.append({
                "query_id": query["query_id"], "phase10_status": result.status.value,
                "catalog_sha256": digest, "candidate_count": len(candidates),
                "capture_status": "FROZEN", "capture_timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "query_interpretation_sha256": hashlib.sha256(json.dumps(expected, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest(),
                "catalog_eligible_count": catalog_eligible_count,
                "no_result_verified": bool(query["expected_status"] == "NO_RESULTS" and catalog_eligible_count == 0 and result.status.value == "NO_RESULTS"),
                "provenance": {"service": "HybridRetrievalService", "contract_version": "1.0.0", "top_n": 20,
                               "query_input": "human_adjudicated_phase8_oracle", "retrieval_mode": "live_pgvector_plus_saved_tfidf",
                               "applied_constraints": result.applied_constraints,
                               "retrieval_config": {"top_n": 20, "price_boundary_semantics": price_semantics,
                                                    "tfidf_manifest": "data/processed/tfidf/tfidf_manifest.json"}},
                "candidates": candidates,
            })
            print(f"{query['query_id']}: {result.status.value} {len(candidates)}")
        if not rows:
            raise RuntimeError("No adjudicated query inputs are available for candidate capture")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--out", type=Path, required=True, help="New, nonexisting staging output path")
    args = parser.parse_args()
    asyncio.run(capture(args.dataset, args.out))


if __name__ == "__main__":
    main()
