from pdf_translator.qa.checks import (
    annotate_repeated_blocks,
    audit_report_to_text,
    build_page_audit,
    build_overlay_ready_report,
    collect_role_summary,
    overlay_ready_report_to_text,
    write_audit_report,
    write_overlay_ready_report,
)
from pdf_translator.translate.glossary import translate_scientific_label
from pdf_translator.translate.glossary import translate_outline_sentence, translate_slide_title


def test_annotate_repeated_blocks_marks_slide_title_page_number_and_content() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": index + 1,
                "height": 800,
                "text_blocks": [
                    {
                        "bbox": {"y0": 20, "y1": 40},
                        "text": "THERMODYNAMIC PN JUNCTION TITLE 1",
                    },
                    {
                        "bbox": {"y0": 300, "y1": 360},
                        "text": f"Real content page {index + 1}",
                    },
                    {
                        "bbox": {"y0": 760, "y1": 780},
                        "text": f"{index + 1}",
                    },
                ],
            }
            for index in range(25)
        ]
    }

    annotated = annotate_repeated_blocks(document_ir)
    summary = collect_role_summary(annotated)

    assert summary["slide_title"] == 25
    assert summary["page_number"] == 25
    assert summary["repeated_chrome"] == 25


def test_build_page_audit_collects_compact_examples() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 3,
                "raw_text": "Header\nReal content",
                "image_count": 2,
                "block_count": 2,
                "text_blocks": [
                    {"role": "header", "text": "COURSE TITLE", "repeat_count": 10},
                    {"role": "content", "text": "Important scientific content\nwith details"},
                ],
            }
        ]
    }

    report = build_page_audit(document_ir, [3])
    text = audit_report_to_text(report)

    assert report["page_count"] == 1
    assert report["role_summary"]["content"] == 1
    assert report["top_repeated_blocks"][0]["repeat_count"] == 10
    assert "Page 3" in text
    assert "Important scientific content | with details" in text


def test_annotate_repeated_blocks_marks_short_symbol_blocks_as_diagram_tokens() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "height": 800,
                "text_blocks": [
                    {"bbox": {"y0": 100, "y1": 120}, "text": "N"},
                    {"bbox": {"y0": 120, "y1": 140}, "text": "+-"},
                    {"bbox": {"y0": 140, "y1": 160}, "text": "Real content line"},
                ],
            }
        ]
    }

    annotated = annotate_repeated_blocks(document_ir)
    roles = [block["role"] for block in annotated["pages"][0]["text_blocks"]]

    assert roles == ["diagram_token", "diagram_token", "content"]


def test_annotate_repeated_blocks_marks_short_uppercase_schema_labels() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "height": 800,
                "text_blocks": [
                    {"bbox": {"y0": 100, "y1": 120}, "text": "ZDR P"},
                    {"bbox": {"y0": 120, "y1": 140}, "text": "x | xn | -xp"},
                    {"bbox": {"y0": 140, "y1": 160}, "text": "CONTACT OHMIQUE"},
                    {"bbox": {"y0": 160, "y1": 180}, "text": "Phrase normale de contenu"},
                ],
            }
        ]
    }

    annotated = annotate_repeated_blocks(document_ir)
    roles = [block["role"] for block in annotated["pages"][0]["text_blocks"]]

    assert roles == ["diagram_label", "diagram_label", "diagram_label", "content"]


def test_annotate_repeated_blocks_marks_multiline_schema_labels() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "height": 540,
                "text_blocks": [
                    {"bbox": {"y0": 150, "y1": 190}, "text": "x\nxn\n-xp"},
                    {"bbox": {"y0": 10, "y1": 30}, "text": "PRINCIPE DE FONCTIONNEMENT DE LA CELLULE PHOTOVOLTAIQUE"},
                ],
            }
        ]
    }

    annotated = annotate_repeated_blocks(document_ir)
    roles = [block["role"] for block in annotated["pages"][0]["text_blocks"]]

    assert roles == ["diagram_label", "slide_title"]


