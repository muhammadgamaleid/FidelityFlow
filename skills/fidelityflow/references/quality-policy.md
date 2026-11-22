# Quality policy and token accounting

## Non-negotiable invariant

An optimization is valid only when it reduces real model usage or cost while preserving the information required for the task. A shorter string is not proof of a saving, and fewer input tokens are not proof of equal quality.

If omitted material may matter, preserve a reversible original and reliable retrieval path, or do not transform it automatically.

## Separate context size from cost

Track these fields separately whenever Claude exposes them:
- input_tokens
- cache_creation_input_tokens
- cache_read_input_tokens
- output_tokens
- thinking-token usage, when available

Prompt caching may reduce the billed cost of repeated input, but cached content can still occupy the model's context window. Do not count cache reads as zero context. Do not report cache hits as token reductions.

Claude subscription usage limits and Claude API billing are different. A subscription usage indicator is not a per-token invoice. Convert API usage to money only with the applicable model, region, cache, and current price schedule.

## What counts as net savings

A fair comparison includes:
- All input, cache-creation, cache-read, output, and thinking tokens exposed by the platform.
- Skill and Plugin instruction overhead.
- Additional tool calls, retries, and recovery reads.
- Any model-assisted preprocessing or embedding calls.
- Latency and local compute, where relevant.
- Task quality and whether original information remains recoverable.

Use the same model, task, source files, tool configuration, cache state, and evaluation rubric for baseline and optimized runs. Compare FidelityFlow against both native Claude behavior and a concise-instructions baseline.

## Quality dimensions

| Dimension | What to verify |
|---|---|
| Task correctness | The requested task is completed accurately |
| Evidence fidelity | Numbers, claims, citations, warnings, and provenance remain correct |
| Retrieval recall | Relevant source passages can still be found |
| Structural fidelity | Code, tables, formulas, types, and document structure remain usable |
| Error preservation | Failures, tracebacks, warnings, and counterexamples are not hidden |
| Reversibility | Omitted content can be recovered from the original |
| Output completeness | Requested length, detail, examples, and format are respected |

## Safe and unsafe transformations

| Workload | Potentially safe | Never remove automatically |
|---|---|---|
| Large documents | Exact duplicate passages; targeted retrieval with page references | Unique evidence, footnotes, caveats, tables, clauses, figures needed by the task |
| Code | Exact repeated reads; narrow successful test boilerplate | Code required for edits, diffs, interfaces, test failures, warnings |
| Search results | Duplicate results with the same canonical source and content | Unique sources, citations, dates, conflicting evidence |
| MCP/JSON | Unrequested fields only when the consumer contract explicitly permits projection | Required fields, types, IDs, errors, pagination state, provenance |
| Spreadsheets | User-approved irrelevant columns or ranges | Values, formulas, units, hidden assumptions, sheet relationships |
| Images/PDFs | Duplicate images or irrelevant pages only after task-aware validation | Visual details, labels, axes, legends, spatial relationships |

## Fail-open rules

Leave original content unchanged when:
- The format or tool response is unknown.
- The result contains errors, diffs, structured data, or likely secrets and no safe parser exists.
- The source cannot be recovered.
- A visual or numerical interpretation is required but only lossy text extraction is available.
- The requested output is intentionally exhaustive.
- Estimated savings do not exceed optimization overhead.

## Measurement tools and current limits

benchmarks/read_claude_usage.py reads token usage fields available in local Claude Code JSONL transcripts and deduplicates repeated message IDs. It reports available fields; it does not invent unavailable values.

The current project does not have reliable per-message token telemetry for Claude.ai web chats. It also does not yet publish a validated end-to-end savings percentage. Character counts, lines removed, cache hits, and archive sizes are diagnostic data, not token-savings measurements.

Do not claim "same quality" or a fixed percentage until controlled A/B evaluations support the claim.
