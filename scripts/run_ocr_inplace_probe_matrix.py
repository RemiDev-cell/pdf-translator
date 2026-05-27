from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import fitz

from pdf_translator.extract.pymupdf_extract import extract_document
from pdf_translator.ocr.debug import (
    ocr_inplace_prototype_summary_to_text,
    render_ocr_inplace_prototype,
    write_ocr_inplace_prototype_summary,
)
from pdf_translator.ocr.experiment import run_ocr_experiment
from pdf_translator.qa.checks import annotate_repeated_blocks
from pdf_translator.routing import build_document_routing_report
from pdf_translator.translate.translator import translate_text, translate_text_mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEBUG_DIR = PROJECT_ROOT / "data" / "debug"
DEFAULT_OUTPUT_DIR = DEFAULT_DEBUG_DIR / "ocr_inplace_probe_matrix"


@dataclass(frozen=True)
class ExpectedProbe:
    name: str
    plan_path: Path
    source_pdf: Path | None
    expected_decisions: dict[str, int]
    expected_appendix_pages: int | None = None


EXPECTED_PROBES = [
    ExpectedProbe(
        name="supportpourocr01",
        plan_path=DEFAULT_DEBUG_DIR / "supportpourocr01_document_preview_fusion_replacement_plan.json",
        source_pdf=PROJECT_ROOT / "data" / "input" / "supportpourocr01.pdf",
        expected_decisions={"applied_native_overlay": 2, "annotated_ocr_side": 1},
        expected_appendix_pages=0,
    ),
    ExpectedProbe(
        name="03_mixed_native_ocr_image",
        plan_path=DEFAULT_DEBUG_DIR / "03_mixed_native_ocr_image_document_preview_fusion_replacement_plan.json",
        source_pdf=PROJECT_ROOT / "data" / "input" / "03_mixed_native_ocr_image.pdf",
        expected_decisions={"applied_ocr_inplace": 1},
        expected_appendix_pages=0,
    ),
    ExpectedProbe(
        name="02_scanned_pure_ocr",
        plan_path=DEFAULT_DEBUG_DIR / "02_scanned_pure_ocr_document_preview_fusion_replacement_plan.json",
        source_pdf=PROJECT_ROOT / "data" / "input" / "02_scanned_pure_ocr.pdf",
        expected_decisions={"annotated_ocr_review": 1},
        expected_appendix_pages=1,
    ),
]


def _load_plan(plan_path: Path) -> dict[str, Any]:
    if not plan_path.exists():
        raise FileNotFoundError(
            f"Missing plan JSON: {plan_path}. Regenerate it with document-preview or ocr-experiment first."
        )
    return json.loads(plan_path.read_text(encoding="utf-8"))


def _max_page_size_from_plan(plan: dict[str, Any]) -> tuple[float, float]:
    max_x = 595.0
    max_y = 842.0
    for page in plan.get("pages", []):
        for replacement in page.get("replacements", []):
            bbox = replacement.get("bbox") or {}
            try:
                max_x = max(max_x, float(bbox.get("x1", 0.0)) + 40.0)
                max_y = max(max_y, float(bbox.get("y1", 0.0)) + 40.0)
            except (TypeError, ValueError):
                continue
    return max_x, max_y


