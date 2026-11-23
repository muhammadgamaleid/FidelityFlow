"""Local OCR and conservative visual-structure analysis.

OCR uses bounded, multi-pass preprocessing and records confidence/layout evidence.
Optional OpenCV analysis reports geometric primitives only; it does not claim to
understand chart meaning, labels, or diagram semantics. No network calls.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import shutil
import unicodedata
import re
import math

MAX_IMAGE_BYTES = 100 * 1024 * 1024
MAX_IMAGE_PIXELS = 80_000_000
MAX_PDF_BYTES = 500 * 1024 * 1024
OCR_TIMEOUT_SECONDS = 15
OSD_TIMEOUT_SECONDS = 10
OCR_ENGINE_VERSION = "tesseract-vision-v3"


def _dependencies():
    if shutil.which("tesseract") is None:
        raise RuntimeError(
            "Tesseract OCR is not installed or is not on PATH. Install the "
            "Tesseract executable and the requested language data."
        )
    try:
        import pytesseract  # type: ignore
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Install FidelityFlow's OCR Python dependencies with "
            'python -m pip install -e ".[ocr]".'
        ) from exc
    return pytesseract, Image, ImageEnhance, ImageFilter, ImageOps


def _validate_languages(pytesseract, language: str) -> None:
    requested = [part.strip() for part in language.split("+") if part.strip()]
    if not requested:
        raise ValueError("At least one Tesseract language code is required.")
    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception:
        # Let the actual OCR call report an actionable runtime error if listing
        # traineddata is unsupported by this Tesseract build.
        return
    missing = [item for item in requested if item not in available]
    if missing:
        raise RuntimeError(
            "Missing Tesseract language data: " + ", ".join(missing)
            + ". Install the corresponding traineddata files and retry."
        )


def _orientation(image, pytesseract) -> tuple[object, str | None]:
    """Apply Tesseract OSD rotation when it is confidently available."""
    try:
        osd = pytesseract.image_to_osd(
            image, config="--psm 0", timeout=OSD_TIMEOUT_SECONDS
        )
        rotation = 0
        confidence = 0.0
        for line in osd.splitlines():
            if line.startswith("Rotate:"):
                rotation = int(line.split(":", 1)[1].strip()) % 360
            elif line.startswith("Orientation confidence:"):
                confidence = float(line.split(":", 1)[1].strip())
        if rotation in (90, 180, 270) and confidence >= 3.0:
            return image.rotate(-rotation, expand=True), f"auto-rotated {rotation} degrees"
    except Exception:
        # OSD commonly fails on short text and non-text images. It is advisory.
        pass
    return image, None


def _preprocess_variants(image, Image, ImageOps, ImageEnhance, ImageFilter):
    """Return a small bounded set of OCR-friendly variants."""
    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    variants = [("contrast", gray)]
    enlarged = gray
    if max(gray.size) < 2200 and min(gray.size) < 1400:
        scale = min(2.0, 2200 / max(gray.size))
        if scale > 1.15:
            enlarged = gray.resize(
                (max(1, int(gray.width * scale)), max(1, int(gray.height * scale))),
                Image.Resampling.LANCZOS,
            )
    sharpened = ImageEnhance.Sharpness(enlarged).enhance(1.5)
    variants.append(("sharp", sharpened))
    # A thresholded variant helps faint scans; keep the grayscale variants too.
    threshold = sharpened.point(lambda value: 255 if value > 165 else 0)
    variants.append(("threshold", threshold))
    return variants


def _run_ocr(image, language: str, psm: int):
    pytesseract, *_ = _dependencies()
    config = f"--oem 3 --psm {psm}"
    data = pytesseract.image_to_data(
        image,
        lang=language,
        config=config,
        output_type=pytesseract.Output.DICT,
        timeout=OCR_TIMEOUT_SECONDS,
    )
    words = []
    confidences = []
    count = len(data.get("text", []))
    for index in range(count):
        token = str(data["text"][index]).strip()
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError, IndexError):
            confidence = -1.0
        if token and confidence >= 0:
            words.append({
                "text": token,
                "confidence": confidence,
                "left": int(data["left"][index]),
                "top": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
                "block": int(data["block_num"][index]),
                "paragraph": int(data["par_num"][index]),
                "line": int(data["line_num"][index]),
            })
            confidences.append(confidence)
    average = sum(confidences) / len(confidences) if confidences else 0.0
    text = pytesseract.image_to_string(
        image, lang=language, config=config, timeout=OCR_TIMEOUT_SECONDS
    ).strip()
    # Prefer credible confidence, then useful coverage; never fabricate text.
    score = average + min(len(text), 1200) / 120.0
    return {"text": text, "words": words, "confidence": average, "score": score, "psm": psm, "image_size": image.size}


def _best_ocr(image, language: str):
    pytesseract, Image, ImageEnhance, ImageFilter, ImageOps = _dependencies()
    _validate_languages(pytesseract, language)
    oriented, rotation_note = _orientation(image, pytesseract)
    variants = _preprocess_variants(oriented, Image, ImageOps, ImageEnhance, ImageFilter)
    best = None
    for _, candidate in variants:
        for psm in (6, 11):
            try:
                result = _run_ocr(candidate, language, psm)
            except (RuntimeError, pytesseract.TesseractError):
                # A timeout or failed segmentation pass must not prevent remaining attempts.
                continue
            if best is None or result["score"] > best["score"]:
                best = result
            if result["confidence"] >= 85 and len(result["text"]) >= 12:
                break
        if best is not None and best["confidence"] >= 85 and len(best["text"]) >= 12:
            break
    if best is None:
        raise RuntimeError("All bounded Tesseract OCR attempts failed or timed out.")
    notes = []
    if rotation_note:
        notes.append(rotation_note)
    if best["confidence"] < 45:
        notes.append(
            f"Low OCR confidence ({best['confidence']:.1f}/100); verify the original image."
        )
    return best, notes


def _layout_lines(words: list[dict]) -> list[str]:
    """Group recognized words into source-positioned lines."""
    groups = defaultdict(list)
    for word in words:
        key = (word["block"], word["paragraph"], word["line"])
        groups[key].append(word)
    lines = []
    for key in sorted(groups):
        row = groups[key]
        sample = " ".join(item["text"] for item in row)
        rtl_chars = sum(
            1 for char in sample
            if unicodedata.bidirectional(char) in {"R", "AL", "AN"}
        )
        strong_chars = sum(1 for char in sample if char.isalpha() or char.isdigit())
        rtl = strong_chars > 0 and rtl_chars / strong_chars > 0.5
        row = sorted(row, key=lambda item: item["left"], reverse=rtl)
        content = " ".join(item["text"] for item in row)
        if not content:
            continue
        left = min(item["left"] for item in row)
        top = min(item["top"] for item in row)
        right = max(item["left"] + item["width"] for item in row)
        bottom = max(item["top"] + item["height"] for item in row)
        confidence = sum(item["confidence"] for item in row) / len(row)
        lines.append(
            f"[OCR_LINE x={left}:{right} y={top}:{bottom} confidence={confidence:.0f}] {content}"
        )
    return lines


def _vision_words(words: list[dict], scale_x: float, scale_y: float) -> list[dict]:
    normalized = []
    for word in words:
        x = int(word["left"] * scale_x)
        y = int(word["top"] * scale_y)
        w = max(1, int(word["width"] * scale_x))
        h = max(1, int(word["height"] * scale_y))
        normalized.append({"text": word["text"], "confidence": float(word["confidence"]),
                           "x": x, "y": y, "width": w, "height": h})
    return normalized


def analyze_visual_structure(image, words: list[dict] | None = None, ocr_size=None) -> list[str]:
    """Extract conservative shape, chart, and connector evidence from raster images.

    Geometry is heuristic and optional. Semantic labels are attached only when OCR
    text overlaps or is immediately adjacent to a detected region.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError:
        return []
    try:
        width, height = image.size
        analysis = image.convert("RGB")
        analysis.thumbnail((1800, 1800))
        scale_x, scale_y = width / analysis.width, height / analysis.height
        array = np.asarray(analysis)
        gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edges = cv2.Canny(blur, 45, 135)
        min_line = max(30, int(min(gray.shape) * 0.07))
        detected = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=45,
                                   minLineLength=min_line, maxLineGap=10)
        lines = []
        horizontal = vertical = diagonal = 0
        if detected is not None:
            for item in detected[:, 0, :]:
                x1, y1, x2, y2 = map(int, item)
                dx, dy = abs(x2 - x1), abs(y2 - y1)
                if max(dx, dy) < min_line:
                    continue
                if dy <= max(3, dx * 0.07):
                    horizontal += 1
                    orientation = "horizontal"
                elif dx <= max(3, dy * 0.07):
                    vertical += 1
                    orientation = "vertical"
                else:
                    diagonal += 1
                    orientation = "diagonal"
                lines.append((x1, y1, x2, y2, orientation))
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        min_area = max(100, gray.shape[0] * gray.shape[1] * 0.00025)
        objects = []
        seen = set()
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < min_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 14 or h < 14 or w > gray.shape[1] * 0.96 or h > gray.shape[0] * 0.96:
                continue
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0:
                continue
            approx = cv2.approxPolyDP(contour, 0.035 * perimeter, True)
            vertices = len(approx)
            ratio = w / max(1, h)
            kind = None
            if vertices == 4:
                points = approx.reshape(-1, 2)
                angles = []
                for i in range(4):
                    a = points[(i - 1) % 4] - points[i]
                    b = points[(i + 1) % 4] - points[i]
                    denom = max(1e-6, float(np.linalg.norm(a) * np.linalg.norm(b)))
                    angles.append(abs(float(np.dot(a, b)) / denom))
                if all(value < 0.28 for value in angles):
                    kind = "rectangle"
                elif all(0.45 < value < 0.95 for value in angles):
                    kind = "diamond"
            elif vertices == 3:
                kind = "triangle"
            elif vertices >= 7:
                circularity = 4 * math.pi * area / max(1.0, perimeter * perimeter)
                if circularity >= 0.68:
                    kind = "ellipse"
            if kind:
                key = (kind, round(x / 8), round(y / 8), round(w / 8), round(h / 8))
                if key not in seen:
                    seen.add(key)
                    objects.append({"kind": kind, "x": x, "y": y, "w": w, "h": h,
                                    "confidence": 0.72 if kind in {"rectangle", "ellipse"} else 0.62})
        # Prefer larger enclosing contours and suppress near-identical nested detections.
        objects.sort(key=lambda item: item["w"] * item["h"], reverse=True)
        filtered = []
        for item in objects:
            duplicate = any(
                prior["kind"] == item["kind"]
                and abs(prior["x"] - item["x"]) < 8 and abs(prior["y"] - item["y"]) < 8
                and abs(prior["w"] - item["w"]) < 12 and abs(prior["h"] - item["h"]) < 12
                for prior in filtered
            )
            if not duplicate:
                filtered.append(item)
        objects = filtered[:80]
        word_scale_x = width / max(1, max((word["left"] + word["width"] for word in (words or [])), default=width))
        word_scale_y = height / max(1, max((word["top"] + word["height"] for word in (words or [])), default=height))
        normalized_words = _vision_words(words or [], word_scale_x, word_scale_y)
        evidence = [f"Image dimensions: {width}x{height} pixels."]
        evidence.append(
            f"Geometric evidence (approximate): {horizontal} horizontal, {vertical} vertical, "
            f"{diagonal} diagonal line segments; {len(objects)} candidate shapes."
        )
        for index, item in enumerate(objects, start=1):
            x, y, w, h = (int(round(item[key] * scale)) for key, scale in
                          (("x", scale_x), ("y", scale_y), ("w", scale_x), ("h", scale_y)))
            right, bottom = x + w, y + h
            labels = []
            for word in normalized_words:
                wx, wy = word["x"], word["y"]
                wr, wb = wx + word["width"], wy + word["height"]
                margin = max(8, int(min(w, h) * 0.12))
                if wx <= right + margin and wr >= x - margin and wy <= bottom + margin and wb >= y - margin:
                    labels.append(word["text"])
            label = re.sub(r"[^\w.-]+", "_", " ".join(labels), flags=re.UNICODE)[:100] or "none"
            evidence.append(
                f"[VISION_OBJECT id={index} type={item['kind']} x={x} y={y} w={w} h={h} "
                f"confidence={item['confidence']:.2f} label={label} coordinate_space=pixels]"
            )
        # Detect chart-like plots only when both axes and a plausible data trace/bar pattern exist.
        chart_candidate = horizontal >= 2 and vertical >= 2 and (
            diagonal >= 1 or any(item["kind"] == "rectangle" for item in objects)
        )
        if chart_candidate:
            evidence.append("[VISION_CHART type=plot_candidate confidence=0.55 coordinate_space=pixels]")
            evidence.append("Chart candidate: intersecting axes/grid and plotted marks detected; values and series are not inferred from pixels.")
        # Detect arrowheads as triangular contours and associate them with the nearest line endpoint.
        triangles = [item for item in objects if item["kind"] == "triangle"]
        relations = []
        for triangle in triangles:
            cx, cy = triangle["x"] + triangle["w"] / 2, triangle["y"] + triangle["h"] / 2
            candidates = []
            for line in lines:
                x1, y1, x2, y2, orientation = line
                d1 = math.hypot(cx - x1, cy - y1)
                d2 = math.hypot(cx - x2, cy - y2)
                if min(d1, d2) <= max(18, min(triangle["w"], triangle["h"]) * 1.8):
                    candidates.append((min(d1, d2), line, "end" if d2 < d1 else "start"))
            if candidates:
                _, line, endpoint = min(candidates, key=lambda value: value[0])
                x1, y1, x2, y2, _ = line
                tip = (x2, y2) if endpoint == "end" else (x1, y1)
                relations.append((triangle, tip, line))
        for index, (triangle, tip, line) in enumerate(relations[:40], start=1):
            tx, ty = int(round(tip[0] * scale_x)), int(round(tip[1] * scale_y))
            lx1, ly1, lx2, ly2, _ = line
            sx, sy = (lx1, ly1) if (lx1, ly1) != tip else (lx2, ly2)
            sx, sy = int(round(sx * scale_x)), int(round(sy * scale_y))
            evidence.append(
                f"[VISION_RELATION id={index} type=arrow_candidate x1={sx} y1={sy} x2={tx} y2={ty} "
                "confidence=0.45 coordinate_space=pixels]"
            )
        if not objects and not lines:
            evidence.append("No stable geometric primitives were detected.")
        evidence.append(
            "Visual findings are heuristic candidates. OCR labels are proximity associations; "
            "numeric chart values, series identity, causal meaning, and ambiguous arrow direction require verification."
        )
        return evidence
    except Exception:
        return ["Optional visual-structure analysis failed; OCR text is retained."]



