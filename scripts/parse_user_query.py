"""Parse a natural-language shopping query into validated structured representations (Phase 8).

Extracts category, brand, price constraints, rating, soft preferences, semantic search query,
and clarification flags using Google Gemini API.

Examples:
    python scripts/parse_user_query.py --query "Puma running shoes under 2000 rupees"
    python scripts/parse_user_query.py --query "Samsung phone under 15000 with good battery life" --json
    python scripts/parse_user_query.py --interactive
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

from shopassist.llm.config import get_llm_settings
from shopassist.llm.query_understanding import QueryUnderstandingEngine
from shopassist.llm.schemas import QueryUnderstandingResult

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("parse_user_query")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Extract validated structured shopping constraints and preferences from user queries."
    )
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        default=None,
        help="Natural language user query to parse.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw structured result as JSON.",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Run in interactive prompt mode.",
    )
    return parser.parse_args()


def display_result(res: QueryUnderstandingResult, as_json: bool = False) -> None:
    """Print parsed query understanding result."""
    if as_json:
        print(json.dumps(res.to_serializable_dict(), indent=2))
        return

    out = res.output
    hc = out.hard_constraints

    print("\n" + "=" * 65)
    print(f"QUERY: \"{res.query}\"")
    print("=" * 65)
    print(f"Semantic Query:        {out.semantic_query}")
    print(f"Needs Clarification:   {out.needs_clarification}")
    if out.needs_clarification and out.clarification_reason:
        print(f"Clarification Reason:  {out.clarification_reason}")

    print("\nHARD CONSTRAINTS:")
    print(f"  Category:            {hc.category or '[None]'}")
    print(f"  Brand:               {hc.brand or '[None]'}")
    print(f"  Min Price:           {f'{hc.min_price} {hc.currency}' if hc.min_price is not None else '[None]'}")
    print(f"  Max Price:           {f'{hc.max_price} {hc.currency}' if hc.max_price is not None else '[None]'}")
    print(f"  Min Rating:          {f'{hc.min_rating} stars' if hc.min_rating is not None else '[None]'}")
    print(f"  Currency:            {hc.currency}")

    print("\nSOFT PREFERENCES:")
    if out.soft_preferences:
        for pref in out.soft_preferences:
            print(f"  - {pref}")
    else:
        print("  [None]")

    print("\nEXECUTION METRICS:")
    print(f"  Latency:             {res.latency_ms:.2f} ms")
    if res.token_usage:
        print(f"  Token Usage:         {res.token_usage.total_tokens} tokens ({res.token_usage.prompt_tokens} in / {res.token_usage.candidates_tokens} out)")
    print(f"  Valid Schema:        {res.is_valid}")
    if res.validation_errors:
        print(f"  Warnings/Errors:     {', '.join(res.validation_errors)}")
    print("=" * 65 + "\n")


async def run_single(engine: QueryUnderstandingEngine, query: str, as_json: bool) -> None:
    """Execute parsing for a single query."""
    res = await engine.parse_query_async(query)
    display_result(res, as_json)


async def run_interactive(engine: QueryUnderstandingEngine, as_json: bool) -> None:
    """Run interactive REPL loop."""
    print("ShopAssist Query Understanding CLI (Interactive Mode)")
    print("Type your shopping query or 'exit' / 'quit' to stop.\n")

    while True:
        try:
            query = input("ShopAssist> ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                print("Exiting.")
                break
            res = await engine.parse_query_async(query)
            display_result(res, as_json)
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break


async def main_async() -> int:
    args = parse_args()
    if not args.query and not args.interactive:
        print("Error: Either --query or --interactive must be provided.", file=sys.stderr)
        return 1

    settings = get_llm_settings()
    engine = QueryUnderstandingEngine(settings=settings)

    try:
        if args.interactive:
            await run_interactive(engine, args.json)
        else:
            await run_single(engine, args.query, args.json)
        return 0
    finally:
        await engine.aclose()


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
