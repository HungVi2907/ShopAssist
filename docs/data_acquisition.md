# Phase 1: Appliances metadata

Source: [Amazon Reviews 2023, McAuley Lab](https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/blob/main/README.md).

Run from the project root:

```powershell
python scripts/download_metadata.py
```

The script downloads the official Hugging Face copy of
`raw/meta_categories/meta_Appliances.jsonl` to `data/raw/`. It verifies the
published SHA-256 and checks that every line is a JSON object with a
`parent_asin`. It prints the record count. `curl` is required. It does not
download reviews; those belong to Phase 4, after product selection.

Raw data is excluded from version control. The JSONL file is the input for
Phase 2 taxonomy exploration.

Phase 1 result (2026-10-06): 94,327 records, 285,298,475 bytes. The file's
SHA-256 is `b25ae892af7bc452c4a54b7e4fee52f4c3e9adf058768ca3cb07ecb8d328b41e`.
