"""Category tree parsing utilities for Flipkart dataset.

The raw product_category_tree in the Flipkart dataset contains serialized
hierarchical breadcrumb paths, typically formatted as:
    ["Clothing >> Women's Clothing >> Lingerie, Sleep & Swimwear >> Shorts >> ..."]
"""

import ast
import json
import re
from typing import List, Optional


def parse_category_tree(tree_raw: Optional[str]) -> List[str]:
    """Parse raw product_category_tree string into a list of hierarchical category levels.

    Args:
        tree_raw: Raw string from product_category_tree column.

    Returns:
        List of category strings from Level 1 (top-level) to leaf level.
        Returns empty list if invalid, missing, or unparseable.
    """
    if not isinstance(tree_raw, str):
        return []

    text = tree_raw.strip()
    if not text or text in {"[]", '[""]', "['']"}:
        return []

    inner_str = ""

    # Strategy 1: Attempt JSON array parsing
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], str):
                inner_str = parsed[0]
        except Exception:
            pass

    # Strategy 2: Attempt ast.literal_eval
    if not inner_str and text.startswith("[") and text.endswith("]"):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], str):
                inner_str = parsed[0]
        except Exception:
            pass

    # Strategy 3: Regex strip brackets and surrounding quotes
    if not inner_str:
        s = text
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1].strip()
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
        inner_str = s

    if not inner_str:
        return []

    # Split on >> and clean whitespace
    levels = [part.strip() for part in inner_str.split(">>") if part.strip()]
    return levels


def get_category_depth(tree_raw: Optional[str]) -> int:
    """Return the depth of the category hierarchy."""
    return len(parse_category_tree(tree_raw))


def extract_category_level(tree_raw: Optional[str], level: int = 1) -> Optional[str]:
    """Extract a specific 1-indexed category level.

    Args:
        tree_raw: Raw category tree string.
        level: 1-indexed level (1 = Top level).

    Returns:
        Category name at the requested level, or None if not available.
    """
    levels = parse_category_tree(tree_raw)
    if 1 <= level <= len(levels):
        return levels[level - 1]
    return None
