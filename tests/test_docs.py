from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DocumentationIntegrityTests(unittest.TestCase):
    def test_readme_has_no_literal_newline_escapes_in_markdown_tables(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn(r"\n|", readme)
        self.assertIn("| Capability | Claude.ai Skill | Claude Code |", readme)

    def test_readme_contents_links_resolve_to_headings(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        headings = {
            re.sub(r"[^a-z0-9 -]", "", match.group(1).lower())
            .strip().replace(" ", "-")
            for match in re.finditer(r"^#{1,6}\s+(.+)$", readme, re.MULTILINE)
        }
        contents = readme.split("## Contents", 1)[1].split("\n## ", 1)[0]
        anchors = re.findall(r"\]\(#([^)]*)\)", contents)
        self.assertGreaterEqual(len(anchors), 8)
        for anchor in anchors:
            self.assertIn(anchor, headings, f"README contents link has no heading: #{anchor}")

    def test_architecture_reference_matches_canonical_document(self):
        canonical = (ROOT / "docs" / "ARCHITECTURE.md").read_bytes()
        packaged = (ROOT / "skills" / "fidelityflow" / "references" / "architecture.md").read_bytes()
        self.assertEqual(packaged, canonical)


if __name__ == "__main__":
    unittest.main()
