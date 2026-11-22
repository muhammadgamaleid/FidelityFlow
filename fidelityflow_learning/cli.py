"""Backward-compatible CLI import for the former fidelityflow_learning package."""

from fidelityflow.learning.cli import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main())
