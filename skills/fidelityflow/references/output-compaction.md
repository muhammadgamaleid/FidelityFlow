# Exact duplicate tool-result suppression and reversible test-output compaction

## A. Exact duplicate Read suppression

The optional Claude Code PostToolUse hook handles large Read results. It stores a SHA-256 marker, not file contents, scoped to the Claude session and agent. Suppression requires all of the following:

- The event is a successful PostToolUse for Read and the result is a plain string of at least 8,000 characters by default (FIDELITYFLOW_READ_DEDUP_MIN_CHARS changes the threshold; values below 1,000 are clamped).
- The same normalized file path and requested offset/limit are present.
- The returned result bytes are identical (SHA-256 match).
- The same marker has already been recorded in the current context epoch.

The first full read is passed through unchanged. One later exact duplicate may be replaced with a small notice. The next identical request is deliberately passed through in full as a recovery safeguard. A changed result, a different range, a different agent, or an unrecognized response is passed through.

## B. Exact duplicate text-result suppression

The same optional hook can suppress one byte-identical repeat from these plain-text tool families:
- Grep and Glob
- WebSearch and WebFetch
- NotebookRead
- MCP tool names beginning with mcp__ when the result is a plain string or a standard text-only MCP content object

The default threshold is 8,000 characters. FIDELITYFLOW_RESULT_DEDUP_MIN_CHARS changes it; values below 1,000 are clamped.

Suppression requires:
1. A successful PostToolUse event with a session and agent identity.
2. An allowlisted text-only tool, or an MCP result with only a content array of text blocks (and optional isError=false).
3. The exact tool name, canonical JSON tool input, and response text hash to match.
4. The first full result to have been delivered in the current context epoch.

For standard MCP text responses, FidelityFlow returns the same outer response shape with a single text block containing the notice. Responses with structuredContent, non-text blocks, image blocks, errors, or unknown top-level fields are unchanged. It does not project fields, truncate content, summarize, or rewrite the result.

The first result passes through. One exact duplicate may be suppressed. The next identical request passes through in full as recovery. PreCompact clears every agent's markers because the first result may no longer be present after summarization.

## C. Reversible successful test-output compaction

The optional hook also handles only successful, completed Bash output from recognized test-runner command families:
- pytest (including python -m pytest)
- python -m unittest (when verbose output is routed to stdout, for example 2>&1)
- go test
- cargo test

It removes only narrowly recognized successful test rows. Failure details, tracebacks, warnings, skipped rows, summary lines, and unclassified lines remain model-visible.

All of these conditions must hold:
1. The event is PostToolUse for Bash.
2. stdout is at least 12,000 characters by default. FIDELITYFLOW_HOOK_MIN_CHARS adjusts the threshold; values below 1,000 are clamped.
3. stderr is empty and the command was not interrupted.
4. The command belongs to a supported test-runner family.
5. A recognized final success summary is present.
6. The output is not structured JSON/XML, tabular data, a diff, or text matching common secret patterns.
7. The deterministic transformation reduces the output by at least 12%.

Any uncertainty or exception fails open.

## Recovery

For Bash compaction, the exact UTF-8 stdout received in the hook event is stored verbatim at .fidelityflow/archive/<ref>.txt; metadata includes a SHA-256 digest. On POSIX systems the hook attempts owner-only permissions (0700 directory and 0600 files); on Windows it relies on inherited filesystem ACLs. This is not encryption.

~~~bash
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" show-archive --ref <ref>
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" show-archive --ref <ref> --lines 40:100
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" search-archive --ref <ref> --query "AssertionError"
~~~

For exact duplicate result suppression, no original result is archived: the first full result is already in the current context. Marker files contain only hashed identities and fixed state labels, not source text.

## Cost boundary

PostToolUse.updatedToolOutput changes what Claude receives after a tool has executed. It does not undo the tool execution, reduce external search/database/API costs, or remove content already present in the context. It prevents only the second identical text result from being added; the next identical call is passed through as a recovery safeguard. Test-output compaction also does not reduce command execution cost.

The hooks are opt-in and Claude Code-specific; Claude.ai Skills cannot install them. Unknown, structured, failing, or non-text result shapes are passed through unchanged.

## Privacy boundary

The Bash hook archives received stdout locally. This is not encryption. Avoid enabling output compaction in sensitive repositories unless local output retention is acceptable. Result dedup marker files store hashes only. All hooks fail open if they encounter ambiguity, symlinks, malformed events, or write failures.
