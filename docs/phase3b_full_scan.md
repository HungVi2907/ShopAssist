# Phase 3B — Full Home_and_Kitchen metadata scan

The scan uses the pinned Amazon Reviews 2023 `meta_Home_and_Kitchen.jsonl` file
(11,788,767,944 bytes). It reads contiguous HTTP byte ranges, validates HTTP
206 and `Content-Range`, and carries any partial JSONL line to the next range.
Only candidate records are written to disk. Reviews are not accessed.
The published SHA-256 for the entire 11.8 GB source is recorded in the JSON
profile but cannot be recalculated from the retained candidate subset.

Run from the ShopAssist root:

```powershell
python scripts/run_full_scan.py --workers 1
```

The command resumes from the last completed range after an interruption and
retries temporary network failures.
`data/interim/home_kitchen_scan_state.sqlite` is the checkpoint and exact
`parent_asin` index. Keep it alongside
`data/interim/home_kitchen_candidates.jsonl.part` until the scan finishes.
The final outputs are:

- `data/interim/home_kitchen_candidates.jsonl`
- `data/interim/home_kitchen_full_profile.json`
- `data/interim/home_kitchen_full_profile.md`

The runner verifies candidate line counts and unique ASINs against the scan
profile, then adds an audit section to the JSON and Markdown reports.

JSONL is used for incremental checkpoints and heterogeneous `details` fields. A
candidate can match multiple families; `candidate_family` is then null and
`candidate_families` keeps all matches. Accessory, manual coffee, and stovetop
kettle flags are audit hints rather than filters. Missing price, description,
and ratings do not remove records.
The source scan is exhaustive; keyword based candidate detection may still
miss products whose title and taxonomy lack the selected family terms.
