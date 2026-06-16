#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHANNEL_DIR="$ROOT/roku-channel/tv-voice-bridge"
OUT_DIR="$ROOT/dist"
OUT_ZIP="$OUT_DIR/tv-voice-bridge.zip"

mkdir -p "$OUT_DIR"
rm -f "$OUT_ZIP"

cd "$CHANNEL_DIR"
zip -r "$OUT_ZIP" manifest source components images

echo "Packaged: $OUT_ZIP"
ls -lh "$OUT_ZIP"
unzip -l "$OUT_ZIP" | head -20