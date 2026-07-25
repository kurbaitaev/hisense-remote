#!/usr/bin/env bash
# Build & run the phone app (real Local Network + SSDP discovery — works like official remotes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "Syncing web UI → mobile app…"
mkdir -p mobile/www
cp web/index.html web/manifest.webmanifest mobile/www/

cd mobile
npx cap sync ios

echo ""
echo "  Opening Xcode…"
echo "  1. Connect your iPhone with a cable"
echo "  2. Select your iPhone as the run target"
echo "  3. Press ▶ Run"
echo "  4. On the phone: Trust the developer if asked"
echo "  5. Open TV Remote → tap Allow Local Network → Find my TV"
echo ""
echo "  The app finds Rokus with SSDP (same method as official apps)."
echo ""

npx cap open ios
