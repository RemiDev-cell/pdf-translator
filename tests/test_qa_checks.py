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
                "text_blocks": [
                    {
                        "block_index": 0,
                        "role": "footer",
                        "bbox": {"x0": 0, "y0": 1, "x1": 2, "y1": 3},
                        "text": "footer text",
                        "lines": [],
                    },
                    {
                        "block_index": 1,
                        "role": "content",
                        "bbox": {"x0": 10, "y0": 11, "x1": 12, "y1": 13},
                        "text": "useful text",
                        "lines": [
                            {"text": "useful text", "bbox": {"x0": 10, "y0": 11, "x1": 12, "y1": 13}}
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
    assert report["pages"][0]["candidates"][0]["block_index"] == 1
    assert report["pages"][0]["candidates"][1]["block_index"] == 2
    assert "candidate_blocks=2" in text
    assert json_path.exists()
    assert text_path.exists()


def test_build_overlay_ready_report_merges_slide_title_suffix_blocks() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 10,
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
    assert report["pages"][0]["candidates"][0]["text"] == "CONTACT OHMIQUE"
    assert translate_scientific_label("CONTACT OHMIQUE") == "OHMIC CONTACT"
    assert translate_scientific_label("Semiconducteur") == "Semiconductor"
    assert translate_scientific_label("Tension d'avalanche") == "Breakdown voltage"
    assert translate_scientific_label("Si type P") == "P-type Si"
    assert translate_scientific_label("Homojonction") == "Homojunction"


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
