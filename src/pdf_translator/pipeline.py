from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import requests

from pdf_translator.compose.overlay import (
    build_pre_overlay_report,
    build_replacement_plan,
    build_translation_preview_report,
    build_translation_preview_segments,
    render_overlay_prototype,
    write_overlay_prototype_summary,
    write_pre_overlay_report,
    write_replacement_plan,
    write_translation_preview_report,
)
from pdf_translator.config import settings
from pdf_translator.extract.pymupdf_extract import extract_document
from pdf_translator.logging_utils import get_logger
from pdf_translator.ocr.experiment import run_ocr_experiment
from pdf_translator.qa.checks import (
    annotate_repeated_blocks,
    build_overlay_ready_report,
    collect_role_summary,
    write_overlay_ready_report,
)
from pdf_translator.routing import build_document_routing_report, routing_report_to_text
from pdf_translator.translate.batching import (
    apply_batch_translations,
    build_batch_prompt,
    collect_translation_groups,
    make_translation_batches,
    parse_batch_response,
    validate_batch_output,
)
from pdf_translator.translate.placeholders import (
    is_translation_candidate,
    placeholders_are_preserved,
    protect_text,
    restore_text,
)
from pdf_translator.translate.translator import translate_batch, translate_text


logger = get_logger(__name__)


def _all_page_numbers(document_ir: dict[str, Any]) -> list[int]:
    return [int(page["page_number"]) for page in document_ir.get("pages", [])]


def _routing_requires_ocr(routing_report: dict[str, Any]) -> bool:
    return any(
        page.get("route") in {"native_plus_ocr_candidates", "ocr_only"}
        for page in routing_report.get("pages", [])
    )


