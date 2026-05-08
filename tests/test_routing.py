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
                "ignored_ocr_images": [
                    {"reason": "image_area_below_ocr_threshold"}
                ],
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
    assert report["pages"][1]["native_text_chars"] == len("Caption")
    assert report["pages"][1]["image_count"] == 2
    assert report["pages"][1]["image_block_count"] == 2
    assert report["pages"][1]["ocr_candidate_count"] == 1
    assert report["pages"][1]["content_blocks"] == 1
    assert report["pages"][1]["excluded_blocks"] == 1
    assert report["pages"][1]["excluded_role_summary"] == {"diagram_label": 1}


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
                "ignored_ocr_images": [
                    {"reason": "image_too_small_for_ocr", "classification": "decorative"},
                    {"reason": "image_too_small_for_ocr", "classification": "too_small_for_ocr"},
                    {"reason": "image_area_below_ocr_threshold", "classification": "illustration_or_figure"},
                ],
                "block_count": 1,
                "text_blocks": [{"role": "content", "text": "Invoice text"}],
            }
        ],
    }

    report = build_document_routing_report(document_ir)

    assert report["route_summary"] == {"native_with_decorative_images": 1}
    assert report["pages"][0]["route"] == "native_with_decorative_images"
    assert report["pages"][0]["image_block_count"] == 3
    assert report["pages"][0]["ignored_ocr_image_count"] == 3
    assert report["pages"][0]["ignored_ocr_image_reason_summary"] == {
        "image_area_below_ocr_threshold": 1,
        "image_too_small_for_ocr": 2,
    }
    assert report["pages"][0]["ignored_ocr_image_classification_summary"] == {
        "decorative": 1,
        "illustration_or_figure": 1,
        "too_small_for_ocr": 1,
    }
    assert "no_ocr_sized_image_regions" in report["pages"][0]["reasons"]


def test_build_document_routing_report_counts_translatable_native_roles_as_content() -> None:
    document_ir = {
        "pdf_kind": "born_digital",
        "pages": [
            {
                "page_number": 1,
                "raw_text": "Title\nCaption\nTable",
                "image_count": 0,
                "ocr_candidates": [],
                "block_count": 4,
                "text_blocks": [
                    {"role": "slide_title", "text": "SCIENTIFIC TITLE"},
                    {"role": "caption", "text": "Figure 1 : Useful caption"},
                    {"role": "table_header", "text": "Parametre\nValeur"},
                    {"role": "table_cell", "text": "Tension\n0,72"},
                ],
            }
        ],
    }

    report = build_document_routing_report(document_ir)

    assert report["route_summary"] == {"native_only": 1}
    assert report["pages"][0]["content_blocks"] == 4
    assert report["pages"][0]["excluded_blocks"] == 0
    assert report["pages"][0]["excluded_role_summary"] == {}


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
                "excluded_blocks": 0,
                "excluded_role_summary": {},
                "ocr_candidate_count": 1,
                "ignored_ocr_image_count": 0,
                "ignored_ocr_image_reason_summary": {},
            }
        ],
    }

    text = routing_report_to_text(report)

    assert "PDF kind: hybrid" in text
    assert 'Route summary: {"ocr_only": 1}' in text
    assert "Page 2: route=ocr_only" in text
    assert "native_text_chars=0" in text
    assert "image_count=1" in text
    assert "image_block_count=1" in text
    assert "ocr_candidate_count=1" in text
    assert "ignored_ocr_image_count=0" in text
    assert "content_blocks=0" in text
    assert "excluded_blocks=0" in text
    assert "contains_raster_images" in text


def test_routing_report_to_text_includes_excluded_role_summary() -> None:
    report = build_document_routing_report(
        {
            "pdf_kind": "hybrid",
            "pages": [
                {
                    "page_number": 1,
                    "raw_text": "Votre facture\npage : 1/2\nOrange SA",
                    "image_count": 1,
                    "ocr_candidates": [],
                    "ignored_ocr_images": [
                        {"reason": "image_too_small_for_ocr", "classification": "decorative"}
                    ],
                    "block_count": 3,
                    "text_blocks": [
                        {"role": "content", "text": "Votre facture"},
                        {"role": "page_number", "text": "page : 1/2"},
                        {"role": "legal_footer", "text": "Orange SA"},
                    ],
                }
            ],
        }
    )

    text = routing_report_to_text(report)

    assert report["pages"][0]["content_blocks"] == 1
    assert report["pages"][0]["excluded_blocks"] == 2
    assert report["pages"][0]["excluded_role_summary"] == {
        "legal_footer": 1,
        "page_number": 1,
    }
    assert report["pages"][0]["ignored_ocr_image_reason_summary"] == {
        "image_too_small_for_ocr": 1,
    }
    assert report["pages"][0]["ignored_ocr_image_classification_summary"] == {
        "decorative": 1,
    }
    assert 'ignored_ocr_images: {"image_too_small_for_ocr": 1}' in text
    assert 'ignored_ocr_image_classes: {"decorative": 1}' in text
    assert 'excluded_roles: {"legal_footer": 1, "page_number": 1}' in text



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
