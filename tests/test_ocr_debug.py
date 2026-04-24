from pathlib import Path
import json

import fitz

from pdf_translator.extract.pymupdf_extract import extract_document
from pdf_translator.ocr.debug import (
    build_fusion_replacement_plan,
    build_fusion_translation_preview_report,
    build_native_ocr_fusion_plan,
    build_native_ocr_fusion_report,
    build_ocr_overlay_strategy_report,
    build_ocr_review_report,
    fusion_replacement_plan_to_text,
    fusion_overlay_diagnostics_summary_to_text,
    fusion_translation_preview_report_to_text,
    native_ocr_fusion_plan_to_text,
    native_ocr_fusion_report_to_text,
    ocr_overlay_strategy_report_to_text,
    ocr_review_report_to_text,
    render_fusion_overlay_diagnostics,
    run_ocr_debug_pipeline,
    write_fusion_replacement_plan,
    write_fusion_overlay_diagnostics_summary,
    write_fusion_translation_preview_report,
    write_native_ocr_fusion_plan,
    write_native_ocr_fusion_report,
    write_ocr_candidate_report,
    write_ocr_overlay_strategy_report,
    write_ocr_review_report,
)
from pdf_translator.qa.checks import annotate_repeated_blocks
from pdf_translator.routing import build_ocr_candidate_report


def test_run_ocr_debug_pipeline_writes_manifest_pngs_and_mock_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ocr-source.pdf"
    image_path = tmp_path / "sample.png"

    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 30, 30), 0)
    pixmap.clear_with(0x00FF00)
    pixmap.save(image_path)

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 30), "Texte natif")
    page.insert_image(fitz.Rect(40, 50, 160, 170), filename=str(image_path))
    doc.save(pdf_path)
    doc.close()

    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    report = build_ocr_candidate_report(document_ir)

    json_path, text_path = write_ocr_candidate_report(report, tmp_path, 'ocr_report')
    manifest_path, image_paths = run_ocr_debug_pipeline(pdf_path, report, tmp_path, 'ocr_report', backend='mock')

    assert json_path.exists()
    assert text_path.exists()
    assert manifest_path.exists()
    assert len(image_paths) == 1
    assert image_paths[0].exists()

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['total_candidates'] == 1
    assert manifest['pages'][0]['candidates'][0]['pixel_width'] > 0
    assert manifest['pages'][0]['candidates'][0]['pixel_height'] > 0
    assert manifest['pages'][0]['candidates'][0]['ocr_backend'] == 'mock'
    assert manifest['pages'][0]['candidates'][0]['ocr_status'] == 'ok'
    assert '[MOCK OCR]' in manifest['pages'][0]['candidates'][0]['ocr_text']



def test_build_ocr_review_report_summarizes_manifest(tmp_path: Path) -> None:
    manifest = {
        "source_path": "data/input/sample.pdf",
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "route": "native_plus_ocr_candidates",
                "candidates": [
                    {
                        "candidate_index": 0,
                        "ocr_backend": "tesseract",
                        "ocr_status": "ok",
                        "ocr_text": "Bonjour ceci est un texte OCR relativement long pour etre utilisable.",
                        "ocr_detail": "tesseract cli output",
                        "image_path": "data/debug/sample.png",
                    },
                    {
                        "candidate_index": 1,
                        "ocr_backend": "tesseract",
                        "ocr_status": "unavailable",
                        "ocr_text": "",
                        "ocr_detail": "No OCR backend available",
                        "image_path": "data/debug/sample2.png",
                    },
                ],
            }
        ],
    }

    report = build_ocr_review_report(manifest)
    text = ocr_review_report_to_text(report)
    json_path, text_path = write_ocr_review_report(report, tmp_path, 'ocr_review')

    assert report['total_regions'] == 2
    assert report['status_summary'] == {'ok': 1, 'unavailable': 1}
    assert report['quality_summary']['unavailable'] == 1
    assert report['pages'][0]['regions'][0]['quality'] in {'usable', 'review'}
    assert 'Status summary:' in text
    assert 'OCR0 [ok/' in text
    assert json_path.exists()
    assert text_path.exists()



