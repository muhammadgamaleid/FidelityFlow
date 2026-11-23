# Changelog

All notable FidelityFlow changes are documented here.

## [0.6.0] — 2026-11-23

### Added
- Structured source mapping for PDF pages, PPTX slides and native objects, XLSX worksheets/cells, DOCX tables and picture anchors, and OCR image regions.
- Native Office chart metadata, cached series values, chart plot-area geometry when explicitly available, and PowerPoint connector references.
- Optional OpenCV raster visual candidates for geometric shapes, plot-like regions, nearby OCR labels, possible arrowheads, and tentative shape-to-shape links.
- OCR coordinate normalization to processed-image pixels and v3 extractor cache identities.
- Expanded OCR and visual regression coverage across the supported Python matrix.

### Improved
- README and platform setup guidance for Claude.ai and Claude Code.
- Skill documentation to distinguish deterministic extraction, OCR, geometric heuristics, and semantic visual interpretation.
- Release metadata aligned to version 0.6.0.

### Boundaries
- Raster chart values/series are not reliably reconstructed.
- Shape and flowchart connections are heuristic candidates, not semantic conclusions.
- Embedded raster media inside DOCX/PPTX is not automatically OCR-analyzed.
- No token-saving percentage is claimed without controlled measurement.

## [0.5.0]

Previous development release. See Git history for detailed changes.
