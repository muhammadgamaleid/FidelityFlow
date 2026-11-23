#!/usr/bin/env python3
"""FidelityFlow local file index and reversible-output archive CLI.

Standard-library only except optional pypdf for PDF text extraction.
No network calls. The original source file is never modified.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import posixpath
from pathlib import Path
import re
import shutil
import sys
import tempfile
import textwrap
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from collections import Counter

VERSION = "0.6.0"  # Structured source locations for pages, sheets, slides, tables, and images.
DEFAULT_CACHE = Path.cwd() / ".fidelityflow" / "cache"
DEFAULT_ARCHIVE = Path.cwd() / ".fidelityflow" / "archive"
CHUNK_CHARS = 7000
MAX_OOXML_XML_MEMBER_BYTES = 64 * 1024 * 1024  # Per-part limit.
MAX_OOXML_TOTAL_BYTES = 256 * 1024 * 1024
MAX_OOXML_MEMBERS = 10000
OCR_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
DEFAULT_OCR_DPI = 180
DEFAULT_OCR_MAX_PAGES = 100


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    """Hash large files incrementally instead of loading them into RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)[:100] or "item"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def validate_ooxml_archive(archive: zipfile.ZipFile) -> None:
    """Bound total expanded size, entry count, and pathological compression ratios."""
    infos = archive.infolist()
    if len(infos) > MAX_OOXML_MEMBERS:
        raise ValueError(f"OOXML archive has too many members ({len(infos)}; limit {MAX_OOXML_MEMBERS})")
    total_size = sum(info.file_size for info in infos)
    if total_size > MAX_OOXML_TOTAL_BYTES:
        raise ValueError(
            f"OOXML archive expands to {total_size:,} bytes; total limit is "
            f"{MAX_OOXML_TOTAL_BYTES:,}. Split the source or use native document handling."
        )
    for info in infos:
        if info.file_size > MAX_OOXML_XML_MEMBER_BYTES and info.filename.lower().endswith(".xml"):
            raise ValueError(
                f"OOXML member {info.filename} is {info.file_size:,} bytes; "
                f"per-XML-member limit is {MAX_OOXML_XML_MEMBER_BYTES:,}"
            )
        if info.file_size > 1024 * 1024 and info.compress_size == 0:
            raise ValueError(f"OOXML member has an invalid compression size: {info.filename}")
        if info.compress_size and info.file_size / info.compress_size > 1000:
            raise ValueError(f"OOXML member has an excessive compression ratio: {info.filename}")


def read_ooxml_xml_member(archive: zipfile.ZipFile, member: str) -> bytes:
    """Read one XML member with a conservative uncompressed-size limit."""
    try:
        info = archive.getinfo(member)
    except KeyError as exc:
        raise ValueError(f"Required OOXML member is missing: {member}") from exc
    if info.file_size > MAX_OOXML_XML_MEMBER_BYTES:
        raise ValueError(
            f"OOXML member {member} is {info.file_size:,} bytes; limit is "
            f"{MAX_OOXML_XML_MEMBER_BYTES:,}. Use Claude's native file handling "
            "or split the source into smaller files."
        )
    return archive.read(member)


def normalized_suffix(path: Path) -> str:
    """Handle multi-part example names such as .env.example explicitly."""
    name = path.name.casefold()
    if name.endswith(".env.example"):
        return ".env.example"
    return path.suffix.casefold()


def xml_text(element: ET.Element) -> str:
    parts = []
    for node in element.iter():
        name = local_name(node.tag)
        if name == "t" and node.text:
            parts.append(node.text)
        elif name == "tab":
            parts.append("\t")
        elif name in {"br", "cr"}:
            parts.append("\n")
    return "".join(parts)


def docx_xml_text(element: ET.Element) -> str:
    """Preserve inserted/deleted revision text with explicit markers."""
    def visit(node: ET.Element) -> str:
        name = local_name(node.tag)
        if name in {"ins", "del"}:
            inner = "".join(visit(child) for child in list(node))
            label = "INSERTED" if name == "ins" else "DELETED"
            return f"[{label}: {inner}]" if inner else ""
        if name in {"t", "delText"}:
            return node.text or ""
        if name == "tab":
            return "\t"
        if name in {"br", "cr"}:
            return "\n"
        return "".join(visit(child) for child in list(node))
    return visit(element)


def _docx_table_text(table: ET.Element) -> list[str]:
    rows = []
    for row in table.iter():
        if local_name(row.tag) != "tr":
            continue
        cells = []
        for cell in list(row):
            if local_name(cell.tag) == "tc":
                paragraphs = [
                    docx_xml_text(paragraph).strip()
                    for paragraph in cell.iter()
                    if local_name(paragraph.tag) == "p"
                ]
                cells.append(" / ".join(value for value in paragraphs if value))
        if any(cells):
            rows.append(" | ".join(cells))
    return rows


def extract_docx(path: Path) -> tuple[str, list[str]]:
    notes = [
        "DOCX extraction preserves paragraph order, heading styles, table text, tracked insertions/deletions, headers, footers, footnotes, endnotes, and comments.",
        "Pagination, floating-object geometry, embedded media, and exact visual layout are not reproduced.",
    ]
    output: list[str] = []

    def append_part(title: str, root: ET.Element) -> None:
        part_lines: list[str] = []

        def visit(container: ET.Element) -> None:
            for child in list(container):
                kind = local_name(child.tag)
                if kind == "p":
                    text = docx_xml_text(child).strip()
                    if not text:
                        continue
                    style = next((
                        node.attrib.get(
                            "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val"
                        )
                        for node in child.iter() if local_name(node.tag) == "pStyle"
                    ), "")
                    if style and style.lower().startswith("heading"):
                        level_match = re.search(r"(\d+)", style)
                        level = min(int(level_match.group(1)), 6) if level_match else 2
                        part_lines.append("#" * level + " " + text)
                    else:
                        part_lines.append(text)
                elif kind == "tbl":
                    rows = _docx_table_text(child)
                    if rows:
                        part_lines.extend(["[TABLE]", *rows, "[/TABLE]"])
                else:
                    # Notes and comments are nested below note/comment records,
                    # unlike the direct paragraph children in word/document.xml.
                    visit(child)

        visit(root)
        if part_lines:
            output.append(f"## {title}")
            output.extend(part_lines)

    with zipfile.ZipFile(path) as archive:
        validate_ooxml_archive(archive)
        names = set(archive.namelist())
        document = ET.fromstring(read_ooxml_xml_member(archive, "word/document.xml"))
        body = next((node for node in document.iter() if local_name(node.tag) == "body"), None)
        if body is None:
            raise ValueError("DOCX has no document body")
        append_part("Document body", body)

        for member in sorted(
            name for name in names
            if re.fullmatch(r"word/(?:header|footer)\d+\.xml", name)
        ):
            root = ET.fromstring(read_ooxml_xml_member(archive, member))
            label = Path(member).stem.replace("header", "Header ").replace("footer", "Footer ")
            append_part(label, root)

        for member, label in (
            ("word/footnotes.xml", "Footnotes"),
            ("word/endnotes.xml", "Endnotes"),
            ("word/comments.xml", "Comments"),
        ):
            if member in names:
                root = ET.fromstring(read_ooxml_xml_member(archive, member))
                append_part(label, root)

    return "\n\n".join(output).rstrip(), notes
