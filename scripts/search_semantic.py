"""Semantic Search CLI for ShopAssist (Phase 7).

Executes dense semantic product retrieval using BAAI/bge-small-en-v1.5 embeddings
and Supabase PostgreSQL + pgvector HNSW index search.

Examples:
    python scripts/search_semantic.py --query "wireless bluetooth keyboard" --top-k 5
    python scripts/search_semantic.py --query "sneakers for jogging" --top-k 10 --json
    python scripts/search_semantic.py --query "running shoes" --exact
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import sys

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.core.config import mask_database_url, settings
from shopassist.db.connection import ensure_windows_event_loop_policy, get_async_engine

from shopassist.retrieval.semantic import (
    SemanticSearchConfig,
    SemanticSearchEngine,
)

ensure_windows_event_loop_policy()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("search_semantic")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Search products using dense semantic retrieval (BAAI/bge-small-en-v1.5 + pgvector)."
    )
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        required=True,
        help="Natural language search query.",
    )
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=5,
        help="Number of product candidates to return (default: 5).",
    )
    parser.add_argument(
        "--no-instruction",
        action="store_true",
        help="Disable the default BGE retrieval instruction prefix.",
    )
    parser.add_argument(
        "--exact",
        action="store_true",
        help="Perform exact linear scan (disables HNSW index scan) for ground-truth comparison.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON.",
    )
    return parser.parse_args()


async def main_async() -> int:
    """Main async entry point."""
    args = parse_args()

    # Verify database URL availability
    db_url = settings.get_raw_supabase_db_url()
    if not db_url:
        logger.error("Supabase database connection URL is not configured.")
        return 1

    instruction = None if args.no_instruction else "Represent this sentence for searching relevant passages: "

    engine = SemanticSearchEngine()
    try:
        if args.exact:
            results = await engine.search_exact(
                query=args.query,
                top_k=args.top_k,
                instruction=instruction,
            )
        else:
            results = await engine.search(
                query=args.query,
                top_k=args.top_k,
                instruction=instruction,
            )

        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))
            return 0

        scan_type = "EXACT LINEAR SCAN" if args.exact else "HNSW ANN INDEX SCAN"
        print("\n" + "=" * 90)
        print(f"DENSE SEMANTIC SEARCH RESULTS ({scan_type})")
        print("=" * 90)
        print(f"Query:        '{args.query}'")
        print(f"Model:        {engine.config.model_name} (384-d, L2 normalized)")
        print(f"Instruction:  {repr(instruction)}")
        print(f"Top-K:        {args.top_k}")
        print(f"Retrieved:    {len(results)} items")
        print("-" * 90)

        if not results:
            print("No matching products found.")
            print("=" * 90 + "\n")
            return 0

        for r in results:
            brand_str = f"Brand: {r.brand}" if r.brand else "Brand: N/A"
            price_str = f"Rs. {r.discounted_price:,.0f}" if r.discounted_price else "Price: N/A"
            print(f"#{r.rank:02d} | Score: {r.semantic_score:.4f} (Dist: {r.cosine_distance:.4f}) | {r.product_id}")
            print(f"     Title:    {r.product_name}")
            print(f"     Category: {r.category} | {brand_str} | {price_str}")
            print("-" * 90)

        print("=" * 90 + "\n")
        return 0

    finally:
        await engine.close()


def main() -> None:
    """CLI execution entrypoint."""
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
