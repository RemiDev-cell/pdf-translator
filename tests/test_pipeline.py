from pathlib import Path

import fitz

from pdf_translator.pipeline import run_document_preview, run_native_overlay_preview


def _make_admin_like_pdf(pdf_path: Path, tmp_path: Path) -> None:
    image_path = tmp_path / "decorative-logo.png"
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), 0)
    pixmap.clear_with(0x2F80ED)
    pixmap.save(image_path)

    doc = fitz.open()
    page = doc.new_page(width=420, height=600)
    page.insert_image(fitz.Rect(28, 24, 44, 40), filename=str(image_path))
    page.insert_text((300, 36), "Facture n° 2026-001", fontsize=10)
    page.insert_text((300, 52), "Date de facture : 07/05/2026", fontsize=10)
    page.insert_text((32, 92), "Votre facture internet fibre", fontsize=14)

    rows = [
        ("Abonnement mensuel fibre optique", "29,99 EUR", 130),
        ("Location box et services inclus", "5,00 EUR", 154),
        ("Remise promotionnelle appliquee", "-3,00 EUR", 178),
        ("Total a payer", "31,99 EUR", 212),
    ]
    for label, amount, y in rows:
        page.insert_text((32, y), label, fontsize=10)
        page.insert_text((250, y), amount, fontsize=10)

    page.insert_text((330, 235), "31,99 EUR", fontsize=12)
    page.insert_textbox(
        fitz.Rect(32, 260, 210, 330),
        "Vos coordonnées\nM PARTOUCHE REMI\nremi@example.org\nn° client : C-778899",
        fontsize=10,
    )
    page.insert_text(
        (32, 558),
        "ACME Telecom SA au capital de 100000 EUR - 123 456 789 RCS Paris",
        fontsize=8,
    )
    doc.save(pdf_path)
    doc.close()


def _make_scientific_born_digital_pdf(pdf_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=480, height=640)
    page.insert_textbox(
        fitz.Rect(36, 28, 444, 62),
        "ETUDE DES JONCTIONS P/N EN REGIME DYNAMIQUE",
        fontsize=15,
    )
    page.insert_textbox(
        fitz.Rect(36, 92, 444, 150),
        (
            "Ce document presente une experience de physique des semi-conducteurs. "
            "La tension appliquee modifie la concentration des porteurs dans la zone "
            "de charge espace."
        ),
        fontsize=10,
    )
    page.insert_text((72, 190), "I = I_s (exp(qV / kT) - 1)", fontsize=11)

    page.draw_rect(fitz.Rect(96, 245, 384, 365), color=(0, 0, 0), width=1)
    page.draw_line(fitz.Point(130, 330), fitz.Point(350, 280), color=(0, 0, 0), width=1)
    page.insert_text((120, 270), "zone P", fontsize=9)
    page.insert_text((290, 310), "zone N", fontsize=9)
    page.insert_textbox(
        fitz.Rect(64, 386, 416, 420),
        "Figure 1 : Profil qualitatif de la jonction P/N sous polarisation directe.",
        fontsize=9,
    )
    page.insert_textbox(
        fitz.Rect(36, 456, 444, 520),
        (
            "Les mesures sont comparees a un modele analytique afin de verifier "
            "la stabilite thermique du prototype."
        ),
        fontsize=10,
    )
    doc.save(pdf_path)
    doc.close()


def _make_simple_table_pdf(pdf_path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=480, height=640)
    page.insert_textbox(
        fitz.Rect(36, 28, 444, 62),
        "MESURES ELECTRIQUES DE LA JONCTION",
        fontsize=15,
    )
    page.insert_textbox(
        fitz.Rect(54, 78, 426, 98),
        "Les resultats experimentaux sont resumes dans le tableau suivant.",
        fontsize=10,
    )

    xs = [54, 190, 310]
    widths = [136, 120, 104]
    rows = [
        ("Parametre", "Valeur", "Unite"),
        ("Tension directe", "0,72", "V"),
        ("Courant inverse", "12", "uA"),
        ("Temperature", "300", "K"),
    ]
    for row_index, row in enumerate(rows):
        y = 130 + (row_index * 30)
        for x, width, text in zip(xs, widths, row):
            page.draw_rect(
                fitz.Rect(x - 6, y - 16, x + width, y + 6),
                color=(0, 0, 0),
                width=0.5,
            )
            page.insert_text((x, y), text, fontsize=9)

    page.insert_textbox(
        fitz.Rect(54, 266, 426, 300),
        "Tableau 1 : Parametres experimentaux mesures a temperature ambiante.",
        fontsize=9,
    )
    doc.save(pdf_path)
    doc.close()


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


