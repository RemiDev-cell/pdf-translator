# pdf-translator

`pdf-translator` is a work-in-progress Python pipeline for translating scientific PDFs from French to English while preserving as much structure and visual fidelity as possible.

The long-term goal is not just text translation, but faithful PDF reconstruction:

- preserve layout
- preserve figures, diagrams, and page structure
- protect technical tokens and sensitive fragments
- prepare a future overlay / in-place recomposition workflow

The current version is an `accuracy-first` local prototype. It is intentionally conservative, debuggable, and slower than a production system would be.

## Current Status

What already works:

- structured PDF extraction with PyMuPDF
- intermediate representation (IR) in JSON
- placeholder protection for technical fragments
- local translation through LM Studio
- batch translation with validation and fallbacks
- repeated block / slide chrome audit
- overlay-ready and pre-overlay diagnostic artifacts, including page zones, reading flow, layout groups, and overlay readiness severity
- visual overlay previews on selected pages
- stabilized native-text overlay prototype on representative real pages
- experimental OCR branch for raster-image text, with debug crops, OCR review, mixed native/OCR translation preview, and diagnostic overlay output

What is not finished yet:

- final translated PDF reconstruction
- full-document production overlay
- production OCR recomposition for text embedded in raster images
- advanced formula / equation handling
- robust table reconstruction
- production-grade performance and scaling

## Why This Project Exists

Many scientific PDFs are difficult to translate well because they contain:

- multi-column layouts
- repeated headers and footers
- diagrams and callouts
- images with embedded text
- equations, notation, and symbolic labels
- exported slide decks with heavy visual structure

This project is being built in stages:

1. establish a reliable local prototype
2. validate extraction and translation behavior on real documents
3. prepare overlay-friendly region selection
4. move to a stronger runtime and better models
5. scale up once the architecture is correct

## Repository Layout

```text
pdf-translator/
├── .env.example
├── README.md
├── data/
│   ├── input/
│   ├── output/
│   └── debug/
├── scripts/
├── src/pdf_translator/
│   ├── compose/
│   ├── extract/
│   ├── ocr/
│   ├── qa/
│   ├── routing.py
│   └── translate/
└── tests/
```

## Local Stack

Reference local environment used during development:

- Python `3.9.6`
- local virtual environment in `.venv`
- LM Studio local server
- tested model: `translategemma-4b-it`
- local API base: `http://localhost:4000/v1`
- optional Tesseract OCR binary for the experimental OCR workflow

## Installation

