# Claude consumption optimization: product strategy

## Product promise

FidelityFlow aims to reduce avoidable Claude usage and cost while preserving task quality. It is not a generic text compressor and does not promise that every task will use fewer tokens.

The product must optimize the full workflow, not only the final prompt:
1. Source files and attachments.
2. Conversation and project context.
3. Tool definitions and tool results.
4. Repeated reads, searches, and retries.
5. Assistant output and thinking usage, when observable.
6. Caching and platform-specific usage accounting.

The central rule is: **measure the real cost and verify result quality before claiming a saving.**

## Platform strategy

### Claude.ai

Skills are available on Free and paid Claude plans when Code execution and file creation is enabled. Plugins are currently paid-plan features. The Free-compatible upload path is therefore the Skill archive.

Claude.ai Skills cannot intercept the platform's initial attachment ingestion/parser pipeline or modify all conversation history. The web release should focus on:
- Skill execution over files available in its managed workspace.
- Local extraction/indexing and bounded retrieval.
- Project Knowledge usage guidance for recurring collections.
- User workflows that avoid repeatedly pasting or printing full sources.
- Explicit disclosure of cache lifetime and visual-processing limits.

Never claim that a Skill makes a first-time attachment upload free or reduces a cost already incurred before Skill code runs.

### Claude Code

Claude Code allows more direct optimization through local CLI tools and supported hooks. The current implementation can:
- Suppress one byte-identical repeated large Read result, then permit a full recovery read.
- Compact a narrow set of completed successful test-runner outputs.
- Archive original stdout locally before applying output compaction.
- Store evidence-backed project facts in local SQLite.
- Read token usage fields from local JSONL transcripts when present.

These hooks are deliberately narrow. General MCP, web search, database, arbitrary Bash, and conversation-history filtering are not implemented.

## Current implementation versus planned work

| Area | Current status | Next engineering target |
|---|---|---|
| File extraction | Text, Office XML-derived content, PDF text | Stronger per-format extraction and source maps |
| File retrieval | Local cache and lexical chunk search | Better ranking, metadata filters, structural retrieval |
| Images and scans | Not supported by local extractor | OCR, image analysis, page/region selection, quality checks |
| Conversation history | No direct rewrite in Claude.ai; no full Claude Code history compressor | Platform-safe session/context analysis and measured compaction guidance |
| Tool output | Exact repeated Read and limited successful tests only | Parsers for known tool families and MCP contracts |
| MCP definitions/results | No general optimizer | Tool discovery hygiene, schema budgeting, result projection |
| Output generation | No output rewriting or global length cap | Generation guidance only where task requirements allow |
| Usage measurement | Claude Code JSONL fields when available | Reproducible A/B benchmark; transparent cost accounting |
| Quality assurance | Conservative fail-open rules | Task-specific golden sets and blind quality evaluation |

## Optimization pipeline

Every optimization candidate should pass these checks:

1. **Detect:** Identify content source, format, size, tool, context boundary, and whether the result is repeated.
2. **Classify:** Determine whether content is plain text, code, structured data, visual material, an error, or an unknown format.
3. **Estimate:** Estimate possible model-visible reduction and processing overhead. Do not turn character counts into claimed token counts.
4. **Transform:** Use deterministic and format-aware processing first. Use model-assisted transformation only when its extra cost is justified and measurable.
5. **Preserve:** Keep the original, source identity, range/page/line metadata, and a reliable recovery reference.
6. **Verify:** Check structural integrity, required facts, and task-specific quality.
7. **Measure:** Record before/after usage, extra calls, latency, and quality. Disable transformations that do not produce a net benefit.

Any unknown, lossy, ambiguous, or unrecoverable transformation must fail open.

## Priority roadmap

### P0 — Truthful baseline and evaluation
- Freeze representative task sets for Claude.ai and Claude Code separately.
- Record model, plan/API mode, model settings, cache conditions, files, tool setup, usage telemetry, and quality scores.
- Compare no Skill, native Claude optimizations, current FidelityFlow, and optimized FidelityFlow.
- Separate context footprint from billed/API cost and subscription usage limits.
- Make no percentage claims before the test set is run.

### P1 — File and image processing
- Add OCR for scanned PDFs and standalone images with page/region references.
- Improve DOCX/XLSX/PPTX extraction without discarding layout-critical metadata.
- Add image deduplication and task-aware resolution/region handling.
- Keep original bytes and support retrieval of exact pages, cells, slides, and regions.
- Avoid sending every page/image to Claude when only a subset is relevant.

### P2 — Tool and MCP result processing
- Build safe adapters for known tool response schemas.
- Return bounded relevant results with stable IDs, counts, pagination state, and provenance.
- Keep full raw results retrievable locally.
- Preserve errors, warnings, diffs, structured types, and required fields.
- Do not rewrite unknown tool responses.

### P3 — Text, code, and session context
- Improve structural code retrieval and duplicate-read detection.
- Add parsers for high-volume log/search/test result formats.
- Evaluate conversation compaction strategies within Claude Code's supported mechanisms.
- Avoid summarizing history Claude has already compacted unless the saved representation is demonstrably useful.

### P4 — User guidance and reporting
- Provide a setup diagnostic for unnecessary Skills, MCP servers, and overly broad project instructions.
- Offer usage reports only from actual platform telemetry.
- Show what changed, why it was safe, what was omitted, and how to recover it.
- Provide separate guidance for Free Claude.ai users and Claude Code users.

## Benchmark contract

Use identical task inputs and equivalent settings across:
- Claude without FidelityFlow.
- Claude using native Projects, caching, compaction, and tool-search features where applicable.
- A concise-instructions control.
- FidelityFlow's current release.
- FidelityFlow's candidate release.
- Relevant competitor tools.

Track separately:
- Input tokens.
- Cache-creation input tokens.
- Cache-read input tokens.
- Output tokens.
- Thinking tokens when exposed.
- Tool calls and retries.
- Model-assisted preprocessing and embedding costs.
- Latency.
- Task correctness, evidence fidelity, retrieval recall, and output completeness.

Calculate net savings from actual cost/usage totals, including all additional work. For subscription users, report platform usage changes rather than inventing per-token dollars. For API users, apply the actual pricing schedule for the selected model and cache category.

A release qualifies as a quality-preserving optimization only when it passes task-specific quality thresholds and offers a positive net benefit. If quality decreases materially or added overhead exceeds savings, do not enable that transformation by default.

## Non-goals

- No global truncation or fixed output-length cap.
- No rewriting of requested long-form deliverables merely to reduce output tokens.
- No generic lossy compression for arbitrary files or tool results.
- No automatic model call just to summarize content a deterministic parser can process.
- No assumption that cached tokens consume zero context.
- No claim that Claude.ai Skills can intercept platform internals.
