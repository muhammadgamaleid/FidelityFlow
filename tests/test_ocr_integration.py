from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OCR_PATH = ROOT / "skills" / "fidelityflow" / "scripts" / "ocr_engine.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("fidelityflow_ocr_integration", OCR_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which("tesseract"), "Tesseract executable is not installed")
class RealOCREndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from PIL import Image, ImageDraw, ImageFont
            import pytesseract
            import pymupdf as fitz
            import cv2
        except ImportError as exc:
            raise unittest.SkipTest(f"Optional OCR/vision dependency missing: {exc}")
        languages = set(pytesseract.get_languages(config=""))
        if "eng" not in languages:
            raise unittest.SkipTest("Tesseract English traineddata is not installed")
        cls.Image = Image
        cls.ImageDraw = ImageDraw
        cls.ImageFont = ImageFont
        cls.fitz = fitz
        cls.engine = load_engine()

    def make_sample_image(self, path: Path):
        image = self.Image.new("RGB", (2000, 600), "white")
        draw = self.ImageDraw.Draw(image)
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        try:
            font = self.ImageFont.truetype(font_path, 100)
        except OSError:
            font = self.ImageFont.load_default()
        draw.text((180, 120), "Fidelity Flow OCR 12345", fill="black", font=font)
        # Add separated axis-like geometry to exercise the optional visual pass.
        draw.line((50, 540, 1900, 540), fill="black", width=5)
        draw.line((50, 70, 50, 540), fill="black", width=5)
        image.save(path)
        return image

    def test_real_image_ocr_emits_text_confidence_layout_and_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.png"
            self.make_sample_image(path)
            output, warnings = self.engine.extract_image(path, language="eng")
            self.assertIn("FIDELITY", output.upper())
            self.assertIn("12345", output)
            self.assertIn("[OCR_QUALITY", output)
            self.assertIn("[IMAGE_DIMENSIONS width=2000 height=600 coordinate_space=pixels]", output)
            self.assertIn("[OCR_LAYOUT]", output)
            self.assertIn("[VISUAL_GEOMETRY]", output)
            self.assertIsInstance(warnings, list)

    def test_real_scanned_pdf_page_uses_the_same_ocr_pipeline(self):
        with tempfile.TemporaryDirectory() as temporary:
            image_path = Path(temporary) / "page.png"
            image = self.make_sample_image(image_path)
            pdf_path = Path(temporary) / "scanned.pdf"
            document = self.fitz.open()
            page = document.new_page(width=900, height=250)
            page.insert_image(page.rect, filename=str(image_path))
            document.save(pdf_path)
            document.close()
            pages, warnings = self.engine.extract_pdf_pages(
                pdf_path, [0], dpi=150, language="eng", max_pages=1
            )
            self.assertIn(0, pages)
            self.assertIn("FIDELITY", pages[0].upper())
            self.assertIn("12345", pages[0])
            self.assertTrue(any("Multi-pass OCR" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