def _chart_cache_values(parent: ET.Element | None) -> list[str]:
    if parent is None:
        return []
    values = []
    for node in parent.iter():
        if local_name(node.tag) in {"v", "t"} and node.text is not None:
            values.append(node.text)
    return values


def parse_chart_xml(archive: zipfile.ZipFile, member: str) -> list[str]:
    """Extract cached category/value labels from an OOXML chart without recalculation."""
    root = ET.fromstring(read_ooxml_xml_member(archive, member))
    output = []
    series_nodes = [node for node in root.iter() if local_name(node.tag) == "ser"]
    for index, series in enumerate(series_nodes, start=1):
        title_node = next((node for node in series if local_name(node.tag) == "tx"), None)
        title_values = _chart_cache_values(title_node)
        title = " ".join(title_values).strip() or f"Series {index}"
        category_node = next(
            (node for node in series if local_name(node.tag) in {"cat", "xVal"}),
            None,
        )
        value_node = next(
            (node for node in series if local_name(node.tag) in {"val", "yVal"}),
            None,
        )
        categories = _chart_cache_values(category_node)
        values = _chart_cache_values(value_node)
        output.append(f"{title}:")
        if categories:
            output.append("  Categories: " + " | ".join(categories))
        if values:
            output.append("  Values: " + " | ".join(values))
        if not categories and not values:
            output.append("  No cached category/value data was embedded in this chart.")
    return output


def append_chart_caches(archive: zipfile.ZipFile, prefix: str, output: list[str]) -> int:
    pattern = re.compile(re.escape(prefix) + r"/charts/chart\d+\.xml$")
    members = sorted(name for name in archive.namelist() if pattern.fullmatch(name))
    for member in members:
        try:
            chart_lines = parse_chart_xml(archive, member)
        except (ET.ParseError, ValueError):
            output.append(f"[Chart data could not be parsed: {member}]")
            continue
        output.append(f"### Chart: {Path(member).name}")
        output.extend(chart_lines)
    return len(members)


