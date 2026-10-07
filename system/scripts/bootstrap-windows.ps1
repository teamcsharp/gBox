# Install / update the gBox Windows node: local venv (never on the share), Python deps, gbox setup checks.
# The code runs from this checkout (Spark share or a GitHub clone); only the venv lives in %LOCALAPPDATA%.
param([string]$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath)
$ErrorActionPreference = "Stop"
$Venv = Join-Path $env:LOCALAPPDATA "gbox\venv"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
}
if (-not (Test-Path "$Venv\Scripts\python.exe")) { python -m venv $Venv }
& "$Venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install -q "fastapi>=0.110" "uvicorn>=0.29" "pydantic>=2.6" "httpx>=0.27" "opencv-contrib-python-headless>=4.8"   # opencv: overlay swap tracker
$env:PYTHONPATH = $Repo
# -P: never import gbox from the current directory (only from the share)
& "$Venv\Scripts\python.exe" -P -m gbox --config "$Repo\gbox.toml" setup
Write-Output "venv: $Venv"
