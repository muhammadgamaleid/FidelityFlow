# Claude platform setup and optimization checklist

## Claude.ai

1. In Settings → Capabilities, enable **Code execution and file creation**. Skills require code execution; current labels can vary slightly by account.
2. Open Customize → Skills → Create skill → Upload a skill.
3. Upload `dist/fidelityflow-claude-ai.zip`, then enable FidelityFlow.
4. Create one Claude Project per coherent research/library subject. Upload source documents once to Project Knowledge; do not reattach the same source in every chat.
5. Keep Project Instructions short and stable. Put long reference material in Project Knowledge.
6. Use descriptive filenames and separate unrelated libraries into different Projects.
7. For a long source file exposed in Claude's VM, run the Skill's bundled CLI (`fidelityflow/scripts/fidelityflow.py`) with the exact file path. Extract once, search bounded excerpts, and open only relevant full chunks. The script source itself is not loaded into model context; only command output is.
8. Store `.fidelityflow/cache` in a writable task/project workspace, not the Skill folder. Reuse it while the workspace persists; do not assume cross-chat or post-reset persistence.
9. Let native Project retrieval handle recurring library search when it is available. Do not build a duplicate full-library index without a measured need.
10. Claude's built-in document skills can process Word, Excel, PowerPoint, and PDF. Prefer them for fidelity-sensitive layout, charts, visual PDF interpretation, and consequential spreadsheet calculations. FidelityFlow extraction is a searchable derivative, not a replacement.

**Boundary:** Claude.ai controls its initial upload/parser pipeline. A custom Skill cannot intercept it or guarantee the initial attachment avoids context/token accounting. It can, however, execute bundled scripts in the Skill VM and avoid repeatedly printing/reading the full source after the path is exposed. Local cache persistence across unrelated chats is not guaranteed.

## Claude Code

1. Install the Skill using `python install.py --scope user` or copy `skills/fidelityflow/` to `~/.claude/skills/fidelityflow/`.
2. Start a new Claude Code session and verify the Skill is available. Run `/skills`.
3. Run `python install.py --scope user --enable-output-hook` only if you explicitly want the optional exact duplicate-Read suppression and reversible test-output hooks. The installer registers `PostToolUse` for `Read|Bash`, plus `PreCompact`, `SessionEnd`, and `SessionStart` (matcher `clear`) cleanup handlers. Read dedup alternates one suppressed repeat with one full recovery read. It updates `~/.claude/settings.json` after backing it up and preserves unrelated hooks/settings.
4. Verify the hooks with `/hooks`. Test them on a repeated large file read and a known verbose passing test run. Confirm that a read after `/compact` is returned in full again.

### Native settings and habits that save usage

- Keep `CLAUDE.md` focused on always-relevant project facts. Move task-specific workflows into Skills so they load only when needed; aim to keep `CLAUDE.md` under 200 lines.
- Use `/context` to find what occupies the context window and `/usage` to inspect usage. Re-check after adding MCP servers or Skills.
- Use `/clear` when switching to an unrelated task. Use `/compact` only when continuing the same task, and state what must be preserved (requirements, decisions, file paths, tests, unresolved questions).
- Leave prompt caching and auto-compaction enabled unless there is a measured reason to change them.
- Disable MCP servers you are not using (`/mcp`). Prefer a CLI command or a narrow script over loading several large tool schemas when appropriate.
- Ask for targeted file reads, symbol searches, and bounded line ranges rather than dumping entire directories or huge files.
- Choose `/model` and `/effort` according to task difficulty. Use lower effort for routine changes; do not reduce reasoning effort for architecture, security, financial, scientific, or high-stakes analysis merely to save tokens.
- Before starting a new large task, ask Claude to make a short plan and identify the exact files/data it needs. Do not ask it to summarize every source preemptively.

### What this project does not change

FidelityFlow does not change model selection, thinking budgets, Anthropic billing, prompt-cache policy, automatic compaction thresholds, or the content of user deliverables. It adds a local file index/cache and opt-in exact Read deduplication plus a narrow successful test-output hook.


For automated user-level installation, run python install.py --scope user. To register all optional Claude Code hooks, run python install.py --scope user --enable-output-hook. Add --hook-only when the Skill is already installed and only hook registration is required. The installer validates existing settings before writing and backs up settings.json before merging.
