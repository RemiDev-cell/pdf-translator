from pathlib import Path
import json

import fitz
import requests

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
    ocr_inplace_prototype_summary_to_text,
    ocr_page_translation_preview_report_to_text,
    ocr_review_report_to_text,
    render_fusion_overlay_diagnostics,
    render_ocr_inplace_prototype,
    run_ocr_debug_pipeline,
    write_fusion_replacement_plan,
    write_fusion_overlay_diagnostics_summary,
    write_fusion_translation_preview_report,
    write_native_ocr_fusion_plan,
    write_native_ocr_fusion_report,
    write_ocr_candidate_report,
    write_ocr_inplace_prototype_summary,
    write_ocr_overlay_strategy_report,
    write_ocr_page_translation_preview_report,
    write_ocr_review_report,
)
from pdf_translator.qa.checks import annotate_repeated_blocks
from pdf_translator.routing import build_ocr_candidate_report


def _rendered_rgb_at(pdf_path: Path, page_index: int, x: int, y: int) -> tuple[int, int, int]:
    doc = fitz.open(pdf_path)
    try:
        pixmap = doc[page_index].get_pixmap(alpha=False)
        offset = (y * pixmap.width + x) * pixmap.n
        return tuple(pixmap.samples[offset : offset + 3])
    finally:
        doc.close()


def _write_black_ocr_region_pdf(pdf_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=420, height=240)
    page.insert_text((24, 42), "Native text")
    page.draw_rect(fitz.Rect(60, 100, 180, 160), color=(0, 0, 0), fill=(0, 0, 0), width=0)
    doc.save(pdf_path)
    doc.close()


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
    candidate = manifest['pages'][0]['candidates'][0]
    assert manifest['pages'][0]['candidates'][0]['pixel_width'] > 0
    assert manifest['pages'][0]['candidates'][0]['pixel_height'] > 0
    assert candidate['ocr_backend'] == 'mock'
    assert candidate['ocr_status'] == 'ok'
    assert '[MOCK OCR]' in candidate['ocr_text']
    assert candidate['crop_padding_pt'] == 8.0
    assert candidate['crop_bbox']['x0'] < candidate['bbox']['x0']
    assert candidate['crop_bbox']['y0'] < candidate['bbox']['y0']
    assert candidate['crop_bbox']['x1'] > candidate['bbox']['x1']
    assert candidate['crop_bbox']['y1'] > candidate['bbox']['y1']
    assert candidate['crop_padding_applied_pt'] == {
        "left": 8.0,
        "top": 8.0,
        "right": 8.0,
        "bottom": 8.0,
    }
    assert candidate['crop_constrained_edges'] == []



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
                        "page_zone": {"vertical": "body_zone", "horizontal": "center_band"},
                        "page_zone_flags": ["review_candidate_content_role_in_margin"],
                        "reading_flow": {
                            "reading_order_index": 0,
                            "classification": "isolated_block",
                            "flags": [],
                        },
                        "layout_group": {
                            "group_id": "P1G0",
                            "group_type": "heading_group",
                        },
                        "text": "Bloc natif principal avec assez de texte pour la revue.",
                    }
                ],
                "reading_flow_review_items": [
                    {
                        "page_number": 1,
                        "block_index": 2,
                        "role": "content",
                        "classification": "isolated_block",
                        "flags": ["review_large_vertical_gap_between_candidates"],
                        "text_preview": "Bloc natif principal avec assez de texte pour la revue.",
                    }
                ],
                "layout_group_review_items": [
                    {
                        "page_number": 1,
                        "group_id": "P1G0",
                        "group_type": "heading_group",
                        "candidate_count": 1,
                        "block_indices": [2],
                        "roles": ["content"],
                        "text_preview": "Bloc natif principal avec assez de texte pour la revue.",
                    }
                ],
                "page_zone_review_items": [
                    {
                        "page_number": 1,
                        "item_type": "candidate",
                        "block_index": 2,
                        "role": "content",
                        "page_zone": {"vertical": "body_zone", "horizontal": "center_band"},
                        "page_zone_flags": ["review_candidate_content_role_in_margin"],
                        "line_count": 2,
                        "text_preview": "Bloc natif principal avec assez de texte pour la revue.",
                        "selection_reason": "selected_as_content",
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
    assert 'page_zone' not in report['pages'][0]['native_regions'][0]
    assert 'page_zone_flags' not in report['pages'][0]['native_regions'][0]
    assert 'page_zone_review_items' not in report['pages'][0]['native_regions'][0]
    assert 'reading_flow' not in report['pages'][0]['native_regions'][0]
    assert 'reading_flow_review_items' not in report['pages'][0]['native_regions'][0]
    assert 'layout_group' not in report['pages'][0]['native_regions'][0]
    assert 'layout_group_review_items' not in report['pages'][0]['native_regions'][0]
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


def test_build_native_ocr_fusion_plan_does_not_treat_long_numbered_paragraph_as_table() -> None:
    paragraph = (
        "Contrairement a une opinion repandue, le Lorem Ipsum n'est pas simplement du texte\n"
        "aleatoire. Il trouve ses racines dans une oeuvre de la litterature latine\n"
        "classique datant de 45 av. J.-C. Un professeur a etudie ce passage."
    )
    overlay_ready_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "candidates": [
                    {
                        "block_index": 0,
                        "role": "content",
                        "line_count": 3,
                        "text": paragraph,
                        "bbox": {"x0": 72, "y0": 120, "x1": 450, "y1": 190},
                    },
                ],
            }
        ],
    }
    ocr_review_report = {"pages": [{"page_number": 1, "route": "native_only", "regions": []}]}

    plan = build_native_ocr_fusion_plan(overlay_ready_report, ocr_review_report)
    segment = plan["pages"][0]["segments"][0]

    assert segment["role"] == "content"
    assert segment["translate"] is True
    assert plan["translatable_segments"] == 1


