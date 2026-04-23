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


def test_annotate_repeated_blocks_marks_repeated_header_and_footer() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": index + 1,
                "height": 800,
                "text_blocks": [
                    {
                        "bbox": {"y0": 20, "y1": 40},
                        "text": "COURSE TITLE 1",
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

    assert summary["header"] == 25
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


def test_build_overlay_ready_report_keeps_only_content_blocks(tmp_path) -> None:
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
                ],
            }
        ]
    }

    report = build_overlay_ready_report(document_ir, [10])
    text = overlay_ready_report_to_text(report)
    json_path, text_path = write_overlay_ready_report(report, tmp_path, "overlay_ready")

    assert report["total_candidate_blocks"] == 1
    assert report["pages"][0]["candidates"][0]["block_index"] == 1
    assert "candidate_blocks=1" in text
    assert json_path.exists()
    assert text_path.exists()