def test_annotate_repeated_blocks_marks_invoice_metadata_as_non_content() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "height": 840,
                "text_blocks": [
                    {
                        "bbox": {"y0": 340, "y1": 440},
                        "text": "Vos coordonnées\nM PARTOUCHE REMI\npartouche@example.org\nn° client : 034 589 6751",
                    },
                    {
                        "bbox": {"y0": 460, "y1": 560},
                        "text": "Nous contacter\nen ligne : contact.orange.fr\nPar téléphone : 3900",
                    },
                    {
                        "bbox": {"y0": 812, "y1": 820},
                        "text": "Orange SA au capital de 10 640 226 396 € - 380 129 866 RCS Nanterre",
                    },
                    {
                        "bbox": {"y0": 294, "y1": 308},
                        "text": "39,36 €",
                    },
                    {
                        "bbox": {"y0": 100, "y1": 130},
                        "text": "Votre facture\ninternet fibre",
                    },
                ],
            }
        ]
    }

    annotated = annotate_repeated_blocks(document_ir)
    roles = [block["role"] for block in annotated["pages"][0]["text_blocks"]]

    assert roles == [
        "sensitive_metadata",
        "support_metadata",
        "legal_footer",
        "numeric_value",
        "content",
    ]


def test_annotate_repeated_blocks_marks_figure_caption_as_caption() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "height": 640,
                "text_blocks": [
                    {
                        "bbox": {"y0": 386, "y1": 404},
                        "text": "Figure 1 : Profil qualitatif de la jonction P/N.",
                    },
                    {
                        "bbox": {"y0": 420, "y1": 438},
                        "text": "Tableau 2 - Parametres experimentaux mesures.",
                    },
                ],
            }
        ]
    }

    annotated = annotate_repeated_blocks(document_ir)
    roles = [block["role"] for block in annotated["pages"][0]["text_blocks"]]

    assert roles == ["caption", "caption"]


def test_annotate_repeated_blocks_marks_simple_table_run() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "height": 640,
                "text_blocks": [
                    {
                        "bbox": {"y0": 100, "y1": 112},
                        "text": "Parametre\nValeur\nUnite",
                        "lines": [
                            {"text": "Parametre", "bbox": {"x0": 54, "y0": 100, "x1": 96, "y1": 112}},
                            {"text": "Valeur", "bbox": {"x0": 190, "y0": 100, "x1": 220, "y1": 112}},
                            {"text": "Unite", "bbox": {"x0": 310, "y0": 100, "x1": 334, "y1": 112}},
                        ],
                    },
                    {
                        "bbox": {"y0": 130, "y1": 142},
                        "text": "Tension directe\n0,72\nV",
                        "lines": [
                            {"text": "Tension directe", "bbox": {"x0": 54, "y0": 130, "x1": 116, "y1": 142}},
                            {"text": "0,72", "bbox": {"x0": 190, "y0": 130, "x1": 212, "y1": 142}},
                            {"text": "V", "bbox": {"x0": 310, "y0": 130, "x1": 316, "y1": 142}},
                        ],
                    },
                    {
                        "bbox": {"y0": 170, "y1": 195},
                        "text": "Paragraph line one\nParagraph line two",
                        "lines": [
                            {"text": "Paragraph line one", "bbox": {"x0": 54, "y0": 170, "x1": 150, "y1": 182}},
                            {"text": "Paragraph line two", "bbox": {"x0": 54, "y0": 183, "x1": 154, "y1": 195}},
                        ],
                    },
                ],
            }
        ]
    }

    annotated = annotate_repeated_blocks(document_ir)
    roles = [block["role"] for block in annotated["pages"][0]["text_blocks"]]

    assert roles == ["table_header", "table_cell", "content"]


def test_annotate_repeated_blocks_marks_typographic_structure_roles() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "height": 800,
                "text_blocks": [
                    {
                        "bbox": {"y0": 40, "y1": 76},
                        "text": "Recette experimentale",
                        "lines": [
                            {
                                "text": "Recette experimentale",
                                "bbox": {"x0": 40, "y0": 40, "x1": 260, "y1": 76},
                                "spans": [{"text": "Recette experimentale", "size": 24, "flags": 4}],
                            }
                        ],
                    },
                    {
                        "bbox": {"y0": 120, "y1": 144},
                        "text": "Étape 1",
                        "lines": [
                            {
                                "text": "Étape 1",
                                "bbox": {"x0": 40, "y0": 120, "x1": 110, "y1": 144},
                                "spans": [{"text": "Étape 1", "size": 18, "flags": 4}],
                            }
                        ],
                    },
                    {
                        "bbox": {"y0": 170, "y1": 190},
                        "text": "Préparer",
                        "lines": [
                            {
                                "text": "Préparer",
                                "bbox": {"x0": 40, "y0": 170, "x1": 120, "y1": 190},
                                "spans": [{"text": "Préparer", "size": 12, "flags": 20}],
                            }
                        ],
                    },
                    {
                        "bbox": {"y0": 220, "y1": 238},
                        "text": "1. Mélanger les poudres",
                        "lines": [
                            {
                                "text": "1. Mélanger les poudres",
                                "bbox": {"x0": 40, "y0": 220, "x1": 210, "y1": 238},
                                "spans": [{"text": "1. Mélanger les poudres", "size": 10, "flags": 4}],
                            }
                        ],
                    },
                    {
                        "bbox": {"y0": 250, "y1": 268},
                        "text": "250g de mascarpone",
                        "lines": [
                            {
                                "text": "250g de mascarpone",
                                "bbox": {"x0": 40, "y0": 250, "x1": 180, "y1": 268},
                                "spans": [{"text": "250g de mascarpone", "size": 10, "flags": 4}],
                            }
                        ],
                    },
                    {
                        "bbox": {"y0": 300, "y1": 318},
                        "text": "Le protocole est ensuite stabilisé par refroidissement.",
                        "lines": [
                            {
                                "text": "Le protocole est ensuite stabilisé par refroidissement.",
                                "bbox": {"x0": 40, "y0": 300, "x1": 340, "y1": 318},
                                "spans": [{"text": "Le protocole est ensuite stabilisé par refroidissement.", "size": 10, "flags": 4}],
                            }
                        ],
                    },
                ],
            }
        ]
    }

    annotated = annotate_repeated_blocks(document_ir)
    roles = [block["role"] for block in annotated["pages"][0]["text_blocks"]]

    assert roles == ["title", "section_step", "short_label", "list_item", "list_item", "content"]


