#!/usr/bin/env bash
# Help share the *friend* remote (their TV), not your living-room guest link.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ""
echo "  Share with friends — THEIR TVs, not yours"
echo "  ──────────────────────────────────────────"
echo ""
echo "  What friends get: web/ (phone → their Roku on their Wi‑Fi)"
echo "  They never touch your Mac or your TV."
echo ""
echo "  Deploy once (free Cloudflare Pages):"
echo ""
echo "    cd $ROOT"
echo "    npx wrangler pages deploy web --project-name=roku-remote"
echo ""
echo "  Then text them the URL, e.g. https://roku-remote.pages.dev"
echo ""
echo "  Full guide: $ROOT/SHARE.md"
echo "  Local demo of the friend app: http://127.0.0.1:8080/static/friend-remote.html"
echo "  ──────────────────────────────────────────"
echo ""

if command -v open >/dev/null 2>&1; then
  if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
    open "http://127.0.0.1:8080/share" 2>/dev/null || true
  else
    open "$ROOT/SHARE.md" 2>/dev/null || true
  fi
fi
