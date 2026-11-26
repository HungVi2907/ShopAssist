"""Freeze the completed native integration without inference or historical writes."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from datetime import datetime, timezone

from shopassist.llm.extraction import EXTRACTION_PROMPT
from shopassist.llm.transformation import ExtractedShoppingIntent
from shopassist.recommendation.local import SELECTION_PROMPT

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/interim/phase18_5'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    protected = [
        'config/llm_gateway.yaml', 'src/shopassist/llm/transformation.py',
        'src/shopassist/llm/constraints.py', 'src/shopassist/llm/normalization.py',
        'src/shopassist/llm/extraction.py', 'src/shopassist/llm/schemas.py',
        'src/shopassist/recommendation/context.py', 'src/shopassist/recommendation/schemas.py',
        'src/shopassist/recommendation/validation.py', 'src/shopassist/api/schemas.py',
        'data/interim/phase18_t17', 'data/interim/phase18_3', 'data/interim/phase18_4',
    ]
    subprocess.run(['git', 'diff', '--exit-code', 'HEAD', '--', *protected], cwd=ROOT, check=True, capture_output=True)
    changed = subprocess.check_output(['git', 'diff', '--name-only', 'HEAD'], cwd=ROOT, text=True).splitlines()
    new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines()
    sources = sorted({p for p in changed + new if p.startswith(('src/', 'scripts/', 'tests/', 'config/')) or p == '.env.example'})
    frozen = OUT / 'frozen_candidate'
    frozen.mkdir(exist_ok=False)
    for name in sources:
        target = frozen / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    live_path = OUT / 'live_02/integration_results/results.json'
    live = json.loads(live_path.read_text(encoding='utf8'))
    assert all(all(row['checks'].values()) for row in live['records'] if 'checks' in row)
    calls = live['http_calls']
    assert sum(row['path'] == '/api/chat' for row in calls) == 6
    route_artifact = OUT / 'live_02/route_validation/artifact.json'
    identity = json.loads(route_artifact.read_text(encoding='utf8'))['verified_tags']
    report = OUT / 'offline_regression_03.txt'
    raw = report.read_bytes()
    assert '728 passed, 1 warning' in raw.decode('utf16' if raw.startswith(b'\xff\xfe') else 'utf8')
    protected_hashes = {}
    for name in protected:
        path = ROOT / name
        for item in ([path] if path.is_file() else path.rglob('*')):
            if item.is_file() and '__pycache__' not in item.parts:
                protected_hashes[item.relative_to(ROOT).as_posix()] = sha(item)
    write(OUT / 'integration_results/summary.json', {
        'date_local': '2026-11-26 Asia/Saigon', 'offline_passed': 728, 'offline_warnings': 1,
        'live_inference_calls': 6, 'live_control_plane_calls': 2, 'external_inference_calls': 0,
        'combined_inference_calls': 2, 'live_results': live_path.relative_to(ROOT).as_posix(),
        'live_results_sha256': sha(live_path),
        'scope': 'Live local Q1S/R3; mocked retrieval/preference vectors; real RRF contracts. No live catalog-backed E2E acceptance.',
        'earlier_failures': [
            'Focused oversized-response parameter initially exceeded Windows temporary filename limits; short test IDs fixed setup.',
            'Offline 01: 710 passed, 16 failed due to obsolete OpenRouter route lookup in test fixture. Synthetic fixture fixed setup without restoring production route.',
            'Offline 02: 726 passed, 1 existing AsyncMock warning.',
            'live_01: UnicodeDecodeError reading PowerShell UTF-16 offline report before any HTTP/inference. BOM handling fixed harness; live_02 passed.',
        ],
        'success_live_before_final_failure_only_changes': True,
        'production_approved': False, 'phase18_status': 'IMPLEMENTED_PENDING_BACKUP_VALIDATION',
    })
    write(OUT / 'route_validation/index.json', {
        'permission_scope': 'Isolated supervised integration tests only; no production semantic approval',
        'configuration': 'data/interim/phase18_5/live_02/route_validation/gateway.yaml',
        'artifact': route_artifact.relative_to(ROOT).as_posix(), 'artifact_sha256': sha(route_artifact),
        'schema_binding': 'Exact fingerprints and frozen options through normal loader; approvals expire after 24 hours',
        'checked_in_templates': 'Production and experimental templates remain disabled/pending',
    })
    write(frozen / 'manifest.json', {
        'frozen_utc': datetime.now(timezone.utc).isoformat(),
        'starting_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'model': identity, 'protocol': 'Ollama Native /api/chat',
        'options': {'temperature': 0, 'seed': 42, 'num_ctx': 4096, 'stream': False, 'qu_num_predict': 512, 'rec_num_predict': 256},
        'q1s_prompt_sha256': hashlib.sha256(EXTRACTION_PROMPT.encode()).hexdigest(),
        'r3_prompt_sha256': hashlib.sha256(SELECTION_PROMPT.encode()).hexdigest(),
        'q1s_schema': ExtractedShoppingIntent.model_json_schema(),
        'schema_family': 'r3.required-keys.v2',
        'r3_schemas': json.loads(route_artifact.read_text(encoding='utf8'))['schemas'],
        'sources_sha256': {name: sha(ROOT / name) for name in sources},
        'protected_git_paths_unchanged': protected,
        'protected_files_sha256': protected_hashes,
        'production_approved': False, 'historical_t17_modified': False,
    })
    paths = sorted(p for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    write(OUT / 'experiment_manifests/index.json', {
        'sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
        'documents_sha256': {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted((ROOT / 'docs/phase18_5').glob('*.md'))},
        'note': 'Self-excluding artifact index; no model inference, route activation or historical mutation.',
    })
    print(json.dumps({'sources_frozen': len(sources), 'protected_files': len(protected_hashes), 'artifacts_indexed': len(paths)}))


if __name__ == '__main__':
    main()