def test_write_audit_report_writes_json_and_text(tmp_path) -> None:
    report = {
        "selected_pages": [1],
        "page_count": 1,
        "role_summary": {"content": 1},
        "top_repeated_blocks": [],
        "pages": [],
    }

    json_path, text_path = write_audit_report(report, tmp_path, "sample_audit")

    assert json_path.exists()
    assert text_path.exists()
    assert '"page_count": 1' in json_path.read_text()
    assert "Audited pages: 1" in text_path.read_text()


def test_build_overlay_ready_report_keeps_content_and_slide_title_blocks(tmp_path) -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 10,
                "width": 100,
                "height": 200,
                "text_blocks": [
                    {
                        "block_index": 0,
                        "role": "footer",
                        "bbox": {"x0": 0, "y0": 1, "x1": 2, "y1": 3},
                        "text": "footer text",
                        "lines": [
                            {
                                "text": "footer text",
                                "bbox": {"x0": 0, "y0": 1, "x1": 2, "y1": 3},
                                "spans": [{"text": "footer text", "size": 7}],
                            }
                        ],
                    },
                    {
                        "block_index": 1,
                        "role": "content",
                        "bbox": {"x0": 10, "y0": 20, "x1": 60, "y1": 50},
                        "text": "useful text",
                        "lines": [
                            {
                                "text": "useful text",
                                "bbox": {"x0": 10, "y0": 20, "x1": 60, "y1": 50},
                                "spans": [{"text": "useful", "size": 10}, {"text": " text", "size": 12}],
                            }
                        ],
                    },
                    {
                        "block_index": 2,
                        "role": "slide_title",
                        "bbox": {"x0": 20, "y0": 21, "x1": 22, "y1": 23},
                        "text": "CHAPTER TITLE",
                        "lines": [
                            {"text": "CHAPTER TITLE", "bbox": {"x0": 20, "y0": 21, "x1": 22, "y1": 23}}
                        ],
                    },
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [10])
    text = overlay_ready_report_to_text(report)
    json_path, text_path = write_overlay_ready_report(report, tmp_path, "overlay_ready")

    assert report["total_candidate_blocks"] == 2
    assert report["total_excluded_blocks"] == 1
    assert report["total_page_zone_review_items"] == 0
    assert report["total_reading_flow_review_items"] == 0
    assert report["page_zone_review_items"] == []
    assert report["reading_flow_review_items"] == []
    assert report["selection_reason_summary"] == {
        "selected_as_content": 1,
        "selected_as_title": 1,
    }
    assert report["exclusion_reason_summary"] == {"excluded_as_footer": 1}
    assert report["reading_flow_summary"] == {"single_column_flow": 2}
    assert report["reading_flow_flag_summary"] == {}
    assert report["page_zone_flag_summary"] == {}
    assert report["candidate_page_zone_summary"] == {
        "vertical": {"body_zone": 1, "header_zone": 1},
        "horizontal": {"center_band": 2},
    }
    assert report["excluded_page_zone_summary"] == {
        "vertical": {"header_zone": 1},
        "horizontal": {"left_margin": 1},
    }
    assert report["candidate_page_zone_role_summary"] == {
        "vertical": {
            "body_zone": {"content": 1},
            "header_zone": {"slide_title": 1},
        },
        "horizontal": {"center_band": {"content": 1, "slide_title": 1}},
    }
    assert report["excluded_page_zone_reason_summary"] == {
        "vertical": {"header_zone": {"excluded_as_footer": 1}},
        "horizontal": {"left_margin": {"excluded_as_footer": 1}},
    }
    assert report["pages"][0]["candidate_page_zone_summary"] == {
        "vertical": {"body_zone": 1, "header_zone": 1},
        "horizontal": {"center_band": 2},
    }
    assert report["pages"][0]["excluded_page_zone_summary"] == {
        "vertical": {"header_zone": 1},
        "horizontal": {"left_margin": 1},
    }
    assert report["pages"][0]["candidate_page_zone_role_summary"] == {
        "vertical": {
            "body_zone": {"content": 1},
            "header_zone": {"slide_title": 1},
        },
        "horizontal": {"center_band": {"content": 1, "slide_title": 1}},
    }
    assert report["pages"][0]["excluded_page_zone_reason_summary"] == {
        "vertical": {"header_zone": {"excluded_as_footer": 1}},
        "horizontal": {"left_margin": {"excluded_as_footer": 1}},
    }
    assert report["pages"][0]["reading_flow_summary"] == {"single_column_flow": 2}
    assert report["pages"][0]["reading_flow_flag_summary"] == {}
    assert report["pages"][0]["reading_flow_review_item_count"] == 0
    assert report["pages"][0]["reading_flow_review_items"] == []
    assert report["pages"][0]["page_zone_flag_summary"] == {}
    assert report["pages"][0]["page_zone_review_item_count"] == 0
    assert report["pages"][0]["page_zone_review_items"] == []
    assert report["pages"][0]["candidates"][0]["block_index"] == 1
    assert report["pages"][0]["candidates"][0]["selection_reason"] == "selected_as_content"
    assert report["pages"][0]["candidates"][0]["page_zone_flags"] == []
    assert report["pages"][0]["candidates"][0]["reading_flow"] == {
        "reading_order_index": 0,
        "previous_candidate_gap": None,
        "next_candidate_gap": {
            "vertical_gap": 0.0,
            "x_overlap": 1.0,
            "same_column": True,
        },
        "same_column_as_previous": None,
        "x_overlap_with_previous": None,
        "vertical_gap_to_previous": None,
        "classification": "single_column_flow",
        "flags": [],
    }
    assert report["pages"][0]["candidates"][0]["page_zone"] == {
        "vertical": "body_zone",
        "horizontal": "center_band",
    }
    assert report["pages"][0]["candidates"][0]["geometry"] == {
        "width": 50.0,
        "height": 30.0,
        "area_ratio": 0.075,
        "x_center": 35.0,
        "y_center": 35.0,
        "font_size_summary": {
            "min": 10.0,
            "max": 12.0,
            "median": 11.0,
            "span_count": 2,
        },
    }
    assert report["pages"][0]["candidates"][1]["block_index"] == 2
    assert report["pages"][0]["candidates"][1]["selection_reason"] == "selected_as_title"
    assert report["pages"][0]["candidates"][1]["page_zone_flags"] == []
    assert report["pages"][0]["excluded_blocks"][0]["block_index"] == 0
    assert report["pages"][0]["excluded_blocks"][0]["exclusion_reason"] == "excluded_as_footer"
    assert report["pages"][0]["excluded_blocks"][0]["page_zone_flags"] == []
    assert report["pages"][0]["excluded_blocks"][0]["page_zone"] == {
        "vertical": "header_zone",
        "horizontal": "left_margin",
    }
    assert report["pages"][0]["excluded_blocks"][0]["geometry"]["width"] == 2.0
    assert report["pages"][0]["excluded_blocks"][0]["geometry"]["font_size_summary"] == {
        "min": 7.0,
        "max": 7.0,
        "median": 7.0,
        "span_count": 1,
    }
    assert "candidate_blocks=2" in text
    assert "excluded_blocks=1" in text
    assert "Total page zone review items: 0" in text
    assert "Total reading flow review items: 0" in text
    assert "page_zone_review_items=0" in text
    assert "reading_flow_review_items=0" in text
    assert "selected_as_content" in text
    assert "excluded_as_footer" in text
    assert "Reading flow:" in text
    assert "flow=single_column_flow" in text
    assert "Candidate page zones:" in text
    assert "Excluded page zones:" in text
    assert "candidate zones:" in text
    assert "excluded zones:" in text
    assert "Candidate zone roles:" in text
    assert "Excluded zone reasons:" in text
    assert "candidate zone roles:" in text
    assert "excluded zone reasons:" in text
    assert json_path.exists()
    assert text_path.exists()


