#!/usr/bin/env bash
# Keeps HTTP + HTTPS uvicorn alive — used by launchd and --daemon.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1")"
CERT_DIR="$ROOT/certs"
KEY="$CERT_DIR/key.pem"
CERT="$CERT_DIR/cert.pem"

mkdir -p "$CERT_DIR"
if [[ ! -f "$KEY" || ! -f "$CERT" ]]; then
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 825 \
    -subj "/CN=$IP" \
    -addext "subjectAltName=IP:$IP,DNS:localhost,IP:127.0.0.1" 2>/dev/null || \
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 825 -subj "/CN=$IP"
fi

source "$ROOT/.venv/bin/activate"

kill_port() {
  local port=$1
  local pids
  pids=$(lsof -ti ":$port" 2>/dev/null || true)
  [[ -n "$pids" ]] && kill $pids 2>/dev/null || true
}

kill_port 8080
kill_port 8443
sleep 1

log() { echo "[$(date '+%H:%M:%S')] $*"; }

run_http() {
  while true; do
    log "HTTP :8080 starting"
    uvicorn server.main:app --host 0.0.0.0 --port 8080 >> /tmp/hisense-remote-http.log 2>&1 || true
    log "HTTP exited — restart in 2s"
    sleep 2
  done
}

run_https() {
  while true; do
    log "HTTPS :8443 starting"
    uvicorn server.main:app --host 0.0.0.0 --port 8443 \
      --ssl-keyfile "$KEY" --ssl-certfile "$CERT" \
      >> /tmp/hisense-remote-https.log 2>&1 || true
    log "HTTPS exited — restart in 2s"
    sleep 2
  done
}

run_http &
run_https &
log "Remote supervisor running (PID $$)"
log "HTTPS: https://${IP}:8443"

wait
