# Claude platform setup and installation

This guide separates Claude platform capabilities from the local FidelityFlow runtime. Interface labels and account availability can change; follow the current Claude UI and organization policy when they differ.

## Claude.ai — upload the Skill

Custom Skills are uploaded as ZIP files. Code execution and file creation must be enabled.

1. Download `fidelityflow-claude-ai.zip` from the [latest FidelityFlow release](https://github.com/muhammadgamaleid/FidelityFlow/releases/latest), or build it locally with `python build_release.py --check`.
2. Open Claude.ai and go to **Settings → Capabilities**.
3. Enable **Code execution and file creation** (the label may appear as **Create and edit files**).
4. Open **Customize → Skills**.
5. Select **+ → Create skill → Upload a skill**.
6. Upload `fidelityflow-claude-ai.zip`.
7. Enable FidelityFlow in the Skills list.
8. Start a new conversation and test it with a source file accessible to the Skill workspace.

Skills are listed for Free and paid Claude plans, subject to current feature availability and organization policies. Enterprise owners may need to enable Skills and Code execution and file creation in organization policy.

Official reference: [Use Skills in Claude](https://support.claude.com/en/articles/12512180-use-skills-in-claude).

## Claude.ai — upload the Plugin

This route applies only when custom Plugin upload is available in the user's account.

1. Download `fidelityflow-plugin.zip` from the [latest release](https://github.com/muhammadgamaleid/FidelityFlow/releases/latest).
2. Open **Customize → Plugins**.
3. Choose the custom Plugin upload action.
4. Upload the ZIP and review its details.
5. Enable FidelityFlow.
6. Keep Code execution and file creation enabled for Skill file-processing workflows.

The current Plugin bundles the Skill only. It does not include a hosted MCP server or Claude.ai chat hooks. Plugin availability and upload controls are determined by Anthropic and organization administrators; if the upload option is absent, use the Skill ZIP instead.

## Claude Code — install the Skill and local runtime

Requirements: Claude Code, Python 3.10+, and Git.

From a terminal:

~~~bash
git clone https://github.com/muhammadgamaleid/FidelityFlow.git
cd FidelityFlow
python -m pip install -e ".[pdf]"
fidelityflow doctor
python install.py --scope user
~~~

Restart Claude Code or start a new session. The Skill is copied to `~/.claude/skills/fidelityflow` for the current user.

To enable optional hooks:

~~~bash
python install.py --scope user --enable-output-hook
~~~

Review `~/.claude/settings.json`, its backup, and the scripts under `~/.claude/hooks/fidelityflow/`. The installer merges its registrations rather than replacing the complete settings file. Hooks are opt-in; local caches and output archives are unencrypted.

To install the Skill into the current project instead of the user account:

~~~bash
python install.py --scope project
~~~

This copies the Skill under the project's `.claude/skills/fidelityflow` directory. Machine-specific hooks are user-scope only.

## Claude Code — install the Plugin from GitHub

The repository includes `.claude-plugin/marketplace.json`. If the repository is reachable to your Git credentials (private repositories require access), install it from a terminal:

~~~bash
claude plugin marketplace add muhammadgamaleid/FidelityFlow
claude plugin install fidelityflow@fidelityflow --scope user
claude plugin list
~~~

To update or remove it:

~~~bash
claude plugin update fidelityflow@fidelityflow
claude plugin uninstall fidelityflow@fidelityflow
~~~

The Plugin provides the Skill component. It does not install the Python runtime or activate the optional Python hooks; use the installer above for those capabilities.

To load a local checkout for one development session without installing it:

~~~bash
claude --plugin-dir .
~~~

See the official [Claude Code plugin installation guide](https://code.claude.com/docs/en/plugins/install) and [marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference).

## Optional local OCR and visual candidates

Install the optional Python packages:

~~~bash
python -m pip install -e ".[ocr,vision]"
fidelityflow doctor
~~~

Install the Tesseract executable and language packs separately. For Arabic and English, install both language datasets and use:

~~~bash
fidelityflow ingest "scanned-report.pdf" --ocr --ocr-lang ara+eng
fidelityflow ingest "screenshot.png" --ocr --ocr-lang ara+eng
~~~

OCR and OpenCV visual analysis are local CLI features. Claude.ai's managed workspace does not guarantee Tesseract, language packs, OpenCV, or native dependencies.

## Use the workflow effectively

- Put recurring reference material in Claude Projects and Project Knowledge where appropriate.
- Keep project instructions short and stable.
- Search indexed files first and retrieve only the chunks needed for the task.
- Use native Claude document/vision handling for consequential visual interpretation, charts, and exact spreadsheet calculations.
- In Claude Code, use `/context` and `/usage` when available; use `/clear` for unrelated work and `/compact` when continuing a task.
- Disable MCP servers that are not needed.
- Do not reduce reasoning effort for security, architecture, or data-critical tasks solely to save usage.

## Boundaries

FidelityFlow does not modify Claude pricing, subscription limits, model selection, thinking budgets, prompt-cache policy, automatic compaction thresholds, or Claude.ai's initial upload pipeline. It does not promise a token-saving percentage before controlled measurement.
