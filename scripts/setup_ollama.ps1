# One-shot Ollama setup for the benchmark (Windows PowerShell).
# Run from the project root:  powershell -ExecutionPolicy Bypass -File scripts\setup_ollama.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "ollama not found. Install it from https://ollama.com/download and re-run." -ForegroundColor Red; exit 1
}
$hostUrl = if ($env:OLLAMA_HOST) { $env:OLLAMA_HOST } else { "http://localhost:11434" }
if ($hostUrl -notmatch "^https?://") { $hostUrl = "http://$hostUrl" }
try { Invoke-RestMethod "$hostUrl/api/tags" | Out-Null }
catch {
    Write-Host "Ollama server not reachable at $hostUrl." -ForegroundColor Red
    Write-Host "Start the Ollama app, or run 'ollama serve' in another terminal."; exit 1
}

# Models are read from config.ollama.yaml, pulled if missing, then smoke-tested.
python -m nl2sql -c config.ollama.yaml ollama-setup
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
python -m nl2sql -c config.ollama.yaml check --ping
Write-Host ""
Write-Host "Ready. Next:  python -m nl2sql -c config.ollama.yaml test --config full_schema"