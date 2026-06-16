#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "192.168.0.10")"
CERT_DIR="$ROOT/certs"
KEY="$CERT_DIR/key.pem"
CERT="$CERT_DIR/cert.pem"

mkdir -p "$CERT_DIR"
if [[ ! -f "$KEY" || ! -f "$CERT" ]]; then
  echo "Generating self-signed HTTPS certificate for $IP ..."
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY" -out "$CERT" -days 825 \
    -subj "/CN=$IP" \
    -addext "subjectAltName=IP:$IP,DNS:localhost,IP:127.0.0.1" 2>/dev/null
fi

source .venv/bin/activate

echo ""
echo "Remote URLs:"
echo "  HTTPS (mic works):  https://$IP:8443"
echo "  HTTP  (no mic):     http://$IP:8080"
echo ""
echo "On iPhone Safari, use HTTPS. Accept the certificate warning once."
echo ""

nohup uvicorn server.main:app --host 0.0.0.0 --port 8080 > /tmp/hisense-remote-http.log 2>&1 &
HTTP_PID=$!

nohup uvicorn server.main:app \
  --host 0.0.0.0 --port 8443 \
  --ssl-keyfile "$KEY" \
  --ssl-certfile "$CERT" > /tmp/hisense-remote-https.log 2>&1 &
HTTPS_PID=$!

echo "HTTP  PID: $HTTP_PID"
echo "HTTPS PID: $HTTPS_PID"
echo "Logs: /tmp/hisense-remote-http.log /tmp/hisense-remote-https.log"

trap 'kill $HTTP_PID $HTTPS_PID 2>/dev/null' EXIT INT TERM
while kill -0 $HTTP_PID 2>/dev/null || kill -0 $HTTPS_PID 2>/dev/null; do
  sleep 2
done