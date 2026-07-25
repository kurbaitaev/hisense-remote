#!/usr/bin/env bash
# One-time setup on Raspberry Pi (or any always-on Linux box on your home Wi‑Fi).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="${DATA_DIR:-/var/lib/hisense-remote}"

echo "=== Hisense Remote — Pi setup ==="
echo ""

if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker…"
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER" 2>/dev/null || true
  echo "Log out and back in so docker runs without sudo, then re-run this script."
  exit 0
fi

sudo mkdir -p "$DATA_DIR/certs"
if [[ ! -f "$DATA_DIR/config.json" ]]; then
  echo "Creating $DATA_DIR/config.json"
  sudo tee "$DATA_DIR/config.json" >/dev/null << 'EOF'
{
  "host": "192.168.0.154",
  "platform": "roku",
  "installed_apps": ["netflix", "paramount", "youtube", "prime"]
}
EOF
  echo ">>> Edit TV IP: sudo nano $DATA_DIR/config.json"
fi

if [[ -f "$ROOT/.env" && ! -f "$DATA_DIR/.env" ]]; then
  sudo cp "$ROOT/.env" "$DATA_DIR/.env"
fi

cd "$ROOT"
sudo docker compose build
sudo docker compose down 2>/dev/null || true

# Bind host data dir so config survives rebuilds
export DATA_DIR
sudo -E docker compose up -d

PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "Done. Remote is running on the Pi (Mac not needed)."
echo ""
echo "  Phone URL (same Wi‑Fi):  https://${PI_IP:-<pi-ip>}:8443"
echo "  Add to Home Screen in Safari."
echo ""
echo "  Logs:   sudo docker compose logs -f"
echo "  Stop:   sudo docker compose down"
echo "  Config: sudo nano $DATA_DIR/config.json"
echo ""
echo "Optional — access from anywhere (Tailscale on Pi):"
echo "  curl -fsSL https://tailscale.com/install.sh | sh"
echo "  sudo tailscale up"
echo "  sudo tailscale serve --bg --https=443 http://127.0.0.1:8443"
