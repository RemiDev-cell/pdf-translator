import json
from pathlib import Path

import fitz
import pytest
import typer
from typer.testing import CliRunner

from pdf_translator import cli
from pdf_translator.cli import _parse_pages_arg, _parse_pages_or_all, _resolve_pages_arg


def test_parse_pages_arg_accepts_ranges_and_deduplicates() -> None:
    assert _parse_pages_arg("1-3, 3, 5") == [1, 2, 3, 5]


def test_parse_pages_arg_rejects_descending_ranges() -> None:
    with pytest.raises(typer.BadParameter):
        _parse_pages_arg("4-2")


def test_parse_pages_arg_rejects_zero_page() -> None:
    with pytest.raises(typer.BadParameter):
        _parse_pages_arg("0")


def test_parse_pages_or_all_accepts_all_keyword() -> None:
    assert _parse_pages_or_all("all") is None
    assert _parse_pages_or_all("ALL") is None
    assert _parse_pages_or_all("1-2") == [1, 2]


def test_resolve_pages_arg_expands_all_from_document_ir() -> None:
    document_ir = {
        "pages": [
            {"page_number": 1},
            {"page_number": 2},
        ]
    }

    assert _resolve_pages_arg("all", document_ir) == [1, 2]
    assert _resolve_pages_arg("2", document_ir) == [2]


def test_ocr_inplace_preview_command_accepts_plan_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 40), "OCR source page")
    page.draw_rect(fitz.Rect(40, 80, 160, 130), color=(0, 0, 0), fill=(0, 0, 0), width=0)
    doc.save(pdf_path)
    doc.close()

    plan = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "replacements": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "apply_strategy": "ocr_overlay_candidate",
                        "status": "translated",
                        "fit_risk": "low",
                        "overflow_ratio": 1.0,
                        "fit_diagnostics": {"flags": []},
                        "bbox": {"x0": 40, "y0": 80, "x1": 160, "y1": 130},
                        "source_text": "Etiquette",
                        "translated_text": "Label",
                    }
                ],
            }
        ],
    }
    plan_json = tmp_path / "plan.json"
    plan_json.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(cli.settings, "debug_dir", tmp_path)

    result = CliRunner().invoke(
        cli.app,
        [
            "ocr-inplace-preview",
            str(pdf_path),
            "--plan-json",
            str(plan_json),
        ],
    )

    assert result.exit_code == 0
    assert "Total OCR in-place applied: 1" in result.output
    assert (tmp_path / "source_ocr_inplace_prototype.pdf").exists()
    assert (tmp_path / "source_ocr_inplace_prototype.txt").exists()
