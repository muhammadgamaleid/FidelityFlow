# File processing and source fidelity

## Source-first design

FidelityFlow never edits the original file. It creates a searchable derivative and records source identity, extractor version, warnings, hashes, and chunk offsets. The cache key combines the source SHA-256, extractor version, chunk settings, and processing options such as OCR language and DPI. An unchanged file can be re-used without repeating extraction only when those settings are also unchanged.

An extracted index is not a replacement for the source. Retrieve the original passage or use Claude's native file handling whenever visual layout, exact calculations, or missing structure affects the task.

## Current local extraction support

| Format | Extracted today | Limitations |
|---|---|---|
| TXT, Markdown, RST, logs, source code | UTF-8 text | Invalid bytes are replaced with a warning; source remains authoritative |
| CSV / TSV / JSON / JSONL / YAML / XML / HTML | Raw text | No general semantic schema inference or validation |
| DOCX | Body paragraphs, headings, tables, headers, footers, footnotes, endnotes, comments, and tracked insertions/deletions | Does not reconstruct pagination, floating-object geometry, embedded media, or exact visual layout |
| XLSX | Sheet visibility, cell addresses, text/numeric values, formulas and cached values, hidden rows/columns, merged ranges, defined names, cached chart data | Does not reproduce formatting, pivot tables, macros, external connections, validations, or formula recalculation |
| PPTX | Slide text, basic tables, shape/image alt text, speaker notes, shape positions, and cached chart data | Does not reconstruct image content, diagrams, animation, or complete spatial layout |
| PDF | Per-page text with [PAGE n] markers | Requires optional pypdf; scans, figures, complex tables, columns, and visual layout are not represented by text extraction |
| PNG / JPEG / TIFF / BMP / WebP | Multi-pass OCR with word confidence and approximate line bounding boxes; optional geometric evidence when OpenCV is installed | Requires OCR extra, Tesseract executable, and language data; OpenCV geometry is not semantic chart/diagram understanding |

Office ZIP/XML input is subject to archive-member, aggregate-size, entry-count, and compression-ratio safety limits. Legacy .doc, .xls, and .ppt formats are not supported.

## Source mapping and traceability

Each indexed chunk now carries structured source-location metadata alongside its character offsets, line range, and content hash. The mapping is derived from the format-specific markers already emitted by the extractors; it does not alter extracted text or the original file.

Supported navigation hints:

| Source format | Location metadata |
|---|---|
| PDF | Page number, including pages that received OCR |
| PPTX | Slide number, Office object IDs, picture/chart-frame bounds, table markers, and chart relationship targets |
| XLSX | Worksheet name and cell references present in the chunk; chart identifier when cached chart data is present |
| DOCX | Table sequence markers, inline/floating picture IDs, media relationships, extents, and anchor-relative offsets |
| Standalone OCR images | Image-level source identity |
| Other text formats | Document identity and line range |

The manifest includes a versioned `source_map` summary (located chunk count, discovered page/slide/sheet/table/image/chart identifiers, and mapped region count). Search results and `show` display the mapped source location and up to three region previews so a retrieved passage can be traced back to its originating part of the file.

### Image-region coordinates

- OCR text lines carry approximate pixel bounding boxes (`x`, `y`, `width`, `height`) and mean word confidence. The source map attaches those boxes to the relevant chunk and records the processed image width and height.
- For scanned PDF pages, OCR boxes are relative to the rendered page image at the selected OCR DPI, not PDF points or the original embedded image.
- DOCX inline and floating pictures carry the native `wp:docPr` object ID, media relationship target, extent in EMUs, and (for floating anchors) raw horizontal/vertical offsets or alignment plus their `relativeFrom` reference frame. These offsets are not absolute page coordinates because Word layout depends on page, margin, column, paragraph, and character layout.
- PPTX picture and chart-frame objects carry native Office object IDs and bounding rectangles in slide EMUs when a complete transform exists. Charts with explicit manual plot-area geometry also expose a normalized chart-relative plot rectangle. Chart frames also retain the chart relationship target; slide canvas dimensions are recorded where available.
- PPTX shape and graphic-frame IDs are exposed as Office object regions to make source references stable within the source part. Native connector objects expose start/end shape IDs and connection-site indices; these are structural references, not proof of semantic or causal meaning.
- Embedded Office charts expose detected chart families (bar, line, pie, doughnut, scatter, area, radar, stock, bubble, and surface), cached title, legend placement, axis titles/IDs and explicit numeric bounds, plus indexed cached category/value points. Missing cache indices remain missing; values are not recalculated.
- Connector endpoints and Office object IDs are retained in source-map regions so diagram relationships can be traced across chunks when the source provides explicit references.
- Coordinates are not silently converted between pixels, PDF points, and EMUs. Each region explicitly identifies its coordinate space.
- Picture bounds identify the image object's placement on a slide; they do not identify semantic subregions inside that picture. Absolute DOCX page placement and semantic interpretation of raster images remain unsupported. Connector endpoint IDs expose topology, but arrow direction, business meaning, and causal relationships are not inferred from line appearance. When a chart stores an explicit manual plot-area layout, FidelityFlow records its normalized chart-relative rectangle; automatic layouts or incomplete geometry are not guessed. Chart-frame bounds identify the containing Office object, not the plot rectangle.

Important boundaries:
- A chunk can span more than one page, slide, or other marked region; all explicit regions represented in that chunk are retained.
- XLSX cell references are recorded only when the extractor emitted them in the chunk.
- OCR boxes are approximate and reflect the processed image. PPTX image bounds are native slide-object bounds; neither mechanism provides semantic understanding of image content.
- DOCX table numbering and PPTX image numbering are extraction-order identifiers; picture and shape object IDs are native identifiers within their OOXML part and are not guaranteed globally unique across files.
- These are navigation hints, not reconstructed page geometry, exact visual coordinates, or a guarantee that every source element was extractable. Always verify consequential content against the original.

