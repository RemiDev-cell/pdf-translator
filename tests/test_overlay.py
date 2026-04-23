import fitz

from pdf_translator.compose.overlay import (
    build_pre_overlay_report,
    build_translation_preview_report,
    build_translation_preview_segments,
    pre_overlay_report_to_text,
    render_pre_overlay_diagnostics,
    translation_preview_report_to_text,
    write_pre_overlay_report,
    write_translation_preview_report,
)


def test_build_pre_overlay_report_keeps_region_geometry(tmp_path) -> None:
    overlay_ready_report = {
        "selected_pages": [10],
        "pages": [
            {
                "page_number": 10,
                "candidates": [
                    {
                        "block_index": 98,
                        "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
                        "text": "Useful translated block",
                        "line_count": 2,
                        "lines": [
                            {"text": "line 1", "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4}},
                            {"text": "line 2", "bbox": {"x0": 5, "y0": 6, "x1": 7, "y1": 8}},
                        ],
                    }
                ],
            }
        ],
    }

    report = build_pre_overlay_report(overlay_ready_report)
    text = pre_overlay_report_to_text(report)
    json_path, text_path = write_pre_overlay_report(report, tmp_path, "pre_overlay")

    assert report["total_regions"] == 1
    assert report["pages"][0]["regions"][0]["block_index"] == 98
    assert "Page 10: regions=1" in text
    assert json_path.exists()
    assert text_path.exists()


def test_render_pre_overlay_diagnostics_writes_pdf_and_pngs(tmp_path) -> None:
    source_pdf = tmp_path / "source.pdf"
    doc = fitz.open()
    doc.new_page(width=200, height=200)
    doc.save(source_pdf)
    doc.close()

    report = {
        "pages": [
            {
                "page_number": 1,
                "regions": [
                    {
                        "block_index": 0,
                        "bbox": {"x0": 10, "y0": 20, "x1": 100, "y1": 80},
                        "source_text": "Hello",
                        "line_count": 1,
                        "lines": [],
                    }
                ],
            }
        ]
    }

    pdf_path, image_paths = render_pre_overlay_diagnostics(
        pdf_path=source_pdf,
        pre_overlay_report=report,
        output_dir=tmp_path,
        stem="preview",
    )

    assert pdf_path.exists()
    assert len(image_paths) == 1
    assert image_paths[0].exists()


def test_build_translation_preview_segments_splits_long_regions_and_skips_symbolic() -> None:
    pre_overlay_report = {
        "pages": [
            {
                "page_number": 10,
                "regions": [
                    {
                        "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                        "source_text": "line one\nline two\nline three\nline four",
                        "lines": [
                            {"text": "line one"},
                            {"text": "line two"},
                            {"text": "line three"},
                            {"text": "line four"},
                        ],
                    },
                    {
                        "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                        "source_text": "Cp | Dp | p | J",
                        "lines": [{"text": "Cp | Dp | p | J"}],
                    },
                ],
            }
        ]
    }

    segments = build_translation_preview_segments(pre_overlay_report, [10], max_lines_per_segment=2)

    assert len(segments["pages"][0]["regions"]) == 3
    assert segments["pages"][0]["regions"][0]["translate"] is True
    assert segments["pages"][0]["regions"][1]["translate"] is True
    assert segments["pages"][0]["regions"][2]["translate"] is False


def test_build_translation_preview_report_marks_statuses_and_writes_files(tmp_path) -> None:
    segments_report = {
        "selected_pages": [10],
        "pages": [
            {
                "page_number": 10,
                "regions": [
                    {"source_text": "Bonjour", "bbox": {}, "translate": True},
                    {"source_text": "Cp | Dp | p | J", "bbox": {}, "translate": False},
                ],
            }
        ],
    }

    report = build_translation_preview_report(segments_report, lambda text: "Hello")
    text = translation_preview_report_to_text(report)
    json_path, text_path = write_translation_preview_report(report, tmp_path, "translation_preview")

    assert report["pages"][0]["regions"][0]["status"] == "translated"
    assert report["pages"][0]["regions"][1]["status"] == "skipped"
    assert "Region 1 [translated]" in text
    assert json_path.exists()
    assert text_path.exists()
