#!/usr/bin/env python3
"""Read actual token-usage fields from Claude Code JSONL transcripts."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from typing import Any

USAGE_FIELDS = (
    "input_tokens", "cache_creation_input_tokens",
    "cache_read_input_tokens", "output_tokens",
)


def extract_usage(row: dict[str, Any]) -> tuple[str | None, dict[str, int]] | None:
    message = row.get("message")
    message = message if isinstance(message, dict) else {}
    usage = message.get("usage")
    if not isinstance(usage, dict):
        usage = row.get("usage")
    if not isinstance(usage, dict):
        return None
    message_id = message.get("id") or row.get("uuid")
    values: dict[str, int] = {}
    for field in USAGE_FIELDS:
        value = usage.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        values[field] = int(value)
    return (str(message_id) if message_id is not None else None, values)


def read_transcript(path: Path) -> tuple[dict[str, int], int, int]:
    totals = {field: 0 for field in USAGE_FIELDS}
    seen: set[str] = set()
    messages = malformed = 0
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                print(f"warning: skipped invalid JSON on line {line_number}", file=sys.stderr)
                continue
            if not isinstance(row, dict):
                continue
            result = extract_usage(row)
            if result is None:
                continue
            message_id, usage = result
            if message_id is not None:
                if message_id in seen:
                    continue
                seen.add(message_id)
            for field, value in usage.items():
                totals[field] += value
            messages += 1
    return totals, messages, malformed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transcript", type=Path, help="Claude Code JSONL transcript path")
    args = parser.parse_args(argv)
    path = args.transcript.expanduser()
    if not path.is_file():
        parser.error(f"transcript not found: {path}")
    try:
        totals, messages, malformed = read_transcript(path)
    except OSError as exc:
        parser.exit(2, f"Could not read transcript: {exc}\n")
    print(f"messages: {messages}")
    for field in USAGE_FIELDS:
        print(f"{field}: {totals[field]}")
    total = (totals["input_tokens"] + totals["cache_creation_input_tokens"]
             + totals["cache_read_input_tokens"])
    print(f"input_total_including_cache_reads: {total}")
    if malformed:
        print(f"malformed_lines: {malformed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