def test_build_native_ocr_fusion_plan_does_not_treat_bullet_list_as_table() -> None:
    bullet_list = (
        "- Temperature moyenne du reacteur: 37.5 C\n"
        "- Concentration de glucose: 4.2 mmol/L\n"
        "- Adresse de contact: support.lab@example.org\n"
        "- Le sous-systeme Sensor Bridge reste deja nomme en anglais"
    )
    overlay_ready_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "candidates": [
                    {
                        "block_index": 0,
                        "role": "content",
                        "line_count": 4,
                        "text": bullet_list,
                        "bbox": {"x0": 72, "y0": 260, "x1": 510, "y1": 330},
                    },
                ],
            }
        ],
    }
    ocr_review_report = {"pages": [{"page_number": 1, "route": "native_only", "regions": []}]}

    plan = build_native_ocr_fusion_plan(overlay_ready_report, ocr_review_report)
    segment = plan["pages"][0]["segments"][0]

    assert segment["role"] == "content"
    assert segment["translate"] is True
    assert plan["translatable_segments"] == 1


def test_build_native_ocr_fusion_report_normalizes_extracted_bullets() -> None:
    overlay_ready_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "candidates": [
                    {
                        "block_index": 7,
                        "role": "content",
                        "line_count": 1,
                        "text": "? Comprendre la structure PDF",
                        "bbox": {"x0": 75, "y0": 370, "x1": 228, "y1": 385},
                        "lines": [
                            {
                                "text": "? Comprendre la structure PDF",
                                "bbox": {"x0": 75, "y0": 370, "x1": 228, "y1": 385},
                            }
                        ],
                    },
                    {
                        "block_index": 8,
                        "role": "content",
                        "line_count": 1,
                        "text": "? Est-ce une question utile ?",
                        "bbox": {"x0": 75, "y0": 390, "x1": 228, "y1": 405},
                        "lines": [
                            {
                                "text": "? Est-ce une question utile ?",
                                "bbox": {"x0": 75, "y0": 390, "x1": 228, "y1": 405},
                            }
                        ],
                    },
                ],
            }
        ],
    }
    ocr_review_report = {"pages": [{"page_number": 1, "route": "native_only", "regions": []}]}

    report = build_native_ocr_fusion_report(overlay_ready_report, ocr_review_report)
    regions = report["pages"][0]["native_regions"]

    assert regions[0]["text"] == "- Comprendre la structure PDF"
    assert regions[0]["lines"][0]["text"] == "- Comprendre la structure PDF"
    assert regions[1]["text"] == "? Est-ce une question utile ?"



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


def test_build_fusion_translation_preview_report_uses_structural_fallback_before_model() -> None:
    fusion_plan = {
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
                        "text": "étape 1",
                        "translate": True,
                    },
                ],
            }
        ],
    }

    def should_not_run(_: str) -> str:
        raise requests.exceptions.Timeout()

    report = build_fusion_translation_preview_report(fusion_plan, should_not_run)
    segment = report["pages"][0]["segments"][0]
    chunk = segment["translation_chunks"][0]

    assert segment["status"] == "translated"
    assert segment["translated_text"] == "step 1"
    assert segment["translation_method"] == "structural_fallback"
    assert segment["translation_attempt_count"] == 0
    assert segment["translation_method_summary"] == {"structural_fallback": 1}
    assert chunk["status"] == "translated"
    assert chunk["translation_method"] == "structural_fallback"


def test_build_fusion_translation_preview_report_keeps_long_unhandled_timeout_visible() -> None:
    fusion_plan = {
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
                        "text": "Ce texte OCR demande une vraie traduction et ne correspond a aucun fallback fiable.",
                        "translate": True,
                    },
                ],
            }
        ],
    }

    def always_timeout(_: str) -> str:
        raise requests.exceptions.Timeout()

    report = build_fusion_translation_preview_report(fusion_plan, always_timeout)
    segment = report["pages"][0]["segments"][0]
    chunk = segment["translation_chunks"][0]

    assert report["translated_segments"] == 0
    assert segment["status"] == "timeout"
    assert segment["translation_method"] == "timeout"
    assert segment["translation_attempt_count"] == 1
    assert segment["translation_method_summary"] == {"timeout": 1}
    assert segment["translated_text"].startswith("[TIMEOUT]")
    assert chunk["status"] == "timeout"
    assert chunk["translation_method"] == "timeout"
    assert chunk["translation_attempt_count"] == 1


