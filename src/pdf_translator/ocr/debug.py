from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz

from pdf_translator.ocr.backend import run_ocr
from pdf_translator.translate.placeholders import protect_text, restore_text


DEFAULT_OCR_ZOOM = 2.0


def write_ocr_candidate_report(
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    text_path.write_text(
        _ocr_candidate_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path


def _ocr_candidate_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report.get('selected_pages') if report.get('selected_pages') is not None else 'all'}",
        f"Candidate pages: {report['page_count']}",
        f"PDF kind: {report['pdf_kind']}",
        f"Total OCR candidates: {report['total_candidates']}",
    ]

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: route={page['route']} candidates={page['candidate_count']}"
        )
        for candidate in page.get("candidates", [])[:5]:
            bbox = candidate.get("bbox", {})
            lines.append(
                f"  OCR{candidate['candidate_index']}: bbox={bbox} area_ratio={candidate.get('area_ratio', 0.0):.3f} reason={candidate.get('reason', 'image_block')}"
            )

    return "\n".join(lines)


def render_ocr_candidate_diagnostics(
    pdf_path: Path,
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
    zoom: float = DEFAULT_OCR_ZOOM,
) -> tuple[Path, list[Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    image_paths: list[Path] = []

    manifest_pages: list[dict[str, Any]] = []

    for page_report in report.get("pages", []):
        page_number = int(page_report["page_number"])
        page = doc[page_number - 1]
        manifest_candidates: list[dict[str, Any]] = []

        for candidate in page_report.get("candidates", []):
            bbox = candidate.get("bbox", {})
            rect = fitz.Rect(
                float(bbox.get("x0", 0.0)),
                float(bbox.get("y0", 0.0)),
                float(bbox.get("x1", 0.0)),
                float(bbox.get("y1", 0.0)),
            )
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect, alpha=False)
            image_path = output_dir / f"{stem}_page_{page_number:03d}_ocr_{int(candidate['candidate_index']):03d}.png"
            pixmap.save(image_path)
            image_paths.append(image_path)

            manifest_candidates.append(
                {
                    "candidate_index": candidate["candidate_index"],
                    "bbox": candidate.get("bbox", {}),
                    "area_ratio": candidate.get("area_ratio", 0.0),
                    "reason": candidate.get("reason", "image_block"),
                    "image_path": str(image_path),
                    "pixel_width": pixmap.width,
                    "pixel_height": pixmap.height,
                }
            )

        manifest_pages.append(
            {
                "page_number": page_number,
                "route": page_report.get("route", "unknown"),
                "candidate_count": page_report.get("candidate_count", 0),
                "candidates": manifest_candidates,
            }
        )

    doc.close()

    manifest = {
        "source_path": str(pdf_path),
        "selected_pages": report.get("selected_pages"),
        "page_count": report.get("page_count", 0),
        "pdf_kind": report.get("pdf_kind", "unknown"),
        "total_candidates": report.get("total_candidates", 0),
        "zoom": zoom,
        "pages": manifest_pages,
    }

    manifest_path = output_dir / f"{stem}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return manifest_path, image_paths



def run_ocr_debug_pipeline(
    pdf_path: Path,
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
    zoom: float = DEFAULT_OCR_ZOOM,
    backend: str | None = None,
) -> tuple[Path, list[Path]]:
    manifest_path, image_paths = render_ocr_candidate_diagnostics(
        pdf_path=pdf_path,
        report=report,
        output_dir=output_dir,
        stem=stem,
        zoom=zoom,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for page in manifest.get("pages", []):
        for candidate in page.get("candidates", []):
            image_path = Path(candidate["image_path"])
            ocr_result = run_ocr(image_path, backend=backend)
            candidate["ocr_backend"] = ocr_result["backend"]
            candidate["ocr_status"] = ocr_result["status"]
            candidate["ocr_text"] = ocr_result["text"]
            candidate["ocr_detail"] = ocr_result["detail"]

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return manifest_path, image_paths



def _normalize_ocr_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()



def _count_suspicious_chars(text: str) -> int:
    suspicious_chars = {"®", "©", "™", "�"}
    return sum(1 for char in text if char in suspicious_chars)



def _estimate_ocr_quality(text: str) -> str:
    normalized = _normalize_ocr_text(text)
    if not normalized:
        return "empty"

    word_count = len(normalized.split())
    suspicious_count = _count_suspicious_chars(normalized)

    if word_count < 4:
        return "weak"
    if suspicious_count >= 3:
        return "review"
    if len(normalized) >= 80 and word_count >= 12:
        return "usable"
    return "review"



def build_ocr_review_report(manifest: dict[str, Any]) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []
    total_regions = 0
    status_summary: dict[str, int] = {}
    quality_summary: dict[str, int] = {}

    for page in manifest.get("pages", []):
        region_reports: list[dict[str, Any]] = []
        for candidate in page.get("candidates", []):
            normalized_text = _normalize_ocr_text(candidate.get("ocr_text", ""))
            status = candidate.get("ocr_status", "missing")
            quality = _estimate_ocr_quality(normalized_text) if status == "ok" else "unavailable"
            status_summary[status] = status_summary.get(status, 0) + 1
            quality_summary[quality] = quality_summary.get(quality, 0) + 1
            total_regions += 1

            region_reports.append(
                {
                    "page_number": page.get("page_number"),
                    "candidate_index": candidate.get("candidate_index"),
                    "ocr_backend": candidate.get("ocr_backend", "unknown"),
                    "ocr_status": status,
                    "quality": quality,
                    "word_count": len(normalized_text.split()) if normalized_text else 0,
                    "char_count": len(normalized_text),
                    "line_count": len([line for line in normalized_text.splitlines() if line.strip()]),
                    "suspicious_char_count": _count_suspicious_chars(normalized_text),
                    "preview": normalized_text[:240],
                    "detail": candidate.get("ocr_detail", ""),
                    "image_path": candidate.get("image_path", ""),
                    "bbox": candidate.get("bbox", {}),
                }
            )

        page_reports.append(
            {
                "page_number": page.get("page_number"),
                "route": page.get("route", "unknown"),
                "region_count": len(region_reports),
                "regions": region_reports,
            }
        )

    return {
        "source_path": manifest.get("source_path", ""),
        "selected_pages": manifest.get("selected_pages"),
        "page_count": len(page_reports),
        "total_regions": total_regions,
        "status_summary": status_summary,
        "quality_summary": quality_summary,
        "pages": page_reports,
    }



def ocr_review_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Source path: {report.get('source_path', '')}",
        f"Selected pages: {report.get('selected_pages') if report.get('selected_pages') is not None else 'all'}",
        f"Reviewed pages: {report['page_count']}",
        f"Total OCR regions: {report['total_regions']}",
        f"Status summary: {json.dumps(report['status_summary'], ensure_ascii=False, sort_keys=True)}",
        f"Quality summary: {json.dumps(report['quality_summary'], ensure_ascii=False, sort_keys=True)}",
    ]

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: route={page['route']} regions={page['region_count']}"
        )
        for region in page.get("regions", []):
            lines.append(
                f"  OCR{region['candidate_index']} [{region['ocr_status']}/{region['quality']}] backend={region['ocr_backend']} words={region['word_count']} chars={region['char_count']} suspicious={region['suspicious_char_count']}"
            )
            if region.get("preview"):
                lines.append(f"    preview: {region['preview'].replace(chr(10), ' | ')}")
            if region.get("detail"):
                lines.append(f"    detail: {region['detail']}")

    return "\n".join(lines)



