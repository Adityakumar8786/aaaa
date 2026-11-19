#!/usr/bin/env bash
# One-shot Ollama setup for the benchmark (Linux / macOS / WSL / Git-Bash).
# Run from the project root:  bash scripts/setup_ollama.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama not found. Install it from https://ollama.com/download and re-run." >&2; exit 1
fi
HOST="${OLLAMA_HOST:-http://localhost:11434}"
case "$HOST" in http*) ;; *) HOST="http://$HOST" ;; esac
if ! curl -fsS "$HOST/api/tags" >/dev/null 2>&1; then
  echo "Ollama server not reachable at $HOST."
  echo "Start it in another terminal with:  ollama serve   (the desktop app starts it automatically)" >&2; exit 1
fi
PY="${PYTHON:-python}"; command -v "$PY" >/dev/null 2>&1 || PY=python3

# Models are read from config.ollama.yaml, pulled if missing, then smoke-tested.
"$PY" -m nl2sql -c config.ollama.yaml ollama-setup
"$PY" -m nl2sql -c config.ollama.yaml check --ping
echo
echo "Ready. Next:  $PY -m nl2sql -c config.ollama.yaml test --config full_schema"