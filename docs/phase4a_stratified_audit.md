# Phase 4A — Stratified Candidate Audit

## Objective and input

Use the completed Phase 3B `data/interim/home_kitchen_candidates.jsonl` (55,064 unique `parent_asin` values) to prepare a **manual** audit. This phase identifies false-positive patterns; it does not produce final cleaning rules or a clean product dataset. The 11.8 GB metadata source is not scanned again.

## Sampling

The script uses seed `20261006` and a SHA-256 rank of `seed:parent_asin`, so repeated runs on the same source produce identical outputs. It samples 20 rows from each of 15 single-family strata: five families × `title_only`, `taxonomy_only`, or `both`. The source is derived from each family's `match_details[family].matched_by`; ambiguous records use their union `matched_by` only for display. If a stratum has fewer than 20 records, all are included.

It then adds up to 20 *new* rows from each of four targeted groups, in this order: multi-family, manual coffee, stovetop kettle, accessory. Existing sampled ASINs are skipped. Multi-family records keep an empty `candidate_family` and retain the complete `candidate_families` list. `audit_group` identifies whether a row came from a base stratum or a targeted addition. Groups and flags can overlap. The current run has 380 unique rows (300 base + 80 targeted).

This is an intentionally balanced, risk-enriched engineering sample. Its raw proportions are **not** estimates of prevalence or cleaning precision in all 55,064 candidates.

## Outputs

- `data/interim/phase4a_audit_sample.csv`: review table, UTF-8 with BOM for spreadsheet compatibility.
- `data/interim/phase4a_audit_profile.json`: counts, configuration, source SHA-256 and paths.
- `data/interim/phase4a_audit_profile.md`: readable coverage and limitations.

The CSV preserves title, family match evidence, matched risk keywords, price, rating and the three risk flags. Nested fields are consistently JSON serialized; `categories` and `match_details` are capped at 500 characters, `features`, `description`, `details` at 1,200 each, and matched risk keyword lists at 300 each, with an explicit truncation suffix. Consult the original candidate JSONL for any shortened cell. Missing price stays in the sample.

## Manual labels

Fill `audit_label`, `audit_family`, `audit_reason`, and `audit_notes` in a **copy** of the generated CSV so regeneration does not overwrite work. Allowed `audit_label` values:

| Label | Meaning |
| --- | --- |
| `VALID_PRODUCT` | Complete powered appliance in the intended family |
| `ACCESSORY` | Part, attachment or other accessory instead of a complete appliance |
| `WRONG_FAMILY` | Complete product assigned to a wrong target family |
| `MANUAL_DEVICE` | Non-powered coffee device, such as a French press |
| `STOVETOP` | Non-electric stovetop or whistling kettle |
| `AMBIGUOUS` | Insufficient evidence for one product type or family |
| `OTHER_NOISE` | Other false positive |

`audit_family` should be one of `coffee_maker`, `blender`, `air_fryer`, `electric_kettle`, `rice_cooker`, or `NONE` when no target family applies. Explain uncertain decisions in `audit_reason` or `audit_notes`. Risk flags are hints and must not be treated as labels. The intended V1 domain is powered small kitchen appliances, but audit examples before designing exclusions.

## Regenerate and validate

Run from the ShopAssist root in PowerShell:

```powershell
python scripts/run_phase4a_audit_sample.py
python -m unittest discover -s tests -v
```

The script also accepts `--source`, `--sample-csv`, `--profile-json`, `--profile-md`, `--seed`, `--per-stratum`, and `--per-target`. Defaults reproduce the reported sample. Tests check uniqueness, reproducibility, all available strata, manual columns, profile counts, source membership, source immutability and targeted coverage without network access.

## Known limitations and next step

Candidate discovery depends on Phase 3B title/taxonomy terms and can miss relevant products with no matching terms. Flag patterns can have both false positives and false negatives. Truncated CSV cells require consultation of the original JSONL. The sample is for discovering patterns, not measuring population rates without weighting.

After the CSV has been manually labeled, analyze errors by family, match source and risk group. Use that evidence in **Phase 4B — Cleaning Rule Design and Validation**. Review acquisition follows final product selection in Phase 4C.

The 380-row sample has now been labeled from retained metadata, including a second pass over all 45 difficult cases. See the [Phase 4A labeling report](phase4a_labeling_report.md) and `data/interim/phase4a_audit_sample_labeled.csv`. Six rows carry a completed `AMBIGUOUS` label because their metadata cannot establish product identity confidently.
