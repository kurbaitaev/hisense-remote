#!/usr/bin/env bash
# No physical remote: find Roku on Wi‑Fi and open a QR page for your phone.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")"
FIND_URL="http://${IP}:8080/find"

echo ""
echo "  Find TV (no remote needed)"
echo "  ──────────────────────────"
echo "  1. Power the TV on (button on the set)"
echo "  2. This computer must be on the same Wi‑Fi"
echo "  3. Phone will scan a QR code to open the remote"
echo ""

# Start HTTP server if not running
if ! lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "  Starting server on port 8080…"
  if [[ -f "$ROOT/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT/.venv/bin/activate"
  fi
  nohup python3 -m uvicorn server.main:app --host 0.0.0.0 --port 8080 \
    >> /tmp/hisense-remote-find.log 2>&1 &
  sleep 2
fi

echo "  Open on this computer:"
echo "    ${FIND_URL}"
echo ""
echo "  Phone: scan the QR on that page (or open the link shown)."
echo ""

if command -v open >/dev/null 2>&1; then
  open "${FIND_URL}" 2>/dev/null || true
fi
