from pdf_translator.routing import (
    build_document_routing_report,
    build_ocr_candidate_report,
    ocr_candidate_report_to_text,
    routing_report_to_text,
)


def test_build_document_routing_report_distinguishes_native_and_ocr_paths() -> None:
    document_ir = {
        "pdf_kind": "hybrid",
        "pages": [
            {
                "page_number": 1,
                "raw_text": "Visible native paragraph",
                "image_count": 0,
                "block_count": 1,
                "text_blocks": [
                    {"role": "content", "text": "Visible native paragraph"}
                ],
            },
            {
                "page_number": 2,
                "raw_text": "Caption",
                "image_count": 2,
                "ocr_candidates": [{"candidate_index": 0}],
                "block_count": 2,
                "text_blocks": [
                    {"role": "content", "text": "Caption"},
                    {"role": "diagram_label", "text": "A"},
                ],
            },
            {
                "page_number": 3,
                "raw_text": "",
                "image_count": 1,
                "ocr_candidates": [{"candidate_index": 0}],
                "block_count": 0,
                "text_blocks": [],
            },
            {
                "page_number": 4,
                "raw_text": "12",
                "image_count": 0,
                "block_count": 1,
                "text_blocks": [
                    {"role": "page_number", "text": "12"}
                ],
            },
        ],
    }

    report = build_document_routing_report(document_ir)

    assert report["route_summary"] == {
        "native_only": 1,
        "native_plus_ocr_candidates": 1,
        "ocr_only": 1,
        "native_non_content_only": 1,
    }
    assert report["pages"][0]["route"] == "native_only"
    assert report["pages"][1]["route"] == "native_plus_ocr_candidates"
    assert report["pages"][2]["route"] == "ocr_only"
    assert report["pages"][3]["route"] == "native_non_content_only"


def test_build_document_routing_report_filters_selected_pages() -> None:
    document_ir = {
        "pdf_kind": "born_digital",
        "pages": [
            {
                "page_number": 1,
                "raw_text": "Bonjour",
                "image_count": 0,
                "block_count": 1,
                "text_blocks": [{"role": "content", "text": "Bonjour"}],
            },
            {
                "page_number": 2,
                "raw_text": "",
                "image_count": 1,
                "block_count": 0,
                "text_blocks": [],
            },
        ],
    }

    report = build_document_routing_report(document_ir, selected_pages=[2])

    assert report["page_count"] == 1
    assert report["route_summary"] == {"image_only_no_ocr_candidates": 1}
    assert report["pages"][0]["page_number"] == 2


def test_build_document_routing_report_ignores_decorative_images_for_ocr_route() -> None:
    document_ir = {
        "pdf_kind": "hybrid",
        "pages": [
            {
                "page_number": 1,
                "raw_text": "Invoice text",
                "image_count": 3,
                "ocr_candidates": [],
                "block_count": 1,
                "text_blocks": [{"role": "content", "text": "Invoice text"}],
            }
        ],
    }

    report = build_document_routing_report(document_ir)

    assert report["route_summary"] == {"native_only": 1}
    assert report["pages"][0]["route"] == "native_only"
    assert "no_ocr_sized_image_regions" in report["pages"][0]["reasons"]


def test_routing_report_to_text_includes_summary_and_reasons() -> None:
    report = {
        "selected_pages": [2],
        "page_count": 1,
        "pdf_kind": "hybrid",
        "route_summary": {"ocr_only": 1},
        "pages": [
            {
                "page_number": 2,
                "route": "ocr_only",
                "reasons": ["contains_raster_images"],
                "raw_chars": 0,
                "image_count": 1,
                "block_count": 0,
                "content_block_count": 0,
            }
        ],
    }

    text = routing_report_to_text(report)

    assert "PDF kind: hybrid" in text
    assert 'Route summary: {"ocr_only": 1}' in text
    assert "Page 2: route=ocr_only" in text
    assert "contains_raster_images" in text



def test_build_ocr_candidate_report_summarizes_candidates() -> None:
    document_ir = {
        "pdf_kind": "hybrid",
        "pages": [
            {
                "page_number": 2,
                "image_count": 1,
                "text_blocks": [{"role": "content", "text": "caption"}],
                "ocr_candidates": [
                    {
                        "candidate_index": 0,
                        "bbox": {"x0": 10, "y0": 20, "x1": 110, "y1": 120},
                        "area_ratio": 0.25,
                        "reason": "image_block",
                    }
                ],
            }
        ],
    }

    report = build_ocr_candidate_report(document_ir)
    text = ocr_candidate_report_to_text(report)

    assert report["total_candidates"] == 1
    assert report["pages"][0]["candidate_count"] == 1
    assert report["pages"][0]["route"] == "native_plus_ocr_candidates"
    assert "Total OCR candidates: 1" in text
    assert "OCR0:" in text
