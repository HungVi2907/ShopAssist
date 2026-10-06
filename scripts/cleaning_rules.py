"""Conservative, explainable Phase 4B metadata rules.

Predictions are audit decisions only. Phase 4C will decide how to apply them to
the full candidate dataset. Phase 3B flags are intentionally not ground truth.
"""

from __future__ import annotations

import re

from phase4b_common import normalize_text


FAMILIES = ("coffee_maker", "blender", "air_fryer", "electric_kettle", "rice_cooker")


def hits(patterns: dict[str, str], text: str) -> list[str]:
    return [name for name, pattern in patterns.items() if re.search(pattern, text)]


def decision(label: str, rule_id: str, signals: list[str], reason: str,
             family: str | None = None) -> dict:
    return {"predicted_label": label,
            "decision": "KEEP" if label == "VALID_PRODUCT" else "REVIEW" if label == "REVIEW" else "REMOVE",
            "predicted_family": family if label == "VALID_PRODUCT" else None,
            "rule_id": rule_id, "matched_signals": sorted(set(signals)), "reason": reason}


ACCESSORY_PATTERNS = {
    "replacement_or_spare": r"\b(?:replacement|spare|oem part|replaces part|compatible with|fits models?|part numbers?)\b",
    "accessory_title": r"\b(?:accessories set|replacement parts|cord organizer|cord winder|dust cover|appliance slider|rolling drawer|liner(?:s)?|parchment (?:paper|liner)|paper liners?|blender cover)\b",
    "component_title": r"\b(?:blade|gasket|carafe|filter screen|tamper|knock box|inner pot|cooking pan|pitcher bowl|coupler|clutch|gear kit|thermal carafe|basket and handle|rotisserie cage|power cord|steamer basket)\b",
}
ACCESSORY_OBJECT = r"\b(?:blade|gasket|carafe|filter|basket|lid|cup|jar|pitcher|cover|cord|tray|pot|container|screen|whisk|rack|mat|pan|thermometer)\b"
COMPLETE_TITLE = {
    "coffee_maker": r"\b(?:coffee maker|coffeemaker|coffee machine|coffee brewer|brewing system|espresso machine|espresso maker)\b",
    "blender": r"\b(?:blender|blendmax|smoothie maker)\b",
    "air_fryer": r"\b(?:air fryer|airfryer|air fry oven|oven with air fry|air and deep fryer)\b",
    "electric_kettle": r"\b(?:electric kettle|electric tea kettle|digital kettle|cordless kettle|electric samovar|hot water boiler|water boiler and warmer)\b",
    "rice_cooker": r"\b(?:rice cooker|rice maker|multicooker|multi cooker|pressure cooker)\b",
}
POWERED = {
    "electric_title": r"\b(?:electric|cordless|rechargeable|battery operated|usb rechargeable|digital|programmable|automatic)\b",
    "power_rating": r"\b\d{2,4}\s*(?:w|watts?)\b",
    "powered_mechanism": r"\b(?:heating element|electric base|electric pump|powered pump|motor|auto shut off|automatic shut off|digital control|touch screen|preset(?:s)?)\b",
}
MANUAL = {
    "french_press": r"\bfrench press\b",
    "pour_over": r"\bpour over\b|\bpourover\b",
    "moka_or_ibrik": r"\b(?:moka pot|stovetop espresso|cezve|ibrik|briki|turkish coffee pot)\b",
    "hand_brewing": r"\b(?:hand pump|hand press|manual coffee|coffee dripper|ceramic coffee dripper|coffee press|coffee percolator pot)\b",
    "cold_brew_vessel": r"\bcold brew coffee maker\b|\bcold brew pitcher\b",
}
STOVE = {
    "stovetop": r"\b(?:stovetop|stove top|for all stovetops|stovetop safe|gas stove|induction stove|stove types)\b",
    "whistling": r"\b(?:whistling|whistle(?:s)?)\b",
    "external_fuel": r"\b(?:natural fuel|camp stove|campfire)\b",
}
OTHER_TITLE = {
    "non_target_kitchen_tool": r"\b(?:oil sprayer|oil dispenser|french fry cutter|pastry blender|dough blender|bench scraper|egg whisk|milk frother|hand mixer|cookie cutter|biscuit cutter|tea ball|tea press|coffee roaster)\b",
    "container_or_non_appliance": r"\b(?:travel mug|espresso cups?|water bottle|shaker bottle|honey jar|honey dispenser|bottle cleaner|mug holder|tea cozy|wax seal|rice paper|rice mold|microwave rice cooker|microwave rice and pasta cooker)\b",
    "other_electrical_product": r"\b(?:ice maker|digital voice recorder|landscape lighting|electric hot plate|electric mini stove|soup kettle|rice warmer|food chopper|electric skillet)\b",
    "external_cookware": r"\b(?:stovetop ceramic|stove top pressure cooker|stovetop pressure cooker|rice pot handmade)\b",
    "brewing_tool": r"\b(?:hop spider|brew pot|sparge arm|brew pot thermometer)\b",
}