def _rescale_ocr_words(words: list[dict], source_size, target_size) -> list[dict]:
    source_width, source_height = source_size or target_size
    target_width, target_height = target_size
    scale_x = target_width / max(1, source_width)
    scale_y = target_height / max(1, source_height)
    return [
        {**word,
         "left": int(round(word["left"] * scale_x)),
         "top": int(round(word["top"] * scale_y)),
         "width": max(1, int(round(word["width"] * scale_x))),
         "height": max(1, int(round(word["height"] * scale_y)))}
        for word in words
    ]


def _format_result(result: dict, image, source: str) -> str:
    text = result["text"]
    lines = _layout_lines(result["words"])
    width, height = image.size
    sections = [
        f"[IMAGE: {source}]",
        f"[IMAGE_DIMENSIONS width={width} height={height} coordinate_space=pixels]",
        f"[OCR_QUALITY mean_word_confidence={result['confidence']:.1f}/100 psm={result['psm']}]",
    ]
    if lines:
        # Keep one copy of recognized text: coordinates/confidence are attached
        # to each line instead of repeating a second plain-text transcript.
        sections.extend(["[OCR_LAYOUT]", *lines, "[/OCR_LAYOUT]"])
    elif text:
        sections.append(text)
    visual = analyze_visual_structure(image, result["words"], result.get("image_size"))
    if visual:
        sections.extend(["[VISUAL_GEOMETRY]", *visual, "[/VISUAL_GEOMETRY]"])
    return "\n".join(section for section in sections if section is not None)


