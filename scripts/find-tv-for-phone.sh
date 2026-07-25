#!/usr/bin/env bash
# First-time / no remote: find Roku on Wi‑Fi and open the phone remote with QR.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LAN="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")"
FIND="http://${LAN}:8080/find"
REMOTE="http://${LAN}:8080/remote"

echo ""
echo "  First time / no physical remote"
echo "  ───────────────────────────────"
echo "  1. Power the TV ON (button on the TV)"
echo "  2. This computer on the same Wi‑Fi"
echo "  3. Phone will open a QR (or use the remote link)"
echo ""
echo "  Finder (QR for phone):  ${FIND}"
echo "  Remote on this Wi‑Fi:   ${REMOTE}"
echo "    ↑ uses server search — works better than the public website alone"
echo ""

if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
fi

if ! lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "  Starting server…"
  nohup python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8080 \
    >> /tmp/hisense-remote-find.log 2>&1 &
  sleep 2
fi

if command -v open >/dev/null 2>&1; then
  open "${FIND}" 2>/dev/null || true
fi
