# Starts the API on port 8000 with reload.
$ErrorActionPreference = "Stop"
Set-Location -Path (Join-Path $PSScriptRoot "backend")
python -m uvicorn app.main:app --reload --port 8000