def test_build_fusion_translation_preview_report_marks_mixed_chunk_methods() -> None:
    long_tail = "mot " * 180
    fusion_plan = {
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
                        "text": f"étape 1\n\n{long_tail}",
                        "translate": True,
                    },
                ],
            }
        ],
    }

    seen_chunks: list[str] = []

    def fake_translate(text: str) -> str:
        seen_chunks.append(text)
        return f"EN:{text[:12]}"

    report = build_fusion_translation_preview_report(fusion_plan, fake_translate)
    segment = report["pages"][0]["segments"][0]

    assert segment["status"] == "translated"
    assert segment["translation_chunk_count"] > 1
    assert segment["translation_method"] == "mixed"
    assert segment["translation_method_summary"]["structural_fallback"] == 1
    assert segment["translation_method_summary"]["model"] >= 1
    assert segment["translation_attempt_count"] == len(seen_chunks)
    assert segment["translated_text"].startswith("step 1")


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


def test_ocr_edge_clipping_is_propagated_to_review_strategy() -> None:
    overlay_ready_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "candidates": [],
            }
        ],
    }
    ocr_review_report = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "route": "ocr_only",
                "regions": [
                    {
                        "candidate_index": 0,
                        "ocr_status": "ok",
                        "quality": "usable",
                        "ocr_backend": "tesseract",
                        "word_count": 8,
                        "edge_clipping_detected": True,
                        "edge_clipping_line_count": 2,
                        "bbox": {"x0": 20, "y0": 40, "x1": 220, "y1": 180},
                        "crop_bbox": {"x0": 12, "y0": 32, "x1": 228, "y1": 188},
                        "crop_padding_pt": 8.0,
                        "text": "Texte OCR coupe au bord droit",
                        "preview": "Texte OCR coupe au bord droit",
                        "ocr_layout": [
                            {
                                "line_index": 1,
                                "text": "Texte OCR coupe au bord droit",
                                "bbox_px": {"x0": 0, "y0": 0, "x1": 400, "y1": 30},
                                "touches_right_edge": True,
                            }
                        ],
                    }
                ],
            }
        ],
    }

    fusion_plan = build_native_ocr_fusion_plan(overlay_ready_report, ocr_review_report)
    assert fusion_plan["pages"][0]["segments"][0]["edge_clipping_detected"] is True
    assert fusion_plan["pages"][0]["segments"][0]["edge_clipping_line_count"] == 2
    assert fusion_plan["pages"][0]["segments"][0]["crop_bbox"]["x0"] == 12

    preview_report = build_fusion_translation_preview_report(fusion_plan, lambda text: f"EN:{text}")
    preview_segment = preview_report["pages"][0]["segments"][0]
    assert preview_segment["edge_clipping_detected"] is True
    assert preview_segment["crop_padding_pt"] == 8.0

    replacement_plan = build_fusion_replacement_plan(preview_report)
    replacement = replacement_plan["pages"][0]["replacements"][0]
    assert replacement["apply_strategy"] == "ocr_review_required"
    assert replacement["edge_clipping_detected"] is True
    assert replacement["crop_bbox"]["x1"] == 228
    assert "edge_clipping_detected" in replacement["fit_diagnostics"]["flags"]

    strategy_report = build_ocr_overlay_strategy_report(replacement_plan)
    decision = strategy_report["pages"][0]["decisions"][0]
    assert decision["recommendation"] == "manual_review"
    assert decision["edge_clipping_detected"] is True
    assert "edge_clipping_detected" in decision["reasons"]


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
                        "translation_method": "model",
                        "translation_attempt_count": 1,
                        "translation_method_summary": {"model": 1},
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
                        "translation_method": "structural_fallback",
                        "translation_attempt_count": 0,
                        "translation_method_summary": {"structural_fallback": 1},
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
    assert plan["pages"][0]["replacements"][0]["translation_method"] == "model"
    assert plan["pages"][0]["replacements"][1]["translation_method"] == "structural_fallback"
    assert plan["pages"][0]["replacements"][1]["translation_attempt_count"] == 0
    assert plan["pages"][0]["replacements"][1]["ocr_recommendation"] == "image_overlay_candidate"
    assert "low_fit_risk" in plan["pages"][0]["replacements"][1]["ocr_recommendation_reasons"]
    assert plan["pages"][0]["replacements"][1]["ocr_readiness_status"] == "ready_for_image_overlay"
    assert "recommendation=image_overlay_candidate" in plan["pages"][0]["replacements"][1]["ocr_readiness_reasons"]
    assert plan["ocr_readiness_summary"] == {"ready_for_image_overlay": 1}
    assert plan["pages"][0]["ocr_readiness_summary"] == {"ready_for_image_overlay": 1}
    assert plan["pages"][0]["replacements"][1]["fit_diagnostics"]["bbox_area"] == 4400
    assert plan["pages"][0]["replacements"][1]["fit_diagnostics"]["flags"] == []
    assert "P1N0 [native/translated]" in text
    assert "strategy=ocr_overlay_candidate" in text
    assert "recommendation=image_overlay_candidate" in text
    assert "readiness=ready_for_image_overlay" in text
    assert "method=structural_fallback" in text
    assert json_path.exists()
    assert text_path.exists()