def fields(record: dict) -> tuple[str, str, str, str]:
    title = normalize_text(record.get("title") or "")
    categories = normalize_text(" ".join(value for value in (record.get("categories") or []) if isinstance(value, str)))
    features = normalize_text(" ".join(value for value in (record.get("features") or []) if isinstance(value, str)))
    description = normalize_text(" ".join(value for value in (record.get("description") or []) if isinstance(value, str)))
    return title, categories, features, description


def detect_accessory(record: dict) -> dict | None:
    title, categories, features, description = fields(record)
    title_hits = hits(ACCESSORY_PATTERNS, title)
    part_taxonomy = "parts accessories" in categories or "replacement parts" in categories
    complete = any(re.search(pattern, title) for pattern in COMPLETE_TITLE.values())
    powered = bool(hits(POWERED, title + " " + features))
    explicit_part = bool(re.search(r"\b(?:replacement|spare|compatible with|fits models?|replaces part|oem part)\b", title))
    hard_part = bool(re.search(r"\b(?:replacement|spare|replaces part|oem part)\b", title))
    accessory_head = bool(re.search(r"^(?:\w+\s+){0,3}(?:air fryer liners?|air fryer paper|cord organizer|blender blade|coffee filter|replacement|[\w ]+ replacement)", title))
    primary_component = bool(re.search(r"\b(?:blender|air fryer|rice cooker|coffee maker)\s+(?:bottom\s+)?(?:blade|basket|cover|cup|container|inner pot|paper|liner|accessories)\b", title)
                             or re.search(r"\b(?:blade|basket|cover|cup|container|inner pot|steamer basket)\b.*\b(?:for|fits|insert in)\b.*\b(?:blender|air fryer|rice cooker|coffee maker)\b", title))
    if part_taxonomy and re.search(r"\b(?:replacement|oem part|listing is only for)\b", features + " " + description):
        return decision("ACCESSORY", "accessory_part_confirmed_by_description", ["parts_taxonomy", "replacement_description"],
                        "Parts taxonomy and product description agree that only a replacement component is sold.")
    if explicit_part and (hard_part or not (complete and powered)) and (re.search(ACCESSORY_OBJECT, title) or part_taxonomy or "part" in title):
        return decision("ACCESSORY", "accessory_explicit_part", title_hits + ["part_object_or_taxonomy"],
                        "Title explicitly sells a replacement/compatible part, supported by object or parts taxonomy.")
    if re.search(r"\b(?:cord organizer|cord winder|dust cover|appliance slider|rolling drawer)\b", title):
        return decision("ACCESSORY", "accessory_companion", title_hits,
                        "The sold item is an appliance companion or organizer, not a complete appliance.")
    if primary_component and not (re.search(r"\b(?:rechargeable|usb|electric)\b", title) and re.search(r"\b(?:portable|personal)\b.*\bblender cup\b", title)):
        return decision("ACCESSORY", "accessory_primary_component", title_hits + ["primary_component"],
                        "The title sells an appliance part or accessory as the primary item.")
    if re.search(r"^air fryer\b.*\baccessories for\b", title):
        return decision("ACCESSORY", "accessory_air_fryer_kit", ["air_fryer_accessories_for"],
                        "The air fryer is only the compatibility target for an accessory kit.")
    if re.search(r"\b(?:liner|liners|parchment paper|air fryer paper|air fryer accessories set|air fryer silicone pot)\b", title) and "air fryer" in title and not (complete and powered and not part_taxonomy):
        return decision("ACCESSORY", "accessory_air_fryer_consumable", title_hits,
                        "The title sells an air-fryer liner, paper or accessory set.")
    if part_taxonomy and not (complete and powered):
        return decision("ACCESSORY", "accessory_parts_taxonomy", title_hits + ["parts_taxonomy"],
                        "Parts/accessories taxonomy is consistent with no powered complete appliance in title/features.")
    if accessory_head and not powered and re.search(ACCESSORY_OBJECT, title):
        return decision("ACCESSORY", "accessory_component_title", title_hits,
                        "The title names an appliance component without complete-appliance power evidence.")
    if re.search(r"\b(?:filter screen|carafe|gasket|coupler|clutch|gear kit|tamper|knock box|basket and handle|rotisserie cage)\b", title) and (part_taxonomy or not complete):
        return decision("ACCESSORY", "accessory_named_component", title_hits,
                        "The sold item is a named component or coffee-tool accessory.")
    if re.search(r"\b(?:o e m authorized part|oem part|fits various models)\b", features + " " + description) and not re.search(r"\b(?:blends|brews|cooks|frys|heats water)\b", features):
        return decision("ACCESSORY", "accessory_oem_part_description", ["oem_part_description"],
                        "Features/description state an OEM replacement part, not a whole appliance.")
    return None