def parse_xlsx(path: Path) -> tuple[str, list[str]]:
    notes = [
        "XLSX extraction records sheet visibility, cell addresses, formulas, cached values, hidden rows/columns, merged ranges, defined names, and cached chart data.",
        "Formatting, pivots, macros, external connections, data validation, and spreadsheet formula recalculation are not reproduced. Verify the original workbook for consequential calculations.",
        "Chart values are cached values embedded in the workbook; FidelityFlow does not recalculate formulas or regenerate chart series.",
    ]
    ns = {
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    output: list[str] = []
    with zipfile.ZipFile(path) as archive:
        validate_ooxml_archive(archive)
        names = set(archive.namelist())
        workbook = ET.fromstring(read_ooxml_xml_member(archive, "xl/workbook.xml"))
        rels_root = ET.fromstring(read_ooxml_xml_member(archive, "xl/_rels/workbook.xml.rels"))
        rel_targets = {
            relationship.attrib.get("Id"): relationship.attrib.get("Target", "")
            for relationship in rels_root
        }

        defined_names = next(
            (node for node in workbook.iter() if local_name(node.tag) == "definedNames"),
            None,
        )
        if defined_names is not None:
            names_text = []
            for item in list(defined_names):
                if local_name(item.tag) == "definedName":
                    name = item.attrib.get("name", "unnamed")
                    scope = item.attrib.get("localSheetId")
                    formula = (item.text or "").strip()
                    scope_text = f" (localSheetId={scope})" if scope is not None else ""
                    names_text.append(f"{name}{scope_text} = {formula}")
            if names_text:
                output.append("# Defined names")
                output.extend(names_text)
                output.append("")

        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            shared_root = ET.fromstring(read_ooxml_xml_member(archive, "xl/sharedStrings.xml"))
            shared = [
                "".join(node.text or "" for node in item.iter() if local_name(node.tag) == "t")
                for item in shared_root if local_name(item.tag) == "si"
            ]

        sheets = next(
            (node for node in workbook.iter() if local_name(node.tag) == "sheets"),
            None,
        )
        if sheets is None:
            raise ValueError("XLSX workbook contains no sheets")

        for sheet in list(sheets):
            if local_name(sheet.tag) != "sheet":
                continue
            sheet_name = sheet.attrib.get("name", "Unnamed")
            sheet_state = sheet.attrib.get("state", "visible")
            rid = sheet.attrib.get("{" + ns["rel"] + "}id")
            target = rel_targets.get(rid, "")
            if not target:
                notes.append(f"Could not resolve worksheet relationship for {sheet_name}.")
                continue

            if target.startswith("/"):
                member = target.lstrip("/")
            else:
                member = posixpath.normpath(posixpath.join("xl", target))
            if member.startswith("../") or member not in names:
                notes.append(f"Worksheet XML missing or outside workbook for {sheet_name}: {member}")
                continue

            root = ET.fromstring(read_ooxml_xml_member(archive, member))
            visibility = "" if sheet_state == "visible" else f" [SHEET STATE: {sheet_state}]"
            output.append(f"# Sheet: {sheet_name}{visibility}")

            for column_group in (node for node in root.iter() if local_name(node.tag) == "cols"):
                for column in list(column_group):
                    if local_name(column.tag) != "col" or column.attrib.get("hidden") not in {"1", "true"}:
                        continue
                    output.append(
                        "[HIDDEN COLUMNS: "
                        + column.attrib.get("min", "?") + "-" + column.attrib.get("max", "?")
                        + "]"
                    )

            for row in (node for node in root.iter() if local_name(node.tag) == "row"):
                row_cells = []
                if row.attrib.get("hidden") in {"1", "true"}:
                    output.append(f"[HIDDEN ROW: {row.attrib.get('r', '?')}]")
                for cell in list(row):
                    if local_name(cell.tag) != "c":
                        continue
                    reference = cell.attrib.get("r", "?")
                    cell_type = cell.attrib.get("t", "")
                    formula_node = next(
                        (node for node in cell if local_name(node.tag) == "f"),
                        None,
                    )
                    value_node = next(
                        (node for node in cell if local_name(node.tag) == "v"),
                        None,
                    )
                    inline_node = next(
                        (node for node in cell if local_name(node.tag) == "is"),
                        None,
                    )
                    value = value_node.text if value_node is not None and value_node.text else ""
                    if cell_type == "s" and value:
                        try:
                            value = shared[int(value)]
                        except (ValueError, IndexError):
                            notes.append(f"Invalid shared-string index in {sheet_name}!{reference}.")
                    elif cell_type == "inlineStr" and inline_node is not None:
                        value = "".join(
                            node.text or "" for node in inline_node.iter()
                            if local_name(node.tag) == "t"
                        )
                    elif cell_type == "b":
                        value = "TRUE" if value == "1" else "FALSE"
                    elif cell_type == "e":
                        value = f"[CELL ERROR: {value}]"
                    if formula_node is not None:
                        formula = formula_node.text or ""
                        formula_type = formula_node.attrib.get("t")
                        type_text = f" type={formula_type}" if formula_type else ""
                        row_cells.append(
                            f"{reference} formula=({formula}){type_text} cached_value=({value})"
                        )
                    elif value != "":
                        row_cells.append(f"{reference}={value}")
                if row_cells:
                    output.append(" | ".join(row_cells))

            for merged_group in (node for node in root.iter() if local_name(node.tag) == "mergeCells"):
                ranges = [
                    node.attrib.get("ref", "")
                    for node in list(merged_group) if local_name(node.tag) == "mergeCell"
                ]
                if ranges:
                    output.append("[MERGED CELLS: " + ", ".join(ranges) + "]")

            for auto_filter in (node for node in root.iter() if local_name(node.tag) == "autoFilter"):
                reference = auto_filter.attrib.get("ref")
                if reference:
                    output.append(f"[AUTO FILTER RANGE: {reference}]")
            output.append("")

        chart_count = append_chart_caches(archive, "xl", output)
        if chart_count:
            output.insert(0, "# Cached chart data")
    return "\n".join(output).rstrip(), notes

def _relationship_targets(archive: zipfile.ZipFile, rels_member: str) -> dict[str, str]:
    try:
        root = ET.fromstring(read_ooxml_xml_member(archive, rels_member))
    except (KeyError, ValueError):
        return {}
    output = {}
    base = rels_member.rsplit("/_rels/", 1)[0]
    for relationship in root:
        if local_name(relationship.tag) != "Relationship":
            continue
        target = relationship.attrib.get("Target", "")
        if not target or relationship.attrib.get("TargetMode") == "External":
            continue
        if target.startswith("/"):
            member = target.lstrip("/")
        else:
            member = posixpath.normpath(posixpath.join(base, target))
        if member.startswith("../"):
            continue
        output[relationship.attrib.get("Id", "")] = member
    return output


def parse_pptx(path: Path) -> tuple[str, list[str]]:
    notes = [
        "PPTX extraction preserves slide order, text, basic table content, shape alt text, speaker notes, and cached chart data.",
        "Images, diagrams, animation, exact visual coordinates, and layout are not reconstructed; inspect the original slides for visual tasks.",
        "Chart data is read from embedded cached values and may be stale if the workbook/chart source was not recalculated before saving.",
    ]
    output: list[str] = []
    with zipfile.ZipFile(path) as archive:
        validate_ooxml_archive(archive)
        names = set(archive.namelist())
        slide_names = [
            name for name in names
            if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
        ]
        slide_names.sort(key=lambda name: int(re.search(r"slide(\d+)", name).group(1)))

        for slide_member in slide_names:
            number = int(re.search(r"slide(\d+)", slide_member).group(1))
            root = ET.fromstring(read_ooxml_xml_member(archive, slide_member))
            output.append(f"# Slide {number}")
            rels_member = f"ppt/slides/_rels/slide{number}.xml.rels"
            relationships = _relationship_targets(archive, rels_member)

            for shape in root.iter():
                kind = local_name(shape.tag)
                if kind == "sp":
                    non_visual = next(
                        (node for node in shape.iter() if local_name(node.tag) == "cNvPr"),
                        None,
                    )
                    if non_visual is not None:
                        shape_name = non_visual.attrib.get("name")
                        alternative = non_visual.attrib.get("descr") or non_visual.attrib.get("title")
                        if alternative:
                            output.append(f"[SHAPE ALT TEXT: {alternative}]")
                        elif shape_name and shape_name not in {"TextBox 1", "Rectangle 1"}:
                            output.append(f"[SHAPE: {shape_name}]")

                    transform = next(
                        (node for node in shape.iter() if local_name(node.tag) == "xfrm"),
                        None,
                    )
                    if transform is not None:
                        offset = next((node for node in transform if local_name(node.tag) == "off"), None)
                        extent = next((node for node in transform if local_name(node.tag) == "ext"), None)
                        if offset is not None or extent is not None:
                            values = []
                            if offset is not None:
                                values.extend([f"x={offset.attrib.get('x', '?')}", f"y={offset.attrib.get('y', '?')}"])
                            if extent is not None:
                                values.extend([f"cx={extent.attrib.get('cx', '?')}", f"cy={extent.attrib.get('cy', '?')}"])
                            output.append("[SHAPE POSITION EMU: " + ", ".join(values) + "]")

                    paragraphs = []
                    for paragraph in shape.iter():
                        if local_name(paragraph.tag) == "p":
                            paragraph_text = xml_text(paragraph).strip()
                            if paragraph_text:
                                paragraphs.append(paragraph_text)
                    output.extend(paragraphs)

                elif kind == "pic":
                    non_visual = next(
                        (node for node in shape.iter() if local_name(node.tag) == "cNvPr"),
                        None,
                    )
                    if non_visual is not None:
                        alternative = non_visual.attrib.get("descr") or non_visual.attrib.get("title")
                        if alternative:
                            output.append(f"[IMAGE ALT TEXT: {alternative}]")
                        else:
                            output.append("[IMAGE: no alternative text provided]")

                elif kind == "graphicFrame":
                    rows = []
                    for row in shape.iter():
                        if local_name(row.tag) == "tr":
                            cells = [
                                xml_text(cell).strip()
                                for cell in row.iter() if local_name(cell.tag) == "tc"
                            ]
                            if cells:
                                rows.append(" | ".join(cells))
                    if rows:
                        output.extend(["[TABLE]", *rows, "[/TABLE]"])

            for target in relationships.values():
                if target.startswith("ppt/notesSlides/") and target in names:
                    note_root = ET.fromstring(read_ooxml_xml_member(archive, target))
                    note_lines = []
                    for paragraph in note_root.iter():
                        if local_name(paragraph.tag) == "p":
                            value = xml_text(paragraph).strip()
                            if value and not re.fullmatch(r"\d+", value):
                                note_lines.append(value)
                    if note_lines:
                        output.append("[SPEAKER NOTES]")
                        output.extend(note_lines)
                        output.append("[/SPEAKER NOTES]")
            output.append("")

        chart_count = append_chart_caches(archive, "ppt", output)
        if chart_count:
            output.insert(0, "# Cached chart data")

    if not slide_names:
        notes.append("No standard slide XML files were found.")
    return "\n".join(output).rstrip(), notes

def _load_ocr_engine():
    try:
        from . import ocr_engine
        return ocr_engine
    except ImportError:
        try:
            import ocr_engine  # type: ignore
            return ocr_engine
        except ImportError as exc:
            raise RuntimeError(
                "OCR engine module is missing from this FidelityFlow installation."
            ) from exc


def parse_pdf(
    path: Path,
    ocr: bool = False,
    ocr_lang: str = "eng",
    ocr_dpi: int = 180,
    ocr_max_pages: int = 100,
) -> tuple[str, list[str]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "PDF extraction requires optional dependency pypdf. "
            'Install with: python -m pip install -e ".[pdf]".'
        ) from exc
    reader = PdfReader(str(path))
    extracted_pages = [(page.extract_text() or "") for page in reader.pages]
    notes = [
        "PDF text extraction preserves page markers but may lose visual layout, columns, charts, scanned text, and complex table geometry."
    ]
    sparse_indices = [
        index for index, text in enumerate(extracted_pages)
        if len(text.strip()) < 40
    ]
    if ocr and sparse_indices:
        engine = _load_ocr_engine()
        recognized, ocr_notes = engine.extract_pdf_pages(
            path, sparse_indices, dpi=ocr_dpi, language=ocr_lang,
            max_pages=ocr_max_pages,
        )
        notes.extend(ocr_notes)
        for index, text in recognized.items():
            if text:
                extracted_pages[index] = "\n".join(
                    part for part in (extracted_pages[index].strip(), text) if part
                )
                notes.append(f"Page {index + 1} received OCR because its extracted text was sparse.")
        if len(sparse_indices) > ocr_max_pages:
            notes.append(
                f"OCR page limit reached ({ocr_max_pages}); {len(sparse_indices) - ocr_max_pages} additional sparse pages were not processed."
            )
    elif ocr:
        notes.append("OCR was enabled, but no pages met the sparse-text threshold.")
    if not any(text.strip() for text in extracted_pages):
        notes.append(
            "No extractable text was found. The PDF may be scanned or image-only; enable --ocr and install the OCR extra plus Tesseract."
        )
    pages = [
        f"[PAGE {index + 1}]\n{text}"
        for index, text in enumerate(extracted_pages)
    ]
    return "\n\n".join(pages), notes

def expected_extractor(path: Path, ocr: bool = False) -> str | None:
    suffix = normalized_suffix(path)
    if suffix in OCR_IMAGE_SUFFIXES:
        return "image-ocr-tesseract-v2" if ocr else None
    if suffix == ".docx":
        return "docx-stdlib-v2"
    if suffix == ".xlsx":
        return "xlsx-stdlib-v2"
    if suffix == ".pptx":
        return "pptx-stdlib-v2"
    if suffix == ".pdf":
        return "pdf-pypdf-ocr-v2" if ocr else "pdf-pypdf-v1"
    text_suffixes = {
        ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv",
        ".json", ".jsonl", ".yaml", ".yml", ".xml", ".html", ".htm",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
        ".c", ".h", ".cpp", ".cs", ".sql", ".sh", ".ps1", ".toml",
        ".ini", ".cfg", ".properties", ".diff", ".patch", ".env.example",
    }
    if suffix in text_suffixes or not suffix:
        return "text-utf8-v1"
    return None

def extract_file(
    path: Path,
    ocr: bool = False,
    ocr_lang: str = "eng",
    ocr_dpi: int = 180,
    ocr_max_pages: int = 100,
) -> tuple[str, list[str], str]:
    suffix = normalized_suffix(path)
    if suffix in OCR_IMAGE_SUFFIXES:
        if not ocr:
            raise RuntimeError("Image files require explicit --ocr and the optional OCR dependencies.")
        engine = _load_ocr_engine()
        text, notes = engine.extract_image(path, language=ocr_lang)
        return text, notes, "image-ocr-tesseract-v2"
    if suffix == ".docx":
        text, notes = extract_docx(path)
        return text, notes, "docx-stdlib-v2"
    if suffix == ".xlsx":
        text, notes = parse_xlsx(path)
        return text, notes, "xlsx-stdlib-v2"
    if suffix == ".pptx":
        text, notes = parse_pptx(path)
        return text, notes, "pptx-stdlib-v2"
    if suffix == ".pdf":
        text, notes = parse_pdf(path, ocr, ocr_lang, ocr_dpi, ocr_max_pages)
        return text, notes, "pdf-pypdf-ocr-v2" if ocr else "pdf-pypdf-v1"
    if suffix in {".doc", ".xls", ".ppt"}:
        raise RuntimeError(
            f"Legacy Office format {suffix} is not supported. Save as DOCX, XLSX, or PPTX first, or use Claude's native file handling."
        )
    text_suffixes = {
        ".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv",
        ".json", ".jsonl", ".yaml", ".yml", ".xml", ".html", ".htm",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
        ".c", ".h", ".cpp", ".cs", ".sql", ".sh", ".ps1", ".toml",
        ".ini", ".cfg", ".properties", ".diff", ".patch", ".env.example",
    }
    if suffix in text_suffixes or not suffix:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
            notes = []
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
            notes = [
                "Some bytes were not valid UTF-8 and were replaced during text extraction. The original file remains authoritative."
            ]
        return text, notes, "text-utf8-v1"
    raise RuntimeError(
        f"Unsupported file type: {suffix or '[no extension]'}. Keep the original and use Claude's native file handling or convert explicitly."
    )

CODE_SUFFIXES = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs",
    ".c", ".h", ".cpp", ".cs", ".sql", ".sh", ".ps1",
}


