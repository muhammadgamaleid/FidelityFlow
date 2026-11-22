# FidelityFlow v0.3.1
**Unified Context & Project Learning Toolkit for Claude.ai & Claude Code**

---

## 🎯 Goals at a Glance

| Capability | Claude.ai | Claude Code |
|------------|-----------|-------------|
| **File Indexing & Search** | ✅ Available | ✅ Available |
| **Direct Memory Persistence** | ❌ (Temporary VM scope) | ✅ Persistent SQLite |
| **Evidence-Backed Project Memory** | ⚠️ Limited (requires manual `fflearn`) | ✅ Full (multi-session verification) |
| **CLI Commands** | ✅ As a bundled Skill | ✅ Native CLI (`fidelityflow`, `fflearn`) |
| **Cross-Session Fact Storage** | ⚠️ Lost on VM reset | ✅ Stored in `~/.fidelityflow/learning.sqlite3` |
| **Security Awareness** | ✅ Context-based | ✅ Context-based |

---

## 📦 About FidelityFlow

FidelityFlow v0.3.0 unifies two powerful eras:

1. **File Processing & Caching** *(from v0.1.0)*  
   Extracts, indexes, and searches large documents (PDF, DOCX, XLSX, PPTX, Markdown…) without re-reading unchanged files.

2. **Evidence-Backed Project Memory** *(from v0.2.0 + new 0.3.0 integration)*  
   Records, verifies, and recalls verified project facts across **independent Claude sessions** using SQLite.

3. **Output Archiving (opt-in)**  
   Preserves raw stdout before compacting detected successful test runs.

**Core Philosophy:** Never shrink, truncate, or discard requested depth. FidelityFlow removes only verifiable redundancy.

---

## 🧑‍💻 Getting Started

### A. On Claude.ai (Web App)

1. **Enable capabilities:**  
   **Settings → Capabilities** → enable **Code execution & file creation**.
2. **Install the Skill:**  
   - From the FidelityFlow repository checkout, run `python build_release.py --check`.
   - Click **Customize → Skills → Create skill** and upload `dist/fidelityflow-claude-ai.zip`.
   - Enable FidelityFlow.
3. **Use in chat:**
   ```bash
   python fidelityflow/scripts/fidelityflow.py ingest "/exact/path/to/report.pdf"
   python fidelityflow/scripts/fidelityflow.py search --query "revenue projection" --top-k 3
   ```
   > ⚠️ Cache lifetime is limited to the current VM session. For persistent memory, use Claude Code or native Project Knowledge.

---

### B. On Claude Code (CLI)

```bash
cd FidelityFlow
python -m pip install -e ".[pdf]"
```

Verify and start:
```bash
fidelityflow doctor
fidelityflow ingest docs/architecture.docx
fidelityflow search --query "performance obligations"
```

Enable optional hooks (read-dedup, test-archive):
```bash
python install.py --scope user --enable-output-hook
```

---

## 🔧 Detailed Capabilities

### File Indexing (`ingest` + `search`)
- **Formats:** PDF (via `pypdf`), DOCX, XLSX, PPTX, CSV/TSV, Markdown, JSON, YAML, source code, plain text.
- **Caching:** Content-addressed via SHA-256 + extractor version. Unchanged files return `cache_hit`.
- **Search:** Lexical BM25-style over extracted chunks.

```bash
fidelityflow ingest-dir "./research-library"
fidelityflow search --query "API key rotation" --top-k 5
```

---

### Memory Retention (`fflearn observe` + `recall`)  <!-- NEW IN 0.3.0 -->
- Facts are stored in `~/.fidelityflow/learning.sqlite3`.
- **Multi-session verification:** Requires observations from 2+ independent sessions before promotion.
- **Contradiction handling:** Conflicting values are suspended until human confirmation.

```bash
export CLAUDE_SESSION_ID="session-$(date +%s)"

# Observe a fact
fflearn observe \
  --key test.command \
  --value "pytest -q" \
  --evidence "Exit code 0; all tests passed"

# List pending candidates
fflearn candidates

# Manually confirm
fflearn confirm --key test.command --value "pytest -q"

# Recall confirmed facts
fflearn recall
```

---

### Output Archiving (opt-in hook)
When the optional `PostToolUse` hook is enabled:

```bash
# View archived stdout
fidelityflow show-archive --ref "pytest output"
fidelityflow search-archive --ref "pytest output" --query "FAILED test_xyz"
```

---

## ⚙️ Common Commands

| Command | Description |
|---------|-------------|
| `fidelityflow doctor` | Check runtime and dependencies |
| `fidelityflow ingest <file>` | Extract and index a file |
| `fidelityflow ingest-dir <dir>` | Batch index with exclusion of `.git`, `.venv`, etc. |
| `fidelityflow search --query "text"` | Search content in indexed files |
| `fflearn observe --key K --value V --evidence E` | Record a verified fact |
| `fflearn recall` | Recall confirmed facts |
| `fflearn candidates` | List pending confirmation candidates |
| `fflearn confirm --key K --value V` | Manually confirm a candidate |
| `fidelityflow show-archive --ref ID` | View archived stdout |
| `fidelityflow search-archive --ref ID --query Q` | Search archived output |

---

## 🧪 Known Limitations

| Category | Limitation |
|----------|------------|
| OCR-scanned PDFs | Require external OCR tools |
| Visual layout & graphics | May lose non-text representation |
| Cache in Claude.ai | Lost on VM reset; migrate to Claude Code for persistence |
| Evidence requirement | Facts need **2+ independent sessions** for automatic promotion |

---

## 🔐 Privacy & Safety

- **Local-only storage** — No network calls, no telemetry, no cost.
- **Fail-open design** — Unknown or ambiguous output is never transformed.
- **Sensitive data redaction** — Best-effort masking of API keys, tokens, passwords before storage.
- **Double-verification** — Facts are stored only after independent confirmation from ≥2 sessions.

---

## 📚 Documentation

- [Architecture Overview](docs/ARCHITECTURE.md)
- [Learning Memory Design](docs/LEARNING-MEMORY.md)
- [File Processing Limits](skills/fidelityflow/references/file-processing.md)
- [Output Compaction Policy](skills/fidelityflow/references/output-compaction.md)

---

## 📄 License

**MIT License** — See [LICENSE](LICENSE).

---

## 🚀 Quick Setup (Code Example)

```bash
git clone https://github.com/muhammadgamaleid/FidelityFlow.git
cd FidelityFlow
python -m pip install -e ".[pdf]"

# Check the environment
fidelityflow doctor

# Index documents
fidelityflow ingest "/path/to/reports/annual-2025.pdf"
fidelityflow ingest-dir "./research-library"

# Search indexed content
fidelityflow search --query "revenue projection" --top-k 3

# Record verified facts (requires CLAUDE_SESSION_ID)
export CLAUDE_SESSION_ID="session-$(date +%s)"
fflearn observe \
  --key test.command \
  --value "pytest -q" \
  --evidence "Exit code 0; all tests passed"

# Retrieve confirmed facts
fflearn recall
```

---

**This README targets both non-technical users (via Claude.ai) and technical developers (via CLI).** Features are clearly labeled where they are fully functional versus limited by platform scope.

### Release validation

Run `python build_release.py --check` to validate Skill references and create `dist/fidelityflow-claude-ai.zip`. Install the optional Claude Code hooks with `python install.py --scope user --enable-output-hook`. Use `--hook-only` to install hooks without copying the Skill.
