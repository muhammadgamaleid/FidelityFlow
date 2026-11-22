# File processing and source fidelity

## Original is authoritative

FidelityFlow creates a searchable derivative; it never edits the original source. It records SHA-256, extractor version, warnings, source name, and chunk offsets. The cache key is the source file's SHA-256 plus extractor version. Re-ingesting an unchanged file with the same extractor version is a cache hit.

## Supported local CLI extraction

| Format | Extracted | Important limitations |
|---|---|---|
| TXT, Markdown, RST, logs, source code | UTF-8 text | Invalid UTF-8 bytes are replaced and explicitly warned; original remains authoritative. |
| CSV / TSV / JSON / JSONL / YAML / XML / HTML | Raw text | No automatic semantic validation or schema inference. |
| DOCX | Main document paragraphs, heading styles, and table text | Pagination, tracked changes, comments, headers/footers, floating objects, embedded media, and exact layout are not preserved. XML parts above the 64 MiB safety limit are rejected. |
| XLSX | Sheet names, cell addresses, text/numeric values, formulas, cached formula values | Formatting, charts, pivots, macros, external links, data validation, and full formula recalculation semantics are not reproduced. XML parts above the 64 MiB safety limit are rejected. |
| PPTX | Slide text and basic table cell text | Images, diagrams, speaker notes, animations, and spatial layout are not fully represented. XML parts above the 64 MiB safety limit are rejected. |
| PDF | Per-page text with `[PAGE n]` markers | Requires optional `pypdf`; scans, figures, complex tables, columns, and visual layout may require native visual inspection or OCR. |

Legacy `.doc`, `.xls`, and `.ppt` are not supported by the local extractor. Save to a modern format or use Claude's native document handling. Images and audio/video are not extracted by this CLI.

## Commands

```bash
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" doctor
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" ingest "report.pdf"
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" ingest-dir "./research-library"
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" list
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" search --query "revenue recognition"
python "${CLAUDE_SKILL_DIR}/scripts/fidelityflow.py" show --document <id> --chunk 0
```

`ingest-dir` skips common generated/vendor folders such as `.git`, `.venv`, `node_modules`, `__pycache__`, `.fidelityflow`, `.idea`, and `.vscode`, as well as the configured cache directory. It processes only known file extensions.

## Cache design

- Original file remains untouched.
- Extracted text is stored once in `content.txt`.
- `chunks.jsonl` stores chunk offsets, line ranges, hashes, and term-frequency metadata only; it does not duplicate chunk text.
- Search returns relevant excerpts. `show` retrieves the complete chunk.
- A changed file has a new content hash and a new cache entry. The current release does not claim arbitrary page-level incremental parsing.
- Cache contents are local and unencrypted. They may include sensitive content; protect the cache directory accordingly.

## Claude.ai bundled-script path

Claude Skills run in a VM filesystem and may execute bundled scripts through Bash. Script source is not inserted into model context merely because it is executed; the script's stdout/stderr is what can enter context. Use this to extract and index a long source without asking Claude to reproduce its complete contents in chat.

The uploaded Skill folder is `fidelityflow/`. Resolve its actual location in the VM before running the bundled CLI. Do not guess the attachment path: use the exact path exposed by the file/tool environment. Example:

```bash
python fidelityflow/scripts/fidelityflow.py doctor
python fidelityflow/scripts/fidelityflow.py ingest "/exact/path/to/source.pdf" --cache-dir "$PWD/.fidelityflow/cache"
python fidelityflow/scripts/fidelityflow.py search --query "specific question" --top-k 5 --max-chars 1400 --cache-dir "$PWD/.fidelityflow/cache"
python fidelityflow/scripts/fidelityflow.py show --document <document-id> --chunk 0 --cache-dir "$PWD/.fidelityflow/cache"
```

The cache must be placed in a writable task/project workspace, not inside the Skill folder. Reuse it while that workspace remains available. Anthropic does not guarantee this local cache survives unrelated chats or VM resets. The original upload and Claude Project Knowledge remain the source of truth.

A Skill cannot intercept Claude.ai's internal upload/parser pipeline or guarantee that initial attachment processing is excluded from context. For recurring libraries, upload documents once to Project Knowledge and prefer Claude's native retrieval over duplicating the same collection in FidelityFlow. Use Claude's native document skills for visual PDFs, complex Word layouts, presentation graphics, and spreadsheet calculations. The local CLI is an optional searchable derivative, not a replacement for native fidelity-sensitive processing.


## Cache write safety

The local indexer rejects symlinked managed cache directories and destination files, and writes content, index, and manifest files through temporary files followed by an atomic replace. OOXML extraction limits individual XML members, aggregate expanded archive size, archive entry count, and extreme compression ratios.
