# Contributing to FidelityFlow

Thanks for helping improve FidelityFlow. The project prioritizes measurable Claude usage reduction without loss of task quality.

## Development setup

- Python 3.10 or newer.
- Git.
- Optional system dependencies only when testing their feature (for example, Tesseract for OCR).

Create an environment and install the development dependencies:

```bash
python -m venv .venv
# Activate the environment, then:
python -m pip install -e ".[dev]"
```

For optional features, install the matching extra:

```bash
python -m pip install -e ".[pdf]"
python -m pip install -e ".[ocr]"
```

## Validate changes

Run the complete test suite and validate both Claude upload archives:

```bash
python -m unittest discover -s tests -v
python build_release.py --check
python -m fidelityflow --version
fidelityflow doctor
```

OCR tests that require optional dependencies may be skipped when those dependencies are not installed. Do not treat a skipped integration test as proof that the external executable or language data is configured correctly.

## Contribution principles

1. Preserve original files and make every transformation recoverable where content is omitted.
2. Fail open for unknown, ambiguous, failed, structured, or sensitive content.
3. Add regression tests for behavior changes and safety boundaries.
4. Do not report token or cost savings from character counts, cache hits, or estimates.
5. Keep documentation, the packaged Skill references, and release metadata synchronized.
6. Do not add network calls or model-assisted preprocessing without documenting the privacy, cost, and measurement implications.

## Reporting issues

Include the Python version, operating system, installation path, exact command, relevant sanitized logs, and whether optional dependencies are installed. Never include API keys, credentials, private source files, or unredacted sensitive transcripts.
