from pathlib import Path

import fitz

from pdf_translator.pipeline import run_document_preview, run_native_overlay_preview


def test_run_native_overlay_preview_writes_artifact_chain(tmp_path: Path) -> None:
    pdf_path = tmp_path / "native.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=180)
    page.insert_text((24, 36), "Bonjour le monde", fontsize=12)
    page.insert_text((24, 58), "Ceci est une phrase scientifique.", fontsize=12)
    doc.save(pdf_path)
    doc.close()

    result = run_native_overlay_preview(
        pdf_path=pdf_path,
        output_dir=tmp_path,
        selected_pages=[1],
        translate_text_fn=lambda text: f"EN {text}",
        artifact_stem="native_chain",
    )

    paths = result["paths"]
    assert paths["overlay_ready_json"].exists()
    assert paths["pre_overlay_json"].exists()
    assert paths["translation_preview_json"].exists()
    assert paths["replacement_plan_json"].exists()
    assert paths["overlay_pdf"].exists()
    assert paths["overlay_summary_text"].exists()
    assert result["replacement_plan"]["total_replacements"] >= 1
    assert result["overlay_summary"]["total_considered_replacements"] >= 1


def test_run_document_preview_routes_native_pages_to_native_overlay(tmp_path: Path) -> None:
    pdf_path = tmp_path / "native-routed.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=180)
    page.insert_text((24, 36), "Bonjour le monde", fontsize=12)
    doc.save(pdf_path)
    doc.close()

    result = run_document_preview(
        pdf_path=pdf_path,
        output_dir=tmp_path,
        selected_pages=[1],
        translate_text_fn=lambda text: f"EN {text}",
        artifact_stem="routed_native",
    )

    assert result["preview_mode"] == "native_overlay"
    assert result["paths"]["routing_json"].exists()
    assert result["preview_result"]["paths"]["overlay_pdf"].exists()
    assert result["routing_report"]["route_summary"] == {"native_only": 1}


def test_run_document_preview_routes_image_pages_to_fusion(tmp_path: Path) -> None:
    pdf_path = tmp_path / "fusion-routed.pdf"
    image_path = tmp_path / "sample.png"

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 24, 24), 0)
    pixmap.clear_with(0x00AAFF)
    pixmap.save(image_path)

    doc = fitz.open()
    page = doc.new_page(width=240, height=240)
    page.insert_text((24, 36), "Texte natif", fontsize=12)
    page.insert_image(fitz.Rect(60, 80, 180, 190), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    result = run_document_preview(
        pdf_path=pdf_path,
        output_dir=tmp_path,
        selected_pages=[1],
        translate_text_fn=lambda text: f"EN {text}",
        backend="mock",
        artifact_stem="routed_fusion",
    )

    assert result["preview_mode"] == "native_ocr_fusion"
    assert result["paths"]["routing_text"].exists()
    assert result["preview_result"]["paths"]["diagnostics_pdf"].exists()
    assert result["routing_report"]["route_summary"] == {"native_plus_ocr_candidates": 1}
