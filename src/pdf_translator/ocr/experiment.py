from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pdf_translator.ocr.debug import (
    build_fusion_replacement_plan,
    build_fusion_translation_preview_report,
    build_native_ocr_fusion_plan,
    build_native_ocr_fusion_report,
    build_ocr_overlay_strategy_report,
    build_ocr_page_translation_preview_report,
    build_ocr_review_report,
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
from pdf_translator.qa.checks import annotate_repeated_blocks, build_overlay_ready_report
from pdf_translator.routing import build_ocr_candidate_report


def run_ocr_experiment(
    pdf_path: Path,
    document_ir: dict[str, Any],
    output_dir: Path,
    translate_text_fn: Callable[[str], str],
    selected_pages: list[int] | None = None,
    backend: str | None = None,
    artifact_stem: str | None = None,
) -> dict[str, Any]:
    annotated_ir = annotate_repeated_blocks(document_ir)
    page_numbers = selected_pages or [page["page_number"] for page in annotated_ir.get("pages", [])]
    stem = artifact_stem or pdf_path.stem

    overlay_ready = build_overlay_ready_report(annotated_ir, page_numbers)
    ocr_candidate_report = build_ocr_candidate_report(annotated_ir, selected_pages)
    ocr_candidate_json, ocr_candidate_text = write_ocr_candidate_report(
        ocr_candidate_report,
        output_dir,
        f"{stem}_ocr_dry_run",
    )
    manifest_path, crop_paths = run_ocr_debug_pipeline(
        pdf_path=pdf_path,
        report=ocr_candidate_report,
        output_dir=output_dir,
        stem=f"{stem}_ocr_dry_run",
        backend=backend,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ocr_review = build_ocr_review_report(manifest)
    ocr_review_json, ocr_review_text = write_ocr_review_report(
        ocr_review,
        output_dir,
        f"{stem}_ocr_dry_run_review",
    )

    fusion_review_report = build_native_ocr_fusion_report(overlay_ready, ocr_review)
    fusion_review_json, fusion_review_text = write_native_ocr_fusion_report(
        fusion_review_report,
        output_dir,
        f"{stem}_fusion_review",
    )

    fusion_plan = build_native_ocr_fusion_plan(overlay_ready, ocr_review)
    fusion_plan_json, fusion_plan_text = write_native_ocr_fusion_plan(
        fusion_plan,
        output_dir,
        f"{stem}_fusion_plan",
    )

    fusion_translation_preview = build_fusion_translation_preview_report(
        fusion_plan,
        translate_text_fn,
    )
    fusion_translation_json, fusion_translation_text = write_fusion_translation_preview_report(
        fusion_translation_preview,
        output_dir,
        f"{stem}_fusion_translation_preview",
    )

    fusion_replacement_plan = build_fusion_replacement_plan(fusion_translation_preview)
    fusion_replacement_json, fusion_replacement_text = write_fusion_replacement_plan(
        fusion_replacement_plan,
        output_dir,
        f"{stem}_fusion_replacement_plan",
    )

    ocr_strategy_report = build_ocr_overlay_strategy_report(fusion_replacement_plan)
    ocr_strategy_json, ocr_strategy_text = write_ocr_overlay_strategy_report(
        ocr_strategy_report,
        output_dir,
        f"{stem}_ocr_overlay_strategy",
    )

    page_translation_preview = build_ocr_page_translation_preview_report(
        fusion_translation_preview,
        ocr_strategy_report,
    )
    page_translation_json, page_translation_text = write_ocr_page_translation_preview_report(
        page_translation_preview,
        output_dir,
        f"{stem}_ocr_page_translation_preview",
    )

    diagnostics_pdf, diagnostics_summary, diagnostic_images = render_fusion_overlay_diagnostics(
        pdf_path=pdf_path,
        fusion_replacement_plan=fusion_replacement_plan,
        output_dir=output_dir,
        stem=f"{stem}_fusion_overlay_diagnostics",
    )
    diagnostics_summary_path = write_fusion_overlay_diagnostics_summary(
        diagnostics_summary,
        output_dir,
        f"{stem}_fusion_overlay_diagnostics",
    )

    return {
        "ocr_candidate_report": ocr_candidate_report,
        "ocr_review": ocr_review,
        "fusion_plan": fusion_plan,
        "fusion_translation_preview": fusion_translation_preview,
        "fusion_replacement_plan": fusion_replacement_plan,
        "ocr_strategy_report": ocr_strategy_report,
        "page_translation_preview": page_translation_preview,
        "diagnostics_summary": diagnostics_summary,
        "paths": {
            "ocr_candidate_json": ocr_candidate_json,
            "ocr_candidate_text": ocr_candidate_text,
            "manifest": manifest_path,
            "ocr_review_json": ocr_review_json,
            "ocr_review_text": ocr_review_text,
            "fusion_review_json": fusion_review_json,
            "fusion_review_text": fusion_review_text,
            "fusion_plan_json": fusion_plan_json,
            "fusion_plan_text": fusion_plan_text,
            "fusion_translation_json": fusion_translation_json,
            "fusion_translation_text": fusion_translation_text,
            "fusion_replacement_json": fusion_replacement_json,
            "fusion_replacement_text": fusion_replacement_text,
            "ocr_strategy_json": ocr_strategy_json,
            "ocr_strategy_text": ocr_strategy_text,
            "page_translation_json": page_translation_json,
            "page_translation_text": page_translation_text,
            "diagnostics_pdf": diagnostics_pdf,
            "diagnostics_summary": diagnostics_summary_path,
            "crop_paths": crop_paths,
            "diagnostic_images": diagnostic_images,
        },
    }
