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
- overlay-ready and pre-overlay diagnostic artifacts
- visual overlay previews on selected pages

What is not finished yet:

- final translated PDF reconstruction
- true overlay / replacement rendering
- OCR for text embedded in raster images
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
│   ├── qa/
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

## Installation

```bash
/usr/bin/python3 -m venv .venv
source .venv/bin/activate
pip install -e .
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

## Debug Artifacts

The pipeline writes useful intermediate artifacts under `data/debug/`, including:

- `document_ir.json`
- audit reports
- overlay-ready reports
- pre-overlay reports
- overlay preview PDFs and PNGs
- translation preview files

These artifacts are a core part of the current workflow and make the system much easier to inspect and improve.

## Test Inputs

Synthetic and real test PDFs currently used:

- `docnavettepourtestsimple.pdf`
- `simple-fr.pdf`
- `scientifique-mixte.pdf`
- `layout-tricky.pdf`

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
- some long regions may still time out locally
- OCR is not implemented yet
- diagram text embedded in images is not handled yet
- formula-heavy scientific notation still needs dedicated logic
- current heuristics are useful, but not final

## Roadmap

Short term:

1. keep the local v1 stable
2. continue improving overlay region selection
3. start the first real overlay / replacement planning pass

Medium term:

1. move to a stronger runtime and model stack
2. reactivate and validate richer contextual grouping
3. add OCR for image-based text

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
