#!/usr/bin/env bash
# OEL — Offline English Learning · start script
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"

if [ ! -d .venv ]; then
  echo "[run] creating venv..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if ! python -c "import fastapi" >/dev/null 2>&1; then
  echo "[run] installing dependencies..."
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
fi

echo "[run] starting OEL on http://127.0.0.1:${PORT}"
exec uvicorn server:app --host 127.0.0.1 --port "${PORT}"
