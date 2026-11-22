# Architecture

## Product objective

FidelityFlow is a Claude-focused context-efficiency toolkit. It reduces avoidable repeated file and tool-output context while preserving original sources and task-required information.

It is not a universal lossy compressor. Each transformation is restricted to a known format and must retain a recovery path or fail open.

## Current runtime paths

~~~text
                       FidelityFlow
                            |
               +------------+-------------+
               |                          |
         Claude.ai Skill              Claude Code
               |                          |
        Bundled file CLI             Local Python CLI
               |                          |
      Skill execution workspace      Persistent local workspace
               |                          |
       Extract / cache / search      Extract / cache / search
               |                          |
        Bounded excerpts              Bounded excerpts
                                          |
                                 Optional Claude Code hooks
                                          |
                        +-----------------+-----------------+
                        |                                   |
                 Exact Read dedup                  Test-output compaction
                        |                                   |
                Hash-only markers                  Local stdout archive
                        |
                   SQLite project memory (separate feature)
~~~

## Components

### 1. Claude Skill

The Skill file at skills/fidelityflow/SKILL.md contains short routing instructions, quality rules, capability boundaries, and links to detailed references. It should not load every reference file for every user request.

The Skill archive is the distribution path for Claude.ai Free and paid accounts. It requires Claude's Code execution and file creation capability.

### 2. File-processing CLI

The bundled file-processing implementation is scripts/fidelityflow.py inside the Skill directory. The maintained package command dispatches file commands through this implementation.

Current extractors cover text/code, Markdown, CSV/TSV, JSON/JSONL, YAML, XML/HTML, DOCX, XLSX, PPTX, and PDF text when optional pypdf is installed.

The local cache is content-addressed by source hash plus extractor version. It stores extracted content once and stores chunk offsets/metadata separately. It does not modify the source file.

Search is lexical. It returns bounded excerpts; the show command retrieves a complete indexed chunk when necessary.

### 3. Claude Code hooks

Optional hooks run in Claude Code after the user installs them. They are not available to a Claude.ai Skill and do not intercept the web app's initial file-upload pipeline.

Current hook transformations:
- Exact repeated large Read result: first full result passes through; one identical repeat may be suppressed; the next identical request passes through in full as a recovery safeguard.
- Test-output compaction: only narrowly recognized successful pytest, unittest, Go test, and Cargo test output, when the event and content meet conservative conditions.

The Bash output hook archives original stdout before compaction. Failed executions, stderr, unknown commands, diffs, structured output, likely secrets, and ambiguous content should pass through unchanged.

### 4. Project memory

The fidelityflow/learning package stores evidence-backed facts in local SQLite for Claude Code workflows. This is separate from the file cache and does not provide persistent SQLite memory inside Claude.ai Skill workspaces.

### 5. Usage telemetry

The read_claude_usage.py utility reads usage fields exposed in Claude Code JSONL transcript records. It does not estimate missing values or measure Claude.ai web-chat usage.

## Platform constraints

### Claude.ai

- Skills are available on Free and paid plans when Code execution and file creation is enabled.
- Plugins are available on paid plans only.
- A Skill can run bundled scripts on files available in its managed execution workspace.
- A Skill cannot intercept Claude.ai's internal initial attachment ingestion/parser pipeline.
- Workspace cache persistence across unrelated chats or VM resets is not guaranteed.
- Plugin hooks and sub-agents do not run in ordinary chat. The current plugin package is only a wrapper around the Skill.

### Claude Code

- The CLI and optional hooks run locally.
- Hooks can transform supported tool output before it becomes model-visible.
- Current hooks do not implement generic MCP, web, shell, or conversation-history compaction.
- Local archives and caches are unencrypted and must be protected by the user.

## Design invariants

- Original source files remain untouched.
- A cached derivative never replaces the authoritative source.
- Any omitted output has a recovery reference or the transformation is not applied.
- Unknown and ambiguous content is unchanged.
- Failures, warnings, diffs, structured data, and likely secrets are not compacted by generic rules.
- No model call is used for hashing, chunking, lexical ranking, or the current hook transformations.
- Token savings, financial savings, and answer quality are measured independently.
- No global savings percentage is published without controlled A/B evidence.

## Planned expansion (not implemented)

- OCR and image/page-region processing.
- More complete document extraction and source maps.
- Schema-aware MCP and tool-result adapters.
- Better code structure and retrieval.
- Session/context evaluation for Claude Code's supported compaction features.
- Reproducible task-quality and cost benchmarks.
- User-facing usage diagnostics and practical Claude setup guidance.

See the consumption strategy in docs/CONSUMPTION-STRATEGY.md for priorities, evaluation rules, and the roadmap.