```bash
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For the experimental OCR workflow on macOS:

```bash
brew install tesseract
```

## Configuration

Main settings live in `.env`.

Example:

```env
PDF_TRANSLATOR_MODEL_BACKEND=lmstudio
PDF_TRANSLATOR_API_BASE=http://localhost:4000/v1
PDF_TRANSLATOR_API_KEY=lm-studio
PDF_TRANSLATOR_MODEL_NAME=translategemma-4b-it
PDF_TRANSLATOR_REQUEST_TIMEOUT_SECONDS=45
PDF_TRANSLATOR_CONTEXT_GROUP_MAX_LINES=1
PDF_TRANSLATOR_CONTEXT_GROUP_MAX_CHARS=160
PDF_TRANSLATOR_BATCH_MAX_SEGMENTS=2
PDF_TRANSLATOR_BATCH_MAX_CHARS=800
PDF_TRANSLATOR_OCR_BACKEND=auto
PDF_TRANSLATOR_OCR_TESSERACT_BIN=tesseract
```

## Recommended Stable Settings

For the current local machine, the most stable profile observed so far is:

- `PDF_TRANSLATOR_REQUEST_TIMEOUT_SECONDS=45`
- `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_LINES=1`
- `PDF_TRANSLATOR_CONTEXT_GROUP_MAX_CHARS=160`
- `PDF_TRANSLATOR_BATCH_MAX_SEGMENTS=2`
- `PDF_TRANSLATOR_BATCH_MAX_CHARS=800`

These defaults favor reliability over speed.

## Main Commands

Inspect a PDF and write the intermediate representation:

```bash
./.venv/bin/python -m pdf_translator.cli inspect data/input/myfile.pdf
```

Run a targeted audit on selected pages:

```bash
./.venv/bin/python -m pdf_translator.cli audit-sample data/input/myfile.pdf --pages "1,3,10,22"
```

Generate overlay-ready candidate blocks:

```bash
./.venv/bin/python -m pdf_translator.cli overlay-ready data/input/myfile.pdf --pages "1,3,10,22"
```

Generate pre-overlay regions with bounding boxes:

```bash
./.venv/bin/python -m pdf_translator.cli pre-overlay data/input/myfile.pdf --pages "1,3,10,22"
```

Generate visual overlay diagnostics:

```bash
./.venv/bin/python -m pdf_translator.cli overlay-preview data/input/myfile.pdf --pages "1,3,10,22"
```

Generate a readable translation preview:

```bash
./.venv/bin/python -m pdf_translator.cli translation-preview data/input/myfile.pdf --pages "10,22"
```

Run the experimental OCR workflow on a hybrid or scanned-image PDF:

```bash
./.venv/bin/python -m pdf_translator.cli ocr-experiment data/input/supportpourocr01.pdf --backend tesseract
```

Try a page-level OCR translation preview without attempting image recomposition:

```bash
./.venv/bin/python -m pdf_translator.cli ocr-page-preview data/input/supportpourocr01.pdf --pages 1 --backend tesseract
```

Generate a multi-page document preview for review, with safe native overlays and annotated OCR regions:

```bash
./.venv/bin/python -m pdf_translator.cli document-preview data/input/supportpourocr01.pdf --pages 1-3 --backend tesseract
```

Generate a routed document preview. Native-only pages use the native overlay chain; pages with OCR candidates use the native/OCR fusion chain:

```bash
./.venv/bin/python -m pdf_translator.cli document-preview data/input/myfile.pdf --pages "1-3" --backend tesseract
```

Generate a native-text overlay preview directly when OCR is not needed:

```bash
./.venv/bin/python -m pdf_translator.cli native-preview data/input/myfile.pdf --pages "1-3"
```

## Debug Artifacts

The pipeline writes useful intermediate artifacts under `data/debug/`, including:

- `document_ir.json`
- audit reports
- overlay-ready reports with candidate/exclusion reasons, geometry metrics, page-zone summaries, reading-flow diagnostics, layout groups, and readiness status
- pre-overlay reports
- overlay preview PDFs and PNGs
- translation preview files
- native replacement plans and overlay summaries with per-page apply policies and render decisions derived from overlay readiness
- OCR candidate reports, crops, manifests, and review reports
- mixed native/OCR fusion plans, translation previews, replacement plans, strategy reports, and diagnostic overlay PDFs
- OCR readiness summaries that classify OCR regions before any in-place image recomposition

These artifacts are a core part of the current workflow and make the system much easier to inspect and improve.

## Stabilized V1 Milestone

The current milestone is a stabilized `native text + overlay` prototype.

This means the project can now:

- detect and filter slide chrome, repeated headers / footers, diagram noise, and page numbers
- select overlay candidate regions from real PDFs
- classify overlay readiness as `ready`, `soft_review`, `hard_review`, or `blocked` before recomposition
- translate many short scientific labels through a controlled glossary
- translate narrative text blocks with conservative fallbacks
- translate small structural labels through deterministic native-preview fallbacks
- generate replacement plans with risk levels
- render overlay prototypes directly onto the original PDF pages

Overlay readiness now gates native overlay application:

- `ready` pages use `apply_overlay`
- `soft_review` pages use `apply_overlay_with_soft_review` and still render for visual validation
- `hard_review` pages use `skip_overlay_hard_review`
- `blocked` pages use `skip_overlay_blocked`

Skipped pages still produce the diagnostic chain, but their replacements are counted as considered rather than applied.
Native overlay summaries also explain each considered replacement as `applied`, `skipped_page_policy`, `skipped_status`, `skipped_apply_strategy`, or `skipped_fit_risk`.
Translation preview regions now include `translation_method` and `translation_attempt_count`, so `skipped_status` can be traced back to `model`, `glossary`, `outline_fallback`, `structural_fallback`, `timeout`, or deliberate `skipped` behavior.

Representative pages already validated on the real PowerPoint-exported scientific deck:

- page `3`: dense labels + explanatory paragraphs
- page `10`: title banner + noisy diagram page
- page `22`: structured pedagogical slide
- page `34`: narrative explanatory slide
- page `120`: short pedagogical slide
- page `160`: title + scientific diagram labels

Important boundary of this milestone:

- this is a strong `text-native overlay prototype`
- it is not yet the final production reconstruction engine
- OCR and text-inside-image handling are now explored in a separate experimental workflow, not in the production overlay path

## Experimental OCR Workflow

The OCR branch is intentionally separate from the stabilized native-text overlay path.

It currently supports:

- detecting image blocks as OCR candidates during PyMuPDF extraction
- cropping candidate image regions to PNG debug files
- running OCR through Tesseract or a mock backend
- reviewing OCR quality and suspicious characters
- combining native text and OCR text into a fusion plan
- translating mixed native/OCR segments
- building a mixed replacement plan with explicit strategies
- recommending whether OCR output should remain a side annotation or become a future image-overlay candidate
- classifying OCR readiness as `ready_for_image_overlay`, `side_annotation_review`, `manual_review`, or `blocked`
- rendering a diagnostic PDF that applies native replacements and annotates pending OCR regions
- rendering an explicit guarded OCR in-place prototype for OCR regions classified as ready
- explaining mixed native/OCR translation methods and render decisions in debug summaries

The one-command workflow is:

```bash
./.venv/bin/python -m pdf_translator.cli ocr-experiment data/input/supportpourocr01.pdf --backend tesseract
```

The preferred review entrypoint is now `document-preview`, which first writes a routing report and then dispatches to either the native overlay preview or the native/OCR fusion preview.

An explicit OCR in-place prototype can be rendered from an existing replacement plan:

```bash
./.venv/bin/python -m pdf_translator.cli ocr-inplace-preview data/input/supportpourocr01.pdf --plan-json data/debug/supportpourocr01_document_preview_fusion_replacement_plan.json
```

Or it can generate the OCR fusion plan first:

```bash
./.venv/bin/python -m pdf_translator.cli ocr-inplace-preview data/input/supportpourocr01.pdf --pages 1 --backend tesseract
```

Useful outputs include:

- `data/debug/*_ocr_dry_run_manifest.json`
- `data/debug/*_ocr_dry_run_page_*_ocr_*.png`
- `data/debug/*_fusion_translation_preview.txt`
- `data/debug/*_fusion_replacement_plan.json`
- `data/debug/*_fusion_replacement_plan.txt`
- `data/debug/*_ocr_overlay_strategy.json`
- `data/debug/*_ocr_overlay_strategy.txt`
- `data/debug/*_ocr_page_translation_preview.json`
- `data/debug/*_ocr_page_translation_preview.txt`
- `data/debug/*_fusion_overlay_diagnostics.pdf`
- `data/debug/*_ocr_inplace_prototype.pdf`
- `data/debug/*_ocr_inplace_prototype.txt`
- `data/debug/*_ocr_inplace_prototype_page_*.png`

Current OCR boundary:

- OCR text can be extracted, reviewed, translated, and included in diagnostic artifacts
- native text replacements can still be previewed through the overlay path
- fusion/OCR summaries now expose translation method, attempt count, and per-replacement render decisions
- OCR diagnostic rendering is driven by the final OCR recommendation: image overlay, side annotation, or manual review
- OCR readiness is still not active in `document-preview`; the separate `ocr-inplace-preview` command uses it as the guard for prototype in-place rendering
- OCR regions are not yet rewritten inside the scanned image by the default preview path
- long OCR translations are currently recommended as side annotations when they do not fit safely into the source image region

Validate the guarded OCR prototype on known probes with:

```bash
./.venv/bin/python scripts/run_ocr_inplace_probe_matrix.py --backend mock
./.venv/bin/python scripts/run_ocr_inplace_probe_matrix.py --backend tesseract --include-local-inputs
```

The local-input run includes `data/input/essai_ocr_02.pdf` when present and reports its route, OCR readiness, render decisions, and generated PDF/TXT/PNG paths.

## Test Inputs

Synthetic and real test PDFs currently used:

- `docnavettepourtestsimple.pdf`
- `simple-fr.pdf`
- `scientifique-mixte.pdf`
- `layout-tricky.pdf`
- `supportpourocr01.pdf`

Additional local OCR probes may be present but are intentionally ignored by Git, for example `essai_ocr_02.pdf`.

Synthetic PDFs can be regenerated with:

```bash
./.venv/bin/python scripts/generate_test_pdfs.py
```

## Placeholder Protection

The current pipeline protects:

- emails
- URLs
- long commit hashes
- ISO dates
- software versions like `x.y.z`

This helps reduce accidental corruption during translation.

## Real-World Document Strategy

The project is currently being validated on two kinds of real documents:

- a PowerPoint-exported teaching deck with dense layout and many images
- a smaller hybrid PDF with less predictable extraction quality

This is intentional:

- slide-export PDFs are a strong target for overlay preparation
- hybrid PDFs are useful later for OCR readiness and robustness testing

## Known Limitations

- local model output can still be inconsistent on difficult blocks
- some longer regions still need deterministic fallbacks or glossary help
- OCR is experimental and debug-first, not production recomposition
- diagram text embedded in images is not yet reconstructed in-place
- formula-heavy scientific notation still needs dedicated logic
- current heuristics are useful, but not final

## Roadmap

Short term:

1. keep the local v1 stable
2. continue validating overlay generalization on new representative pages
3. validate the experimental OCR workflow on more hybrid/scanned fixtures

Medium term:

1. move to a stronger runtime and model stack
2. reactivate and validate richer contextual grouping
3. decide the OCR rendering strategy: side annotations, image-region overlay, or deeper image reconstruction

Long term:

1. reconstruct translated PDFs faithfully
2. support diagrams, figures, and embedded text
3. scale the pipeline for larger documents and faster throughput

## Development

Run tests with:

```bash
./.venv/bin/python -m pytest
```

The project currently prioritizes:

- correctness over speed
- inspectability over opacity
- transferability over local overfitting

## License

No license has been added yet.
