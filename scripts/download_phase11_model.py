"""Download the pinned Phase 11 Cross-Encoder into an ignored local directory."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "cross-encoder/ms-marco-MiniLM-L2-v2"
MODEL_REVISION = "1b5cd67b15209f24824c50370e0397743aa9b787"
MODEL_DIR = Path(os.getenv("SHOPASSIST_PHASE11_MODEL_DIR", ROOT / ".models/phase11/ms-marco-MiniLM-L2-v2"))
MANIFEST = ROOT / "data/interim/phase11/phase11_model_manifest.json"


def run() -> dict[str, object]:
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=str(MODEL_DIR),
        allow_patterns=[
            "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
            "special_tokens_map.json", "vocab.txt", "modules.json", "sentence_bert_config.json",
        ],
    )
    files: dict[str, dict[str, object]] = {}
    for path in sorted(item for item in MODEL_DIR.rglob("*") if item.is_file() and ".cache" not in item.parts):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        files[str(path.relative_to(MODEL_DIR))] = {"size_bytes": path.stat().st_size, "sha256": digest}
    required = {"config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "vocab.txt"}
    missing = sorted(required - files.keys())
    if missing:
        raise RuntimeError(f"Pinned snapshot is missing required artifacts: {missing}")
    manifest = {
        "status": "DOWNLOADED_PINNED_ARTIFACTS",
        "repository": MODEL_ID,
        "revision": MODEL_REVISION,
        "license": "apache-2.0 (repository model card)",
        "license_source": "https://huggingface.co/cross-encoder/ms-marco-MiniLM-L2-v2",
        "model_dir": str(MODEL_DIR),
        "files": files,
        "required_files": sorted(required),
        "configuration": json.loads((MODEL_DIR / "config.json").read_text(encoding="utf-8")),
        "tokenizer_configuration": json.loads((MODEL_DIR / "tokenizer_config.json").read_text(encoding="utf-8")),
        "runtime_dependencies": {
            package: importlib.metadata.version(package)
            for package in ("sentence-transformers", "torch", "transformers", "huggingface-hub", "safetensors")
        },
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    result = run()
    print(json.dumps({"status": result["status"], "repository": result["repository"], "revision": result["revision"], "file_count": len(result["files"]), "manifest": str(MANIFEST)}, indent=2))
