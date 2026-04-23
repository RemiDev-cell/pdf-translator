from __future__ import annotations

from pathlib import Path
import textwrap

import fitz


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 56
TEXT_WIDTH = PAGE_WIDTH - (2 * MARGIN)
FONT = "helv"


def add_title(page: fitz.Page, text: str, y: float) -> float:
    rect = fitz.Rect(MARGIN, y, PAGE_WIDTH - MARGIN, y + 36)
    page.insert_textbox(rect, text, fontsize=20, fontname=FONT, align=0)
    return y + 30


def add_heading(page: fitz.Page, text: str, y: float) -> float:
    rect = fitz.Rect(MARGIN, y, PAGE_WIDTH - MARGIN, y + 24)
    page.insert_textbox(rect, text, fontsize=13, fontname=FONT, align=0)
    return y + 20


def add_paragraph(page: fitz.Page, text: str, y: float, width: float = TEXT_WIDTH) -> float:
    max_chars = max(40, int(width / 5.4))
    wrapped_parts: list[str] = []

    for raw_paragraph in text.split("\n"):
        if not raw_paragraph.strip():
            wrapped_parts.append("")
            continue
        wrapped_parts.extend(textwrap.wrap(raw_paragraph, width=max_chars))

    lines = wrapped_parts or [text]
    line_height = 14

    for index, line in enumerate(lines):
        line_y = y + (index * line_height)
        if line_y > PAGE_HEIGHT - MARGIN:
            raise RuntimeError("Paragraph did not fit in the page layout.")
        page.insert_text((MARGIN, line_y), line, fontsize=10.5, fontname=FONT)

    return y + (len(lines) * line_height) + 10


def add_bullet_list(page: fitz.Page, items: list[str], y: float) -> float:
    lines = "\n".join(f"- {item}" for item in items)
    return add_paragraph(page, lines, y)


def add_table(page: fitz.Page, y: float, headers: list[str], rows: list[list[str]]) -> float:
    col_widths = [90, 115, 110, 110]
    row_height = 22
    x = MARGIN

    for row_index, row in enumerate([headers] + rows):
        cursor_x = x
        top = y + (row_index * row_height)
        bottom = top + row_height

        for col_index, cell in enumerate(row):
            width = col_widths[col_index]
            rect = fitz.Rect(cursor_x, top, cursor_x + width, bottom)
            page.draw_rect(rect, color=(0, 0, 0), width=0.6)
            page.insert_textbox(rect + (4, 4, -4, -4), cell, fontsize=9.5, fontname=FONT, align=0)
            cursor_x += width

    return y + ((len(rows) + 1) * row_height) + 18


def add_caption(page: fitz.Page, text: str, y: float) -> float:
    rect = fitz.Rect(MARGIN + 20, y, PAGE_WIDTH - MARGIN, y + 22)
    page.insert_textbox(rect, text, fontsize=9.5, fontname=FONT, align=0)
    return y + 18