def write_ocr_review_report(
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    text_path.write_text(
        ocr_review_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path



def _truncate_preview(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."



def build_native_ocr_fusion_report(
    overlay_ready_report: dict[str, Any],
    ocr_review_report: dict[str, Any],
) -> dict[str, Any]:
    ocr_pages = {
        int(page.get("page_number")): page
        for page in ocr_review_report.get("pages", [])
    }

    page_reports: list[dict[str, Any]] = []
    total_native_regions = 0
    total_ocr_regions = 0

    for native_page in overlay_ready_report.get("pages", []):
        page_number = int(native_page.get("page_number"))
        ocr_page = ocr_pages.get(page_number, {})
        native_regions = []
        for candidate in native_page.get("candidates", []):
            preview = _truncate_preview(candidate.get("text", ""))
            native_regions.append(
                {
                    "block_index": candidate.get("block_index"),
                    "role": candidate.get("role", "content"),
                    "line_count": candidate.get("line_count", 0),
                    "bbox": candidate.get("bbox", {}),
                    "preview": preview,
                }
            )

        ocr_regions = []
        for region in ocr_page.get("regions", []):
            ocr_regions.append(
                {
                    "candidate_index": region.get("candidate_index"),
                    "ocr_status": region.get("ocr_status", "missing"),
                    "quality": region.get("quality", "unknown"),
                    "ocr_backend": region.get("ocr_backend", "unknown"),
                    "word_count": region.get("word_count", 0),
                    "bbox": region.get("bbox", {}),
                    "preview": _truncate_preview(region.get("preview", "")),
                }
            )

        total_native_regions += len(native_regions)
        total_ocr_regions += len(ocr_regions)
        page_reports.append(
            {
                "page_number": page_number,
                "route": ocr_page.get("route", "native_only"),
                "native_region_count": len(native_regions),
                "ocr_region_count": len(ocr_regions),
                "native_regions": native_regions,
                "ocr_regions": ocr_regions,
            }
        )

    reviewed_page_numbers = {page["page_number"] for page in page_reports}
    for ocr_page in ocr_review_report.get("pages", []):
        page_number = int(ocr_page.get("page_number"))
        if page_number in reviewed_page_numbers:
            continue
        ocr_regions = []
        for region in ocr_page.get("regions", []):
            ocr_regions.append(
                {
                    "candidate_index": region.get("candidate_index"),
                    "ocr_status": region.get("ocr_status", "missing"),
                    "quality": region.get("quality", "unknown"),
                    "ocr_backend": region.get("ocr_backend", "unknown"),
                    "word_count": region.get("word_count", 0),
                    "bbox": region.get("bbox", {}),
                    "preview": _truncate_preview(region.get("preview", "")),
                }
            )
        total_ocr_regions += len(ocr_regions)
        page_reports.append(
            {
                "page_number": page_number,
                "route": ocr_page.get("route", "ocr_only"),
                "native_region_count": 0,
                "ocr_region_count": len(ocr_regions),
                "native_regions": [],
                "ocr_regions": ocr_regions,
            }
        )

    page_reports.sort(key=lambda page: int(page["page_number"]))

    return {
        "selected_pages": overlay_ready_report.get("selected_pages"),
        "page_count": len(page_reports),
        "total_native_regions": total_native_regions,
        "total_ocr_regions": total_ocr_regions,
        "pages": page_reports,
    }



def native_ocr_fusion_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report.get('selected_pages') if report.get('selected_pages') is not None else 'all'}",
        f"Fusion pages: {report['page_count']}",
        f"Total native regions: {report['total_native_regions']}",
        f"Total OCR regions: {report['total_ocr_regions']}",
    ]

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: route={page['route']} native_regions={page['native_region_count']} ocr_regions={page['ocr_region_count']}"
        )
        for native_region in page.get("native_regions", [])[:3]:
            lines.append(
                f"  native B{native_region['block_index']} [{native_region['role']}] lines={native_region['line_count']}: {native_region['preview']}"
            )
        for ocr_region in page.get("ocr_regions", [])[:3]:
            lines.append(
                f"  ocr OCR{ocr_region['candidate_index']} [{ocr_region['ocr_status']}/{ocr_region['quality']}] backend={ocr_region['ocr_backend']} words={ocr_region['word_count']}: {ocr_region['preview']}"
            )

    return "\n".join(lines)