def extract_image(path: Path, language: str = "eng") -> tuple[str, list[str]]:
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image exceeds the OCR safety limit of {MAX_IMAGE_BYTES // (1024 * 1024)} MiB."
        )
    _, Image, _, _, ImageOps = _dependencies()
    try:
        with Image.open(path) as opened:
            width, height = opened.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise ValueError(
                    f"Image exceeds the OCR safety limit of {MAX_IMAGE_PIXELS:,} pixels."
                )
            image = ImageOps.exif_transpose(opened).convert("RGB")
            result, notes = _best_ocr(image, language)
            output = _format_result(result, image, path.name)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Could not safely OCR image {path.name}: {exc}") from exc
    warnings = [
        f"Image text was extracted with Tesseract language '{language}'. "
        "OCR coordinates and confidence are approximate; verify numbers, names, "
        "tables, and reading order against the original."
    ]
    warnings.extend(notes)
    if not result["text"]:
        warnings.append("OCR found no readable text. The original image remains authoritative.")
    return output, warnings


def extract_pdf_pages(
    path: Path,
    page_indices: list[int],
    dpi: int = 180,
    language: str = "eng",
    max_pages: int = 100,
) -> tuple[dict[int, str], list[str]]:
    if path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError(f"PDF exceeds the OCR safety limit of {MAX_PDF_BYTES // (1024 * 1024)} MiB.")
    if dpi < 100 or dpi > 300:
        raise ValueError("OCR DPI must be between 100 and 300.")
    if max_pages < 1 or max_pages > 500:
        raise ValueError("OCR page limit must be between 1 and 500.")
    selected = list(dict.fromkeys(page_indices))[:max_pages]
    if not selected:
        return {}, []
    _, Image, *_ = _dependencies()
    try:
        import pymupdf as fitz  # type: ignore
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
            estimated_width = max(1, int(page.rect.width * scale + 0.999))
            estimated_height = max(1, int(page.rect.height * scale + 0.999))
            if estimated_width * estimated_height > MAX_IMAGE_PIXELS:
                warnings.append(f"Page {index + 1} skipped: estimated render exceeds the pixel safety limit.")
                continue
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(scale, scale),
                colorspace=fitz.csRGB,
                alpha=False,
            )
            if pixmap.width <= 0 or pixmap.height <= 0 or pixmap.width * pixmap.height > MAX_IMAGE_PIXELS:
                warnings.append(f"Page {index + 1} skipped: rendered page exceeds the pixel safety limit.")
                continue
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            result, notes = _best_ocr(image, language)
            results[index] = _format_result(result, image, f"{path.name} page {index + 1}")
            warnings.extend(f"Page {index + 1}: {note}" for note in notes)
    warnings.append(
        f"Multi-pass OCR was applied only to sparse-text PDF pages "
        f"(language={language}, dpi={dpi}, maximum pages={max_pages})."
    )
    return results, warnings


def doctor() -> dict:
    result = {
        "pillow_available": False,
        "pytesseract_available": False,
        "pymupdf_available": False,
        "opencv_available": False,
        "tesseract_available": shutil.which("tesseract") is not None,
        "ocr_ready_for_images": False,
        "ocr_ready_for_scanned_pdfs": False,
        "visual_geometry_ready": False,
        "ocr_engine_version": OCR_ENGINE_VERSION,
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
        import pymupdf as fitz  # type: ignore
        result["pymupdf_available"] = True
        result["pymupdf_version"] = getattr(fitz, "VersionBind", "unknown")
    except ImportError:
        pass
    try:
        import cv2  # type: ignore
        import numpy  # type: ignore
        result["opencv_available"] = True
        result["opencv_version"] = getattr(cv2, "__version__", "unknown")
        result["numpy_version"] = getattr(numpy, "__version__", "unknown")
    except ImportError:
        pass
    result["ocr_ready_for_images"] = all(
        result[key] for key in ("pillow_available", "pytesseract_available", "tesseract_available")
    )
    result["ocr_ready_for_scanned_pdfs"] = (
        result["ocr_ready_for_images"] and result["pymupdf_available"]
    )
    result["visual_geometry_ready"] = result["opencv_available"]
    return result