def test_build_fusion_replacement_plan_summarizes_ocr_readiness() -> None:
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
                        "translated_text": (
                            "This translated OCR text is deliberately much longer than the source "
                            "and should remain visible as a side annotation."
                        ),
                        "bbox": {"x0": 10, "y0": 70, "x1": 130, "y1": 100},
                    },
                    {
                        "segment_id": "P1O2",
                        "source_kind": "ocr",
                        "source_ref": "ocr:2",
                        "role": "ocr_region",
                        "status": "timeout",
                        "source_text": "Texte OCR",
                        "translated_text": "[TIMEOUT] Texte OCR",
                        "bbox": {"x0": 10, "y0": 120, "x1": 130, "y1": 150},
                    },
                    {
                        "segment_id": "P1O3",
                        "source_kind": "ocr",
                        "source_ref": "ocr:3",
                        "role": "ocr_region",
                        "status": "translated",
                        "source_text": "Texte OCR",
                        "translated_text": "",
                        "bbox": {"x0": 10, "y0": 170, "x1": 130, "y1": 200},
                    },
                    {
                        "segment_id": "P1O4",
                        "source_kind": "ocr",
                        "source_ref": "ocr:4",
                        "role": "ocr_region",
                        "status": "translated",
                        "source_text": "Texte OCR",
                        "translated_text": "OCR text",
                        "bbox": {"x0": 10, "y0": 210, "x1": 130, "y1": 240},
                        "edge_clipping_detected": True,
                    },
                    {
                        "segment_id": "P1O5",
                        "source_kind": "ocr",
                        "source_ref": "ocr:5",
                        "role": "ocr_region",
                        "status": "translated",
                        "source_text": "Texte OCR",
                        "translated_text": "OCR text",
                        "bbox": {},
                    },
                ],
            }
        ],
    }

    plan = build_fusion_replacement_plan(preview_report)
    replacements = plan["pages"][0]["replacements"]

    assert [replacement["ocr_readiness_status"] for replacement in replacements] == [
        "ready_for_image_overlay",
        "side_annotation_review",
        "blocked",
        "blocked",
        "blocked",
        "blocked",
    ]
    assert plan["ocr_readiness_summary"] == {
        "ready_for_image_overlay": 1,
        "side_annotation_review": 1,
        "blocked": 4,
    }
    assert plan["pages"][0]["ocr_readiness_summary"] == plan["ocr_readiness_summary"]
    assert plan["ocr_readiness_reason_summary"]["recommendation=image_overlay_candidate"] == 1
    assert plan["ocr_readiness_reason_summary"]["recommendation=side_annotation_recommended"] == 1
    assert plan["ocr_readiness_reason_summary"]["status=timeout"] == 1
    assert plan["ocr_readiness_reason_summary"]["empty_translation"] == 1
    assert plan["ocr_readiness_reason_summary"]["edge_clipping_detected"] == 1
    assert plan["ocr_readiness_reason_summary"]["missing_bbox"] == 1


