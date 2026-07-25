#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

DAEMON=false
for arg in "$@"; do
  [[ "$arg" == "--daemon" || "$arg" == "-d" ]] && DAEMON=true
done

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "192.168.0.10")"

if $DAEMON; then
  nohup "$ROOT/scripts/run-server.sh" >> /tmp/hisense-remote-supervisor.log 2>&1 &
  disown
  echo "Remote running in background (auto-restarts if it crashes)."
  echo "  HTTPS: https://${IP}:8443"
  echo "  Logs:  /tmp/hisense-remote-https.log"
  echo ""
  echo "Stop: kill \$(lsof -ti :8443)"
  exit 0
fi

exec "$ROOT/scripts/run-server.sh"