def test_build_native_ocr_fusion_report_combines_native_and_ocr_views(tmp_path: Path) -> None:
    overlay_ready_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "candidates": [
                    {
                        "block_index": 2,
                        "role": "content",
                        "line_count": 2,
                        "text": "Bloc natif principal avec assez de texte pour la revue.",
                    }
                ],
            }
        ],
    }
    ocr_review_report = {
        "pages": [
            {
                "page_number": 1,
                "route": "native_plus_ocr_candidates",
                "regions": [
                    {
                        "candidate_index": 0,
                        "ocr_status": "ok",
                        "quality": "usable",
                        "ocr_backend": "tesseract",
                        "word_count": 12,
                        "preview": "Texte OCR de la zone image pour comparaison.",
                    }
                ],
            }
        ]
    }

    report = build_native_ocr_fusion_report(overlay_ready_report, ocr_review_report)
    text = native_ocr_fusion_report_to_text(report)
    json_path, text_path = write_native_ocr_fusion_report(report, tmp_path, 'fusion_review')

    assert report['page_count'] == 1
    assert report['total_native_regions'] == 1
    assert report['total_ocr_regions'] == 1
    assert report['pages'][0]['native_regions'][0]['block_index'] == 2
    assert report['pages'][0]['ocr_regions'][0]['ocr_backend'] == 'tesseract'
    assert 'native B2' in text
    assert 'ocr OCR0 [ok/usable]' in text
    assert json_path.exists()
    assert text_path.exists()



def test_build_native_ocr_fusion_plan_marks_translatable_segments(tmp_path: Path) -> None:
    overlay_ready_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "candidates": [
                    {
                        "block_index": 2,
                        "role": "content",
                        "line_count": 2,
                        "text": "Bloc natif principal.",
                    }
                ],
            }
        ],
    }
    ocr_review_report = {
        "pages": [
            {
                "page_number": 1,
                "route": "native_plus_ocr_candidates",
                "regions": [
                    {
                        "candidate_index": 0,
                        "ocr_status": "ok",
                        "quality": "usable",
                        "ocr_backend": "tesseract",
                        "word_count": 12,
                        "preview": "Texte OCR exploitable.",
                    },
                    {
                        "candidate_index": 1,
                        "ocr_status": "unavailable",
                        "quality": "unavailable",
                        "ocr_backend": "tesseract",
                        "word_count": 0,
                        "preview": "",
                    },
                ],
            }
        ]
    }

    plan = build_native_ocr_fusion_plan(overlay_ready_report, ocr_review_report)
    text = native_ocr_fusion_plan_to_text(plan)
    json_path, text_path = write_native_ocr_fusion_plan(plan, tmp_path, 'fusion_plan')

    assert plan['total_segments'] == 3
    assert plan['translatable_segments'] == 2
    assert plan['pages'][0]['segments'][0]['source_kind'] == 'native'
    assert plan['pages'][0]['segments'][1]['source_kind'] == 'ocr'
    assert plan['pages'][0]['segments'][1]['translate'] is True
    assert plan['pages'][0]['segments'][2]['translate'] is False
    assert 'P1O0 [ocr/translate]' in text
    assert 'P1O1 [ocr/skip]' in text
    assert json_path.exists()
    assert text_path.exists()



def test_build_fusion_translation_preview_report_translates_mix_of_native_and_ocr_segments(tmp_path: Path) -> None:
    fusion_plan = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "route": "native_plus_ocr_candidates",
                "segments": [
                    {
                        "segment_id": "P1N0",
                        "source_kind": "native",
                        "source_ref": "block:0",
                        "text": "Bonjour le monde",
                        "translate": True,
                    },
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "source_ref": "ocr:0",
                        "text": "Version 1.2.3",
                        "translate": True,
                    },
                    {
                        "segment_id": "P1O1",
                        "source_kind": "ocr",
                        "source_ref": "ocr:1",
                        "text": "",
                        "translate": False,
                    },
                ],
            }
        ],
    }

    def fake_translate(text: str) -> str:
        return f"EN:{text}"

    report = build_fusion_translation_preview_report(fusion_plan, fake_translate)
    text = fusion_translation_preview_report_to_text(report)
    json_path, text_path = write_fusion_translation_preview_report(report, tmp_path, 'fusion_translation_preview')

    assert report['total_segments'] == 3
    assert report['translated_segments'] == 2
    assert report['pages'][0]['segments'][0]['translated_text'] == 'EN:Bonjour le monde'
    assert '[[VERSION_1]]' not in report['pages'][0]['segments'][1]['translated_text']
    assert report['pages'][0]['segments'][2]['status'] == 'skipped'
    assert 'P1N0 [native/translated]' in text
    assert 'P1O1 [ocr/skipped]' in text
    assert json_path.exists()
    assert text_path.exists()


