# Release process

This document describes how to prepare and verify a FidelityFlow release. It does not publish a GitHub Release or merge a pull request automatically.

## Version source

For a normal release, keep these values aligned:
- `pyproject.toml` `[project].version`
- `fidelityflow/__init__.py` `__version__`
- `.claude-plugin/plugin.json` `version`
- `CHANGELOG.md` release heading

The Skill name is stable and intentionally does not carry a separate version field in its frontmatter.

## Build locally

Use Python 3.10+:

```bash
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python build_release.py --check
python -m pip wheel . --no-deps --wheel-dir wheelhouse
```

The release builder validates Skill frontmatter, required files, relative references, canonical documentation mirrors, Plugin metadata, and ZIP integrity. It produces:

- `dist/fidelityflow-claude-ai.zip`
- `dist/fidelityflow-plugin.zip`

## GitHub release checklist

1. Review the release branch and ensure the intended changes are included.
2. Run the full test suite and release archive validation.
3. Confirm the package, Plugin, and changelog versions match.
4. Review both ZIP archives and test the Skill upload and Plugin load path.
5. Open/update the pull request and wait for all required CI jobs.
6. After approval, merge the pull request according to the repository's release policy.
7. Create a GitHub Release with tag `v0.6.0`, title `FidelityFlow v0.6.0`, and the matching changelog notes.
8. Attach both ZIP files from `dist/` to the GitHub Release.
9. Verify the release download links and installation instructions.

Do not create a tag or publish an archive until the release branch has passed CI and the maintainer has approved the release.

## Distribution notes

- Claude.ai Skill upload: use `fidelityflow-claude-ai.zip`.
- Claude.ai custom Plugin upload: use `fidelityflow-plugin.zip` only if that upload option is available to the account.
- Claude Code local Skill/runtime: use the repository installer documented in README.
- Claude Code marketplace install: `claude plugin marketplace add muhammadgamaleid/FidelityFlow`, then `claude plugin install fidelityflow@fidelityflow --scope user`.
- Claude Code local Plugin testing: use `claude --plugin-dir .` from the repository root.

Claude's third-party plugin distribution policies may change. Verify the current official documentation before promising a public marketplace installation route.
