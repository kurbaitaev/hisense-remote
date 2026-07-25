#!/usr/bin/env bash
# Free Roku remote for everyone — print the public link.
set -euo pipefail

LINK="https://kurbaitaev.github.io/hisense-remote/"
REPO="https://github.com/kurbaitaev/hisense-remote"

echo ""
echo "  TV Remote — free Roku remote (no App Store)"
echo "  ───────────────────────────────────────────"
echo "  ${LINK}"
echo ""
echo "  Repo: ${REPO}"
echo ""
echo "  Anyone opens that URL on their phone,"
echo "  same Wi‑Fi as THEIR TV, and uses the remote."
echo "  ───────────────────────────────────────────"
echo ""

if command -v open >/dev/null 2>&1; then
  open "${LINK}" 2>/dev/null || true
fi
