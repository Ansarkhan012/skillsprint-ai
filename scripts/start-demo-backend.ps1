# Run in a dedicated terminal. Ctrl+C stops Uvicorn and its reload worker.
$ErrorActionPreference = 'Stop'
$demoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $demoRoot
if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is already in use. Stop the previous backend with Ctrl+C first.'
}
# For the demo, the durable root .env owns these three nonsecret choices.
# Remove inherited overrides only; never change or print credential variables.
Remove-Item Env:AI_PROVIDER, Env:DEEPSEEK_MODEL, Env:GENERATION_CONTENT_ONLY -ErrorAction SilentlyContinue
& "$demoRoot\.venv\Scripts\python.exe" -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000 --reload
