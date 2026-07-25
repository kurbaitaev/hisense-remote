#!/usr/bin/env python3
"""Convert a Cursor agent transcript (.jsonl) to Markdown for Grok."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def strip_tags(text: str) -> str:
    text = re.sub(r"<user_query>\s*", "", text)
    text = re.sub(r"\s*</user_query>", "", text)
    text = re.sub(r"\[REDACTED\]", "", text)
    return text.strip()


def role_label(role: str) -> str:
    return "You" if role == "user" else "Cursor"


def extract_text(message: dict) -> str:
    parts: list[str] = []
    for block in message.get("content", []):
        if block.get("type") == "text" and block.get("text"):
            parts.append(strip_tags(block["text"]))
    return "\n\n".join(p for p in parts if p)


def convert(jsonl_path: Path) -> str:
    lines: list[str] = [
        "# Cursor chat export",
        "",
        f"Source: `{jsonl_path}`",
        "",
        "---",
        "",
    ]
    for raw in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        role = row.get("role", "")
        message = row.get("message") or {}
        text = extract_text(message)
        if not text:
            continue
        lines.append(f"## {role_label(role)}")
        lines.append("")
        lines.append(text)
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Export Cursor chat JSONL to Markdown")
    p.add_argument("jsonl", type=Path, help="Path to .jsonl transcript")
    p.add_argument("-o", "--output", type=Path, help="Output .md path (default: stdout)")
    args = p.parse_args()
    md = convert(args.jsonl)
    if args.output:
        args.output.write_text(md, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    main()
