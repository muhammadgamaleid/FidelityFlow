from __future__ import annotations

from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "skills" / "fidelityflow" / "scripts" / "fidelityflow.py"
OCR_PATH = ROOT / "skills" / "fidelityflow" / "scripts" / "ocr_engine.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OptionalOCRTests(unittest.TestCase):
    def test_images_are_not_processed_without_explicit_ocr(self):
        cli = load_module(CLI_PATH, "fidelityflow_ocr_cli_test")
        image = Path("example.png")
        self.assertIsNone(cli.expected_extractor(image, ocr=False))
        self.assertEqual(cli.expected_extractor(image, ocr=True), "image-ocr-tesseract-v1")

    def test_image_ocr_enforces_size_limit_before_loading_dependencies(self):
        engine = load_module(OCR_PATH, "fidelityflow_ocr_engine_size_test")
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "oversized.png"
            image.write_bytes(b"too large for configured test limit")
            engine.MAX_IMAGE_BYTES = 4
            with self.assertRaisesRegex(ValueError, "safety limit"):
                engine.extract_image(image)

    def test_pdf_ocr_processes_only_sparse_pages_and_preserves_page_markers(self):
        cli = load_module(CLI_PATH, "fidelityflow_ocr_pdf_test")
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf is an optional PDF dependency")
        with tempfile.TemporaryDirectory() as temporary:
            pdf = Path(temporary) / "scanned.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            with pdf.open("wb") as stream:
                writer.write(stream)

            engine = Mock()
            engine.extract_pdf_pages.return_value = (
                {0: "recognized page content"},
                ["fake OCR warning"],
            )
            cli._load_ocr_engine = lambda: engine
            extracted, warnings = cli.parse_pdf(
                pdf, ocr=True, ocr_lang="ara+eng", ocr_dpi=200, ocr_max_pages=7
            )
            engine.extract_pdf_pages.assert_called_once_with(
                pdf, [0], dpi=200, language="ara+eng", max_pages=7
            )
            self.assertIn("[PAGE 1]", extracted)
            self.assertIn("recognized page content", extracted)
            self.assertTrue(any("fake OCR warning" in item for item in warnings))

    def test_cli_help_documents_ocr_switches(self):
        result = subprocess.run(
            [sys.executable, str(CLI_PATH), "ingest", "--help"],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--ocr", result.stdout)
        self.assertIn("--ocr-lang", result.stdout)
        self.assertIn("--ocr-dpi", result.stdout)
        self.assertIn("--ocr-max-pages", result.stdout)


if __name__ == "__main__":
    unittest.main()
