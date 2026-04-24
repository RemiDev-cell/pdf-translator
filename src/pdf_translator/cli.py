from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich import print

from pdf_translator.config import settings
from pdf_translator.compose.overlay import (
    build_pre_overlay_report,
    build_replacement_plan,
    build_translation_preview_report,
    build_translation_preview_segments,
    overlay_prototype_summary_to_text,
    pre_overlay_report_to_text,
    render_overlay_prototype,
    replacement_plan_to_text,
    render_pre_overlay_diagnostics,
    translation_preview_report_to_text,
    write_overlay_prototype_summary,
    write_pre_overlay_report,
    write_replacement_plan,
    write_translation_preview_report,
)
from pdf_translator.logging_utils import configure_logging
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
    write_fusion_replacement_plan,
    write_fusion_overlay_diagnostics_summary,
    write_fusion_translation_preview_report,
    write_native_ocr_fusion_plan,
    write_native_ocr_fusion_report,
    write_ocr_candidate_report,
    write_ocr_overlay_strategy_report,
    write_ocr_review_report,
)
from pdf_translator.ocr.experiment import run_ocr_experiment
from pdf_translator.extract.pymupdf_extract import extract_document
from pdf_translator.pipeline import run_extract_only
from pdf_translator.routing import (
    build_document_routing_report,
    build_ocr_candidate_report,
    ocr_candidate_report_to_text,
    routing_report_to_text,
)
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


@app.command()
def replacement_plan(
    pdf_path: Path,
    pages: str = "10,22",
) -> None:
    """Construit un plan de remplacement à partir du preview de traduction."""
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

    translation_report = build_translation_preview_report(segments_report, _translate_region)
    plan = build_replacement_plan(translation_report)
    stem = f"{pdf_path.stem}_replacement_plan"
    json_path, text_path = write_replacement_plan(plan, settings.debug_dir, stem)
    print(replacement_plan_to_text(plan))
    print(f"[green]Replacement-plan JSON écrit dans :[/green] {json_path}")
    print(f"[green]Replacement-plan texte écrit dans :[/green] {text_path}")


@app.command()
def overlay_prototype(
    pdf_path: Path,
    plan_json: Optional[Path] = None,
) -> None:
    """Génère un premier PDF d'overlay en n'appliquant que les remplacements low-risk déjà traduits."""
    configure_logging()
    if plan_json is None:
        plan_json = settings.debug_dir / f"{pdf_path.stem}_replacement_plan.json"

    replacement_plan_data = json.loads(plan_json.read_text(encoding="utf-8"))
    stem = f"{pdf_path.stem}_overlay_prototype"
    pdf_output_path, summary = render_overlay_prototype(
        pdf_path=pdf_path,
        replacement_plan=replacement_plan_data,
        output_dir=settings.debug_dir,
        stem=stem,
    )
    summary_path = write_overlay_prototype_summary(summary, settings.debug_dir, stem)
    print(overlay_prototype_summary_to_text(summary))
    print(f"[green]Overlay prototype PDF écrit dans :[/green] {pdf_output_path}")
    print(f"[green]Overlay prototype résumé écrit dans :[/green] {summary_path}")


@app.command()
def routing_report(
    pdf_path: Path,
    pages: Optional[str] = None,
) -> None:
    """Construit un rapport de routage natif/OCR pour preparer la future branche OCR."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages) if pages else None
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    report = build_document_routing_report(document_ir, selected_pages)
    print(routing_report_to_text(report))



@app.command()
def ocr_candidates(
    pdf_path: Path,
    pages: Optional[str] = None,
) -> None:
    """Construit un rapport des regions candidates a une future branche OCR."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages) if pages else None
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    report = build_ocr_candidate_report(document_ir, selected_pages)
    print(ocr_candidate_report_to_text(report))



