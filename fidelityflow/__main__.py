#!/usr/bin/env python3
"""Unified command-line entry point for FidelityFlow."""

from __future__ import annotations

import sys

from . import __version__
from .learning.cli import main as learning_main

LEARNING_COMMANDS = {
    "observe", "recall", "candidates", "confirm", "retire", "forget", "stats",
}
FILE_COMMANDS = {
    "doctor", "ingest", "ingest-dir", "list", "search", "show",
    "show-archive", "search-archive",
}


def _help() -> None:
    print(f"""FidelityFlow {__version__}

Unified file processing and evidence-backed project memory.

Usage:
  fidelityflow <command> [options]

File processing:
  doctor          Check Python runtime and optional extractors
  ingest          Extract and cache one source file
  ingest-dir      Recursively index a directory
  list            List indexed documents
  search          Search indexed document chunks
  show            Retrieve a complete indexed chunk
  show-archive    Recover an archived Bash output
  search-archive  Search an archived Bash output

Project memory:
  observe         Record a fact with evidence
  recall          Recall confirmed facts
  candidates      List facts awaiting confirmation
  confirm         Manually resolve a conflicting fact
  retire          Retire a fact
  forget          Delete this project's learned data
  stats           Show local memory counts

Run 'fidelityflow <command> --help' for command-specific options.
For PDF text extraction, install: python -m pip install 'fidelityflow[pdf]'. For local image/scanned-PDF OCR, install the [ocr] extra and the Tesseract executable plus language data.
""")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        _help()
        return 0
    if args[0] in {"--version", "-V"}:
        print(__version__)
        return 0

    command = args[0]
    if command in LEARNING_COMMANDS:
        return learning_main(args)
    if command in FILE_COMMANDS:
        # The Skill CLI remains standalone for Claude.ai; this import reuses
        # the same tested implementation for the installed Python package.
        from skills.fidelityflow.scripts.fidelityflow import main as file_main
        return file_main(args)

    print(f"fidelityflow: unknown command '{command}'", file=sys.stderr)
    _help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
