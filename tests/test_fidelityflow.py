from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills" / "fidelityflow" / "scripts" / "fidelityflow.py"
HOOK = ROOT / "hooks" / "post_tool_output.py"
INSTALLER = ROOT / "install.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class SkillPackagingTests(unittest.TestCase):
    def test_claude_ai_skill_description_is_within_documented_limit(self):
        skill = (ROOT / "skills" / "fidelityflow" / "SKILL.md").read_text(encoding="utf-8")
        description = next((line.split(":", 1)[1].strip() for line in skill.splitlines()
                            if line.startswith("description:")), None)
        self.assertIsNotNone(description)
        self.assertLessEqual(len(description), 200)

    def test_release_builder_validates_skill_scripts_and_references(self):
        script = ROOT / "build_release.py"
        proc = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, cwd=ROOT, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        package = ROOT / "dist" / "fidelityflow-claude-ai.zip"
        with zipfile.ZipFile(package) as zf:
            names = set(zf.namelist())
        self.assertIn("fidelityflow/SKILL.md", names)
        self.assertIn("fidelityflow/scripts/fidelityflow.py", names)
        self.assertIn("fidelityflow/scripts/ocr_engine.py", names)
        self.assertIn("fidelityflow/references/file-processing.md", names)


class FidelityFlowCliTests(unittest.TestCase):
    def test_chunking_is_lossless_and_offsets_reconstruct_source(self):
        module = load_module(CLI, "fidelityflow_cli_test")
        text = ("سطر عربي\n" * 2000) + "END"
        chunks = module.split_chunks(text, 700)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(c["text"] for c in chunks), text)
        self.assertEqual("".join(text[c["char_start"]:c["char_end"]] for c in chunks), text)
        for chunk in chunks:
            self.assertEqual(chunk["line_start"], text.count("\n", 0, chunk["char_start"]) + 1)
            self.assertEqual(chunk["line_end"], text.count("\n", 0, max(chunk["char_start"], chunk["char_end"] - 1)) + 1)

    def test_tokenizer_splits_code_identifiers_and_keeps_exact_names(self):
        module = load_module(CLI, "fidelityflow_identifier_tokenizer_test")
        terms = module.tokenize("getUserProfile user_id HTTPClient")
        for term in ("getuserprofile", "get", "user", "profile", "user_id", "id", "httpclient", "http", "client"):
            self.assertIn(term, terms)

    def test_code_chunking_prefers_symbol_boundaries_without_losing_source(self):
        module = load_module(CLI, "fidelityflow_structural_chunker_test")
        source = ("value = 1\n" * 12) + (
            "class OAuthTokenManager:\n"
            "    def get_user_profile(self):\n"
            "        return 'profile'\n"
        ) + ("# trailing explanation\n" * 15)
        chunks = module.split_chunks(source, 200, source_suffix=".py")
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(item["text"] for item in chunks), source)
        self.assertTrue(source[chunks[0]["char_end"]:].startswith("class OAuthTokenManager"))
        self.assertEqual(chunks[0]["boundary_type"], "structure")

    def test_search_excerpt_centers_match_and_preserves_code_line_breaks(self):
        module = load_module(CLI, "fidelityflow_excerpt_test")
        lines = [f"def helper_{i}(): return {i}" for i in range(60)]
        lines[31] = "def important_function(user_id):"
        lines[32] = "    profile = getUserProfile(user_id)"
        lines[33] = "    return profile"
        excerpt = module.build_excerpt("\n".join(lines), "important_function", 180)
        self.assertIn("important_function", excerpt)
        self.assertIn("getUserProfile", excerpt)
        self.assertGreaterEqual(excerpt.count("\n"), 2)
        self.assertLessEqual(len(excerpt), 180)
        self.assertNotIn("def helper_0()", excerpt)

    def test_ingest_cache_search_and_index_does_not_duplicate_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "research.md"
            source.write_text("# Revenue recognition\n\nPerformance obligations are satisfied over time.\n", encoding="utf-8")
            cache = base / "cache"
            first = subprocess.run([sys.executable, str(CLI), "ingest", str(source), "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            payload = json.loads(first.stdout)
            self.assertEqual(payload["status"], "processed")
            index_path = Path(payload["cache"]) / "chunks.jsonl"
            index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
            self.assertNotIn("text", index_rows[0])
            self.assertIn("term_freq", index_rows[0])
            self.assertIn("char_start", index_rows[0])
            second = subprocess.run([sys.executable, str(CLI), "ingest", str(source), "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(json.loads(second.stdout)["status"], "cache_hit")
            search = subprocess.run([sys.executable, str(CLI), "search", "--query", "performance obligations", "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
            self.assertEqual(search.returncode, 0, search.stderr)
            self.assertIn("Performance obligations", search.stdout)

    def test_cache_manifest_cannot_redirect_search_or_show_outside_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source.md"
            source.write_text("Verified source text about context optimization.", encoding="utf-8")
            outside = base / "outside.txt"
            outside.write_text("DO NOT READ THIS FILE", encoding="utf-8")
            cache = base / "cache"
            ingest = subprocess.run([sys.executable, str(CLI), "ingest", str(source), "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
            self.assertEqual(ingest.returncode, 0, ingest.stderr)
            data = json.loads(ingest.stdout)
            manifest_path = Path(data["cache"]) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["content_file"] = str(outside)
            manifest["chunks_file"] = str(outside)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            search = subprocess.run([sys.executable, str(CLI), "search", "--query", "context optimization", "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
            self.assertEqual(search.returncode, 0, search.stderr)
            self.assertIn("Verified source text", search.stdout)
            self.assertNotIn("DO NOT READ THIS FILE", search.stdout)
            show = subprocess.run([sys.executable, str(CLI), "show", "--document", data["document_id"], "--chunk", "0", "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
            self.assertEqual(show.returncode, 0, show.stderr)
            self.assertIn("Verified source text", show.stdout)
            self.assertNotIn("DO NOT READ THIS FILE", show.stdout)


    def test_cache_documents_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            base = Path(tmp)
            outside = Path(outside_tmp)
            source = base / "source.md"
            source.write_text("source text", encoding="utf-8")
            cache = base / "cache"
            (cache / "documents").mkdir(parents=True)
            (cache / "documents").rmdir()
            try:
                (cache / "documents").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            proc = subprocess.run(
                [sys.executable, str(CLI), "ingest", str(source), "--cache-dir", str(cache)],
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 3)
            self.assertFalse(any(outside.iterdir()))

    def test_cache_key_includes_extractor_and_prevents_cross_format_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive_bytes = base / "payload.zip"
            docx_xml = '''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Word document payload</w:t></w:r></w:p></w:body></w:document>'''
            pptx_xml = '''<?xml version="1.0"?><p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Slide payload</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'''
            with zipfile.ZipFile(archive_bytes, "w") as archive:
                archive.writestr("word/document.xml", docx_xml)
                archive.writestr("ppt/slides/slide1.xml", pptx_xml)
            data = archive_bytes.read_bytes()
            docx = base / "same-bytes.docx"
            pptx = base / "same-bytes.pptx"
            docx.write_bytes(data)
            pptx.write_bytes(data)
            cache = base / "cache"
            results = []
            for path in (docx, pptx):
                proc = subprocess.run([sys.executable, str(CLI), "ingest", str(path), "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                results.append(json.loads(proc.stdout))
            self.assertEqual(results[0]["status"], "processed")
            self.assertEqual(results[1]["status"], "processed")
            self.assertNotEqual(results[0]["document_id"], results[1]["document_id"])

    def test_chunk_size_is_part_of_cache_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "long.md"
            source.write_text(("A paragraph with useful words.\n" * 800), encoding="utf-8")
            cache = base / "cache"
            outputs = []
            for size in (700, 900):
                proc = subprocess.run([sys.executable, str(CLI), "ingest", str(source), "--chunk-chars", str(size), "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                outputs.append(json.loads(proc.stdout))
            self.assertEqual(outputs[0]["status"], "processed")
            self.assertEqual(outputs[1]["status"], "processed")
            self.assertNotEqual(outputs[0]["document_id"], outputs[1]["document_id"])

    def test_identical_file_alias_is_added_without_reextracting(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source_a = base / "first.md"
            source_b = base / "second.md"
            source_a.write_text("Same bytes.", encoding="utf-8")
            source_b.write_text("Same bytes.", encoding="utf-8")
            cache = base / "cache"
            for source in (source_a, source_b):
                proc = subprocess.run([sys.executable, str(CLI), "ingest", str(source), "--cache-dir", str(cache)], capture_output=True, text=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
            second_record = json.loads(proc.stdout)
            self.assertEqual(second_record["status"], "cache_hit")
            manifest = json.loads((Path(second_record["cache"]) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual({x["name"] for x in manifest["source_aliases"]}, {"first.md", "second.md"})

    def test_ingest_directory_counts_cache_hits_and_ignores_vendor_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "docs").mkdir()
            (base / "docs" / "a.md").write_text("Alpha source.", encoding="utf-8")
            (base / "node_modules").mkdir()
            (base / "node_modules" / "ignored.md").write_text("Do not ingest.", encoding="utf-8")
            cache = base / "cache"
            command = [sys.executable, str(CLI), "ingest-dir", str(base), "--cache-dir", str(cache)]
            first = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_data = json.loads(first.stdout)
            self.assertEqual(first_data["processed"], 1)
            self.assertEqual(first_data["cache_hits"], 0)
            second = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(second.returncode, 0, second.stderr)
            second_data = json.loads(second.stdout)
            self.assertEqual(second_data["processed"], 0)
            self.assertEqual(second_data["cache_hits"], 1)

    def test_docx_extraction_preserves_paragraph_and_table_text(self):
        module = load_module(CLI, "fidelityflow_docx_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.docx"
            document = '''<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Chapter One</w:t></w:r></w:p>
                <w:p><w:r><w:t>Body text</w:t></w:r></w:p>
                <w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
              </w:body>
            </w:document>'''
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", document)
            text, notes = module.extract_docx(path)
            self.assertIn("# Chapter One", text)
            self.assertIn("Body text", text)
            self.assertIn("A | B", text)

    def test_xlsx_extraction_keeps_formula_and_cached_value(self):
        module = load_module(CLI, "fidelityflow_xlsx_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.xlsx"
            workbook = '''<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Summary" sheetId="1" r:id="rId1"/></sheets></workbook>'''
            rels = '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>'''
            sheet = '''<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Revenue</t></is></c><c r="B1"><f>SUM(B2:B3)</f><v>250</v></c></row></sheetData></worksheet>'''
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("xl/workbook.xml", workbook)
                archive.writestr("xl/_rels/workbook.xml.rels", rels)
                archive.writestr("xl/worksheets/sheet1.xml", sheet)
            text, notes = module.parse_xlsx(path)
            self.assertIn("Sheet: Summary", text)
            self.assertIn("A1=Revenue", text)
            self.assertIn("B1 formula=(SUM(B2:B3)) cached_value=(250)", text)

    def test_pptx_extraction_preserves_slide_and_table_text(self):
        module = load_module(CLI, "fidelityflow_pptx_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.pptx"
            slide = '''<?xml version="1.0" encoding="UTF-8"?>
            <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                   xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <p:cSld><p:spTree>
                <p:sp><p:txBody><a:p><a:r><a:t>Quarterly results</a:t></a:r></a:p></p:txBody></p:sp>
                <p:graphicFrame><a:tbl><a:tr><a:tc><a:txBody><a:p><a:r><a:t>Revenue</a:t></a:r></a:p></a:txBody></a:tc>
                  <a:tc><a:txBody><a:p><a:r><a:t>250</a:t></a:r></a:p></a:txBody></a:tc></a:tr></a:tbl></p:graphicFrame>
              </p:spTree></p:cSld>
            </p:sld>'''
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", slide)
            text, notes = module.parse_pptx(path)
            self.assertIn("# Slide 1", text)
            self.assertIn("Quarterly results", text)
            self.assertIn("Revenue | 250", text)
            self.assertTrue(notes)

    def test_docx_includes_headers_footnotes_and_revision_markers(self):
        module = load_module(CLI, "fidelityflow_docx_extended_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extended.docx"
            document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
              <w:p><w:r><w:t>Current text</w:t></w:r><w:ins><w:r><w:t>Inserted text</w:t></w:r></w:ins><w:del><w:r><w:delText>Deleted text</w:delText></w:r></w:del></w:p>
            </w:body></w:document>"""
            header = """<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Header text</w:t></w:r></w:p></w:hdr>"""
            footnotes = """<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:footnote w:id="1"><w:p><w:r><w:t>Footnote detail</w:t></w:r></w:p></w:footnote></w:footnotes>"""
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", document)
                archive.writestr("word/header1.xml", header)
                archive.writestr("word/footnotes.xml", footnotes)
            extracted, _ = module.extract_docx(path)
            self.assertIn("Current text", extracted)
            self.assertIn("[INSERTED: Inserted text]", extracted)
            self.assertIn("[DELETED: Deleted text]", extracted)
            self.assertIn("Header text", extracted)
            self.assertIn("Footnote detail", extracted)

    def test_xlsx_preserves_hidden_state_merged_ranges_and_chart_cache(self):
        module = load_module(CLI, "fidelityflow_xlsx_extended_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extended.xlsx"
            workbook = """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Summary" sheetId="1" state="hidden" r:id="rId1"/></sheets><definedNames><definedName name="Revenue_Total">Summary!$B$2</definedName></definedNames></workbook>"""
            rels = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>"""
            sheet = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><cols><col min="3" max="4" hidden="1"/></cols><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Revenue</t></is></c></row><row r="2" hidden="1"><c r="B2"><f>SUM(B3:B4)</f><v>500</v></c></row></sheetData><mergeCells count="1"><mergeCell ref="A1:B1"/></mergeCells></worksheet>"""
            chart = """<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart><c:plotArea><c:barChart><c:ser><c:tx><c:v>Revenue</c:v></c:tx><c:cat><c:strRef><c:strCache><c:pt idx="0"><c:v>Q1</c:v></c:pt></c:strCache></c:strRef></c:cat><c:val><c:numRef><c:numCache><c:pt idx="0"><c:v>500</c:v></c:pt></c:numCache></c:numRef></c:val></c:ser></c:barChart></c:plotArea></c:chart></c:chartSpace>"""
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("xl/workbook.xml", workbook)
                archive.writestr("xl/_rels/workbook.xml.rels", rels)
                archive.writestr("xl/worksheets/sheet1.xml", sheet)
                archive.writestr("xl/charts/chart1.xml", chart)
            extracted, _ = module.parse_xlsx(path)
            self.assertIn("Sheet: Summary [SHEET STATE: hidden]", extracted)
            self.assertIn("[HIDDEN COLUMNS: 3-4]", extracted)
            self.assertIn("[HIDDEN ROW: 2]", extracted)
            self.assertIn("[MERGED CELLS: A1:B1]", extracted)
            self.assertIn("Revenue_Total = Summary!$B$2", extracted)
            self.assertIn("Categories: Q1", extracted)
            self.assertIn("Values: 500", extracted)

    def test_pptx_includes_alt_text_speaker_notes_and_cached_chart_data(self):
        module = load_module(CLI, "fidelityflow_pptx_extended_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "extended.pptx"
            slide = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:pic><p:nvPicPr><p:cNvPr id="2" name="Picture 1" descr="Quarterly sales chart"/></p:nvPicPr></p:pic><p:sp><p:txBody><a:p><a:r><a:t>Quarterly summary</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>"""
            rels = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide1.xml"/></Relationships>"""
            speaker_notes = """<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Explain the revenue trend</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>"""
            chart = """<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart><c:plotArea><c:lineChart><c:ser><c:tx><c:v>Sales</c:v></c:tx><c:cat><c:strRef><c:strCache><c:pt idx="0"><c:v>Jan</c:v></c:pt></c:strCache></c:strRef></c:cat><c:val><c:numRef><c:numCache><c:pt idx="0"><c:v>250</c:v></c:pt></c:numCache></c:numRef></c:val></c:ser></c:lineChart></c:plotArea></c:chart></c:chartSpace>"""
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("ppt/slides/slide1.xml", slide)
                archive.writestr("ppt/slides/_rels/slide1.xml.rels", rels)
                archive.writestr("ppt/notesSlides/notesSlide1.xml", speaker_notes)
                archive.writestr("ppt/charts/chart1.xml", chart)
            extracted, _ = module.parse_pptx(path)
            self.assertIn("[IMAGE ALT TEXT: Quarterly sales chart]", extracted)
            self.assertIn("Quarterly summary", extracted)
            self.assertIn("Explain the revenue trend", extracted)
            self.assertIn("Categories: Jan", extracted)
            self.assertIn("Values: 250", extracted)

    def test_oversized_docx_xml_member_is_rejected_before_reading(self):
        module = load_module(CLI, "fidelityflow_docx_limit_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "oversized.docx"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", "<document>" + ("x" * 200) + "</document>")
            module.MAX_OOXML_XML_MEMBER_BYTES = 64
            with self.assertRaisesRegex(ValueError, "safety limit|limit is"):
                module.extract_docx(path)

    def test_env_example_multisuffix_is_recognized(self):
        module = load_module(CLI, "fidelityflow_env_example_test")
        path = Path(".env.example")
        self.assertEqual(module.normalized_suffix(path), ".env.example")
        self.assertEqual(module.expected_extractor(path), "text-utf8-v1")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / ".env.example").write_text("SAFE=example\n", encoding="utf-8")
            hidden = base / ".private"
            hidden.mkdir()
            (hidden / "hidden.md").write_text("must not be indexed", encoding="utf-8")
            files = list(module.supported_files(base))
            self.assertEqual([item.name for item in files], [".env.example"])

    def test_sha256_file_matches_bytes_hash(self):
        module = load_module(CLI, "fidelityflow_hash_test")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bytes.bin"
            path.write_bytes(b"x" * 2_000_000)
            self.assertEqual(module.sha256_file(path), module.sha256_bytes(path.read_bytes()))


class FidelityFlowHookTests(unittest.TestCase):
    def run_hook(self, tmp: Path, stdout: str, command: str = "pytest tests -v", stderr: str = ""):
        event = {
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "cwd": str(tmp),
            "tool_use_id": "toolu_test_001",
            "tool_input": {"command": command},
            "tool_response": {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False},
        }
        env = dict(os.environ)
        env["FIDELITYFLOW_HOOK_MIN_CHARS"] = "1000"
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def run_precompact_hook(self, home: Path, *, custom_instructions: str | None = None):
        event = {
            "hook_event_name": "PreCompact",
            "session_id": "session-1",
            "cwd": str(home),
            "trigger": "manual",
        }
        if custom_instructions is not None:
            event["custom_instructions"] = custom_instructions
        env = dict(os.environ)
        env["HOME"] = str(home)
        proc = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(event),
            capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def run_read_hook(self, home: Path, *, event_name: str = "PostToolUse", session_id: str = "session-1",
                      agent_id: str = "main", file_path: str = "docs/source.md", offset=None, limit=None,
                      response: str = "source line\n" * 300):
        tool_input = {"file_path": file_path}
        if offset is not None:
            tool_input["offset"] = offset
        if limit is not None:
            tool_input["limit"] = limit
        event = {
            "hook_event_name": event_name,
            "tool_name": "Read",
            "session_id": session_id,
            "agent_id": agent_id,
            "cwd": str(home),
            "tool_use_id": "read-tool-use",
            "tool_input": tool_input,
            "tool_response": response,
        }
        if event_name == "SessionStart":
            event["source"] = "clear"
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["FIDELITYFLOW_READ_DEDUP_MIN_CHARS"] = "1000"
        proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout if event_name == "PreCompact" else json.loads(proc.stdout)

    def test_precompact_returns_plain_language_preservation_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = self.run_precompact_hook(Path(tmp))
            self.assertIn("FIDELITYFLOW — CONTEXT COMPACTION POLICY", output)
            self.assertIn("current objective", output)
            self.assertIn("failed tests", output)
            self.assertIn("latest explicit user instruction", output)
            self.assertIn("Open Work", output)
            self.assertLess(len(output), 5000)
            self.assertFalse(output.lstrip().startswith("{"))

    def test_precompact_includes_user_instructions_and_safe_session_brief(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / ".fidelityflow"
            folder.mkdir()
            (folder / "session-brief.md").write_text(
                "# Project checkpoint\nCurrent goal: finish OCR tests.\nDo not publish yet.",
                encoding="utf-8",
            )
            output = self.run_precompact_hook(
                root, custom_instructions="Preserve the open API compatibility question."
            )
            self.assertIn("Preserve the open API compatibility question.", output)
            self.assertIn("Current goal: finish OCR tests.", output)
            self.assertIn("Do not publish yet.", output)
            self.assertIn("newer explicit conversation statements take precedence", output)

    def test_precompact_ignores_symlinked_session_brief(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            folder = root / ".fidelityflow"
            folder.mkdir()
            secret = Path(outside) / "brief.md"
            secret.write_text("EXTERNAL PRIVATE BRIEF SHOULD NOT BE READ", encoding="utf-8")
            (folder / "session-brief.md").symlink_to(secret)
            output = self.run_precompact_hook(root)
            self.assertNotIn("EXTERNAL PRIVATE BRIEF SHOULD NOT BE READ", output)

    def test_exact_duplicate_large_read_is_suppressed_without_archiving_or_losing_first_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            original = "Confidential source body that must never be copied into the dedup cache.\n" * 100
            first = self.run_read_hook(home, response=original)
            self.assertEqual(first, {})  # the first full Read passes through unchanged
            second = self.run_read_hook(home, response=original)
            note = second["hookSpecificOutput"]["updatedToolOutput"]
            self.assertIn("One exact duplicate Read suppressed", note)
            self.assertIn("docs/source.md", note)
            self.assertIn("next identical Read is deliberately passed through", note)
            self.assertNotIn("Confidential source body", note)
            # The very next identical read is a full recovery read; after that,
            # another single duplicate may be suppressed.
            self.assertEqual(self.run_read_hook(home, response=original), {})
            fourth = self.run_read_hook(home, response=original)
            self.assertIn("One exact duplicate Read suppressed", fourth["hookSpecificOutput"]["updatedToolOutput"])
            markers = list((home / ".claude" / "fidelityflow" / "read-dedup").rglob("*.seen"))
            self.assertEqual(len(markers), 1)
            self.assertIn("fidelityflow-read-dedup-v2:suppressed", markers[0].read_text(encoding="ascii"))
            self.assertNotIn("Confidential source body", markers[0].read_text(encoding="ascii"))

    def test_changed_read_content_or_requested_range_is_not_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            original = "same source line\n" * 300
            self.assertEqual(self.run_read_hook(home, response=original, offset=1, limit=300), {})
            self.assertEqual(self.run_read_hook(home, response=original + "changed\n", offset=1, limit=300), {})
            self.assertEqual(self.run_read_hook(home, response=original, offset=301, limit=300), {})
            self.assertEqual(self.run_read_hook(home, response=original, offset=1, limit=300, file_path="docs/other.md"), {})

    def test_precompact_clears_read_dedup_for_all_agents_and_resets_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            original = "source content\n" * 300
            self.assertEqual(self.run_read_hook(home, response=original, agent_id="main"), {})
            self.assertEqual(self.run_read_hook(home, response=original, agent_id="subagent-a"), {})
            root = home / ".claude" / "fidelityflow" / "read-dedup"
            self.assertEqual(len(list(root.rglob("*.seen"))), 2)
            compact = self.run_read_hook(home, event_name="PreCompact", response="unused", agent_id="main")
            self.assertIn("FIDELITYFLOW — CONTEXT COMPACTION POLICY", compact)
            self.assertIn("Open Work", compact)
            self.assertFalse(any(root.rglob("*.seen")))
            # Both agents must pass a full result after the session context is compacted.
            self.assertEqual(self.run_read_hook(home, response=original, agent_id="main"), {})
            self.assertEqual(self.run_read_hook(home, response=original, agent_id="subagent-a"), {})

    def test_session_end_cleans_read_dedup_state_for_all_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            original = "source content\n" * 300
            self.assertEqual(self.run_read_hook(home, response=original, agent_id="main"), {})
            self.assertEqual(self.run_read_hook(home, response=original, agent_id="subagent-a"), {})
            self.run_read_hook(home, event_name="SessionEnd", response="unused")
            root = home / ".claude" / "fidelityflow" / "read-dedup"
            self.assertFalse(any(root.rglob("*.seen")))

    def test_session_start_after_clear_removes_markers_for_all_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            original = "source content\n" * 300
            self.assertEqual(self.run_read_hook(home, response=original, agent_id="main"), {})
            self.assertEqual(self.run_read_hook(home, response=original, agent_id="subagent-a"), {})
            event = {
                "hook_event_name": "SessionStart", "source": "clear", "session_id": "session-1",
            }
            result = self.run_read_hook(home, event_name="SessionStart", response="unused")
            self.assertEqual(result, {})
            root = home / ".claude" / "fidelityflow" / "read-dedup"
            self.assertFalse(any(root.rglob("*.seen")))

    def test_read_dedup_fails_open_when_marker_root_is_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as target:
            home = Path(tmp)
            marker_root = home / ".claude" / "fidelityflow" / "read-dedup"
            marker_root.parent.mkdir(parents=True)
            marker_root.symlink_to(Path(target), target_is_directory=True)
            original = "source content\n" * 300
            self.assertEqual(self.run_read_hook(home, response=original), {})
            self.assertEqual(self.run_read_hook(home, response=original), {})

    def test_short_or_missing_session_read_is_never_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            short = "short read"
            self.assertEqual(self.run_read_hook(home, response=short), {})
            # No session id means no reliable context-epoch boundary.
            event = {
                "hook_event_name": "PostToolUse", "tool_name": "Read", "cwd": tmp,
                "tool_input": {"file_path": "docs/source.md"}, "tool_response": "long source\n" * 300,
            }
            env = dict(os.environ)
            env["HOME"] = str(home)
            env["FIDELITYFLOW_READ_DEDUP_MIN_CHARS"] = "1000"
            proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), {})

    def test_recognized_pytest_output_is_compacted_and_archived_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            passing = "".join(f"tests/test_module.py::test_case_{i} PASSED [ {i % 100:2d}% ]\n" for i in range(700))
            original = "============================= test session starts =============================\n" + passing + "============================= 700 passed in 8.42s =============================\n"
            result = self.run_hook(Path(tmp), original)
            output = result["hookSpecificOutput"]["updatedToolOutput"]
            self.assertLess(len(output["stdout"]), len(original))
            self.assertIn("700 passed", output["stdout"])
            self.assertIn("FIDELITYFLOW", output["stdout"])
            archive = Path(tmp) / ".fidelityflow" / "archive" / "toolu_test_001.txt"
            self.assertTrue(archive.is_file())
            self.assertEqual(archive.read_text(encoding="utf-8"), original)

    def test_failing_pytest_run_is_left_completely_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            passed = "".join(f"tests/test_x.py::test_ok_{i} PASSED [ {i % 100:2d}% ]\n" for i in range(200))
            failure = "________________________ test_payment_failure ________________________\nE       AssertionError: total mismatch\nassert 10 == 11\n"
            original = passed + failure + "============================= 200 passed, 1 failed in 9.2s =============================\n"
            self.assertEqual(self.run_hook(Path(tmp), original), {})
            self.assertFalse((Path(tmp) / ".fidelityflow" / "archive").exists())

    def test_successful_unittest_output_can_be_compacted_when_routed_to_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            passing = "".join(f"test_case_{i} (tests.test_suite.Sample) ... ok\n" for i in range(500))
            original = passing + "\n----------------------------------------------------------------------\nRan 500 tests in 2.1s\n\nOK\n"
            result = self.run_hook(Path(tmp), original, command="python -m unittest -v 2>&1")
            output = result["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
            self.assertLess(len(output), len(original))
            self.assertIn("Ran 500 tests in 2.1s", output)
            self.assertTrue((Path(tmp) / ".fidelityflow" / "archive" / "toolu_test_001.txt").is_file())

    def test_non_post_tool_use_event_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = {
                "hook_event_name": "PostToolUseFailure",
                "tool_name": "Bash",
                "cwd": tmp,
                "tool_use_id": "failed",
                "tool_input": {"command": "pytest tests -v"},
                "tool_response": {"stdout": "long output", "stderr": "failure", "interrupted": False, "isImage": False},
            }
            env = dict(os.environ)
            proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(json.loads(proc.stdout), {})

    def test_unknown_command_is_never_compacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = "routine output line\n" * 800
            self.assertEqual(self.run_hook(Path(tmp), original, command="python custom_report.py"), {})

    def test_json_is_not_compacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = json.dumps({"rows": list(range(1000))})
            self.assertEqual(self.run_hook(Path(tmp), original), {})

    def test_git_diff_is_not_compacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = "diff --git a/a.py b/a.py\n" + ("+x = 1\n" * 500)
            self.assertEqual(self.run_hook(Path(tmp), original), {})

    def test_stderr_is_not_compacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = "test_case PASSED [ 1% ]\n" * 600 + "================ 600 passed in 2s ================\n"
            self.assertEqual(self.run_hook(Path(tmp), original, stderr="critical error"), {})

    def test_secret_pattern_is_not_archived(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = ("test_case PASSED [ 1% ]\n" * 600) + "sk-ant-abcdefghijklmnopqrstuvwxyz1234567890\n================ 600 passed in 2s ================\n"
            self.assertEqual(self.run_hook(Path(tmp), original), {})
            self.assertFalse((Path(tmp) / ".fidelityflow" / "archive").exists())

    def test_jsonl_output_is_not_compacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = "\n".join(json.dumps({"event": "pass", "index": i}) for i in range(600)) + "\n"
            self.assertEqual(self.run_hook(Path(tmp), original, command="go test ./..."), {})
            self.assertFalse((Path(tmp) / ".fidelityflow" / "archive").exists())

    def test_cargo_output_with_any_failed_summary_is_not_compacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = ("test sample::works ... ok\n" * 500) + (
                "test result: ok. 500 passed; 0 failed\n"
                "test result: FAILED. 1 failed; 0 passed\n"
            )
            self.assertEqual(self.run_hook(Path(tmp), original, command="cargo test"), {})
            self.assertFalse((Path(tmp) / ".fidelityflow" / "archive").exists())

    def test_npm_test_script_is_not_assumed_to_have_safe_output_grammar(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = "test case passed\n" * 1000
            self.assertEqual(self.run_hook(Path(tmp), original, command="npm test"), {})
            self.assertFalse((Path(tmp) / ".fidelityflow" / "archive").exists())

    @unittest.skipIf(os.name == "nt", "POSIX symlink permissions and semantics required")
    def test_hook_fails_open_when_archive_path_is_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            archive_dir = base / ".fidelityflow" / "archive"
            archive_dir.mkdir(parents=True)
            outside = base / "outside"
            outside.mkdir()
            (archive_dir / "toolu_test_001.txt").symlink_to(outside / "important.txt")
            stdout = "".join(f"tests/test_module.py::test_case_{i} PASSED [ {i % 100:2d}% ]\n" for i in range(700))
            stdout = "============================= test session starts =============================\n" + stdout + "============================= 700 passed in 8.42s =============================\n"
            self.assertEqual(self.run_hook(base, stdout), {})
            self.assertFalse((outside / "important.txt").exists())

    def test_invalid_threshold_environment_fails_safe_and_archive_permissions_are_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            passing = "".join(f"tests/test_module.py::test_case_{i} PASSED [ {i % 100:2d}% ]\n" for i in range(700))
            original = "============================= test session starts =============================\n" + passing + "============================= 700 passed in 8.42s =============================\n"
            event = {
                "hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": tmp,
                "tool_use_id": "private_archive", "tool_input": {"command": "pytest tests -v"},
                "tool_response": {"stdout": original, "stderr": "", "interrupted": False, "isImage": False},
            }
            env = dict(os.environ)
            env["FIDELITYFLOW_HOOK_MIN_CHARS"] = "not-a-number"
            proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event), capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertIn("hookSpecificOutput", result)
            if os.name != "nt":
                archive = Path(tmp) / ".fidelityflow" / "archive" / "private_archive.txt"
                self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
                self.assertEqual(archive.parent.stat().st_mode & 0o777, 0o700)


class UsageTelemetryTests(unittest.TestCase):
    def test_usage_parser_counts_uncached_cache_and_output_separately(self):
        script = ROOT / "benchmarks" / "read_claude_usage.py"
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / "session.jsonl"
            rows = [
                {"uuid": "msg-1", "message": {"id": "msg-1", "model": "claude-sonnet-test", "usage": {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40}}},
                {"uuid": "msg-1-duplicate", "message": {"id": "msg-1", "model": "claude-sonnet-test", "usage": {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 30, "cache_read_input_tokens": 40}}},
            ]
            transcript.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(script), str(transcript)], capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("input_tokens: 100", proc.stdout)
            self.assertIn("cache_creation_input_tokens: 30", proc.stdout)
            self.assertIn("cache_read_input_tokens: 40", proc.stdout)
            self.assertIn("output_tokens: 20", proc.stdout)
            self.assertIn("context_input_tokens_including_cache: 170", proc.stdout)



class UnifiedPackageCliTests(unittest.TestCase):
    def test_module_entrypoint_routes_file_commands_to_the_indexer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source.md"
            source.write_text("Revenue contracts contain performance obligations.", encoding="utf-8")
            cache = base / "cache"
            ingest = subprocess.run(
                [sys.executable, "-m", "fidelityflow", "ingest", str(source),
                 "--cache-dir", str(cache)],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(ingest.returncode, 0, ingest.stderr)
            self.assertEqual(json.loads(ingest.stdout)["status"], "processed")
            search = subprocess.run(
                [sys.executable, "-m", "fidelityflow", "search", "--query",
                 "performance obligations", "--cache-dir", str(cache)],
                cwd=ROOT, capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(search.returncode, 0, search.stderr)
            self.assertIn("performance obligations", search.stdout.lower())

    def test_module_entrypoint_help_and_version(self):
        help_result = subprocess.run(
            [sys.executable, "-m", "fidelityflow"], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("ingest-dir", help_result.stdout)
        version = subprocess.run(
            [sys.executable, "-m", "fidelityflow", "--version"], cwd=ROOT,
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertIn("0.5.0", version.stdout)


class InstallerTests(unittest.TestCase):
    def test_settings_merge_preserves_existing_hooks(self):
        module = load_module(INSTALLER, "fidelityflow_installer_test")
        settings = {"model": "sonnet", "hooks": {"PreToolUse": [{"matcher": "Read", "hooks": [{"type": "command", "command": "existing"}]}]}}
        merged, changed = module.merge_hook(settings, "python hook.py")
        self.assertTrue(changed)
        self.assertEqual(merged["model"], "sonnet")
        self.assertEqual(merged["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "existing")
        self.assertEqual(merged["hooks"]["PostToolUse"][0]["matcher"], "Read|Bash|Grep|Glob|WebSearch|WebFetch|NotebookRead|mcp__.*")
        self.assertIn("PreCompact", merged["hooks"])
        self.assertIn("SessionEnd", merged["hooks"])
        self.assertEqual(merged["hooks"]["SessionStart"][0]["matcher"], "clear")
        merged_again, changed_again = module.merge_hook(merged, "python hook.py")
        self.assertFalse(changed_again)
        self.assertEqual(merged_again, merged)

    def test_upgrades_legacy_read_bash_matcher_without_registering_duplicate(self):
        module = load_module(INSTALLER, "fidelityflow_installer_upgrade_test")
        old_command = "python hook.py"
        settings = {
            "hooks": {
                "PostToolUse": [{
                    "matcher": "Read|Bash",
                    "hooks": [{"type": "command", "command": old_command, "timeout": 8}],
                }]
            }
        }
        merged, changed = module.merge_hook(settings, old_command)
        self.assertTrue(changed)
        entries = merged["hooks"]["PostToolUse"]
        fidelity_entries = [
            item for item in entries
            if any(h.get("command") == old_command for h in item.get("hooks", []))
        ]
        self.assertEqual(len(fidelity_entries), 1)
        self.assertEqual(
            fidelity_entries[0]["matcher"],
            "Read|Bash|Grep|Glob|WebSearch|WebFetch|NotebookRead|mcp__.*",
        )

    def test_settings_merge_refuses_malformed_hooks(self):
        module = load_module(INSTALLER, "fidelityflow_installer_invalid_test")
        with self.assertRaises(ValueError):
            module.merge_hook({"hooks": {"PostToolUse": "not-a-list"}}, "python hook.py")

    def test_project_scope_refuses_machine_specific_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(INSTALLER), "--scope", "project", "--enable-output-hook"],
                cwd=tmp, capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("only be installed with --scope user", proc.stderr)
            self.assertFalse((Path(tmp) / ".claude").exists())

    def test_user_install_copies_skill_and_cli_without_enabling_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["HOME"] = tmp
            proc = subprocess.run(
                [sys.executable, str(INSTALLER), "--scope", "user"],
                capture_output=True, text=True, env=env, timeout=20,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            base = Path(tmp) / ".claude"
            installed_skill = base / "skills" / "fidelityflow"
            self.assertTrue((installed_skill / "SKILL.md").is_file())
            self.assertTrue((installed_skill / "scripts" / "fidelityflow.py").is_file())
            self.assertFalse((base / "settings.json").exists())
            self.assertFalse(any(installed_skill.rglob("*.pyc")))

    def test_hook_only_installs_hook_without_duplicate_synced_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["HOME"] = tmp
            proc = subprocess.run(
                [sys.executable, str(INSTALLER), "--scope", "user", "--enable-output-hook", "--hook-only"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            base = Path(tmp) / ".claude"
            hook_path = base / "hooks" / "fidelityflow" / "post_tool_output.py"
            self.assertTrue(hook_path.is_file())
            self.assertFalse((base / "skills" / "fidelityflow").exists())
            settings = json.loads((base / "settings.json").read_text(encoding="utf-8"))
            command = settings["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
            self.assertIn(str(hook_path), command)
            self.assertEqual(settings["hooks"]["PostToolUse"][0]["matcher"], "Read|Bash|Grep|Glob|WebSearch|WebFetch|NotebookRead|mcp__.*")
            self.assertIn("PreCompact", settings["hooks"])
            self.assertIn("SessionEnd", settings["hooks"])
            self.assertEqual(settings["hooks"]["SessionStart"][0]["matcher"], "clear")

    def test_hook_only_requires_output_hook_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["HOME"] = tmp
            proc = subprocess.run(
                [sys.executable, str(INSTALLER), "--scope", "user", "--hook-only"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("requires --enable-output-hook", proc.stderr)
            self.assertFalse((Path(tmp) / ".claude").exists())

    def test_malformed_settings_do_not_leave_partial_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / ".claude"
            base.mkdir()
            (base / "settings.json").write_text("{ invalid", encoding="utf-8")
            env = dict(os.environ)
            env["HOME"] = tmp
            proc = subprocess.run(
                [sys.executable, str(INSTALLER), "--scope", "user", "--enable-output-hook"],
                capture_output=True, text=True, env=env, timeout=30,
            )
            self.assertEqual(proc.returncode, 3)
            self.assertIn("no files were changed", proc.stderr)
            self.assertFalse((base / "skills" / "fidelityflow").exists())


class SourceMappingTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module(CLI, "fidelityflow_source_mapping_test")

    def test_source_map_tracks_multiple_pdf_pages_across_chunks(self):
        source = "[PAGE 1]\n" + ("first page text\n" * 60) + "[PAGE 2]\n" + ("second page text\n" * 60)
        mapped, summary = self.module.build_source_map(source, ".pdf", max_chars=500)
        self.assertEqual(len(mapped), len(self.module.split_chunks(source, 500, ".pdf")))
        self.assertIn(1, summary["pages"])
        self.assertIn(2, summary["pages"])
        self.assertTrue(all(item["line_start"] <= item["line_end"] for item in mapped))

    def test_source_map_tracks_xlsx_sheet_and_cell_addresses(self):
        source = "# Sheet: Revenue\nA1=Total | B1=100\nA2=Net income | B2=80\n"
        mapped, summary = self.module.build_source_map(source, ".xlsx", max_chars=500)
        self.assertEqual(summary["sheets"], ["Revenue"])
        refs = mapped[0]["cell_refs"]
        self.assertEqual(refs, ["A1", "B1", "A2", "B2"])
        self.assertIn("sheet=Revenue", self.module.format_source_location(mapped[0]))

    def test_source_map_tracks_pptx_slides_tables_and_images(self):
        source = (
            "# Slide 1\nIntro\n[TABLE]\nName | Value\n[/TABLE]\n"
            "# Slide 2\n[IMAGE ALT TEXT: Revenue chart]\nConclusion\n"
        )
        mapped, summary = self.module.build_source_map(source, ".pptx", max_chars=500)
        self.assertEqual(summary["slides"], [1, 2])
        self.assertEqual(summary["tables"], 1)
        self.assertEqual(summary["images"], 1)
        rendered = " ".join(self.module.format_source_location(item) for item in mapped)
        self.assertIn("slide=1", rendered)
        self.assertIn("slide=2", rendered)
        self.assertIn("table=1", rendered)
        self.assertIn("image=1", rendered)

    def test_source_map_tracks_ocr_pixel_regions_and_image_dimensions(self):
        source = (
            "[IMAGE: scan.png]\n"
            "[IMAGE_DIMENSIONS width=1200 height=800 coordinate_space=pixels]\n"
            "[OCR_QUALITY mean_word_confidence=91.0 psm=6]\n"
            "[OCR_LAYOUT]\n"
            "[OCR_LINE x=10:210 y=30:70 confidence=92] Revenue 2026\n"
            "[/OCR_LAYOUT]\n"
        )
        mapped, summary = self.module.build_source_map(source, ".png", max_chars=7000)
        self.assertEqual(summary["regions"], 1)
        region = mapped[0]["regions"][0]
        self.assertEqual(region["kind"], "ocr_text_line")
        self.assertEqual(region["bbox"], {"x": 10, "y": 30, "width": 200, "height": 40})
        self.assertEqual(region["image_dimensions"]["width"], 1200)
        self.assertIn("OCR bbox(px)=10,30,200,40", self.module.format_source_location(mapped[0]))

    def test_source_map_tracks_powerpoint_embedded_image_regions(self):
        source = (
            "# Slide 3\n"
            "[SLIDE_DIMENSIONS cx=12192000 cy=6858000 coordinate_space=EMU]\n"
            "[IMAGE ALT TEXT: Sales chart]\n"
            "[IMAGE_REGION id=7 x=100000 y=200000 cx=3000000 cy=1800000 coordinate_space=slide_emu]\n"
        )
        mapped, summary = self.module.build_source_map(source, ".pptx", max_chars=7000)
        self.assertEqual(summary["regions"], 1)
        region = mapped[0]["regions"][0]
        self.assertEqual(region["kind"], "embedded_image")
        self.assertEqual(region["object_id"], "7")
        self.assertEqual(region["slide_dimensions"]["cx"], 12192000)
        self.assertIn("image#7 bbox(EMU)=100000,200000,3000000,1800000",
                      self.module.format_source_location(mapped[0]))

    def test_source_map_tracks_docx_floating_picture_anchor_and_relationship(self):
        source = (
            "## Document body\nParagraph text\n"
            "[DOCX_IMAGE_REGION id=9 cx=914400 cy=457200 layout=floating rel=rId5 target=media/image2.png "
            "x=1200 relative_x=page y=2400 relative_y=margin]\n"
        )
        mapped, summary = self.module.build_source_map(source, ".docx", max_chars=7000)
        region = mapped[0]["regions"][0]
        self.assertEqual(region["kind"], "docx_picture")
        self.assertEqual(region["object_id"], "9")
        self.assertEqual(region["layout"], "floating")
        self.assertEqual(region["anchor"]["relative_x"], "page")
        self.assertEqual(region["media_target"], "media/image2.png")

    def test_docx_drawing_marker_handles_inline_and_floating_extent(self):
        xml = """<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
          xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
          xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
          <w:r><w:drawing><wp:anchor><wp:positionH relativeFrom="page"><wp:posOffset>1200</wp:posOffset></wp:positionH>
          <wp:positionV relativeFrom="margin"><wp:align>center</wp:align></wp:positionV>
          <wp:extent cx="914400" cy="457200"/><wp:docPr id="9" name="Picture 2"/>
          <a:blip r:embed="rId5"/></wp:anchor></w:drawing></w:r></w:p>"""
        paragraph = ET.fromstring(xml)
        markers = self.module._docx_drawing_markers(paragraph, {"rId5": "word/media/image2.png"})
        self.assertEqual(len(markers), 1)
        self.assertIn("layout=floating", markers[0])
        self.assertIn("x=1200", markers[0])
        self.assertIn("y=center", markers[0])
        self.assertIn("target=word/media/image2.png", markers[0])

    def test_source_map_tracks_chart_frame_and_office_object_identity(self):
        source = (
            "# Slide 1\n[SLIDE_DIMENSIONS cx=12192000 cy=6858000 coordinate_space=EMU]\n"
            "[CHART_REGION id=14 x=100 y=200 cx=3000 cy=1800 coordinate_space=slide_emu]\n"
            "[OFFICE_OBJECT id=14 name=Chart_1 kind=graphicFrame]\n"
        )
        mapped, summary = self.module.build_source_map(source, ".pptx", max_chars=7000)
        kinds = {region["kind"] for region in mapped[0]["regions"]}
        self.assertIn("chart_frame", kinds)
        self.assertIn("office_object", kinds)
        self.assertIn("chart_frame#14 bbox(EMU)=100,200,3000,1800",
                      self.module.format_source_location(mapped[0]))

    def test_source_map_summary_does_not_claim_visual_geometry(self):
        source = "# Slide 1\n[IMAGE: no alternative text provided]\n"
        mapped, summary = self.module.build_source_map(source, ".pptx")
        self.assertEqual(summary["version"], 2)
        self.assertNotIn("coordinates", summary)
        self.assertIn("image=1", self.module.format_source_location(mapped[0]))

        image_map, image_summary = self.module.build_source_map("recognized OCR text\n", ".png")
        self.assertEqual(image_summary["images"], 1)
        self.assertIn("image=1", self.module.format_source_location(image_map[0]))


if __name__ == "__main__":
    unittest.main()
