# RnD_Data_Logging_System
A data logging system created across research and development department to manage Oliver Twinsafe and RnD System
# RnD Monorepo

This repository contains the R&D application stack used around the Twinsafe
workflow:

- `Central Hub`: FastAPI backend plus frontend for the hub UI
- `DLS`: FastAPI backend plus frontend for the DLS rig UI
- `shared/chart_generation`: shared report and PDF generation logic

## Repository Layout

```text
apps/
  central_hub/
  dls/
shared/
  chart_generation/
  frontend_assets/
  frontend_pages/
  static/
  utils/
tools/
```

Key locations:

- `apps/central_hub/backend/main.py`: Central Hub entry point
- `apps/dls/backend/main.py`: DLS entry point
- `shared/chart_generation/main.py`: chart/report generation entry point
- `shared/chart_generation/tests/`: chart-generation pytest suite
- `shared/shared_config.py`: shared rig and PLC configuration

## Quick Start

### 1. Create a virtual environment

PowerShell:

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Install Python dependencies

```powershell
python -m pip install -r requirements.txt
```

For Raspberry Pi camera deployments, install the Pi camera stack from the OS
packages as well:

```bash
sudo apt install python3-picamera2 python3-opencv
```

Central Hub's deploy page can do this automatically. After updating the hub,
use `Git Pull + Dependencies` for each rig; it runs
`apps/dls/deploy/sync_dependencies.sh`, installs missing Python and Pi camera
dependencies, and restarts `visualisation.service`.

### 3. Set `PYTHONPATH`

The repo expects the monorepo root to be importable so that `apps` and
`shared` resolve correctly.

PowerShell:

```powershell
$env:PYTHONPATH += ";."
```

Command Prompt:

```bat
set PYTHONPATH=%PYTHONPATH%;.
```

macOS/Linux:

```bash
export PYTHONPATH="${PYTHONPATH}:."
```

## Configuration

Shared rig and PLC settings live in `shared/shared_config.py`.

For Central Hub deploy-page access, create or update `apps/central_hub/.env`
with:

```env
DEPLOY_IP_WHITELIST=127.0.0.1,::1
```

This accepts a comma-separated list of exact IPs and/or CIDR ranges.

## Running the Applications

### Central Hub

```powershell
python -m apps.central_hub.backend.main
```

Default URL: `http://localhost:9000`

### DLS

```powershell
python -m apps.dls.backend.main
```

Default URL: `http://localhost:9000`

Both apps use the same default port, so if you need to run them together,
start one of them with `uvicorn` on a different port:

```powershell
uvicorn apps.central_hub.backend.main:app --host 0.0.0.0 --port 9001 --reload
```

```powershell
uvicorn apps.dls.backend.main:app --host 0.0.0.0 --port 9001 --reload
```

## Frontend Asset Build

Only needed when changing Tailwind-based frontend styling.

```powershell
cd tools/tailwind
npm install
npm run build
```

Use `npm run watch` while iterating on frontend markup.

## Testing

### Live Chart Smoke Tests

The chart-generation smoke suite lives under `shared/chart_generation/tests/`
and runs against live DAQ Station JSON/CSV data in a read-only way.

```powershell
python -m pytest -c shared/chart_generation/tests/pytest.ini -q
```

That command runs both:

- report generation smoke tests
- signature key-point regression tests for torque and hydraulic signatures

The signature regression baselines are currently pinned to the approved
chart-generation behavior from commit
`12b1e3353f62c55e8c9990f5045c90529d0880b8`.

That baseline now matches the current signature logic, so both the
signature-only suite and the full chart-generation suite should pass unless a
new change introduces a regression.

Discovery excludes:

- `Archive`
- `.bin`
- `Calibration`
- `Incoming`
- `Unknown`

By default the suite selects the newest successful `CSV` sample it can find
for each supported program handler and generates PDFs into pytest temp folders.
It does not edit or delete anything under:

`V:\Userdoc\R & D\DAQ_Station`

Useful options:

```powershell
$env:RND_LIVE_CASES_PER_PROGRAM = "2"
python -m pytest -c shared/chart_generation/tests/pytest.ini -q
```

```powershell
$env:RND_LIVE_INCLUDE_FAILED = "1"
python -m pytest -c shared/chart_generation/tests/pytest.ini -q
```

To run just the deeper signature regression suite:

```powershell
python -m pytest -c shared/chart_generation/tests/pytest.ini shared/chart_generation/tests/test_signature_key_points.py -q
```

If a signature regression test fails, pytest now writes a PDF artifact to
`shared/chart_generation/tests/_failure_artifacts/`. The PDF overlays the
expected key point and the current key point on the same cycle trace so the
difference is visible without digging through raw values by hand.

If a signature change is reviewed and accepted as the new correct behavior,
refresh the stored baseline in
`shared/chart_generation/tests/signature_regression_cases.py` and update the
commit reference in this README.

Current live-folder coverage gaps:

- `Atmospheric Cyclic`
- `Calibration`
- `Number of Turns & RPM Verification Test`

## Notes

- `shared/static/` is used for generated PDFs and related static output.
- `shared/chart_generation/` is shared infrastructure, so changes there affect
  more than one application path.
- `apps/dls/deploy/` contains deployment scripts used for DLS environments.

