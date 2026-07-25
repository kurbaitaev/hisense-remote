#!/usr/bin/env bash
# Print install instructions for the free phone remote (no mic).
set -euo pipefail

LINK="https://kurbaitaev.github.io/hisense-remote/"

echo ""
echo "  Free TV Remote — install on your phone"
echo "  ──────────────────────────────────────"
echo "  ${LINK}"
echo ""
echo "  1. Same Wi‑Fi as the TV"
echo "  2. TV: Control by mobile apps → Enabled"
echo "  3. Open the link → connect"
echo "  4. Install on phone:"
echo "       iPhone:  Share → Add to Home Screen"
echo "       Android: ⋮ → Add to Home screen"
echo "  5. Open TV Remote from the home screen"
echo ""
echo "  No App Store. No microphone required."
echo "  Voice is optional (home server) — not needed for the remote."
echo "  ──────────────────────────────────────"
echo ""

if command -v open >/dev/null 2>&1; then
  open "${LINK}" 2>/dev/null || true
fi
