# File processing and source fidelity

## Source-first design

FidelityFlow never edits the original file. It creates a searchable derivative and records source identity, extractor version, warnings, hashes, and chunk offsets. The cache key combines the source SHA-256 and extractor version. An unchanged file can be re-used without repeating extraction.

An extracted index is not a replacement for the source. Retrieve the original passage or use Claude's native file handling whenever visual layout, exact calculations, or missing structure affects the task.

## Current local extraction support

| Format | Extracted today | Limitations |
|---|---|---|
| TXT, Markdown, RST, logs, source code | UTF-8 text | Invalid bytes are replaced with a warning; source remains authoritative |
| CSV / TSV / JSON / JSONL / YAML / XML / HTML | Raw text | No general semantic schema inference or validation |
| DOCX | Main paragraphs, heading styles, table text | Does not preserve pagination, tracked changes, comments, headers/footers, floating objects, embedded media, or exact layout |
| XLSX | Sheet names, cell addresses, text/numeric values, formulas, cached formula values | Does not reproduce formatting, charts, pivots, macros, external links, validations, or formula recalculation |
| PPTX | Slide text and basic table cell text | Does not fully extract images, diagrams, speaker notes, animations, or spatial layout |
| PDF | Per-page text with [PAGE n] markers | Requires optional pypdf; scans, figures, complex tables, columns, and visual layout are not reliably represented |

OOXML safety limits apply to archive members, aggregate expanded size, entry count, and extreme compression ratios. Legacy .doc, .xls, and .ppt formats are not supported by the current local extractor.

**Not implemented yet:** standalone image ingestion, OCR for scanned pages, audio/video extraction, image-region analysis, chart understanding, and visual layout reconstruction.

## Commands

~~~bash
fidelityflow doctor
fidelityflow ingest "report.pdf"
fidelityflow ingest-dir "./research-library"
fidelityflow list
fidelityflow search --query "revenue recognition" --top-k 5
fidelityflow show --document DOCUMENT_ID --chunk 0
~~~

The bundled Claude Skill script can be run with the exact path exposed by the Skill execution environment:

~~~bash
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" doctor
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" ingest "/exact/path/to/report.pdf" --cache-dir "$PWD/.fidelityflow/cache"
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" search --query "specific question" --top-k 5 --max-chars 1400 --cache-dir "$PWD/.fidelityflow/cache"
~~~

Never guess the Skill installation path. The local Python package is needed for the native Claude Code CLI; the bundled Skill script is packaged separately for Claude.ai.

## Search and retrieval

- Search is lexical and ranks extracted chunks by term overlap/frequency; it is not semantic vector search.
- Search returns bounded excerpts and source metadata. Use show to retrieve a complete chunk only when needed.
- Use alternate terms or native Claude search when lexical retrieval misses a relevant passage.
- Preserve source names, PDF page markers, line ranges, and any available cell/slide identifiers when quoting results.
- Do not ingest every repository or directory automatically. Select only sources relevant to the task.

## Cache and privacy

- Extracted content is stored once in the local cache; chunk metadata stores offsets rather than duplicating full text.
- Cache entries are local and unencrypted. They can contain sensitive source material.
- The cache is content-addressed; changed source content gets a different cache identity.
- Claude.ai Skill workspace caches may disappear after a reset or unrelated chat. Do not promise persistence.
- Do not delete or replace the original source after indexing.

## Claude.ai upload boundary

Claude.ai controls its own initial attachment ingestion and document parser. A custom Skill cannot intercept that pipeline, rewrite the attachment before Claude receives it, or guarantee that the initial upload avoids context/usage accounting.

When a file is already available in the Skill execution workspace, local extraction and bounded retrieval can avoid repeatedly printing its full content into the conversation. For recurring libraries, use Claude Projects and Project Knowledge when appropriate; do not duplicate a complete library in both systems without a measured benefit.

For visual PDFs, scanned pages, charts, spreadsheet calculations, and layout-sensitive tasks, prefer Claude's native document capabilities or a dedicated visual workflow. The current FidelityFlow extractor is text-oriented.
