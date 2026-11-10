#!/usr/bin/env bash
# OEL — Offline English Learning · start script
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8765}"
RELOAD="${RELOAD:-0}"

# ── pastikan tidak ada instance lama yang masih memegang port ────────────────
port_busy() {
  # connect, bukan bind: TIME_WAIT tidak dianggap "terpakai"
  python3 - "$1" <<'PY'
import socket, sys
port = int(sys.argv[1])
s = socket.socket()
s.settimeout(0.5)
try:
    s.connect(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    s.close()
sys.exit(0)
PY
}

free_port() {
  local pids
  if command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -ti tcp:"${PORT}" 2>/dev/null || true)"
  elif command -v fuser >/dev/null 2>&1; then
    pids="$(fuser -n tcp "${PORT}" 2>/dev/null | tr -s ' ' '\n' || true)"
  else
    pids=""
  fi
  pids="$(echo "${pids}" | tr -s ' \n' ' ' | xargs || true)"
  if [ -n "${pids}" ]; then
    echo "[run] port ${PORT} dipakai PID ${pids} — dihentikan dulu…"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      port_busy "${PORT}" || return 0
      sleep 0.5
    done
    # shellcheck disable=SC2086
    kill -9 ${pids} 2>/dev/null || true
    sleep 0.5
  fi
}

if port_busy "${PORT}"; then
  free_port
fi
if port_busy "${PORT}"; then
  echo "[run] port ${PORT} masih dipakai proses lain. Coba PORT=9000 ./run.sh" >&2
  exit 1
fi

# ── venv + dependency ───────────────────────────────────────────────────────
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

echo "[run] app dir : $(pwd)"
echo "[run] static  : $(pwd)/static  (HTML/CSS/JS dibaca langsung dari disk, tanpa cache)"
echo "[run] cek versi: curl -s http://127.0.0.1:${PORT}/api/version"
echo "[run] starting OEL on http://127.0.0.1:${PORT}"
if [ "${RELOAD}" = "1" ]; then
  exec uvicorn server:app --host 127.0.0.1 --port "${PORT}" --reload
else
  exec uvicorn server:app --host 127.0.0.1 --port "${PORT}"
fi
