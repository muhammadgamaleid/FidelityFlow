# Claude platform setup and usage optimization

This guide distinguishes what Claude provides from what FidelityFlow currently controls.

## Claude.ai: Skill upload (Free and paid plans)

Anthropic lists Skills as available on Free, Pro, Max, Ultra, Team, and Enterprise plans. For individual Free, Pro, Max, and Ultra accounts, Code execution and file creation must be enabled. In newer Settings layouts this capability may be labelled **Create and edit files**.

1. Open **Settings → Capabilities**.
2. Enable **Code execution and file creation** (or **Create and edit files**).
3. Open **Customize → Skills**.
4. Click **+ → Create skill → Upload a skill**.
5. Select dist/fidelityflow-claude-ai.zip.
6. Enable FidelityFlow in the Skills list.

For Team accounts, the organization must have Skills enabled. Enterprise owners must enable both Code execution and file creation and Skills in **Organization settings → Plugins & skills → Policy**. Administrators may impose additional policies.

## Claude.ai: Plugin upload (paid plans only)

Anthropic currently lists Plugins for Pro, Max, Ultra, Team, and Enterprise; Free is not included.

1. Open **Customize → Plugins**.
2. Choose the option to upload a custom Plugin.
3. Select dist/fidelityflow-plugin.zip.
4. Enable FidelityFlow.

Because the Plugin bundles a Skill, keep **Code execution and file creation** enabled for its file-processing commands.

The Plugin archive wraps the same Skill in a Claude plugin manifest. The current Plugin package contains a Skill only. It does not add a hosted MCP server, chat hooks, or sub-agents. Plugin hooks and sub-agents do not run in ordinary Claude web chat.

Official references:
- [Use Skills in Claude](https://support.claude.com/en/articles/12512180-use-skills-in-claude)
- [Use Plugins in Claude](https://support.claude.com/en/articles/13837440-use-plugins-in-claude)

## Claude.ai: use large files carefully

1. For recurring reference material, create a Claude Project and add stable documents to Project Knowledge once rather than attaching the same library to every new chat.
2. Keep Project Instructions short and stable. Put task-specific guidance in Skills or reference documents.
3. When a file is accessible to the Skill execution workspace, use the bundled CLI to extract and index it once, then retrieve targeted excerpts.
4. Put the cache in a writable workspace directory such as .fidelityflow/cache, not inside the Skill installation directory.
5. Reuse a cache only while that workspace remains available. Anthropic does not guarantee persistence across unrelated chats or VM resets.
6. Use Claude's native document capabilities for visual PDFs, scanned pages, charts, complex Word layouts, presentation graphics, and consequential spreadsheet calculations.

**Important boundary:** a custom Skill cannot intercept Claude.ai's internal initial attachment-upload/parser pipeline or guarantee that the first upload is excluded from usage. Do not promise zero-cost uploads. A local index is a derivative, not a way to bypass platform processing.

## Claude Code: install the local package and Skill

From the repository root:

~~~bash
python -m pip install -e ".[pdf]"
fidelityflow doctor
python install.py --scope user
~~~

Start a new Claude Code session and verify the Skill is available. Use the Skills picker or inspect the installed Skills list.

To install optional hooks:

~~~bash
python install.py --scope user --enable-output-hook
~~~

Review the Claude settings file after installation. The installer backs up existing settings and merges its registrations, but users should still inspect hook commands and local archive paths. The current hooks are opt-in and intentionally narrow. The PostToolUse matcher covers Read, Bash, selected text-result tools, and MCP tool names; PreCompact adds a concise preservation policy to Claude's existing compaction summary. You can maintain an optional `.fidelityflow/session-brief.md` from the template at `docs/SESSION-BRIEF-TEMPLATE.md`.

## Optional local OCR for Claude Code

OCR is available only when the local machine has the optional Python packages, the Tesseract executable, and the required language data installed.

~~~bash
python -m pip install -e ".[ocr]"
fidelityflow doctor
fidelityflow ingest "scanned-report.pdf" --ocr --ocr-lang ara+eng
fidelityflow ingest "screenshot.png" --ocr --ocr-lang ara+eng
~~~

OCR is opt-in. It processes sparse-text PDF pages only, respects the configured page/DPI limits, and keeps the original file unchanged. Claude.ai's managed workspace does not guarantee Tesseract or its language data; do not assume this local OCR workflow works in web chat.

## Claude Code: native usage habits

- Use /context to inspect what occupies the context window and /usage to inspect usage when available.
- Use /clear when switching to an unrelated task. Use /compact when continuing the same task and preserve decisions, constraints, file paths, tests, and unresolved questions.
- Keep CLAUDE.md focused on facts that matter in most sessions. Move detailed workflows into Skills that are loaded when relevant.
- Disable MCP servers you are not using. Tool definitions and returned results can both consume context.
- Prefer narrow CLI commands, symbol searches, and line ranges over dumping entire directories or large files. FidelityFlow search expands common code identifiers and returns line-preserving excerpts; use `show` when the complete function or source chunk is required.
- Reuse repository knowledge and avoid repeating identical reads or searches.
- Choose model and effort based on task difficulty. Do not lower reasoning effort for security, architecture, data integrity, or other high-stakes tasks only to save tokens.
- Leave prompt caching enabled unless you have a measured reason to change it. Cache reads can reduce billed API cost, but cached content can still occupy context.

## What FidelityFlow changes today

- The file CLI extracts and caches supported files locally, then returns lexical search excerpts on demand.
- The Claude Code output hook can suppress one byte-identical repeated large Read result and then permits a full recovery read on the next identical request.
- The optional output hook compacts only a narrow set of recognized successful test-runner output and archives original stdout locally.
- Claude Code project memory stores evidence-backed facts in local SQLite.

## What FidelityFlow does not change

FidelityFlow does not modify Claude pricing, subscription limits, model selection, thinking budgets, prompt-cache policy, automatic compaction thresholds, or Claude.ai's internal upload pipeline. It supports opt-in local OCR when Tesseract and the optional dependencies are installed. It does not yet generically rewrite MCP and web-search results. It does not promise a saving percentage until measured against a controlled baseline.