def test_build_overlay_ready_report_classifies_page_zones() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "width": 100,
                "height": 200,
                "text_blocks": [
                    {
                        "block_index": 1,
                        "role": "content",
                        "bbox": {"x0": 40, "y0": 10, "x1": 60, "y1": 20},
                        "text": "top",
                        "lines": [{"text": "top", "bbox": {"x0": 40, "y0": 10, "x1": 60, "y1": 20}}],
                    },
                    {
                        "block_index": 2,
                        "role": "content",
                        "bbox": {"x0": 40, "y0": 80, "x1": 60, "y1": 100},
                        "text": "middle",
                        "lines": [{"text": "middle", "bbox": {"x0": 40, "y0": 80, "x1": 60, "y1": 100}}],
                    },
                    {
                        "block_index": 3,
                        "role": "content",
                        "bbox": {"x0": 40, "y0": 180, "x1": 60, "y1": 190},
                        "text": "bottom",
                        "lines": [{"text": "bottom", "bbox": {"x0": 40, "y0": 180, "x1": 60, "y1": 190}}],
                    },
                    {
                        "block_index": 4,
                        "role": "content",
                        "bbox": {"x0": 0, "y0": 80, "x1": 10, "y1": 100},
                        "text": "left",
                        "lines": [{"text": "left", "bbox": {"x0": 0, "y0": 80, "x1": 10, "y1": 100}}],
                    },
                    {
                        "block_index": 5,
                        "role": "content",
                        "bbox": {"x0": 90, "y0": 80, "x1": 100, "y1": 100},
                        "text": "right",
                        "lines": [{"text": "right", "bbox": {"x0": 90, "y0": 80, "x1": 100, "y1": 100}}],
                    },
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [1])
    zones = {
        item["block_index"]: item["page_zone"]
        for item in report["pages"][0]["candidates"]
    }

    assert zones[1] == {"vertical": "header_zone", "horizontal": "center_band"}
    assert zones[2] == {"vertical": "body_zone", "horizontal": "center_band"}
    assert zones[3] == {"vertical": "footer_zone", "horizontal": "center_band"}
    assert zones[4] == {"vertical": "body_zone", "horizontal": "left_margin"}
    assert zones[5] == {"vertical": "body_zone", "horizontal": "right_margin"}
    assert report["candidate_page_zone_summary"] == {
        "vertical": {"body_zone": 3, "footer_zone": 1, "header_zone": 1},
        "horizontal": {"center_band": 3, "left_margin": 1, "right_margin": 1},
    }
    assert report["candidate_page_zone_role_summary"] == {
        "vertical": {
            "body_zone": {"content": 3},
            "footer_zone": {"content": 1},
            "header_zone": {"content": 1},
        },
        "horizontal": {
            "center_band": {"content": 3},
            "left_margin": {"content": 1},
            "right_margin": {"content": 1},
        },
    }
    assert report["reading_flow_summary"] == {
        "multi_column_candidate": 2,
        "single_column_flow": 3,
    }
    assert report["reading_flow_flag_summary"] == {
        "review_candidate_order_moves_up_page": 1,
    }
    assert report["total_reading_flow_review_items"] == 1
    assert report["pages"][0]["reading_flow_review_item_count"] == 1
    assert report["reading_flow_review_items"][0] == {
        "page_number": 1,
        "block_index": 4,
        "role": "content",
        "selection_reason": "selected_as_content",
        "reading_order_index": 3,
        "classification": "multi_column_candidate",
        "flags": ["review_candidate_order_moves_up_page"],
        "vertical_gap_to_previous": 0.0,
        "x_overlap_with_previous": 0.0,
        "same_column_as_previous": False,
        "line_count": 1,
        "text_preview": "left",
    }
    assert report["pages"][0]["candidates"][2]["reading_flow"]["flags"] == []
    assert report["pages"][0]["candidates"][3]["reading_flow"]["flags"] == [
        "review_candidate_order_moves_up_page",
    ]
    assert report["pages"][0]["candidates"][4]["reading_flow"]["classification"] == "multi_column_candidate"
    assert report["page_zone_flag_summary"] == {
        "review_candidate_content_role_in_footer_zone": 1,
        "review_candidate_content_role_in_header_zone": 1,
        "review_candidate_content_role_in_margin": 2,
    }
    assert report["total_page_zone_review_items"] == 4
    assert report["pages"][0]["page_zone_review_item_count"] == 4
    assert report["page_zone_review_items"][0] == {
        "page_number": 1,
        "item_type": "candidate",
        "block_index": 1,
        "role": "content",
        "page_zone": {"vertical": "header_zone", "horizontal": "center_band"},
        "page_zone_flags": ["review_candidate_content_role_in_header_zone"],
        "line_count": 1,
        "text_preview": "top",
        "selection_reason": "selected_as_content",
    }
    assert {
        item["block_index"]: item["page_zone_flags"]
        for item in report["pages"][0]["candidates"]
    } == {
        1: ["review_candidate_content_role_in_header_zone"],
        2: [],
        3: ["review_candidate_content_role_in_footer_zone"],
        4: ["review_candidate_content_role_in_margin"],
        5: ["review_candidate_content_role_in_margin"],
    }