def detect_manual_device(record: dict) -> dict | None:
    title, categories, features, description = fields(record)
    families = record.get("candidate_families") or ([record.get("candidate_family")] if record.get("candidate_family") else [])
    if "coffee_maker" not in families and not re.search(r"\bcoffee\b", title):
        return None
    manual_hits = hits(MANUAL, title)
    if re.search(r"\b(?:manual lever|hand operated|requires no electricity)\b", features + " " + description):
        manual_hits.append("manual_operation_description")
    if "percolators" in categories and re.search(r"\bpercolator\b", title) and not re.search(r"\belectric\b", title):
        manual_hits.append("manual_percolator")
    if re.search(r"\bmanual grind\b", title) and "coffee" in title:
        manual_hits.append("manual_grinding_brewing_kit")
    if not manual_hits and "french presses" in categories:
        manual_hits = ["french_press_taxonomy"]
    if not manual_hits:
        return None
    powered = hits(POWERED, title + " " + features + " " + description)
    if re.search(r"\b(?:electric moka|electric base|electric espresso|electric coffee|electric pot moka)\b", title + " " + features):
        return None
    external_electric = bool(re.search(r"\b(?:electric stovetop|electric stove|gas electric|stove types|stovetops)\b", title + " " + features))
    if powered and not external_electric and not re.search(r"\b(?:no electricity|requires no electricity|hand operated|manual lever)\b", title + " " + features + " " + description):
        return None
    return decision("MANUAL_DEVICE", "manual_coffee_brewer", manual_hits,
                    "Coffee brewing relies on manual operation or external heat, with no reliable integrated power evidence.")


