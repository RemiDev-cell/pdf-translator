from pathlib import Path

import pytest

from scripts.run_ocr_inplace_probe_matrix import (
    EXPECTED_PROBES,
    ExpectedProbe,
    _assert_ocr_background_metrics,
    _assert_final_like_review,
    _assert_recomposition_review,
    _resolve_probe_source,
    _should_render_final_like,
)


def test_probe_matrix_requires_real_sources_when_requested(tmp_path: Path) -> None:
    probe = ExpectedProbe(
        name="missing_real_probe",
        plan_path=tmp_path / "plan.json",
        source_pdf=tmp_path / "missing.pdf",
        expected_decisions={},
    )

    with pytest.raises(FileNotFoundError, match="--require-real-sources"):
        _resolve_probe_source(
            probe,
            {"pages": []},
            tmp_path,
            require_real_sources=True,
        )


def test_probe_matrix_rejects_unexpected_outside_recomposition_changes() -> None:
    summary = {
        "render_decision_summary": {"applied_ocr_inplace": 1},
        "pages": [
            {
                "page_number": 1,
                "render_decision_summary": {"applied_ocr_inplace": 1},
                "recomposition_metrics": {
                    "recomposition_verdict": "unexpected_outside_changes",
                    "changed_in_source_replacement_zone_count": 20,
                    "changed_outside_allowed_zone_ratio": 0.2,
                },
                "render_review_items": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "render_decision": "applied_ocr_inplace",
                        "render_zones": [{"zone_type": "source_replacement_zone"}],
                    }
                ],
            }
        ],
    }

    errors = _assert_recomposition_review("probe", summary)

    assert any("unexpected outside changes" in error for error in errors)


def test_probe_matrix_requires_side_annotations_to_stay_out_of_source_replacement() -> None:
    summary = {
        "render_decision_summary": {"annotated_ocr_side": 1},
        "pages": [
            {
                "page_number": 1,
                "render_decision_summary": {"annotated_ocr_side": 1},
                "recomposition_metrics": {
                    "recomposition_verdict": "expected_annotation_changes",
                    "changed_outside_allowed_zone_ratio": 0.0,
                },
                "render_review_items": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "render_decision": "annotated_ocr_side",
                        "render_zones": [{"zone_type": "source_replacement_zone"}],
                    }
                ],
            }
        ],
    }

    errors = _assert_recomposition_review("probe", summary)

    assert any("should not replace OCR source" in error for error in errors)


def test_probe_matrix_renders_final_like_only_for_applied_ocr_inplace() -> None:
    assert _should_render_final_like(
        {"render_decision_summary": {"applied_ocr_inplace": 1}}
    ) is True
    assert _should_render_final_like(
        {"render_decision_summary": {"annotated_ocr_side": 1}}
    ) is False
    assert _should_render_final_like(
        {"render_decision_summary": {"annotated_ocr_review": 1}}
    ) is False


def test_probe_matrix_includes_light_positive_ocr_probe() -> None:
    probe = next(
        probe for probe in EXPECTED_PROBES if probe.name == "04_mixed_light_ocr_image"
    )

    assert probe.source_pdf is not None
    assert probe.source_pdf.name == "04_mixed_light_ocr_image.pdf"
    assert probe.expected_decisions == {"applied_ocr_inplace": 1}
    assert probe.expected_appendix_pages == 0
    assert probe.generate_plan_if_missing is True
    assert probe.expected_ocr_background_luminance_min == 0.75
    assert probe.expected_ocr_background_dominant_ratio_min == 0.60
    assert probe.expected_ocr_background_full_clear is True


def test_probe_matrix_accepts_light_ocr_background_metrics() -> None:
    summary = {
        "pages": [
            {
                "render_review_items": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "render_decision": "applied_ocr_inplace",
                        "ocr_background_luminance": 0.91,
                        "ocr_background_dominant_ratio": 0.82,
                        "ocr_background_full_clear": True,
                    }
                ],
            }
        ],
    }

    errors = _assert_ocr_background_metrics(
        "probe",
        summary,
        luminance_min=0.75,
        dominant_ratio_min=0.60,
        full_clear=True,
    )

    assert errors == []


