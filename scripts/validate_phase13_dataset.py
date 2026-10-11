"""Validate Phase 13 data and emit a machine-readable audit report.

The pilot may pass structural checks while remaining unannotated. Readiness is
reported separately; a structural PASS never means Phase 14 is authorized.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data/evaluation/phase13/v1"
VALID_TYPES = {"SIMPLE_CONSTRAINT", "MULTI_CONSTRAINT", "SOFT_PREFERENCE", "USE_CASE", "MIXED_HARD_SOFT", "DIFFICULT_SEMANTIC", "MISSING_ATTRIBUTE", "NO_RESULT", "CLARIFICATION_UNSUPPORTED"}
VALID_STATUSES = {"SUCCESS", "NO_RESULTS", "CLARIFICATION_REQUIRED", "UNSUPPORTED_INTENT"}
VALID_SUPPORT = {"SUPPORTED", "PARTIALLY_SUPPORTED", "UNSUPPORTED", "NOT_ENOUGH_INFORMATION"}
VALID_FACTUAL = {"CORRECT", "PARTIALLY_CORRECT", "INCORRECT", "NOT_ENOUGH_INFORMATION"}
VALID_RELEVANCE = {"RELEVANT", "PARTIALLY_RELEVANT", "IRRELEVANT"}
VALID_MISSING = {"CORRECTLY_DISTINGUISHED", "MISSTATED_ABSENCE", "NOT_APPLICABLE"}


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{number}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path.name}:{number}: expected object")
            rows.append(value)
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def tokens(value: str) -> set[str]:
    return set(re.findall(r"\w+", unicodedata.normalize("NFC", str(value)).casefold()))


def near_duplicates(rows: list[dict], threshold: float = 0.8) -> list[dict]:
    result = []
    for i, left in enumerate(rows):
        a = tokens(left.get("raw_query") or "")
        for right in rows[i + 1:]:
            b = tokens(right.get("raw_query") or "")
            similarity = len(a & b) / len(a | b) if a | b else 1.0
            if similarity >= threshold:
                result.append({"left": left["query_id"], "right": right["query_id"], "jaccard": round(similarity, 3)})
    return result


def _catalog_records(path: Path) -> dict[str, dict]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas/Parquet support is required when product rows exist") from exc
    frame = pd.read_parquet(path, columns=["product_id", "product_name", "category", "brand", "discounted_price", "rating", "retrieval_text"])
    records = {}
    for _, row in frame.iterrows():
        pid = str(row["product_id"])
        records[pid] = {"product_name": str(row["product_name"]), "category": str(row["category"]),
                        "brand": None if pd.isna(row["brand"]) else str(row["brand"]),
                        "discounted_price": float(row["discounted_price"]),
                        "rating": None if pd.isna(row["rating"]) else float(row["rating"]),
                        "retrieval_text": str(row["retrieval_text"])}
    if len(records) != len(frame):
        raise ValueError("Catalog contains duplicate product IDs")
    return records


def weighted_kappa(pairs: list[tuple[int, int]]) -> float | None:
    """Quadratic-weighted Cohen kappa for two independent 0–3 reviewers."""
    if len(pairs) < 2:
        return None
    n = len(pairs)
    left, right = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    observed = sum((a - b) ** 2 for a, b in pairs) / n
    expected = sum((a - b) ** 2 * left[a] * right[b] for a in range(4) for b in range(4)) / (n * n)
    return round(1 - observed / expected, 6) if expected else None


def validate(dataset: Path = DEFAULT_DATASET, *, catalog_ids: set[str] | None = None, catalog_path: Path | None = None) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    required = ["queries.jsonl", "candidate_pools.jsonl", "qrels.csv", "query_annotations.csv", "relevance_annotations.csv", "generation_claims.csv", "splits.json", "dataset_manifest.json"]
    missing = [name for name in required if not (dataset / name).is_file()]
    if missing:
        return {"status": "FAIL", "errors": [f"Missing files: {', '.join(missing)}"], "warnings": [], "statistics": {}}
    try:
        queries = read_jsonl(dataset / "queries.jsonl")
        pools = read_jsonl(dataset / "candidate_pools.jsonl")
        qrels = read_csv(dataset / "qrels.csv")
        query_reviews = read_csv(dataset / "query_annotations.csv")
        relevance_reviews = read_csv(dataset / "relevance_annotations.csv")
        claims = read_csv(dataset / "generation_claims.csv")
        splits = json.loads((dataset / "splits.json").read_text(encoding="utf-8"))
        manifest = json.loads((dataset / "dataset_manifest.json").read_text(encoding="utf-8"))
        query_decisions = read_jsonl(dataset / "query_adjudications.jsonl") if (dataset / "query_adjudications.jsonl").is_file() else []
        relevance_decisions = read_csv(dataset / "relevance_adjudications.csv") if (dataset / "relevance_adjudications.csv").is_file() else []
        claim_decisions = read_csv(dataset / "claim_adjudications.csv") if (dataset / "claim_adjudications.csv").is_file() else []
        claim_reviews = read_csv(dataset / "claim_annotations.csv") if (dataset / "claim_annotations.csv").is_file() else []
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return {"status": "FAIL", "errors": [str(exc)], "warnings": [], "statistics": {}}
    required_columns = {
        "qrels.csv": {"query_id", "product_id", "reviewer_a_id", "reviewer_b_id", "reviewer_a_grade", "reviewer_b_grade", "adjudicated_grade", "price_violation"},
        "query_annotations.csv": {"query_id", "annotator_id", "semantic_query", "category", "soft_preferences_json", "min_operator", "max_operator", "expected_status"},
        "relevance_annotations.csv": {"query_id", "product_id", "annotator_id", "relevance_grade", "comment"},
        "generation_claims.csv": {"claim_id", "query_id", "product_id", "claim", "evidence_ids_json", "evidence_text_json", "reviewer_a_id", "reviewer_b_id", "adjudicated_support"},
    }
    for name, required_fields in required_columns.items():
        with (dataset / name).open(encoding="utf-8-sig", newline="") as handle:
            header = set(next(csv.reader(handle), []))
        if missing_fields := required_fields - header:
            errors.append(f"{name}: missing columns {sorted(missing_fields)}")
    catalog = catalog_path or ROOT / manifest.get("catalog_artifact", "data/processed/products.parquet")
    if not catalog.is_file():
        errors.append(f"Catalog artifact missing: {catalog}")
    else:
        actual_hash = hashlib.sha256(catalog.read_bytes()).hexdigest()
        if actual_hash != manifest.get("catalog_sha256"):
            errors.append("Catalog SHA-256 differs from dataset manifest")
    ids = [q.get("query_id") for q in queries]
    query_set = set(ids)
    if len(ids) != len(set(ids)):
        errors.append("Duplicate query IDs")
    normalized = [unicodedata.normalize("NFC", str(q.get("raw_query") or "")).strip().casefold() for q in queries]
    if len(normalized) != len(set(normalized)):
        errors.append("Exact duplicate raw queries")
    category_names = {c["category"] for c in json.loads((ROOT / "data/interim/selected_categories.json").read_text(encoding="utf-8"))["selected_categories"] if c["selection_status"] == "SELECT"}
    for q in queries:
        qid = q.get("query_id", "<missing>")
        if not re.fullmatch(r"Q\d{4}", str(qid)) or not isinstance(q.get("raw_query"), str) or not q["raw_query"].strip():
            errors.append(f"{qid}: invalid ID or empty query")
        if q.get("query_type") not in VALID_TYPES or q.get("language") not in {"en", "vi"}:
            errors.append(f"{qid}: invalid taxonomy or language")
        if q.get("planning_category") not in category_names:
            errors.append(f"{qid}: invalid planning category")
        if not q.get("intent_group"):
            errors.append(f"{qid}: missing intent group")
        status = q.get("expected_status")
        if status is not None and status not in VALID_STATUSES:
            errors.append(f"{qid}: invalid expected status")
        understanding = q.get("expected_query_understanding")
        if understanding is not None:
            if not isinstance(understanding, dict) or not isinstance(understanding.get("hard_constraints"), dict):
                errors.append(f"{qid}: invalid query understanding object")
                continue
            hc = understanding.get("hard_constraints", {})
            if not isinstance(understanding.get("semantic_query"), str) or not understanding["semantic_query"].strip():
                errors.append(f"{qid}: semantic_query missing")
            if hc.get("category") is not None and hc["category"] not in category_names:
                errors.append(f"{qid}: invalid canonical category")
            if not isinstance(understanding.get("soft_preferences"), list):
                errors.append(f"{qid}: preferences must be a list")
            for field in ("min_price", "max_price", "min_rating"):
                value = hc.get(field)
                if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0):
                    errors.append(f"{qid}: invalid {field}")
            bounds = q.get("price_boundary_semantics") or {}
            for bound, operator, accepted in (("min_price", "min_operator", {">", ">="}), ("max_price", "max_operator", {"<", "<="})):
                value, op = hc.get(bound), bounds.get(operator)
                if (value is None and op is not None) or (value is not None and op not in accepted):
                    errors.append(f"{qid}: {operator} inconsistent with {bound}")
            if status is None:
                errors.append(f"{qid}: interpretation has no expected status")
        elif q.get("annotation_status") != "UNREVIEWED_DRAFT":
            errors.append(f"{qid}: missing reviewed interpretation")
    query_decision_map = {row.get("query_id"): row for row in query_decisions}
    if len(query_decision_map) != len(query_decisions):
        errors.append("Duplicate query adjudication decisions")
    if set(query_decision_map) - query_set:
        errors.append("Query adjudication contains unknown query IDs")
    for q in queries:
        if q.get("annotation_status") == "ADJUDICATED":
            decision = query_decision_map.get(q["query_id"])
            if not decision or not decision.get("adjudicator_id"):
                errors.append(f"{q['query_id']}: missing named query adjudication decision")
            elif decision.get("expected_status") != q.get("expected_status"):
                errors.append(f"{q['query_id']}: query adjudication status differs from final query")
    duplicates = near_duplicates(queries)
    if duplicates:
        warnings.append(f"{len(duplicates)} near-duplicate query pairs require review")
    pool_by_qid = {}
    product_rows = bool(pools or qrels or relevance_reviews or claims)
    catalog_records: dict[str, dict] = {}
    if product_rows and catalog_ids is None:
        try:
            catalog_records = _catalog_records(catalog)
            catalog_ids = set(catalog_records)
        except (RuntimeError, ValueError, OSError) as exc:
            errors.append(str(exc))
    catalog_ids = catalog_ids or set()
    for pool in pools:
        qid = pool.get("query_id")
        if qid not in query_set or qid in pool_by_qid:
            errors.append(f"Invalid or duplicate candidate pool: {qid}")
        matched_query = next((query for query in queries if query.get("query_id") == qid), None)
        if matched_query and (matched_query.get("annotation_status") != "ADJUDICATED" or matched_query.get("expected_status") not in {"SUCCESS", "NO_RESULTS"}):
            errors.append(f"{qid}: candidate pool lacks adjudicated retrieval-eligible query")
        pool_by_qid[qid] = pool
        if pool.get("catalog_sha256") != manifest.get("catalog_sha256"):
            errors.append(f"{qid}: candidate pool catalog mismatch")
        if pool.get("provenance", {}).get("service") != "HybridRetrievalService":
            errors.append(f"{qid}: missing Phase 10 provenance")
        if manifest.get("dataset_version") != "phase13-pilot-v1" and (pool.get("capture_status") != "FROZEN" or not pool.get("capture_timestamp_utc") or not pool.get("provenance", {}).get("retrieval_config")):
            errors.append(f"{qid}: missing frozen capture status, timestamp, or retrieval configuration")
        candidates = pool.get("candidates", [])
        if pool.get("phase10_status") not in {"SUCCESS", "NO_RESULTS"}:
            errors.append(f"{qid}: invalid Phase 10 capture status")
        if pool.get("phase10_status") == "NO_RESULTS" and candidates:
            errors.append(f"{qid}: NO_RESULTS pool contains candidates")
        if pool.get("phase10_status") == "SUCCESS" and not candidates:
            errors.append(f"{qid}: SUCCESS pool has no candidates")
        if pool.get("no_result_verified") is True and (pool.get("phase10_status") != "NO_RESULTS" or pool.get("catalog_eligible_count") != 0 or candidates):
            errors.append(f"{qid}: invalid catalog-verified no-result claim")
        if pool.get("candidate_count") != len(candidates):
            errors.append(f"{qid}: candidate count mismatch")
        if len(candidates) > 20 or len(candidates) != len({p.get("product_id") for p in candidates}):
            errors.append(f"{qid}: invalid candidate count or duplicate products")
        for rank, candidate in enumerate(candidates, 1):
            if candidate.get("rank") != rank or not candidate.get("retrieval_text", "").strip():
                errors.append(f"{qid}: invalid rank or missing canonical evidence")
            if candidate.get("product_id") not in catalog_ids:
                errors.append(f"{qid}: unknown candidate product ID {candidate.get('product_id')}")
            elif catalog_records:
                canonical = catalog_records[candidate["product_id"]]
                for field in ("product_name", "category", "brand", "discounted_price", "rating", "retrieval_text"):
                    observed, expected = candidate.get(field), canonical[field]
                    same = (observed == expected) if field not in {"discounted_price", "rating"} else (
                        observed is None and expected is None or observed is not None and expected is not None
                        and isinstance(observed, (int, float)) and math.isfinite(observed)
                        and abs(float(observed) - expected) <= 1e-6)
                    if not same:
                        errors.append(f"{qid}/{candidate['product_id']}: candidate {field} differs from catalog snapshot")
                if not isinstance(candidate.get("sources"), dict) or not candidate["sources"]:
                    errors.append(f"{qid}: candidate branch provenance is missing")
                score = candidate.get("rrf_score")
                if not isinstance(score, (int, float)) or not math.isfinite(score):
                    errors.append(f"{qid}: invalid RRF score")
    seen_qrels = set()
    grade_counts = Counter()
    relevant_by_query = Counter()
    review_pairs: list[tuple[int, int]] = []
    relevant_reviewers = defaultdict(set)
    for review in relevance_reviews:
        relevant_reviewers[(review.get("query_id"), review.get("product_id"))].add(review.get("annotator_id"))
    for row in qrels:
        key = (row.get("query_id"), row.get("product_id"))
        if key in seen_qrels:
            errors.append(f"Duplicate qrel row: {key}")
        seen_qrels.add(key)
        if key[0] not in query_set or key[1] not in catalog_ids:
            errors.append(f"Invalid qrel query or product ID: {key}")
        if key[0] not in pool_by_qid or key[1] not in {c["product_id"] for c in pool_by_qid[key[0]].get("candidates", [])}:
            warnings.append(f"Qrel outside frozen Phase 10 pool: {key}; document supplemental pool provenance")
        for field in ("reviewer_a_grade", "reviewer_b_grade", "adjudicated_grade"):
            if row.get(field) and row[field] not in {"0", "1", "2", "3"}:
                errors.append(f"{key}: invalid {field}")
        a_grade, b_grade = row.get("reviewer_a_grade", ""), row.get("reviewer_b_grade", "")
        if a_grade in {"0", "1", "2", "3"} and b_grade in {"0", "1", "2", "3"}:
            review_pairs.append((int(a_grade), int(b_grade)))
        final = row.get("adjudicated_grade", "")
        if final in {"0", "1", "2", "3"}:
            grade_counts[final] += 1
            if int(final) >= 2:
                relevant_by_query[key[0]] += 1
            for field in ("reviewer_a_grade", "reviewer_b_grade"):
                if not row.get(field):
                    errors.append(f"{key}: adjudicated grade without two independent reviews")
            if not row.get("reviewer_a_id") or not row.get("reviewer_b_id") or row["reviewer_a_id"] == row["reviewer_b_id"]:
                errors.append(f"{key}: missing distinct reviewer identities")
            if len(relevant_reviewers[key]) < 2:
                errors.append(f"{key}: fewer than two independent relevance review rows")
            if any(row.get(field, "").lower() not in {"true", "false"} for field in ("category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation")):
                errors.append(f"{key}: final qrel has incomplete violation flags")
        for field in ("category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation"):
            if row.get(field) and row[field].lower() not in {"true", "false"}:
                errors.append(f"{key}: invalid {field}")
        if final in {"2", "3"} and any(row.get(field, "").lower() == "true" for field in ("category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation")):
            errors.append(f"{key}: high relevance conflicts with hard violation")
    relevance_decision_map = {(row.get("query_id"), row.get("product_id")): row for row in relevance_decisions}
    if len(relevance_decision_map) != len(relevance_decisions):
        errors.append("Duplicate relevance adjudication decisions")
    if set(relevance_decision_map) - seen_qrels:
        errors.append("Relevance adjudication contains pairs absent from qrels")
    for row in qrels:
        key = (row.get("query_id"), row.get("product_id"))
        decision = relevance_decision_map.get(key)
        if row.get("adjudicated_grade") and (not decision or not decision.get("adjudicator_id") or decision.get("adjudicated_grade") != row.get("adjudicated_grade")):
            errors.append(f"{key}: missing or inconsistent relevance adjudication decision")
        if row.get("adjudicated_grade") and decision and any(str(decision.get(flag, "")).lower() != str(row.get(flag, "")).lower() for flag in ("category_violation", "brand_violation", "price_violation", "rating_violation", "other_violation")):
            errors.append(f"{key}: final constraint flags differ from adjudication decision")
    for row in query_reviews + relevance_reviews:
        if row.get("query_id") not in query_set or not row.get("annotator_id"):
            errors.append("Annotation row has unknown query or missing annotator ID")
    query_review_keys = [(r.get("query_id"), r.get("annotator_id")) for r in query_reviews]
    relevance_review_keys = [(r.get("query_id"), r.get("product_id"), r.get("annotator_id")) for r in relevance_reviews]
    if len(query_review_keys) != len(set(query_review_keys)):
        errors.append("Duplicate query interpretation review rows")
    if len(relevance_review_keys) != len(set(relevance_review_keys)):
        errors.append("Duplicate relevance review rows")
    relevance_by_reviewer = {(r.get("query_id"), r.get("product_id"), r.get("annotator_id")): r for r in relevance_reviews}
    for row in qrels:
        if row.get("adjudicated_grade"):
            for label in ("a", "b"):
                review = relevance_by_reviewer.get((row.get("query_id"), row.get("product_id"), row.get(f"reviewer_{label}_id")))
                if not review or review.get("relevance_grade") != row.get(f"reviewer_{label}_grade"):
                    errors.append(f"{row.get('query_id')}/{row.get('product_id')}: qrel reviewer grade differs from submitted review")
    for row in query_reviews:
        if not row.get("semantic_query") or row.get("expected_status") not in VALID_STATUSES:
            errors.append(f"{row.get('query_id')}: incomplete query interpretation review")
        try:
            preferences = json.loads(row.get("soft_preferences_json") or "null")
            if not isinstance(preferences, list):
                errors.append(f"{row.get('query_id')}: preferences review is not a JSON list")
        except json.JSONDecodeError:
            errors.append(f"{row.get('query_id')}: invalid preferences JSON")
    for row in relevance_reviews:
        if row.get("relevance_grade") not in {"0", "1", "2", "3"}:
            errors.append(f"{row.get('query_id')}/{row.get('product_id')}: invalid reviewer relevance grade")
    query_reviewers = defaultdict(set)
    for row in query_reviews:
        query_reviewers[row.get("query_id")].add(row.get("annotator_id"))
    for q in queries:
        if q.get("annotation_status") == "ADJUDICATED" and len(query_reviewers[q.get("query_id")]) < 2:
            errors.append(f"{q.get('query_id')}: fewer than two independent query interpretation reviews")
        if q.get("annotation_status") == "ADJUDICATED" and query_decision_map.get(q.get("query_id")):
            decision = query_decision_map[q["query_id"]]
            understanding = q.get("expected_query_understanding") or {}
            if decision.get("semantic_query") != understanding.get("semantic_query"):
                errors.append(f"{q['query_id']}: final semantic query differs from adjudication decision")
    for row in claims:
        if row.get("query_id") not in query_set or row.get("product_id") not in catalog_ids:
            errors.append(f"Invalid claim query/product: {row.get('claim_id')}")
        elif row["product_id"] not in {p["product_id"] for p in pool_by_qid.get(row["query_id"], {}).get("candidates", [])}:
            errors.append(f"Claim product absent from frozen candidate pool: {row.get('claim_id')}")
        if not row.get("claim") or not row.get("generation_snapshot"):
            errors.append(f"Claim missing text or generation snapshot: {row.get('claim_id')}")
        for field in ("reviewer_a_support", "reviewer_b_support", "adjudicated_support"):
            if row.get(field) and row[field] not in VALID_SUPPORT:
                errors.append(f"Invalid claim support label: {row.get('claim_id')}")
        if row.get("adjudicated_support") and (not row.get("reviewer_a_id") or not row.get("reviewer_b_id") or row["reviewer_a_id"] == row["reviewer_b_id"] or not row.get("reviewer_a_support") or not row.get("reviewer_b_support")):
            errors.append(f"Claim lacks independent support reviews: {row.get('claim_id')}")
        if (row.get("adjudicated_factual") and (not row.get("reviewer_a_factual") or not row.get("reviewer_b_factual"))) or (row.get("adjudicated_relevance") and (not row.get("reviewer_a_relevance") or not row.get("reviewer_b_relevance"))):
            errors.append(f"Claim lacks independent quality reviews: {row.get('claim_id')}")
        for field, allowed in (("reviewer_a_factual", VALID_FACTUAL), ("reviewer_b_factual", VALID_FACTUAL), ("adjudicated_factual", VALID_FACTUAL), ("reviewer_a_relevance", VALID_RELEVANCE), ("reviewer_b_relevance", VALID_RELEVANCE), ("adjudicated_relevance", VALID_RELEVANCE), ("missing_information_handling", VALID_MISSING)):
            if row.get(field) and row[field] not in allowed:
                errors.append(f"Invalid {field}: {row.get('claim_id')}")
        try:
            evidence_ids = json.loads(row.get("evidence_ids_json") or "[]")
            evidence_text = json.loads(row.get("evidence_text_json") or "{}")
            if not isinstance(evidence_ids, list) or not isinstance(evidence_text, dict) or any(eid not in evidence_text for eid in evidence_ids):
                errors.append(f"Claim evidence mismatch: {row.get('claim_id')}")
        except json.JSONDecodeError:
            errors.append(f"Invalid claim evidence JSON: {row.get('claim_id')}")
        if manifest.get("dataset_version") != "phase13-pilot-v1" and any(not row.get(field) for field in ("provider", "model_version", "prompt_configuration", "product_metadata_json", "source_result_sha256")):
            errors.append(f"Claim missing frozen generation provenance: {row.get('claim_id')}")
    claim_decision_map = {row.get("claim_id"): row for row in claim_decisions}
    if len(claim_decision_map) != len(claim_decisions):
        errors.append("Duplicate claim adjudication decisions")
    claim_review_map = {(row.get("claim_id"), row.get("annotator_id")): row for row in claim_reviews}
    if len(claim_review_map) != len(claim_reviews):
        errors.append("Duplicate claim review rows")
    claim_ids = {row.get("claim_id") for row in claims}
    if set(claim_decision_map) - claim_ids or any(claim_id not in claim_ids or not reviewer for claim_id, reviewer in claim_review_map):
        errors.append("Claim review or adjudication references an unknown claim or missing reviewer")
    for row in claims:
        if row.get("adjudicated_support"):
            decision = claim_decision_map.get(row.get("claim_id"))
            if not decision or not decision.get("adjudicator_id") or decision.get("adjudicated_support") != row.get("adjudicated_support"):
                errors.append(f"{row.get('claim_id')}: missing or inconsistent claim adjudication decision")
            elif any(decision.get(source) != row.get(target) for source, target in (("adjudicated_factual", "adjudicated_factual"), ("adjudicated_relevance", "adjudicated_relevance"), ("missing_information_handling", "missing_information_handling"))):
                errors.append(f"{row.get('claim_id')}: claim quality labels differ from adjudication decision")
            for label in ("a", "b"):
                review = claim_review_map.get((row.get("claim_id"), row.get(f"reviewer_{label}_id")))
                if not review or review.get("support_label") != row.get(f"reviewer_{label}_support") or review.get("factual_correctness") != row.get(f"reviewer_{label}_factual") or review.get("recommendation_relevance") != row.get(f"reviewer_{label}_relevance"):
                    errors.append(f"{row.get('claim_id')}: final claim labels differ from submitted reviewer row")
    dev, test = set(splits.get("development", [])), set(splits.get("held_out", []))
    if splits.get("status") not in {"NOT_FROZEN", "FROZEN"}:
        errors.append("Dataset split status must be NOT_FROZEN or FROZEN")
    if splits.get("status") == "NOT_FROZEN" and (dev or test):
        errors.append("Unfrozen dataset must not assign development or held-out IDs")
    if dev & test or not (dev | test) <= query_set:
        errors.append("Invalid development/held-out split assignments")
    if splits.get("status") == "FROZEN":
        if not splits.get("split_version") or not isinstance(splits.get("random_seed"), int) or not splits.get("split_timestamp_utc"):
            errors.append("Frozen split lacks version, seed or timestamp")
        if splits.get("intent_groups") != {q["query_id"]: q.get("intent_group") for q in queries}:
            errors.append("Frozen split intent-group mapping differs from queries")
        if dev | test != query_set or not dev or not test:
            errors.append("Frozen split must cover every query with both partitions nonempty")
        if not all(q.get("annotation_status") == "ADJUDICATED" for q in queries):
            errors.append("Frozen split contains unadjudicated queries")
        for q in queries:
            qid = q.get("query_id")
            if q.get("expected_status") in {"SUCCESS", "NO_RESULTS"} and qid not in pool_by_qid:
                errors.append(f"{qid}: frozen split has no candidate pool")
            if qid in pool_by_qid:
                pool_ids = {c["product_id"] for c in pool_by_qid[qid].get("candidates", [])}
                judged_ids = {pid for query_id, pid in seen_qrels if query_id == qid}
                if pool_ids - judged_ids:
                    errors.append(f"{qid}: frozen pool has unjudged products")
        if any(not row.get("adjudicated_grade") for row in qrels):
            errors.append("Frozen split contains unadjudicated qrels")
        if any(not row.get("adjudicated_support") for row in claims):
            errors.append("Frozen split contains unadjudicated generation claims")
        if any(not row.get("adjudicated_factual") or not row.get("adjudicated_relevance") or not row.get("missing_information_handling") for row in claims):
            errors.append("Frozen split contains incomplete generation-quality judgments")
        if not claims:
            errors.append("Frozen full-pipeline benchmark has no generated claim cases")
    groups = defaultdict(set)
    for q in queries:
        if q.get("query_id") in dev:
            groups[q.get("intent_group")].add("dev")
        if q.get("query_id") in test:
            groups[q.get("intent_group")].add("test")
    if any(len(parts) > 1 for parts in groups.values()):
        errors.append("Paraphrase intent group crosses development/held-out split")
    leakage = [p for p in duplicates if (p["left"] in dev and p["right"] in test) or (p["right"] in dev and p["left"] in test)]
    if leakage:
        errors.append(f"Near-duplicate queries cross split: {leakage}")
    def reviewed(q: dict) -> dict | None:
        value = q.get("expected_query_understanding")
        return value if isinstance(value, dict) and isinstance(value.get("hard_constraints"), dict) else None

    interpretation_rows = [reviewed(q) for q in queries if reviewed(q) is not None]
    preference_counts = [len(item.get("soft_preferences", [])) for item in interpretation_rows]
    claim_support_pairs = [(c.get("reviewer_a_support"), c.get("reviewer_b_support")) for c in claims
                           if c.get("reviewer_a_support") and c.get("reviewer_b_support")]
    category_coverage = {}
    for category in sorted(category_names):
        members = [q for q in queries if q.get("planning_category") == category]
        member_ids = {q.get("query_id") for q in members}
        category_coverage[category] = {
            "queries": len(members),
            "query_types": sorted({str(q.get("query_type")) for q in members}),
            "candidate_pools": sum(qid in pool_by_qid for qid in member_ids),
            "relevant_judged_products": sum(count for qid, count in relevant_by_query.items() if qid in member_ids),
            "reviewed_hard_constraint_queries": sum(bool(reviewed(q) and any(reviewed(q)["hard_constraints"].get(f) is not None for f in ("category", "brand", "min_price", "max_price", "min_rating"))) for q in members),
            "reviewed_soft_preference_queries": sum(bool(reviewed(q) and reviewed(q).get("soft_preferences")) for q in members),
        }
    stats = {
        "queries": len(queries), "by_type": dict(Counter(str(q.get("query_type")) for q in queries)),
        "by_category": dict(Counter(str(q.get("planning_category")) for q in queries)),
        "category_coverage": category_coverage,
        "by_language": dict(Counter(str(q.get("language")) for q in queries)),
        "by_status": dict(Counter(q.get("expected_status") or "UNREVIEWED" for q in queries)),
        "annotation_completion": {
            "fully_annotated_queries": sum(q.get("annotation_status") == "ADJUDICATED" for q in queries),
            "partially_annotated_queries": sum(q.get("annotation_status") not in {"ADJUDICATED", "UNREVIEWED_DRAFT"} for q in queries),
            "unannotated_queries": sum(q.get("annotation_status") == "UNREVIEWED_DRAFT" for q in queries),
        },
        "query_interpretations": sum(q.get("expected_query_understanding") is not None for q in queries),
        "hard_constraint_queries": sum(bool(reviewed(q) and any(reviewed(q)["hard_constraints"].get(f) is not None for f in ("category", "brand", "min_price", "max_price", "min_rating"))) for q in queries),
        "soft_preference_queries": sum(bool(reviewed(q) and reviewed(q).get("soft_preferences")) for q in queries),
        "average_preferences_per_reviewed_query": round(sum(preference_counts) / len(preference_counts), 3) if preference_counts else None,
        "candidate_pools": len(pools), "candidate_pool_sizes": {p["query_id"]: len(p.get("candidates", [])) for p in pools},
        "average_candidate_pool_size": round(sum(len(p.get("candidates", [])) for p in pools) / len(pools), 3) if pools else None,
        "qrels": len(qrels), "adjudicated_qrels": sum(bool(r.get("adjudicated_grade")) for r in qrels),
        "relevance_distribution": dict(grade_counts), "relevant_products_per_query": dict(relevant_by_query),
        "generation_claims": len(claims), "adjudicated_claim_support": sum(bool(c.get("adjudicated_support")) for c in claims),
        "double_annotated_claims": len(claim_support_pairs),
        "claim_support_disagreements": sum(left != right for left, right in claim_support_pairs),
        "claim_support_exact_agreement": round(sum(left == right for left, right in claim_support_pairs) / len(claim_support_pairs), 6) if claim_support_pairs else None,
        "query_review_rows": len(query_reviews), "relevance_review_rows": len(relevance_reviews),
        "claim_review_rows": len(claim_reviews),
        "query_adjudication_decisions": len(query_decisions), "relevance_adjudication_decisions": len(relevance_decisions),
        "claim_adjudication_decisions": len(claim_decisions),
        "reviewer_count": len({r.get("annotator_id") for r in query_reviews + relevance_reviews + claim_reviews if r.get("annotator_id")}),
        "double_annotated_qrels": len(review_pairs),
        "relevance_disagreements": sum(a != b for a, b in review_pairs),
        "exact_grade_agreement": round(sum(a == b for a, b in review_pairs) / len(review_pairs), 6) if review_pairs else None,
        "quadratic_weighted_kappa": weighted_kappa(review_pairs),
        "split_counts": {"development": len(dev), "held_out": len(test)},
        "near_duplicate_pairs": duplicates,
    }
    if manifest.get("query_count") != len(queries) or manifest.get("qrel_count") != len(qrels):
        errors.append("Manifest query/qrel counts differ from files")
    if manifest.get("split_counts") != {"development": len(dev), "held_out": len(test)}:
        errors.append("Manifest split counts differ from split assignments")
    if manifest.get("reviewer_count") != stats["reviewer_count"]:
        errors.append("Manifest reviewer count differs from submitted annotations")
    if manifest.get("category_distribution") != dict(Counter(q.get("planning_category") for q in queries)):
        errors.append("Manifest category distribution differs from queries")
    if manifest.get("language_distribution") != dict(Counter(q.get("language") for q in queries)):
        errors.append("Manifest language distribution differs from queries")
    if manifest.get("query_type_distribution") != dict(Counter(q.get("query_type") for q in queries)):
        errors.append("Manifest query type distribution differs from queries")
    artifact_hashes = manifest.get("artifact_sha256", {})
    core_artifacts = {"queries.jsonl", "candidate_pools.jsonl", "qrels.csv", "query_annotations.csv", "relevance_annotations.csv", "generation_claims.csv"}
    review_artifacts = {"query_adjudications.jsonl", "relevance_adjudications.csv", "claim_annotations.csv", "claim_adjudications.csv"}
    for name, expected_hash in artifact_hashes.items():
        if name not in core_artifacts | review_artifacts or not (dataset / name).is_file() or hashlib.sha256((dataset / name).read_bytes()).hexdigest() != expected_hash:
            errors.append(f"Dataset artifact hash mismatch: {name}")
    if manifest.get("dataset_version") != "phase13-pilot-v1" and (not core_artifacts <= set(artifact_hashes) or any((dataset / name).is_file() and name not in artifact_hashes for name in review_artifacts)):
        errors.append("Dataset artifact hashes are incomplete")
    source_relpath = manifest.get("source_dataset_relpath")
    if source_relpath:
        source_dir = (ROOT / source_relpath).resolve()
        if not source_dir.is_relative_to(ROOT) or not source_dir.is_dir():
            errors.append("Source dataset lineage path is invalid")
        else:
            source_hashes = manifest.get("source_file_sha256") or ({"queries.jsonl": manifest["source_query_sha256"]} if manifest.get("source_query_sha256") else {})
            for name, expected_hash in source_hashes.items():
                if not (source_dir / name).is_file() or hashlib.sha256((source_dir / name).read_bytes()).hexdigest() != expected_hash:
                    errors.append(f"Source dataset lineage hash mismatch: {name}")
    audit_hash = manifest.get("catalog_draft_audit_sha256")
    if audit_hash and (not (dataset / "catalog_draft_audit.json").is_file() or hashlib.sha256((dataset / "catalog_draft_audit.json").read_bytes()).hexdigest() != audit_hash):
        errors.append("Catalog draft audit hash mismatch")
    if splits.get("status") == "FROZEN":
        required_hashes = set(artifact_hashes) | {"dataset_manifest.json"}
        if set(splits.get("dataset_hashes", {})) != required_hashes:
            errors.append("Frozen split dataset hashes are incomplete")
        for name, expected_hash in splits.get("dataset_hashes", {}).items():
            if name not in required_hashes or hashlib.sha256((dataset / name).read_bytes()).hexdigest() != expected_hash:
                errors.append(f"Frozen split hash mismatch: {name}")
    eligible = {q["query_id"] for q in queries if q.get("expected_status") in {"SUCCESS", "NO_RESULTS"}}
    no_result_queries = [q for q in queries if q.get("expected_status") == "NO_RESULTS"]
    required_pairs = {(p["query_id"], c["product_id"]) for p in pools for c in p.get("candidates", [])}
    reviewed_pairs = {(r["query_id"], r["product_id"]) for r in qrels if r.get("adjudicated_grade") in {"0", "1", "2", "3"}}
    claim_interactions = {(c["query_id"], c["generation_snapshot"]) for c in claims if c.get("generation_snapshot")}
    gates = {
        "query_count": len(queries) >= 200,
        "category_coverage": {q.get("planning_category") for q in queries} == category_names,
        "query_type_coverage": {q.get("query_type") for q in queries} == VALID_TYPES,
        "interpretations_adjudicated": bool(queries) and all(q.get("annotation_status") == "ADJUDICATED" and q.get("expected_query_understanding") and q.get("expected_status") in VALID_STATUSES and len(query_reviewers[q["query_id"]]) == 2 for q in queries),
        "candidate_pools_frozen": bool(eligible) and eligible <= set(pool_by_qid) and manifest.get("candidate_capture_status") == "FROZEN" and all(p.get("capture_status") == "FROZEN" for p in pools),
        "no_results_verified": bool(no_result_queries) and all(pool_by_qid.get(q["query_id"], {}).get("no_result_verified") is True and pool_by_qid[q["query_id"]].get("catalog_eligible_count") == 0 and pool_by_qid[q["query_id"]].get("phase10_status") == "NO_RESULTS" for q in no_result_queries),
        "relevance_complete": bool(required_pairs) and required_pairs == reviewed_pairs and all(len(relevant_reviewers[key]) == 2 for key in required_pairs),
        "claims_adjudicated": bool(claims) and all(c.get("adjudicated_support") in VALID_SUPPORT and c.get("adjudicated_factual") in VALID_FACTUAL and c.get("adjudicated_relevance") in VALID_RELEVANCE and c.get("missing_information_handling") in VALID_MISSING for c in claims),
        "adjudication_trail": len(query_decisions) == len(queries) and len(relevance_decisions) == len(qrels) and len(claim_decisions) == len(claims),
        "generation_case_coverage": len(claim_interactions) >= 50,
        "claim_challenge_coverage": any(c.get("adjudicated_support") == "UNSUPPORTED" for c in claims) and any(c.get("adjudicated_support") == "NOT_ENOUGH_INFORMATION" or c.get("missing_information_handling") in {"CORRECTLY_DISTINGUISHED", "MISSTATED_ABSENCE"} for c in claims),
        "split_frozen": splits.get("status") == "FROZEN" and bool(dev) and bool(test),
        "dataset_hashes": bool(artifact_hashes) and not any("hash" in e.lower() for e in errors),
        "regression_tests": manifest.get("regression_test_status") == "PASS" and bool(manifest.get("regression_test_evidence")),
        "critical_blockers_resolved": manifest.get("critical_blockers_resolved") is True,
    }
    ready = not errors and all(gates.values())
    return {"status": "FAIL" if errors else "PASS", "phase14_ready": ready, "readiness_gates": gates, "errors": errors, "warnings": warnings, "statistics": stats}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = validate(args.dataset)
    report_path = args.report or args.dataset / "validation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Phase 13 structural validation: {report['status']}; Phase 14 ready: {report.get('phase14_ready', False)}")
    for message in report["errors"]:
        print(f"ERROR: {message}")
    for message in report["warnings"]:
        print(f"WARNING: {message}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
