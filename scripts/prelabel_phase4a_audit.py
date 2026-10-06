"""Write human-reviewed preliminary labels for the fixed Phase 4A sample.

The index decisions below were made after reading titles, taxonomy, features,
descriptions and selected full candidate records. This is an audit artifact,
not a product filtering rule. The source CSV is never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from pathlib import Path


SOURCE = Path("data/interim/phase4a_audit_sample.csv")
OUTPUT = Path("data/interim/phase4a_audit_sample_prelabelled.csv")
REVIEW_QUEUE = Path("data/interim/phase4a_review_queue.csv")
EXPECTED_SHA256 = "203addda3543c952821baf6e4640f90a6ba6b3dfc54d6eb6d374e8629d10d8c7"


def indices(spec: str) -> set[int]:
    result = set()
    for token in spec.split():
        if "-" in token:
            first, last = map(int, token.split("-"))
            result.update(range(first, last + 1))
        else:
            result.add(int(token))
    return result


# V: complete powered appliance in scope. A: part/accessory. M: manual coffee.
# S: non-electric kettle. B: genuinely ambiguous. Remaining reviewed rows are O:
# unrelated products, food, manual non-coffee cookware, or other domain noise.
DECISIONS = {
    "VALID_PRODUCT": indices("""
        1 4 6 18 26 32 34 37 40 43 44 46 47 48 50 51 54-59
        70 71 73 75 76 78 80 82 88 89 92 100-103 105 108-112 114 116 117 119
        121 124 140-146 148-157 159 162-165 167 168 170-172 174-179
        187 197 201 202 206 220 221 223-226 230 233 234 236-238
        240 242 244 248 250 252 257 268 270 272 277-287 289 291-299
        306 321 323 360-362 364 367 369 371 372
    """),
    "ACCESSORY": indices("""
        3 8 14 19 22-25 27 28 31 35 36 38 42 53
        61 63 67 74 79 84 86 87 91 93-99 104 106 107 113 115 118
        120 125-128 130-139 160 161 166 169 173
        245 253 254 258 265 290
        300 301 303 304 307-312 314 316 318 319 336 363 365 368 370 373-377 379
    """),
    "MANUAL_DEVICE": indices("""
        0 5 7 9 10 12 15-17 20 21 39 41 45 49 52
        231 313 317 320 322 325-334 337-339
    """),
    "STOVETOP": indices("""
        180 183 188 194 195 199 203 205 210 212-214 227-229 232 239
        340-351 353-355 357-359
    """),
    "AMBIGUOUS": indices("11 62 81 83 182 198 200 235 243 255 263 305 315 356 378"),
}

# User review is requested for all ambiguous records and these additional
# boundary, contradictory-metadata or policy-sensitive cases.
REVIEW_NOTES = {
    11: "Title says electric Moka pot, but features and description describe an RC car speed controller.",
    21: "Percolator pot; confirm it is a non-powered coffee brewer.",
    57: "Powered espresso machine, but 220–240 V and European plug; decide regional suitability later.",
    58: "Generic title; confirm product identity from original metadata if needed.",
    62: "USB shaker bottle has a mixing motor, but may not perform as a target blender.",
    81: "Title is only *****; details suggest an electric blender but identity is unclear.",
    83: "Title says black beans while description says replacement blender cup.",
    89: "Nut milk maker blends and heats; decide whether such hybrids belong to blender family.",
    98: "Title says thermostat but description says replacement blender container.",
    121: "Air fryer and toaster oven hybrid; confirm V1 treatment of hybrid appliances.",
    124: "Title/features support air fryer, taxonomy says knife sharpeners.",
    142: "Brand-only title; features/details support a powered air fryer.",
    148: "Oven with air-fry mode; confirm V1 treatment of hybrid appliances.",
    156: "Air/deep fryer combination; confirm V1 treatment of hybrid appliances.",
    180: "Outdoor solid-fuel kettle; classify with non-electric kettles if that boundary is intended.",
    182: "Solar/camping kettle; heating mechanism and V1 boundary unclear.",
    185: "Glass teapot with warmer; no evidence of its own electric heater.",
    197: "Electric samovar boils water; confirm inclusion in electric-kettle family.",
    198: "Manual pour-over kit includes a glass kettle, dripper and filters; confirm dominant item.",
    200: "Cast-iron teapot suitable for heat surfaces, but boiling use is unclear.",
    203: "Japanese description suggests a copper water-boiling kettle; verify heating method.",
    204: "Electric chai brewer is outside the current five families; confirm V1 boundary.",
    205: "Teakettle with little functional metadata; confirm it is stovetop.",
    235: "Title only says kettle; electric taxonomy has no supporting features or description.",
    243: "Electric lunch box/food heater calls itself rice cooker; rice-cooking capability unclear.",
    244: "Electric pressure/rice multicooker; decide inclusion of rice-capable hybrids.",
    250: "Electric pressure/rice multicooker; decide inclusion of rice-capable hybrids.",
    255: "Title says rice cooker, but metadata describes an electric skillet/hot pot.",
    263: "One-touch cooker in rice taxonomy, but no features or description.",
    264: "Electric multi-cooker/steamer without clear rice function; confirm domain boundary.",
    266: "Powered rice warmer holds cooked rice but may not cook it.",
    268: "Electric pressure/rice multicooker; decide inclusion of rice-capable hybrids.",
    272: "Electric pressure/rice multicooker; decide inclusion of rice-capable hybrids.",
    277: "Electric hot pot explicitly cooks rice; decide inclusion of rice-capable hybrids.",
    283: "Electric food steamer with rice bowl; confirm whether it counts as rice cooker.",
    305: "Teapot/coffee maker wording; heat source and dominant function unclear.",
    306: "Actual electric kettle is misfiled under coffee machines; use electric_kettle if retained.",
    313: "Manual pour-over brewer and kettle kit; confirm dominant item.",
    315: "Complete powered coffee maker with built-in blender; choose family or multi-family handling.",
    321: "Manual flag is triggered by 'manual' wording, but 1050 W pump confirms electric espresso machine.",
    323: "Manual flag is triggered by Moka wording, but electric base is described.",
    352: "Electric soup kettle/warmer, not a water kettle; taxonomy is misleading.",
    356: "Cast-iron teapot with infuser; stovetop suitability is not established.",
    366: "French-fry cutter is a separate hand tool; only mentions air fryer as use context.",
    378: "Powered stand mixer with blender attachment; confirm whether hybrid qualifies as blender.",
}

REASONS = {
    "VALID_PRODUCT": "Title and/or product details describe a complete powered appliance in the target family.",
    "ACCESSORY": "Product is a part, replacement, cover or companion accessory rather than a complete target appliance.",
    "MANUAL_DEVICE": "Coffee is prepared manually or with external heat; no integrated powered brewing appliance.",
    "STOVETOP": "Non-electric kettle heated on a stove or other external heat source.",
    "AMBIGUOUS": "Product identity, power source or target family cannot be resolved confidently from metadata.",
    "OTHER_NOISE": "Product is outside the five target powered-appliance families.",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Overwrite existing prelabels and review queue")
    args = parser.parse_args()
    if not args.force and (OUTPUT.exists() or REVIEW_QUEUE.exists()):
        raise SystemExit("Prelabel outputs already exist; use --force only after preserving manual edits")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != EXPECTED_SHA256:
        raise RuntimeError("The Phase 4A sample changed; review index decisions before running")
    with SOURCE.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if len(rows) != 380 or any(row["audit_label"] for row in rows):
        raise RuntimeError("Expected 380 unlabeled sample rows")
    assigned = {}
    for label, positions in DECISIONS.items():
        for position in positions:
            if position in assigned:
                raise RuntimeError(f"Conflicting decisions at row {position}")
            assigned[position] = label
    if max(assigned) >= len(rows):
        raise RuntimeError("Decision position exceeds sample length")
    if set(REVIEW_NOTES) - set(range(len(rows))):
        raise RuntimeError("Review note position exceeds sample length")

    for index, row in enumerate(rows):
        label = assigned.get(index, "OTHER_NOISE")
        row["audit_label"] = label
        row["audit_family"] = ("electric_kettle" if index == 306 else row["candidate_family"] or "NONE") if label == "VALID_PRODUCT" else "NONE"
        row["audit_reason"] = REASONS[label]
        row["review_required"] = "YES" if index in REVIEW_NOTES or label == "AMBIGUOUS" else "NO"
        row["audit_notes"] = ("REVIEW_REQUIRED: " + REVIEW_NOTES.get(index, "Metadata insufficient or contradictory.")) if row["review_required"] == "YES" else "Preliminary label; source listing was not independently verified."

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields + ["review_required"])
        writer.writeheader()
        writer.writerows(rows)
    with REVIEW_QUEUE.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields + ["review_required"])
        writer.writeheader()
        writer.writerows(row for row in rows if row["review_required"] == "YES")
    print(f"Wrote {len(rows)} preliminary labels to {OUTPUT}")
    print("Label counts:", dict(Counter(row["audit_label"] for row in rows)))
    print("Review required:", sum(row["review_required"] == "YES" for row in rows), "->", REVIEW_QUEUE)


if __name__ == "__main__":
    main()
