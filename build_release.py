#!/usr/bin/env python3
"""Validate and build upload-ready Claude Skill and Plugin archives."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
SKILL_ROOT = ROOT / "skills" / "fidelityflow"
PLUGIN_MANIFEST = ROOT / ".claude-plugin" / "plugin.json"
DEFAULT_SKILL_OUTPUT = ROOT / "dist" / "fidelityflow-claude-ai.zip"
DEFAULT_PLUGIN_OUTPUT = ROOT / "dist" / "fidelityflow-plugin.zip"

REQUIRED_SKILL_FILES = {
    "LICENSE",
    "SKILL.md",
    "scripts/fidelityflow.py",
    "references/file-processing.md",
    "references/output-compaction.md",
    "references/platform-setup.md",
    "references/quality-policy.md",
    "references/architecture.md",
    "references/learning-memory.md",
}


def _skill_metadata() -> tuple[str, str]:
    skill_file = SKILL_ROOT / "SKILL.md"
    if not skill_file.is_file():
        raise FileNotFoundError("skills/fidelityflow/SKILL.md is required")
    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not match:
        raise ValueError("SKILL.md must start with YAML frontmatter")
    fields = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"').strip("'")
    name = fields.get("name", "")
    description = fields.get("description", "")
    if not name or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("SKILL.md must define a valid kebab-case name")
    if not description:
        raise ValueError("SKILL.md must define a non-empty description")
    if len(description) > 200:
        raise ValueError(f"SKILL.md description is {len(description)} characters; maximum is 200")
    return name, description


def validate_skill_source() -> list[Path]:
    if not SKILL_ROOT.is_dir():
        raise FileNotFoundError(f"Skill source directory not found: {SKILL_ROOT}")
    _skill_metadata()
    text = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
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

    files = [
        path for path in sorted(SKILL_ROOT.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    ]
    present = {path.relative_to(SKILL_ROOT).as_posix() for path in files}
    missing = sorted(REQUIRED_SKILL_FILES - present)
    if missing:
        raise FileNotFoundError("Skill package is incomplete: " + ", ".join(missing))
    return files


def validate_plugin_source() -> dict:
    if not PLUGIN_MANIFEST.is_file():
        raise FileNotFoundError(".claude-plugin/plugin.json is required")
    try:
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid Plugin manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Plugin manifest must be a JSON object")
    name = manifest.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        raise ValueError("Plugin manifest name must be non-empty kebab-case")
    for field in ("displayName", "version", "description"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"Plugin manifest requires a non-empty {field}")
    skill_paths = manifest.get("skills")
    if isinstance(skill_paths, str):
        skill_paths = [skill_paths]
    if not isinstance(skill_paths, list) or not skill_paths:
        raise ValueError("Plugin manifest must declare at least one skills path")
    found_skill = False
    for raw_path in skill_paths:
        if not isinstance(raw_path, str) or not raw_path.startswith("./"):
            raise ValueError(f"Invalid Plugin skills path: {raw_path!r}")
        resolved = (ROOT / raw_path[2:]).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise ValueError(f"Plugin skills path escapes the repository: {raw_path}") from exc
        if not resolved.is_dir():
            raise FileNotFoundError(f"Plugin skills directory not found: {raw_path}")
        if (resolved / "SKILL.md").is_file() or any(resolved.glob("*/SKILL.md")):
            found_skill = True
    if not found_skill:
        raise ValueError("Plugin manifest does not point to a directory containing a SKILL.md")
    return manifest


def _write_archive(output: Path, entries: list[tuple[Path, str]]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for source, archive_name in entries:
                archive.write(source, archive_name)
        with zipfile.ZipFile(temporary, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError(f"ZIP integrity check failed at {bad_member}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def build_skill_archive(output: Path) -> None:
    files = validate_skill_source()
    entries = [
        (path, f"fidelityflow/{path.relative_to(SKILL_ROOT).as_posix()}")
        for path in files
    ]
    _write_archive(output, entries)
    with zipfile.ZipFile(output, "r") as archive:
        names = set(archive.namelist())
        for relative in REQUIRED_SKILL_FILES:
            if f"fidelityflow/{relative}" not in names:
                raise ValueError(f"Skill ZIP is missing fidelityflow/{relative}")


def build_plugin_archive(output: Path) -> None:
    validate_plugin_source()
    skill_files = validate_skill_source()
    entries = [
        (PLUGIN_MANIFEST, ".claude-plugin/plugin.json"),
        (ROOT / "LICENSE", "LICENSE"),
    ]
    entries.extend(
        (path, f"skills/fidelityflow/{path.relative_to(SKILL_ROOT).as_posix()}")
        for path in skill_files
    )
    _write_archive(output, entries)
    with zipfile.ZipFile(output, "r") as archive:
        names = set(archive.namelist())
        required = {".claude-plugin/plugin.json", "skills/fidelityflow/SKILL.md"}
        missing = sorted(required - names)
        if missing:
            raise ValueError("Plugin ZIP is missing: " + ", ".join(missing))
        manifest = json.loads(archive.read(".claude-plugin/plugin.json"))
        if manifest.get("name") != "fidelityflow":
            raise ValueError("Plugin ZIP contains an unexpected manifest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", "--skill-output", dest="skill_output", type=Path,
        default=DEFAULT_SKILL_OUTPUT,
        help="output path for the Free-compatible Skill ZIP",
    )
    parser.add_argument(
        "--plugin-output", type=Path, default=DEFAULT_PLUGIN_OUTPUT,
        help="output path for the paid-plan Plugin ZIP",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="validate all sources, build both archives, and verify ZIP integrity",
    )
    args = parser.parse_args(argv)
    try:
        skill_output = args.skill_output.expanduser().resolve()
        plugin_output = args.plugin_output.expanduser().resolve()
        if skill_output == plugin_output:
            raise ValueError("Skill and Plugin archives must use different output paths")
        build_skill_archive(skill_output)
        build_plugin_archive(plugin_output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Release build failed: {exc}\n")
    print(f"Skill archive {'validated and built' if args.check else 'built'}: {skill_output}")
    print(f"Plugin archive {'validated and built' if args.check else 'built'}: {plugin_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
