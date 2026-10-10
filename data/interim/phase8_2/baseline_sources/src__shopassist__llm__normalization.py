"""Category, brand, currency, and business rule normalization for ShopAssist (Phase 8).

Ensures extracted attributes map cleanly to the 16 approved canonical catalog categories
and database schema constraints.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Sequence

from shopassist.llm.schemas import HardConstraints, QueryUnderstandingOutput

logger = logging.getLogger(__name__)

# The 16 canonical categories finalized in Phase 3 and Phase 5
CANONICAL_CATEGORIES: tuple[str, ...] = (
    "Automotive",
    "Baby Care",
    "Bags, Wallets & Belts",
    "Cameras & Accessories",
    "Computers",
    "Footwear",
    "Furniture",
    "Home Decor & Festive Needs",
    "Home Furnishing",
    "Home Improvement",
    "Kitchen & Dining",
    "Mobiles & Accessories",
    "Pens & Stationery",
    "Sports & Fitness",
    "Tools & Hardware",
    "Watches",
)

# Canonical set for O(1) membership checks
CANONICAL_CATEGORIES_SET: set[str] = set(CANONICAL_CATEGORIES)
CANONICAL_CATEGORIES_LOWER: dict[str, str] = {c.lower(): c for c in CANONICAL_CATEGORIES}

# Keyword to canonical category mapping for sub-category / product-type expressions
CATEGORY_SYNONYM_MAP: dict[str, str] = {
    # Footwear
    "shoes": "Footwear",
    "running shoes": "Footwear",
    "walking shoes": "Footwear",
    "sneakers": "Footwear",
    "boots": "Footwear",
    "sandals": "Footwear",
    "heels": "Footwear",
    "wedges": "Footwear",
    "loafers": "Footwear",
    "slippers": "Footwear",
    "flip flops": "Footwear",
    "flats": "Footwear",
    "casual shoes": "Footwear",
    "formal shoes": "Footwear",
    # Computers
    "laptop": "Computers",
    "notebook": "Computers",
    "desktop": "Computers",
    "pc": "Computers",
    "keyboard": "Computers",
    "mouse": "Computers",
    "monitor": "Computers",
    "printer": "Computers",
    "hard drive": "Computers",
    "ssd": "Computers",
    "pen drive": "Computers",
    "usb drive": "Computers",
    "usb light": "Computers",
    "router": "Computers",
    "processor": "Computers",
    "ram": "Computers",
    # Mobiles & Accessories
    "phone": "Mobiles & Accessories",
    "smartphone": "Mobiles & Accessories",
    "mobile": "Mobiles & Accessories",
    "cell phone": "Mobiles & Accessories",
    "iphone": "Mobiles & Accessories",
    "charger": "Mobiles & Accessories",
    "charging cable": "Mobiles & Accessories",
    "lightning cable": "Mobiles & Accessories",
    "screen protector": "Mobiles & Accessories",
    "phone case": "Mobiles & Accessories",
    "mobile cover": "Mobiles & Accessories",
    "earbuds": "Mobiles & Accessories",
    "earphones": "Mobiles & Accessories",
    "headset": "Mobiles & Accessories",
    "headphones": "Mobiles & Accessories",
    "power bank": "Mobiles & Accessories",
    # Watches
    "watch": "Watches",
    "smartwatch": "Watches",
    "wrist watch": "Watches",
    "chronograph": "Watches",
    "analog watch": "Watches",
    "digital watch": "Watches",
    # Automotive
    "car": "Automotive",
    "car mat": "Automotive",
    "car accessories": "Automotive",
    "bike": "Automotive",
    "helmet": "Automotive",
    "seat cover": "Automotive",
    "tyre": "Automotive",
    "car perfume": "Automotive",
    "audio receiver car kit": "Automotive",
    # Cameras & Accessories
    "camera": "Cameras & Accessories",
    "dslr": "Cameras & Accessories",
    "lens": "Cameras & Accessories",
    "tripod": "Cameras & Accessories",
    "camera bag": "Cameras & Accessories",
    "camcorder": "Cameras & Accessories",
    # Bags, Wallets & Belts
    "backpack": "Bags, Wallets & Belts",
    "bag": "Bags, Wallets & Belts",
    "wallet": "Bags, Wallets & Belts",
    "belt": "Bags, Wallets & Belts",
    "handbag": "Bags, Wallets & Belts",
    "luggage": "Bags, Wallets & Belts",
    "tote": "Bags, Wallets & Belts",
    "suitcase": "Bags, Wallets & Belts",
    # Furniture
    "sofa": "Furniture",
    "bed": "Furniture",
    "table": "Furniture",
    "chair": "Furniture",
    "dining table": "Furniture",
    "wardrobe": "Furniture",
    "bookshelf": "Furniture",
    "cabinet": "Furniture",
    # Home Furnishing
    "curtain": "Home Furnishing",
    "bedsheet": "Home Furnishing",
    "pillow": "Home Furnishing",
    "cushion": "Home Furnishing",
    "blanket": "Home Furnishing",
    "mattress": "Home Furnishing",
    "towel": "Home Furnishing",
    "carpet": "Home Furnishing",
    # Home Decor & Festive Needs
    "wall clock": "Home Decor & Festive Needs",
    "painting": "Home Decor & Festive Needs",
    "photo frame": "Home Decor & Festive Needs",
    "vase": "Home Decor & Festive Needs",
    "candle": "Home Decor & Festive Needs",
    "showpiece": "Home Decor & Festive Needs",
    "wall sticker": "Home Decor & Festive Needs",
    "diya": "Home Decor & Festive Needs",
    # Kitchen & Dining
    "cookware": "Kitchen & Dining",
    "pressure cooker": "Kitchen & Dining",
    "pan": "Kitchen & Dining",
    "pot": "Kitchen & Dining",
    "plate": "Kitchen & Dining",
    "bottle": "Kitchen & Dining",
    "flask": "Kitchen & Dining",
    "lunch box": "Kitchen & Dining",
    "knife": "Kitchen & Dining",
    "gas stove": "Kitchen & Dining",
    # Sports & Fitness
    "dumbbell": "Sports & Fitness",
    "treadmill": "Sports & Fitness",
    "yoga mat": "Sports & Fitness",
    "cricket bat": "Sports & Fitness",
    "badminton": "Sports & Fitness",
    "football": "Sports & Fitness",
    "fitness band": "Sports & Fitness",
    "skating": "Sports & Fitness",
    # Baby Care
    "diaper": "Baby Care",
    "baby wipes": "Baby Care",
    "baby stroller": "Baby Care",
    "baby toy": "Baby Care",
    "baby clothes": "Baby Care",
    # Tools & Hardware
    "drill": "Tools & Hardware",
    "screwdriver": "Tools & Hardware",
    "wrench": "Tools & Hardware",
    "hammer": "Tools & Hardware",
    "plier": "Tools & Hardware",
    "ladder": "Tools & Hardware",
    "toolbox": "Tools & Hardware",
    # Pens & Stationery
    "pen": "Pens & Stationery",
    "notebook": "Pens & Stationery",
    "diary": "Pens & Stationery",
    "pencil": "Pens & Stationery",
    "marker": "Pens & Stationery",
    "stapler": "Pens & Stationery",
    "calculator": "Pens & Stationery",
    # Home Improvement
    "door lock": "Home Improvement",
    "tap": "Home Improvement",
    "shower": "Home Improvement",
    "light bulb": "Home Improvement",
    "extension cord": "Home Improvement",
}


def is_canonical_category(cat: str | None) -> bool:
    """Check if category is one of the 16 approved canonical categories."""
    if not cat:
        return False
    return cat.strip() in CANONICAL_CATEGORIES_SET


def normalize_category(raw_cat: str | None) -> str | None:
    """Normalize raw or extracted category string to one of the 16 canonical categories.

    1. Checks exact match against canonical categories.
    2. Checks case-insensitive match against canonical categories.
    3. Checks sub-category/keyword synonym dictionary.
    4. Returns canonical name or None if unmapped.

    Args:
        raw_cat: Category string from LLM output or None.

    Returns:
        Canonical category name, or None.
    """
    if not raw_cat or not str(raw_cat).strip():
        return None

    clean = str(raw_cat).strip()

    # 1. Exact match
    if clean in CANONICAL_CATEGORIES_SET:
        return clean

    # 2. Case-insensitive match
    lower = clean.lower()
    if lower in CANONICAL_CATEGORIES_LOWER:
        return CANONICAL_CATEGORIES_LOWER[lower]

    # 3. Direct lookup in synonym map
    if lower in CATEGORY_SYNONYM_MAP:
        return CATEGORY_SYNONYM_MAP[lower]

    # 4. Substring / multi-word scan in synonym map
    for kw, canon in CATEGORY_SYNONYM_MAP.items():
        if kw in lower:
            return canon

    # 5. Check if any canonical category name is contained within string
    for canon in CANONICAL_CATEGORIES:
        if canon.lower() in lower:
            return canon

    return None


def normalize_brand(raw_brand: str | None, catalog_brands: set[str] | None = None) -> str | None:
    """Normalize extracted brand string.

    Args:
        raw_brand: Raw brand string.
        catalog_brands: Optional set of known catalog brand names.

    Returns:
        Cleaned brand string or None.
    """
    if not raw_brand or not str(raw_brand).strip():
        return None

    clean = str(raw_brand).strip()
    if clean.lower() in ("none", "null", "n/a", "na", "unspecified", "any", "all"):
        return None

    if catalog_brands:
        # Check case-insensitive match in catalog brands
        lower = clean.lower()
        for b in catalog_brands:
            if b.lower() == lower:
                return b

    # Standard clean brand formatting: capitalize if all lower
    if clean.islower():
        return clean.title()

    return clean


def normalize_currency(currency_str: str | None) -> str:
    """Normalize currency string to standard ISO code.

    Defaults to 'INR' for ShopAssist.
    """
    if not currency_str or not str(currency_str).strip():
        return "INR"
    clean = str(currency_str).strip().upper()
    if clean in ("RUPEES", "RUPEE", "RS", "INR", "₹"):
        return "INR"
    if clean in ("DOLLARS", "DOLLAR", "USD", "$"):
        return "USD"
    if clean in ("EUROS", "EURO", "EUR", "€"):
        return "EUR"
    if clean in ("POUNDS", "POUND", "GBP", "£"):
        return "GBP"
    return clean


def validate_and_normalize_output(
    output: QueryUnderstandingOutput,
    catalog_brands: set[str] | None = None,
) -> tuple[QueryUnderstandingOutput, list[str]]:
    """Validate business rules and normalize category/brand/currency in output.

    Args:
        output: Raw QueryUnderstandingOutput from LLM.
        catalog_brands: Optional set of catalog brands.

    Returns:
        Tuple of (normalized QueryUnderstandingOutput, list of validation warning messages).
    """
    warnings: list[str] = []

    # 1. Normalize category
    raw_cat = output.hard_constraints.category
    norm_cat = normalize_category(raw_cat)
    if raw_cat and not norm_cat:
        warnings.append(
            f"Extracted category '{raw_cat}' is not in the 16 approved canonical categories."
        )
    output.hard_constraints.category = norm_cat

    # 2. Normalize brand
    raw_brand = output.hard_constraints.brand
    norm_brand = normalize_brand(raw_brand, catalog_brands=catalog_brands)
    output.hard_constraints.brand = norm_brand

    # 3. Normalize currency
    raw_curr = output.hard_constraints.currency
    output.hard_constraints.currency = normalize_currency(raw_curr)

    # 4. Check price consistency
    if (
        output.hard_constraints.min_price is not None
        and output.hard_constraints.max_price is not None
        and output.hard_constraints.min_price > output.hard_constraints.max_price
    ):
        warnings.append(
            f"min_price ({output.hard_constraints.min_price}) exceeds max_price ({output.hard_constraints.max_price}); resetting min_price to None."
        )
        output.hard_constraints.min_price = None

    # 5. Check foreign currency clarification
    if output.hard_constraints.currency != "INR":
        output.needs_clarification = True
        curr_msg = (
            f"Query specifies currency '{output.hard_constraints.currency}'. "
            "Catalog prices are exclusively in INR. Currency conversion or clarification required."
        )
        if output.clarification_reason:
            output.clarification_reason = f"{output.clarification_reason} {curr_msg}"
        else:
            output.clarification_reason = curr_msg
        warnings.append(curr_msg)

    # 6. Check unsupported category clarification
    if raw_cat and not norm_cat:
        output.needs_clarification = True
        unsupp_msg = f"Requested category '{raw_cat}' is outside the 16 supported catalog categories."
        if output.clarification_reason:
            output.clarification_reason = f"{output.clarification_reason} {unsupp_msg}"
        else:
            output.clarification_reason = unsupp_msg

    return output, warnings
