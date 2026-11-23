---
name: fidelityflow
description: Reduce avoidable Claude context use with cached file indexing and relevant excerpts; optionally filter exact duplicate Claude Code tool output while preserving originals and task quality.
---

# FidelityFlow

Use FidelityFlow when the user is working with large or repeatedly used files, needs targeted retrieval from an indexed source, or wants to understand avoidable Claude context usage.

**Operating rule:** reduce repeated or irrelevant context, not information needed to complete the task. Never claim savings that have not been measured.

## Before using it

1. Decide whether the task is large or repetitive enough to justify this Skill's own instruction and tool overhead. For a small one-off question, use Claude's normal capabilities.
2. Identify the platform:
   - **Claude.ai:** use the bundled file-processing CLI only when the source file is actually accessible in the Skill execution workspace.
   - **Claude Code:** use the local CLI after installation. Optional hooks are separate and must be installed by the user.
3. Identify whether the task depends on visual layout, charts, screenshots, scanned pages, or exact spreadsheet calculations. For standalone images and scanned pages, local OCR and the optional `vision` extra can provide OCR coordinates and heuristic shape, plot, nearby-label, arrow, and tentative flowchart-connection candidates. Treat these as navigation evidence only; verify chart values, arrow direction, and semantic meaning against the original or use Claude's native visual capabilities.

## File workflow

The bundled CLI is at `scripts/fidelityflow.py` relative to the Skill directory. Resolve the actual installed Skill path from the execution environment; never guess an absolute path.

Run doctor to see available extraction support, then ingest only the files needed for the task:

~~~bash
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" doctor
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" ingest "/exact/path/to/source.pdf" --cache-dir "$PWD/.fidelityflow/cache"
~~~

Search for relevant information and keep returned excerpts bounded:

~~~bash
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" search --query "specific question" --top-k 5 --max-chars 1400 --cache-dir "$PWD/.fidelityflow/cache"
~~~

Use show to retrieve a complete chunk only when the task requires it:

~~~bash
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" show --document DOCUMENT_ID --chunk 0 --cache-dir "$PWD/.fidelityflow/cache"
~~~

Do not print an entire extracted document, cache, or archive into chat. Search first; retrieve only the minimum source passages needed to answer accurately. Preserve source names, page/line references, and relevant caveats in the answer.

## Current capabilities and limits

- The local engine extracts text/code, Markdown, CSV/TSV, JSON/JSONL, YAML, XML/HTML, DOCX, XLSX, PPTX, and PDF when pypdf is installed.
- The cache is content-addressed by source hash and extractor version. Re-ingesting unchanged content can avoid repeated extraction; it does not make the original first upload free.
- Search is lexical (BM25-style), not semantic. It expands common code identifiers into component terms, prefers source-aware chunk boundaries, and returns line-preserving excerpts centered near query matches. A failed search may require alternate terms or native Claude search; do not invent a result.
- Source maps preserve available PDF page, PPTX slide/object/chart/connector, XLSX worksheet/cell, DOCX table/picture-anchor, and OCR pixel-region references. Coordinate systems are explicit and must not be mixed.
- PDF extraction preserves page markers but may miss scanned text, complex tables, columns, charts, figures, or layout.
- DOCX extraction does not preserve exact pagination or all visual layout. Embedded raster media is not automatically OCR-analyzed.
- XLSX extraction is not a spreadsheet calculation engine and does not reproduce chart rendering, pivots, macros, or formula recalculation semantics.
- PPTX extraction does not fully represent animations, images, diagrams, notes, or complete spatial layout.
- Standalone image OCR and sparse-text PDF page OCR are available in the local CLI with optional OCR dependencies, Tesseract, and language data. They require explicit `--ocr`; they are not guaranteed in Claude.ai's managed Skill workspace.
- The optional OpenCV `vision` extra can detect candidate rectangles, ellipses, diamonds, triangles, plot-like axes and approximate plot bounds, nearby OCR labels, possible arrowheads, and tentative links between detected shapes. These are heuristic geometric candidates, not verified objects, chart values, arrow direction, causal links, or semantic diagram interpretation.
- Audio and video extraction are not currently supported.
- The original file remains authoritative. An extracted index is a searchable derivative, not a replacement.

## Claude.ai boundary

A Claude.ai Skill cannot intercept Claude's internal attachment ingestion or document parser. Do not claim that uploading a large file directly to Claude becomes free or that this Skill can rewrite the initial upload. The Skill can process a source exposed to its execution workspace and avoid repeatedly printing the full extracted source. Workspace cache persistence across unrelated chats or VM resets is not guaranteed.

For recurring reference libraries, prefer Claude Projects and Project Knowledge where available. Avoid indexing the same library twice without a measured reason.

## Claude Code boundary

The optional hooks are installed separately with the project installer. In the current release they handle:
- Large, byte-identical repeated Read results within a session/agent context epoch.
- Exact duplicate plain-text results from supported text-result tools when both tool input and output match.
- Narrowly recognized, completed, successful test-runner output.
- PreCompact guidance for Claude's existing summary, optionally informed by `.fidelityflow/session-brief.md`.

They do not generically summarize or compress arbitrary MCP, web, database, or Bash output, and they do not rewrite conversation history. Unknown, failed, structured, image-bearing, secret-like, or ambiguous output remains unchanged. Do not claim that hooks are active unless the user installed and verified them.

## Output and quality policy

- Do not shorten a user-requested deliverable merely to reduce output tokens.
- Preserve code, identifiers, numbers, units, formulas, citations, warnings, failures, and uncertainty.
- Do not replace evidence with unsupported summaries.
- If the source is unavailable, retrieval is uncertain, or a transformation may hide relevant information, fail open and ask to inspect the original.
- Distinguish measured token usage from character counts or estimates.
- Never claim a quality-neutral saving percentage without an A/B evaluation.

## Project memory

When working in Claude Code with project memory installed, use evidence-backed facts only. Treat candidates as unconfirmed; respect contradictions and provenance. Do not assume persistent SQLite memory exists in Claude.ai Skill workspaces.
