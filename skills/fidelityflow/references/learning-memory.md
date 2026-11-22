# Evidence-backed Project Memory (v0.3.1)

## Design Goals

- Learn only stable, reusable repository facts
- Keep facts project-scoped and local
- Promote automatically only after independent-session evidence
- Keep contradictions unresolved until a human confirms the current value
- Recall a small number of compact facts, never raw transcripts
- Never use learned facts to shorten user-requested deliverables

## Storage and Privacy

The default SQLite database is `~/.fidelityflow/learning.sqlite3`; override it with `FIDELITYFLOW_HOME` or `--db`. Each repository is scoped by a SHA-256 digest of its resolved local root. The original path is not used as a global key.

Evidence is limited to 500 characters and values to 360 characters. Common token, password, bearer, and email patterns are redacted before storage. This is a safety filter, not a guarantee that all sensitive data can be detected; do not submit secrets.

No network access, embeddings, external model calls, or telemetry are used. The module uses only Python's standard library. SQLite WAL mode supports concurrent readers. The database is local and is not automatically synchronized between devices or Claude.ai.

## Learning State Machine

```
candidate → active → retired
```

- An observation records a key/value, session identifier, source, short evidence, and timestamp.
- A fact becomes active after the same value is supported in two distinct session IDs, provided no competing value has been observed for that key.
- If different values are observed for the same key, neither is auto-promoted. A human can confirm one; confirmation retires other active values.
- One session cannot count twice, even with different evidence strings.
- Retired facts are not recalled. They remain available for audit until explicitly forgotten.

## CLI

```bash
fflearn --root . recall
fflearn --root . observe --key test.command --value "pytest -q" --session "$CLAUDE_SESSION_ID" --source bash --evidence "Ran pytest -q; exit code 0."
fflearn --root . candidates
fflearn --root . confirm --key test.command --value "pytest -q"
fflearn --root . retire --key test.command
fflearn --root . forget
fflearn --root . stats
```

## Claude.ai Limitation

Claude.ai Skills run in a hosted environment and cannot transparently share a local SQLite database with Claude Code. This module does not claim cross-product synchronization. In Claude.ai, use the Skill's evidence discipline with Project Knowledge or a user-provided compact project-facts file. Do not pretend that local learning is available in a hosted chat.

## Claude Code Hooks

This release includes opt-in, fail-open hooks:

- `hooks/session_start.py` injects up to eight active facts through SessionStart `hookSpecificOutput.additionalContext`.
- `hooks/post_tool_use.py` observes only allowlisted Bash test/build/lint commands after successful PostToolUse events. It uses Claude Code's stable `session_id`; it never manufactures an ID. It does not read command output or store transcripts.

Copy the entries from `hooks/hooks.example.json` into the existing settings file; do not replace the whole settings file. Change both script paths to absolute paths on your machine. The scripts use the standard Python library and have short timeouts. They fail open, and you can remove the two hook entries to disable learning.

The observer is deliberately narrow: it does not learn arbitrary project instructions, file contents, shell aliases, or MCP tool behavior. Add new command families only with explicit allowlist rules and tests. The two-session threshold is still required before a fact is injected.

## Resolution semantics (schema v2)

- facts.required_sessions records the promotion threshold selected on the first observation of a particular key/value. Later observations cannot silently lower or raise that threshold.
- resolutions records the human-selected value and the latest observation ID considered when the decision was made.
- Repeating the selected value after confirmation keeps it active.
- A newly inserted conflicting observation after the decision removes the resolution and returns active facts for that key to candidate review. Conflicts that existed before the human decision remain historical evidence and do not immediately undo that decision.
- Confirming a value retires all competing fact rows for the key. A new conflict can reopen review, but no value is automatically selected.

Existing schema-v1 databases are migrated to schema v2 when opened. The migration adds the promotion-threshold field and resolution table without deleting observations or learned facts.
