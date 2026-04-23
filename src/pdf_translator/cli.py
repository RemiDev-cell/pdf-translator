from __future__ import annotations

from pathlib import Path

import typer
from rich import print

from pdf_translator.config import settings
from pdf_translator.compose.overlay import (
    build_pre_overlay_report,
    build_translation_preview_report,
    build_translation_preview_segments,
    pre_overlay_report_to_text,
    render_pre_overlay_diagnostics,
    translation_preview_report_to_text,
    write_pre_overlay_report,
    write_translation_preview_report,
)
from pdf_translator.logging_utils import configure_logging
from pdf_translator.extract.pymupdf_extract import extract_document
from pdf_translator.pipeline import run_extract_only
from pdf_translator.qa.checks import (
    annotate_repeated_blocks,
    audit_report_to_text,
    build_page_audit,
    build_overlay_ready_report,
    overlay_ready_report_to_text,
    write_audit_report,
    write_overlay_ready_report,
)
from pdf_translator.translate.placeholders import protect_text, restore_text
from pdf_translator.translate.translator import translate_text


app = typer.Typer(no_args_is_help=True)


def _parse_pages_arg(pages: str) -> list[int]:
    values = []
    for item in pages.split(","):
        stripped = item.strip()
        if not stripped:
            continue
        values.append(int(stripped))
    return values


@app.command()
def inspect(pdf_path: Path) -> None:
    """Inspecte un PDF et écrit une représentation intermédiaire JSON."""
    configure_logging()
    output_path = run_extract_only(pdf_path)
    print(f"[green]IR écrite dans :[/green] {output_path}")


@app.command()
def audit_sample(
    pdf_path: Path,
    pages: str = "1,3,10,22,80,120,160",
) -> None:
    """Audit ciblé sur un sous-ensemble de pages, sans traduction."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages)
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    report = build_page_audit(document_ir, selected_pages)
    stem = f"{pdf_path.stem}_audit_sample"
    json_path, text_path = write_audit_report(report, settings.debug_dir, stem)
    print(audit_report_to_text(report))
    print(f"[green]Audit JSON écrit dans :[/green] {json_path}")
    print(f"[green]Audit texte écrit dans :[/green] {text_path}")


@app.command()
def overlay_ready(
    pdf_path: Path,
    pages: str = "1,3,10,22,80,120,160",
) -> None:
    """Construit un rapport compact des blocs content candidats à l'overlay."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages)
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    report = build_overlay_ready_report(document_ir, selected_pages)
    stem = f"{pdf_path.stem}_overlay_ready"
    json_path, text_path = write_overlay_ready_report(report, settings.debug_dir, stem)
    print(overlay_ready_report_to_text(report))
    print(f"[green]Overlay-ready JSON écrit dans :[/green] {json_path}")
    print(f"[green]Overlay-ready texte écrit dans :[/green] {text_path}")


@app.command()
def pre_overlay(
    pdf_path: Path,
    pages: str = "1,3,10,22,80,120,160",
) -> None:
    """Construit les regions candidates au futur overlay à partir des blocs content."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages)
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    overlay_ready_report = build_overlay_ready_report(document_ir, selected_pages)
    report = build_pre_overlay_report(overlay_ready_report)
    stem = f"{pdf_path.stem}_pre_overlay"
    json_path, text_path = write_pre_overlay_report(report, settings.debug_dir, stem)
    print(pre_overlay_report_to_text(report))
    print(f"[green]Pre-overlay JSON écrit dans :[/green] {json_path}")
    print(f"[green]Pre-overlay texte écrit dans :[/green] {text_path}")


@app.command()
def overlay_preview(
    pdf_path: Path,
    pages: str = "1,3,10,22,80,120,160",
) -> None:
    """Génère un PDF annoté et des PNG de diagnostic pour les regions pre-overlay."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages)
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    overlay_ready_report = build_overlay_ready_report(document_ir, selected_pages)
    report = build_pre_overlay_report(overlay_ready_report)
    stem = f"{pdf_path.stem}_overlay_preview"
    pdf_output_path, image_paths = render_pre_overlay_diagnostics(
        pdf_path=pdf_path,
        pre_overlay_report=report,
        output_dir=settings.debug_dir,
        stem=stem,
    )
    print(f"[green]Overlay preview PDF écrit dans :[/green] {pdf_output_path}")
    if image_paths:
        print(f"[green]Première image écrite dans :[/green] {image_paths[0]}")
        print(f"[green]Nombre d'images générées :[/green] {len(image_paths)}")


@app.command()
def translation_preview(
    pdf_path: Path,
    pages: str = "10,22",
) -> None:
    """Génère un aperçu de traduction lisible sans identifiants de blocs."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages)
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    overlay_ready_report = build_overlay_ready_report(document_ir, selected_pages)
    pre_overlay_report = build_pre_overlay_report(overlay_ready_report)
    segments_report = build_translation_preview_segments(pre_overlay_report, selected_pages)

    def _translate_region(text: str) -> str:
        protected_text, placeholders = protect_text(text)
        translated_text = translate_text(protected_text)
        return restore_text(translated_text, placeholders)

    report = build_translation_preview_report(segments_report, _translate_region)
    stem = f"{pdf_path.stem}_translation_preview"
    json_path, text_path = write_translation_preview_report(report, settings.debug_dir, stem)
    print(translation_preview_report_to_text(report))
    print(f"[green]Translation preview JSON écrit dans :[/green] {json_path}")
    print(f"[green]Translation preview texte écrit dans :[/green] {text_path}")


if __name__ == "__main__":
    app()