def test_build_overlay_ready_report_flags_body_zone_structural_exclusions() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "width": 100,
                "height": 200,
                "text_blocks": [
                    {
                        "block_index": 1,
                        "role": "header",
                        "bbox": {"x0": 30, "y0": 80, "x1": 70, "y1": 100},
                        "text": "misplaced header",
                        "lines": [
                            {
                                "text": "misplaced header",
                                "bbox": {"x0": 30, "y0": 80, "x1": 70, "y1": 100},
                            }
                        ],
                    }
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [1])
    text = overlay_ready_report_to_text(report)

    assert report["total_reading_flow_review_items"] == 0
    assert report["reading_flow_review_items"] == []
    assert report["total_page_zone_review_items"] == 1
    assert report["page_zone_flag_summary"] == {
        "review_structural_exclusion_in_body_zone": 1,
    }
    assert report["pages"][0]["page_zone_flag_summary"] == {
        "review_structural_exclusion_in_body_zone": 1,
    }
    assert report["pages"][0]["excluded_blocks"][0]["page_zone_flags"] == [
        "review_structural_exclusion_in_body_zone"
    ]
    assert report["page_zone_review_items"] == [
        {
            "page_number": 1,
            "item_type": "excluded",
            "block_index": 1,
            "role": "header",
            "page_zone": {"vertical": "body_zone", "horizontal": "center_band"},
            "page_zone_flags": ["review_structural_exclusion_in_body_zone"],
            "line_count": 1,
            "text_preview": "misplaced header",
            "exclusion_reason": "excluded_as_header",
        }
    ]
    assert "Page zone flags:" in text
    assert "page zone flags:" in text
    assert "Total page zone review items: 1" in text
    assert "review excluded block 1" in text


