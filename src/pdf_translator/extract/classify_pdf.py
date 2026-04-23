from __future__ import annotations

import fitz

from pdf_translator.models import PdfKind


def classify_pdf(doc: fitz.Document) -> PdfKind:
    pages_with_text = 0
    pages_with_images = 0

    for page in doc:
        text = page.get_text("text").strip()
        images = page.get_images(full=True)

        if text:
            pages_with_text += 1
        if images:
            pages_with_images += 1

    if pages_with_text and not pages_with_images:
        return "born_digital"
    if pages_with_images and not pages_with_text:
        return "scanned"
    return "hybrid"