def test_build_ocr_overlay_strategy_report_preserves_manual_review_readiness() -> None:
    plan = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "route": "ocr_only",
                "replacements": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "source_ref": "ocr:0",
                        "status": "translated",
                        "fit_risk": "low",
                        "overflow_ratio": 1.0,
                        "fit_diagnostics": {"flags": []},
                        "bbox": {"x0": 10, "y0": 20, "x1": 160, "y1": 60},
                        "source_text": "Texte OCR",
                        "translated_text": "OCR text",
                        "ocr_recommendation": "manual_review",
                        "ocr_recommendation_reasons": ["human_review_requested"],
                    }
                ],
            }
        ],
    }

    report = build_ocr_overlay_strategy_report(plan)
    decision = report["pages"][0]["decisions"][0]

    assert report["ocr_readiness_summary"] == {"manual_review": 1}
    assert report["pages"][0]["ocr_readiness_summary"] == {"manual_review": 1}
    assert decision["recommendation"] == "manual_review"
    assert decision["ocr_readiness_status"] == "manual_review"
    assert decision["ocr_readiness_reasons"] == [
        "recommendation=manual_review",
        "human_review_requested",
    ]


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
                    {
                        "segment_id": "P1O1",
                        "source_kind": "ocr",
                        "apply_strategy": "ocr_overlay_candidate",
                        "status": "translated",
                        "fit_risk": "low",
                        "overflow_ratio": 1.0,
                        "fit_diagnostics": {"flags": []},
                        "bbox": {"x0": 40, "y0": 182, "x1": 200, "y1": 212},
                        "translated_text": "Short OCR label",
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
    assert summary["total_ocr_annotated"] == 2
    assert summary["render_decision_summary"] == {
        "applied_native_overlay": 1,
        "annotated_ocr_side": 1,
        "applied_ocr_overlay": 1,
    }
    assert summary["pages"][0]["render_decision_summary"] == {
        "applied_native_overlay": 1,
        "annotated_ocr_side": 1,
        "applied_ocr_overlay": 1,
    }
    assert [
        item["render_decision"]
        for item in summary["pages"][0]["render_review_items"]
    ] == ["applied_native_overlay", "annotated_ocr_side", "applied_ocr_overlay"]
    assert summary["ocr_recommendation_summary"] == {
        "side_annotation_recommended": 1,
        "image_overlay_candidate": 1,
    }
    assert summary["ocr_readiness_summary"] == {
        "side_annotation_review": 1,
        "ready_for_image_overlay": 1,
    }
    assert summary["pages"][0]["ocr_recommendations"] == {
        "side_annotation_recommended": 1,
        "image_overlay_candidate": 1,
    }
    assert summary["pages"][0]["ocr_readiness_summary"] == {
        "side_annotation_review": 1,
        "ready_for_image_overlay": 1,
    }
    assert [
        item["ocr_readiness_status"]
        for item in summary["pages"][0]["render_review_items"]
        if item["source_kind"] == "ocr"
    ] == ["side_annotation_review", "ready_for_image_overlay"]
    assert "Total OCR annotated: 2" in text
    assert 'OCR recommendations: {"image_overlay_candidate": 1, "side_annotation_recommended": 1}' in text
    assert 'OCR readiness: {"ready_for_image_overlay": 1, "side_annotation_review": 1}' in text
    assert "Render decisions:" in text
    assert "decision=annotated_ocr_side" in text
    assert "decision=applied_ocr_overlay" in text
    assert "readiness=side_annotation_review" in text


def test_render_fusion_overlay_diagnostics_adds_review_appendix_for_manual_ocr(tmp_path: Path) -> None:
    pdf_path = tmp_path / "source.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=240)
    page.insert_text((24, 42), "Scan text remains visible")
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
                        "apply_strategy": "ocr_review_required",
                        "status": "translated",
                        "fit_risk": "high",
                        "overflow_ratio": 1.0,
                        "fit_diagnostics": {"flags": ["edge_clipping_detected"]},
                        "edge_clipping_detected": True,
                        "edge_clipping_line_count": 2,
                        "crop_constrained_edges": ["right"],
                        "bbox": {"x0": 10, "y0": 10, "x1": 230, "y1": 230},
                        "source_text": "Texte OCR coupe au bord droit",
                        "translated_text": "OCR text clipped on the right edge",
                    },
                ],
            }
        ],
    }

    pdf_output_path, summary, image_paths = render_fusion_overlay_diagnostics(
        pdf_path=pdf_path,
        fusion_replacement_plan=plan,
        output_dir=tmp_path,
        stem="manual_review_overlay",
    )
    text = fusion_overlay_diagnostics_summary_to_text(summary)

    assert pdf_output_path.exists()
    assert len(image_paths) == 2
    assert summary["total_ocr_review_required"] == 1
    assert summary["ocr_recommendation_summary"] == {"manual_review": 1}
    assert summary["ocr_readiness_summary"] == {"blocked": 1}
    assert summary["render_decision_summary"] == {"annotated_ocr_review": 1}
    assert summary["ocr_review_appendix_page_count"] == 1
    assert summary["pages"][0]["render_review_items"][0]["ocr_readiness_status"] == "blocked"
    assert "OCR review appendix pages: 1" in text
    assert "decision=annotated_ocr_review" in text
    assert "readiness=blocked" in text
    rendered = fitz.open(pdf_output_path)
    try:
        assert rendered.page_count == 2
        assert "OCR manual review" in rendered[1].get_text()
        assert "crop_constrained_edges=right" in rendered[1].get_text()
    finally:
        rendered.close()