def detect_stovetop(record: dict) -> dict | None:
    title, categories, features, description = fields(record)
    families = record.get("candidate_families") or ([record.get("candidate_family")] if record.get("candidate_family") else [])
    if "electric_kettle" not in families and not re.search(r"\bkettle\b|\bteakettle\b", title):
        return None
    if (re.search(r"\b(?:electric kettle|electric tea kettle|digital kettle|cordless kettle|electric samovar)\b", title)
            or ("electric" in title and "kettle" in title and "stovetop" not in title)):
        return None
    stove_hits = hits(STOVE, title + " " + features)
    cookware_kettle = "cookware tea kettles" in categories
    kettle_title = bool(re.search(r"\b(?:kettle|teakettle|teapot)\b", title))
    if stove_hits and kettle_title and not re.search(r"\b(?:faster than|unlike|compared with)\b.{0,40}\bstovetop\b", features + " " + description):
        return decision("STOVETOP", "stovetop_external_heat", stove_hits,
                        "Kettle is explicitly heated on a stove or external fuel, with no integrated electric kettle in title.")
    if cookware_kettle and kettle_title and not hits(POWERED, title + " " + features):
        return decision("STOVETOP", "stovetop_cookware_taxonomy", ["cookware_tea_kettles"],
                        "Cookware kettle with no integrated powered-heater evidence.")
    return None


def detect_other_noise(record: dict) -> dict | None:
    title, categories, features, description = fields(record)
    title_hits = hits(OTHER_TITLE, title)
    if re.search(r"\b(?:milk frother|steamer pot|stand mixer)\b", title):
        coffee_machine = bool(re.search(r"\b(?:coffee maker|coffeemaker|espresso machine|coffee machine|espresso.*maker machine)\b", title))
        rice_machine = bool(re.search(r"\brice cooker\b", title))
        if (coffee_machine and "milk frother" in title) or (rice_machine and "steamer pot" in title):
            title_hits = [hit for hit in title_hits if hit != "non_target_kitchen_tool"]
        if re.search(r"\bstand mixer\b", title) and not re.search(r"\b(?:coffee maker|air fryer|rice cooker)\b", title):
            title_hits.append("stand_mixer_primary")
    if re.search(r"\b(?:balloon whisk|hand push (?:egg )?whisk|manual whisk)\b", title):
        title_hits.append("manual_whisk")
    if re.search(r"\b(?:steamer pot)\b", title) and not re.search(r"\brice cooker\b", title):
        title_hits.append("standalone_steamer_pot")
    if title_hits:
        return decision("OTHER_NOISE", "other_non_target_title", title_hits,
                        "Title identifies a different product type or non-powered cookware outside the target families.")
    if "rice_cooker" in (record.get("candidate_families") or []) or record.get("candidate_family") == "rice_cooker":
        if re.search(r"\bmicrowave\b", title) and re.search(r"\brice\b", title):
            return decision("OTHER_NOISE", "other_microwave_rice_vessel", ["microwave", "rice"],
                            "Microwave vessel has no integrated rice-cooking heater.")
        if re.search(r"\brice warmer\b", title):
            return decision("OTHER_NOISE", "other_rice_warmer", ["rice_warmer"],
                            "Warmer holds already cooked rice; cooking function is not evidenced.")
    if re.search(r"\b(?:dictaphone|black beans|stranded wire|electrical wire|rice paper wrappers|rice mold)\b", title):
        return decision("OTHER_NOISE", "other_obvious_taxonomy_noise", ["non_target_title"],
                        "Title contradicts target appliance taxonomy.")
    return None


