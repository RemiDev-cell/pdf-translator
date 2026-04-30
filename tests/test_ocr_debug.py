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
    build_ocr_page_translation_preview_report,
    build_ocr_review_report,
    fusion_replacement_plan_to_text,
    fusion_overlay_diagnostics_summary_to_text,
    fusion_translation_preview_report_to_text,
    native_ocr_fusion_plan_to_text,
    native_ocr_fusion_report_to_text,
    ocr_overlay_strategy_report_to_text,
    ocr_page_translation_preview_report_to_text,
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
    write_ocr_page_translation_preview_report,
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
    long_ocr_text = (
        "Bonjour ceci est un texte OCR relativement long pour etre utilisable. "
        "Cette seconde phrase depasse volontairement les limites habituelles "
        "du champ preview afin de verifier que le texte complet reste disponible "
        "pour les etapes de fusion et de traduction."
    )
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
                        "ocr_text": long_ocr_text,
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
    assert report['pages'][0]['regions'][0]['text'] == long_ocr_text
    assert 'Status summary:' in text
    assert 'OCR0 [ok/' in text
    assert json_path.exists()
    assert text_path.exists()



def test_build_native_ocr_fusion_report_combines_native_and_ocr_views(tmp_path: Path) -> None:
    full_ocr_text = "Texte OCR de la zone image pour comparaison. Phrase complete conservee pour traduction."
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
                        "text": full_ocr_text,
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
    assert report['pages'][0]['ocr_regions'][0]['text'] == full_ocr_text
    assert 'native B2' in text
    assert 'ocr OCR0 [ok/usable]' in text
    assert json_path.exists()
    assert text_path.exists()



def test_build_native_ocr_fusion_plan_marks_translatable_segments(tmp_path: Path) -> None:
    full_ocr_text = "Texte OCR exploitable avec une suite qui ne doit pas etre tronquee."
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
                        "text": full_ocr_text,
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
    assert plan['pages'][0]['segments'][1]['text'] == full_ocr_text
    assert 'Texte OCR exploitable' in plan['pages'][0]['segments'][1]['preview']
    assert plan['pages'][0]['segments'][1]['translate'] is True
    assert plan['pages'][0]['segments'][2]['translate'] is False
    assert 'P1O0S1 [ocr/translate]' in text
    assert 'P1O1S1 [ocr/skip]' in text
    assert json_path.exists()
    assert text_path.exists()


def test_build_native_ocr_fusion_plan_skips_native_ui_controls() -> None:
    overlay_ready_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "candidates": [
                    {
                        "block_index": 0,
                        "role": "content",
                        "line_count": 1,
                        "text": "Nom du demandeur",
                        "bbox": {"x0": 75, "y0": 119, "x1": 163, "y1": 133},
                    },
                    {
                        "block_index": 1,
                        "role": "content",
                        "line_count": 1,
                        "text": "Traduction complete",
                        "bbox": {"x0": 105, "y0": 249, "x1": 196, "y1": 263},
                    },
                    {
                        "block_index": 2,
                        "role": "content",
                        "line_count": 1,
                        "text": "OCR uniquement",
                        "bbox": {"x0": 105, "y0": 269, "x1": 182, "y1": 283},
                    },
                    {
                        "block_index": 3,
                        "role": "content",
                        "line_count": 1,
                        "text": "Relecture humaine",
                        "bbox": {"x0": 105, "y0": 289, "x1": 189, "y1": 303},
                    },
                    {
                        "block_index": 4,
                        "role": "content",
                        "line_count": 1,
                        "text": "Export debug",
                        "bbox": {"x0": 105, "y0": 309, "x1": 164, "y1": 323},
                    },
                    {
                        "block_index": 5,
                        "role": "content",
                        "line_count": 1,
                        "text": "Valider",
                        "bbox": {"x0": 232, "y0": 328, "x1": 269, "y1": 344},
                    },
                    {
                        "block_index": 6,
                        "role": "content",
                        "line_count": 2,
                        "text": "Bloc de commentaire libre: ce texte doit rester contenu principal.",
                        "bbox": {"x0": 72, "y0": 383, "x1": 419, "y1": 428},
                    },
                ],
            }
        ],
    }
    ocr_review_report = {"pages": [{"page_number": 1, "route": "native_only", "regions": []}]}

    plan = build_native_ocr_fusion_plan(overlay_ready_report, ocr_review_report)
    segments = plan["pages"][0]["segments"]
    by_text = {segment["text"]: segment for segment in segments}

    assert plan["total_segments"] == 7
    assert plan["translatable_segments"] == 2
    assert by_text["Nom du demandeur"]["translate"] is True
    assert by_text["Bloc de commentaire libre: ce texte doit rester contenu principal."]["translate"] is True
    for text in [
        "Traduction complete",
        "OCR uniquement",
        "Relecture humaine",
        "Export debug",
        "Valider",
    ]:
        assert by_text[text]["translate"] is False
        assert by_text[text]["role"] == "ui_control"