@app.command()
def ocr_dry_run(
    pdf_path: Path,
    pages: Optional[str] = None,
    backend: Optional[str] = None,
) -> None:
    """Extrait les crops PNG des regions OCR candidates et ecrit un manifeste de debug."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages) if pages else None
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    report = build_ocr_candidate_report(document_ir, selected_pages)
    stem = f"{pdf_path.stem}_ocr_dry_run"
    json_path, text_path = write_ocr_candidate_report(report, settings.debug_dir, stem)
    manifest_path, image_paths = run_ocr_debug_pipeline(
        pdf_path=pdf_path,
        report=report,
        output_dir=settings.debug_dir,
        stem=stem,
        backend=backend,
    )
    print(ocr_candidate_report_to_text(report))
    print(f"[green]OCR candidate JSON ecrit dans :[/green] {json_path}")
    print(f"[green]OCR candidate texte ecrit dans :[/green] {text_path}")
    print(f"[green]OCR dry-run manifeste ecrit dans :[/green] {manifest_path}")
    if image_paths:
        print(f"[green]Premier crop OCR ecrit dans :[/green] {image_paths[0]}")
        print(f"[green]Nombre de crops OCR generes :[/green] {len(image_paths)}")



@app.command()
def ocr_review(
    manifest_json: Optional[Path] = None,
) -> None:
    """Construit un rapport lisible de revue OCR a partir du manifeste de dry-run."""
    configure_logging()
    if manifest_json is None:
        manifest_json = settings.debug_dir / "supportpourocr01_ocr_dry_run_manifest.json"

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    report = build_ocr_review_report(manifest)
    stem = manifest_json.stem.replace("_manifest", "_review")
    json_path, text_path = write_ocr_review_report(report, settings.debug_dir, stem)
    print(ocr_review_report_to_text(report))
    print(f"[green]OCR review JSON ecrit dans :[/green] {json_path}")
    print(f"[green]OCR review texte ecrit dans :[/green] {text_path}")



@app.command()
def fusion_review(
    pdf_path: Path,
    manifest_json: Optional[Path] = None,
    pages: Optional[str] = None,
) -> None:
    """Construit un rapport combine texte natif + OCR par page sans toucher a l'overlay final."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages) if pages else None
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    overlay_ready = build_overlay_ready_report(
        document_ir,
        selected_pages or [page["page_number"] for page in document_ir.get("pages", [])],
    )

    if manifest_json is None:
        manifest_json = settings.debug_dir / f"{pdf_path.stem}_ocr_dry_run_manifest.json"

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    ocr_review = build_ocr_review_report(manifest)
    report = build_native_ocr_fusion_report(overlay_ready, ocr_review)
    stem = f"{pdf_path.stem}_fusion_review"
    json_path, text_path = write_native_ocr_fusion_report(report, settings.debug_dir, stem)
    print(native_ocr_fusion_report_to_text(report))
    print(f"[green]Fusion review JSON ecrit dans :[/green] {json_path}")
    print(f"[green]Fusion review texte ecrit dans :[/green] {text_path}")



@app.command()
def fusion_plan(
    pdf_path: Path,
    manifest_json: Optional[Path] = None,
    pages: Optional[str] = None,
) -> None:
    """Construit un plan de segments source natifs+OCR pret pour une future traduction."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages) if pages else None
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    overlay_ready = build_overlay_ready_report(
        document_ir,
        selected_pages or [page["page_number"] for page in document_ir.get("pages", [])],
    )

    if manifest_json is None:
        manifest_json = settings.debug_dir / f"{pdf_path.stem}_ocr_dry_run_manifest.json"

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    ocr_review = build_ocr_review_report(manifest)
    plan = build_native_ocr_fusion_plan(overlay_ready, ocr_review)
    stem = f"{pdf_path.stem}_fusion_plan"
    json_path, text_path = write_native_ocr_fusion_plan(plan, settings.debug_dir, stem)
    print(native_ocr_fusion_plan_to_text(plan))
    print(f"[green]Fusion plan JSON ecrit dans :[/green] {json_path}")
    print(f"[green]Fusion plan texte ecrit dans :[/green] {text_path}")



@app.command()
def fusion_translation_preview(
    pdf_path: Path,
    manifest_json: Optional[Path] = None,
    pages: Optional[str] = None,
) -> None:
    """Traduit le fusion plan natif+OCR pour produire un preview mixte sans toucher a l'overlay."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages) if pages else None
    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    overlay_ready = build_overlay_ready_report(
        document_ir,
        selected_pages or [page["page_number"] for page in document_ir.get("pages", [])],
    )

    if manifest_json is None:
        manifest_json = settings.debug_dir / f"{pdf_path.stem}_ocr_dry_run_manifest.json"

    manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
    ocr_review = build_ocr_review_report(manifest)
    plan = build_native_ocr_fusion_plan(overlay_ready, ocr_review)

    def _translate_segment(text: str) -> str:
        return translate_text(text)

    report = build_fusion_translation_preview_report(plan, _translate_segment)
    stem = f"{pdf_path.stem}_fusion_translation_preview"
    json_path, text_path = write_fusion_translation_preview_report(report, settings.debug_dir, stem)
    print(fusion_translation_preview_report_to_text(report))
    print(f"[green]Fusion translation preview JSON ecrit dans :[/green] {json_path}")
    print(f"[green]Fusion translation preview texte ecrit dans :[/green] {text_path}")


