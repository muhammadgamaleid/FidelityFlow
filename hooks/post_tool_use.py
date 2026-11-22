#!/usr/bin/env python3
"""Learn only allowlisted successful Bash test/build/lint commands."""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Intentionally narrow. Add patterns only with tests and clear evidence semantics.
PATTERNS = [
    ("test.command", re.compile(r"(^|[;&|]\s*)(pytest(?:\s|$)|python\s+-m\s+unittest(?:\s|$)|npm\s+(?:run\s+)?test(?:\s|$)|pnpm\s+(?:run\s+)?test(?:\s|$)|yarn\s+test(?:\s|$)|go\s+test(?:\s|$)|cargo\s+test(?:\s|$))")),
    ("build.command", re.compile(r"(^|[;&|]\s*)(npm\s+run\s+build|pnpm\s+build|yarn\s+build|cargo\s+build|go\s+build)(?:\s|$)")),
    ("lint.command", re.compile(r"(^|[;&|]\s*)(ruff\s+check|eslint(?:\s|$)|prettier\s+--check|mypy(?:\s|$)|pyright(?:\s|$))(?:\s|$)")),
]
SENSITIVE = re.compile(r"(?i)(--password|--token|--api[-_]?key|\.env(?:\.|\s|$)|secret\s*=|token\s*=|api[_-]?key\s*=)")


def main() -> int:
    try:
        event = json.load(sys.stdin)
        if event.get("hook_event_name") != "PostToolUse" or event.get("tool_name") != "Bash":
            return 0
        session = str(event.get("session_id") or "").strip()
        cwd = str(event.get("cwd") or Path.cwd())
        command = str((event.get("tool_input") or {}).get("command") or "").strip()
        if not session or not command or len(command) > 360 or SENSITIVE.search(command):
            return 0
        matched_key = next((key for key, pattern in PATTERNS if pattern.search(command)), None)
        if not matched_key:
            return 0
        # PostToolUse is emitted after a successful tool call. Never infer from output text.
        evidence = f"Claude Code PostToolUse: allowlisted Bash command completed successfully in session {session}."
        subprocess.run([
            sys.executable, "-m", "fidelityflow_learning", "--root", cwd,
            "observe", "--key", matched_key, "--value", command,
            "--session", session, "--source", "claude-code-posttooluse",
            "--evidence", evidence,
        ], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL, timeout=2, check=False)
    except Exception:
        # Fail open: memory collection is optional and must not affect tool execution.
        return 0
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