def test_build_overlay_ready_report_classifies_table_and_caption_reading_flow() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "width": 300,
                "height": 300,
                "text_blocks": [
                    {
                        "block_index": 1,
                        "role": "table_header",
                        "bbox": {"x0": 20, "y0": 40, "x1": 120, "y1": 60},
                        "text": "Header",
                        "lines": [{"text": "Header", "bbox": {"x0": 20, "y0": 40, "x1": 120, "y1": 60}}],
                    },
                    {
                        "block_index": 2,
                        "role": "table_cell",
                        "bbox": {"x0": 20, "y0": 62, "x1": 120, "y1": 82},
                        "text": "Cell",
                        "lines": [{"text": "Cell", "bbox": {"x0": 20, "y0": 62, "x1": 120, "y1": 82}}],
                    },
                    {
                        "block_index": 3,
                        "role": "caption",
                        "bbox": {"x0": 20, "y0": 180, "x1": 180, "y1": 200},
                        "text": "Figure 1: caption",
                        "lines": [{"text": "Figure 1: caption", "bbox": {"x0": 20, "y0": 180, "x1": 180, "y1": 200}}],
                    },
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [1])

    assert report["reading_flow_summary"] == {
        "floating_label_or_caption": 1,
        "table_like_flow": 2,
    }
    assert report["reading_flow_flag_summary"] == {
        "review_large_vertical_gap_between_candidates": 1,
    }
    assert report["total_reading_flow_review_items"] == 1
    assert report["reading_flow_review_items"][0]["block_index"] == 3
    assert report["reading_flow_review_items"][0]["classification"] == "floating_label_or_caption"
    assert [
        candidate["reading_flow"]["classification"]
        for candidate in report["pages"][0]["candidates"]
    ] == [
        "table_like_flow",
        "table_like_flow",
        "floating_label_or_caption",
    ]


