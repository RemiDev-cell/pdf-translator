from pathlib import Path

import fitz

from pdf_translator.extract.pymupdf_extract import extract_document


def test_extract_document_collects_ocr_candidates_from_image_blocks(tmp_path: Path) -> None:
    pdf_path = tmp_path / "image-block.pdf"
    image_path = tmp_path / "sample.png"

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), 0)
    pixmap.clear_with(0xFF0000)
    pixmap.save(image_path)

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 30), "Bonjour")
    page.insert_image(fitz.Rect(50, 60, 150, 160), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    extracted = extract_document(pdf_path)

    assert extracted.page_count == 1
    assert extracted.pages[0].image_count == 1
    assert len(extracted.pages[0].ocr_candidates) == 1
    candidate = extracted.pages[0].ocr_candidates[0]
    assert candidate.page_number == 1
    assert candidate.candidate_index == 0
    assert round(candidate.width, 1) == 100.0
    assert round(candidate.height, 1) == 100.0
    assert candidate.area_ratio > 0.0