def test_render_ocr_inplace_prototype_applies_ready_ocr_only(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ocr-ready-source.pdf"
    _write_black_ocr_region_pdf(pdf_path)

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
                        "bbox": {"x0": 60, "y0": 100, "x1": 180, "y1": 160},
                        "source_text": "Etiquette",
                        "translated_text": "Label",
                    },
                ],
            }
        ],
    }

    pdf_output_path, summary, image_paths = render_ocr_inplace_prototype(
        pdf_path=pdf_path,
        fusion_replacement_plan=plan,
        output_dir=tmp_path,
        stem="ocr_inplace_ready",
    )
    text = ocr_inplace_prototype_summary_to_text(summary)
    summary_path = write_ocr_inplace_prototype_summary(summary, tmp_path, "ocr_inplace_ready")

    assert pdf_output_path.exists()
    assert summary_path.exists()
    assert len(image_paths) == 1
    review_path = Path(summary["recomposition_review_path"])
    assert review_path.exists()
    assert Path(summary["source_image_paths"][0]).exists()
    assert summary["total_ocr_inplace_applied"] == 1
    assert summary["total_ocr_annotated"] == 0
    assert summary["render_decision_summary"] == {"applied_ocr_inplace": 1}
    assert summary["ocr_render_mode_summary"] == {"bbox_textbox": 1}
    assert summary["pages"][0]["ocr_render_mode_summary"] == {"bbox_textbox": 1}
    assert summary["ocr_readiness_summary"] == {"ready_for_image_overlay": 1}
    ready_item = summary["pages"][0]["render_review_items"][0]
    assert ready_item["ocr_render_mode"] == "bbox_textbox"
    assert ready_item["rendered_with_layout"] is False
    assert ready_item["ocr_layout_line_count"] == 0
    assert ready_item["ocr_layout_rendered_block_count"] == 0
    assert ready_item["ocr_layout_fallback_used"] is True
    metrics = summary["pages"][0]["recomposition_metrics"]
    assert metrics["changed_in_replacement_zone_count"] > 0
    assert metrics["changed_in_replacement_zone_ratio"] > 0.1
    assert metrics["changed_outside_replacement_zone_ratio"] < 0.02
    html = review_path.read_text(encoding="utf-8")
    assert "ocr_render_mode" in html
    assert "bbox_textbox" in html
    assert image_paths[0].name in html
    assert Path(summary["source_image_paths"][0]).name in html
    assert "decision=applied_ocr_inplace" in text
    assert 'OCR render modes: {"bbox_textbox": 1}' in text
    assert "Recomposition review:" in text
    assert "ocr_render_mode=bbox_textbox" in text
    assert "Total OCR in-place applied: 1" in text
    assert sum(_rendered_rgb_at(pdf_output_path, 0, 120, 130)) > 600


def test_render_ocr_inplace_prototype_reports_layout_tsv_mode(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ocr-ready-layout-source.pdf"
    _write_black_ocr_region_pdf(pdf_path)

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
                        "bbox": {"x0": 60, "y0": 100, "x1": 180, "y1": 160},
                        "crop_bbox": {"x0": 60, "y0": 100, "x1": 180, "y1": 160},
                        "source_text": "Texte OCR\nsur deux lignes",
                        "translated_text": "OCR text\non two lines",
                        "ocr_readiness_status": "ready_for_image_overlay",
                        "ocr_readiness_reasons": ["manual_readiness_override"],
                        "ocr_layout": [
                            {
                                "line_index": 0,
                                "block_num": 1,
                                "par_num": 1,
                                "text": "Texte OCR",
                                "bbox_px": {"x0": 0, "y0": 0, "x1": 360, "y1": 80},
                            },
                            {
                                "line_index": 1,
                                "block_num": 1,
                                "par_num": 1,
                                "text": "sur deux lignes",
                                "bbox_px": {"x0": 0, "y0": 90, "x1": 360, "y1": 180},
                            },
                        ],
                    },
                ],
            }
        ],
    }

    _, summary, _ = render_ocr_inplace_prototype(
        pdf_path=pdf_path,
        fusion_replacement_plan=plan,
        output_dir=tmp_path,
        stem="ocr_inplace_layout",
    )
    text = ocr_inplace_prototype_summary_to_text(summary)

    assert summary["render_decision_summary"] == {"applied_ocr_inplace": 1}
    assert summary["ocr_render_mode_summary"] == {"layout_tsv": 1}
    item = summary["pages"][0]["render_review_items"][0]
    assert item["ocr_render_mode"] == "layout_tsv"
    assert item["rendered_with_layout"] is True
    assert item["ocr_layout_line_count"] == 2
    assert item["ocr_layout_block_count"] == 1
    assert item["ocr_layout_rendered_line_count"] == 2
    assert item["ocr_layout_fallback_used"] is False
    assert 'OCR render modes: {"layout_tsv": 1}' in text
    assert "ocr_render_mode=layout_tsv" in text


