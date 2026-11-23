# Architecture

## Product objective

FidelityFlow is a Claude-focused, local-first context-efficiency toolkit. It reduces avoidable repeated file and tool-output context while preserving original sources, source locations, and task-required information.

It is not a universal lossy compressor. Each transformation is restricted to a known format and must retain a recovery path or fail open.

## Repository layout

```text
.
├── .claude-plugin/          # Claude Plugin manifest
├── .github/workflows/       # CI and integration tests
├── benchmarks/              # Usage transcript reader and evaluation helpers
├── docs/                    # Canonical architecture, strategy, and project docs
├── fidelityflow/            # Python package and local project-memory implementation
├── hooks/                   # Optional Claude Code hooks and examples
├── skills/fidelityflow/     # Distributable Skill, scripts, and packaged references
├── tests/                   # Unit, integration, and release-package tests
├── build_release.py         # Validates and builds Skill/Plugin ZIP archives
├── install.py               # Installs Skill and opt-in Claude Code hooks
└── pyproject.toml            # Python package metadata and optional dependencies
```

The architecture deliberately keeps canonical project documentation under `docs/` and the Skill's runtime-facing copies under `skills/fidelityflow/references/`. The release validator checks that the architecture, learning-memory, and license copies remain synchronized.

## Runtime paths

```text
                         FidelityFlow
                              |
                 +------------+-------------+
                 |                          |
             Claude.ai                   Claude Code
                 |                          |
          Uploaded Skill ZIP       Local Python package
                 |                          |
         Managed Skill workspace    Local CLI + installed Skill
                 |                          |
        Bundled file-processing CLI  Extract / cache / search
                 |                          |
         Bounded source excerpts       Optional Claude Code hooks
                                            |
                              +-------------+-------------+
                              |                           |
                       Duplicate filtering        Successful test compaction
                              |                           |
                        Recovery marker              Local stdout archive
                              |
                       PreCompact guidance
                              |
                    SQLite project memory
```

## Components

### 1. Claude Skill

`skills/fidelityflow/SKILL.md` contains concise routing instructions, quality rules, and platform boundaries. Detailed procedures live in references so Claude does not need to load the entire manual for every task.

The Skill archive is the Claude.ai upload path. The Skill can invoke its bundled script only for files exposed to its execution workspace. It cannot intercept Claude.ai's initial attachment ingestion pipeline.

### 2. File-processing CLI

The packaged implementation is `skills/fidelityflow/scripts/fidelityflow.py`; the Python package exposes it through the `fidelityflow` command.

Supported extractors cover text/code, Markdown, CSV/TSV, JSON/JSONL, YAML, XML/HTML, DOCX, XLSX, PPTX, and PDF text when optional pypdf is installed.

The cache is content-addressed by source hash, extractor version, chunk settings, and OCR settings. It stores extracted content once and chunk offsets/metadata separately. It never modifies the original file.

Search is lexical (BM25-style), not semantic/vector search. It expands common code identifiers, prefers headings and common code symbol boundaries, and returns line-preserving excerpts around query matches.

### 3. Source mapping

Indexed chunks can retain:
- PDF page references.
- PPTX slide numbers, native object IDs, picture/chart bounds, chart metadata, cached values, and connector endpoints.
- XLSX worksheet and cell references.
- DOCX table and picture metadata, including native extents and anchor-relative offsets.
- OCR line boxes and raster visual candidate regions in processed-image pixels.

Coordinate spaces remain explicit: pixels, slide EMUs, chart-relative fractions, and Word anchor-relative offsets are not silently converted. Source maps are navigation evidence, not a reconstruction of every visual detail.

### 4. OCR and raster visual candidates

Optional local OCR processes standalone images and sparse-text PDF pages. Its bounded multi-pass pipeline applies preprocessing, multiple Tesseract segmentation modes, confidence scoring, and confidence-gated orientation correction. Arabic right-to-left line ordering is handled conservatively.

The optional `vision` extra uses OpenCV to detect candidate rectangles, ellipses, diamonds, triangles, plot-like axes and estimated plot bounds, nearby OCR labels, possible arrowheads, and tentative shape-to-shape connections. These are geometric heuristics only. They do not reliably reconstruct raster chart values, establish arrow direction, or infer diagram semantics. Tesseract, language packs, and native libraries are external local dependencies.

### 5. Claude Code hooks

Hooks are optional and installed by `install.py`. Supported behavior is deliberately narrow:
- Exact repeated large Read result filtering with a recovery read.
- Exact duplicate plain-text results for supported tools when canonical input and output hashes match.
- Compaction of narrowly recognized successful test-runner output.
- Local archive of original stdout before supported Bash output compaction.
- PreCompact guidance for Claude's existing summary.

Unknown, failed, structured, image-bearing, secret-like, and ambiguous output remains unchanged. Hooks do not rewrite conversation history or generically summarize arbitrary tool output.

### 6. Project memory

The `fidelityflow.learning` package stores evidence-backed project facts in local SQLite. Facts require distinct-session evidence before automatic promotion; conflicts remain unresolved until human confirmation. This is separate from the file cache and is not shared with Claude.ai.

### 7. Usage telemetry

`benchmarks/read_claude_usage.py` reads usage fields exposed in Claude Code JSONL transcripts. It does not estimate missing values or measure Claude.ai web-chat usage.

## Platform constraints

### Claude.ai

- Custom Skills are uploaded as ZIP archives; Code execution and file creation must be enabled.
- A Skill can process only files exposed to its managed execution workspace.
- Workspace cache persistence across unrelated chats or VM resets is not guaranteed.
- Tesseract, language packs, OpenCV, and native dependencies are not guaranteed in the managed workspace.
- The Plugin package currently bundles the Skill; it does not provide a hosted MCP server or web-chat hooks.

### Claude Code

- The local package, CLI, and optional hooks run on the user's machine.
- `python install.py --scope user` installs the Skill for the user; project scope is also supported.
- `claude --plugin-dir .` loads the local Plugin for development/testing in that session.
- The installer and plugin loader are distinct: plugin loading does not install the Python package or activate optional hooks.
- Local archives, SQLite memory, and caches are unencrypted and must be protected by the user.

## Design invariants

- Original source files remain untouched.
- A cached derivative never replaces the authoritative source.
- Any omitted output has a recovery reference or the transformation is not applied.
- Unknown and ambiguous content is unchanged.
- Failures, warnings, diffs, structured data, and likely secrets are not compacted by generic rules.
- No model call is used for hashing, chunking, lexical ranking, or current hook transformations.
- Token savings, financial savings, and answer quality are measured independently.
- No global savings percentage is published without controlled A/B evidence.

## Current limitations

- Search is lexical; semantic/vector retrieval is not implemented.
- Raster chart values and series are not reliably reconstructed from pixels.
- Visual shape and connection detection is heuristic, not semantic understanding.
- Embedded raster media inside DOCX/PPTX is not automatically OCR-analyzed.
- Spreadsheet formulas are not recalculated.
- Audio/video extraction is not supported.
- Independent, large-scale end-to-end quality and savings benchmarks remain future work.

See [the consumption strategy](../../../../docs/CONSUMPTION-STRATEGY.md) for priorities and evaluation criteria.