def test_build_overlay_ready_report_merges_slide_title_suffix_blocks() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 10,
                "width": 400,
                "height": 200,
                "text_blocks": [
                    {
                        "block_index": 3,
                        "role": "slide_title",
                        "bbox": {"x0": 100, "y0": 10, "x1": 300, "y1": 30},
                        "text": "MAIN TITLE",
                        "lines": [{"text": "MAIN TITLE", "bbox": {"x0": 100, "y0": 10, "x1": 300, "y1": 30}, "spans": []}],
                    },
                    {
                        "block_index": 4,
                        "role": "header",
                        "bbox": {"x0": 302, "y0": 10, "x1": 308, "y1": 30},
                        "text": "-",
                        "lines": [{"text": "-", "bbox": {"x0": 302, "y0": 10, "x1": 308, "y1": 30}, "spans": []}],
                    },
                    {
                        "block_index": 5,
                        "role": "header",
                        "bbox": {"x0": 310, "y0": 10, "x1": 320, "y1": 30},
                        "text": "2",
                        "lines": [{"text": "2", "bbox": {"x0": 310, "y0": 10, "x1": 320, "y1": 30}, "spans": []}],
                    },
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [10])

    assert report["total_candidate_blocks"] == 1
    assert report["pages"][0]["candidates"][0]["text"] == "MAIN TITLE - 2"
    assert report["pages"][0]["candidates"][0]["bbox"] == {"x0": 100.0, "y0": 10.0, "x1": 320.0, "y1": 30.0}
    assert report["pages"][0]["candidates"][0]["geometry"]["width"] == 220.0
    assert report["pages"][0]["candidates"][0]["geometry"]["x_center"] == 210.0
    assert report["pages"][0]["candidates"][0]["selection_reason"] == "selected_as_title"
    assert report["pages"][0]["candidates"][0]["merged_block_indices"] == [3, 4, 5]
    assert report["total_excluded_blocks"] == 0


def test_build_overlay_ready_report_keeps_only_glossary_backed_diagram_labels() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 160,
                "text_blocks": [
                    {
                        "block_index": 1,
                        "role": "diagram_label",
                        "bbox": {"x0": 10, "y0": 10, "x1": 80, "y1": 20},
                        "text": "CONTACT OHMIQUE",
                        "lines": [{"text": "CONTACT OHMIQUE", "bbox": {"x0": 10, "y0": 10, "x1": 80, "y1": 20}}],
                    },
                    {
                        "block_index": 2,
                        "role": "diagram_label",
                        "bbox": {"x0": 10, "y0": 30, "x1": 40, "y1": 40},
                        "text": "ZDR P",
                        "lines": [{"text": "ZDR P", "bbox": {"x0": 10, "y0": 30, "x1": 40, "y1": 40}}],
                    },
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [160])

    assert report["total_candidate_blocks"] == 1
    assert report["total_excluded_blocks"] == 1
    assert report["pages"][0]["candidates"][0]["text"] == "CONTACT OHMIQUE"
    assert report["pages"][0]["candidates"][0]["selection_reason"] == "selected_as_glossary_backed_diagram_label"
    assert report["pages"][0]["excluded_blocks"][0]["block_index"] == 2
    assert report["pages"][0]["excluded_blocks"][0]["exclusion_reason"] == "excluded_as_untranslated_diagram_label"
    assert translate_scientific_label("CONTACT OHMIQUE") == "OHMIC CONTACT"
    assert translate_scientific_label("Semiconducteur") == "Semiconductor"
    assert translate_scientific_label("Tension d'avalanche") == "Breakdown voltage"
    assert translate_scientific_label("Si type P") == "P-type Si"
    assert translate_scientific_label("Homojonction") == "Homojunction"


