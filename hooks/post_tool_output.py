#!/usr/bin/env python3
"""Lossless-archive, conservative Claude Code test-output filter.

Only recognized verbose test-runner output is compacted. Unknown commands,
ambiguous output, structured data, diffs, stderr, secrets, and interrupted
runs are passed through unchanged. The original stdout is archived verbatim.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import tempfile
from datetime import datetime, timezone


def atomic_private_write(path: Path, text: str) -> None:
    """Write archive material atomically without following a destination symlink."""
    if path.is_symlink():
        raise OSError(f"Refusing to overwrite symlink: {path}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        if path.is_symlink():
            raise OSError(f"Archive destination became a symlink: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def minimum_chars() -> int:
    """Read the optional threshold defensively; bad settings must fail safe."""
    try:
        configured = int(os.environ.get("FIDELITYFLOW_HOOK_MIN_CHARS", "12000"))
    except (TypeError, ValueError):
        configured = 12000
    return max(1000, configured)


MIN_CHARS = minimum_chars()


def read_dedup_min_chars() -> int:
    """Minimum size for exact duplicate Read suppression."""
    try:
        configured = int(os.environ.get("FIDELITYFLOW_READ_DEDUP_MIN_CHARS", "8000"))
    except (TypeError, ValueError):
        configured = 8000
    return max(1000, configured)


READ_DEDUP_MIN_CHARS = read_dedup_min_chars()


def result_dedup_min_chars() -> int:
    """Minimum size for exact duplicate plain-text tool-result suppression."""
    try:
        configured = int(os.environ.get("FIDELITYFLOW_RESULT_DEDUP_MIN_CHARS", "8000"))
    except (TypeError, ValueError):
        configured = 8000
    return max(1000, configured)


RESULT_DEDUP_MIN_CHARS = result_dedup_min_chars()
TEXT_RESULT_TOOLS = {"Grep", "Glob", "WebSearch", "WebFetch", "NotebookRead"}
SECRET = re.compile(
    r"(?i)(-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\bsk-ant-[A-Za-z0-9_-]{12,}|\bgh[pousr]_[A-Za-z0-9]{20,}|"
    r"\bAKIA[0-9A-Z]{16}\b|\bxox[baprs]-[A-Za-z0-9-]{15,}|"
    r"(?:password|passwd|secret|api[_-]?key)\s*[:=]\s*\S{6,})"
)

PYTEST_SUMMARY = re.compile(r"^=+\s+.+\b(?:passed|failed|error|errors|skipped|xfailed|xpassed)\b.+\s+=+\s*$", re.I)
UNITTEST_SUMMARY = re.compile(r"^(?:Ran\s+\d+\s+tests?(?:\s+in\s+.+)?|OK(?:\s*\(.*\))?|FAILED\s*\(.*\))\s*$", re.I)
CARGO_RESULT = re.compile(r"^test result:\s+(?:ok|FAILED)\..*$", re.I)


def emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def fail_open() -> None:
    emit({})


def _tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return []


def classify_command(command: str) -> str | None:
    """Allow only test runners with a conservative, known output grammar."""
    tokens = [Path(t).name.casefold() if i == 0 else t.casefold() for i, t in enumerate(_tokens(command))]
    if not tokens:
        return None
    # Strip common wrappers while retaining the actual executable sequence.
    while tokens and tokens[0] in {"env", "sudo", "time", "uv", "poetry", "pipenv", "npm", "pnpm", "yarn"}:
        first = tokens.pop(0)
        if first in {"uv", "poetry", "pipenv"} and tokens:
            if tokens[0] in {"run", "exec", "shell"}:
                tokens.pop(0)
        elif first in {"npm", "pnpm", "yarn"}:
            # Package-manager scripts can wrap arbitrary commands and output
            # formats; keep them untouched unless a dedicated parser exists.
            return None
        elif first == "env":
            while tokens and ("=" in tokens[0] or tokens[0].startswith("-")):
                tokens.pop(0)
    if not tokens:
        return None
    if tokens[0] in {"pytest"} or (len(tokens) >= 2 and tokens[0] in {"python", "python3", "python3.10", "python3.11", "python3.12", "python3.13"} and tokens[1:3] == ["-m", "pytest"]):
        return "pytest"
    if len(tokens) >= 3 and tokens[0] in {"python", "python3", "python3.10", "python3.11", "python3.12", "python3.13"} and tokens[1:3] == ["-m", "unittest"]:
        return "unittest"
    if tokens[0] == "go" and len(tokens) >= 2 and tokens[1] == "test":
        return "go-test"
    if tokens[0] == "cargo" and len(tokens) >= 2 and tokens[1] == "test":
        return "cargo-test"
    return None


def unsafe_output(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped or SECRET.search(text):
        return True
    if "diff --git " in text or re.search(r"(?m)^(?:\+\+\+ |--- )", text):
        return True
    if stripped.startswith(("{", "[", "<?xml", "<!DOCTYPE")):
        try:
            json.loads(stripped)
            return True
        except (json.JSONDecodeError, TypeError):
            if stripped.startswith(("<?xml", "<!DOCTYPE")):
                return True
    # JSON Lines is not valid as one JSON document. Detect it separately so a
    # test command emitting structured events is never mistaken for plain text.
    nonempty = [line for line in text.splitlines() if line.strip()]
    sample_json = nonempty[:50]
    json_objects = 0
    for line in sample_json:
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, (dict, list)):
            json_objects += 1
    if len(sample_json) >= 3 and json_objects >= max(3, math.ceil(len(sample_json) * 0.8)):
        return True
    # Preserve data-shaped output, not just valid JSON.
    sample = [line for line in text.splitlines()[:30] if line.strip()]
    if len(sample) >= 5:
        comma_counts = [line.count(",") for line in sample]
        tab_counts = [line.count("\t") for line in sample]
        if min(comma_counts) >= 2 and max(comma_counts) - min(comma_counts) <= 1:
            return True
        if min(tab_counts) >= 2 and max(tab_counts) - min(tab_counts) <= 1:
            return True
    return False


def _render(lines: list[str], kept: list[tuple[int, str]], label: str) -> tuple[str, int] | None:
    if len(kept) >= len(lines) * 0.88:
        return None
    result = [f"FIDELITYFLOW: {label}; {len(lines) - len(kept)} repetitive/pass lines omitted."]
    previous = -1
    for index, line in kept:
        if previous >= 0 and index > previous + 1:
            result.append(f"… [{index - previous - 1} lines omitted; original is archived verbatim] …")
        result.append(line)
        previous = index
    return "\n".join(result) + "\n", len(kept)


def compact_pytest(text: str) -> tuple[str, int] | None:
    lines = text.splitlines()
    summaries = [line.strip() for line in lines if PYTEST_SUMMARY.match(line.strip())]
    if not summaries or re.search(r"\b[1-9]\d*\s+(?:failed|error|errors)\b", " ".join(summaries), re.I):
        return None  # failing runs must remain fully visible
    # Only discard explicit successful test rows and pure progress rows.
    # All failure sections, tracebacks, warnings, setup output and summaries remain.
    kept = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^\S.*\s+PASSED(?:\s+\[[^]]+\])?$", stripped, re.I):
            continue
        if re.match(r"^\S.*\s+SKIPPED(?:\s+\[[^]]+\])?$", stripped, re.I):
            # Skips can explain coverage; do not remove them.
            kept.append((i, line))
            continue
        if stripped and re.fullmatch(r"[.sFxX]+", stripped) and len(stripped) >= 20:
            continue
        kept.append((i, line))
    return _render(lines, kept, "recognized pytest output")


def compact_unittest(text: str) -> tuple[str, int] | None:
    lines = text.splitlines()
    summaries = [line.strip() for line in lines if UNITTEST_SUMMARY.match(line.strip())]
    if not summaries or any(line.upper().startswith("FAILED") for line in summaries):
        return None  # failing runs must remain fully visible
    kept = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # unittest's standard verbose success rows end in '... ok'.
        if re.search(r"\.\.\.\s+ok$", stripped, re.I):
            continue
        kept.append((i, line))
    return _render(lines, kept, "recognized unittest output")


def compact_go(text: str) -> tuple[str, int] | None:
    lines = text.splitlines()
    if any(line.startswith("FAIL\t") or line.startswith("FAIL ") for line in lines):
        return None
    if not any(re.match(r"^ok\s+\S+\s+\S+\s*$", line) for line in lines):
        return None
    kept = []
    for i, line in enumerate(lines):
        if re.match(r"^ok\s+\S+\s+\S+\s*$", line):
            continue
        kept.append((i, line))
    return _render(lines, kept, "recognized go test output")


def compact_cargo(text: str) -> tuple[str, int] | None:
    lines = text.splitlines()
    summaries = [line.strip() for line in lines if re.match(r"^test result:", line.strip(), re.I)]
    if (not summaries
            or any(re.match(r"^test result:\s+FAILED\.", line, re.I) for line in summaries)
            or not any(CARGO_RESULT.match(line) for line in summaries)):
        return None  # a failed or mixed run is not rewritten
    kept = []
    for i, line in enumerate(lines):
        if re.match(r"^test\s+.+\s+\.\.\.\s+ok$", line.strip(), re.I):
            continue
        kept.append((i, line))
    return _render(lines, kept, "recognized cargo test output")


def compact(text: str, kind: str) -> tuple[str, int] | None:
    return {
        "pytest": compact_pytest,
        "unittest": compact_unittest,
        "go-test": compact_go,
        "cargo-test": compact_cargo,
    }.get(kind, lambda _: None)(text)


def _session_read_root(event: dict) -> Path | None:
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    # Keep only non-content hashes in the user's Claude directory. This
    # session-level parent lets lifecycle events clear every agent conservatively.
    session_key = hashlib.sha256(session_id.encode("utf-8", errors="replace")).hexdigest()
    claude_dir = Path.home() / ".claude"
    fidelity_dir = claude_dir / "fidelityflow"
    dedup_root = fidelity_dir / "read-dedup"
    session_root = dedup_root / session_key
    for path in (claude_dir, fidelity_dir, dedup_root, session_root):
        if path.is_symlink():
            return None
    return session_root


def _session_read_dir(event: dict) -> Path | None:
    session_root = _session_read_root(event)
    if session_root is None:
        return None
    # Separate agents so a subagent's Read is never assumed to exist in the main
    # agent's context. agent_id is opaque and is stored only as a SHA-256 key.
    agent_id = str(event.get("agent_id") or "main")
    agent_key = hashlib.sha256(agent_id.encode("utf-8", errors="replace")).hexdigest()
    agent_dir = session_root / agent_key
    return None if agent_dir.is_symlink() else agent_dir


def clear_session_reads(event: dict) -> None:
    session_root = _session_read_root(event)
    if session_root is None or not session_root.exists():
        return
    # Clear every agent's markers for this session. PreCompact events may not
    # identify an agent, so over-clearing is safer than suppressing a Read whose
    # first full result might have been discarded by compaction.
    shutil.rmtree(session_root)



MAX_COMPACTION_INSTRUCTIONS = 10000
MAX_SESSION_BRIEF_CHARS = 4500
MAX_CUSTOM_COMPACTION_CHARS = 1500


def _safe_session_brief(event: dict) -> str:
    """Read an explicitly user-maintained brief from the current project only."""
    cwd_value = event.get("cwd")
    if not isinstance(cwd_value, str) or not cwd_value.strip():
        return ""
    try:
        cwd = Path(cwd_value).expanduser().resolve()
        fidelity_dir = cwd / ".fidelityflow"
        brief_path = fidelity_dir / "session-brief.md"
        if (
            fidelity_dir.is_symlink()
            or not fidelity_dir.is_dir()
            or brief_path.is_symlink()
            or not brief_path.is_file()
        ):
            return ""
        if brief_path.stat().st_size > MAX_SESSION_BRIEF_CHARS * 4:
            return ""
        content = brief_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, RuntimeError):
        return ""
    content = "".join(
        char for char in content
        if char in "\n\r\t" or ord(char) >= 32
    ).strip()
    if len(content) > MAX_SESSION_BRIEF_CHARS:
        content = content[:MAX_SESSION_BRIEF_CHARS].rstrip() + "\n[SESSION BRIEF TRUNCATED]"
    return content


def build_precompact_instructions(event: dict) -> str:
    """Return compact, quality-preserving instructions for Claude Code compaction."""
    lines = [
        "FIDELITYFLOW — CONTEXT COMPACTION POLICY",
        "",
        "Create a concise, accurate handoff for the next assistant turn. Optimize for task continuity, not for preserving the transcript.",
        "",
        "PRESERVE, IN THIS ORDER:",
        "1. The user's current objective and explicit success criteria.",
        "2. Hard constraints, scope boundaries, preferences, and decisions the user explicitly made.",
        "3. Verified project facts, architecture choices, important assumptions, and unresolved contradictions.",
        "4. Exact file paths, symbols, identifiers, API names, versions, numeric values, URLs, commands, and error text needed to continue.",
        "5. Files changed, changes made, tests actually run, exact outcomes, and any failures not yet fixed.",
        "6. Remaining work, blockers, and the next concrete action.",
        "",
        "OMIT:",
        "- Repeated tool output, duplicated file contents, routine progress chatter, and irrelevant earlier tasks.",
        "- Suggestions that the user did not approve; keep suggestions separate from decisions.",
        "- Details already represented accurately by a current verified project file or the user-maintained brief, unless a path or reason is needed.",
        "",
        "ACCURACY RULES:",
        "- Do not invent missing facts, test results, approvals, or completion claims.",
        "- Distinguish verified facts from assumptions and unresolved questions.",
        "- Prefer the latest explicit user instruction when earlier discussion conflicts.",
        "- Preserve warnings, failed tests, security concerns, and important limitations; never compress them into a false success.",
        "- Keep source references so omitted detail can be retrieved when necessary.",
        "",
        "Use compact headings: Goal, Constraints, Decisions, Current State, Verification, Open Work. Keep the handoff as short as possible without losing any item required to continue safely.",
    ]
    custom = event.get("custom_instructions")
    if isinstance(custom, str) and custom.strip():
        custom = custom.strip()[:MAX_CUSTOM_COMPACTION_CHARS]
        lines.extend(["", "USER-SUPPLIED COMPACTION INSTRUCTIONS (also follow):", custom])
    brief = _safe_session_brief(event)
    if brief:
        lines.extend([
            "",
            "USER-MAINTAINED PROJECT SESSION BRIEF (reference only; newer explicit conversation statements take precedence):",
            brief,
        ])
    output = "\n".join(lines).strip()
    return output[:MAX_COMPACTION_INSTRUCTIONS]


def emit_precompact_instructions(event: dict) -> None:
    """Write plain text to stdout; Claude Code uses it as compaction guidance."""
    clear_session_reads(event)
    sys.stdout.write(build_precompact_instructions(event))

def _atomic_marker_state(marker: Path, state: str) -> bool:
    """Atomically replace a fixed marker state; never store source content."""
    if state not in {"seen", "suppressed"} or marker.is_symlink():
        return False
    temporary = marker.with_name(f".{marker.name}.{os.getpid()}.tmp")
    if temporary.exists() or temporary.is_symlink():
        return False
    fd = None
    try:
        fd = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            fd = None
            stream.write(f"fidelityflow-read-dedup-v2:{state}\n")
        if marker.is_symlink():
            return False
        os.replace(temporary, marker)
        return True
    except OSError:
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def handle_read_dedup(event: dict) -> dict | None:
    response = event.get("tool_response")
    tool_input = event.get("tool_input") or {}
    session_dir = _session_read_dir(event)
    if (not isinstance(response, str) or len(response) < READ_DEDUP_MIN_CHARS
            or not isinstance(tool_input, dict) or session_dir is None):
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        return None
    # Include path, requested range, agent identity and exact returned bytes.
    # Same content from a different range or source is not a duplicate.
    request_identity = {
        "file_path": os.path.normcase(os.path.normpath(file_path)),
        "offset": tool_input.get("offset"),
        "limit": tool_input.get("limit"),
        "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
    }
    marker_name = hashlib.sha256(
        json.dumps(request_identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest() + ".seen"
    try:
        session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if session_dir.is_symlink():
            return None
        if os.name != "nt":
            try:
                session_dir.chmod(0o700)
            except OSError:
                pass
        marker = session_dir / marker_name
        if marker.is_symlink():
            return None
        try:
            fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                state = marker.read_text(encoding="ascii").strip()
            except (OSError, UnicodeError):
                return None
            # v1 markers are treated as a first, fully delivered read during
            # upgrade. Suppression is alternating: after one skipped duplicate,
            # the next identical request is passed through as a recovery read.
            if state == "fidelityflow-read-dedup-v1":
                state = "fidelityflow-read-dedup-v2:seen"
            if state == "fidelityflow-read-dedup-v2:suppressed":
                _atomic_marker_state(marker, "seen")
                return None
            if state != "fidelityflow-read-dedup-v2:seen":
                return None
            if not _atomic_marker_state(marker, "suppressed"):
                return None  # fail open if the state cannot be updated safely
            range_text = []
            if tool_input.get("offset") is not None:
                range_text.append(f"offset={tool_input.get('offset')}")
            if tool_input.get("limit") is not None:
                range_text.append(f"limit={tool_input.get('limit')}")
            requested_range = ", ".join(range_text) if range_text else "default range"
            note = (
                "FIDELITYFLOW: One exact duplicate Read suppressed. The same file path, requested range, "
                "and byte-identical result were already returned in this session's current context epoch. "
                f"Source: {file_path} ({requested_range}). No content was summarized or deleted. "
                "The next identical Read is deliberately passed through in full as a recovery safeguard. "
                "A new range or changed file result is always returned normally."
            )
            return {"hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedToolOutput": note,
            }}
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write("fidelityflow-read-dedup-v2:seen\n")
        return None
    except OSError:
        return None



def _plain_text_payload(response: object) -> tuple[str, str] | None:
    """Return text plus payload kind only for safe, plain-text response shapes."""
    if isinstance(response, str):
        return response, "string"
    if not isinstance(response, dict):
        return None
    if response.get("isError") is True:
        return None
    if set(response) - {"content", "isError"}:
        return None
    content = response.get("content")
    if not isinstance(content, list) or not content:
        return None
    text_parts = []
    for block in content:
        if (
            not isinstance(block, dict)
            or set(block) - {"type", "text"}
            or block.get("type") != "text"
            or not isinstance(block.get("text"), str)
        ):
            return None
        text_parts.append(block["text"])
    return "\n".join(text_parts), "mcp-content"


def _restore_payload_shape(response: object, note: str, payload_kind: str) -> object:
    if payload_kind == "string":
        return note
    assert isinstance(response, dict)
    updated = {"content": [{"type": "text", "text": note}]}
    if "isError" in response:
        updated["isError"] = False
    return updated


def handle_text_result_dedup(event: dict) -> dict | None:
    """Suppress one exact repeated text result while preserving MCP result shape."""
    tool_name = event.get("tool_name")
    if not isinstance(tool_name, str):
        return None
    if tool_name not in TEXT_RESULT_TOOLS and not tool_name.startswith("mcp__"):
        return None

    parsed = _plain_text_payload(event.get("tool_response"))
    if parsed is None:
        return None
    response_text, payload_kind = parsed
    if (
        len(response_text) < RESULT_DEDUP_MIN_CHARS
        or unsafe_output(response_text)
    ):
        return None

    tool_input = event.get("tool_input") or {}
    session_dir = _session_read_dir(event)
    if not isinstance(tool_input, dict) or session_dir is None:
        return None
    try:
        input_bytes = json.dumps(
            tool_input, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        return None

    request_identity = {
        "tool_name": tool_name,
        "tool_input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "response_sha256": hashlib.sha256(response_text.encode("utf-8")).hexdigest(),
        "payload_kind": payload_kind,
    }
    marker_name = hashlib.sha256(
        json.dumps(
            request_identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest() + ".seen"

    try:
        session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if session_dir.is_symlink():
            return None
        if os.name != "nt":
            try:
                session_dir.chmod(0o700)
            except OSError:
                pass
        marker = session_dir / marker_name
        if marker.is_symlink():
            return None
        try:
            fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                state = marker.read_text(encoding="ascii").strip()
            except (OSError, UnicodeError):
                return None
            if state == "fidelityflow-read-dedup-v2:seen":
                if not _atomic_marker_state(marker, "suppressed"):
                    return None
                note = (
                    f"FIDELITYFLOW: One exact duplicate {tool_name} result suppressed. "
                    "The same tool input and byte-identical text result were already returned "
                    "in this session's current context epoch. No summary or semantic rewrite "
                    "was generated. The next identical request is passed through in full "
                    "as a recovery safeguard."
                )
                updated = _restore_payload_shape(
                    event.get("tool_response"), note, payload_kind
                )
                return {"hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "updatedToolOutput": updated,
                }}
            if state == "fidelityflow-read-dedup-v2:suppressed":
                _atomic_marker_state(marker, "seen")
                return None
            return None
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write("fidelityflow-read-dedup-v2:seen\n")
        return None
    except OSError:
        return None

def main() -> None:
    try:
        event = json.load(sys.stdin)
        event_name = event.get("hook_event_name")
        if event_name == "PreCompact":
            return emit_precompact_instructions(event)
        if event_name == "SessionEnd" or (
            event_name == "SessionStart" and event.get("source") == "clear"
        ):
            clear_session_reads(event)
            return fail_open()
        if event_name != "PostToolUse":
            return fail_open()
        if event.get("tool_name") == "Read":
            read_result = handle_read_dedup(event)
            if read_result is not None:
                return emit(read_result)
            return fail_open()
        tool_name = event.get("tool_name")
        if tool_name in TEXT_RESULT_TOOLS or (
            isinstance(tool_name, str) and tool_name.startswith("mcp__")
        ):
            result = handle_text_result_dedup(event)
            if result is not None:
                return emit(result)
            return fail_open()
        if tool_name != "Bash":
            return fail_open()
        response = event.get("tool_response")
        tool_input = event.get("tool_input") or {}
        if not isinstance(response, dict):
            return fail_open()
        stdout = response.get("stdout")
        if not isinstance(stdout, str) or len(stdout) < MIN_CHARS:
            return fail_open()
        if response.get("stderr") or response.get("interrupted") or response.get("isImage"):
            return fail_open()
        command = str(tool_input.get("command", ""))
        kind = classify_command(command)
        if kind is None or unsafe_output(stdout):
            return fail_open()
        result = compact(stdout, kind)
        if result is None:
            return fail_open()
        reduced, retained_lines = result
        if len(reduced) >= len(stdout) * 0.88:
            return fail_open()

        cwd = Path(event.get("cwd") or os.getcwd()).resolve()
        fidelity_root = cwd / ".fidelityflow"
        archive_root = fidelity_root / "archive"
        if fidelity_root.is_symlink() or archive_root.is_symlink():
            return fail_open()
        archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            try:
                archive_root.chmod(0o700)
            except OSError:
                pass
        raw_hash = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
        tool_id = str(event.get("tool_use_id") or raw_hash[:16])
        ref = re.sub(r"[^A-Za-z0-9._-]+", "_", tool_id)[:100] or raw_hash[:16]
        archive_file = archive_root / f"{ref}.txt"
        metadata_file = archive_root / f"{ref}.json"
        if archive_file.is_symlink() or metadata_file.is_symlink():
            return fail_open()
        if archive_file.exists() and hashlib.sha256(archive_file.read_bytes()).hexdigest() != raw_hash:
            ref = f"{ref}-{raw_hash[:8]}"
            archive_file = archive_root / f"{ref}.txt"
            metadata_file = archive_root / f"{ref}.json"
        if archive_file.is_symlink() or metadata_file.is_symlink():
            return fail_open()

        atomic_private_write(archive_file, stdout)
        metadata = {
            "schema_version": 1,
            "archive_ref": ref,
            "sha256": raw_hash,
            "processor": kind,
            "source": "Claude Code Bash tool stdout",
            # Store only the parser family, not the shell command: command lines
            # can contain credentials or other sensitive arguments.
            "command_kind": kind,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "original_chars": len(stdout),
            "original_lines": len(stdout.splitlines()),
            "retained_lines": retained_lines,
            "archive_file": str(archive_file),
        }
        atomic_private_write(metadata_file, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        if os.name != "nt":
            for private_file in (archive_file, metadata_file):
                try:
                    private_file.chmod(0o600)
                except OSError:
                    pass
        note = (
            f"FIDELITYFLOW: Replaced only recognized repetitive test-runner output. "
            f"The exact original is archived at {archive_file} (ref: {ref}, SHA-256: {raw_hash}). "
            f"Retrieve the full output before relying on omitted lines: "
            f"python <path-to-fidelityflow.py> show-archive --ref {ref}"
        )
        updated = dict(response)
        updated["stdout"] = note + "\n\n" + reduced
        emit({"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated}})
    except Exception:
        fail_open()


if __name__ == "__main__":
    main()