def write_native_ocr_fusion_report(
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    text_path.write_text(
        native_ocr_fusion_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path



def build_native_ocr_fusion_plan(
    overlay_ready_report: dict[str, Any],
    ocr_review_report: dict[str, Any],
) -> dict[str, Any]:
    fusion_report = build_native_ocr_fusion_report(overlay_ready_report, ocr_review_report)
    page_plans: list[dict[str, Any]] = []
    total_segments = 0
    translatable_segments = 0

    for page in fusion_report.get("pages", []):
        segments: list[dict[str, Any]] = []

        for native_region in page.get("native_regions", []):
            segment = {
                "segment_id": f"P{page['page_number']}N{native_region['block_index']}",
                "source_kind": "native",
                "source_ref": f"block:{native_region['block_index']}",
                "role": native_region.get("role", "content"),
                "text": native_region.get("preview", ""),
                "bbox": native_region.get("bbox", {}),
                "translate": True,
            }
            segments.append(segment)
            total_segments += 1
            translatable_segments += 1

        for ocr_region in page.get("ocr_regions", []):
            should_translate = ocr_region.get("ocr_status") == "ok" and ocr_region.get("quality") in {"usable", "review"}
            segment = {
                "segment_id": f"P{page['page_number']}O{ocr_region['candidate_index']}",
                "source_kind": "ocr",
                "source_ref": f"ocr:{ocr_region['candidate_index']}",
                "role": "ocr_region",
                "text": ocr_region.get("preview", ""),
                "ocr_backend": ocr_region.get("ocr_backend", "unknown"),
                "ocr_status": ocr_region.get("ocr_status", "missing"),
                "quality": ocr_region.get("quality", "unknown"),
                "bbox": ocr_region.get("bbox", {}),
                "translate": should_translate,
            }
            segments.append(segment)
            total_segments += 1
            if should_translate:
                translatable_segments += 1

        page_plans.append(
            {
                "page_number": page.get("page_number"),
                "route": page.get("route", "unknown"),
                "segment_count": len(segments),
                "segments": segments,
            }
        )

    return {
        "selected_pages": fusion_report.get("selected_pages"),
        "page_count": len(page_plans),
        "total_segments": total_segments,
        "translatable_segments": translatable_segments,
        "pages": page_plans,
    }



def native_ocr_fusion_plan_to_text(plan: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {plan.get('selected_pages') if plan.get('selected_pages') is not None else 'all'}",
        f"Plan pages: {plan['page_count']}",
        f"Total segments: {plan['total_segments']}",
        f"Translatable segments: {plan['translatable_segments']}",
    ]

    for page in plan.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: route={page['route']} segments={page['segment_count']}"
        )
        for segment in page.get("segments", [])[:5]:
            translate_flag = "translate" if segment.get("translate") else "skip"
            lines.append(
                f"  {segment['segment_id']} [{segment['source_kind']}/{translate_flag}] {segment['source_ref']}: {_truncate_preview(segment.get('text', ''), 160)}"
            )

    return "\n".join(lines)



def write_native_ocr_fusion_plan(
    plan: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"

    json_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    text_path.write_text(
        native_ocr_fusion_plan_to_text(plan),
        encoding="utf-8",
    )

    return json_path, text_path



def build_fusion_translation_preview_report(
    fusion_plan: dict[str, Any],
    translate_text_fn,
) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []
    total_segments = 0
    translated_segments = 0

    for page in fusion_plan.get("pages", []):
        segment_reports: list[dict[str, Any]] = []
        for segment in page.get("segments", []):
            source_text = segment.get("text", "")
            if not segment.get("translate", True):
                translated_text = source_text
                status = "skipped"
            else:
                protected_text, placeholders = protect_text(source_text)
                translated_raw = translate_text_fn(protected_text)
                translated_text = restore_text(translated_raw, placeholders)
                status = "translated"
                translated_segments += 1

            total_segments += 1
            segment_reports.append(
                {
                    "segment_id": segment.get("segment_id"),
                    "source_kind": segment.get("source_kind", "native"),
                    "source_ref": segment.get("source_ref", ""),
                    "translate": segment.get("translate", True),
                    "status": status,
                    "source_text": source_text,
                    "translated_text": translated_text,
                    "role": segment.get("role", "content"),
                    "bbox": segment.get("bbox", {}),
                }
            )

        page_reports.append(
            {
                "page_number": page.get("page_number"),
                "route": page.get("route", "unknown"),
                "segment_count": len(segment_reports),
                "segments": segment_reports,
            }
        )

    return {
        "selected_pages": fusion_plan.get("selected_pages"),
        "page_count": len(page_reports),
        "total_segments": total_segments,
        "translated_segments": translated_segments,
        "pages": page_reports,
    }



def fusion_translation_preview_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report.get('selected_pages') if report.get('selected_pages') is not None else 'all'}",
        f"Preview pages: {report['page_count']}",
        f"Total segments: {report['total_segments']}",
        f"Translated segments: {report['translated_segments']}",
    ]

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: route={page['route']} segments={page['segment_count']}"
        )
        for segment in page.get("segments", [])[:5]:
            lines.append(
                f"  {segment['segment_id']} [{segment['source_kind']}/{segment['status']}] {segment['source_ref']}"
            )
            lines.append(f"    source: {_truncate_preview(segment.get('source_text', ''), 140)}")
            lines.append(f"    translated: {_truncate_preview(segment.get('translated_text', ''), 140)}")

    return "\n".join(lines)



