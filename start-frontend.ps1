# Starts the web app on port 3000.
$ErrorActionPreference = "Stop"
Set-Location -Path (Join-Path $PSScriptRoot "frontend")
npm run dev