def _build_synthetic_source_pdf(plan: dict[str, Any], output_dir: Path, stem: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_path = output_dir / f"{stem}_synthetic_source.pdf"
    width, height = _max_page_size_from_plan(plan)

    doc = fitz.open()
    for page_report in plan.get("pages", []):
        page = doc.new_page(width=width, height=height)
        page.insert_text((28, 32), f"Synthetic probe source: {stem}", fontsize=11)
        for replacement in page_report.get("replacements", []):
            bbox = replacement.get("bbox") or {}
            if not bbox:
                continue
            rect = fitz.Rect(
                float(bbox.get("x0", 0.0)),
                float(bbox.get("y0", 0.0)),
                float(bbox.get("x1", 0.0)),
                float(bbox.get("y1", 0.0)),
            )
            if rect.is_empty:
                continue
            if replacement.get("source_kind") == "ocr":
                page.draw_rect(rect, color=(0, 0, 0), fill=(0, 0, 0), width=0)
            else:
                page.draw_rect(rect, color=(0.85, 0.85, 0.85), width=0.3)
                preview = " ".join(str(replacement.get("source_text", "")).split())[:90]
                if preview:
                    page.insert_textbox(
                        rect + (2, 2, -2, -2),
                        preview,
                        fontsize=6,
                        fontname="helv",
                        color=(0.2, 0.2, 0.2),
                    )

    if doc.page_count == 0:
        doc.new_page(width=width, height=height)
    doc.save(source_path)
    doc.close()
    return source_path


def _resolve_probe_source(
    probe: ExpectedProbe,
    plan: dict[str, Any],
    output_dir: Path,
    *,
    require_real_sources: bool = False,
) -> tuple[Path, str]:
    if probe.source_pdf and probe.source_pdf.exists():
        return probe.source_pdf, "real"
    if require_real_sources:
        raise FileNotFoundError(
            f"{probe.name}: --require-real-sources requested but missing {probe.source_pdf}"
        )
    return _build_synthetic_source_pdf(plan, output_dir, probe.name), "synthetic"


def _assert_expected(
    probe_name: str,
    summary: dict[str, Any],
    expected_decisions: dict[str, int],
    expected_appendix_pages: int | None,
) -> list[str]:
    errors: list[str] = []
    decisions = summary.get("render_decision_summary", {})
    for decision, expected_count in expected_decisions.items():
        actual_count = int(decisions.get(decision, 0) or 0)
        if actual_count != expected_count:
            errors.append(
                f"{probe_name}: expected {decision}={expected_count}, got {actual_count}"
            )
    if expected_appendix_pages is not None:
        actual_appendix_pages = int(summary.get("ocr_review_appendix_page_count", 0) or 0)
        if actual_appendix_pages != expected_appendix_pages:
            errors.append(
                f"{probe_name}: expected appendix={expected_appendix_pages}, got {actual_appendix_pages}"
            )
    return errors


def _assert_recomposition_review(probe_name: str, summary: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    decisions = summary.get("render_decision_summary", {})
    for page in summary.get("pages", []):
        page_number = page.get("page_number")
        metrics = page.get("recomposition_metrics", {})
        verdict = metrics.get("recomposition_verdict")
        if verdict == "unexpected_outside_changes":
            errors.append(
                f"{probe_name}: page {page_number} has unexpected outside changes "
                f"ratio={metrics.get('changed_outside_allowed_zone_ratio')}"
            )

        if page.get("render_decision_summary", {}).get("applied_ocr_inplace", 0):
            if int(metrics.get("changed_in_source_replacement_zone_count", 0) or 0) <= 0:
                errors.append(f"{probe_name}: page {page_number} applied OCR in-place without source-zone changes")
            if float(metrics.get("changed_outside_allowed_zone_ratio", 0.0) or 0.0) > 0.001:
                errors.append(f"{probe_name}: page {page_number} changed pixels outside allowed zones")

        for item in page.get("render_review_items", []):
            if item.get("source_kind") != "ocr":
                continue
            zone_types = {zone.get("zone_type") for zone in item.get("render_zones", [])}
            decision = item.get("render_decision")
            if decision == "applied_ocr_inplace" and "source_replacement_zone" not in zone_types:
                errors.append(f"{probe_name}: {item.get('segment_id')} missing source_replacement_zone")
            if decision == "annotated_ocr_side":
                if "annotation_zone" not in zone_types:
                    errors.append(f"{probe_name}: {item.get('segment_id')} missing annotation_zone")
                if "source_replacement_zone" in zone_types:
                    errors.append(f"{probe_name}: {item.get('segment_id')} should not replace OCR source")
            if decision == "annotated_ocr_review" and "appendix_zone" not in zone_types:
                errors.append(f"{probe_name}: {item.get('segment_id')} missing appendix_zone")

    if decisions.get("annotated_ocr_review", 0) and int(summary.get("ocr_review_appendix_page_count", 0) or 0) <= 0:
        errors.append(f"{probe_name}: review decision did not create appendix page")
    return errors


def _should_render_final_like(summary: dict[str, Any]) -> bool:
    decisions = summary.get("render_decision_summary", {})
    return int(decisions.get("applied_ocr_inplace", 0) or 0) > 0


def _assert_final_like_review(
    probe_name: str,
    baseline_summary: dict[str, Any],
    final_like_summary: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not bool(final_like_summary.get("review_final_like", False)):
        errors.append(f"{probe_name}: final-like summary is not marked review_final_like")
    if bool(final_like_summary.get("ocr_inplace_review_markers", True)):
        errors.append(f"{probe_name}: final-like summary still has OCR review markers enabled")

    for key in [
        "render_decision_summary",
        "ocr_render_mode_summary",
        "ocr_readiness_summary",
    ]:
        if final_like_summary.get(key, {}) != baseline_summary.get(key, {}):
            errors.append(
                f"{probe_name}: final-like {key} changed from "
                f"{baseline_summary.get(key, {})} to {final_like_summary.get(key, {})}"
            )

    for page in final_like_summary.get("pages", []):
        page_number = page.get("page_number")
        if not page.get("render_decision_summary", {}).get("applied_ocr_inplace", 0):
            continue

        metrics = page.get("recomposition_metrics", {})
        if metrics.get("recomposition_verdict") != "clean":
            errors.append(
                f"{probe_name}: final-like page {page_number} verdict="
                f"{metrics.get('recomposition_verdict')}"
            )
        if float(metrics.get("changed_outside_allowed_zone_ratio", 0.0) or 0.0) != 0.0:
            errors.append(
                f"{probe_name}: final-like page {page_number} changed outside allowed zones "
                f"ratio={metrics.get('changed_outside_allowed_zone_ratio')}"
            )

        for item in page.get("render_review_items", []):
            if item.get("render_decision") != "applied_ocr_inplace":
                continue
            if item.get("ocr_inplace_review_marker_drawn") is not False:
                errors.append(
                    f"{probe_name}: final-like {item.get('segment_id')} still has review marker"
                )

    return errors


def _render_probe(
    *,
    name: str,
    source_pdf: Path,
    plan: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, dict[str, Any], list[Path], Path]:
    stem = f"{name}_ocr_inplace_prototype"
    pdf_path, summary, image_paths = render_ocr_inplace_prototype(
        pdf_path=source_pdf,
        fusion_replacement_plan=plan,
        output_dir=output_dir,
        stem=stem,
    )
    summary_path = write_ocr_inplace_prototype_summary(summary, output_dir, stem)
    return pdf_path, summary, image_paths, summary_path


def _render_final_like_probe(
    *,
    name: str,
    source_pdf: Path,
    plan: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, dict[str, Any], list[Path], Path]:
    stem = f"{name}_ocr_inplace_final_like_prototype"
    pdf_path, summary, image_paths = render_ocr_inplace_prototype(
        pdf_path=source_pdf,
        fusion_replacement_plan=plan,
        output_dir=output_dir,
        stem=stem,
        draw_ocr_review_markers=False,
    )
    summary_path = write_ocr_inplace_prototype_summary(summary, output_dir, stem)
    return pdf_path, summary, image_paths, summary_path


def _format_probe_line(
    *,
    name: str,
    source_mode: str,
    route_summary: dict[str, int] | None,
    summary: dict[str, Any],
    pdf_path: Path,
    summary_path: Path,
    image_paths: list[Path],
) -> str:
    route_text = f" route={json.dumps(route_summary, sort_keys=True)}" if route_summary else ""
    first_image = str(image_paths[0]) if image_paths else "none"
    return (
        f"[OK] {name} source={source_mode}{route_text} "
        f"readiness={json.dumps(summary.get('ocr_readiness_summary', {}), sort_keys=True)} "
        f"render_modes={json.dumps(summary.get('ocr_render_mode_summary', {}), sort_keys=True)} "
        f"decisions={json.dumps(summary.get('render_decision_summary', {}), sort_keys=True)} "
        f"pdf={pdf_path} summary={summary_path} first_image={first_image}"
    )


def _format_final_like_line(
    *,
    name: str,
    summary: dict[str, Any],
    pdf_path: Path,
    summary_path: Path,
    image_paths: list[Path],
) -> str:
    first_image = str(image_paths[0]) if image_paths else "none"
    return (
        f"[OK] {name} final_like=rendered "
        f"markers={summary.get('ocr_inplace_review_markers', True)} "
        f"decisions={json.dumps(summary.get('render_decision_summary', {}), sort_keys=True)} "
        f"render_modes={json.dumps(summary.get('ocr_render_mode_summary', {}), sort_keys=True)} "
        f"pdf={pdf_path} summary={summary_path} first_image={first_image}"
    )


def _run_expected_probes(output_dir: Path, *, require_real_sources: bool = False) -> list[str]:
    errors: list[str] = []
    for probe in EXPECTED_PROBES:
        try:
            plan = _load_plan(probe.plan_path)
            source_pdf, source_mode = _resolve_probe_source(
                probe,
                plan,
                output_dir,
                require_real_sources=require_real_sources,
            )
        except FileNotFoundError as exc:
            errors.append(str(exc))
            continue
        pdf_path, summary, image_paths, summary_path = _render_probe(
            name=probe.name,
            source_pdf=source_pdf,
            plan=plan,
            output_dir=output_dir,
        )
        probe_errors = _assert_expected(
            probe.name,
            summary,
            probe.expected_decisions,
            probe.expected_appendix_pages,
        )
        probe_errors.extend(_assert_recomposition_review(probe.name, summary))
        if _should_render_final_like(summary):
            final_pdf_path, final_summary, final_image_paths, final_summary_path = _render_final_like_probe(
                name=probe.name,
                source_pdf=source_pdf,
                plan=plan,
                output_dir=output_dir,
            )
            probe_errors.extend(
                _assert_final_like_review(
                    probe.name,
                    summary,
                    final_summary,
                )
            )
        else:
            final_pdf_path = None
            final_summary = None
            final_image_paths = []
            final_summary_path = None
        errors.extend(probe_errors)
        print(
            _format_probe_line(
                name=probe.name,
                source_mode=source_mode,
                route_summary=None,
                summary=summary,
                pdf_path=pdf_path,
                summary_path=summary_path,
                image_paths=image_paths,
            )
        )
        if final_summary is not None and final_pdf_path is not None and final_summary_path is not None:
            print(
                _format_final_like_line(
                    name=probe.name,
                    summary=final_summary,
                    pdf_path=final_pdf_path,
                    summary_path=final_summary_path,
                    image_paths=final_image_paths,
                )
            )
        else:
            print(f"[SKIP] {probe.name} final_like=not_applicable reason=no_applied_ocr_inplace")
        if probe_errors:
            print(ocr_inplace_prototype_summary_to_text(summary))
            if final_summary is not None:
                print(ocr_inplace_prototype_summary_to_text(final_summary))
    return errors


def _translator_for_mode(mode: str) -> Callable[[str], str]:
    if mode == "mock":
        return translate_text_mock
    return translate_text


def _run_local_essai_probe(
    *,
    output_dir: Path,
    backend: str,
    translator_mode: str,
) -> list[str]:
    errors: list[str] = []
    pdf_path = PROJECT_ROOT / "data" / "input" / "essai_ocr_02.pdf"
    if not pdf_path.exists():
        return [f"essai_ocr_02: missing local input {pdf_path}"]

    document = extract_document(pdf_path)
    document_ir = annotate_repeated_blocks(document.model_dump())
    routing_report = build_document_routing_report(document_ir)
    page_numbers = [int(page["page_number"]) for page in document_ir.get("pages", [])]
    artifact_stem = "essai_ocr_02_probe_matrix"

    try:
        result = run_ocr_experiment(
            pdf_path=pdf_path,
            document_ir=document.model_dump(),
            output_dir=output_dir,
            translate_text_fn=_translator_for_mode(translator_mode),
            selected_pages=page_numbers,
            backend=backend,
            artifact_stem=artifact_stem,
        )
    except Exception as exc:
        return [
            "essai_ocr_02: local probe failed "
            f"(backend={backend}, translator={translator_mode}): {type(exc).__name__}: {exc}"
        ]
    status_summary = result.get("ocr_review", {}).get("status_summary", {})
    failing_statuses = {
        status: count
        for status, count in status_summary.items()
        if status in {"unavailable", "unsupported", "error"} and count
    }
    if failing_statuses:
        errors.append(
            f"essai_ocr_02: OCR backend {backend!r} did not produce usable OCR statuses: {failing_statuses}"
        )

    pdf_output_path, summary, image_paths, summary_path = _render_probe(
        name="essai_ocr_02",
        source_pdf=pdf_path,
        plan=result["fusion_replacement_plan"],
        output_dir=output_dir,
    )
    errors.extend(_assert_recomposition_review("essai_ocr_02", summary))
    if _should_render_final_like(summary):
        (
            final_pdf_path,
            final_summary,
            final_image_paths,
            final_summary_path,
        ) = _render_final_like_probe(
            name="essai_ocr_02",
            source_pdf=pdf_path,
            plan=result["fusion_replacement_plan"],
            output_dir=output_dir,
        )
        errors.extend(
            _assert_final_like_review(
                "essai_ocr_02",
                summary,
                final_summary,
            )
        )
    else:
        final_pdf_path = None
        final_summary = None
        final_image_paths = []
        final_summary_path = None

    print(
        _format_probe_line(
            name="essai_ocr_02",
            source_mode="real",
            route_summary=routing_report.get("route_summary", {}),
            summary=summary,
            pdf_path=pdf_output_path,
            summary_path=summary_path,
            image_paths=image_paths,
        )
    )
    if final_summary is not None and final_pdf_path is not None and final_summary_path is not None:
        print(
            _format_final_like_line(
                name="essai_ocr_02",
                summary=final_summary,
                pdf_path=final_pdf_path,
                summary_path=final_summary_path,
                image_paths=final_image_paths,
            )
        )
    else:
        print("[SKIP] essai_ocr_02 final_like=not_applicable reason=no_applied_ocr_inplace")
    print("essai_ocr_02 page preview:")
    for page in summary.get("pages", []):
        print(
            f"  page={page.get('page_number')} readiness={page.get('ocr_readiness_summary', {})} "
            f"render_modes={page.get('ocr_render_mode_summary', {})} "
            f"decisions={page.get('render_decision_summary', {})}"
        )
        for item in page.get("render_review_items", []):
            if item.get("source_kind") == "ocr":
                print(
                    f"    {item.get('segment_id')} decision={item.get('render_decision')} "
                    f"readiness={item.get('ocr_readiness_status')} "
                    f"recommendation={item.get('ocr_recommendation')} "
                    f"risk={item.get('fit_risk')} "
                    f"mode={item.get('ocr_render_mode')} "
                    f"layout={item.get('rendered_with_layout', False)} "
                    f"layout_lines={item.get('ocr_layout_line_count', 0)} "
                    f"rendered_blocks={item.get('ocr_layout_rendered_block_count', 0)} "
                    f"fallback={item.get('ocr_layout_fallback_used', False)}"
                )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate guarded OCR in-place rendering on known probe plans."
    )
    parser.add_argument(
        "--backend",
        default="tesseract",
        help="OCR backend for local-input probes. Use mock only for quick debugging.",
    )
    parser.add_argument(
        "--include-local-inputs",
        action="store_true",
        help="Include local ignored PDFs such as data/input/essai_ocr_02.pdf.",
    )
    parser.add_argument(
        "--require-real-sources",
        action="store_true",
        help="Fail instead of using synthetic debug PDFs when expected probe sources are missing.",
    )
    parser.add_argument(
        "--translator",
        choices=("mock", "configured"),
        default="configured",
        help="Translation function for generated local-input plans. Use mock only for quick debugging.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for probe PDFs, summaries, and generated synthetic sources.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Probe output dir: {output_dir}")
    print(f"Local-input translator: {args.translator}")
    if args.require_real_sources:
        print("Expected probes require real source PDFs.")
    errors = _run_expected_probes(
        output_dir,
        require_real_sources=args.require_real_sources,
    )

    if args.include_local_inputs:
        errors.extend(
            _run_local_essai_probe(
                output_dir=output_dir,
                backend=args.backend,
                translator_mode=args.translator,
            )
        )

    if errors:
        print("Probe matrix failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("Probe matrix passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