def build_simple_fr(output_dir: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = 60

    y = add_title(page, "Rapport experimental simplifie", y)
    y = add_paragraph(
        page,
        (
            "Ce document de test verifie la traduction d'un texte francais continu dans un PDF "
            "born-digital. L'objectif est de conserver la mise en page, les lignes et les segments "
            "sensibles sans perturber les elements techniques deja stables."
        ),
        y,
    )
    y = add_paragraph(
        page,
        (
            "Le prototype a ete deploye le 2026-04-23T09:41:12.120Z sur la station d'essai A3. "
            "La version logicielle utilisee est 2.4.18, le commit associe est "
            "a4b8c0de12fa44ff99112233445566778899aabb et la documentation complete reste accessible "
            "a l'adresse https://labo.example.org/projets/pdf-translator."
        ),
        y,
    )
    y = add_bullet_list(
        page,
        [
            "Temperature moyenne du reacteur: 37.5 C",
            "Concentration de glucose: 4.2 mmol/L",
            "Adresse de contact: support.lab@example.org",
            "Le sous-systeme Sensor Bridge reste deja nomme en anglais",
        ],
        y,
    )
    y = add_paragraph(
        page,
        (
            "Les observations montrent une amelioration nette de la stabilite mecanique, mais une "
            "augmentation legere du bruit de mesure au-dela de 15 min d'acquisition. Une verification "
            "croisee avec le journal Quality Check est recommande."
        ),
        y,
    )

    output_path = output_dir / "simple-fr.pdf"
    doc.save(output_path)
    doc.close()


def build_scientifique_mixte(output_dir: Path) -> None:
    doc = fitz.open()

    page1 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = 60
    y = add_title(page1, "Note scientifique mixte", y)
    y = add_heading(page1, "1. Contexte", y)
    y = add_paragraph(
        page1,
        (
            "Cette note etudie l'effet d'un revetement poreux sur le transfert thermique dans un "
            "module de refroidissement compact. Le protocole combine des paragraphes rediges en "
            "francais, des labels techniques, des unites scientifiques et quelques expressions deja "
            "en anglais comme baseline noise ou flow control."
        ),
        y,
    )
    y = add_heading(page1, "2. Resultats numeriques", y)
    y = add_table(
        page1,
        y,
        headers=["Serie", "Condition", "Mesure", "Commentaire"],
        rows=[
            ["A", "0.8 m/s", "12.4 W", "Variation faible"],
            ["B", "1.1 m/s", "15.7 W", "Gain visible"],
            ["C", "1.4 m/s", "18.1 W", "Noise stable"],
        ],
    )
    y = add_paragraph(
        page1,
        (
            "La figure 1 indique que la temperature de surface diminue plus vite lorsque la rugosite "
            "effective depasse 1.2 mm. En revanche, le rendement marginal chute apres 18 s de pompage "
            "continu, ce qui impose un arbitrage entre performance et consommation."
        ),
        y,
    )
    y = add_caption(page1, "Figure 1. Evolution de la temperature moyenne en fonction du debit.", y)

    page2 = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = 60
    y = add_heading(page2, "3. Notes de mise en oeuvre", y)
    y = add_bullet_list(
        page2,
        [
            "API locale: http://localhost:4000/v1",
            "Version du banc d'essai: 5.3.2",
            "Email de suivi: thermo-team@example.org",
            "Date du lot: 2026-04-18T17:05:44.009Z",
        ],
        y,
    )
    y = add_paragraph(
        page2,
        (
            "Pour les essais suivants, nous conserverons les termes Reynolds number, pressure drop et "
            "reference sensor dans leur forme anglaise afin de verifier que le pipeline ne sur-traduit "
            "pas les labels techniques deja acceptes par les chercheurs."
        ),
        y,
    )
    y = add_paragraph(
        page2,
        (
            "La reconstruction PDF n'est pas encore activee, mais la qualite du mapping ligne par ligne "
            "doit deja permettre de tester les futurs overlays. Une validation manuelle est prevue avant "
            "toute generalisation sur des articles de 20 pages."
        ),
        y,
    )

    output_path = output_dir / "scientifique-mixte.pdf"
    doc.save(output_path)
    doc.close()


def build_layout_tricky(output_dir: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = 60

    y = add_title(page, "Mise en page complexe de reference", y)

    left_rect = fitz.Rect(MARGIN, y, (PAGE_WIDTH / 2) - 12, PAGE_HEIGHT - 160)
    right_rect = fitz.Rect((PAGE_WIDTH / 2) + 12, y, PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 160)

    left_text = (
        "Resume. Ce bloc simule une premiere colonne avec des phrases assez courtes, des labels de "
        "section et des retours a la ligne frequents. Il doit aider a verifier que le batching garde "
        "le bon ordre logique meme lorsque la lecture visuelle ressemble a une maquette dense.\n\n"
        "Procedure. Le capteur primaire a mesure 98.4 kPa, puis 101.2 kPa apres recalibration. Le lien "
        "de controle est https://intranet.example.net/calibration et le ticket associe porte la version 7.2.11."
    )
    right_text = (
        "Observations. La seconde colonne contient des phrases plus longues et quelques marqueurs deja en "
        "anglais comme Sample ID, Peak Hold et Recovery Mode. Le texte ne doit pas etre fusionne avec la "
        "colonne de gauche.\n\n"
        "Conclusion. Une extraction propre ici donnera un bon signal avant d'attaquer les vrais PDF avec "
        "deux colonnes, encadres, tableaux et notes de bas de page."
    )

    left_used = page.insert_textbox(left_rect, left_text, fontsize=10.2, fontname=FONT, align=0)
    right_used = page.insert_textbox(right_rect, right_text, fontsize=10.2, fontname=FONT, align=0)
    if left_used < 0 or right_used < 0:
        raise RuntimeError("Two-column layout did not fit in the page layout.")

    box_top = PAGE_HEIGHT - 150
    callout = fitz.Rect(MARGIN, box_top, PAGE_WIDTH - MARGIN, box_top + 74)
    page.draw_rect(callout, color=(0, 0, 0), width=0.8)
    page.insert_textbox(
        callout + (8, 8, -8, -8),
        (
            "Encadre de validation. Contact: qa-layout@example.org | Date: 2026-04-20T08:15:00.000Z | "
            "Build: 1.9.4 | Commit: bbccee99887766554433221100ffeeddccbbaa99"
        ),
        fontsize=10,
        fontname=FONT,
        align=0,
    )

    output_path = output_dir / "layout-tricky.pdf"
    doc.save(output_path)
    doc.close()


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    output_dir = project_root / "data" / "input"
    output_dir.mkdir(parents=True, exist_ok=True)

    build_simple_fr(output_dir)
    build_scientifique_mixte(output_dir)
    build_layout_tricky(output_dir)

    print("Generated PDFs:")
    for name in ["simple-fr.pdf", "scientifique-mixte.pdf", "layout-tricky.pdf"]:
        print(output_dir / name)


if __name__ == "__main__":
    main()