def detect_valid_product(record: dict) -> dict | None:
    title, categories, features, description = fields(record)
    families = record.get("candidate_families") or ([record.get("candidate_family")] if record.get("candidate_family") else [])
    if not families:
        return None
    evidence = title + " " + features + " " + description
    if len(families) > 1:
        if re.search(r"\b(?:electric|digital|cordless) kettle\b", title):
            families = ["electric_kettle"]
        elif "coffee_maker" in families and re.search(r"\bcoffee maker\b", title) and "coffee makers" in categories:
            families = ["coffee_maker"]
        else:
            return None
    family = families[0]
    if family not in FAMILIES:
        return None
    title_complete = bool(re.search(COMPLETE_TITLE[family], title))
    powered = hits(POWERED, evidence)
    category_support = {
        "coffee_maker": ("coffee makers", "espresso machines", "coffee machines"),
        "blender": ("blenders",), "air_fryer": ("air fryers",),
        "electric_kettle": ("electric kettles", "water boilers"), "rice_cooker": ("rice cookers",),
    }
    taxonomy = any(term in categories for term in category_support[family])
    if family == "electric_kettle":
        if (title_complete and (powered or taxonomy)) or (taxonomy and powered and re.search(r"\b(?:electric thermos pot|water boiler|kettle)\b", title)):
            return decision("VALID_PRODUCT", "valid_electric_kettle", ["complete_kettle_title", *powered, *( ["target_taxonomy"] if taxonomy else [])],
                            "Complete kettle with integrated electric-heating evidence or electric-kettle taxonomy.", family)
        return None
    if family == "rice_cooker":
        rice_function = bool(re.search(r"\b(?:rice cook(?:er|ing|s)?|cooks rice|rice program|rice preset|rice risotto)\b", evidence))
        if re.search(r"\b(?:lunch box|food heater)\b", title) and not re.search(r"\b(?:rice cook(?:ing|s)?|cooks rice|rice program|rice preset)\b", features + " " + description):
            return None
        if title_complete and rice_function and (powered or taxonomy):
            return decision("VALID_PRODUCT", "valid_powered_rice_cooking", ["rice_function", *powered, *( ["target_taxonomy"] if taxonomy else [])],
                            "Complete powered cooker has an explicit rice-cooking function.", family)
        return None
    if family == "coffee_maker":
        if title_complete and (powered or taxonomy or re.search(r"\b(?:brews|brewing|15 bar|pump espresso)\b", evidence)):
            return decision("VALID_PRODUCT", "valid_powered_coffee", ["complete_coffee_title", *powered, *( ["target_taxonomy"] if taxonomy else [])],
                            "Complete coffee machine has power, brewing or target-taxonomy support.", family)
        return None
    if family == "blender":
        if title_complete and (powered or taxonomy or re.search(r"\b(?:blends|smoothies|motor base|blending)\b", evidence)):
            return decision("VALID_PRODUCT", "valid_powered_blender", ["complete_blender_title", *powered, *( ["target_taxonomy"] if taxonomy else [])],
                            "Complete blender has motor, blending or target-taxonomy support.", family)
        return None
    if family == "air_fryer":
        if (title_complete or (taxonomy and "air fryer" in evidence)) and (powered or taxonomy or re.search(r"\bhot air\b", evidence)):
            return decision("VALID_PRODUCT", "valid_powered_air_fryer", ["air_fry_function", *powered, *( ["target_taxonomy"] if taxonomy else [])],
                            "Complete appliance has an explicit powered air-fry function.", family)
    return None


def resolve_candidate(record: dict) -> dict:
    """Return label/KEEP/REMOVE/REVIEW plus a stable rule ID and evidence."""
    title, categories, features, description = fields(record)
    if not title and not features and not description:
        return decision("REVIEW", "unresolved_missing_identity", ["missing_title_and_text"],
                        "Insufficient product text to establish identity.")
    # Explicit conflict is deferred rather than trusting either metadata side.
    if title == "" or re.fullmatch(r"\W*", record.get("title") or ""):
        return decision("REVIEW", "unresolved_title", ["unusable_title"],
                        "Unusable title prevents a reliable product decision.")
    # These orders protect complete machines mentioning their included filters,
    # cups or baskets, while still allowing strong replacement evidence to win.
    for detector in (detect_accessory, detect_manual_device, detect_stovetop, detect_other_noise, detect_valid_product):
        result = detector(record)
        if result is not None:
            return result
    return decision("REVIEW", "unresolved_insufficient_evidence", ["no_safe_rule"],
                    "Available signals do not safely establish a target appliance or an invalid class.")