def test_probe_matrix_rejects_light_ocr_background_metric_regression() -> None:
    summary = {
        "pages": [
            {
                "render_review_items": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "render_decision": "applied_ocr_inplace",
                        "ocr_background_luminance": 0.22,
                        "ocr_background_dominant_ratio": 0.40,
                        "ocr_background_full_clear": False,
                    }
                ],
            }
        ],
    }

    errors = _assert_ocr_background_metrics(
        "probe",
        summary,
        luminance_min=0.75,
        dominant_ratio_min=0.60,
        full_clear=True,
    )

    assert any("background luminance" in error for error in errors)
    assert any("background dominant ratio" in error for error in errors)
    assert any("background full_clear=True" in error for error in errors)


def test_probe_matrix_accepts_clean_final_like_review() -> None:
    baseline_summary = {
        "render_decision_summary": {"applied_ocr_inplace": 1},
        "ocr_render_mode_summary": {"layout_tsv": 1},
        "ocr_readiness_summary": {"ready_for_image_overlay": 1},
    }
    final_like_summary = {
        "review_final_like": True,
        "ocr_inplace_review_markers": False,
        "render_decision_summary": {"applied_ocr_inplace": 1},
        "ocr_render_mode_summary": {"layout_tsv": 1},
        "ocr_readiness_summary": {"ready_for_image_overlay": 1},
        "pages": [
            {
                "page_number": 1,
                "render_decision_summary": {"applied_ocr_inplace": 1},
                "recomposition_metrics": {
                    "recomposition_verdict": "clean",
                    "changed_outside_allowed_zone_ratio": 0.0,
                },
                "render_review_items": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "render_decision": "applied_ocr_inplace",
                        "ocr_inplace_review_marker_drawn": False,
                    }
                ],
            }
        ],
    }

    errors = _assert_final_like_review(
        "probe",
        baseline_summary,
        final_like_summary,
    )

    assert errors == []


def test_probe_matrix_rejects_final_like_review_markers() -> None:
    baseline_summary = {
        "render_decision_summary": {"applied_ocr_inplace": 1},
        "ocr_render_mode_summary": {"layout_tsv": 1},
        "ocr_readiness_summary": {"ready_for_image_overlay": 1},
    }
    final_like_summary = {
        "review_final_like": True,
        "ocr_inplace_review_markers": True,
        "render_decision_summary": {"applied_ocr_inplace": 1},
        "ocr_render_mode_summary": {"layout_tsv": 1},
        "ocr_readiness_summary": {"ready_for_image_overlay": 1},
        "pages": [
            {
                "page_number": 1,
                "render_decision_summary": {"applied_ocr_inplace": 1},
                "recomposition_metrics": {
                    "recomposition_verdict": "clean",
                    "changed_outside_allowed_zone_ratio": 0.0,
                },
                "render_review_items": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "render_decision": "applied_ocr_inplace",
                        "ocr_inplace_review_marker_drawn": True,
                    }
                ],
            }
        ],
    }

    errors = _assert_final_like_review(
        "probe",
        baseline_summary,
        final_like_summary,
    )

    assert any("markers enabled" in error for error in errors)
    assert any("still has review marker" in error for error in errors)


def test_probe_matrix_rejects_dirty_final_like_recomposition() -> None:
    baseline_summary = {
        "render_decision_summary": {"applied_ocr_inplace": 1},
        "ocr_render_mode_summary": {"layout_tsv": 1},
        "ocr_readiness_summary": {"ready_for_image_overlay": 1},
    }
    final_like_summary = {
        "review_final_like": True,
        "ocr_inplace_review_markers": False,
        "render_decision_summary": {"applied_ocr_inplace": 1},
        "ocr_render_mode_summary": {"layout_tsv": 1},
        "ocr_readiness_summary": {"ready_for_image_overlay": 1},
        "pages": [
            {
                "page_number": 1,
                "render_decision_summary": {"applied_ocr_inplace": 1},
                "recomposition_metrics": {
                    "recomposition_verdict": "unexpected_outside_changes",
                    "changed_outside_allowed_zone_ratio": 0.2,
                },
                "render_review_items": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "render_decision": "applied_ocr_inplace",
                        "ocr_inplace_review_marker_drawn": False,
                    }
                ],
            }
        ],
    }

    errors = _assert_final_like_review(
        "probe",
        baseline_summary,
        final_like_summary,
    )

    assert any("verdict=unexpected_outside_changes" in error for error in errors)
    assert any("changed outside allowed zones" in error for error in errors)
