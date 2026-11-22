# Exact Read deduplication and reversible test-output compaction

## A. Exact duplicate Read suppression

The optional Claude Code `PostToolUse` hook also handles large `Read` results. It stores a SHA-256 marker, not file contents, scoped to the Claude session and agent. Suppression requires all of the following:

- The event is a successful `PostToolUse` for `Read` and the result is a plain string of at least 8,000 characters by default (`FIDELITYFLOW_READ_DEDUP_MIN_CHARS` changes the threshold; values below 1,000 are clamped).
- The same normalized file path and requested `offset`/`limit` are present.
- The returned result bytes are identical (SHA-256 match).
- The same marker has already been recorded in the current context epoch.

The first full read is passed through unchanged. One later exact duplicate may be replaced with a small notice pointing back to the earlier result. The next identical request is deliberately passed through in full as a recovery safeguard; this alternation prevents repeated suppression when Claude requests the source again. A changed result, a different range, a different agent, or an unrecognized response is passed through. `PreCompact` clears every agent's markers for the session before the context is summarized; `SessionEnd` and `SessionStart` with source `clear` also clear them. This is exact duplicate suppression, not summarization or lossy compression.

The marker directory is `~/.claude/fidelityflow/read-dedup/`, partitioned by SHA-256 hashes of session and agent identifiers. It contains only SHA-256-derived filenames and a small state marker (`seen` or `suppressed`), not file paths or source text. Each agent has a separate subdirectory; lifecycle cleanup removes the whole session directory. The directory is local, unencrypted, and may be removed safely; removing it simply disables dedup until markers are recreated.

## B. Reversible test-output compaction

The optional Claude Code hook handles only successful, completed `Bash` output from recognized test-runner command families. Failed command executions are delivered through a different hook event and are not rewritten:

- `pytest` (including `python -m pytest`)
- `python -m unittest` (when verbose output is explicitly routed to stdout, for example `2>&1`)
- `go test`
- `cargo test`

It does not attempt generic summarization. It removes only narrowly recognized successful test rows. Failure details, traceback lines, warnings, skipped-test rows, summary lines, and all other unclassified lines remain in the model-visible output.

## Conditions for compaction

All of the following must hold:

1. The event is `PostToolUse` for `Bash`.
2. `stdout` is at least 12,000 characters by default. Set `FIDELITYFLOW_HOOK_MIN_CHARS` to adjust the threshold; values below 1,000 are clamped to 1,000.
3. `stderr` is empty and the command was not interrupted.
4. The command belongs to a supported test-runner family.
5. A recognized final success summary is present; nonzero failure/error summaries pass through unchanged.
6. The output is not structured JSON/XML, tabular data, a diff, or text matching common secret patterns.
7. The deterministic transformation reduces the output by at least 12%.

Any uncertainty or exception fails open and leaves the original tool output unchanged.

## Recovery

The exact UTF-8 stdout text received in the Claude Code hook event is stored verbatim at `.fidelityflow/archive/<ref>.txt`; metadata includes a SHA-256 digest. On POSIX systems the hook attempts owner-only permissions (`0700` directory and `0600` files); on Windows it relies on inherited filesystem ACLs. This is not encryption. Use:

```bash
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" show-archive --ref <ref>
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" show-archive --ref <ref> --lines 40:100
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" search-archive --ref <ref> --query "AssertionError"
```

An archive pointer is a retrieval handle, not proof that omitted material is irrelevant. Retrieve the complete original whenever omitted output could affect a decision.

## Cost boundary

`PostToolUse.updatedToolOutput` changes what Claude receives after a tool has executed. Exact Read dedup saves only alternating repeated identical model-visible tool results; it does not reduce the first read or the underlying file I/O. Test-output compaction saves only model-visible successful boilerplate rows. Neither transformation reduces command execution cost. The hook is opt-in and Claude Code-specific; Claude.ai Skills cannot install it.

## Privacy boundary

The Bash hook archives the received stdout text locally and is intentionally conservative. Secret-pattern checks cover common token/key formats but cannot detect every secret. Keep output compaction disabled in sensitive repositories unless local output retention is acceptable. The Read dedup marker store contains hashes and fixed state markers only. Do not combine this Read rewrite with another `PostToolUse` hook that rewrites Read output; matching hooks run in parallel and their replacements can conflict. The `.fidelityflow/` directory is gitignored by this repository's default `.gitignore`; the marker store is under the user's `~/.claude/` directory.