def _write_routing_report(
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    text_path.write_text(routing_report_to_text(report), encoding="utf-8")
    return json_path, text_path


def _preserve_batch_text(batch: list[dict[str, str]]) -> dict[str, str]:
    return {
        line["segment_id"]: line["protected_text"]
        for group in batch
        for line in group["lines"]
    }


def run_document_preview(
    pdf_path: str | Path,
    output_dir: Path | None = None,
    selected_pages: list[int] | None = None,
    translate_text_fn: Callable[[str], str] = translate_text,
    backend: str | None = None,
    artifact_stem: str | None = None,
) -> dict[str, Any]:
    """Route selected pages to the native or native/OCR preview chain."""
    pdf_path = Path(pdf_path)
    output_dir = output_dir or settings.debug_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    page_numbers = selected_pages or _all_page_numbers(document_ir)
    stem = artifact_stem or f"{pdf_path.stem}_document_preview"

    routing_report = build_document_routing_report(document_ir, page_numbers)
    routing_json, routing_text = _write_routing_report(
        routing_report,
        output_dir,
        f"{stem}_routing",
    )

    if _routing_requires_ocr(routing_report):
        preview_mode = "native_ocr_fusion"
        preview_result = run_ocr_experiment(
            pdf_path=pdf_path,
            document_ir=document_ir,
            output_dir=output_dir,
            translate_text_fn=translate_text_fn,
            selected_pages=page_numbers,
            backend=backend,
            artifact_stem=stem,
        )
    else:
        preview_mode = "native_overlay"
        preview_result = run_native_overlay_preview(
            pdf_path=pdf_path,
            output_dir=output_dir,
            selected_pages=page_numbers,
            translate_text_fn=translate_text_fn,
            artifact_stem=stem,
        )

    return {
        "preview_mode": preview_mode,
        "routing_report": routing_report,
        "preview_result": preview_result,
        "paths": {
            "routing_json": routing_json,
            "routing_text": routing_text,
        },
    }


def run_native_overlay_preview(
    pdf_path: str | Path,
    output_dir: Path | None = None,
    selected_pages: list[int] | None = None,
    translate_text_fn: Callable[[str], str] = translate_text,
    artifact_stem: str | None = None,
) -> dict[str, Any]:
    """Run the native-text overlay preview chain and persist review artifacts."""
    pdf_path = Path(pdf_path)
    output_dir = output_dir or settings.debug_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    page_numbers = selected_pages or _all_page_numbers(document_ir)
    stem = artifact_stem or f"{pdf_path.stem}_native_preview"

    overlay_ready_report = build_overlay_ready_report(document_ir, page_numbers)
    overlay_ready_json, overlay_ready_text = write_overlay_ready_report(
        overlay_ready_report,
        output_dir,
        f"{stem}_overlay_ready",
    )

    pre_overlay_report = build_pre_overlay_report(overlay_ready_report)
    pre_overlay_json, pre_overlay_text = write_pre_overlay_report(
        pre_overlay_report,
        output_dir,
        f"{stem}_pre_overlay",
    )

    segments_report = build_translation_preview_segments(
        pre_overlay_report,
        page_numbers,
    )

    def _translate_region(text: str) -> str:
        protected_text, placeholders = protect_text(text)
        translated_text = translate_text_fn(protected_text)
        return restore_text(translated_text, placeholders)

    translation_preview_report = build_translation_preview_report(
        segments_report,
        _translate_region,
    )
    translation_preview_json, translation_preview_text = write_translation_preview_report(
        translation_preview_report,
        output_dir,
        f"{stem}_translation_preview",
    )

    replacement_plan = build_replacement_plan(
        translation_preview_report,
        overlay_ready_report=overlay_ready_report,
    )
    replacement_plan_json, replacement_plan_text = write_replacement_plan(
        replacement_plan,
        output_dir,
        f"{stem}_replacement_plan",
    )

    overlay_pdf, overlay_summary = render_overlay_prototype(
        pdf_path=pdf_path,
        replacement_plan=replacement_plan,
        output_dir=output_dir,
        stem=f"{stem}_overlay_prototype",
    )
    overlay_summary_text = write_overlay_prototype_summary(
        overlay_summary,
        output_dir,
        f"{stem}_overlay_prototype",
    )

    return {
        "document_ir": document_ir,
        "overlay_ready_report": overlay_ready_report,
        "pre_overlay_report": pre_overlay_report,
        "segments_report": segments_report,
        "translation_preview_report": translation_preview_report,
        "replacement_plan": replacement_plan,
        "overlay_summary": overlay_summary,
        "paths": {
            "overlay_ready_json": overlay_ready_json,
            "overlay_ready_text": overlay_ready_text,
            "pre_overlay_json": pre_overlay_json,
            "pre_overlay_text": pre_overlay_text,
            "translation_preview_json": translation_preview_json,
            "translation_preview_text": translation_preview_text,
            "replacement_plan_json": replacement_plan_json,
            "replacement_plan_text": replacement_plan_text,
            "overlay_pdf": overlay_pdf,
            "overlay_summary_text": overlay_summary_text,
        },
    }


def run_extract_only(pdf_path: str | Path) -> Path:
    settings.debug_dir.mkdir(parents=True, exist_ok=True)

    document = extract_document(pdf_path)
    document_ir = document.model_dump()
    document_ir = annotate_repeated_blocks(document_ir)

    role_summary = collect_role_summary(document_ir)
    logger.info("Block role summary: %s", role_summary)

    for page in document_ir["pages"]:
        for block in page["text_blocks"]:
            block_role = block.get("role", "content")
            if block_role != "content":
                block["translate"] = False
                for line in block["lines"]:
                    line["protected_text"] = line["text"]
                    line["placeholders"] = []
                    line["translation_candidate"] = False
                    line["translated_text"] = line["text"]
                    line["restored_text"] = line["text"]
                continue

            for line in block["lines"]:
                protected_text, placeholders = protect_text(line["text"])
                line["protected_text"] = protected_text
                line["placeholders"] = [item.model_dump() for item in placeholders]
                line["translation_candidate"] = is_translation_candidate(line["text"])

                if line["translation_candidate"]:
                    line["translated_text"] = ""
                    line["restored_text"] = ""
                else:
                    line["translated_text"] = line["text"]
                    line["restored_text"] = line["text"]

    groups = collect_translation_groups(
        document_ir,
        max_group_lines=settings.context_group_max_lines,
        max_group_chars=settings.context_group_max_chars,
    )
    batches = make_translation_batches(
        groups,
        max_segments=settings.batch_max_segments,
        max_chars=settings.batch_max_chars,
    )
    translations_by_segment_id: dict[str, str] = {}

    logger.info(
        "Prepared %s contextual groups across %s batch(es) for %s",
        len(groups),
        len(batches),
        pdf_path,
    )

    for batch_index, batch in enumerate(batches, start=1):
        batch_chars = sum(
            len(
                "\n".join(
                    f"[{line['segment_id']}] {line['protected_text']}"
                    for line in group["lines"]
                )
            )
            for group in batch
        )
        batch_line_count = sum(len(group["lines"]) for group in batch)
        logger.info(
            "Running batch %s/%s with %s group(s), %s line(s) and %s chars",
            batch_index,
            len(batches),
            len(batch),
            batch_line_count,
            batch_chars,
        )
        try:
            prompt = build_batch_prompt(batch)
            raw_response = translate_batch(prompt)
            batch_translations = parse_batch_response(raw_response)
            validate_batch_output(batch, batch_translations)
            for group in batch:
                for line in group["lines"]:
                    translated_text = batch_translations[line["segment_id"]]
                    if not placeholders_are_preserved(
                        translated_text,
                        line.get("placeholders", []),
                    ):
                        raise ValueError(
                            f"Placeholder preservation failed for segment {line['segment_id']}"
                        )
            logger.info("Batch %s succeeded", batch_index)
        except Exception as exc:
            logger.exception("Batch %s failed, falling back to per-line translation", batch_index)
            if isinstance(exc, requests.exceptions.Timeout):
                logger.warning(
                    "Batch %s hit backend timeout, preserving protected text for the whole batch",
                    batch_index,
                )
                batch_translations = _preserve_batch_text(batch)
                translations_by_segment_id.update(batch_translations)
                continue

            batch_translations = {}
            for group in batch:
                for line in group["lines"]:
                    try:
                        translated_text = translate_text(line["protected_text"])
                        if not placeholders_are_preserved(
                            translated_text,
                            line.get("placeholders", []),
                        ):
                            raise ValueError(
                                f"Placeholder preservation failed for segment {line['segment_id']}"
                            )
                    except Exception:
                        logger.exception(
                            "Per-line fallback failed for segment %s, preserving protected text",
                            line["segment_id"],
                        )
                        translated_text = line["protected_text"]
                    batch_translations[line["segment_id"]] = translated_text

        translations_by_segment_id.update(batch_translations)

    document_ir = apply_batch_translations(
        document_ir=document_ir,
        translations_by_segment_id=translations_by_segment_id,
        restore_text_fn=restore_text,
    )

    output_path = settings.debug_dir / "document_ir.json"
    output_path.write_text(
        json.dumps(document_ir, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote document IR to %s", output_path)
    return output_path
