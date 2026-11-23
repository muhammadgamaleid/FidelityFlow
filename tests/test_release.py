from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import build_release
import fidelityflow


class ReleaseBuildTests(unittest.TestCase):
    def test_release_versions_are_consistent(self):
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        manifest = build_release.validate_plugin_source()
        self.assertEqual(fidelityflow.__version__, "0.6.0")
        self.assertIn('version = "0.6.0"', pyproject)
        self.assertEqual(manifest["version"], fidelityflow.__version__)

    def test_skill_metadata_is_valid(self):
        name, description = build_release._skill_metadata()
        self.assertEqual(name, "fidelityflow")
        self.assertTrue(description)
        self.assertLessEqual(len(description), 200)

    def test_plugin_manifest_points_to_skill(self):
        manifest = build_release.validate_plugin_source()
        self.assertEqual(manifest["name"], "fidelityflow")
        self.assertIn("./skills/", manifest["skills"])
        self.assertEqual(manifest["version"], "0.6.0")

    def test_builds_skill_and_plugin_archives(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_archive = root / "skill.zip"
            plugin_archive = root / "plugin.zip"

            build_release.build_skill_archive(skill_archive)
            build_release.build_plugin_archive(plugin_archive)

            with zipfile.ZipFile(skill_archive) as archive:
                self.assertIn("fidelityflow/SKILL.md", archive.namelist())
                self.assertIsNone(archive.testzip())

            with zipfile.ZipFile(plugin_archive) as archive:
                names = set(archive.namelist())
                self.assertIn(".claude-plugin/plugin.json", names)
                self.assertIn("skills/fidelityflow/SKILL.md", names)
                manifest = json.loads(archive.read(".claude-plugin/plugin.json"))
                self.assertEqual(manifest["name"], "fidelityflow")
                self.assertEqual(manifest["version"], "0.6.0")
                self.assertIsNone(archive.testzip())


if __name__ == "__main__":
    unittest.main()
