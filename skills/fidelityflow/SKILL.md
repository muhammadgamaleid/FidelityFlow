---
name: fidelityflow
description: Unified file processing, caching, and evidence-backed project memory for Claude.ai and Claude Code. v0.3.0
---

# FidelityFlow v0.3.0

**Optimized context efficiency, never at the expense of user deliverables.**  
This version merges:
- **File indexing & caching** (v0.1.0): Extract, index, and search large documents without duplicating content.
- **Project memory** (v0.2.0): Evidence-backed SQLite facts that survive across sessions.

---

## Quick Start (Claude Code)

```bash
# Install the package
python -m pip install -e .

# Check runtime and extract a large report
python -m fidelityflow doctor
python -m fidelityflow ingest "reports/annual-2025.pdf"
python -m fidelityflow search --query "revenue projection"

# Observe and recall verified facts
python -m fidelityflow observe --key test.command --value "pytest -q" --session "$CLAUDE_SESSION_ID" --evidence "All tests passed"
python -m fidelityflow recall
```

---

## Quick Start (Claude.ai)

1. Ensure **Code execution and file creation** is enabled in Settings.
2. Upload the `skills/` folder as a Skill in Customize → Skills.
3. Run the bundled CLI when processing long text files is required.

```bash
python skills/fidelityflow/scripts/fidelityflow.py ingest "/exact/path/to/source.docx"
python skills/fidelityflow/scripts/fidelityflow.py search --query "specific question" --top-k 3
```

---

## Capabilities Matrix

| Capability | Claude.ai | Claude Code |
|---|---|---|
| **File extraction** (DOCX, XLSX, PPTX, PDF, text) | ✓ (in Skill VM) | ✓ (local) |
| **Content-addressed cache** | ✓ (workspace lifetime) | ✓ (project/user local) |
| **Lexical chunk search** | ✓ | ✓ |
| **Exact-read deduplication** | ✗ | ✓ (opt-in) |
| **Test-output compaction** | ✗ | ✓ (opt-in) |
| **Project memory** | ✗ | ✓ |
| **Evidence promotion** | ✗ | ✓ (2-session threshold) |
| **Contradiction suspension** | ✗ | ✓ |
| **Sensitive data redaction** | ✗ | ✓ |

---

## Project Memory (The new v0.3.0 feature)

FidelityFlow v0.3.0 introduces a **project-scoped SQLite learning ledger** at `~/.fidelityflow/learning.sqlite3`.

- Record facts only after observing them in **independent sessions**.
- A fact becomes **active** only after being supported in two distinct `CLAUDE_SESSION_ID`s.
- Conflicting observations suspend all active facts until you manually confirm the correct value.
- Facts can be retired (`retire`), forgotten (`forget`), or audited (`candidates`, `stats`).

**Example Workflow:**

```bash
# After a successful test run
python -m fidelityflow observe \
  --key test.command \
  --value "pytest -q" \
  --session "$CLAUDE_SESSION_ID" \
  --source manual \
  --evidence "Exit code 0, all 9 tests passed"

# List facts pending confirmation
python -m fidelityflow candidates

# Promote a candidate
python -m fidelityflow confirm --key test.command --value "pytest -q"
```

---

## Language Support

All components use **UTF-8 encoding** natively. FidelityFlow handles:
- Source code in any language (Python, JavaScript, Java, C++, Go, etc.)
- Natural language text (Arabic, Chinese, Russian, etc.)
- Mixed-language documents.

**Note:** Extracted text is a **derivative**, not a replacement. For visual/layout-sensitive tasks, use Claude’s native document skills.

---

## Privacy & Safety

- **Local-only storage**: No network calls, no telemetry, no model-side cost.
- **Fail-open design**: Unknown or ambiguous data is never transformed.
- **Evidence-based promotion**: Automatic learning only occurs after independent session verification.
- **Best-effort redaction**: API keys, tokens, emails, and passwords are masked before storage (not a guarantee).

---

## Load Details Only When Needed

- [File Processing Limits](references/file-processing.md)
- [Output Compaction Policy](references/output-compaction.md)
- [Quality Contract](references/quality-policy.md)
- [Platform Setup](references/platform-setup.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
- [Learning Memory Design](docs/LEARNING-MEMORY.md)

---

## License

MIT. See [LICENSE](LICENSE).