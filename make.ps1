# Windows shim for the Makefile targets (Windows has no `make`).
#   .\make.ps1 up
#   .\make.ps1 initdb
#   .\make.ps1 check-phase1
param([Parameter(Mandatory = $true)][string]$Target)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Py = Join-Path $Root ".venv\Scripts\python.exe"

function Need-Venv {
    if (-not (Test-Path $Py)) { throw "No venv found. Run: .\make.ps1 install" }
}

switch ($Target) {
    "up"       { docker compose up -d; docker compose ps }
    "down"     { docker compose down }
    "install"  {
        python -m venv (Join-Path $Root ".venv")
        & $Py -m pip install --upgrade pip
        & $Py -m pip install -r (Join-Path $Root "backend\requirements.txt")
    }
    "initdb"   { Need-Venv; & $Py (Join-Path $Root "scripts\init_db.py") --force }
    "backfill" { Need-Venv; & $Py (Join-Path $Root "scripts\backfill.py") }
    "train"    { Need-Venv; & $Py (Join-Path $Root "scripts\train.py") --from 2022-01-01 --promote }
    "backtest" { Need-Venv; & $Py (Join-Path $Root "scripts\backtest.py") }
    "seed"     { Need-Venv; & $Py (Join-Path $Root "scripts\seed_demo_data.py") }
    "api"      { Need-Venv; Push-Location (Join-Path $Root "backend"); try { & $Py -m uvicorn api.main:app --reload --port 8000 } finally { Pop-Location } }
    "web"      { Push-Location (Join-Path $Root "frontend"); try { npm run dev } finally { Pop-Location } }
    "test"     { Need-Venv; Push-Location (Join-Path $Root "backend"); try { & $Py -m pytest } finally { Pop-Location } }
    default {
        if ($Target -match "^check-phase(\d+)$") {
            $n = $Matches[1]
            if ($n -eq "10") { Push-Location (Join-Path $Root "frontend"); try { npm run build } finally { Pop-Location }; break }
            Need-Venv
            $file = Get-ChildItem (Join-Path $Root "backend\tests") -Filter "test_phase$n`_*.py" | Select-Object -First 1
            if (-not $file) { throw "No test file for phase $n yet." }
            Push-Location (Join-Path $Root "backend")
            try { & $Py -m pytest "tests/$($file.Name)" -v } finally { Pop-Location }
        } else {
            throw "Unknown target: $Target"
        }
    }
}
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