def _structural_patterns(suffix: str | None) -> list[re.Pattern]:
    """Return conservative, line-start patterns for lightweight section boundaries."""
    if suffix in {".md", ".markdown", ".rst"}:
        return [re.compile(r"^\s{0,3}(?:#{1,6}\s+|={3,}\s*$|-{3,}\s*$)")]
    if suffix == ".py":
        return [re.compile(r"^\s{0,16}(?:async\s+def|def|class)\s+\w+")]
    if suffix in {".js", ".ts", ".tsx", ".jsx"}:
        return [
            re.compile(r"^\s{0,16}(?:(?:export|declare)\s+)*(?:default\s+)?(?:async\s+)?function\s+\w*"),
            re.compile(r"^\s{0,16}(?:(?:export|declare)\s+)*(?:abstract\s+)?(?:class|interface|type|enum)\s+\w+"),
            re.compile(r"^\s{0,16}(?:(?:export\s+)?(?:const|let|var))\s+\w+\s*=\s*(?:async\s*)?\("),
        ]
    if suffix == ".go":
        return [
            re.compile(r"^\s{0,16}func\s+(?:\([^)]*\)\s*)?\w+"),
            re.compile(r"^\s{0,16}type\s+\w+\s+(?:struct|interface)"),
        ]
    if suffix == ".rs":
        return [
            re.compile(r"^\s{0,16}(?:(?:pub(?:\([^)]*\))?)\s+)*(?:async\s+)?fn\s+\w+"),
            re.compile(r"^\s{0,16}(?:(?:pub(?:\([^)]*\))?)\s+)*(?:struct|enum|trait|impl)\b"),
        ]
    if suffix in {".java", ".cs"}:
        return [
            re.compile(r"^\s{0,16}(?:(?:public|private|protected|internal|static|abstract|final|sealed|async|partial)\s+)*(?:class|interface|enum|struct)\s+\w+"),
            re.compile(r"^\s{0,16}(?:(?:public|private|protected|internal|static|async|virtual|override|final)\s+)+[\w<>?,\[\].]+\s+\w+\s*\("),
        ]
    if suffix in {".c", ".h", ".cpp"}:
        return [
            re.compile(r"^\s{0,16}(?:class|struct|enum|namespace)\s+\w+"),
            re.compile(r"^\s{0,16}[\w:*&<>~]+\s+\w+\s*\([^;]*\)\s*(?:const\s*)?(?:\{|$)"),
        ]
    return []


def _find_structural_boundary(
    text: str, start: int, end: int, min_chars: int, patterns: list[re.Pattern]
) -> int | None:
    if not patterns:
        return None
    cursor = text.find("\n", start + min_chars - 1, end)
    candidates = []
    while cursor >= 0:
        line_start = cursor + 1
        if line_start >= end:
            break
        line_end = text.find("\n", line_start, end)
        if line_end < 0:
            line_end = end
        line = text[line_start:line_end]
        if any(pattern.match(line) for pattern in patterns):
            candidates.append(line_start)
        cursor = text.find("\n", line_start, end)
    return candidates[0] if candidates else None


