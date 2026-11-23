# Release process

This document describes the release workflow and the checks required before distribution. A version tag triggers GitHub Actions to run tests, rebuild both Claude archives, generate SHA-256 checksums, and publish a GitHub Release.

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

1. Merge the approved release work into `main`.
2. Confirm the full CI matrix and OCR/vision integration pass on the exact `main` commit.
3. Confirm the package, Plugin, marketplace, and changelog versions match.
4. Create and push the version tag (for this release: `v0.6.0`) on the verified `main` commit.
5. The `release.yml` workflow reruns the test suite, validates and rebuilds both archives, creates `SHA256SUMS.txt`, and publishes the GitHub Release with all three assets.
6. Verify the release page, archive downloads, checksums, and installation instructions.

Never publish a tag from an unverified commit. The workflow uses `GITHUB_SHA` as the release target when it needs to create a missing tag.

## Distribution notes

- Claude.ai Skill upload: use `fidelityflow-claude-ai.zip`.
- Claude.ai custom Plugin upload: use `fidelityflow-plugin.zip` only if that upload option is available to the account.
- Claude Code local Skill/runtime: use the repository installer documented in README.
- Claude Code marketplace install: `claude plugin marketplace add muhammadgamaleid/FidelityFlow`, then `claude plugin install fidelityflow@fidelityflow --scope user`.
- Claude Code local Plugin testing: use `claude --plugin-dir .` from the repository root.

Claude's third-party plugin distribution policies may change. Verify the current official documentation before promising a public marketplace installation route.