def write_fusion_translation_preview_report(
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    text_path.write_text(
        fusion_translation_preview_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path


def _estimate_fusion_fit_risk(source_text: str, translated_text: str, source_kind: str) -> str:
    source_len = len(source_text.replace("\n", " ").strip())
    translated_len = len(translated_text.replace("\n", " ").strip())
    overflow_ratio = (translated_len / source_len) if source_len else 1.0

    if source_kind == "ocr":
        return "review"
    if overflow_ratio > 1.35:
        return "high"
    if overflow_ratio > 1.1:
        return "medium"
    return "low"


def build_fusion_replacement_plan(
    fusion_translation_preview_report: dict[str, Any],
) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []
    total_replacements = 0
    apply_strategy_summary: dict[str, int] = {}

    for page in fusion_translation_preview_report.get("pages", []):
        replacements: list[dict[str, Any]] = []
        for index, segment in enumerate(page.get("segments", []), start=1):
            source_text = segment.get("source_text", "")
            translated_text = segment.get("translated_text", "")
            source_kind = segment.get("source_kind", "native")
            source_len = len(source_text.replace("\n", " ").strip())
            translated_len = len(translated_text.replace("\n", " ").strip())
            overflow_ratio = (translated_len / source_len) if source_len else 1.0

            if source_kind == "ocr":
                apply_strategy = "ocr_overlay_pending"
            else:
                apply_strategy = "native_overlay_candidate"
            apply_strategy_summary[apply_strategy] = apply_strategy_summary.get(apply_strategy, 0) + 1

            replacements.append(
                {
                    "replacement_index": index,
                    "segment_id": segment.get("segment_id"),
                    "source_kind": source_kind,
                    "source_ref": segment.get("source_ref", ""),
                    "role": segment.get("role", "content"),
                    "source_text": source_text,
                    "translated_text": translated_text,
                    "bbox": segment.get("bbox", {}),
                    "status": segment.get("status", "missing"),
                    "source_length": source_len,
                    "translated_length": translated_len,
                    "overflow_ratio": round(overflow_ratio, 2),
                    "fit_risk": _estimate_fusion_fit_risk(source_text, translated_text, source_kind),
                    "apply_strategy": apply_strategy,
                }
            )

        total_replacements += len(replacements)
        page_reports.append(
            {
                "page_number": page.get("page_number"),
                "route": page.get("route", "unknown"),
                "replacement_count": len(replacements),
                "replacements": replacements,
            }
        )

    return {
        "selected_pages": fusion_translation_preview_report.get("selected_pages"),
        "page_count": len(page_reports),
        "total_replacements": total_replacements,
        "apply_strategy_summary": apply_strategy_summary,
        "pages": page_reports,
    }


def fusion_replacement_plan_to_text(plan: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {plan.get('selected_pages') if plan.get('selected_pages') is not None else 'all'}",
        f"Replacement-plan pages: {plan['page_count']}",
        f"Total replacements: {plan['total_replacements']}",
        f"Apply strategies: {json.dumps(plan['apply_strategy_summary'], ensure_ascii=False, sort_keys=True)}",
    ]

    for page in plan.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: route={page['route']} replacements={page['replacement_count']}"
        )
        for item in page.get("replacements", [])[:5]:
            lines.append(
                f"  {item['segment_id']} [{item['source_kind']}/{item['status']}] "
                f"strategy={item['apply_strategy']} risk={item['fit_risk']} "
                f"ratio={item['overflow_ratio']}: {_truncate_preview(item.get('translated_text', ''), 160)}"
            )

    return "\n".join(lines)


def write_fusion_replacement_plan(
    plan: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"

    json_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    text_path.write_text(
        fusion_replacement_plan_to_text(plan),
        encoding="utf-8",
    )

    return json_path, text_path


def _rect_from_bbox(bbox: dict[str, Any]) -> fitz.Rect | None:
    if not bbox:
        return None
    return fitz.Rect(
        float(bbox.get("x0", 0.0)),
        float(bbox.get("y0", 0.0)),
        float(bbox.get("x1", 0.0)),
        float(bbox.get("y1", 0.0)),
    )


def _draw_diagnostic_note(
    page: fitz.Page,
    anchor_rect: fitz.Rect,
    text: str,
) -> None:
    note_width = min(220.0, max(120.0, page.rect.width * 0.32))
    note_height = 92.0
    x0 = min(max(12.0, anchor_rect.x1 + 10.0), page.rect.width - note_width - 12.0)
    y0 = min(max(12.0, anchor_rect.y0), page.rect.height - note_height - 12.0)
    note_rect = fitz.Rect(x0, y0, x0 + note_width, y0 + note_height)
    page.draw_rect(note_rect, color=(1.0, 0.55, 0.0), fill=(1.0, 0.96, 0.86), width=0.8)
    page.insert_textbox(
        note_rect + (5, 5, -5, -5),
        text,
        fontsize=7.2,
        fontname="helv",
        color=(0.2, 0.12, 0.0),
    )


def render_fusion_overlay_diagnostics(
    pdf_path: Path,
    fusion_replacement_plan: dict[str, Any],
    output_dir: Path,
    stem: str,
    allowed_native_fit_risks: tuple[str, ...] = ("low", "medium"),
) -> tuple[Path, dict[str, Any], list[Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_doc = fitz.open(pdf_path)
    diagnostic_doc = fitz.open()
    image_paths: list[Path] = []

    summary_pages: list[dict[str, Any]] = []
    total_considered = 0
    total_native_applied = 0
    total_ocr_annotated = 0
    total_skipped = 0

    for page_report in fusion_replacement_plan.get("pages", []):
        page_number = int(page_report["page_number"])
        diagnostic_doc.insert_pdf(source_doc, from_page=page_number - 1, to_page=page_number - 1)
        page = diagnostic_doc[-1]

        native_applied = 0
        ocr_annotated = 0
        skipped = 0

        for replacement in page_report.get("replacements", []):
            total_considered += 1
            rect = _rect_from_bbox(replacement.get("bbox", {}))
            if rect is None or rect.is_empty:
                skipped += 1
                total_skipped += 1
                continue

            strategy = replacement.get("apply_strategy")
            status = replacement.get("status")
            fit_risk = replacement.get("fit_risk")

            if strategy == "native_overlay_candidate" and status == "translated" and fit_risk in allowed_native_fit_risks:
                page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
                page.insert_textbox(
                    rect,
                    replacement.get("translated_text", ""),
                    fontsize=8.5,
                    fontname="helv",
                    color=(0, 0, 0),
                )
                native_applied += 1
                total_native_applied += 1
                continue

            if strategy == "ocr_overlay_pending":
                page.draw_rect(rect, color=(1.0, 0.45, 0.0), width=1.4)
                label_point = fitz.Point(rect.x0, max(10.0, rect.y0 - 4.0))
                page.insert_text(
                    label_point,
                    f"{replacement.get('segment_id')} OCR pending",
                    fontsize=8,
                    fontname="helv",
                    color=(1.0, 0.35, 0.0),
                )
                _draw_diagnostic_note(
                    page,
                    rect,
                    f"{replacement.get('segment_id')} OCR translation\n"
                    f"risk={fit_risk}\n"
                    f"{_truncate_preview(replacement.get('translated_text', ''), 260)}",
                )
                ocr_annotated += 1
                total_ocr_annotated += 1
                continue

            skipped += 1
            total_skipped += 1

        summary_pages.append(
            {
                "page_number": page_number,
                "considered_replacements": len(page_report.get("replacements", [])),
                "native_applied": native_applied,
                "ocr_annotated": ocr_annotated,
                "skipped": skipped,
            }
        )

    pdf_output_path = output_dir / f"{stem}.pdf"
    diagnostic_doc.save(pdf_output_path)

    for index, page in enumerate(diagnostic_doc, start=1):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        image_path = output_dir / f"{stem}_page_{index:03d}.png"
        pixmap.save(image_path)
        image_paths.append(image_path)

    diagnostic_doc.close()
    source_doc.close()

    summary = {
        "selected_pages": fusion_replacement_plan.get("selected_pages"),
        "page_count": len(summary_pages),
        "total_considered_replacements": total_considered,
        "total_native_applied": total_native_applied,
        "total_ocr_annotated": total_ocr_annotated,
        "total_skipped": total_skipped,
        "allowed_native_fit_risks": list(allowed_native_fit_risks),
        "pages": summary_pages,
    }

    return pdf_output_path, summary, image_paths


def fusion_overlay_diagnostics_summary_to_text(summary: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {summary.get('selected_pages') if summary.get('selected_pages') is not None else 'all'}",
        f"Page count: {summary['page_count']}",
        f"Allowed native fit risks: {summary['allowed_native_fit_risks']}",
        f"Total considered replacements: {summary['total_considered_replacements']}",
        f"Total native applied: {summary['total_native_applied']}",
        f"Total OCR annotated: {summary['total_ocr_annotated']}",
        f"Total skipped: {summary['total_skipped']}",
    ]

    for page in summary.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: native_applied={page['native_applied']} "
            f"ocr_annotated={page['ocr_annotated']} skipped={page['skipped']} "
            f"considered={page['considered_replacements']}"
        )

    return "\n".join(lines)


def write_fusion_overlay_diagnostics_summary(
    summary: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    text_path = output_dir / f"{stem}.txt"
    text_path.write_text(fusion_overlay_diagnostics_summary_to_text(summary), encoding="utf-8")
    return text_path


def _bbox_area(bbox: dict[str, Any]) -> float:
    if not bbox:
        return 0.0
    width = max(0.0, float(bbox.get("x1", 0.0)) - float(bbox.get("x0", 0.0)))
    height = max(0.0, float(bbox.get("y1", 0.0)) - float(bbox.get("y0", 0.0)))
    return width * height


def _recommend_ocr_overlay_strategy(replacement: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    bbox = replacement.get("bbox", {})
    overflow_ratio = float(replacement.get("overflow_ratio", 1.0) or 1.0)
    status = replacement.get("status", "missing")
    translated_text = replacement.get("translated_text", "").strip()

    if status != "translated":
        return "manual_review", [f"status={status}"]
    if not translated_text:
        return "manual_review", ["empty_translation"]
    if _bbox_area(bbox) <= 0:
        return "manual_review", ["missing_bbox"]

    if overflow_ratio <= 1.25 and len(translated_text) <= 220:
        reasons.append("translation_size_close_to_source")
        reasons.append("text_short_enough_for_region_trial")
        return "image_overlay_candidate", reasons

    reasons.append("translation_expands_beyond_source_region")
    reasons.append("side_note_preserves_scanned_image")
    return "side_annotation_recommended", reasons


def build_ocr_overlay_strategy_report(
    fusion_replacement_plan: dict[str, Any],
) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []
    total_ocr_replacements = 0
    recommendation_summary: dict[str, int] = {}

    for page in fusion_replacement_plan.get("pages", []):
        decisions: list[dict[str, Any]] = []
        for replacement in page.get("replacements", []):
            if replacement.get("source_kind") != "ocr":
                continue

            recommendation, reasons = _recommend_ocr_overlay_strategy(replacement)
            recommendation_summary[recommendation] = recommendation_summary.get(recommendation, 0) + 1
            total_ocr_replacements += 1
            decisions.append(
                {
                    "segment_id": replacement.get("segment_id"),
                    "source_ref": replacement.get("source_ref", ""),
                    "status": replacement.get("status", "missing"),
                    "fit_risk": replacement.get("fit_risk", "unknown"),
                    "overflow_ratio": replacement.get("overflow_ratio", 1.0),
                    "bbox": replacement.get("bbox", {}),
                    "recommendation": recommendation,
                    "reasons": reasons,
                    "translated_preview": _truncate_preview(replacement.get("translated_text", ""), 220),
                }
            )

        page_reports.append(
            {
                "page_number": page.get("page_number"),
                "route": page.get("route", "unknown"),
                "ocr_decision_count": len(decisions),
                "decisions": decisions,
            }
        )

    return {
        "selected_pages": fusion_replacement_plan.get("selected_pages"),
        "page_count": len(page_reports),
        "total_ocr_replacements": total_ocr_replacements,
        "recommendation_summary": recommendation_summary,
        "pages": page_reports,
    }


def ocr_overlay_strategy_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report.get('selected_pages') if report.get('selected_pages') is not None else 'all'}",
        f"Strategy pages: {report['page_count']}",
        f"Total OCR replacements: {report['total_ocr_replacements']}",
        f"Recommendations: {json.dumps(report['recommendation_summary'], ensure_ascii=False, sort_keys=True)}",
    ]

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: route={page['route']} ocr_decisions={page['ocr_decision_count']}"
        )
        for decision in page.get("decisions", [])[:5]:
            lines.append(
                f"  {decision['segment_id']} recommendation={decision['recommendation']} "
                f"risk={decision['fit_risk']} ratio={decision['overflow_ratio']} "
                f"reasons={', '.join(decision['reasons'])}"
            )
            if decision.get("translated_preview"):
                lines.append(f"    translated: {decision['translated_preview']}")

    return "\n".join(lines)


def write_ocr_overlay_strategy_report(
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    text_path.write_text(
        ocr_overlay_strategy_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path
