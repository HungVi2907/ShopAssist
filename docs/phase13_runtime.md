# Phase 13 Windows runtime and test record

## Reproduce the local runtime

The repository's existing `.venv` points at an unavailable Python 3.10 installation. This run used a separate ignored environment in `.deps/`, based on the official Python 3.12.10 Windows x64 package. The downloaded ZIP SHA-256 was `8649692de846c56a7189d6dae5c322ab20deb1b5908b6f39426b62a36f39415d`.

From the repository root in PowerShell:

```powershell
New-Item -ItemType Directory -Path .deps -Force | Out-Null
Invoke-WebRequest https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.zip -OutFile .deps/python-3.12.10-amd64.zip
if ((Get-FileHash .deps/python-3.12.10-amd64.zip -Algorithm SHA256).Hash.ToLower() -ne '8649692de846c56a7189d6dae5c322ab20deb1b5908b6f39426b62a36f39415d') { throw 'Python archive hash mismatch' }
Expand-Archive .deps/python-3.12.10-amd64.zip -DestinationPath .deps/python312
.\.deps\python312\python.exe -m venv .deps/phase13-win-venv
$env:DISABLE_SQLALCHEMY_CEXT='1'
$env:PIP_CACHE_DIR=(Join-Path (Get-Location) '.deps/pip-cache')
.\.deps\phase13-win-venv\Scripts\python.exe -m pip install --no-binary sqlalchemy -r requirements-phase13-windows.txt
.\.deps\phase13-win-venv\Scripts\python.exe -m pip install -e . --no-deps
.\.deps\phase13-win-venv\Scripts\python.exe -m pip check
```

NumPy 1.26.4 needs PyArrow 19.0.1 here; PyArrow 26.0.0 failed to import. SQLAlchemy 2.1.4's compiled extension was blocked by Windows Application Control; 2.0.41 built without its optional C extensions imported successfully. The scikit-learn 1.9.1 wheel's compiled extension was also blocked; 1.7.2 imported successfully and matches the saved TF-IDF artifact. The lock file records the working versions, including `psutil` and `psycopg[binary]`, both needed by the repository but previously absent from its project dependencies.

## Tests and limits

Commands used for this Phase 13 run:

```powershell
.\.deps\phase13-win-venv\Scripts\python.exe -m unittest tests.test_phase13_dataset tests.test_phase13_workflow -v
.\.deps\phase13-win-venv\Scripts\python.exe -m pytest -q -m 'not integration' --disable-warnings --tb=short
.\.deps\phase13-win-venv\Scripts\python.exe scripts/validate_phase13_dataset.py --dataset data/evaluation/phase13/v2
```

The final offline pytest selection passed **482**, skipped **7**, and deselected **15** in 69.11 seconds. The Phase 13 unittest selection passed **18**. The v2 validator reported structural `PASS` and `phase14_ready=false`. Live provider tests and neural-model integration tests were not included in that offline count. A separate read-only Phase 10 to Phase 11 integration test passed. OpenRouter and Groq smoke tests were executed separately and failed as recorded in the [Phase 13 report](phase13_dataset_report.md).

The `.deps/` interpreter and packages are a local reproduction aid, not committed source artifacts. The lock file is the reusable dependency record. The current runtime does not supply human evaluation judgments.
