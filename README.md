<div align="center">

# FidelityFlow

**Spend fewer Claude tokens on context. Keep the information that matters.**

A Claude-focused toolkit for local file indexing, targeted retrieval, and conservative Claude Code output optimization.

[![CI](https://github.com/muhammadgamaleid/FidelityFlow/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/muhammadgamaleid/FidelityFlow/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Claude Skills](https://img.shields.io/badge/Claude_Skills-Free_%2B_Paid-blueviolet)
![Claude Plugins](https://img.shields.io/badge/Claude_Plugins-Paid_Plans-orange)

</div>

> **Honest status:** FidelityFlow is under active development. Current capabilities and limitations are listed below. We do not publish a token-saving percentage until controlled tests prove net savings without reducing task quality.

## Contents

- [Why FidelityFlow](#why-fidelityflow)
- [Choose your Claude installation](#choose-your-claude-installation)
- [Install on Claude.ai](#install-on-claudeai)
- [Install on Claude Code](#install-on-claude-code)
- [What works today](#what-works-today)
- [Practical ways to use fewer tokens](#practical-ways-to-use-fewer-tokens)
- [Measurement and quality](#measurement-and-quality)
- [Roadmap](#roadmap)
- [Privacy and limitations](#privacy-and-limitations)

## Why FidelityFlow

Large files, repeated reads, long tool results, unused tools, and oversized conversation history can all add context. FidelityFlow focuses on avoidable repetition and retrieval overhead—not on shortening answers that need to be complete.

**The core rule:** preserve the original, retrieve only what the task needs, and leave uncertain content untouched.

## Choose your Claude installation

| Package | Free | Pro / Max / Ultra | Team / Enterprise |
|---|:---:|:---:|:---:|
| **FidelityFlow Skill** | Yes* | Yes* | Yes* |
| **FidelityFlow Plugin** | — | Yes* | Yes* |

* Skills and Plugins require the relevant Claude capabilities and may be restricted by Team or Enterprise administrators. The Skill is the recommended upload for Free accounts. The Plugin package currently wraps the same Skill; it does not add a hosted service or extra optimization engine.

Official availability: [Claude Skills](https://support.claude.com/en/articles/12512180-use-skills-in-claude) · [Claude Plugins](https://support.claude.com/en/articles/13837440-use-plugins-in-claude).

## Install on Claude.ai

### Option A — Upload the Skill (Free and paid)

1. Open **Settings → Capabilities** and enable **Code execution and file creation** (also labelled **Create and edit files** in the updated settings).
2. Open **Customize → Skills**.
3. Choose **+ → Create skill → Upload a skill**.
4. Upload `dist/fidelityflow-claude-ai.zip`.
5. Enable FidelityFlow in your Skills list.

### Option B — Upload the Plugin (paid plans)

1. Open **Customize → Plugins**.
2. Choose the custom Plugin upload option.
3. Upload `dist/fidelityflow-plugin.zip`.
4. Enable FidelityFlow.

The Plugin includes the Skill. Keep **Code execution and file creation** enabled so its file-processing workflow can run. Plugin hooks and sub-agents are not active in ordinary web chat.

### Build the upload files yourself

Download or clone the repository, then run:

```bash
python build_release.py --check
```

This validates and creates both archives under `dist/`. Python 3.10 or newer is required.

## Install on Claude Code

From the repository directory:

```bash
python -m pip install -e ".[pdf]"
fidelityflow doctor
python install.py --scope user
```

To enable the optional output hooks:

```bash
python install.py --scope user --enable-output-hook
```

Hooks are opt-in. Review the settings backup and local archive behavior before enabling them, especially in sensitive projects.

**Useful commands**

```bash
fidelityflow ingest "docs/architecture.pdf"
fidelityflow search --query "authentication flow" --top-k 5
fidelityflow show --document DOCUMENT_ID --chunk 0
fidelityflow doctor
```

For PDF extraction, install the `pdf` extra as shown above.

### Optional local OCR for images and scanned PDFs

OCR is available in the local CLI only. Install the Python extra, then install the Tesseract executable and the language data you need:

```bash
python -m pip install -e ".[ocr,vision]"
fidelityflow doctor
fidelityflow ingest "scanned-report.pdf" --ocr --ocr-lang ara+eng
fidelityflow ingest "screenshot.png" --ocr --ocr-lang ara+eng
```

OCR is opt-in, processes only sparse-text PDF pages by default, and respects DPI/page limits. Claude.ai's managed Skill workspace does not guarantee Tesseract or its language packs, so this workflow is not promised in web chat. OCR extracts text and approximate layout evidence; it does not interpret chart values, arrow direction, or diagram semantics.

## What works today

| Capability | Claude.ai Skill | Claude Code |
|---|:---:|:---:|
| Extract text, code, DOCX, XLSX, PPTX, and PDF text | Yes, when source files are exposed to the Skill workspace | Yes |
| Local content-addressed cache | Workspace lifetime; persistence is not guaranteed | Persistent local cache |
| Lexical search and bounded excerpt retrieval | Yes | Yes |
| Code-aware identifier matching and symbol-aware chunk boundaries | Yes | Yes |
| Line-preserving excerpts centered around query matches | Yes | Yes |
| Source mapping for pages/slides/sheets/cells, OCR pixel regions, DOCX floating-picture anchors, and native PPTX picture/chart-frame bounds | Yes | Yes |
| Optional local multi-pass OCR with confidence and line coordinates | Not guaranteed in Skill VM | Yes, with OCR dependencies and Tesseract language data |
| Optional raster visual candidates (OpenCV) | Not guaranteed in Skill VM | Yes, with the separate `vision` extra; candidate shapes, plot-like axes, proximity-linked OCR labels, and possible arrows |
| Exact repeated large `Read` suppression | — | Optional hook |
| Exact repeated plain-text search and MCP results | — | Optional hook; one repeat only, with recovery read |
| Narrow successful test-output compaction | — | Optional hook; original stdout archived locally |
| PreCompact context handoff guidance | — | Optional hook; guides Claude's native compaction |
| Evidence-backed project memory | — | Local SQLite |

**Still limited:** raster chart values and series are not reconstructed reliably from pixels; semantic flowchart interpretation, robust arrow topology, embedded Office-image OCR, model-based visual reasoning, audio/video processing, and independently validated end-to-end savings remain future work. The current vision pass emits conservative geometric candidates, not authoritative semantic conclusions.

Search is lexical, not semantic. Office extraction is text-oriented and does not fully reconstruct visual layout, charts, embedded objects, or spreadsheet calculation behavior.

## Practical ways to use fewer tokens

These habits help even before enabling FidelityFlow:

1. **Use Claude Projects for recurring reference material.** Keep stable documents in Project Knowledge instead of repeatedly attaching the same library.
2. **Start a new chat for an unrelated task.** Do not carry old conversation history when it is no longer useful.
3. **Keep project instructions focused.** Put task-specific procedures in Skills rather than repeating them in every prompt.
4. **Disable MCP servers and connectors you do not use.** Tool definitions and tool results can both add context.
5. **Ask for targeted reads.** Search for filenames, symbols, terms, or line ranges before loading large files.
6. **In Claude Code, inspect `/context` and `/usage`.** Use `/clear` for a separate task and `/compact` when continuing the same task.
7. **Keep the right reasoning effort.** Lower effort may suit routine tasks; do not reduce it blindly for architecture, security, or data-critical work.

FidelityFlow does not silently change Claude's model, billing, thinking budget, prompt-cache policy, or initial web upload pipeline.

## Measurement and quality

A shorter tool result is not automatically a real saving. A fair evaluation counts:

- Input, cache-creation, cache-read, output, and thinking tokens when exposed.
- Skill instructions, extra calls, retries, and recovery reads.
- Actual API cost when the user supplies the applicable model pricing.
- Task correctness, evidence fidelity, retrieval accuracy, and output completeness.

For a Claude Code JSONL transcript, inspect actual recorded usage:

```bash
python benchmarks/read_claude_usage.py "/path/to/session.jsonl"
```

This reads usage fields present in the transcript. It does not estimate missing values or measure Claude.ai web-chat usage. Subscription usage limits are not the same as API dollar billing.

## Roadmap

The current release already includes conservative duplicate-result filtering, successful test-output compaction, PreCompact handoff guidance, local OCR, and lexical file retrieval. The remaining work is deeper than these initial safeguards:

1. **Visual understanding (in progress):** structured extraction of embedded Office chart types, titles, axes, legends, indexed cached data, and native diagram connector endpoints is implemented. Remaining work includes visual interpretation of raster charts/diagrams, arrow direction and semantic relationships, OCR-to-visual label association, and independent accuracy benchmarks.
2. **Text and code retrieval:** semantic search, language-aware AST/LSP navigation, and stronger log and structured-document retrieval.
3. **Tool and MCP processing:** schema-aware adapters, safe field projection, pagination-aware retrieval, and recoverable original results.
4. **Session continuity:** structured checkpoints, memory lifecycle controls, contradiction handling, and supported cross-session recovery.
5. **Benchmark suite:** reproducible A/B tasks, independent quality evaluation, full overhead accounting, and transparent reports.

Features remain labelled as planned until implemented and tested. See [the engineering strategy](docs/CONSUMPTION-STRATEGY.md) for detailed priorities and acceptance criteria.

## Privacy and limitations

- Original files are never modified by the local indexer.
- Local caches, project memory, and optional output archives may contain sensitive data and are **not encrypted** by FidelityFlow.
- The local extraction and hook code makes no network calls.
- Redaction is best-effort, not a guarantee.
- A Claude.ai Skill cannot intercept the platform's initial attachment ingestion or guarantee that the first upload is free.
- Skill-workspace cache persistence across unrelated chats or VM resets is not guaranteed.
- Unknown, ambiguous, structured, failed, or sensitive tool output must pass through unchanged unless a format-specific adapter proves a safe transformation.

## Project policies

- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

## License

MIT — see [LICENSE](LICENSE).
