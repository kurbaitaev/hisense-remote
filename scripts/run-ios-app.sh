#!/usr/bin/env bash
# Build the native iPhone app (SSDP discovery like official Roku remotes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/mobile"

echo ""
echo "  TV Remote — native iPhone app"
echo "  ─────────────────────────────"
echo "  Discovery = SSDP (roku:ecp) + HTTP :8060"
echo "  Same method as official apps / open-source remotes."
echo ""

# Prefer full Xcode if present
if [[ -d /Applications/Xcode.app ]]; then
  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer 2>/dev/null || true
fi

echo "  Syncing UI…"
mkdir -p www
# App-focused UI (native SSDP)
# (www/index.html is the Capacitor shell UI)

npx cap sync ios

echo ""
echo "  Next in Xcode:"
echo "  1. Plug in iPhone"
echo "  2. Select your iPhone as run target"
echo "  3. Signing & Capabilities → your Apple ID team"
echo "  4. Run ▶"
echo "  5. On phone: Allow Local Network"
echo "  6. Tap Find my TV"
echo ""

if [[ -d /Applications/Xcode.app ]]; then
  open ios/App/App.xcodeproj
else
  echo "  Install Xcode from the Mac App Store, then re-run this script."
  npx cap open ios || true
fi