def split_chunks(
    text: str,
    max_chars: int = CHUNK_CHARS,
    source_suffix: str | None = None,
) -> list[dict]:
    """Split losslessly, preferring Markdown headings and code symbol boundaries."""
    if not text:
        return []
    chunks = []
    start = 0
    index = 0
    line_start = 1
    length = len(text)
    patterns = _structural_patterns(source_suffix)
    while start < length:
        end = min(start + max_chars, length)
        boundary_type = "limit"
        if end < length:
            structural = _find_structural_boundary(
                text, start, end, max_chars // 2, patterns
            )
            if structural is not None and structural > start:
                end = structural
                boundary_type = "structure"
            else:
                boundary = text.rfind("\n", start + max_chars // 2, end)
                if boundary > start:
                    end = boundary + 1
                    boundary_type = "line"
        if end <= start:
            end = min(start + max_chars, length)
        piece = text[start:end]
        line_end = line_start + piece[:-1].count("\n") if piece else line_start
        chunks.append({
            "chunk": index,
            "char_start": start,
            "char_end": end,
            "line_start": line_start,
            "line_end": line_end,
            "sha256": sha256_bytes(piece.encode("utf-8")),
            "boundary_type": boundary_type,
            "text": piece,
        })
        line_start += piece.count("\n")
        start = end
        index += 1
    assert "".join(chunk["text"] for chunk in chunks) == text
    return chunks
def build_source_map(text: str, source_suffix: str | None = None) -> tuple[list[dict], dict]:
    """Build deterministic, text-offset-based source locations for extracted content.

    Locations are inferred only from explicit extractor markers and cell references.
    They are navigational hints, not claims about visual coordinates or semantic layout.
    """
    suffix = (source_suffix or "").casefold()
    lines = []
    offset = 0
    for line_number, line in enumerate(text.splitlines(keepends=True), start=1):
        content = line.rstrip("\r\n")
        lines.append((offset, offset + len(line), line_number, content))
        offset += len(line)

    events: list[tuple[int, dict]] = []
    counters = Counter()
    context: dict = {"kind": "document"}

    for start, end, line_number, line in lines:
        stripped = line.strip()
        location = None

        match = re.match(r"^\[PAGE\s+(\d+)\]$", stripped, re.IGNORECASE)
        if match:
            location = {"kind": "page", "page": int(match.group(1))}
        else:
            match = re.match(r"^#\s*Slide\s+(\d+)\b", stripped, re.IGNORECASE)
            if match:
                location = {"kind": "slide", "slide": int(match.group(1))}
            else:
                match = re.match(r"^#\s*Sheet:\s*(.+?)\s*$", stripped, re.IGNORECASE)
                if match:
                    location = {"kind": "sheet", "sheet": match.group(1)}
                elif stripped == "[TABLE]":
                    counters["table"] += 1
                    location = {"kind": "table", "table": counters["table"]}
                elif stripped.startswith(("[IMAGE:", "[IMAGE ALT TEXT:", "[SHAPE ALT TEXT:")):
                    counters["image"] += 1
                    location = {"kind": "image", "image": counters["image"]}
                else:
                    match = re.match(r"^###\s*Chart:\s*(.+?)\s*$", stripped, re.IGNORECASE)
                    if match:
                        counters["chart"] += 1
                        location = {"kind": "chart", "chart": match.group(1), "chart_index": counters["chart"]}

        if location:
            context = dict(location)
            context["line"] = line_number
            events.append((start, context))

        if suffix == ".xlsx" or context.get("kind") == "sheet":
            refs = re.findall(r"(?<![A-Za-z0-9_])([A-Z]{1,3}\d+)\s*(?==|formula=)", line)
            if refs:
                cell_event = dict(context)
                cell_event["cell_refs"] = list(dict.fromkeys(refs))[:50]
                cell_event["line"] = line_number
                events.append((start, cell_event))

    events.sort(key=lambda item: item[0])
    locations = []
    event_index = 0
    active = {"kind": "document"}
    for chunk in split_chunks(text, max_chars=max(500, min(CHUNK_CHARS, len(text) or CHUNK_CHARS)),
                              source_suffix=source_suffix):
        while event_index < len(events) and events[event_index][0] < chunk["char_end"]:
            event_offset, event_location = events[event_index]
            if event_offset < chunk["char_start"] or event_offset >= chunk["char_start"]:
                active = {key: value for key, value in event_location.items() if key != "cell_refs"}
            event_index += 1
        chunk_events = [
            event for event_offset, event in events
            if chunk["char_start"] <= event_offset < chunk["char_end"]
            and event.get("cell_refs")
        ]
        location = dict(active)
        cell_refs = []
        for event in chunk_events:
            cell_refs.extend(event.get("cell_refs", []))
        if cell_refs:
            location["cell_refs"] = list(dict.fromkeys(cell_refs))[:50]
        location["line_start"] = chunk["line_start"]
        location["line_end"] = chunk["line_end"]
        locations.append(location)

    summary = {
        "version": 1,
        "chunk_count": len(locations),
        "located_chunks": sum(1 for item in locations if item.get("kind") != "document"),
        "pages": sorted({item["page"] for item in locations if "page" in item}),
        "slides": sorted({item["slide"] for item in locations if "slide" in item}),
        "sheets": sorted({item["sheet"] for item in locations if "sheet" in item}),
        "tables": counters["table"],
        "images": counters["image"],
        "charts": counters["chart"],
    }
    return locations, summary


def format_source_location(location: dict | None) -> str:
    """Render compact, human-readable provenance without inventing missing coordinates."""
    if not isinstance(location, dict):
        return "document"
    parts = []
    for key, label in (("page", "page"), ("slide", "slide"), ("sheet", "sheet"),
                       ("table", "table"), ("image", "image"), ("chart", "chart")):
        if location.get(key) is not None:
            parts.append(f"{label}={location[key]}")
    if location.get("cell_refs"):
        refs = location["cell_refs"]
        parts.append("cells=" + ",".join(refs[:12]) + ("…" if len(refs) > 12 else ""))
    if not parts:
        parts.append(str(location.get("kind", "document")))
    parts.append(f"lines={location.get('line_start', '?')}-{location.get('line_end', '?')}")
    return " | ".join(parts)


def default_cache_dir(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else DEFAULT_CACHE.resolve()


def atomic_write_text(path: Path, text: str) -> None:
    """Write within a prepared cache directory without following a destination symlink."""
    if path.is_symlink():
        raise OSError(f"Refusing to overwrite symlinked cache file: {path}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        if path.is_symlink():
            raise OSError(f"Cache file became a symlink during write: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_cache_document(cache_root: Path, doc_dir: Path) -> None:
    """Create the cache path while rejecting symlinks in its managed directories."""
    cache_root.mkdir(parents=True, exist_ok=True)
    if cache_root.is_symlink() or not cache_root.is_dir():
        raise OSError(f"Cache root is not a regular directory: {cache_root}")
    documents_dir = cache_root / "documents"
    if documents_dir.is_symlink():
        raise OSError(f"Refusing symlinked cache documents directory: {documents_dir}")
    documents_dir.mkdir(exist_ok=True)
    if documents_dir.is_symlink() or not documents_dir.is_dir():
        raise OSError(f"Cache documents path is not a regular directory: {documents_dir}")
    if doc_dir.is_symlink():
        raise OSError(f"Refusing symlinked document cache directory: {doc_dir}")
    doc_dir.mkdir(exist_ok=True)
    if doc_dir.is_symlink() or not doc_dir.is_dir():
        raise OSError(f"Document cache path is not a regular directory: {doc_dir}")
    if os.name != "nt":
        for directory in (cache_root, documents_dir, doc_dir):
            try:
                directory.chmod(0o700)
            except OSError:
                pass
    for name in ("manifest.json", "content.txt", "chunks.jsonl"):
        if (doc_dir / name).is_symlink():
            raise OSError(f"Refusing symlinked cache file: {doc_dir / name}")


def cmd_ingest(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 2
    raw_hash = sha256_file(path)
    ocr_enabled = bool(getattr(args, "ocr", False))
    ocr_lang = str(getattr(args, "ocr_lang", "eng"))
    ocr_dpi = int(getattr(args, "ocr_dpi", DEFAULT_OCR_DPI))
    ocr_max_pages = int(getattr(args, "ocr_max_pages", DEFAULT_OCR_MAX_PAGES))
    extractor_expected = expected_extractor(path, ocr=ocr_enabled)
    if extractor_expected is None:
        message = f"unsupported file type: {path.suffix or '[no extension]'}"
        if normalized_suffix(path) in OCR_IMAGE_SUFFIXES and not ocr_enabled:
            message = "image files require --ocr; install the optional OCR dependencies and Tesseract first"
        print(f"Extraction failed: {message}", file=sys.stderr)
        return 3
    # Include the extractor identity in the cache key. Identical ZIP bytes
    # named .docx and .pptx must never share an incompatible extracted view.
    processing_identity = f"ocr={int(ocr_enabled)}|lang={ocr_lang}|dpi={ocr_dpi}|max_pages={ocr_max_pages}"
    cache_key = sha256_bytes(f"{raw_hash}|{extractor_expected}|{VERSION}|chunk={args.chunk_chars}|{processing_identity}".encode("utf-8"))
    cache_root = default_cache_dir(args.cache_dir)
    doc_dir = cache_root / "documents" / cache_key
    manifest_path = doc_dir / "manifest.json"
    try:
        prepare_cache_document(cache_root, doc_dir)
    except OSError as exc:
        print(f"Cache preparation failed: {exc}", file=sys.stderr)
        return 3
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("extractor_version") == VERSION and manifest.get("extractor") == extractor_expected:
                aliases = manifest.setdefault("source_aliases", [])
                alias = {"name": path.name, "path": str(path)}
                if alias not in aliases:
                    aliases.append(alias)
                    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({"status": "cache_hit", "document_id": manifest.get("document_id", cache_key[:12]), "source": str(path), "cache": str(doc_dir), "chunks": manifest.get("chunk_count", 0)}, ensure_ascii=False))
                return 0
        except (OSError, json.JSONDecodeError):
            pass
    try:
        text, notes, extractor = extract_file(
            path, ocr=ocr_enabled, ocr_lang=ocr_lang,
            ocr_dpi=ocr_dpi, ocr_max_pages=ocr_max_pages,
        )
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 3
    if extractor != extractor_expected:
        print(f"Extraction failed: extractor mismatch ({extractor} != {extractor_expected})", file=sys.stderr)
        return 3
    chunks = split_chunks(text, args.chunk_chars, source_suffix=normalized_suffix(path))
    source_locations, source_map_summary = build_source_map(text, normalized_suffix(path))
    for chunk, location in zip(chunks, source_locations):
        chunk["source_location"] = location
    atomic_write_text(doc_dir / "content.txt", text)
    # Store text once. The index stores offsets, source locations, hashes,
    # and term frequencies only, allowing ranking before reading source text.
    index_lines = []
    for chunk in chunks:
        record = {key: value for key, value in chunk.items() if key != "text"}
        frequencies = Counter(tokenize(chunk["text"]))
        record["term_freq"] = dict(frequencies)
        record["term_count"] = sum(frequencies.values())
        index_lines.append(json.dumps(record, ensure_ascii=False))
    atomic_write_text(doc_dir / "chunks.jsonl", "\n".join(index_lines) + ("\n" if index_lines else ""))
    manifest = {
        "schema_version": 1,
        "fidelityflow_version": VERSION,
        "extractor_version": VERSION,
        "extractor": extractor,
        "document_id": cache_key[:12],
        "cache_key": cache_key,
        "sha256": raw_hash,
        "source_name": path.name,
        "source_aliases": [{"name": path.name, "path": str(path)}],
        "source_path_at_ingest": str(path),
        "source_size_bytes": path.stat().st_size,
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "character_count": len(text),
        "line_count": text.count("\n") + (1 if text else 0),
        "chunk_count": len(chunks),
        "chunk_chars": args.chunk_chars,
        "source_map": source_map_summary,
        "processing": {"ocr": ocr_enabled, "ocr_lang": ocr_lang, "ocr_dpi": ocr_dpi, "ocr_max_pages": ocr_max_pages},
        "warnings": notes,
        "content_file": "content.txt",
        "chunks_file": "chunks.jsonl",
    }
    atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "processed", "document_id": cache_key[:12], "sha256": raw_hash, "source": str(path), "cache": str(doc_dir), "characters": len(text), "chunks": len(chunks), "warnings": notes}, ensure_ascii=False))
    return 0


def read_manifests(cache_root: Path) -> list[tuple[dict, Path]]:
    docs = cache_root / "documents"
    if not docs.exists():
        return []
    result = []
    for item in docs.glob("*/manifest.json"):
        if item.is_symlink() or item.parent.is_symlink():
            continue
        try:
            result.append((json.loads(item.read_text(encoding="utf-8")), item.parent))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(result, key=lambda pair: pair[0].get("processed_at_utc", ""), reverse=True)


def cmd_list(args: argparse.Namespace) -> int:
    cache_root = default_cache_dir(args.cache_dir)
    records = read_manifests(cache_root)
    for manifest, folder in records:
        print(f"{manifest.get('document_id')}  {manifest.get('source_name')}  chunks={manifest.get('chunk_count')}  {folder}")
    if not records:
        print("No indexed documents. Run: python fidelityflow.py ingest <file>")
    return 0


def tokenize(value: str) -> list[str]:
    """Tokenize prose and split common code identifiers while retaining exact names."""
    output: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[\w'-]+", value, flags=re.UNICODE):
        if len(raw) > 128:
            continue
        expanded = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", raw)
        expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", expanded)
        candidates = [raw]
        candidates.extend(re.split(r"[_'-]+", raw))
        candidates.extend(expanded.split())
        candidates.extend(re.split(r"[_'-]+", expanded))
        for candidate in candidates:
            term = candidate.casefold()
            if len(term) > 1 and len(term) <= 128 and term not in seen:
                seen.add(term)
                output.append(term)
    return output


def build_excerpt(text: str, query: str, max_chars: int) -> str:
    """Return a bounded, line-preserving excerpt around the query match."""
    if max_chars < 80:
        max_chars = 80
    if len(text) <= max_chars:
        return text

    prefix = "… [context omitted]\n"
    suffix = "\n… [excerpt truncated; use show]"
    budget = max(1, max_chars - len(prefix) - len(suffix))
    folded = text.casefold()
    phrase = " ".join(query.casefold().split())
    match_at = folded.find(phrase) if phrase else -1
    if match_at < 0:
        positions = [
            folded.find(term)
            for term in tokenize(query)
            if len(term) >= 3 and folded.find(term) >= 0
        ]
        match_at = min(positions) if positions else 0

    start = max(0, match_at - budget // 3)
    if start > 0:
        previous_newline = text.rfind("\n", 0, start)
        if previous_newline >= max(0, start - 120):
            start = previous_newline + 1
    end = min(len(text), start + budget)
    if end < len(text):
        next_boundary = text.rfind("\n", start, end)
        if next_boundary > start + budget // 2:
            end = next_boundary
    excerpt = text[start:end]
    if start > 0:
        excerpt = prefix + excerpt.lstrip("\n")
    if end < len(text):
        excerpt = excerpt.rstrip("\n") + suffix
    return excerpt


def cmd_search(args: argparse.Namespace) -> int:
    cache_root = default_cache_dir(args.cache_dir)
    q_tokens = list(dict.fromkeys(tokenize(args.query)))
    if not q_tokens:
        print("Error: query contains no searchable terms.", file=sys.stderr)
        return 2
    chunks = []
    for manifest, folder in read_manifests(cache_root):
        index_file = folder / "chunks.jsonl"
        content_file = folder / "content.txt"
        if index_file.is_symlink() or content_file.is_symlink():
            continue
        try:
            for line in index_file.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                record["source_name"] = manifest.get("source_name")
                record["document_id"] = manifest.get("document_id")
                record["_content_file"] = str(content_file)
                chunks.append(record)
        except (OSError, json.JSONDecodeError):
            continue
    if not chunks:
        print("No indexed chunks. Run ingest first.")
        return 0
    df = Counter()
    for chunk in chunks:
        df.update(set(chunk.get("term_freq", {})))
    avg_len = sum(int(c.get("term_count", 0)) for c in chunks) / max(1, len(chunks))
    scored = []
    for chunk in chunks:
        tf = chunk.get("term_freq", {})
        doc_length = int(chunk.get("term_count", 0))
        score = 0.0
        for term in q_tokens:
            freq = int(tf.get(term, 0))
            if freq:
                idf = math.log(1 + (len(chunks) - df[term] + 0.5) / (df[term] + 0.5))
                denom = freq + 1.2 * (0.25 + 0.75 * doc_length / max(1, avg_len))
                score += idf * (freq * 2.2) / denom
        if score > 0:
            scored.append((score, chunk))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    content_cache: dict[str, str] = {}
    for rank, (score, chunk) in enumerate(scored[:args.top_k], 1):
        content_file = chunk["_content_file"]
        if content_file not in content_cache:
            try:
                content_cache[content_file] = Path(content_file).read_text(encoding="utf-8")
            except OSError:
                continue
        content = content_cache[content_file]
        full_text = content[chunk["char_start"]:chunk["char_end"]]
        excerpt = build_excerpt(full_text, args.query, args.max_chars)
        location = format_source_location(chunk.get("source_location"))
        print(f"\n## Result {rank} | score={score:.3f} | {chunk['source_name']} | doc={chunk['document_id']} chunk={chunk['chunk']} | {location}")
        print(excerpt)
    if not scored:
        print("No lexical matches. Try alternate terms or use Claude's native Project search for semantic retrieval.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    cache_root = default_cache_dir(args.cache_dir)
    all_docs = read_manifests(cache_root)
    matches = [(m, d) for m, d in all_docs if m.get("document_id") == args.document or m.get("cache_key", "").startswith(args.document)]
    if not matches:
        by_source_hash = [(m, d) for m, d in all_docs if m.get("sha256", "").startswith(args.document)]
        matches = by_source_hash if len(by_source_hash) == 1 else []
    if not matches:
        print(f"Document not found: {args.document}", file=sys.stderr)
        return 2
    manifest, folder = matches[0]
    index_path = folder / "chunks.jsonl"
    content_path = folder / "content.txt"
    if index_path.is_symlink() or content_path.is_symlink():
        print("Refusing to read symlinked cache files.", file=sys.stderr)
        return 3
    try:
        records = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
        content = content_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Could not read cached document: {exc}", file=sys.stderr)
        return 3
    if args.chunk < 0 or args.chunk >= len(records):
        print(f"Chunk index out of range. Available: 0..{max(-1, len(records)-1)}", file=sys.stderr)
        return 2
    record = records[args.chunk]
    chunk_text = content[record["char_start"]:record["char_end"]]
    location = format_source_location(record.get("source_location"))
    print(f"[SOURCE: {manifest['source_name']} | SHA256: {manifest['sha256']} | CHUNK: {record['chunk']} | {location}]")
    print(chunk_text, end="" if chunk_text.endswith("\n") else "\n")
    return 0


def supported_files(root: Path, cache_root: Path | None = None, include_images: bool = False):
    """Yield supported files while pruning ignored directories before descent."""
    excluded = {".git", ".fidelityflow", ".venv", "venv", "node_modules",
                "__pycache__", ".idea", ".vscode", "dist", "build", "target",
                "vendor", "coverage", ".next", ".tox"}
    suffixes = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".markdown",
                ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl", ".yaml",
                ".yml", ".xml", ".html", ".htm", ".py", ".js", ".ts",
                ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".h",
                ".cpp", ".cs", ".sql", ".sh", ".ps1", ".toml", ".ini",
                ".cfg", ".properties", ".diff", ".patch", ".env.example"}
    if include_images:
        suffixes.update(OCR_IMAGE_SUFFIXES)
    cache_resolved = cache_root.resolve() if cache_root is not None else None
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        if cache_resolved is not None and current_path.resolve() == cache_resolved:
            dirnames[:] = []
            continue
        retained_dirs = []
        for dirname in sorted(dirnames):
            candidate = current_path / dirname
            if dirname in excluded or dirname.startswith(".") or candidate.is_symlink():
                continue
            candidate_resolved = candidate.resolve()
            if cache_resolved is not None and (
                candidate_resolved == cache_resolved or cache_resolved in candidate_resolved.parents
            ):
                continue
            retained_dirs.append(dirname)
        dirnames[:] = retained_dirs
        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                continue
            if normalized_suffix(path) in suffixes:
                yield path


def cmd_ingest_dir(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"Error: directory not found: {root}", file=sys.stderr)
        return 2
    cache_root = default_cache_dir(args.cache_dir)
    files = list(supported_files(root, cache_root, include_images=bool(getattr(args, "ocr", False))))
    processed = cache_hits = errors = 0
    for path in files:
        namespace = argparse.Namespace(
            path=str(path), cache_dir=args.cache_dir, chunk_chars=args.chunk_chars,
            ocr=getattr(args, "ocr", False), ocr_lang=getattr(args, "ocr_lang", "eng"),
            ocr_dpi=getattr(args, "ocr_dpi", DEFAULT_OCR_DPI),
            ocr_max_pages=getattr(args, "ocr_max_pages", DEFAULT_OCR_MAX_PAGES),
        )
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            status = cmd_ingest(namespace)
        if status != 0:
            errors += 1
            continue
        try:
            record = json.loads(captured.getvalue())
        except json.JSONDecodeError:
            errors += 1
            continue
        if record.get("status") == "cache_hit":
            cache_hits += 1
        elif record.get("status") == "processed":
            processed += 1
        else:
            errors += 1
    print(json.dumps({
        "files_seen": len(files),
        "processed": processed,
        "cache_hits": cache_hits,
        "errors": errors,
        "cache_dir": str(default_cache_dir(args.cache_dir)),
    }, ensure_ascii=False, indent=2))
    return 1 if errors else 0


def cmd_doctor(args: argparse.Namespace) -> int:
    info = {
        "fidelityflow_version": VERSION,
        "python": sys.version.split()[0],
        "cache_dir": str(default_cache_dir(args.cache_dir)),
        "pypdf_available": False,
        "supported_extractors": [
            "text", "Markdown", "CSV/TSV", "JSON/JSONL", "YAML",
            "XML/HTML", "source code", "DOCX", "XLSX", "PPTX",
        ],
        "limitations": [
            "PDF text extraction requires optional pypdf",
            "image and scanned-page OCR requires the optional ocr extra plus the Tesseract executable and language data",
            "OCR is opt-in with --ocr; visual geometry is optional and neither infers chart values nor diagram semantics",
            "legacy .doc/.xls/.ppt are unsupported",
            "visual layout, charts, macros, and embedded objects may need native inspection",
        ],
    }
    try:
        import pypdf  # type: ignore
        info["pypdf_available"] = True
        info["pypdf_version"] = getattr(pypdf, "__version__", "unknown")
    except ImportError:
        pass
    try:
        engine = _load_ocr_engine()
        info["ocr"] = engine.doctor()
        if info["ocr"].get("ocr_ready_for_images"):
            info["supported_extractors"].append("image OCR (opt-in)")
        if info["ocr"].get("ocr_ready_for_scanned_pdfs"):
            info["supported_extractors"].append("scanned PDF OCR (opt-in)")
        if info["ocr"].get("visual_geometry_ready"):
            info["supported_extractors"].append("visual geometry cues (optional OpenCV)")
    except Exception as exc:
        info["ocr"] = {"available": False, "reason": str(exc)}
    print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0
def archive_dir(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else DEFAULT_ARCHIVE.resolve()


def cmd_show_archive(args: argparse.Namespace) -> int:
    root = archive_dir(args.archive_dir)
    path = root / f"{safe_name(args.ref)}.txt"
    if path.is_symlink():
        print("Refusing to read a symlinked archive file.", file=sys.stderr)
        return 3
    if not path.is_file():
        print(f"Archive not found: {path}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8", errors="replace")
    if args.lines:
        try:
            start_s, end_s = args.lines.split(":", 1)
            start, end = max(1, int(start_s)), max(1, int(end_s))
        except ValueError:
            print("Invalid --lines. Use START:END, e.g. 40:100", file=sys.stderr)
            return 2
        lines = text.splitlines()
        for i in range(start - 1, min(end, len(lines))):
            print(f"{i+1}: {lines[i]}")
    else:
        print(text, end="" if text.endswith("\n") else "\n")
    return 0


def cmd_search_archive(args: argparse.Namespace) -> int:
    root = archive_dir(args.archive_dir)
    path = root / f"{safe_name(args.ref)}.txt"
    if path.is_symlink():
        print("Refusing to read a symlinked archive file.", file=sys.stderr)
        return 3
    if not path.is_file():
        print(f"Archive not found: {path}", file=sys.stderr)
        return 2
    terms = tokenize(args.query)
    found = 0
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines):
        if any(term in line.casefold() for term in terms):
            start, end = max(0, i-1), min(len(lines), i+2)
            print(f"--- lines {start+1}-{end} ---")
            for j in range(start, end):
                print(f"{j+1}: {lines[j]}")
            found += 1
    if not found:
        print("No matching lines.")
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fidelityflow", description="Local, reversible context and file-processing utilities. No network access.")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest", help="Extract and cache a source file without modifying it")
    ingest.add_argument("path")
    ingest.add_argument("--cache-dir")
    ingest.add_argument("--chunk-chars", type=int, default=CHUNK_CHARS)
    ingest.add_argument("--ocr", action="store_true", help="OCR standalone images and sparse-text PDF pages (requires optional OCR stack)")
    ingest.add_argument("--ocr-lang", default="eng", help="Tesseract language or language combination, e.g. eng or ara+eng")
    ingest.add_argument("--ocr-dpi", type=int, default=DEFAULT_OCR_DPI, help="PDF rasterization DPI for OCR (100-300)")
    ingest.add_argument("--ocr-max-pages", type=int, default=DEFAULT_OCR_MAX_PAGES, help="maximum sparse-text PDF pages to OCR (1-500)")
    ingest.set_defaults(func=cmd_ingest)
    ingest_dir = sub.add_parser("ingest-dir", help="Recursively ingest supported files, excluding common generated/vendor folders")
    ingest_dir.add_argument("path")
    ingest_dir.add_argument("--cache-dir")
    ingest_dir.add_argument("--chunk-chars", type=int, default=CHUNK_CHARS)
    ingest_dir.add_argument("--ocr", action="store_true", help="include image files and OCR sparse-text PDF pages")
    ingest_dir.add_argument("--ocr-lang", default="eng", help="Tesseract language or language combination, e.g. eng or ara+eng")
    ingest_dir.add_argument("--ocr-dpi", type=int, default=DEFAULT_OCR_DPI, help="PDF rasterization DPI for OCR (100-300)")
    ingest_dir.add_argument("--ocr-max-pages", type=int, default=DEFAULT_OCR_MAX_PAGES, help="maximum sparse-text PDF pages to OCR (1-500)")
    ingest_dir.set_defaults(func=cmd_ingest_dir)
    ls = sub.add_parser("list", help="List cached source files")
    ls.add_argument("--cache-dir")
    ls.set_defaults(func=cmd_list)
    search = sub.add_parser("search", help="Lexically retrieve relevant chunks from cached files")
    search.add_argument("--query", required=True)
    search.add_argument("--top-k", type=int, default=5)
    search.add_argument("--max-chars", type=int, default=1600)
    search.add_argument("--cache-dir")
    search.set_defaults(func=cmd_search)
    show = sub.add_parser("show", help="Print a complete cached chunk")
    show.add_argument("--document", required=True)
    show.add_argument("--chunk", required=True, type=int)
    show.add_argument("--cache-dir")
    show.set_defaults(func=cmd_show)
    archive = sub.add_parser("show-archive", help="Recover an original archived Bash output")
    archive.add_argument("--ref", required=True)
    archive.add_argument("--lines", help="Optional one-based line range START:END")
    archive.add_argument("--archive-dir")
    archive.set_defaults(func=cmd_show_archive)
    search_archive = sub.add_parser("search-archive", help="Search an archived original Bash output")
    search_archive.add_argument("--ref", required=True)
    search_archive.add_argument("--query", required=True)
    search_archive.add_argument("--archive-dir")
    search_archive.set_defaults(func=cmd_search_archive)
    doctor = sub.add_parser("doctor", help="Report local runtime and optional extractor availability")
    doctor.add_argument("--cache-dir")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if getattr(args, "chunk_chars", CHUNK_CHARS) < 500:
        parser.error("--chunk-chars must be at least 500")
    if getattr(args, "top_k", 1) < 1 or getattr(args, "top_k", 1) > 50:
        parser.error("--top-k must be between 1 and 50")
    if getattr(args, "max_chars", 100) < 100:
        parser.error("--max-chars must be at least 100")
    if getattr(args, "ocr_dpi", DEFAULT_OCR_DPI) < 100 or getattr(args, "ocr_dpi", DEFAULT_OCR_DPI) > 300:
        parser.error("--ocr-dpi must be between 100 and 300")
    if getattr(args, "ocr_max_pages", DEFAULT_OCR_MAX_PAGES) < 1 or getattr(args, "ocr_max_pages", DEFAULT_OCR_MAX_PAGES) > 500:
        parser.error("--ocr-max-pages must be between 1 and 500")
    ocr_lang = getattr(args, "ocr_lang", "eng")
    if ocr_lang and not re.fullmatch(r"[A-Za-z0-9_+.-]+", ocr_lang):
        parser.error("--ocr-lang must contain only language codes separated by +")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
