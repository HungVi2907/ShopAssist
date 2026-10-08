"""Phase 6 executable CLI script: Search Product Knowledge Base using TF-IDF Baseline.

Usage:
    python scripts/search_tfidf.py --query "wireless bluetooth keyboard"
    python scripts/search_tfidf.py --query "running shoes" --top-k 10
    python scripts/search_tfidf.py  # Interactive search mode
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
import time

# Ensure src/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from shopassist.retrieval.tfidf import DEFAULT_TFIDF_ARTIFACT_DIR, TFIDFIndex

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Search ShopAssist catalog using Phase 6 TF-IDF lexical baseline retrieval."
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Search query text. If omitted, enters interactive mode.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of top candidates to retrieve (default: 5)",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=DEFAULT_TFIDF_ARTIFACT_DIR,
        help=f"Directory containing saved TF-IDF artifacts (default: {DEFAULT_TFIDF_ARTIFACT_DIR})",
    )
    return parser.parse_args()


def display_results(query: str, results: list, latency_ms: float) -> None:
    """Pretty print search results table."""
    print("\n" + "=" * 80)
    print(f"SEARCH QUERY: \"{query}\"")
    print(f"Retrieval Latency: {latency_ms:.3f} ms | Returned: {len(results)} items")
    print("=" * 80)

    if not results:
        print("  [NO RESULTS FOUND]")
        print("  The query was either empty or contained exclusively out-of-vocabulary terms.")
        print("=" * 80 + "\n")
        return

    header = f"{'Rank':<5} | {'Score':<7} | {'Price':<10} | {'Category':<22} | {'Product Name'}"
    print(header)
    print("-" * 80)

    for r in results:
        brand_str = f" [{r.brand}]" if r.brand else ""
        price_str = f"${r.discounted_price:,.2f}"
        name_str = f"{r.product_name[:35]}{brand_str}"
        print(f"#{r.rank:<4} | {r.tfidf_score:<7.4f} | {price_str:<10} | {r.category[:22]:<22} | {name_str}")

    print("=" * 80 + "\n")


def main() -> int:
    """CLI execution entrypoint."""
    args = parse_args()

    if not args.artifacts.exists():
        print(
            f"Error: Artifact directory '{args.artifacts}' does not exist.\n"
            f"Please run 'python scripts/build_tfidf_baseline.py' first.",
            file=sys.stderr,
        )
        return 1

    try:
        index = TFIDFIndex.load(args.artifacts)
    except Exception as exc:
        print(f"Error loading TF-IDF index: {exc}", file=sys.stderr)
        return 1

    if args.query:
        t0 = time.perf_counter()
        results = index.search(args.query, top_k=args.top_k)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        display_results(args.query, results, latency_ms)
        return 0

    # Interactive mode
    print("\n" + "=" * 80)
    print("ShopAssist TF-IDF Lexical Retrieval — Interactive Search Console")
    print("Type your search query and press Enter. Type 'exit' or 'quit' to stop.")
    print("=" * 80)

    while True:
        try:
            q = input("\nEnter query > ").strip()
            if q.lower() in ("exit", "quit", "q"):
                print("Exiting search console.")
                break
            if not q:
                continue

            t0 = time.perf_counter()
            results = index.search(q, top_k=args.top_k)
            latency_ms = (time.perf_counter() - t0) * 1000.0
            display_results(q, results, latency_ms)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting search console.")
            break

    return 0


if __name__ == "__main__":
    sys.exit(main())
