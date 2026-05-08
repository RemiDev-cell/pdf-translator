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


def test_extract_document_ignores_small_decorative_images_as_ocr_candidates(tmp_path: Path) -> None:
    pdf_path = tmp_path / "decorative-image.pdf"
    image_path = tmp_path / "sample.png"

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), 0)
    pixmap.clear_with(0xFF6600)
    pixmap.save(image_path)

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 30), "Bonjour")
    page.insert_image(fitz.Rect(20, 50, 28, 58), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    extracted = extract_document(pdf_path)

    assert extracted.pages[0].image_count == 1
    assert extracted.pages[0].ocr_candidates == []
    assert len(extracted.pages[0].ignored_ocr_images) == 1
    ignored = extracted.pages[0].ignored_ocr_images[0]
    assert ignored.reason == "image_too_small_for_ocr"
    assert ignored.classification == "decorative"
    assert round(ignored.width, 1) == 8.0
    assert round(ignored.height, 1) == 8.0


def test_extract_document_classifies_small_illustration_below_ocr_area_threshold(tmp_path: Path) -> None:
    pdf_path = tmp_path / "small-illustration.pdf"
    image_path = tmp_path / "small-illustration.png"

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 35, 25), 0)
    pixmap.clear_with(0x55AA55)
    pixmap.save(image_path)

    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((20, 30), "Bonjour")
    page.insert_image(fitz.Rect(40, 60, 75, 85), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    extracted = extract_document(pdf_path)

    assert extracted.pages[0].ocr_candidates == []
    assert len(extracted.pages[0].ignored_ocr_images) == 1
    ignored = extracted.pages[0].ignored_ocr_images[0]
    assert ignored.reason == "image_area_below_ocr_threshold"
    assert ignored.classification == "illustration_or_figure"
    assert round(ignored.width, 1) == 35.0
    assert round(ignored.height, 1) == 25.0
