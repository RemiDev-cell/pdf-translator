from __future__ import annotations

from pathlib import Path

import fitz

from pdf_translator.extract.classify_pdf import classify_pdf
from pdf_translator.models import (
    BoundingBox,
    DocumentModel,
    IgnoredOcrImage,
    OcrCandidate,
    PageModel,
    TextBlock,
    TextLine,
    TextSpan,
)


MIN_OCR_CANDIDATE_AREA_RATIO = 0.01
MIN_OCR_CANDIDATE_WIDTH = 32.0
MIN_OCR_CANDIDATE_HEIGHT = 24.0
MAX_OCR_CANDIDATE_ASPECT_RATIO = 8.0


def _bbox_from_sequence(values) -> BoundingBox:
    return BoundingBox(
        x0=float(values[0]),
        y0=float(values[1]),
        x1=float(values[2]),
        y1=float(values[3]),
    )


def _ocr_ignored_reason(width: float, height: float, area_ratio: float) -> str | None:
    if width < MIN_OCR_CANDIDATE_WIDTH or height < MIN_OCR_CANDIDATE_HEIGHT:
        return "image_too_small_for_ocr"
    if area_ratio < MIN_OCR_CANDIDATE_AREA_RATIO:
        return "image_area_below_ocr_threshold"

    aspect_ratio = max(width / max(height, 1.0), height / max(width, 1.0))
    if aspect_ratio > MAX_OCR_CANDIDATE_ASPECT_RATIO:
        return "image_aspect_ratio_too_extreme"

    return None


def extract_document(pdf_path: str | Path) -> DocumentModel:
    pdf_path = Path(pdf_path)
    doc = fitz.open(pdf_path)

    pages: list[PageModel] = []

    for page_number, page in enumerate(doc, start=1):
        page_dict = page.get_text("dict")
        raw_text = page.get_text("text").strip()
        image_count = len(page.get_images(full=True))

        page_model = PageModel(
            page_number=page_number,
            width=float(page.rect.width),
            height=float(page.rect.height),
            image_count=image_count,
            raw_text=raw_text,
        )

        block_index = 0
        ocr_candidate_index = 0
        image_block_index = 0
        page_area = max(1.0, float(page.rect.width) * float(page.rect.height))
        for block in page_dict.get("blocks", []):
            block_type = block.get("type", -1)

            if block_type == 1:
                bbox = _bbox_from_sequence(block["bbox"])
                width = max(0.0, bbox.x1 - bbox.x0)
                height = max(0.0, bbox.y1 - bbox.y0)
                area_ratio = (width * height) / page_area
                ignored_reason = _ocr_ignored_reason(width, height, area_ratio)
                if ignored_reason is not None:
                    page_model.ignored_ocr_images.append(
                        IgnoredOcrImage(
                            page_number=page_number,
                            image_index=image_block_index,
                            bbox=bbox,
                            width=width,
                            height=height,
                            area_ratio=area_ratio,
                            reason=ignored_reason,
                        )
                    )
                    image_block_index += 1
                    continue

                page_model.ocr_candidates.append(
                    OcrCandidate(
                        page_number=page_number,
                        candidate_index=ocr_candidate_index,
                        bbox=bbox,
                        width=width,
                        height=height,
                        area_ratio=area_ratio,
                        reason="image_block",
                    )
                )
                ocr_candidate_index += 1
                image_block_index += 1
                continue

            if block_type != 0:
                continue

            lines: list[TextLine] = []
            line_texts: list[str] = []

            for line in block.get("lines", []):
                spans: list[TextSpan] = []
                span_texts: list[str] = []

                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    if not span_text.strip():
                        continue

                    spans.append(
                        TextSpan(
                            text=span_text,
                            font=span.get("font"),
                            size=float(span["size"]) if span.get("size") is not None else None,
                            flags=span.get("flags"),
                            color=span.get("color"),
                            bbox=_bbox_from_sequence(span["bbox"]),
                        )
                    )
                    span_texts.append(span_text)

                if not spans:
                    continue

                joined_line_text = "".join(span_texts).strip()
                if not joined_line_text:
                    continue

                lines.append(
                    TextLine(
                        bbox=_bbox_from_sequence(line["bbox"]),
                        spans=spans,
                        text=joined_line_text,
                    )
                )
                line_texts.append(joined_line_text)

            if not lines:
                continue

            joined_block_text = "\n".join(line_texts).strip()
            if not joined_block_text:
                continue

            page_model.text_blocks.append(
                TextBlock(
                    page_number=page_number,
                    block_index=block_index,
                    block_type="text",
                    bbox=_bbox_from_sequence(block["bbox"]),
                    text=joined_block_text,
                    translate=True,
                    lines=lines,
                )
            )
            block_index += 1

        page_model.block_count = len(page_model.text_blocks)
        pages.append(page_model)

    return DocumentModel(
        source_path=str(pdf_path),
        pdf_kind=classify_pdf(doc),
        page_count=len(doc),
        pages=pages,
    )
