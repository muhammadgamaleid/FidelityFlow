# File processing and source fidelity

## Source-first design

FidelityFlow never edits the original file. It creates a searchable derivative and records source identity, extractor version, warnings, hashes, and chunk offsets. The cache key combines the source SHA-256, extractor version, chunk settings, and processing options such as OCR language and DPI. An unchanged file can be re-used without repeating extraction only when those settings are also unchanged.

An extracted index is not a replacement for the source. Retrieve the original passage or use Claude's native file handling whenever visual layout, exact calculations, or missing structure affects the task.

## Current local extraction support

| Format | Extracted today | Limitations |
|---|---|---|
| TXT, Markdown, RST, logs, source code | UTF-8 text | Invalid bytes are replaced with a warning; source remains authoritative |
| CSV / TSV / JSON / JSONL / YAML / XML / HTML | Raw text | No general semantic schema inference or validation |
| DOCX | Body paragraphs, headings, tables, headers, footers, footnotes, endnotes, comments, tracked insertions/deletions | Does not reconstruct exact pagination or all visual layout; embedded raster media is not automatically OCR-analyzed |
| XLSX | Sheet visibility, cell addresses, text/numeric values, formulas and cached values, hidden rows/columns, merged ranges, defined names, cached chart data | Does not reproduce formatting, pivot tables, macros, external connections, validations, or formula recalculation |
| PPTX | Slide text, basic tables, shape/image alt text, native object geometry, connector references, chart metadata and cached values | Does not reconstruct all image content, diagrams, animation, notes, or complete spatial layout |
| PDF | Per-page text with [PAGE n] markers | Requires optional pypdf; scans, figures, complex tables, columns, and visual layout are not represented by text extraction |
| PNG / JPEG / TIFF / BMP / WebP | Multi-pass OCR with word confidence and pixel boxes; optional OpenCV candidate shapes, plot-area bounds, proximity labels, possible arrows, and tentative shape connections | Requires OCR extra, Tesseract executable, and language data; geometric classes and links are heuristic candidates, not verified semantic interpretations |

Office ZIP/XML input is subject to archive-member, aggregate-size, entry-count, and compression-ratio safety limits. Legacy .doc, .xls, and .ppt formats are not supported.

## Source mapping and traceability

Each indexed chunk carries structured source-location metadata alongside its character offsets, line range, and content hash. The mapping is derived from format-specific extraction markers; it does not alter extracted text or the original file.

| Source format | Location metadata |
|---|---|
| PDF | Page number, including pages that received OCR |
| PPTX | Slide number, native object IDs, picture/chart-frame bounds, table markers, chart relationship targets, and connector endpoints |
| XLSX | Worksheet name and cell references present in the chunk; chart identifier when cached chart data is present |
| DOCX | Table sequence markers, inline/floating picture IDs, media relationships, extents, and anchor-relative offsets |
| Standalone OCR images | Image identity, processed-image dimensions, OCR line boxes, and visual candidate regions |
| Other text formats | Document identity and line range |

The manifest includes a versioned `source_map` summary. Search results and `show` expose mapped source locations and region previews so retrieved passages can be traced to their source.

### Image-region coordinates

- OCR text lines carry approximate pixel bounding boxes (`x`, `y`, `width`, `height`) and mean word confidence. Coordinates are normalized back to the processed image dimensions after OCR preprocessing.
- For scanned PDF pages, OCR boxes are relative to the rendered page image at the selected OCR DPI, not PDF points or the original embedded image.
- DOCX inline and floating pictures carry native `wp:docPr` object IDs, media relationship targets, extents in EMUs, and (for floating anchors) raw offsets or alignment plus their `relativeFrom` reference frame. These are not absolute page coordinates.
- PPTX picture and chart-frame objects carry native Office object IDs and bounding rectangles in slide EMUs when a complete transform exists. Explicit manual plot-area rectangles are normalized to chart-relative fractions.
- PPTX shape and graphic-frame IDs are stable within their OOXML part. Native connector objects expose start/end shape IDs and connection-site indices; these are structural references, not proof of semantic or causal meaning.
- Embedded Office charts expose chart families, titles, legends, axis metadata and indexed cached series values where present. Missing cache indices remain missing; values are not recalculated.
- Raster visual analysis uses processed-image pixel coordinates. It can report candidate rectangles, ellipses, diamonds, triangles, plot-like axes and estimated plot bounds, nearby OCR words, possible arrowheads, and tentative shape-to-shape links when line endpoints are near two distinct detected shapes.
- Coordinate spaces are explicit and are never silently converted between pixels, PDF points, slide EMUs, chart-relative fractions, and Word anchor-relative offsets.

