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
                        "page_zone_flags": ["review_candidate_content_role_in_margin"],
                        "reading_flow": {
                            "reading_order_index": 0,
                            "classification": "isolated_block",
                            "flags": [],
                        },
                        "layout_group": {
                            "group_id": "P10G0",
                            "group_type": "heading_group",
                        },
                        "lines": [
                            {"text": "line 1", "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4}},
                            {"text": "line 2", "bbox": {"x0": 5, "y0": 6, "x1": 7, "y1": 8}},
                        ],
                    }
                ],
                "reading_flow_review_items": [
                    {
                        "page_number": 10,
                        "block_index": 98,
                        "role": "slide_title",
                        "classification": "isolated_block",
                        "flags": ["review_large_vertical_gap_between_candidates"],
                        "text_preview": "Useful translated block",
                    }
                ],
                "layout_group_review_items": [
                    {
                        "page_number": 10,
                        "group_id": "P10G0",
                        "group_type": "heading_group",
                        "candidate_count": 1,
                        "block_indices": [98],
                        "roles": ["slide_title"],
                        "text_preview": "Useful translated block",
                    }
                ],
                "page_zone_review_items": [
                    {
                        "page_number": 10,
                        "item_type": "candidate",
                        "block_index": 98,
                        "role": "slide_title",
                        "page_zone": {"vertical": "header_zone", "horizontal": "left_margin"},
                        "page_zone_flags": ["review_candidate_content_role_in_margin"],
                        "line_count": 2,
                        "text_preview": "Useful translated block",
                        "selection_reason": "selected_as_title",
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
    assert "page_zone_flags" not in report["pages"][0]["regions"][0]
    assert "page_zone_review_items" not in report["pages"][0]["regions"][0]
    assert "reading_flow" not in report["pages"][0]["regions"][0]
    assert "reading_flow_review_items" not in report["pages"][0]["regions"][0]
    assert "layout_group" not in report["pages"][0]["regions"][0]
    assert "layout_group_review_items" not in report["pages"][0]["regions"][0]
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


def _single_region_translation_report(
    page_number: int = 1,
    translated_text: str = "Hello",
    bbox=None,
) -> dict:
    return {
        "selected_pages": [page_number],
        "pages": [
            {
                "page_number": page_number,
                "regions": [
                    {
                        "role": "content",
                        "source_text": "Bonjour",
                        "translated_text": translated_text,
                        "source_color": 0,
                        "source_color_mode": "uniform",
                        "bbox": bbox or {"x0": 10, "y0": 20, "x1": 150, "y1": 80},
                        "status": "translated",
                    }
                ],
            }
        ],
    }


def _overlay_ready_report_for_status(status: str, page_number: int = 1) -> dict:
    return {
        "selected_pages": [page_number],
        "pages": [
            {
                "page_number": page_number,
                "overlay_readiness": {
                    "status": status,
                    "reason_summary": {"reason": 1} if status != "ready" else {},
                    "severity_summary": {status: 1} if status != "ready" else {},
                    "review_item_count": 1 if status != "ready" else 0,
                    "soft_review_item_count": 1 if status == "soft_review" else 0,
                    "hard_review_item_count": 1 if status == "hard_review" else 0,
                    "candidate_block_count": 1,
                    "excluded_block_count": 0,
                },
            }
        ],
    }


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
    assert plan["page_apply_policy_summary"] == {"apply_overlay": 1}
    assert plan["pages"][0]["overlay_readiness_status"] == "ready"
    assert plan["pages"][0]["page_apply_policy"] == "apply_overlay"
    assert "Page 10: replacements=2 policy=apply_overlay readiness=ready" in text
    assert "Apply strategies:" in text
    assert "Page apply policies:" in text
    assert json_path.exists()
    assert text_path.exists()


def test_build_replacement_plan_uses_soft_review_page_policy() -> None:
    plan = build_replacement_plan(
        _single_region_translation_report(page_number=3),
        overlay_ready_report=_overlay_ready_report_for_status("soft_review", page_number=3),
    )

    assert plan["page_apply_policy_summary"] == {"apply_overlay_with_soft_review": 1}
    assert plan["pages"][0]["overlay_readiness_status"] == "soft_review"
    assert plan["pages"][0]["overlay_readiness_reason_summary"] == {"reason": 1}
    assert plan["pages"][0]["overlay_readiness_severity_summary"] == {"soft_review": 1}
    assert plan["pages"][0]["page_apply_policy"] == "apply_overlay_with_soft_review"


def test_build_replacement_plan_uses_skip_policies_for_hard_review_and_blocked() -> None:
    for status, expected_policy in (
        ("hard_review", "skip_overlay_hard_review"),
        ("blocked", "skip_overlay_blocked"),
    ):
        plan = build_replacement_plan(
            _single_region_translation_report(),
            overlay_ready_report=_overlay_ready_report_for_status(status),
        )

        assert plan["page_apply_policy_summary"] == {expected_policy: 1}
        assert plan["pages"][0]["overlay_readiness_status"] == status
        assert plan["pages"][0]["page_apply_policy"] == expected_policy


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
    assert summary["total_skipped_replacements"] == 1
    assert summary["page_apply_policy_summary"] == {"apply_overlay": 1}
    assert summary["total_skipped_replacements_due_to_page_policy"] == 0
    assert summary["render_decision_summary"] == {
        "applied": 1,
        "skipped_apply_strategy": 1,
    }
    assert summary["pages"][0]["render_decision_summary"] == {
        "applied": 1,
        "skipped_apply_strategy": 1,
    }
    assert [
        item["render_decision"]
        for item in summary["pages"][0]["render_review_items"]
    ] == ["applied", "skipped_apply_strategy"]
    assert "Total applied replacements: 1" in text
    assert "Page apply policies:" in text
    assert "Render decisions:" in text
    assert "decision=skipped_apply_strategy" in text
    assert summary_path.exists()


def test_render_overlay_prototype_explains_status_skips(tmp_path) -> None:
    source_pdf = tmp_path / "source-status.pdf"
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
                "page_apply_policy": "apply_overlay",
                "replacements": [
                    {
                        "replacement_index": 1,
                        "role": "content",
                        "bbox": {"x0": 10, "y0": 20, "x1": 150, "y1": 80},
                        "translated_text": "[TIMEOUT] Bonjour",
                        "status": "timeout",
                        "fit_risk": "low",
                        "apply_strategy": "native_overlay_candidate",
                    },
                ],
            }
        ],
    }

    _, summary = render_overlay_prototype(
        pdf_path=source_pdf,
        replacement_plan=replacement_plan,
        output_dir=tmp_path,
        stem="overlay_proto_status",
    )

    assert summary["total_applied_replacements"] == 0
    assert summary["total_skipped_replacements"] == 1
    assert summary["render_decision_summary"] == {"skipped_status": 1}
    assert summary["pages"][0]["render_review_items"][0] == {
        "replacement_index": 1,
        "role": "content",
        "status": "timeout",
        "fit_risk": "low",
        "apply_strategy": "native_overlay_candidate",
        "render_decision": "skipped_status",
        "text_preview": "[TIMEOUT] Bonjour",
    }