def test_render_ocr_inplace_prototype_keeps_side_annotation_off_region(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ocr-side-source.pdf"
    _write_black_ocr_region_pdf(pdf_path)

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
                        "fit_risk": "high",
                        "overflow_ratio": 1.0,
                        "fit_diagnostics": {"flags": ["long_translation"]},
                        "bbox": {"x0": 60, "y0": 100, "x1": 180, "y1": 160},
                        "source_text": "Texte OCR",
                        "translated_text": "This OCR translation is intentionally long enough to stay as a side annotation for human review.",
                        "ocr_recommendation": "image_overlay_candidate",
                        "ocr_recommendation_reasons": ["precomputed_image_candidate"],
                        "ocr_readiness_status": "side_annotation_review",
                        "ocr_readiness_reasons": ["manual_readiness_override"],
                    },
                ],
            }
        ],
    }

    pdf_output_path, summary, _ = render_ocr_inplace_prototype(
        pdf_path=pdf_path,
        fusion_replacement_plan=plan,
        output_dir=tmp_path,
        stem="ocr_inplace_side",
    )

    assert summary["total_ocr_inplace_applied"] == 0
    assert summary["total_ocr_annotated"] == 1
    assert summary["render_decision_summary"] == {"annotated_ocr_side": 1}
    assert summary["ocr_render_mode_summary"] == {"side_annotation": 1}
    assert summary["pages"][0]["render_review_items"][0]["ocr_render_mode"] == "side_annotation"
    assert summary["ocr_recommendation_summary"] == {"image_overlay_candidate": 1}
    assert summary["ocr_readiness_summary"] == {"side_annotation_review": 1}
    assert sum(_rendered_rgb_at(pdf_output_path, 0, 120, 130)) < 30


def test_render_ocr_inplace_prototype_keeps_blocked_ocr_in_review_appendix(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ocr-blocked-source.pdf"
    _write_black_ocr_region_pdf(pdf_path)

    plan = {
        "selected_pages": [1],
        "pages": [
            {
                "page_number": 1,
                "replacements": [
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "apply_strategy": "ocr_review_required",
                        "status": "translated",
                        "fit_risk": "medium",
                        "overflow_ratio": 1.0,
                        "fit_diagnostics": {"flags": ["edge_clipping_detected"]},
                        "edge_clipping_detected": True,
                        "edge_clipping_line_count": 1,
                        "bbox": {"x0": 60, "y0": 100, "x1": 180, "y1": 160},
                        "source_text": "Texte OCR coupe",
                        "translated_text": "Clipped OCR text",
                    },
                ],
            }
        ],
    }

    pdf_output_path, summary, image_paths = render_ocr_inplace_prototype(
        pdf_path=pdf_path,
        fusion_replacement_plan=plan,
        output_dir=tmp_path,
        stem="ocr_inplace_blocked",
    )
    text = ocr_inplace_prototype_summary_to_text(summary)

    assert len(image_paths) == 2
    assert summary["total_ocr_inplace_applied"] == 0
    assert summary["total_ocr_review_required"] == 1
    assert summary["render_decision_summary"] == {"annotated_ocr_review": 1}
    assert summary["ocr_render_mode_summary"] == {"review_appendix": 1}
    assert summary["pages"][0]["render_review_items"][0]["ocr_render_mode"] == "review_appendix"
    assert summary["ocr_readiness_summary"] == {"blocked": 1}
    assert summary["ocr_review_appendix_page_count"] == 1
    assert "decision=annotated_ocr_review" in text
    assert "readiness=blocked" in text
    rendered = fitz.open(pdf_output_path)
    try:
        assert rendered.page_count == 2
        assert "OCR manual review" in rendered[1].get_text()
    finally:
        rendered.close()


def test_render_ocr_inplace_prototype_skips_missing_ocr_bbox(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ocr-missing-bbox-source.pdf"
    _write_black_ocr_region_pdf(pdf_path)

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
                        "bbox": {},
                        "source_text": "Texte OCR",
                        "translated_text": "OCR text",
                    },
                ],
            }
        ],
    }

    _, summary, image_paths = render_ocr_inplace_prototype(
        pdf_path=pdf_path,
        fusion_replacement_plan=plan,
        output_dir=tmp_path,
        stem="ocr_inplace_missing_bbox",
    )

    assert len(image_paths) == 1
    assert summary["total_skipped"] == 1
    assert summary["total_ocr_inplace_applied"] == 0
    assert summary["render_decision_summary"] == {"skipped_missing_bbox": 1}
    assert summary["ocr_render_mode_summary"] == {"skipped": 1}
    assert summary["pages"][0]["render_review_items"][0]["ocr_render_mode"] == "skipped"
    assert summary["ocr_readiness_summary"] == {"blocked": 1}