def test_build_native_ocr_fusion_plan_skips_native_table_rows() -> None:
    overlay_ready_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "candidates": [
                    {
                        "block_index": 0,
                        "role": "content",
                        "line_count": 1,
                        "text": "Facture avec tableau dense",
                        "bbox": {"x0": 72, "y0": 31, "x1": 333, "y1": 58},
                    },
                    {
                        "block_index": 1,
                        "role": "content",
                        "line_count": 5,
                        "text": "Designation\nQuantite\nUnite\nPrix HT\nTotal HT",
                        "bbox": {"x0": 59, "y0": 173, "x1": 545, "y1": 186},
                        "lines": [
                            {"text": "Designation", "bbox": {"x0": 59, "y0": 173, "x1": 111, "y1": 186}},
                            {"text": "Quantite", "bbox": {"x0": 269, "y0": 173, "x1": 306, "y1": 186}},
                            {"text": "Unite", "bbox": {"x0": 344, "y0": 173, "x1": 367, "y1": 186}},
                            {"text": "Prix HT", "bbox": {"x0": 419, "y0": 173, "x1": 451, "y1": 186}},
                            {"text": "Total HT", "bbox": {"x0": 509, "y0": 173, "x1": 545, "y1": 186}},
                        ],
                    },
                    {
                        "block_index": 2,
                        "role": "content",
                        "line_count": 5,
                        "text": "Licence pedagogique annuelle\n3\nu\n120,00\n360,00",
                        "bbox": {"x0": 59, "y0": 201, "x1": 537, "y1": 214},
                    },
                    {
                        "block_index": 3,
                        "role": "content",
                        "line_count": 3,
                        "text": "Le pipeline doit conserver la structure tabulaire.",
                        "bbox": {"x0": 72, "y0": 440, "x1": 432, "y1": 483},
                    },
                ],
            }
        ],
    }
    ocr_review_report = {"pages": [{"page_number": 1, "route": "native_only", "regions": []}]}

    plan = build_native_ocr_fusion_plan(overlay_ready_report, ocr_review_report)
    segments = plan["pages"][0]["segments"]
    by_text = {segment["text"]: segment for segment in segments}

    assert plan["total_segments"] == 8
    assert plan["translatable_segments"] == 7
    assert by_text["Facture avec tableau dense"]["translate"] is True
    assert by_text["Le pipeline doit conserver la structure tabulaire."]["translate"] is True
    for text in ["Designation", "Quantite", "Unite", "Prix HT", "Total HT"]:
        assert by_text[text]["translate"] is True
        assert by_text[text]["role"] == "table_header_cell"

    assert by_text["Licence pedagogique annuelle\n3\nu\n120,00\n360,00"]["translate"] is False
    assert by_text["Licence pedagogique annuelle\n3\nu\n120,00\n360,00"]["role"] == "table_row"



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


def test_build_fusion_translation_preview_report_chunks_long_ocr_text() -> None:
    long_ocr_text = (
        "Premier paragraphe OCR avec assez de contenu pour commencer le bloc. "
        + "mot " * 180
        + "\n\nDeuxieme paragraphe OCR qui doit rester dans la meme region mais etre traduit separement. "
        + "suite " * 130
    )
    fusion_plan = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "route": "native_plus_ocr_candidates",
                "segments": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "source_ref": "ocr:0",
                        "text": long_ocr_text,
                        "translate": True,
                    },
                ],
            }
        ],
    }
    seen_chunks: list[str] = []

    def fake_translate(text: str) -> str:
        seen_chunks.append(text)
        return f"EN:{text[:24]}"

    report = build_fusion_translation_preview_report(fusion_plan, fake_translate)
    segment = report["pages"][0]["segments"][0]

    assert report["total_segments"] == 1
    assert report["translated_segments"] == 1
    assert segment["source_text"] == long_ocr_text
    assert segment["translation_chunk_count"] > 1
    assert len(seen_chunks) == segment["translation_chunk_count"]
    assert all(len(chunk) <= 520 for chunk in seen_chunks)
    assert "\n\n" in segment["translated_text"]


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
                        "bbox": {"x0": 10, "y0": 20, "x1": 120, "y1": 50},
                    },
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "source_ref": "ocr:0",
                        "role": "ocr_region",
                        "status": "translated",
                        "source_text": "Texte OCR",
                        "translated_text": "OCR text",
                        "bbox": {"x0": 10, "y0": 70, "x1": 120, "y1": 110},
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
        "ocr_overlay_candidate": 1,
    }
    assert plan["pages"][0]["replacements"][0]["fit_risk"] == "low"
    assert plan["pages"][0]["replacements"][1]["fit_risk"] == "low"
    assert plan["pages"][0]["replacements"][1]["fit_diagnostics"]["bbox_area"] == 4400
    assert plan["pages"][0]["replacements"][1]["fit_diagnostics"]["flags"] == []
    assert "P1N0 [native/translated]" in text
    assert "strategy=ocr_overlay_candidate" in text
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
                        "apply_strategy": "ocr_overlay_candidate",
                        "status": "translated",
                        "fit_risk": "review",
                        "overflow_ratio": 1.0,
                        "fit_diagnostics": {"flags": ["fit_risk=review"]},
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
    assert summary["ocr_recommendation_summary"] == {"side_annotation_recommended": 1}
    assert summary["pages"][0]["ocr_recommendations"] == {"side_annotation_recommended": 1}
    assert "Total OCR annotated: 1" in text
    assert 'OCR recommendations: {"side_annotation_recommended": 1}' in text


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
                        "fit_risk": "low",
                        "overflow_ratio": 1.0,
                        "fit_diagnostics": {"flags": []},
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


