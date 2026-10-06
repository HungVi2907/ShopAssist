"""Adjudicate the 45 flagged Phase 4A rows from retained product metadata.

Decisions are tied to parent_asin and the exact preliminary CSV. This script
records audit judgments only; it does not clean or filter the candidate set.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from pathlib import Path


ROOT = Path("data/interim")
INPUT = ROOT / "phase4a_audit_sample_prelabelled.csv"
INITIAL_QUEUE = ROOT / "phase4a_review_queue.csv"
OUTPUT = ROOT / "phase4a_audit_sample_labeled.csv"
RESOLVED_QUEUE = ROOT / "phase4a_review_queue_resolved.csv"
EXPECTED_INPUT_SHA256 = "3e879f06b9764a3c02e600ddc1dd7d8e31eadfd3296dfe7b89b20a7b92c3fad6"
EXPECTED_QUEUE_SHA256 = "2f4d58cb06ce0a12af670a979f21eb850f97a6fe30bfd977599e1e45ed60ea61"
LABELS = {"VALID_PRODUCT", "ACCESSORY", "WRONG_FAMILY", "MANUAL_DEVICE", "STOVETOP", "AMBIGUOUS", "OTHER_NOISE"}
FAMILIES = {"coffee_maker", "blender", "air_fryer", "electric_kettle", "rice_cooker"}


# Each entry is: final label, final family (None means NONE; "candidate" means
# use the existing single candidate family), and the case-specific evidence.
DECISIONS = {
    "B0837266L8": ("AMBIGUOUS", None, "Coffee-machine title conflicts with RC-car speed-controller features and description; listing identity is unreliable."),
    "B001RL5P9W": ("MANUAL_DEVICE", None, "Granite steel percolator pot has an insulating handle and no integrated electrical heater."),
    "B00EZBTTV6": ("VALID_PRODUCT", "candidate", "15-bar powered espresso machine; 220–240 V plug compatibility is a later availability issue, not product type."),
    "B00N2XQ8Q2": ("VALID_PRODUCT", "candidate", "Features state that the machine grinds beans and automatically brews up to 12 cups."),
    "B0BK876P3S": ("OTHER_NOISE", None, "USB shaker bottle mixes protein powder; no food-blending blades or target blender function are described."),
    "B0B1MB61HL": ("AMBIGUOUS", None, "Title is only asterisks; blender taxonomy and electric specifications cannot establish product identity."),
    "B071VJGDLF": ("AMBIGUOUS", None, "Black-beans title conflicts with replacement blender-cup description; neither product identity is reliable."),
    "B0BCHJ7F8G": ("VALID_PRODUCT", "candidate", "Powered nut-milk machine explicitly heats and blends, and offers a smoothie mode."),
    "B0055ZHAV2": ("ACCESSORY", None, "Thermostat title conflicts with blender-container description, but both describe parts rather than a complete blender."),
    "B091RM7GCK": ("VALID_PRODUCT", "candidate", "Complete countertop oven explicitly marketed with an air-fry function; hybrid appliance counted for this audit."),
    "B08VDLK32T": ("VALID_PRODUCT", "candidate", "1400 W air fryer, basket and air-circulation features outweigh incorrect knife-sharpener taxonomy."),
    "B07HRMQJCF": ("VALID_PRODUCT", "candidate", "Brand-only title is supported by air-fryer features, capacity, wattage and controls."),
    "B0C8F19BQY": ("VALID_PRODUCT", "candidate", "Powered countertop oven has an explicit Air Fry cooking mode; hybrid appliance counted for this audit."),
    "B089B63Z8R": ("VALID_PRODUCT", "candidate", "Complete 2-in-1 machine explicitly provides rapid-hot-air frying as well as deep frying."),
    "B00AQ7YA26": ("STOVETOP", None, "Outdoor kettle boils using natural fuel rather than an integrated electrical heater; grouped with externally heated kettles."),
    "B07L965DPC": ("OTHER_NOISE", None, "Camping solar/thermos vessel has no evidence of an integrated powered kettle heater."),
    "B0160JG29C": ("OTHER_NOISE", None, "Glass teapot with a matching warmer is described without an integrated electric boiling element."),
    "B01LYOAYPE": ("VALID_PRODUCT", "candidate", "Electric samovar has a 2200 W heating element, boils water and shuts off automatically."),
    "B071HC5PYT": ("MANUAL_DEVICE", None, "Hario kit contains a glass pouring vessel, porcelain dripper and paper filters; operation is manual."),
    "B000AXQAEW": ("STOVETOP", None, "Full description says cast-iron teapot brings water to a boil at medium external heat."),
    "B002WBV1L2": ("STOVETOP", None, "Copper water-boiling kettle is listed as cookware and has no integrated electrical components."),
    "B096TB5NLT": ("OTHER_NOISE", None, "1500 W chai brewer prepares milk tea; it is not an electric water kettle or another target family."),
    "B0007CXQM0": ("STOVETOP", None, "Traditional teakettle under cookware has no powered element; classified as externally heated."),
    "B07G8Y42B5": ("AMBIGUOUS", None, "Only a generic kettle title and electric taxonomy exist; no features establish its heat source."),
    "B09H5FYLWK": ("AMBIGUOUS", None, "Electric lunch-box heater calls itself a rice cooker, but no features show that it cooks raw rice."),
    "B001JO40X4": ("VALID_PRODUCT", "candidate", "Electric pressure/slow cooker explicitly includes a rice-cooking program; hybrid counted for this audit."),
    "B07HB139GC": ("VALID_PRODUCT", "candidate", "Electric multicooker explicitly rice-cooks in addition to pressure-cooking and steaming."),
    "B089FLQZ3R": ("OTHER_NOISE", None, "Features and description identify an electric skillet/hot pot with no supported rice program despite the title."),
    "B01DJDE9PQ": ("AMBIGUOUS", None, "One-touch cooker has rice-cooker taxonomy but no feature or description confirming rice cooking."),
    "B00GRTW524": ("OTHER_NOISE", None, "Electric multi-cooker/steamer description covers stews, roasts and steaming but no rice function."),
    "B0C1RBRQ7L": ("OTHER_NOISE", None, "Commercial electric rice warmer holds already-cooked rice; no raw-rice cooking function is described."),
    "B07MCW97CF": ("VALID_PRODUCT", "candidate", "Electric pressure multicooker lists a dedicated Rice program."),
    "B081V7RG9M": ("VALID_PRODUCT", "candidate", "Electric pressure multicooker lists Rice/Risotto and Multigrain presets."),
    "B098G2G6SG": ("VALID_PRODUCT", "candidate", "Electric hot pot explicitly advertises a de-sugar rice-cooking function."),
    "B00004SC50": ("VALID_PRODUCT", "candidate", "Powered steamer includes a rice bowl and description explicitly says it cooks rice."),
    "B07SZ6W7NN": ("STOVETOP", None, "Teapot feature says it is safe on gas, induction and electric stovetops for boiling water."),
    "B0757Y4S84": ("VALID_PRODUCT", "electric_kettle", "Complete kettle has digital temperature control, concealed electric heater and keep-warm mode; coffee taxonomy is wrong."),
    "B077TVSJ7Q": ("MANUAL_DEVICE", None, "Pour-over kit includes manual coffee brewer and pouring kettle, with no integrated powered brewer."),
    "B09JZR6XWC": ("VALID_PRODUCT", "coffee_maker", "Complete powered machine brews coffee and has a built-in blender; coffee maker is the primary marketed function."),
    "B07H28TCLC": ("VALID_PRODUCT", "candidate", "1050 W, 15-bar pump proves powered espresso machine; manual flag refers to wording, not manual brewing."),
    "B01E5KME6S": ("VALID_PRODUCT", "candidate", "Moka brewer has a described electric base and adjustable heat control; manual keyword is misleading."),
    "B003XW7XMK": ("OTHER_NOISE", None, "1000 W soup kettle is a commercial soup warmer, not a water kettle."),
    "B09NY9W21B": ("STOVETOP", None, "Title explicitly states cast-iron tea kettle is stove-top safe; no electric heater is described."),
    "B08LDFMWKW": ("OTHER_NOISE", None, "Hand-operated french-fry cutter only mentions an air fryer as a possible use context."),
    "B00938S1V0": ("OTHER_NOISE", None, "Product is primarily a stand mixer; included blender attachment does not make it a standalone blender."),
}


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Overwrite existing adjudicated outputs")
    args = parser.parse_args()
    if not args.force and (OUTPUT.exists() or RESOLVED_QUEUE.exists()):
        raise SystemExit("Adjudicated outputs already exist; preserve edits before using --force")
    for path, expected in ((INPUT, EXPECTED_INPUT_SHA256), (INITIAL_QUEUE, EXPECTED_QUEUE_SHA256)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Input changed; inspect decisions before running: {path}")
    fields, rows = read_csv(INPUT)
    _, queue = read_csv(INITIAL_QUEUE)
    flagged = {row["parent_asin"] for row in queue}
    if len(rows) != 380 or len(queue) != 45 or flagged != set(DECISIONS):
        raise RuntimeError("Decision ASINs do not exactly match the 45-row review queue")
    if len({row["parent_asin"] for row in rows}) != 380:
        raise RuntimeError("Duplicate ASIN in input")

    resolved = []
    for row in rows:
        asin = row["parent_asin"]
        if asin in DECISIONS:
            label, family, reason = DECISIONS[asin]
            if label not in LABELS:
                raise RuntimeError(f"Invalid audit label for {asin}")
            if family == "candidate":
                family = row["candidate_family"]
            if label == "VALID_PRODUCT" and family not in FAMILIES:
                raise RuntimeError(f"Missing canonical audit family for {asin}")
            row["audit_label"] = label
            row["audit_family"] = family if label == "VALID_PRODUCT" else "NONE"
            row["audit_reason"] = reason
            row["audit_notes"] = ("Metadata conflict remains; AMBIGUOUS is the completed audit label."
                                  if label == "AMBIGUOUS" else "Adjudicated from retained Amazon metadata; live listing not checked.")
            row["review_required"] = "NO"
            row["audit_status"] = "ADJUDICATED"
            resolved.append(row)
        else:
            if row["review_required"] != "NO":
                raise RuntimeError(f"Unexpected unresolved row: {asin}")
            row["audit_status"] = "PRELABEL"
    if len(resolved) != 45 or any(row["review_required"] != "NO" for row in rows):
        raise RuntimeError("Not all review rows were adjudicated")
    output_fields = fields + ["audit_status"]
    for path, content in ((OUTPUT, rows), (RESOLVED_QUEUE, resolved)):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=output_fields)
            writer.writeheader()
            writer.writerows(content)
    print(f"Wrote {len(rows)} labeled rows to {OUTPUT}")
    print(f"Resolved {len(resolved)} cases in {RESOLVED_QUEUE}")
    print("Final label counts:", dict(Counter(row["audit_label"] for row in rows)))


if __name__ == "__main__":
    main()
