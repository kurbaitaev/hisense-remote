#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${DATA_DIR:-/data}"
mkdir -p "$DATA_DIR/certs"

if [[ ! -f "$DATA_DIR/config.json" ]]; then
  cp config.example.json "$DATA_DIR/config.json"
fi
ln -sf "$DATA_DIR/config.json" /app/config.json

if [[ -f "$DATA_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$DATA_DIR/.env"
  set +a
elif [[ -f /app/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /app/.env
  set +a
fi

KEY="$DATA_DIR/certs/key.pem"
CERT="$DATA_DIR/certs/cert.pem"
IP="${PUBLIC_HOST:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
IP="${IP:-localhost}"

if [[ ! -f "$KEY" || ! -f "$CERT" ]]; then
  echo "Generating HTTPS certificate for $IP ..."
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 825 \
    -subj "/CN=$IP" \
    -addext "subjectAltName=IP:$IP,DNS:localhost,IP:127.0.0.1" 2>/dev/null || \
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 825 \
    -subj "/CN=$IP"
fi

HTTP_PORT="${HTTP_PORT:-8080}"
HTTPS_PORT="${HTTPS_PORT:-8443}"

echo ""
echo "Remote URLs (same Wi‑Fi as the TV):"
echo "  HTTPS (mic):  https://${IP}:${HTTPS_PORT}"
echo "  HTTP:         http://${IP}:${HTTP_PORT}"
echo ""

uvicorn server.main:app --host 0.0.0.0 --port "$HTTP_PORT" &
HTTP_PID=$!
uvicorn server.main:app --host 0.0.0.0 --port "$HTTPS_PORT" \
  --ssl-keyfile "$KEY" --ssl-certfile "$CERT" &
HTTPS_PID=$!

trap 'kill $HTTP_PID $HTTPS_PID 2>/dev/null' EXIT INT TERM
wait -n $HTTP_PID $HTTPS_PID
