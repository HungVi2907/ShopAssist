# Phase 4A — Preliminary labels and review queue

**Archived first-pass record.** The 45 queued cases have now been adjudicated. Use the [completed labeling report](phase4a_labeling_report.md), `data/interim/phase4a_audit_sample_labeled.csv`, and `data/interim/phase4a_review_queue_resolved.csv` for current results. The queue described below is the preserved first-pass snapshot.

The 380-row Phase 4A sample has been read against the full retained candidate metadata. Preliminary decisions are in `data/interim/phase4a_audit_sample_prelabelled.csv`; the original `phase4a_audit_sample.csv` remains unedited. The 45 rows marked `review_required = YES` in this archived file were the cases selected for deeper review.

| Preliminary label | Rows |
| --- | ---: |
| `VALID_PRODUCT` | 141 |
| `ACCESSORY` | 89 |
| `MANUAL_DEVICE` | 34 |
| `STOVETOP` | 35 |
| `AMBIGUOUS` | 15 |
| `OTHER_NOISE` | 66 |

Read `audit_notes` for the reason a row needs review. The main decision points are hybrid appliances (air fryer ovens, pressure/rice cookers, coffee maker plus blender), inconsistent metadata, products with only a generic title, and borderline kettle/coffee brewing equipment. A review flag is not a rejection decision. Automatic Phase 3B accessory/manual/stovetop flags were treated as clues; several flagged products are complete powered appliances.

For the completed decisions, inspect `data/interim/phase4a_review_queue_resolved.csv`. Corrections should be made in a copy of the completed labeled CSV so the audit trail remains intact.

The decisions are encoded in `scripts/prelabel_phase4a_audit.py` for traceability against the exact sampled CSV SHA-256. Running the script again will stop if the output exists; `--force` overwrites the prelabelled CSV and review queue, so preserve any human edits first. These labels are provisional and were based on Amazon metadata only, without inspecting live listings. They are not Phase 4B cleaning rules or a population error estimate.
