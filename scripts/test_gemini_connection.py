"""Verify Gemini API connection, model availability, and structured output capability (Phase 8).

Usage:
    python scripts/test_gemini_connection.py
    python scripts/test_gemini_connection.py --query "wireless gaming mouse under 1500 rs"
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

from shopassist.core.config import mask_database_url
from shopassist.llm.config import get_llm_settings
from shopassist.llm.gemini_client import GeminiClient
from shopassist.llm.prompts import SYSTEM_INSTRUCTION, build_user_prompt
from shopassist.llm.schemas import QueryUnderstandingOutput

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("test_gemini_connection")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Verify Gemini API connectivity, model discovery, and structured output."
    )
    parser.add_argument(
        "--query",
        type=str,
        default="Puma running shoes under 2000 rupees",
        help="Sample test query for smoke test (default: 'Puma running shoes under 2000 rupees').",
    )
    return parser.parse_args()


async def run_connection_test(query: str) -> bool:
    """Run connection smoke test against Gemini API."""
    print("=" * 70)
    print("SHOPASSIST PHASE 8: GEMINI API CONNECTION & SMOKE TEST")
    print("=" * 70)

    # 1. Configuration check
    try:
        settings = get_llm_settings()
        print("\n[Step 1] LLM Configuration:")
        print(f"  Provider:           {settings.provider}")
        print(f"  Configured Model:   {settings.model}")
        print(f"  API Key:            {settings.masked_api_key}")
        print(f"  Temperature:        {settings.temperature}")
        print(f"  Max Output Tokens:  {settings.max_output_tokens}")
        print(f"  Timeout (seconds):  {settings.timeout_seconds}")
        print(f"  Max Retries:        {settings.max_retries}")
    except Exception as e:
        print(f"\n[ERROR] Failed to load LLM settings: {e}", file=sys.stderr)
        return False

    client = GeminiClient(settings)

    try:
        # 2. Model Discovery & Verification
        print("\n[Step 2] Verifying Model Availability via google-genai SDK...")
        models = await client.list_available_models()
        matching = [m for m in models if settings.model in m]
        print(f"  Total models discovered: {len(models)}")
        if matching:
            print(f"  Found matching configured model: {matching[0]} [VERIFIED]")
        else:
            print(f"  Warning: Configured model '{settings.model}' not in direct name match list.")
            print(f"  Available sample models: {models[:5]}")

        # 3. Live Structured Output Smoke Test
        print(f"\n[Step 3] Running Structured Output Smoke Test...")
        print(f"  Input Query: '{query}'")

        user_prompt = build_user_prompt(query)
        (
            parsed_output,
            raw_json,
            latency_ms,
            token_usage,
        ) = await client.generate_structured_async(
            prompt=user_prompt,
            response_schema=QueryUnderstandingOutput,
            system_instruction=SYSTEM_INSTRUCTION,
        )

        print("\n[Step 4] Live Response Received Successfully:")
        print(f"  Model Used:       {settings.model}")
        print(f"  Latency:          {latency_ms:.2f} ms")
        if token_usage:
            print(f"  Input Tokens:     {token_usage.prompt_tokens}")
            print(f"  Output Tokens:    {token_usage.candidates_tokens}")
            print(f"  Total Tokens:     {token_usage.total_tokens}")

        print("\n[Step 5] Extracted Structured JSON:")
        print(json.dumps(parsed_output.model_dump(), indent=2))

        print("\n" + "=" * 70)
        print("RESULT: PASS — Gemini API connection and structured output verified.")
        print("=" * 70)
        return True

    except Exception as e:
        print(f"\n[ERROR] Gemini API connection test failed: {e}", file=sys.stderr)
        return False
    finally:
        await client.close()


def main() -> int:
    args = parse_args()
    success = asyncio.run(run_connection_test(args.query))
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
