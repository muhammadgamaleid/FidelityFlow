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
from pathlib import Path
import re
import sys
import textwrap
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from collections import Counter

VERSION = "0.1.0"  # Initial public release; bump when extractor/cache semantics change.
DEFAULT_CACHE = Path.cwd() / ".fidelityflow" / "cache"
DEFAULT_ARCHIVE = Path.cwd() / ".fidelityflow" / "archive"
CHUNK_CHARS = 7000
MAX_OOXML_XML_MEMBER_BYTES = 64 * 1024 * 1024  # Refuse oversized XML parts rather than risk ZIP-bomb memory exhaustion.


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


def extract_docx(path: Path) -> tuple[str, list[str]]:
    notes = ["DOCX extraction preserves paragraph and table text, not pagination or exact visual layout."]
    with zipfile.ZipFile(path) as archive:
        xml = ET.fromstring(read_ooxml_xml_member(archive, "word/document.xml"))
    body = next((x for x in xml.iter() if local_name(x.tag) == "body"), None)
    if body is None:
        raise ValueError("DOCX has no document body")
    output: list[str] = []
    for child in list(body):
        kind = local_name(child.tag)
        if kind == "p":
            text = xml_text(child).strip()
            if text:
                style = next((n.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val")
                              for n in child.iter() if local_name(n.tag) == "pStyle"), "")
                if style and style.lower().startswith("heading"):
                    level_match = re.search(r"(\d+)", style)
                    level = min(int(level_match.group(1)), 6) if level_match else 2
                    output.append("#" * level + " " + text)
                else:
                    output.append(text)
        elif kind == "tbl":
            output.append("[TABLE]")
            for row in child.iter():
                if local_name(row.tag) != "tr":
                    continue
                cells = []
                for cell in list(row):
                    if local_name(cell.tag) == "tc":
                        cell_paras = [xml_text(p).strip() for p in cell.iter() if local_name(p.tag) == "p"]
                        cells.append(" / ".join(x for x in cell_paras if x))
                output.append(" | ".join(cells))
            output.append("[/TABLE]")
    return "\n\n".join(output), notes