## Optional OCR

OCR is local, opt-in, and never runs unless the user supplies `--ocr`. Install the Python dependencies:

~~~bash
python -m pip install -e ".[ocr,vision]"
~~~

Install the Tesseract OCR executable separately and install the language data you need. For Arabic and English together, pass `ara+eng`; both language packs must be present. The `vision` extra is optional and can be omitted when only OCR is needed.

Check readiness:

~~~bash
fidelityflow doctor
~~~

OCR a standalone image:

~~~bash
fidelityflow ingest "scanned-page.png" --ocr --ocr-lang ara+eng
~~~

OCR only sparse-text pages in a PDF:

~~~bash
fidelityflow ingest "scanned-report.pdf" --ocr --ocr-lang ara+eng --ocr-dpi 180 --ocr-max-pages 100
~~~

OCR images in a directory (image extensions are included only when `--ocr` is enabled):

~~~bash
fidelityflow ingest-dir "./scans" --ocr --ocr-lang ara+eng
~~~

Controls:
- `--ocr-dpi`: PDF page rasterization resolution, 100–300 DPI.
- `--ocr-max-pages`: maximum sparse-text pages processed per PDF, 1–500.
- OCR is attempted only on PDF pages with fewer than 40 extracted text characters. It does not OCR every page by default.
- Image inputs are bounded by file-size and pixel-count safety limits.
- OCR runs bounded preprocessing variants (contrast normalization, upscaling/sharpening, and thresholding), tries multiple page segmentation modes, and selects the strongest result using recognized-word confidence and text coverage. Orientation detection is applied only when Tesseract reports sufficient confidence.
- Recognized lines retain approximate pixel bounding boxes and mean word confidence; coordinates refer to the processed image and are not a substitute for the original.
- The optional `vision` extra installs OpenCV for conservative geometric evidence such as long horizontal/vertical/diagonal lines and substantial contours. It does not infer chart values, axis labels, arrow direction, flow semantics, or causal relationships.
- OCR output remains approximate. Verify numbers, names, tables, and legal/financial text against the original.

The Skill package includes the OCR Python module, but Claude.ai's managed workspace does not guarantee that the Tesseract executable, OCR language packs, or native dependencies are available. Do not promise OCR in Claude.ai. The supported and documented OCR route is the local CLI.

## Commands

~~~bash
fidelityflow doctor
fidelityflow ingest "report.pdf"
fidelityflow ingest "scanned-report.pdf" --ocr --ocr-lang eng
fidelityflow ingest "scan.png" --ocr --ocr-lang eng
fidelityflow ingest-dir "./research-library"
fidelityflow ingest-dir "./scans" --ocr --ocr-lang ara+eng
fidelityflow list
fidelityflow search --query "revenue recognition" --top-k 5
fidelityflow show --document DOCUMENT_ID --chunk 0
~~~

The bundled Claude Skill script can be run with the exact path exposed by the Skill execution environment:

~~~bash
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" doctor
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" ingest "/exact/path/to/report.pdf" --cache-dir "$PWD/.fidelityflow/cache"
python "/resolved/path/to/fidelityflow/scripts/fidelityflow.py" search --query "specific question" --top-k 5 --max-chars 1400 --cache-dir "$PWD/.fidelityflow/cache"
~~~

Never guess the Skill installation path. The local Python package is needed for the native Claude Code CLI; the bundled Skill script is packaged separately for Claude.ai.

## Search and retrieval

- Search is lexical (BM25-style) and ranks extracted chunks by term overlap/frequency. Code identifiers are indexed both as written and as common underscore/CamelCase components (for example, `getUserProfile` also matches `get`, `user`, and `profile`). It is not semantic vector search.
- Text, Markdown, and source-code chunks remain lossless. For supported source types, chunking prefers section headings and common function/class/type declarations when a safe boundary is available, then falls back to a line boundary.
- Search excerpts preserve line breaks and indentation and are centered near a query match within the selected chunk. Use `show` to retrieve the complete chunk when a code edit or exact context requires it.
- Search returns bounded excerpts and source metadata. Use show to retrieve a complete chunk only when needed.
- Use alternate terms or native Claude search when lexical retrieval misses a relevant passage.
- Preserve source names, PDF page markers, line ranges, and any available cell/slide identifiers when quoting results.
- Do not ingest every repository or directory automatically. Select only sources relevant to the task.

## Cache and privacy

- Extracted content is stored once in the local cache; chunk metadata stores offsets rather than duplicating full text.
- Cache entries are local and unencrypted. They can contain sensitive source material.
- The cache is content-addressed; changed source content gets a new cache identity. OCR options are part of that identity.
- Claude.ai Skill workspace caches may disappear after a reset or unrelated chat. Do not promise persistence.
- Do not delete or replace the original source after indexing.

## Claude.ai upload boundary

Claude.ai controls its own initial attachment ingestion and document parser. A custom Skill cannot intercept that pipeline, rewrite the attachment before Claude receives it, or guarantee that the initial upload avoids context/usage accounting.

When a file is already available in the Skill execution workspace, local extraction and bounded retrieval can avoid repeatedly printing its full content into the conversation. For recurring libraries, use Claude Projects and Project Knowledge when appropriate; do not duplicate a complete library in both systems without a measured benefit.

For visual PDFs, scanned pages, charts, spreadsheet calculations, and layout-sensitive tasks, prefer Claude's native document capabilities or a dedicated visual workflow. OCR recovers text; it does not reconstruct visual structure or replace image understanding.
