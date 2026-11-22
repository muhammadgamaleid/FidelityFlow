# Quality policy and token accounting

## Non-negotiable invariant

Optimization may remove redundant context, but must not reduce information necessary to satisfy the task. When a transformation omits material, preserve a reversible original or do not apply it automatically.

## Task-aware policy

| Workload | Safe optimization | Do not remove |
|---|---|---|
| Simple Q&A | Repeated preambles and restatements | Necessary definitions, reasoning, caveats |
| Research | Duplicate excerpts and unrelated sources | Evidence, counterevidence, citations, uncertainty |
| Books / long-form writing | Repeated ideas across drafts when meaning is unchanged | Requested length, argument, examples, voice, nuance |
| Code | Repeated reads and recognized successful test boilerplate | Code, diffs, stack traces, warnings, failures, interfaces, tests |
| Data | Explicitly irrelevant columns after user approval | Rows, formulas, values, units, types, provenance |
| Document edits | Redundant boilerplate when meaning is preserved | Meaning, structure, required clauses, citations |

## Never infer savings from shorter text alone

Report these separately when the platform exposes them:

- `input_tokens`
- `cache_creation_input_tokens`
- `cache_read_input_tokens`
- `output_tokens`
- any available thinking-token telemetry

Cached reads are generally billed differently from uncached input, but they still occupy model context. A prompt cache can reduce billed input cost without reducing the context-window footprint. Output compaction can reduce output tokens only where the task permits it; it must not change the requested deliverable. FidelityFlow never applies a global output length cap.

FidelityFlow's local CLI reports hashes, characters, lines, and cache hits; it does not invent model token counts. `benchmarks/read_claude_usage.py` reads Claude Code transcript usage fields when available. It does not estimate missing or Claude.ai web-chat telemetry.

## When not to optimize

- The transformation could hide a relevant fact.
- The full original is unavailable for retrieval.
- The requested output is intentionally long or exhaustive.
- A data or code structure is not understood well enough to transform safely.
- Tool output is ambiguous or contains errors, stderr, structured data, diffs, or likely secrets.
- Skill overhead exceeds likely savings for a tiny one-off task.

## Measure net benefit

A fair evaluation includes skill instruction overhead, actual input/output/cache token usage, extra tool calls, retries, latency, and task quality. Compare against both a no-skill baseline and a simple "answer concisely" control. For tool-output filters, count tokens with the same Claude model/tokenizer where possible; `characters / 4` is only a rough proxy.