def parse_xlsx(path: Path) -> tuple[str, list[str]]:
    notes = ["XLSX extraction records sheet names, cell addresses, formulas, and cached values where present.",
             "Charts, formatting, pivot tables, macros, external links, and full spreadsheet calculation semantics are not reproduced; verify the original workbook for consequential analysis."]
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        workbook = ET.fromstring(read_ooxml_xml_member(archive, "xl/workbook.xml"))
        rels_root = ET.fromstring(read_ooxml_xml_member(archive, "xl/_rels/workbook.xml.rels"))
        rel_targets = {}
        for rel in rels_root:
            rel_targets[rel.attrib.get("Id")] = rel.attrib.get("Target", "")
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(read_ooxml_xml_member(archive, "xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter() if local_name(t.tag) == "t")
                      for si in root if local_name(si.tag) == "si"]
        output: list[str] = []
        sheets = next((x for x in workbook.iter() if local_name(x.tag) == "sheets"), None)
        if sheets is None:
            raise ValueError("XLSX workbook contains no sheets")
        for sheet in list(sheets):
            if local_name(sheet.tag) != "sheet":
                continue
            sheet_name = sheet.attrib.get("name", "Unnamed")
            rid = sheet.attrib.get("{" + ns["rel"] + "}id")
            target = rel_targets.get(rid, "")
            if not target:
                notes.append(f"Could not resolve worksheet relationship for {sheet_name}.")
                continue
            if target.startswith("/"):
                member = target.lstrip("/")
            else:
                member = str(Path("xl") / target).replace("\\", "/")
                # Normalize xl/../ paths without allowing archive extraction.
                parts = []
                for part in member.split("/"):
                    if part == "..":
                        if parts:
                            parts.pop()
                    elif part != ".":
                        parts.append(part)
                member = "/".join(parts)
            if member not in names:
                notes.append(f"Worksheet XML missing for {sheet_name}: {member}")
                continue
            root = ET.fromstring(read_ooxml_xml_member(archive, member))
            output.append(f"# Sheet: {sheet_name}")
            for row in root.iter():
                if local_name(row.tag) != "row":
                    continue
                row_cells = []
                for cell in list(row):
                    if local_name(cell.tag) != "c":
                        continue
                    ref = cell.attrib.get("r", "?")
                    ctype = cell.attrib.get("t", "")
                    formula = next((x.text or "" for x in cell if local_name(x.tag) == "f"), None)
                    value_node = next((x for x in cell if local_name(x.tag) == "v"), None)
                    inline_node = next((x for x in cell if local_name(x.tag) == "is"), None)
                    value = value_node.text if value_node is not None else ""
                    if ctype == "s" and value:
                        try:
                            value = shared[int(value)]
                        except (ValueError, IndexError):
                            pass
                    elif ctype == "inlineStr" and inline_node is not None:
                        value = "".join(t.text or "" for t in inline_node.iter() if local_name(t.tag) == "t")
                    elif ctype == "b":
                        value = "TRUE" if value == "1" else "FALSE"
                    if formula is not None:
                        row_cells.append(f"{ref} formula=({formula}) value=({value})")
                    elif value != "":
                        row_cells.append(f"{ref}={value}")
                if row_cells:
                    output.append(" | ".join(row_cells))
            output.append("")
    return "\n".join(output).rstrip(), notes


def parse_pptx(path: Path) -> tuple[str, list[str]]:
    notes = ["PPTX extraction captures slide text and basic table cell text; it does not reproduce images, charts, diagrams, layout, animations, or speaker notes."]
    with zipfile.ZipFile(path) as archive:
        slide_names = [n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        slide_names.sort(key=lambda n: int(re.search(r"slide(\d+)", n).group(1)))
        output = []
        for slide_name in slide_names:
            num = int(re.search(r"slide(\d+)", slide_name).group(1))
            root = ET.fromstring(read_ooxml_xml_member(archive, slide_name))
            output.append(f"# Slide {num}")
            for shape in root.iter():
                if local_name(shape.tag) == "sp":
                    paragraphs = []
                    for p in shape.iter():
                        if local_name(p.tag) == "p":
                            ptext = xml_text(p).strip()
                            if ptext:
                                paragraphs.append(ptext)
                    output.extend(paragraphs)
                elif local_name(shape.tag) == "graphicFrame":
                    rows = []
                    for row in shape.iter():
                        if local_name(row.tag) == "tr":
                            cells = []
                            for cell in row.iter():
                                if local_name(cell.tag) == "tc":
                                    cells.append(xml_text(cell).strip())
                            if cells:
                                rows.append(" | ".join(cells))
                    if rows:
                        output.append("[TABLE]")
                        output.extend(rows)
                        output.append("[/TABLE]")
            output.append("")
    if not slide_names:
        notes.append("No standard slide XML files were found.")
    return "\n".join(output).rstrip(), notes


def parse_pdf(path: Path) -> tuple[str, list[str]]:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PDF extraction requires optional dependency pypdf. Install with: python -m pip install pypdf. Claude.ai users should use Claude's native PDF handling if the sandbox does not expose this dependency.") from exc
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(f"[PAGE {index}]\n{text}")
    notes = ["PDF text extraction preserves page markers but may lose visual layout, columns, charts, scanned text, and complex table geometry."]
    if not any(p.strip().split("\n", 1)[-1].strip() for p in pages):
        notes.append("No extractable text was found. The PDF may be scanned or image-only; use OCR or inspect the original visually.")
    return "\n\n".join(pages), notes


def expected_extractor(path: Path) -> str | None:
    suffix = normalized_suffix(path)
    if suffix == ".docx":
        return "docx-stdlib-v1"
    if suffix == ".xlsx":
        return "xlsx-stdlib-v1"
    if suffix == ".pptx":
        return "pptx-stdlib-v1"
    if suffix == ".pdf":
        return "pdf-pypdf-v1"
    text_suffixes = {".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".cs", ".sql", ".sh", ".ps1", ".toml", ".ini", ".cfg", ".properties", ".diff", ".patch", ".env.example"}
    if suffix in text_suffixes or not suffix:
        return "text-utf8-v1"
    return None


def extract_file(path: Path) -> tuple[str, list[str], str]:
    suffix = normalized_suffix(path)
    if suffix == ".docx":
        text, notes = extract_docx(path)
        return text, notes, "docx-stdlib-v1"
    if suffix == ".xlsx":
        text, notes = parse_xlsx(path)
        return text, notes, "xlsx-stdlib-v1"
    if suffix == ".pptx":
        text, notes = parse_pptx(path)
        return text, notes, "pptx-stdlib-v1"
    if suffix == ".pdf":
        text, notes = parse_pdf(path)
        return text, notes, "pdf-pypdf-v1"
    if suffix in {".doc", ".xls", ".ppt"}:
        raise RuntimeError(f"Legacy Office format {suffix} is not supported. Save as DOCX, XLSX, or PPTX first, or use Claude's native file handling.")
    if suffix in {".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".xml", ".html", ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".cs", ".sql", ".sh", ".ps1", ".toml", ".ini", ".cfg", ".properties", ".diff", ".patch", ".env.example"} or not suffix:
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
            notes = []
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
            notes = ["Some bytes were not valid UTF-8 and were replaced during text extraction. The original file remains authoritative."]
        return text, notes, "text-utf8-v1"
    raise RuntimeError(f"Unsupported file type: {suffix or '[no extension]'}. Keep the original and use Claude's native file handling or convert explicitly.")


def split_chunks(text: str, max_chars: int = CHUNK_CHARS) -> list[dict]:
    """Split without dropping characters; chunk text concatenation equals input."""
    if not text:
        return []
    chunks = []
    start = 0
    index = 0
    line_start = 1
    length = len(text)
    while start < length:
        end = min(start + max_chars, length)
        if end < length:
            boundary = text.rfind("\n", start + max_chars // 2, end)
            if boundary > start:
                end = boundary + 1
        if end <= start:
            end = min(start + max_chars, length)
        piece = text[start:end]
        # Maintain line offsets incrementally; repeatedly counting from the
        # start of a very large file would make chunking quadratic.
        line_end = line_start + piece[:-1].count("\n") if piece else line_start
        chunks.append({
            "chunk": index,
            "char_start": start,
            "char_end": end,
            "line_start": line_start,
            "line_end": line_end,
            "sha256": sha256_bytes(piece.encode("utf-8")),
            "text": piece,
        })
        line_start += piece.count("\n")
        start = end
        index += 1
    assert "".join(chunk["text"] for chunk in chunks) == text
    return chunks


def default_cache_dir(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else DEFAULT_CACHE.resolve()


def cmd_ingest(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.is_file():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 2
    raw_hash = sha256_file(path)
    extractor_expected = expected_extractor(path)
    if extractor_expected is None:
        print(f"Extraction failed: unsupported file type: {path.suffix or '[no extension]'}", file=sys.stderr)
        return 3
    # Include the extractor identity in the cache key. Identical ZIP bytes
    # named .docx and .pptx must never share an incompatible extracted view.
    cache_key = sha256_bytes(f"{raw_hash}|{extractor_expected}|{VERSION}|chunk={args.chunk_chars}".encode("utf-8"))
    cache_root = default_cache_dir(args.cache_dir)
    doc_dir = cache_root / "documents" / cache_key
    manifest_path = doc_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("extractor_version") == VERSION and manifest.get("extractor") == extractor_expected:
                aliases = manifest.setdefault("source_aliases", [])
                alias = {"name": path.name, "path": str(path)}
                if alias not in aliases:
                    aliases.append(alias)
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({"status": "cache_hit", "document_id": manifest.get("document_id", cache_key[:12]), "source": str(path), "cache": str(doc_dir), "chunks": manifest.get("chunk_count", 0)}, ensure_ascii=False))
                return 0
        except (OSError, json.JSONDecodeError):
            pass
    try:
        text, notes, extractor = extract_file(path)
    except Exception as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 3
    if extractor != extractor_expected:
        print(f"Extraction failed: extractor mismatch ({extractor} != {extractor_expected})", file=sys.stderr)
        return 3
    chunks = split_chunks(text, args.chunk_chars)
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / "content.txt").write_text(text, encoding="utf-8")
    # Store text once. The index stores offsets, source locations, hashes,
    # and term frequencies only, allowing ranking before reading source text.
    with (doc_dir / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for chunk in chunks:
            record = {key: value for key, value in chunk.items() if key != "text"}
            frequencies = Counter(tokenize(chunk["text"]))
            record["term_freq"] = dict(frequencies)
            record["term_count"] = sum(frequencies.values())
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
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
        "warnings": notes,
        "content_file": "content.txt",
        "chunks_file": "chunks.jsonl",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    return [t.casefold() for t in re.findall(r"[\w'-]+", value, flags=re.UNICODE) if len(t) > 1]


def cmd_search(args: argparse.Namespace) -> int:
    cache_root = default_cache_dir(args.cache_dir)
    q_tokens = tokenize(args.query)
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
        excerpt = textwrap.shorten(full_text.replace("\n", " "), width=args.max_chars, placeholder=" … [retrieve full chunk]")
        print(f"\n## Result {rank} | score={score:.3f} | {chunk['source_name']} | doc={chunk['document_id']} chunk={chunk['chunk']} lines={chunk['line_start']}-{chunk['line_end']}")
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
    print(f"[SOURCE: {manifest['source_name']} | SHA256: {manifest['sha256']} | CHUNK: {record['chunk']} | LINES: {record['line_start']}-{record['line_end']}]")
    print(chunk_text, end="" if chunk_text.endswith("\n") else "\n")
    return 0


def supported_files(root: Path, cache_root: Path | None = None):
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
    files = list(supported_files(root, cache_root))
    processed = cache_hits = errors = 0
    for path in files:
        namespace = argparse.Namespace(path=str(path), cache_dir=args.cache_dir, chunk_chars=args.chunk_chars)
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
        "supported_extractors": ["text", "Markdown", "CSV/TSV", "JSON/JSONL", "YAML", "XML/HTML", "source code", "DOCX", "XLSX", "PPTX"],
        "limitations": ["PDF requires optional pypdf", "scanned PDFs and image OCR are not processed", "legacy .doc/.xls/.ppt are unsupported", "visual layout, charts, macros and embedded objects may need native inspection"],
    }
    try:
        import pypdf  # type: ignore
        info["pypdf_available"] = True
        info["pypdf_version"] = getattr(pypdf, "__version__", "unknown")
    except ImportError:
        pass
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
    ingest.set_defaults(func=cmd_ingest)
    ingest_dir = sub.add_parser("ingest-dir", help="Recursively ingest supported files, excluding common generated/vendor folders")
    ingest_dir.add_argument("path")
    ingest_dir.add_argument("--cache-dir")
    ingest_dir.add_argument("--chunk-chars", type=int, default=CHUNK_CHARS)
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
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