@app.command()
def fusion_replacement_plan(
    pdf_path: Path,
    preview_json: Optional[Path] = None,
    manifest_json: Optional[Path] = None,
    pages: Optional[str] = None,
) -> None:
    """Construit un plan de remplacement mixte natif+OCR sans appliquer l'overlay."""
    configure_logging()
    if preview_json is None:
        selected_pages = _parse_pages_arg(pages) if pages else None
        document = extract_document(pdf_path)
        document_ir = annotate_repeated_blocks(document.model_dump())
        overlay_ready = build_overlay_ready_report(
            document_ir,
            selected_pages or [page["page_number"] for page in document_ir.get("pages", [])],
        )

        if manifest_json is None:
            manifest_json = settings.debug_dir / f"{pdf_path.stem}_ocr_dry_run_manifest.json"

        manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
        ocr_review = build_ocr_review_report(manifest)
        plan = build_native_ocr_fusion_plan(overlay_ready, ocr_review)

        def _translate_segment(text: str) -> str:
            return translate_text(text)

        preview_report = build_fusion_translation_preview_report(plan, _translate_segment)
    else:
        preview_report = json.loads(preview_json.read_text(encoding="utf-8"))

    replacement_plan_data = build_fusion_replacement_plan(preview_report)
    stem = f"{pdf_path.stem}_fusion_replacement_plan"
    json_path, text_path = write_fusion_replacement_plan(
        replacement_plan_data,
        settings.debug_dir,
        stem,
    )
    print(fusion_replacement_plan_to_text(replacement_plan_data))
    print(f"[green]Fusion replacement plan JSON ecrit dans :[/green] {json_path}")
    print(f"[green]Fusion replacement plan texte ecrit dans :[/green] {text_path}")


@app.command()
def fusion_overlay_diagnostics(
    pdf_path: Path,
    plan_json: Optional[Path] = None,
    manifest_json: Optional[Path] = None,
    pages: Optional[str] = None,
) -> None:
    """Rend un PDF diagnostic mixte: natif applique, OCR annote en attente."""
    configure_logging()
    if plan_json is None:
        selected_pages = _parse_pages_arg(pages) if pages else None
        document = extract_document(pdf_path)
        document_ir = annotate_repeated_blocks(document.model_dump())
        overlay_ready = build_overlay_ready_report(
            document_ir,
            selected_pages or [page["page_number"] for page in document_ir.get("pages", [])],
        )

        if manifest_json is None:
            manifest_json = settings.debug_dir / f"{pdf_path.stem}_ocr_dry_run_manifest.json"

        manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
        ocr_review = build_ocr_review_report(manifest)
        plan = build_native_ocr_fusion_plan(overlay_ready, ocr_review)

        def _translate_segment(text: str) -> str:
            return translate_text(text)

        preview_report = build_fusion_translation_preview_report(plan, _translate_segment)
        replacement_plan_data = build_fusion_replacement_plan(preview_report)
    else:
        replacement_plan_data = json.loads(plan_json.read_text(encoding="utf-8"))

    stem = f"{pdf_path.stem}_fusion_overlay_diagnostics"
    pdf_output_path, summary, image_paths = render_fusion_overlay_diagnostics(
        pdf_path=pdf_path,
        fusion_replacement_plan=replacement_plan_data,
        output_dir=settings.debug_dir,
        stem=stem,
    )
    summary_path = write_fusion_overlay_diagnostics_summary(summary, settings.debug_dir, stem)
    print(fusion_overlay_diagnostics_summary_to_text(summary))
    print(f"[green]Fusion overlay diagnostics PDF ecrit dans :[/green] {pdf_output_path}")
    print(f"[green]Fusion overlay diagnostics resume ecrit dans :[/green] {summary_path}")
    if image_paths:
        print(f"[green]Premiere image ecrite dans :[/green] {image_paths[0]}")
        print(f"[green]Nombre d'images generees :[/green] {len(image_paths)}")