def test_run_document_preview_keeps_admin_like_pdf_native_with_decorative_image(tmp_path: Path) -> None:
    pdf_path = tmp_path / "admin-like.pdf"
    _make_admin_like_pdf(pdf_path, tmp_path)

    result = run_document_preview(
        pdf_path=pdf_path,
        output_dir=tmp_path,
        selected_pages=[1],
        translate_text_fn=lambda text: f"EN {text}",
        artifact_stem="admin_like",
    )

    assert result["preview_mode"] == "native_overlay"
    assert result["routing_report"]["route_summary"] == {"native_only": 1}

    page_report = result["routing_report"]["pages"][0]
    assert page_report["ocr_candidate_count"] == 0
    assert page_report["ignored_ocr_image_reason_summary"] == {
        "image_too_small_for_ocr": 1,
    }
    assert page_report["excluded_role_summary"] == {
        "billing_metadata": 2,
        "legal_footer": 1,
        "numeric_value": 1,
        "sensitive_metadata": 1,
    }

    overlay_ready = result["preview_result"]["overlay_ready_report"]
    overlay_page = overlay_ready["pages"][0]
    candidate_texts = [candidate["text"] for candidate in overlay_page["candidates"]]

    assert overlay_ready["total_candidate_blocks"] == overlay_page["candidate_block_count"]
    assert overlay_page["candidate_block_count"] == len(candidate_texts)
    assert "Votre facture internet fibre" in candidate_texts
    assert any("Abonnement mensuel fibre optique" in text for text in candidate_texts)
    assert any("Location box et services inclus" in text for text in candidate_texts)
    assert any("Total a payer" in text for text in candidate_texts)
    assert all("Facture n°" not in text for text in candidate_texts)
    assert all("n° client" not in text for text in candidate_texts)
    assert all("ACME Telecom SA" not in text for text in candidate_texts)
    assert all(text != "31,99 EUR" for text in candidate_texts)


def test_run_document_preview_keeps_scientific_born_digital_page_native(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scientific-born-digital.pdf"
    _make_scientific_born_digital_pdf(pdf_path)

    result = run_document_preview(
        pdf_path=pdf_path,
        output_dir=tmp_path,
        selected_pages=[1],
        translate_text_fn=lambda text: f"EN {text}",
        artifact_stem="scientific_native",
    )

    assert result["preview_mode"] == "native_overlay"
    assert result["routing_report"]["pdf_kind"] == "born_digital"
    assert result["routing_report"]["route_summary"] == {"native_only": 1}

    page_report = result["routing_report"]["pages"][0]
    assert page_report["image_count"] == 0
    assert page_report["ocr_candidate_count"] == 0
    assert page_report["ignored_ocr_image_reason_summary"] == {}
    assert page_report["excluded_role_summary"] == {}

    role_summary = {}
    for block in result["preview_result"]["document_ir"]["pages"][0]["text_blocks"]:
        role_summary[block["role"]] = role_summary.get(block["role"], 0) + 1
    assert role_summary == {
        "caption": 1,
        "content": 5,
        "slide_title": 1,
    }

    overlay_ready = result["preview_result"]["overlay_ready_report"]
    overlay_page = overlay_ready["pages"][0]
    candidate_texts = [candidate["text"] for candidate in overlay_page["candidates"]]

    assert overlay_page["candidate_block_count"] == 7
    assert "ETUDE DES JONCTIONS P/N EN REGIME DYNAMIQUE" in candidate_texts
    assert "I = I_s (exp(qV / kT) - 1)" in candidate_texts
    assert any(text.startswith("Figure 1 : Profil qualitatif") for text in candidate_texts)
    assert any("semi-conducteurs" in text for text in candidate_texts)


def test_run_document_preview_marks_simple_table_rows_as_overlay_candidates(tmp_path: Path) -> None:
    pdf_path = tmp_path / "simple-table.pdf"
    _make_simple_table_pdf(pdf_path)

    result = run_document_preview(
        pdf_path=pdf_path,
        output_dir=tmp_path,
        selected_pages=[1],
        translate_text_fn=lambda text: f"EN {text}",
        artifact_stem="simple_table",
    )

    assert result["preview_mode"] == "native_overlay"
    assert result["routing_report"]["pdf_kind"] == "born_digital"
    assert result["routing_report"]["route_summary"] == {"native_only": 1}

    page_report = result["routing_report"]["pages"][0]
    assert page_report["image_count"] == 0
    assert page_report["ocr_candidate_count"] == 0
    assert page_report["excluded_role_summary"] == {}

    role_summary = {}
    for block in result["preview_result"]["document_ir"]["pages"][0]["text_blocks"]:
        role_summary[block["role"]] = role_summary.get(block["role"], 0) + 1
    assert role_summary == {
        "caption": 1,
        "content": 1,
        "slide_title": 1,
        "table_cell": 3,
        "table_header": 1,
    }

    overlay_page = result["preview_result"]["overlay_ready_report"]["pages"][0]
    candidate_texts = [candidate["text"] for candidate in overlay_page["candidates"]]

    assert overlay_page["candidate_block_count"] == 7
    assert "Parametre\nValeur\nUnite" in candidate_texts
    assert "Tension directe\n0,72\nV" in candidate_texts
    assert "Temperature\n300\nK" in candidate_texts
    assert any(text.startswith("Tableau 1 : Parametres") for text in candidate_texts)
