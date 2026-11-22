# Architecture

## Goals

FidelityFlow v0.3.1 targets both **Claude.ai** and **Claude Code**. It optimizes avoidable context overhead while preserving the requested deliverable. The product deliberately avoids a universal lossy compressor: output semantics vary by command, file type, and task, so unknown material is left untouched.

## Unified Architecture

```text
User Request
    │
    ├──▶ File Processing Path (Claude.ai + Claude Code)
    │       ├── Extract & index supported formats
    │       ├── Content-addressed cache (SHA-256 + extractor version)
    │       ├── Lexical search over chunk offsets
    │       └── Retrieve bounded excerpts on demand
    │
    ├──▶ Context Optimization Path (Claude Code only, opt-in)
    │       ├── PostToolUse Read: exact same-file/range/bytes dedup within context epoch
    │       ├── PostToolUse Bash: archive + compact recognized successful test rows
    │       ├── PreCompact: clear all agent markers before summarization
    │       ├── SessionEnd: clear per-session agent markers
    │       └── SessionStart (clear): clear after /clear
    │
    └──▶ Project Memory Path (Claude Code only)
            ├── SessionStart hook: inject up to 8 confirmed facts via additionalContext
            ├── PostToolUse Bash: observe allowlisted successful test/build/lint commands
            ├── Evidence-based promotion (2 independent sessions minimum)
            ├── Contradiction suspension until human confirmation
            └── Local SQLite with best-effort redaction
```

## Components

### 1. Skill (`skills/fidelityflow/SKILL.md`)

The Skill is intentionally small. It contains routing policy, platform boundaries, and quality contract. Detailed guidance is split into reference files so the model does not need to read every document for every task.

### 2. Bundled File CLI (`skills/fidelityflow/scripts/fidelityflow.py`)

Python standard library only (optional `pypdf` for PDF). No network calls. Never modifies original source files. Runs in:
- **Claude.ai Skill VM:** when source file is exposed to the VM filesystem
- **Claude Code:** locally with persistent project/user cache

**Cache structure (content-addressed):**
```
.fidelityflow/
  cache/
    documents/<cache-key>/
      manifest.json
      content.txt        # extracted text stored once
      chunks.jsonl       # offsets, metadata, term frequencies only
  archive/
    <tool-use-ref>.txt   # original stdout for recovery

~/.claude/fidelityflow/read-dedup/
  <session-hash>/
    <agent-hash>/
      <request-response-hash>.seen
```

Each cache entry is content-addressed by source SHA-256 + extractor version. Re-ingesting an unchanged file with the same extractor is a cache hit.

### 3. Learning Module (`fidelityflow/learning/`)

Local SQLite database at `~/.fidelityflow/learning.sqlite3` (override via `FIDELITYFLOW_HOME`).

**Schema:**
- `metadata`: schema version
- `observations`: raw evidence records (session_id, source, evidence, evidence_hash)
- `facts`: promoted facts with status (candidate/active/retired)

**State Machine:**
```
candidate → active → retired
```

Promotion requires distinct session IDs (default min 2). Contradictions suspend auto-promotion. Values and evidence are length-limited and redacted.

### 4. Exact Read Deduplication & Reversible Output Hook

Optional `PostToolUse` handler for `Read|Bash`:

**Read:** Stores SHA-256-derived marker scoped to session + agent + normalized path + offset/limit + exact returned bytes. First result passes through; one byte-identical repeat may become a short pointer; the next identical repeat passes through in full as recovery safeguard. `PreCompact`, `SessionEnd`, and `SessionStart` after `/clear` clear the entire session tree across agents.

**Bash:** Compacts only recognized successful test output (pytest, unittest, Go test, Cargo test). Archives exact UTF-8 stdout locally first. Failed executions, stderr, unknown commands, diffs, structured data, detected secrets, and ambiguous outputs pass through unchanged.

### 5. Benchmark Telemetry

The project does not estimate Claude token counts from character length. `benchmarks/read_claude_usage.py` reads usage fields present in local Claude Code JSONL transcript records, including cache creation and cache read separately. If the transcript schema lacks usage fields, it reports this rather than inventing data.

## Design Invariants

- Original files are never modified
- A summary is an index, not a replacement for source
- Exact duplicate Read suppression leaves the first full result in the current context epoch and alternates a skipped duplicate with a full recovery read; test-output compaction archives exact UTF-8 stdout received in the hook event locally
- Unknown output is unchanged
- Failure output is unchanged
- Structured data and diffs are unchanged
- No LLM call is used for hashing, text extraction, chunking, lexical ranking, or hook transformation
- Token savings and output quality are measured independently

## Platform Boundaries

- **Claude.ai:** Bundled Skill scripts run in its VM, but cannot intercept the platform's initial attachment ingestion or guarantee cache persistence across unrelated chats
- **Claude Code:** Local CLI and hooks persist in the project/user environment. Hook behavior is intentionally opt-in
- **Both:** No global percentage saving claim is made until model-level A/B benchmarks are run on the same tasks, model, cache conditions, and quality rubric

## Deliberate Non-Goals in v0.3.1

- No semantic embedding model or hosted vector database
- No GraphRAG engine or full knowledge graph
- No OCR, speech recognition, or video understanding
- No local code AST graph; use Claude Code's native code intelligence for that
- No generic shell output rewriting or arbitrary source-code compression
- No automatic reduction of user-requested book, report, code, or spreadsheet content

## Packaging and CLI Integration

The maintained Learning implementation is fidelityflow/learning/. The former fidelityflow_learning package is a backwards-compatible import shim; it does not contain a second copy of the implementation.

The installed fidelityflow command and python -m fidelityflow dispatch file commands to the Skill's tested file-processing engine and memory commands to the Learning CLI. The skills namespace is included in the Python distribution so this routing also works after wheel installation.

install.py installs the Claude Skill and, when requested, registers optional hooks while preserving existing Claude settings. build_release.py validates relative Skill references and builds dist/fidelityflow-claude-ai.zip. The GitHub Actions workflow tests supported Python versions and builds a wheel.