def test_build_overlay_ready_report_explains_admin_exclusions() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "text_blocks": [
                    {
                        "block_index": 1,
                        "role": "billing_metadata",
                        "bbox": {"x0": 10, "y0": 10, "x1": 80, "y1": 20},
                        "text": "Facture n° 2026-001",
                        "lines": [{"text": "Facture n° 2026-001", "bbox": {"x0": 10, "y0": 10, "x1": 80, "y1": 20}}],
                    },
                    {
                        "block_index": 2,
                        "role": "sensitive_metadata",
                        "bbox": {"x0": 10, "y0": 30, "x1": 80, "y1": 40},
                        "text": "n° client : C-778899",
                        "lines": [{"text": "n° client : C-778899", "bbox": {"x0": 10, "y0": 30, "x1": 80, "y1": 40}}],
                    },
                    {
                        "block_index": 3,
                        "role": "numeric_value",
                        "bbox": {"x0": 10, "y0": 50, "x1": 80, "y1": 60},
                        "text": "31,99 EUR",
                        "lines": [{"text": "31,99 EUR", "bbox": {"x0": 10, "y0": 50, "x1": 80, "y1": 60}}],
                    },
                    {
                        "block_index": 4,
                        "role": "content",
                        "bbox": {"x0": 10, "y0": 70, "x1": 160, "y1": 80},
                        "text": "Abonnement mensuel fibre optique",
                        "lines": [{"text": "Abonnement mensuel fibre optique", "bbox": {"x0": 10, "y0": 70, "x1": 160, "y1": 80}}],
                    },
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [1])

    assert report["total_candidate_blocks"] == 1
    assert report["total_excluded_blocks"] == 3
    assert report["selection_reason_summary"] == {"selected_as_content": 1}
    assert report["exclusion_reason_summary"] == {
        "excluded_as_billing_metadata": 1,
        "excluded_as_numeric_value": 1,
        "excluded_as_sensitive_metadata": 1,
    }
    assert [
        item["exclusion_reason"]
        for item in report["pages"][0]["excluded_blocks"]
    ] == [
        "excluded_as_billing_metadata",
        "excluded_as_sensitive_metadata",
        "excluded_as_numeric_value",
    ]


def test_build_overlay_ready_report_explains_structural_selection_reasons() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "text_blocks": [
                    {
                        "block_index": 1,
                        "role": "title",
                        "bbox": {"x0": 10, "y0": 10, "x1": 180, "y1": 30},
                        "text": "Recette experimentale",
                        "lines": [{"text": "Recette experimentale", "bbox": {"x0": 10, "y0": 10, "x1": 180, "y1": 30}}],
                    },
                    {
                        "block_index": 2,
                        "role": "section_step",
                        "bbox": {"x0": 10, "y0": 40, "x1": 90, "y1": 60},
                        "text": "Étape 1",
                        "lines": [{"text": "Étape 1", "bbox": {"x0": 10, "y0": 40, "x1": 90, "y1": 60}}],
                    },
                    {
                        "block_index": 3,
                        "role": "short_label",
                        "bbox": {"x0": 10, "y0": 70, "x1": 100, "y1": 90},
                        "text": "Préparer",
                        "lines": [{"text": "Préparer", "bbox": {"x0": 10, "y0": 70, "x1": 100, "y1": 90}}],
                    },
                    {
                        "block_index": 4,
                        "role": "list_item",
                        "bbox": {"x0": 10, "y0": 100, "x1": 160, "y1": 120},
                        "text": "1. Mélanger les poudres",
                        "lines": [{"text": "1. Mélanger les poudres", "bbox": {"x0": 10, "y0": 100, "x1": 160, "y1": 120}}],
                    },
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [1])

    assert report["total_candidate_blocks"] == 4
    assert report["selection_reason_summary"] == {
        "selected_as_list_item": 1,
        "selected_as_section_step": 1,
        "selected_as_short_label": 1,
        "selected_as_title": 1,
    }
    assert [
        item["selection_reason"]
        for item in report["pages"][0]["candidates"]
    ] == [
        "selected_as_title",
        "selected_as_section_step",
        "selected_as_short_label",
        "selected_as_list_item",
    ]


def test_glossary_supports_page_120_pedagogical_lines() -> None:
    assert translate_slide_title("JONCTION P/N EN DYNAMIQUE") == "JUNCTION P/N UNDER DYNAMIC CONDITIONS"
    assert translate_outline_sentence("1 - La Conductance de la jonction") == "1 - Junction conductance"
    assert (
        translate_outline_sentence("Nous aborderons donc le calcul de :")
        == "We will therefore examine the calculation of:"
    )
    assert (
        translate_outline_sentence("2 - La Capacité de Stockage et de Transition")
        == "2 - Storage and transition capacitance"
    )


def test_glossary_supports_page_34_pedagogical_lines() -> None:
    assert (
        translate_outline_sentence(
            "Commençons par une polarisation en direct, pour cela c’est facile :\nOn relie la région P du matériau SC au pole + d’un générateur de tension et"
        )
        == "Let us begin with forward biasing; it is simple:\nThe P region of the semiconductor is connected to the + terminal of a voltage source and"
    )
    assert (
        translate_outline_sentence("Commençons par une polarisation en direct, pour cela c’est facile :")
        == "Let us begin with forward biasing; it is quite straightforward:"
    )
    assert (
        translate_outline_sentence("On relie la région P du matériau SC au pole + d’un générateur de tension et")
        == "The P region of the semiconductor is connected to the positive terminal of a voltage source and"
    )
