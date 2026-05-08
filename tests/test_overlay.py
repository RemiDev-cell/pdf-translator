import fitz
import requests

from pdf_translator.compose.overlay import (
    build_pre_overlay_report,
    build_replacement_plan,
    build_translation_preview_report,
    build_translation_preview_segments,
    overlay_prototype_summary_to_text,
    pre_overlay_report_to_text,
    render_overlay_prototype,
    replacement_plan_to_text,
    render_pre_overlay_diagnostics,
    translation_preview_report_to_text,
    write_overlay_prototype_summary,
    write_pre_overlay_report,
    write_replacement_plan,
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
                        "role": "slide_title",
                        "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
                        "text": "Useful translated block",
                        "line_count": 2,
                        "page_zone": {"vertical": "header_zone", "horizontal": "left_margin"},
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
    assert report["pages"][0]["regions"][0]["role"] == "slide_title"
    assert "page_zone" not in report["pages"][0]["regions"][0]
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
                        "role": "content",
                        "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                        "source_text": "line one\nline two\nline three\nline four",
                        "lines": [
                            {"text": "line one", "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10}, "spans": [{"color": 0}]},
                            {"text": "line two", "bbox": {"x0": 0, "y0": 10, "x1": 10, "y1": 20}, "spans": [{"color": 0}]},
                            {"text": "line three", "bbox": {"x0": 0, "y0": 20, "x1": 10, "y1": 30}, "spans": [{"color": 255}]},
                            {"text": "line four", "bbox": {"x0": 0, "y0": 30, "x1": 10, "y1": 40}, "spans": [{"color": 255}]},
                        ],
                    },
                    {
                        "role": "content",
                        "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1},
                        "source_text": "Cp | Dp | p | J",
                        "lines": [{"text": "Cp | Dp | p | J", "bbox": {"x0": 0, "y0": 50, "x1": 10, "y1": 60}, "spans": [{"color": 0}]}],
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
    assert segments["pages"][0]["regions"][0]["bbox"] == {"x0": 0, "y0": 0, "x1": 10, "y1": 20}
    assert segments["pages"][0]["regions"][1]["bbox"] == {"x0": 0, "y0": 20, "x1": 10, "y1": 40}
    assert segments["pages"][0]["regions"][0]["source_color"] == 0
    assert segments["pages"][0]["regions"][0]["source_color_mode"] == "uniform"
    assert segments["pages"][0]["regions"][1]["source_color"] == 255


def test_build_translation_preview_report_marks_statuses_and_writes_files(tmp_path) -> None:
    segments_report = {
        "selected_pages": [10],
        "pages": [
            {
                "page_number": 10,
                "regions": [
                    {"source_text": "Bonjour", "role": "content", "bbox": {}, "translate": True},
                    {"source_text": "Cp | Dp | p | J", "role": "content", "bbox": {}, "translate": False},
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


def test_build_translation_preview_report_strips_unexpected_placeholders() -> None:
    segments_report = {
        "selected_pages": [22],
        "pages": [
            {
                "page_number": 22,
                "regions": [
                    {
                        "source_text": "Calculons la densité de courant.",
                        "role": "content",
                        "bbox": {},
                        "translate": True,
                    }
                ],
            }
        ],
    }

    report = build_translation_preview_report(
        segments_report,
        lambda _: "Let's calculate the current density.\n[[VERSION_1]]\n[[URL_1]]",
    )

    assert report["pages"][0]["regions"][0]["translated_text"] == "Let's calculate the current density."


def test_build_translation_preview_report_keeps_aligned_translated_lines_when_line_breaks_match() -> None:
    segments_report = {
        "selected_pages": [10],
        "pages": [
            {
                "page_number": 10,
                "regions": [
                    {
                        "source_text": "ligne 1\nligne 2",
                        "role": "content",
                        "bbox": {},
                        "source_color": 0,
                        "source_color_mode": "uniform",
                        "source_lines": [
                            {
                                "text": "ligne 1",
                                "bbox": {"x0": 0, "y0": 0, "x1": 10, "y1": 10},
                                "source_color": 0,
                                "source_color_mode": "uniform",
                                "source_spans": [
                                    {"text": "ligne", "source_color": 16711680},
                                    {"text": " 1", "source_color": 0},
                                ],
                            },
                            {
                                "text": "ligne 2",
                                "bbox": {"x0": 0, "y0": 10, "x1": 10, "y1": 20},
                                "source_color": 0,
                                "source_color_mode": "uniform",
                                "source_spans": [
                                    {"text": "ligne", "source_color": 255},
                                    {"text": " 2", "source_color": 0},
                                ],
                            },
                        ],
                        "translate": True,
                    }
                ],
            }
        ],
    }

    def fake_translate(text: str) -> str:
        return "EN:ligne 1\nEN:ligne 2"

    report = build_translation_preview_report(segments_report, fake_translate)

    assert report["pages"][0]["regions"][0]["status"] == "translated"
    assert report["pages"][0]["regions"][0]["translated_text"] == "EN:ligne 1\nEN:ligne 2"
    assert report["pages"][0]["regions"][0]["translated_lines"][0]["text"] == "EN:ligne 1"
    assert report["pages"][0]["regions"][0]["translated_lines"][1]["text"] == "EN:ligne 2"
    assert len(report["pages"][0]["regions"][0]["translated_lines"][0]["translated_segments"]) == 2


def test_build_translation_preview_report_infers_line_split_from_source_structure() -> None:
    segments_report = {
        "selected_pages": [22],
        "pages": [
            {
                "page_number": 22,
                "regions": [
                    {
                        "source_text": "ligne source 1\nligne source 2",
                        "role": "content",
                        "bbox": {},
                        "source_lines": [
                            {
                                "text": "ligne source 1",
                                "bbox": {"x0": 0, "y0": 0, "x1": 100, "y1": 10},
                                "source_color": 0,
                                "source_color_mode": "uniform",
                                "source_font": "Arial-BoldMT",
                                "source_font_size": 16.0,
                                "source_spans": [{"text": "ligne source 1", "source_color": 0}],
                            },
                            {
                                "text": "ligne source 2",
                                "bbox": {"x0": 0, "y0": 10, "x1": 60, "y1": 20},
                                "source_color": 0,
                                "source_color_mode": "uniform",
                                "source_font": "Arial-BoldMT",
                                "source_font_size": 16.0,
                                "source_spans": [{"text": "ligne source 2", "source_color": 0}],
                            },
                        ],
                        "translate": True,
                    }
                ],
            }
        ],
    }

    report = build_translation_preview_report(
        segments_report,
        lambda _: "This translated sentence should be split over two source-shaped lines.",
    )

    assert report["pages"][0]["regions"][0]["translated_lines"] is not None
    assert len(report["pages"][0]["regions"][0]["translated_lines"]) == 2


def test_build_translation_preview_report_uses_slide_title_fallback_on_timeout() -> None:
    segments_report = {
        "selected_pages": [10],
        "pages": [
            {
                "page_number": 10,
                "regions": [
                    {
                        "source_text": "JONCTION P/N A L’EQUILIBRE THERMODYNAMIQUE",
                        "role": "slide_title",
                        "bbox": {},
                        "source_color": 16777215,
                        "source_color_mode": "uniform",
                        "translate": True,
                    }
                ],
            }
        ],
    }

    def always_timeout(_: str) -> str:
        raise requests.exceptions.Timeout()

    report = build_translation_preview_report(segments_report, always_timeout)

    assert report["pages"][0]["regions"][0]["status"] == "translated"
    assert report["pages"][0]["regions"][0]["translated_text"] == "JUNCTION P/N AT THERMODYNAMIC EQUILIBRIUM"


def test_build_translation_preview_report_falls_back_to_clausewise_translation_for_single_line_timeout() -> None:
    segments_report = {
        "selected_pages": [22],
        "pages": [
            {
                "page_number": 22,
                "regions": [
                    {
                        "source_text": "2. La conséquence de l’établissement d’une ZCE négative côté P, positive côté N :",
                        "role": "content",
                        "bbox": {},
                        "translate": True,
                    }
                ],
            }
        ],
    }

    def fake_translate(text: str) -> str:
        if text == "2. La conséquence de l’établissement d’une ZCE négative côté P, positive côté N :":
            raise requests.exceptions.Timeout()
        mapping = {
            "2. La conséquence de l’établissement d’une ZCE négative côté P": "2. The consequence of establishing a negative SCR on the P side",
            "positive côté N": "positive on the N side",
        }
        return mapping[text]

    report = build_translation_preview_report(segments_report, fake_translate)

    assert report["pages"][0]["regions"][0]["status"] == "translated"
    assert report["pages"][0]["regions"][0]["translated_text"] == (
        "2. The consequence of the establishment of a negative SCR on the P side "
        "and a positive SCR on the N side:"
    )


def test_build_translation_preview_report_uses_outline_sentence_fallback_on_timeout() -> None:
    segments_report = {
        "selected_pages": [22],
        "pages": [
            {
                "page_number": 22,
                "regions": [
                    {
                        "source_text": "Nous avons décrits phénoménologiquement ce qui se passe, étape par étape:",
                        "role": "content",
                        "bbox": {},
                        "translate": True,
                    }
                ],
            }
        ],
    }

    def always_timeout(_: str) -> str:
        raise requests.exceptions.Timeout()

    report = build_translation_preview_report(segments_report, always_timeout)

    assert report["pages"][0]["regions"][0]["status"] == "translated"
    assert report["pages"][0]["regions"][0]["translated_text"] == (
        "We have described phenomenologically what happens, step by step:"
    )


def test_build_translation_preview_report_uses_scientific_glossary_before_model() -> None:
    segments_report = {
        "selected_pages": [3],
        "pages": [
            {
                "page_number": 3,
                "regions": [
                    {"source_text": "Homojonction", "role": "content", "bbox": {}, "translate": True},
                    {"source_text": "Si type P", "role": "content", "bbox": {}, "translate": True},
                ],
            }
        ],
    }

    def should_not_run(_: str) -> str:
        raise AssertionError("model should not be called for glossary-backed terms")

    report = build_translation_preview_report(segments_report, should_not_run)

    assert report["pages"][0]["regions"][0]["translated_text"] == "Homojunction"
    assert report["pages"][0]["regions"][1]["translated_text"] == "P-type Si"


def test_build_replacement_plan_assigns_fit_risk_and_writes_files(tmp_path) -> None:
    translation_report = {
        "selected_pages": [10],
        "pages": [
            {
                "page_number": 10,
                "regions": [
                    {
                        "role": "content",
                        "source_text": "Bonjour",
                        "translated_text": "Hello",
                        "source_color": 0,
                        "source_color_mode": "uniform",
                        "bbox": {"x0": 10, "y0": 20, "x1": 130, "y1": 44},
                        "status": "translated",
                    },
                    {
                        "role": "slide_title",
                        "source_text": "Texte court",
                        "translated_text": "[TIMEOUT] Texte court",
                        "source_color": 16777215,
                        "source_color_mode": "uniform",
                        "bbox": {"x0": 5, "y0": 6, "x1": 7, "y1": 8},
                        "status": "timeout",
                    },
                ],
            }
        ],
    }

    plan = build_replacement_plan(translation_report)
    text = replacement_plan_to_text(plan)
    json_path, text_path = write_replacement_plan(plan, tmp_path, "replacement_plan")

    assert plan["total_replacements"] == 2
    assert plan["pages"][0]["replacements"][0]["fit_risk"] == "low"
    assert plan["pages"][0]["replacements"][0]["source_color"] == 0
    assert plan["pages"][0]["replacements"][0]["translated_lines"] is None
    assert plan["pages"][0]["replacements"][0]["fit_diagnostics"]["flags"] == []
    assert plan["pages"][0]["replacements"][0]["apply_strategy"] == "native_overlay_candidate"
    assert plan["pages"][0]["replacements"][1]["fit_risk"] == "high"
    assert plan["fit_risk_summary"] == {"low": 1, "high": 1}
    assert plan["apply_strategy_summary"] == {
        "native_overlay_candidate": 1,
        "native_review_required": 1,
    }
    assert "Page 10: replacements=2" in text
    assert "Apply strategies:" in text
    assert json_path.exists()
    assert text_path.exists()


def test_build_replacement_plan_allows_medium_risk_for_translated_slide_titles() -> None:
    translation_report = {
        "selected_pages": [120],
        "pages": [
            {
                "page_number": 120,
                "regions": [
                    {
                        "role": "slide_title",
                        "source_text": "JONCTION P/N EN DYNAMIQUE - 2",
                        "translated_text": "JUNCTION P/N UNDER DYNAMIC CONDITIONS - 2",
                        "source_color": 16777215,
                        "source_color_mode": "uniform",
                        "bbox": {"x0": 1, "y0": 2, "x1": 250, "y1": 24},
                        "status": "translated",
                    }
                ],
            }
        ],
    }

    plan = build_replacement_plan(translation_report)

    assert plan["pages"][0]["replacements"][0]["fit_risk"] == "medium"


def test_build_replacement_plan_uses_line_geometry_for_narrow_regions() -> None:
    translation_report = {
        "selected_pages": [2],
        "pages": [
            {
                "page_number": 2,
                "regions": [
                    {
                        "role": "content",
                        "source_text": "intitulé",
                        "translated_text": "translated column heading",
                        "source_color": 0,
                        "source_color_mode": "uniform",
                        "bbox": {"x0": 162.5, "y0": 188.0, "x1": 183.5, "y1": 195.0},
                        "translated_lines": [
                            {
                                "text": "translated column heading",
                                "bbox": {"x0": 162.5, "y0": 188.0, "x1": 183.5, "y1": 195.0},
                                "source_font": "Arial",
                                "source_font_size": 7.0,
                                "source_color": 0,
                                "source_color_mode": "uniform",
                            }
                        ],
                        "status": "translated",
                    }
                ],
            }
        ],
    }

    plan = build_replacement_plan(translation_report)
    replacement = plan["pages"][0]["replacements"][0]

    assert replacement["fit_risk"] == "high"
    assert replacement["apply_strategy"] == "native_review_required"
    assert "severe_line_overflow" in replacement["fit_diagnostics"]["flags"]


def test_render_overlay_prototype_skips_review_required_replacements(tmp_path) -> None:
    source_pdf = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "Bonjour", fontsize=12)
    doc.save(source_pdf)
    doc.close()

    replacement_plan = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "replacements": [
                    {
                        "bbox": {"x0": 10, "y0": 20, "x1": 150, "y1": 80},
                        "translated_text": "Hello",
                        "status": "translated",
                        "fit_risk": "low",
                    },
                    {
                        "bbox": {"x0": 10, "y0": 90, "x1": 150, "y1": 140},
                        "translated_text": "Ignored",
                        "status": "translated",
                        "fit_risk": "medium",
                        "apply_strategy": "native_review_required",
                    },
                ],
            }
        ],
    }

    pdf_path, summary = render_overlay_prototype(
        pdf_path=source_pdf,
        replacement_plan=replacement_plan,
        output_dir=tmp_path,
        stem="overlay_proto",
    )
    summary_path = write_overlay_prototype_summary(summary, tmp_path, "overlay_proto")
    text = overlay_prototype_summary_to_text(summary)

    assert pdf_path.exists()
    assert summary["total_applied_replacements"] == 1
    assert "Total applied replacements: 1" in text
    assert summary_path.exists()
