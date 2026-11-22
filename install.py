#!/usr/bin/env python3
"""Install the FidelityFlow Skill and optional Claude Code hooks."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parent
SKILL_SOURCE = ROOT / "skills" / "fidelityflow"
HOOK_SOURCE = ROOT / "hooks"
PACKAGE_SOURCE = ROOT / "fidelityflow"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache")


def _command(script: Path) -> str:
    return f"{json.dumps(sys.executable)} {json.dumps(str(script.resolve()))}"


def _add_hook(hooks: dict[str, Any], event: str, matcher: str | None,
              command: str, timeout: int = 3) -> None:
    entries = hooks.setdefault(event, [])
    if not isinstance(entries, list):
        raise ValueError(f"settings hooks.{event} must be a list")
    entry = next((item for item in entries
                  if isinstance(item, dict)
                  and (item.get("matcher") if "matcher" in item else None) == matcher), None)
    if entry is None:
        entry = {"hooks": []}
        if matcher is not None:
            entry["matcher"] = matcher
        entries.append(entry)
    commands = entry.setdefault("hooks", [])
    if not isinstance(commands, list):
        raise ValueError(f"settings hooks.{event} entries must contain a hooks list")
    if not any(isinstance(item, dict) and item.get("command") == command for item in commands):
        commands.append({"type": "command", "command": command, "timeout": timeout})


def merge_hook(settings: dict[str, Any], command: str,
               learning_command: str | None = None,
               session_start_command: str | None = None) -> tuple[dict[str, Any], bool]:
    """Return settings with idempotent FidelityFlow hook registrations."""
    if not isinstance(settings, dict):
        raise ValueError("Claude settings must be a JSON object")
    merged = json.loads(json.dumps(settings))
    hooks = merged.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("settings hooks must be an object")
    before = json.dumps(merged, sort_keys=True)
    _add_hook(hooks, "PostToolUse", "Read|Bash", command, 8)
    _add_hook(hooks, "PreCompact", None, command)
    _add_hook(hooks, "SessionEnd", None, command)
    _add_hook(hooks, "SessionStart", "clear", command)
    if learning_command:
        _add_hook(hooks, "PostToolUse", "Bash", learning_command)
    if session_start_command:
        _add_hook(hooks, "SessionStart", None, session_start_command)
    return merged, before != json.dumps(merged, sort_keys=True)


def _read_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    hooks = value.get("hooks", {})
    if hooks is not None and not isinstance(hooks, dict):
        raise ValueError(f"{path}: 'hooks' must be an object")
    return value


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"Required source directory is missing: {source}")
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=IGNORE)


def _write_settings(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        if backup.exists():
            backup = path.with_suffix(path.suffix + f".{os.getpid()}.bak")
        shutil.copy2(path, backup)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("user", "project"), default="user")
    parser.add_argument("--enable-output-hook", action="store_true")
    parser.add_argument("--hook-only", action="store_true")
    args = parser.parse_args(argv)
    if args.hook_only and not args.enable_output_hook:
        parser.error("--hook-only requires --enable-output-hook")
    if args.scope == "project" and args.enable_output_hook:
        parser.error("machine-specific hooks can only be installed with --scope user")

    base = Path.home() / ".claude" if args.scope == "user" else Path.cwd() / ".claude"
    settings_path = base / "settings.json"
    merged_settings = None

    # Validate settings before copying any files to avoid partial installation.
    if args.enable_output_hook:
        try:
            existing = _read_settings(settings_path)
            hook_dir = base / "hooks" / "fidelityflow"
            merged_settings, _ = merge_hook(
                existing,
                _command(hook_dir / "post_tool_output.py"),
                _command(hook_dir / "post_tool_use.py"),
                _command(hook_dir / "session_start.py"),
            )
        except (OSError, ValueError) as exc:
            print(f"Install error: {exc}; no files were changed.", file=sys.stderr)
            return 3

    try:
        if not args.hook_only:
            _copy_tree(SKILL_SOURCE, base / "skills" / "fidelityflow")
        if args.enable_output_hook:
            hook_dir = base / "hooks" / "fidelityflow"
            _copy_tree(HOOK_SOURCE, hook_dir)
            _copy_tree(PACKAGE_SOURCE, hook_dir / "runtime" / "fidelityflow")
            _write_settings(settings_path, merged_settings or {})
    except (OSError, shutil.Error) as exc:
        print(f"Install error: {exc}", file=sys.stderr)
        return 3

    if args.hook_only:
        print(f"FidelityFlow hooks installed under {base / 'hooks' / 'fidelityflow'}.")
    elif args.enable_output_hook:
        print(f"FidelityFlow Skill and hooks installed under {base}.")
    else:
        print(f"FidelityFlow Skill installed under {base / 'skills' / 'fidelityflow'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
