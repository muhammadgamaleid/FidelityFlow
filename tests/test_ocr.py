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
        self.assertEqual(cli.expected_extractor(image, ocr=True), "image-ocr-tesseract-v3")

    def test_visual_analyzer_detects_shape_chart_candidate_and_nearby_ocr_label(self):
        try:
            import cv2  # noqa: F401
            from PIL import Image, ImageDraw
        except ImportError:
            self.skipTest("Optional vision dependencies are not installed")
        engine = load_module(OCR_PATH, "fidelityflow_visual_analyzer_test")
        image = Image.new("RGB", (640, 420), "white")
        draw = ImageDraw.Draw(image)
        draw.line((80, 330, 560, 330), fill="black", width=4)
        draw.line((100, 40, 100, 350), fill="black", width=4)
        draw.rectangle((180, 180, 240, 330), outline="black", width=4)
        draw.line((260, 270, 360, 190), fill="black", width=4)
        words = [{"text": "Revenue", "confidence": 92, "left": 175, "top": 155,
                  "width": 65, "height": 18}]
        result = engine.analyze_visual_structure(image, words, image.size)
        joined = "\\n".join(result)
        self.assertTrue(any("[VISION_OBJECT" in line for line in result), joined)
        self.assertIn("[VISION_CHART type=plot_candidate", joined)
        self.assertIn("label=Revenue", joined)

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


    def test_ocr_layout_lines_keep_coordinates_confidence_and_reading_order(self):
        engine = load_module(OCR_PATH, "fidelityflow_ocr_layout_test")
        words = [
            {"text": "world", "confidence": 90, "left": 80, "top": 10, "width": 30, "height": 12, "block": 1, "paragraph": 1, "line": 1},
            {"text": "Hello", "confidence": 80, "left": 10, "top": 10, "width": 40, "height": 12, "block": 1, "paragraph": 1, "line": 1},
        ]
        lines = engine._layout_lines(words)
        self.assertEqual(len(lines), 1)
        self.assertIn("x=10:110", lines[0])
        self.assertIn("y=10:22", lines[0])
        self.assertIn("confidence=85", lines[0])
        self.assertTrue(lines[0].endswith("Hello world"))


    def test_ocr_layout_preserves_right_to_left_word_order(self):
        engine = load_module(OCR_PATH, "fidelityflow_ocr_rtl_test")
        words = [
            {"text": "العالم", "confidence": 90, "left": 80, "top": 10, "width": 30, "height": 12, "block": 1, "paragraph": 1, "line": 1},
            {"text": "مرحبا", "confidence": 90, "left": 10, "top": 10, "width": 40, "height": 12, "block": 1, "paragraph": 1, "line": 1},
        ]
        line = engine._layout_lines(words)[0]
        self.assertTrue(line.endswith("العالم مرحبا"))

    def test_formatted_ocr_does_not_duplicate_recognized_text(self):
        engine = load_module(OCR_PATH, "fidelityflow_ocr_format_test")
        engine.analyze_visual_structure = lambda image: []
        result = {
            "text": "alpha beta",
            "words": [
                {"text": "alpha", "confidence": 90, "left": 1, "top": 2, "width": 10, "height": 5, "block": 1, "paragraph": 1, "line": 1},
                {"text": "beta", "confidence": 80, "left": 15, "top": 2, "width": 10, "height": 5, "block": 1, "paragraph": 1, "line": 1},
            ],
            "confidence": 85.0,
            "psm": 6,
        }
        image = Mock()
        image.size = (100, 50)
        output = engine._format_result(result, image, "sample.png")
        self.assertEqual(output.count("alpha"), 1)
        self.assertEqual(output.count("beta"), 1)
        self.assertIn("mean_word_confidence=85.0", output)
        self.assertIn("[OCR_LAYOUT]", output)

    def test_preprocessing_produces_bounded_grayscale_sharp_and_threshold_variants(self):
        try:
            from PIL import Image, ImageEnhance, ImageFilter, ImageOps
        except ImportError:
            self.skipTest("Pillow is an optional OCR dependency")
        engine = load_module(OCR_PATH, "fidelityflow_ocr_preprocess_test")
        source = Image.new("RGB", (500, 300), "white")
        variants = engine._preprocess_variants(source, Image, ImageOps, ImageEnhance, ImageFilter)
        self.assertEqual([name for name, _ in variants], ["contrast", "sharp", "threshold"])
        self.assertTrue(all(image.mode == "L" for _, image in variants))
        self.assertTrue(all(image.width <= 2200 and image.height <= 2200 for _, image in variants))

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
