#!/usr/bin/env python3
"""Entry point for FidelityFlow v0.3.0 as a unified command-line tool.

Combined functionality:
- File extraction, indexing, and search (from core file processing)
- Evidence-backed project memory (from learning module)
"""

import argparse
import sys
from pathlib import Path

# Import from learning module
sys.path.insert(0, str(Path(__file__).resolve().parent / "learning"))


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fidelityflow",
        description="Unified tool for file processing, indexing, and project learning."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Learning commands (from fidelityflow_learning.cli)
    obs = sub.add_parser("observe", help="Record a small fact with evidence")
    obs.add_argument("--key", required=True, help="Fact identifier (e.g., test.command)")
    obs.add_argument("--value", required=True, help="The fact/value to record")
    obs.add_argument("--session", default=None, help="Session ID (or set CLAUDE_SESSION_ID)")
    obs.add_argument("--source", default="manual", help="Source of the observation")
    obs.add_argument("--evidence", required=True, help="Evidence supporting the fact")
    obs.add_argument("--min-sessions", type=int, default=2, help="Sessions needed for promotion (2-10)")

    recall = sub.add_parser("recall", help="Recall confirmed project facts")
    recall.add_argument("--query", default="", help="Optional search query")
    recall.add_argument("--limit", type=int, default=12, help="Max results (1-30)")

    sub.add_parser("candidates", help="List facts awaiting confirmation")

    confirm = sub.add_parser("confirm", help="Manually confirm a candidate")
    confirm.add_argument("--key", required=True)
    confirm.add_argument("--value", required=True)

    retire = sub.add_parser("retire", help="Retire an outdated fact")
    retire.add_argument("--key", required=True)
    retire.add_argument("--value")

    forget = sub.add_parser("forget", help="Delete this project's learned data")
    forget.add_argument("--key")

    sub.add_parser("stats", help="Show local counts")

    # File processing commands
    doctor = sub.add_parser("doctor", help="Check runtime and extractor availability")
    doctor.add_argument("--cache-dir", help="Cache directory path")

    ingest = sub.add_parser("ingest", help="Extract and cache a source file")
    ingest.add_argument("path", help="Path to the file")
    ingest.add_argument("--cache-dir", help="Cache directory")
    ingest.add_argument("--chunk-chars", type=int, default=7000, help="Chunk size in characters")

    ingest_dir = sub.add_parser("ingest-dir", help="Recursively ingest supported files")
    ingest_dir.add_argument("path", help="Root directory")
    ingest_dir.add_argument("--cache-dir", help="Cache directory")
    ingest_dir.add_argument("--chunk-chars", type=int, default=7000, help="Chunk size")

    search = sub.add_parser("search", help="Search cached files")
    search.add_argument("--query", required=True, help="Search query")
    search.add_argument("--top-k", type=int, default=5, help="Max results")
    search.add_argument("--max-chars", type=int, default=1600, help="Max chars per result")
    search.add_argument("--cache-dir", help="Cache directory")

    show = sub.add_parser("show", help="Show a cached chunk")
    show.add_argument("--document", required=True, help="Document ID")
    show.add_argument("--chunk", type=int, required=True, help="Chunk index")
    show.add_argument("--cache-dir", help="Cache directory")

    args = parser.parse_args(argv)

    if args.command in ("observe", "recall", "candidates", "confirm", "retire", "forget", "stats"):
        from fidelityflow_learning.cli import main as learn_main
        return learn_main(argv)

    if args.command == "doctor":
        from skills.fidelityflow.scripts.fidelityflow import make_parser, main as ff_main
        return ff_main(["doctor", "--cache-dir", args.cache_dir] if args.cache_dir else ["doctor"])

    print(f"Command {args.command} not configured at package level.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())