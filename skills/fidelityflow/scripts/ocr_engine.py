"""Optional local OCR support for image files and scanned PDF pages.

Requires Pillow, pytesseract, PyMuPDF, the Tesseract executable, and installed
Tesseract language data. This module performs no network calls.
"""
from __future__ import annotations

from pathlib import Path
import shutil

MAX_IMAGE_BYTES = 100 * 1024 * 1024
MAX_IMAGE_PIXELS = 80_000_000


def _dependencies():
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract OCR is not installed or is not on PATH. Install the "
            "Tesseract executable and the requested language data."
        )
    try:
        import pytesseract  # type: ignore
        from PIL import Image, ImageOps  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Install FidelityFlow's OCR Python dependencies with "
            'python -m pip install -e ".[ocr]".'
        ) from exc
    return pytesseract, Image, ImageOps


def _recognize(image, language: str) -> str:
    pytesseract, _, _ = _dependencies()
    try:
        return pytesseract.image_to_string(
            image, lang=language, config="--psm 6", timeout=30
        ).strip()
    except RuntimeError as exc:
        raise RuntimeError(
            f"Tesseract OCR failed for language '{language}'. Install its trained "
            "language data and verify the language code."
        ) from exc


def extract_image(path: Path, language: str = "eng") -> tuple[str, list[str]]:
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image exceeds the OCR safety limit of {MAX_IMAGE_BYTES // (1024 * 1024)} MiB."
        )
    _, Image, ImageOps = _dependencies()
    try:
        with Image.open(path) as opened:
            width, height = opened.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"Image exceeds the OCR safety limit of {MAX_IMAGE_PIXELS:,} pixels."
                )
            image = ImageOps.grayscale(ImageOps.exif_transpose(opened).convert("RGB"))
            text = _recognize(image, language)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not safely OCR image {path.name}: {exc}") from exc

    warnings = [
        f"Image text was extracted with Tesseract language '{language}'. Verify OCR output against the original image, especially numbers, names, and tables."
    ]
    if not text:
        warnings.append("OCR found no readable text. The original image remains authoritative.")
    return f"[IMAGE: {path.name}]\n{text}", warnings


def extract_pdf_pages(
    path: Path,
    page_indices: list[int],
    dpi: int = 180,
    language: str = "eng",
    max_pages: int = 100,
) -> tuple[dict[int, str], list[str]]:
    if dpi < 100 or dpi > 300:
        raise ValueError("OCR DPI must be between 100 and 300.")
    if max_pages < 1 or max_pages > 500:
        raise ValueError("OCR page limit must be between 1 and 500.")
    selected = list(dict.fromkeys(page_indices))[:max_pages]
    if not selected:
        return {}, []

    _, Image, ImageOps = _dependencies()
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Scanned PDF OCR requires PyMuPDF. Install with "
            'python -m pip install -e ".[ocr]".'
        ) from exc

    results: dict[int, str] = {}
    warnings = []
    scale = dpi / 72.0
    with fitz.open(str(path)) as document:
        for index in selected:
            if index < 0 or index >= len(document):
                continue
            page = document.load_page(index)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                colorspace=fitz.csRGB,
                alpha=False,
            )
            image = Image.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
            image = ImageOps.grayscale(image)
            results[index] = _recognize(image, language)
    warnings.append(
        f"OCR was applied only to sparse-text PDF pages (language={language}, dpi={dpi}, maximum pages={max_pages})."
    )
    return results, warnings


def doctor() -> dict:
    result = {
        "pillow_available": False,
        "pytesseract_available": False,
        "pymupdf_available": False,
        "tesseract_available": shutil.which("tesseract") is not None,
        "ocr_ready_for_images": False,
        "ocr_ready_for_scanned_pdfs": False,
    }
    try:
        import PIL  # type: ignore
        result["pillow_available"] = True
        result["pillow_version"] = getattr(PIL, "__version__", "unknown")
    except ImportError:
        pass
    try:
        import pytesseract  # type: ignore
        result["pytesseract_available"] = True
        result["pytesseract_version"] = getattr(pytesseract, "__version__", "unknown")
    except ImportError:
        pass
    try:
        import fitz  # type: ignore
        result["pymupdf_available"] = True
        result["pymupdf_version"] = getattr(fitz, "VersionBind", "unknown")
    except ImportError:
        pass
    result["ocr_ready_for_images"] = all(
        result[key] for key in (
            "pillow_available", "pytesseract_available", "tesseract_available"
        )
    )
    result["ocr_ready_for_scanned_pdfs"] = (
        result["ocr_ready_for_images"] and result["pymupdf_available"]
    )
    return result