@app.command()
def ocr_overlay_strategy(
    pdf_path: Path,
    plan_json: Optional[Path] = None,
    manifest_json: Optional[Path] = None,
    pages: Optional[str] = None,
) -> None:
    """Recommande une strategie de rendu pour les remplacements OCR."""
    configure_logging()
    if plan_json is None:
        selected_pages = _parse_pages_arg(pages) if pages else None
        document = extract_document(pdf_path)
        document_ir = annotate_repeated_blocks(document.model_dump())
        overlay_ready = build_overlay_ready_report(
            document_ir,
            selected_pages or [page["page_number"] for page in document_ir.get("pages", [])],
        )

        if manifest_json is None:
            manifest_json = settings.debug_dir / f"{pdf_path.stem}_ocr_dry_run_manifest.json"

        manifest = json.loads(manifest_json.read_text(encoding="utf-8"))
        ocr_review = build_ocr_review_report(manifest)
        plan = build_native_ocr_fusion_plan(overlay_ready, ocr_review)

        def _translate_segment(text: str) -> str:
            return translate_text(text)

        preview_report = build_fusion_translation_preview_report(plan, _translate_segment)
        replacement_plan_data = build_fusion_replacement_plan(preview_report)
    else:
        replacement_plan_data = json.loads(plan_json.read_text(encoding="utf-8"))

    report = build_ocr_overlay_strategy_report(replacement_plan_data)
    stem = f"{pdf_path.stem}_ocr_overlay_strategy"
    json_path, text_path = write_ocr_overlay_strategy_report(report, settings.debug_dir, stem)
    print(ocr_overlay_strategy_report_to_text(report))
    print(f"[green]OCR overlay strategy JSON ecrit dans :[/green] {json_path}")
    print(f"[green]OCR overlay strategy texte ecrit dans :[/green] {text_path}")


@app.command()
def ocr_experiment(
    pdf_path: Path,
    pages: Optional[str] = None,
    backend: Optional[str] = None,
) -> None:
    """Execute toute la chaine OCR experimentale et ecrit les artefacts de debug."""
    configure_logging()
    selected_pages = _parse_pages_arg(pages) if pages else None
    document = extract_document(pdf_path)
    result = run_ocr_experiment(
        pdf_path=pdf_path,
        document_ir=document.model_dump(),
        output_dir=settings.debug_dir,
        translate_text_fn=translate_text,
        selected_pages=selected_pages,
        backend=backend,
    )
    paths = result["paths"]

    print("[bold]OCR experiment complete[/bold]")
    print(ocr_candidate_report_to_text(result["ocr_candidate_report"]))
    print(ocr_review_report_to_text(result["ocr_review"]))
    print(native_ocr_fusion_plan_to_text(result["fusion_plan"]))
    print(fusion_replacement_plan_to_text(result["fusion_replacement_plan"]))
    print(ocr_overlay_strategy_report_to_text(result["ocr_strategy_report"]))
    print(fusion_overlay_diagnostics_summary_to_text(result["diagnostics_summary"]))
    print(f"[green]OCR candidate report:[/green] {paths['ocr_candidate_json']} / {paths['ocr_candidate_text']}")
    print(f"[green]OCR manifest:[/green] {paths['manifest']}")
    print(f"[green]OCR review:[/green] {paths['ocr_review_json']} / {paths['ocr_review_text']}")
    print(f"[green]Fusion review:[/green] {paths['fusion_review_json']} / {paths['fusion_review_text']}")
    print(f"[green]Fusion plan:[/green] {paths['fusion_plan_json']} / {paths['fusion_plan_text']}")
    print(f"[green]Fusion translation preview:[/green] {paths['fusion_translation_json']} / {paths['fusion_translation_text']}")
    print(f"[green]Fusion replacement plan:[/green] {paths['fusion_replacement_json']} / {paths['fusion_replacement_text']}")
    print(f"[green]OCR overlay strategy:[/green] {paths['ocr_strategy_json']} / {paths['ocr_strategy_text']}")
    print(f"[green]Fusion overlay diagnostics:[/green] {paths['diagnostics_pdf']} / {paths['diagnostics_summary']}")
    if paths["crop_paths"]:
        print(f"[green]OCR crops generated:[/green] {len(paths['crop_paths'])}")
    if paths["diagnostic_images"]:
        print(f"[green]Diagnostic images generated:[/green] {len(paths['diagnostic_images'])}")



if __name__ == "__main__":
    app()
