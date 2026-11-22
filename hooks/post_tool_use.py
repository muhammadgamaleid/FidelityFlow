#!/usr/bin/env python3
"""Learn only allowlisted successful Bash test/build/lint commands."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "runtime"
if (RUNTIME / "fidelityflow").is_dir():
    sys.path.insert(0, str(RUNTIME))
else:
    sys.path.insert(0, str(HERE.parent))

from fidelityflow.learning.store import LearningStore  # noqa: E402

PATTERNS = [
    ("test.command", re.compile(
        r"(^|[;&|]\s*)(pytest(?:\s|$)|python\s+-m\s+unittest(?:\s|$)|"
        r"npm\s+(?:run\s+)?test(?:\s|$)|pnpm\s+(?:run\s+)?test(?:\s|$)|"
        r"yarn\s+test(?:\s|$)|go\s+test(?:\s|$)|cargo\s+test(?:\s|$))"
    )),
    ("build.command", re.compile(
        r"(^|[;&|]\s*)(npm\s+run\s+build|pnpm\s+build|yarn\s+build|"
        r"cargo\s+build|go\s+build)(?:\s|$)"
    )),
    ("lint.command", re.compile(
        r"(^|[;&|]\s*)(ruff\s+check|eslint(?:\s|$)|prettier\s+--check|"
        r"mypy(?:\s|$)|pyright(?:\s|$))(?:\s|$)"
    )),
]

# Commands containing credentials are discarded entirely rather than relying
# on redaction to recognize every possible secret format.
SENSITIVE = re.compile(
    r"(?i)(--(?:password|token|api[-_]?key|secret|authorization|database[-_]?url|connection[-_]?string)\b|"
    r"\b[A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|API_KEY|DATABASE_URL|PRIVATE_KEY)\s*=|"
    r"(?:https?|postgres(?:ql)?|mysql)://[^/\s:@]+:[^@\s]+@|"
    r"\.env(?:\.|\s|$))"
)


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

        # PostToolUse is emitted after a successful tool call. The hook stores
        # the command only after credential-bearing forms have been rejected;
        # LearningStore applies a second, independent redaction layer.
        evidence = "Claude Code PostToolUse: allowlisted Bash command completed successfully."
        with LearningStore(root=cwd) as store:
            store.observe(
                matched_key,
                command,
                session,
                "claude-code-posttooluse",
                evidence,
            )
    except Exception:
        # Optional learning must never block the user's tool workflow.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
