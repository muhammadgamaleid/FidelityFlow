#!/usr/bin/env python3
"""Build and validate the upload-ready Claude Skill archive."""

from __future__ import annotations
import argparse
import re
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
SKILL_ROOT = ROOT / "skills" / "fidelityflow"
DEFAULT_OUTPUT = ROOT / "dist" / "fidelityflow-claude-ai.zip"
REQUIRED = {
    "LICENSE", "SKILL.md", "scripts/fidelityflow.py",
    "references/file-processing.md", "references/output-compaction.md",
    "references/platform-setup.md", "references/quality-policy.md",
    "references/architecture.md", "references/learning-memory.md",
}


def validate_source() -> list[Path]:
    if not SKILL_ROOT.is_dir():
        raise FileNotFoundError(f"Skill source directory not found: {SKILL_ROOT}")
    skill_file = SKILL_ROOT / "SKILL.md"
    if not skill_file.is_file():
        raise FileNotFoundError("skills/fidelityflow/SKILL.md is required")
    text = skill_file.read_text(encoding="utf-8")
    description = next((line.split(":", 1)[1].strip() for line in text.splitlines()
                        if line.startswith("description:")), None)
    if not description:
        raise ValueError("SKILL.md must define a non-empty description")
    if len(description) > 200:
        raise ValueError(f"SKILL.md description is {len(description)} characters; maximum is 200")
    for link in re.findall(r"\]\(([^)]+)\)", text):
        target = link.strip().split("#", 1)[0]
        if not target or target.startswith(("https://", "http://", "mailto:")):
            continue
        if not (SKILL_ROOT / target).resolve().is_file():
            raise ValueError(f"Broken relative link in SKILL.md: {link}")

    mirrors = (
        ("LICENSE", ROOT / "LICENSE"),
        ("references/architecture.md", ROOT / "docs" / "ARCHITECTURE.md"),
        ("references/learning-memory.md", ROOT / "docs" / "LEARNING-MEMORY.md"),
    )
    for relative, canonical in mirrors:
        packaged = SKILL_ROOT / relative
        if not canonical.is_file() or not packaged.is_file():
            raise FileNotFoundError(f"Missing canonical or packaged document: {relative}")
        if packaged.read_bytes() != canonical.read_bytes():
            raise ValueError(f"{relative} is out of sync with {canonical.relative_to(ROOT)}")

    files = []
    for path in sorted(SKILL_ROOT.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            files.append(path)
    missing = sorted(REQUIRED - {p.relative_to(SKILL_ROOT).as_posix() for p in files})
    if missing:
        raise FileNotFoundError("Skill package is incomplete: " + ", ".join(missing))
    return files


def build(output: Path) -> None:
    files = validate_source()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp",
                                     dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in files:
                relative = path.relative_to(SKILL_ROOT).as_posix()
                archive.write(path, f"fidelityflow/{relative}")
        with zipfile.ZipFile(temporary, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError(f"ZIP integrity check failed at {bad_member}")
            names = set(archive.namelist())
            for relative in REQUIRED:
                if f"fidelityflow/{relative}" not in names:
                    raise ValueError(f"Built ZIP is missing fidelityflow/{relative}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="validate all Skill sources, build the archive, and verify its contents")
    args = parser.parse_args(argv)
    try:
        build(args.output.expanduser().resolve())
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Release build failed: {exc}\n")
    print(f"Skill archive {'validated and built' if args.check else 'built'}: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