def test_render_overlay_prototype_applies_soft_review_pages(tmp_path) -> None:
    source_pdf = tmp_path / "source-soft.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "Bonjour", fontsize=12)
    doc.save(source_pdf)
    doc.close()

    replacement_plan = build_replacement_plan(
        _single_region_translation_report(),
        overlay_ready_report=_overlay_ready_report_for_status("soft_review"),
    )

    _, summary = render_overlay_prototype(
        pdf_path=source_pdf,
        replacement_plan=replacement_plan,
        output_dir=tmp_path,
        stem="overlay_proto_soft",
    )

    assert summary["page_apply_policy_summary"] == {"apply_overlay_with_soft_review": 1}
    assert summary["pages"][0]["page_apply_policy"] == "apply_overlay_with_soft_review"
    assert summary["total_considered_replacements"] == 1
    assert summary["total_applied_replacements"] == 1
    assert summary["total_skipped_replacements"] == 0
    assert summary["total_skipped_replacements_due_to_page_policy"] == 0
    assert summary["render_decision_summary"] == {"applied": 1}
    assert summary["pages"][0]["render_review_items"][0]["render_decision"] == "applied"


def test_render_overlay_prototype_skips_hard_review_and_blocked_pages(tmp_path) -> None:
    source_pdf = tmp_path / "source-skips.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "Bonjour", fontsize=12)
    doc.save(source_pdf)
    doc.close()

    for status, expected_policy in (
        ("hard_review", "skip_overlay_hard_review"),
        ("blocked", "skip_overlay_blocked"),
    ):
        replacement_plan = build_replacement_plan(
            _single_region_translation_report(),
            overlay_ready_report=_overlay_ready_report_for_status(status),
        )

        _, summary = render_overlay_prototype(
            pdf_path=source_pdf,
            replacement_plan=replacement_plan,
            output_dir=tmp_path,
            stem=f"overlay_proto_{status}",
        )

        assert summary["page_apply_policy_summary"] == {expected_policy: 1}
        assert summary["pages"][0]["page_apply_policy"] == expected_policy
        assert summary["total_considered_replacements"] == 1
        assert summary["total_applied_replacements"] == 0
        assert summary["total_skipped_replacements"] == 1
        assert summary["total_skipped_replacements_due_to_page_policy"] == 1
        assert summary["render_decision_summary"] == {"skipped_page_policy": 1}
        assert summary["pages"][0]["skipped_replacements_due_to_page_policy"] == 1
        assert summary["pages"][0]["render_review_items"][0]["render_decision"] == "skipped_page_policy"


def test_render_overlay_prototype_keeps_fit_risk_gate_on_ready_pages(tmp_path) -> None:
    source_pdf = tmp_path / "source-fit-risk.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "Bonjour", fontsize=12)
    doc.save(source_pdf)
    doc.close()

    replacement_plan = build_replacement_plan(
        _single_region_translation_report(
            translated_text="A very long translated phrase that cannot fit",
            bbox={"x0": 10, "y0": 20, "x1": 16, "y1": 24},
        ),
        overlay_ready_report=_overlay_ready_report_for_status("ready"),
    )
    replacement_plan["pages"][0]["replacements"][0]["apply_strategy"] = "native_overlay_candidate"

    _, summary = render_overlay_prototype(
        pdf_path=source_pdf,
        replacement_plan=replacement_plan,
        output_dir=tmp_path,
        stem="overlay_proto_fit_risk",
    )

    assert replacement_plan["pages"][0]["page_apply_policy"] == "apply_overlay"
    assert replacement_plan["pages"][0]["replacements"][0]["fit_risk"] == "high"
    assert summary["total_considered_replacements"] == 1
    assert summary["total_applied_replacements"] == 0
    assert summary["total_skipped_replacements"] == 1
    assert summary["total_skipped_replacements_due_to_page_policy"] == 0
    assert summary["render_decision_summary"] == {"skipped_fit_risk": 1}
    assert summary["pages"][0]["render_review_items"][0]["render_decision"] == "skipped_fit_risk"
