#!/usr/bin/env bash
# Export latest Cursor chat for this project and open Grok with context.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TRANSCRIPT="${1:-}"

if [[ -z "$TRANSCRIPT" ]]; then
  # newest hisense-remote transcript in Cursor projects
  TRANSCRIPT="$(find "$HOME/.cursor/projects" -path "*agent-transcripts*/*.jsonl" 2>/dev/null \
    | while read -r f; do
        if grep -q "hisense-remote\|Roku\|TV remote" "$f" 2>/dev/null; then
          echo "$f"
        fi
      done \
    | xargs ls -t 2>/dev/null | head -1)"
fi

if [[ -z "$TRANSCRIPT" || ! -f "$TRANSCRIPT" ]]; then
  echo "Usage: $0 [path/to/chat.jsonl]"
  echo "Or drop the .jsonl path from:"
  echo "  ~/.cursor/projects/*/agent-transcripts/*/*.jsonl"
  exit 1
fi

OUT="$ROOT/.cursor-grok-context.md"
python3 "$ROOT/scripts/cursor-to-grok.py" "$TRANSCRIPT" -o "$OUT"

echo "Exported → $OUT"
echo "Starting Grok in $ROOT ..."
cd "$ROOT"
# --prompt-file is single-turn only and cannot combine with a positional PROMPT.
# Interactive session: point Grok at the exported context file.
exec grok "Continue this hisense-remote project. Read the full Cursor chat context from .cursor-grok-context.md first, then pick up where we left off."