**Interpretation boundary:** OCR proximity does not prove that a word labels a shape. A candidate line does not prove a connector; a candidate arrowhead does not establish direction; and a geometric link does not establish semantic or causal meaning. Raster chart values and series are not reliably reconstructed from pixels. Use native Office chart caches and connector references when available, and verify consequential conclusions against the original source.

Other limitations:
- A chunk can span more than one page, slide, or marked region; all explicit regions represented in that chunk are retained.
- DOCX table numbering and PPTX image numbering are extraction-order identifiers; native shape and picture IDs are scoped to their OOXML part.
- Office embedded raster media is not automatically passed through OCR by this phase.
- These are navigation hints, not reconstructed page geometry or a guarantee that every source element was extracted.

## Optional OCR and visual analysis

Install the Python dependencies:

~~~bash
python -m pip install -e ".[ocr,vision]"
~~~

Install the Tesseract executable and language data separately. For Arabic and English, use `ara+eng` and ensure both language packs are installed.

~~~bash
fidelityflow doctor
fidelityflow ingest "scanned-page.png" --ocr --ocr-lang ara+eng
fidelityflow ingest "scanned-report.pdf" --ocr --ocr-lang ara+eng --ocr-dpi 180 --ocr-max-pages 100
fidelityflow ingest-dir "./scans" --ocr --ocr-lang ara+eng
~~~

Controls:
- `--ocr-dpi`: PDF page rasterization resolution, 100–300 DPI.
- `--ocr-max-pages`: maximum sparse-text pages processed per PDF, 1–500.
- OCR is attempted only on PDF pages with fewer than 40 extracted text characters by default.
- Image inputs are bounded by file-size and pixel-count safety limits.
- OCR uses bounded preprocessing variants, multiple page segmentation modes, confidence scoring, and confidence-gated orientation correction.
- OpenCV analysis is optional and emits geometric candidates only; it does not infer chart values or semantic diagram meaning.
- Verify numbers, names, tables, and legal/financial text against the original.

Tesseract and native dependencies are not guaranteed in Claude.ai's managed Skill workspace. The dependable OCR route is the local CLI.

## Commands

~~~bash
fidelityflow doctor
fidelityflow ingest "report.pdf"
fidelityflow ingest "scanned-report.pdf" --ocr --ocr-lang eng
fidelityflow ingest "scan.png" --ocr --ocr-lang eng
fidelityflow ingest-dir "./research-library"
fidelityflow list
fidelityflow search --query "revenue recognition" --top-k 5
fidelityflow show --document DOCUMENT_ID --chunk 0
~~~

The bundled Claude Skill script can be run using the exact path exposed by the Skill execution environment. Never guess its absolute path.

## Search and retrieval

- Search is lexical (BM25-style), not semantic vector search.
- Code identifiers are indexed both as written and as common underscore/CamelCase components.
- Text, Markdown, and source-code chunks remain lossless. Chunking prefers headings and common function/class/type declarations when safe.
- Search excerpts preserve line breaks and indentation and are centered near a query match. Use `show` when the complete chunk is required.
- Use alternate terms or native Claude search when lexical retrieval misses a passage.
- Preserve source names, page markers, line ranges, and available cell/slide identifiers when quoting results.
- Do not ingest every repository or directory automatically; select only sources relevant to the task.

## Cache and privacy

- Extracted content is stored once in the local cache; chunk metadata stores offsets rather than duplicating full text.
- Cache entries are local and unencrypted and may contain sensitive source material.
- Cache identity includes source content and relevant extractor/processing options.
- Claude.ai Skill workspace caches may disappear after a reset or unrelated chat.
- Never delete or replace the original source after indexing.

## Claude.ai upload boundary

Claude.ai controls its initial attachment ingestion and document parser. A custom Skill cannot intercept that pipeline, rewrite the attachment before Claude receives it, or guarantee that the initial upload avoids context/usage accounting.

When a file is available in the Skill execution workspace, local extraction and bounded retrieval can avoid repeatedly printing its full content into the conversation. For recurring libraries, use Claude Projects and Project Knowledge when appropriate.

For visual PDFs, scanned pages, charts, spreadsheet calculations, and layout-sensitive tasks, prefer Claude's native document capabilities or a dedicated visual workflow. OCR recovers text; it does not replace image understanding.
