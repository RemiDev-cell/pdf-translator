from pathlib import Path

import pytest

from scripts.run_ocr_inplace_probe_matrix import (
    ExpectedProbe,
    _assert_recomposition_review,
    _resolve_probe_source,
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
