from pathlib import Path

import fitz

from pdf_translator.extract.pymupdf_extract import extract_document
from pdf_translator.ocr.experiment import run_ocr_experiment


def test_run_ocr_experiment_writes_full_artifact_chain_with_mock_backend(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ocr-experiment.pdf"
    image_path = tmp_path / "sample.png"

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 24, 24), 0)
    pixmap.clear_with(0x00AAFF)
    pixmap.save(image_path)

    doc = fitz.open()
    page = doc.new_page(width=220, height=220)
    page.insert_text((20, 30), "Texte natif")
    page.insert_image(fitz.Rect(50, 70, 170, 170), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    document = extract_document(pdf_path)
    result = run_ocr_experiment(
        pdf_path=pdf_path,
        document_ir=document.model_dump(),
        output_dir=tmp_path,
        translate_text_fn=lambda text: f"EN:{text}",
        backend="mock",
    )

    paths = result["paths"]
    assert paths["manifest"].exists()
    assert paths["fusion_translation_json"].exists()
    assert paths["fusion_replacement_json"].exists()
    assert paths["ocr_strategy_json"].exists()
    assert paths["diagnostics_pdf"].exists()
    assert len(paths["crop_paths"]) == 1
    assert len(paths["diagnostic_images"]) == 1
    assert result["ocr_review"]["status_summary"] == {"ok": 1}
    assert result["fusion_replacement_plan"]["total_replacements"] >= 2
