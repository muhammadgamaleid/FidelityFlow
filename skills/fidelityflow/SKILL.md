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
3. Identify whether the task depends on visual layout, charts, screenshots, scanned pages, or exact spreadsheet calculations. For standalone images and scanned pages, enable local OCR and the optional `vision` extra to obtain OCR coordinates and heuristic shape/plot/arrow candidates. Treat these as navigation evidence only; verify chart values, arrow direction, and semantic meaning against the original or use Claude's native visual capabilities.

## File workflow

The bundled CLI is at scripts/fidelityflow.py relative to the Skill directory. Resolve the actual installed Skill path from the execution environment; never guess an absolute path.

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
- Search is lexical (BM25-style), not semantic. Code identifiers are indexed both as written and as common underscore/CamelCase components; source-aware chunking prefers common function/class/type boundaries when possible. Search excerpts preserve line breaks and are centered near query matches. A failed search may require alternate terms or native Claude search; do not invent a result.
- PDF extraction preserves page markers but may miss scanned text, complex tables, columns, charts, figures, or layout.
- DOCX extraction does not preserve exact pagination, embedded media, or all review/layout metadata.
- XLSX extraction is not a spreadsheet calculation engine and does not reproduce charts, pivots, macros, or recalculation semantics.
- PPTX extraction does not fully represent images, diagrams, notes, animations, or spatial layout.
- Standalone image OCR and sparse-text PDF page OCR are available only in the local CLI with the optional OCR dependencies, the Tesseract executable, and language data installed. They require explicit `--ocr`; they are not guaranteed to run in Claude.ai's managed Skill workspace. The OCR pipeline uses bounded multi-pass preprocessing, confidence scoring, and approximate line bounding boxes.\n- The optional OpenCV `vision` extra can report geometric evidence (line orientation/counts and contours) for images and OCR-rendered PDF pages. It does not interpret chart data, arrow direction, flow semantics, or the meaning of a diagram. For semantic visual questions, use Claude's native vision capabilities and verify against the original.
- Audio and video extraction are not currently supported.
- The original file remains authoritative. An extracted index is a searchable derivative, not a replacement.

## Claude.ai boundary

A Claude.ai Skill cannot intercept Claude's internal attachment ingestion or document parser. Do not claim that uploading a large file directly to Claude becomes free or that this Skill can rewrite the initial upload. The Skill can process a source exposed to its execution workspace and avoid repeatedly printing the full extracted source. Workspace cache persistence across unrelated chats or VM resets is not guaranteed.

For recurring reference libraries, prefer Claude Projects and Project Knowledge where available. Avoid indexing the same library twice without a measured reason. Keep Project Instructions short and use this Skill only when its local file workflow provides a practical benefit.

## Claude Code boundary

The optional hooks are installed separately with the project installer. In the current release they handle:
- Large, byte-identical repeated Read results within a session/agent context epoch.
- Exact duplicate plain-text results from Grep, Glob, WebSearch, WebFetch, NotebookRead, and standard text-only MCP results when both tool input and output match.
- Narrowly recognized, completed, successful test-runner output.
- PreCompact guidance for the existing Claude Code summary, optionally informed by `.fidelityflow/session-brief.md`.

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