def test_render_fusion_overlay_diagnostics_explains_skips_and_side_annotations(tmp_path: Path) -> None:
    pdf_path = tmp_path / "source-decisions.pdf"
    doc = fitz.open()
    page = doc.new_page(width=260, height=260)
    page.insert_text((24, 42), "Native and OCR diagnostics")
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
                        "status": "timeout",
                        "translation_method": "timeout",
                        "translation_attempt_count": 1,
                        "fit_risk": "low",
                        "bbox": {"x0": 20, "y0": 26, "x1": 130, "y1": 54},
                        "translated_text": "[TIMEOUT] Bonjour",
                    },
                    {
                        "segment_id": "P1N1",
                        "source_kind": "native",
                        "apply_strategy": "native_overlay_candidate",
                        "status": "translated",
                        "translation_method": "model",
                        "translation_attempt_count": 1,
                        "fit_risk": "high",
                        "bbox": {"x0": 20, "y0": 60, "x1": 130, "y1": 80},
                        "translated_text": "Too long for this native region",
                    },
                    {
                        "segment_id": "P1N2",
                        "source_kind": "native",
                        "apply_strategy": "native_overlay_candidate",
                        "status": "translated",
                        "fit_risk": "low",
                        "bbox": {},
                        "translated_text": "Missing bbox",
                    },
                    {
                        "segment_id": "P1N3",
                        "source_kind": "native",
                        "apply_strategy": "unknown_strategy",
                        "status": "translated",
                        "fit_risk": "low",
                        "bbox": {"x0": 20, "y0": 86, "x1": 130, "y1": 106},
                        "translated_text": "Unknown strategy",
                    },
                    {
                        "segment_id": "P1O0",
                        "source_kind": "ocr",
                        "apply_strategy": "ocr_side_annotation",
                        "status": "translated",
                        "translation_method": "model",
                        "translation_attempt_count": 1,
                        "fit_risk": "high",
                        "overflow_ratio": 2.4,
                        "fit_diagnostics": {"flags": ["long_translation"]},
                        "bbox": {"x0": 40, "y0": 120, "x1": 210, "y1": 185},
                        "source_text": "Texte OCR",
                        "translated_text": "This OCR text is intentionally better kept as a visible side annotation.",
                    },
                ],
            }
        ],
    }

    _, summary, _ = render_fusion_overlay_diagnostics(
        pdf_path=pdf_path,
        fusion_replacement_plan=plan,
        output_dir=tmp_path,
        stem="decision_overlay",
    )
    text = fusion_overlay_diagnostics_summary_to_text(summary)

    assert summary["total_skipped"] == 4
    assert summary["total_ocr_annotated"] == 1
    assert summary["render_decision_summary"] == {
        "skipped_status": 1,
        "skipped_native_fit_risk": 1,
        "skipped_missing_bbox": 1,
        "skipped_apply_strategy": 1,
        "annotated_ocr_side": 1,
    }
    assert summary["pages"][0]["render_review_items"][0]["translation_method"] == "timeout"
    assert summary["pages"][0]["render_review_items"][-1]["ocr_recommendation"] == "side_annotation_recommended"
    assert summary["ocr_readiness_summary"] == {"side_annotation_review": 1}
    assert summary["pages"][0]["render_review_items"][-1]["ocr_readiness_status"] == "side_annotation_review"
    assert "decision=skipped_status" in text
    assert "decision=annotated_ocr_side" in text
    assert "readiness=side_annotation_review" in text


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
    assert report["ocr_readiness_summary"] == {
        "side_annotation_review": 1,
        "ready_for_image_overlay": 1,
    }
    assert report["pages"][0]["decisions"][0]["recommendation"] == "side_annotation_recommended"
    assert report["pages"][0]["decisions"][1]["recommendation"] == "image_overlay_candidate"
    assert report["pages"][0]["decisions"][0]["ocr_readiness_status"] == "side_annotation_review"
    assert report["pages"][0]["decisions"][1]["ocr_readiness_status"] == "ready_for_image_overlay"
    assert "P1O0 recommendation=side_annotation_recommended" in text
    assert "readiness=side_annotation_review" in text
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
    assert decisions[0]["ocr_readiness_status"] == "ready_for_image_overlay"
    assert decisions[0]["fit_diagnostics"]["flags"] == []
    assert decisions[1]["recommendation"] == "side_annotation_recommended"
    assert decisions[1]["ocr_readiness_status"] == "side_annotation_review"
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
                        "ocr_readiness_status": "ready_for_image_overlay",
                        "ocr_readiness_reasons": [
                            "recommendation=image_overlay_candidate",
                            "translation_size_close_to_source",
                            "low_fit_risk",
                        ],
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
    assert report["ocr_readiness_summary"] == {"ready_for_image_overlay": 1}
    assert report["pages"][0]["ocr_readiness_summary"] == {"ready_for_image_overlay": 1}
    assert report["pages"][0]["segments"][1]["recommendation"] == "image_overlay_candidate"
    assert report["pages"][0]["segments"][1]["ocr_readiness_status"] == "ready_for_image_overlay"
    assert report["pages"][0]["segments"][1]["translation_chunk_count"] == 2
    assert "Page 1: route=native_plus_ocr_candidates" in text
    assert "Rendered pages: [1]" in text
    assert "Missing pages: []" in text
    assert "P1O0 kind=ocr status=translated" in text
    assert "ocr_strategy: recommendation=image_overlay_candidate" in text
    assert "readiness=ready_for_image_overlay" in text
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