def test_build_fusion_replacement_plan_distinguishes_native_and_ocr_strategies(tmp_path: Path) -> None:
    preview_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "route": "native_plus_ocr_candidates",
                "segments": [
                    {
                        "segment_id": "P1N0",
                        "source_kind": "native",
                        "source_ref": "block:0",
                        "role": "content",
                        "status": "translated",
                        "source_text": "Bonjour le monde",
                        "translated_text": "Hello world",
                    },
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "source_ref": "ocr:0",
                        "role": "ocr_region",
                        "status": "translated",
                        "source_text": "Texte OCR",
                        "translated_text": "OCR text",
                    },
                ],
            }
        ],
    }

    plan = build_fusion_replacement_plan(preview_report)
    text = fusion_replacement_plan_to_text(plan)
    json_path, text_path = write_fusion_replacement_plan(plan, tmp_path, "fusion_replacement_plan")

    assert plan["total_replacements"] == 2
    assert plan["apply_strategy_summary"] == {
        "native_overlay_candidate": 1,
        "ocr_overlay_pending": 1,
    }
    assert plan["pages"][0]["replacements"][0]["fit_risk"] == "low"
    assert plan["pages"][0]["replacements"][1]["fit_risk"] == "review"
    assert "P1N0 [native/translated]" in text
    assert "strategy=ocr_overlay_pending" in text
    assert json_path.exists()
    assert text_path.exists()


def test_render_fusion_overlay_diagnostics_writes_pdf_png_and_summary(tmp_path: Path) -> None:
    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=240)
    page.insert_text((24, 42), "Bonjour natif")
    page.draw_rect(fitz.Rect(40, 90, 200, 170), color=(0, 0, 0), width=1)
    doc.save(pdf_path)
    doc.close()

    plan = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "replacements": [
                    {
                        "segment_id": "P1N0",
                        "source_kind": "native",
                        "apply_strategy": "native_overlay_candidate",
                        "status": "translated",
                        "fit_risk": "low",
                        "bbox": {"x0": 20, "y0": 26, "x1": 130, "y1": 54},
                        "translated_text": "Native hello",
                    },
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "apply_strategy": "ocr_overlay_pending",
                        "status": "translated",
                        "fit_risk": "review",
                        "bbox": {"x0": 40, "y0": 90, "x1": 200, "y1": 170},
                        "translated_text": "OCR translated text waiting for image overlay.",
                    },
                ],
            }
        ],
    }

    pdf_output_path, summary, image_paths = render_fusion_overlay_diagnostics(
        pdf_path=pdf_path,
        fusion_replacement_plan=plan,
        output_dir=tmp_path,
        stem="mixed_overlay",
    )
    summary_path = write_fusion_overlay_diagnostics_summary(summary, tmp_path, "mixed_overlay")
    text = fusion_overlay_diagnostics_summary_to_text(summary)

    assert pdf_output_path.exists()
    assert len(image_paths) == 1
    assert image_paths[0].exists()
    assert summary_path.exists()
    assert summary["total_native_applied"] == 1
    assert summary["total_ocr_annotated"] == 1
    assert "Total OCR annotated: 1" in text


def test_build_ocr_overlay_strategy_report_recommends_by_size_and_status(tmp_path: Path) -> None:
    plan = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "route": "native_plus_ocr_candidates",
                "replacements": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "source_ref": "ocr:0",
                        "status": "translated",
                        "fit_risk": "review",
                        "overflow_ratio": 3.2,
                        "bbox": {"x0": 10, "y0": 20, "x1": 110, "y1": 90},
                        "translated_text": "This OCR translation is long enough that it should stay as a side annotation for review.",
                    },
                    {
                        "segment_id": "P1O1",
                        "source_kind": "ocr",
                        "source_ref": "ocr:1",
                        "status": "translated",
                        "fit_risk": "review",
                        "overflow_ratio": 1.0,
                        "bbox": {"x0": 10, "y0": 120, "x1": 180, "y1": 150},
                        "translated_text": "Short label",
                    },
                    {
                        "segment_id": "P1N0",
                        "source_kind": "native",
                        "status": "translated",
                        "translated_text": "Native text",
                    },
                ],
            }
        ],
    }

    report = build_ocr_overlay_strategy_report(plan)
    text = ocr_overlay_strategy_report_to_text(report)
    json_path, text_path = write_ocr_overlay_strategy_report(report, tmp_path, "ocr_strategy")

    assert report["total_ocr_replacements"] == 2
    assert report["recommendation_summary"] == {
        "side_annotation_recommended": 1,
        "image_overlay_candidate": 1,
    }
    assert report["pages"][0]["decisions"][0]["recommendation"] == "side_annotation_recommended"
    assert report["pages"][0]["decisions"][1]["recommendation"] == "image_overlay_candidate"
    assert "P1O0 recommendation=side_annotation_recommended" in text
    assert json_path.exists()
    assert text_path.exists()