def test_build_ocr_overlay_strategy_report_uses_generated_fit_diagnostics() -> None:
    preview_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "route": "ocr_only",
                "segments": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "source_ref": "ocr:0",
                        "role": "ocr_region",
                        "status": "translated",
                        "source_text": "Etiquette",
                        "translated_text": "Label",
                        "bbox": {"x0": 10, "y0": 10, "x1": 130, "y1": 50},
                    },
                    {
                        "segment_id": "P1O1",
                        "source_kind": "ocr",
                        "source_ref": "ocr:1",
                        "role": "ocr_region",
                        "status": "translated",
                        "source_text": "Court",
                        "translated_text": "This translated OCR text is deliberately much longer than the source and should remain visible as a side annotation until image-region rendering can be validated.",
                        "bbox": {"x0": 10, "y0": 70, "x1": 130, "y1": 100},
                    },
                ],
            }
        ],
    }

    plan = build_fusion_replacement_plan(preview_report)
    report = build_ocr_overlay_strategy_report(plan)

    decisions = report["pages"][0]["decisions"]
    assert decisions[0]["recommendation"] == "image_overlay_candidate"
    assert decisions[0]["fit_diagnostics"]["flags"] == []
    assert decisions[1]["recommendation"] == "side_annotation_recommended"
    assert "large_translation_expansion" in plan["pages"][0]["replacements"][1]["fit_diagnostics"]["flags"]


def test_build_ocr_page_translation_preview_report_combines_page_translation_and_strategy(tmp_path: Path) -> None:
    translation_preview = {
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
                        "status": "translated",
                        "source_text": "Bonjour natif",
                        "translated_text": "Native hello",
                    },
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "source_ref": "ocr:0",
                        "status": "translated",
                        "source_text": "Texte OCR",
                        "translated_text": "OCR text",
                        "translation_chunk_count": 2,
                    },
                ],
            }
        ],
    }
    strategy_report = {
        "pages": [
            {
                "page_number": 1,
                "decisions": [
                    {
                        "segment_id": "P1O0",
                        "recommendation": "image_overlay_candidate",
                        "fit_risk": "low",
                        "overflow_ratio": 0.89,
                        "reasons": ["translation_size_close_to_source", "low_fit_risk"],
                    }
                ],
            }
        ],
    }

    report = build_ocr_page_translation_preview_report(translation_preview, strategy_report)
    text = ocr_page_translation_preview_report_to_text(report)
    json_path, text_path = write_ocr_page_translation_preview_report(
        report,
        tmp_path,
        "page_translation_preview",
    )

    assert report["page_count"] == 1
    assert report["rendered_pages"] == [1]
    assert report["missing_pages"] == []
    assert report["total_native_segments"] == 1
    assert report["total_ocr_segments"] == 1
    assert report["pages"][0]["segments"][1]["recommendation"] == "image_overlay_candidate"
    assert report["pages"][0]["segments"][1]["translation_chunk_count"] == 2
    assert "Page 1: route=native_plus_ocr_candidates" in text
    assert "Rendered pages: [1]" in text
    assert "Missing pages: []" in text
    assert "P1O0 kind=ocr status=translated" in text
    assert "ocr_strategy: recommendation=image_overlay_candidate" in text
    assert "translation_chunks: 2" in text
    assert json_path.exists()
    assert text_path.exists()


def test_build_ocr_page_translation_preview_report_marks_missing_selected_pages() -> None:
    translation_preview = {
        "selected_pages": [1, 2],
        "pages": [
            {
                "page_number": 1,
                "route": "native_only",
                "segments": [
                    {
                        "segment_id": "P1N0",
                        "source_kind": "native",
                        "source_ref": "block:0",
                        "status": "translated",
                        "source_text": "Bonjour",
                        "translated_text": "Hello",
                    },
                ],
            }
        ],
    }

    report = build_ocr_page_translation_preview_report(translation_preview, {"pages": []})
    text = ocr_page_translation_preview_report_to_text(report)

    assert report["rendered_pages"] == [1]
    assert report["missing_pages"] == [2]
    assert "Missing pages: [2]" in text
