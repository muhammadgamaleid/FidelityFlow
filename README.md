<div align="center">

# FidelityFlow

**Make Claude's context more efficient without losing the evidence.**

A local-first toolkit for Claude that indexes files, retrieves relevant source passages, and applies conservative, recoverable context optimizations in Claude Code.

[![Tests](https://github.com/muhammadgamaleid/FidelityFlow/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/muhammadgamaleid/FidelityFlow/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Version](https://img.shields.io/badge/version-0.6.0-blue)
![License](https://img.shields.io/badge/license-MIT-green)

[Features](#features) · [Install on Claude.ai](#install-on-claudeai) · [Install on Claude Code](#install-on-claude-code) · [CLI](#cli-quick-start) · [Architecture](docs/ARCHITECTURE.md) · [Changelog](CHANGELOG.md)

</div>

> **Project status:** active development. FidelityFlow does not advertise a token- or cost-saving percentage. Any optimization must be measured against actual usage and task quality before a quantitative claim is made.

## Why FidelityFlow?

Large files, repeated reads, oversized tool results, and unnecessary context can make Claude sessions harder and more expensive to operate. FidelityFlow focuses on avoidable repetition and retrieval overhead—not on shortening answers that need to be complete.

**Design principles**
- Keep the original source authoritative and unchanged.
- Index once, search narrowly, and retrieve only the passages a task needs.
- Preserve source locations and coordinate systems.
- Leave unknown, failed, structured, sensitive, or ambiguous output untouched.
- Make local hooks opt-in and transformations recoverable.

## Features

| Area | Current capabilities |
|---|---|
| File indexing | Text, source code, Markdown, CSV/TSV, JSON/JSONL, YAML, XML/HTML, DOCX, XLSX, PPTX, and PDF text |
| Retrieval | Local content-addressed cache, lexical ranking, code-identifier expansion, bounded excerpts, full-chunk recovery |
| Source mapping | PDF pages, PPTX slides/shapes/charts/connectors, XLSX sheets/cells, DOCX tables and picture anchors, OCR image regions |
| OCR | Optional local Tesseract OCR for images and sparse-text PDF pages; confidence and pixel coordinates |
| Visual candidates | Optional OpenCV shape, plot-area, nearby-label, arrow, and tentative flowchart-connection candidates |
| Claude Code | Optional hooks for exact repeated text-result filtering, narrow successful test-output compaction, and PreCompact guidance |
| Project memory | Local SQLite evidence-backed facts for Claude Code |
| Diagnostics | `fidelityflow doctor`, usage transcript reader, release archive validation |

Visual candidates are geometric heuristics, not semantic image understanding. Raster chart values and series are not reliably reconstructed; embedded raster media inside DOCX/PPTX is not automatically OCR-analyzed. See [file-processing limitations](skills/fidelityflow/references/file-processing.md).

## Choose the right installation

| What you need | Recommended path |
|---|---|
| Use the workflow in Claude.ai | Upload the **Skill ZIP** |
| Install a Claude plugin in Claude.ai | Upload the **Plugin ZIP** (if custom plugin upload is available to your account) |
| Use indexing and retrieval locally | Install the Python package |
| Use Claude Code hooks and local project memory | Install the package and Skill, then opt in to hooks |
| Test the plugin from a checkout | Launch Claude Code with `--plugin-dir` |

The Skill teaches Claude when and how to use the workflow. The local Python package provides the CLI and hooks. Installing a Skill does **not** install Python, Tesseract, or Claude Code hooks.

## Install on Claude.ai

### A. Upload the Skill (recommended)

The Skill ZIP is suitable for Claude.ai custom Skill upload on accounts where custom Skills and code execution are enabled.

1. Download **`fidelityflow-claude-ai.zip`** from the [latest GitHub Release](https://github.com/muhammadgamaleid/FidelityFlow/releases/latest). If no release is published yet, build it locally using the commands below.
2. Open [Claude](https://claude.ai/).
3. Open **Settings → Capabilities** and enable **Code execution and file creation** (the label may appear as **Create and edit files**).
4. Open **Customize → Skills**.
5. Select **+ → Create skill → Upload a skill**.
6. Choose `fidelityflow-claude-ai.zip`.
7. Enable FidelityFlow in your Skills list.
8. Start a new chat and ask Claude to index or search a file that is available in its Skill execution workspace.

**Important:** the Skill can only process files exposed to its managed execution workspace. Claude.ai does not guarantee Tesseract, language packs, OpenCV, or persistent cache storage in that environment. Use the local CLI for dependable OCR and persistent indexing.

### B. Upload the Plugin

Use this route only if your Claude account exposes custom Plugin upload.

1. Download **`fidelityflow-plugin.zip`** from the [latest GitHub Release](https://github.com/muhammadgamaleid/FidelityFlow/releases/latest).
2. In Claude, open **Customize → Plugins**.
3. Choose the custom Plugin upload option.
4. Upload `fidelityflow-plugin.zip`.
5. Review the plugin details and enable FidelityFlow.
6. Keep **Code execution and file creation** enabled for the bundled Skill's file-processing workflow.

The current Plugin package bundles the FidelityFlow Skill. It does not provide a hosted service, remote MCP server, or Claude.ai chat hooks. Plugin capabilities and availability are controlled by Anthropic and may differ by plan or organization policy.

### Build the Skill and Plugin ZIP files yourself

Requirements: Python 3.10 or newer.

```bash
git clone https://github.com/muhammadgamaleid/FidelityFlow.git
cd FidelityFlow
python build_release.py --check
```

The two archives are created under `dist/`:
- `dist/fidelityflow-claude-ai.zip`
- `dist/fidelityflow-plugin.zip`

The build validates the Skill metadata, required files, internal references, Plugin manifest, and ZIP integrity.

## Install on Claude Code

There are two separate pieces: the Skill (instructions Claude discovers) and the local runtime (CLI, hooks, and project memory).

### Option A — Install the Skill and local runtime (recommended)

Requirements:
- Claude Code installed and authenticated.
- Python 3.10+.
- Git.

1. Clone the repository:

```bash
git clone https://github.com/muhammadgamaleid/FidelityFlow.git
cd FidelityFlow
```

2. Install the package:

```bash
python -m pip install -e ".[pdf]"
```

3. Run diagnostics:

```bash
fidelityflow doctor
fidelityflow --version
```

4. Install the Skill for your user:

```bash
python install.py --scope user
```

5. Restart Claude Code (or start a new session). The Skill is installed at `~/.claude/skills/fidelityflow`.

6. Verify the CLI:

```bash
fidelityflow --help
fidelityflow search --help
```

### Enable optional Claude Code hooks

Hooks are deliberately **opt-in**. They can suppress a single byte-identical repeated result in narrowly supported cases, compact only recognized successful test output, archive original stdout locally, and provide PreCompact guidance.

1. From the repository root, run:

```bash
python install.py --scope user --enable-output-hook
```

2. Restart Claude Code.
3. Review `~/.claude/settings.json` and the installed hook scripts under `~/.claude/hooks/fidelityflow/`.
4. Run a normal task and inspect the hook behavior before relying on it in a sensitive project.

The installer backs up an existing settings file before updating it. Hook archives and caches are local and unencrypted; protect them accordingly. To disable the hooks, remove only the FidelityFlow hook registrations from Claude settings. Do not replace your entire settings file.

### Option B — Load the Plugin from a local checkout (development/testing)

To test the Plugin manifest and bundled Skill without installing it permanently:

```bash
git clone https://github.com/muhammadgamaleid/FidelityFlow.git
cd FidelityFlow
claude --plugin-dir .
```

This loads the local plugin for that Claude Code session. It is a development/test path; it does not install the Python runtime or enable the optional local hooks. Use Option A for the supported persistent Skill + CLI + hooks setup.

### Install optional OCR and visual analysis

OCR requires Python extras **and** the external Tesseract executable with the language data you need.

```bash
python -m pip install -e ".[ocr,vision]"
fidelityflow doctor
fidelityflow ingest "scanned-report.pdf" --ocr --ocr-lang ara+eng
fidelityflow ingest "screenshot.png" --ocr --ocr-lang ara+eng
```

On Ubuntu/Debian, for example:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-ara
```

Use the equivalent package manager for your operating system. OCR is opt-in and respects page/DPI and image-size limits.

## CLI quick start

```bash
# Inspect optional capabilities
fidelityflow doctor

# Index a document
fidelityflow ingest "docs/architecture.pdf"

# Search for a focused question
fidelityflow search --query "authentication flow" --top-k 5

# Retrieve the full indexed chunk when needed
fidelityflow show --document DOCUMENT_ID --chunk 0

# Index a directory
fidelityflow ingest-dir "./research-library"

# Inspect local project memory
fflearn --help
```

For PDF text extraction, install the `pdf` extra. For image and scanned-PDF OCR, install `ocr` and optionally `vision`, then configure Tesseract and its language data.

## What FidelityFlow does not do

- It does not intercept Claude.ai's initial file-upload or internal document-parsing pipeline.
- It does not make the first upload free or guarantee that a cached Skill workspace persists across chats.
- It does not change Claude pricing, subscription limits, model choice, reasoning effort, prompt caching, or automatic compaction thresholds.
- It does not perform semantic/vector search.
- It does not reliably recover raster chart values, prove arrow direction, or infer diagram meaning.
- It does not automatically OCR raster images embedded inside DOCX/PPTX.
- It does not promise a token- or cost-saving percentage without controlled measurement.

## Measurement and quality

A shorter tool result is not automatically a net saving. Evaluate actual input/cache/output/thinking usage when available, extra tool calls and retries, latency, task correctness, evidence fidelity, retrieval recall, and output completeness.

For a Claude Code JSONL transcript:

```bash
python benchmarks/read_claude_usage.py "/path/to/session.jsonl"
```

The reader reports fields present in the transcript; it does not estimate missing usage or measure Claude.ai web-chat usage. Subscription usage limits are not equivalent to API dollar billing.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [File processing and source mapping](skills/fidelityflow/references/file-processing.md)
- [Claude platform setup](skills/fidelityflow/references/platform-setup.md)
- [Quality and safety policy](skills/fidelityflow/references/quality-policy.md)
- [Consumption strategy and roadmap](docs/CONSUMPTION-STRATEGY.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## Privacy

- Original source files are not modified by the local indexer.
- Local caches, SQLite memory, and optional output archives may contain sensitive data and are not encrypted by FidelityFlow.
- The local extraction and hook code makes no network calls.
- Redaction is best-effort, not a guarantee. Never submit credentials or secrets.
- Unknown, ambiguous, structured, failed, or sensitive output is passed through unchanged unless a format-specific rule safely handles it.

## License

MIT. See [LICENSE](LICENSE).
