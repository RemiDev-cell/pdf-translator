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
                    "text": normalized_text,
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


def _split_long_text_by_words(text: str, max_chars: int) -> list[str]:
    chunks: list[str] = []
    current_words: list[str] = []
    current_len = 0

    for word in text.split():
        next_len = current_len + len(word) + (1 if current_words else 0)
        if current_words and next_len > max_chars:
            chunks.append(" ".join(current_words))
            current_words = [word]
            current_len = len(word)
            continue
        current_words.append(word)
        current_len = next_len

    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


def _split_ocr_text_for_translation(text: str, max_chars: int = 520) -> list[str]:
    normalized = _normalize_ocr_text(text)
    if not normalized:
        return []

    paragraphs = [
        " ".join(part.split())
        for part in normalized.split("\n\n")
        if part.strip()
    ]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        paragraph_chunks = (
            [paragraph]
            if len(paragraph) <= max_chars
            else _split_long_text_by_words(paragraph, max_chars)
        )

        for paragraph_chunk in paragraph_chunks:
            if not current:
                current = paragraph_chunk
                continue
            if len(current) + len(paragraph_chunk) + 2 <= max_chars:
                current = f"{current}\n\n{paragraph_chunk}"
                continue
            chunks.append(current)
            current = paragraph_chunk

    if current:
        chunks.append(current)

    return chunks
def _split_ocr_text_for_rendering(text: str, max_chars: int = 180) -> list[dict[str, Any]]:
    normalized = _normalize_ocr_text(text)
    if not normalized:
        return []

    raw_lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    segments: list[dict[str, Any]] = []

    for raw_line in raw_lines:
        if len(raw_line) <= max_chars:
            segments.append(
                {
                    "text": raw_line,
                    "segment_role": "ocr_line",
                    "char_count": len(raw_line),
                    "word_count": len(raw_line.split()),
                }
            )
            continue

        chunks = _split_long_text_by_words(raw_line, max_chars)
        for chunk in chunks:
            segments.append(
                {
                    "text": chunk,
                    "segment_role": "ocr_text_chunk",
                    "char_count": len(chunk),
                    "word_count": len(chunk.split()),
                }
            )

    return segments


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
                    "text": region.get("text", region.get("preview", "")),
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
                    "text": region.get("text", region.get("preview", "")),
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
            ocr_text = ocr_region.get("text", ocr_region.get("preview", ""))
            rendering_segments = [
                {
                    "text": ocr_text,
                    "segment_role": "ocr_region",
                    "char_count": len(ocr_text),
                    "word_count": len(ocr_text.split()),
                }
            ]

            for ocr_segment_index, ocr_segment in enumerate(rendering_segments, start=1):
                segment = {
                    "segment_id": f"P{page['page_number']}O{ocr_region['candidate_index']}S{ocr_segment_index}",
                    "source_kind": "ocr",
                    "source_ref": f"ocr:{ocr_region['candidate_index']}",
                    "role": ocr_segment.get("segment_role", "ocr_line"),
                    "text": ocr_segment.get("text", ""),
                    "preview": _truncate_preview(ocr_segment.get("text", "")),
                    "ocr_backend": ocr_region.get("ocr_backend", "unknown"),
                    "ocr_status": ocr_region.get("ocr_status", "missing"),
                    "quality": ocr_region.get("quality", "unknown"),
                    "bbox": ocr_region.get("bbox", {}),
                    "translate": should_translate,
                    "ocr_parent_candidate_index": ocr_region.get("candidate_index"),
                    "ocr_segment_index": ocr_segment_index,
                    "ocr_segment_count": len(rendering_segments),
                    "ocr_segment_char_count": ocr_segment.get("char_count", 0),
                    "ocr_segment_word_count": ocr_segment.get("word_count", 0),
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
                translation_chunks: list[dict[str, Any]] = []
            else:
                source_chunks = (
                    _split_ocr_text_for_translation(source_text)
                    if segment.get("source_kind") == "ocr"
                    else [source_text]
                )
                translated_chunks: list[str] = []
                translation_chunks = []
                for chunk_index, source_chunk in enumerate(source_chunks, start=1):
                    protected_text, placeholders = protect_text(source_chunk)
                    translated_raw = translate_text_fn(protected_text)
                    translated_chunk = restore_text(translated_raw, placeholders)
                    translated_chunks.append(translated_chunk)
                    translation_chunks.append(
                        {
                            "chunk_index": chunk_index,
                            "source_text": source_chunk,
                            "translated_text": translated_chunk,
                            "source_length": len(source_chunk),
                            "translated_length": len(translated_chunk),
                        }
                    )
                translated_text = "\n\n".join(translated_chunks)
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
                    "translation_chunk_count": len(translation_chunks),
                    "translation_chunks": translation_chunks,
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
            if segment.get("translation_chunk_count", 0) > 1:
                lines.append(f"    chunks: {segment['translation_chunk_count']}")
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
        if translated_len == 0:
            return "review"
        if overflow_ratio > 1.6 or translated_len > 260:
            return "high"
        if overflow_ratio > 1.25 or translated_len > 180:
            return "medium"
        return "low"
    if overflow_ratio > 1.35:
        return "high"
    if overflow_ratio > 1.1:
        return "medium"
    return "low"


def _line_count(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip()])


def _build_fit_diagnostics(
    source_text: str,
    translated_text: str,
    bbox: dict[str, Any],
) -> dict[str, Any]:
    source_len = len(source_text.replace("\n", " ").strip())
    translated_len = len(translated_text.replace("\n", " ").strip())
    area = _bbox_area(bbox)
    translated_density = (translated_len / area * 1000.0) if area else 0.0
    source_line_count = _line_count(source_text)
    translated_line_count = _line_count(translated_text)

    flags: list[str] = []
    if area <= 0:
        flags.append("missing_bbox")
    if translated_len == 0:
        flags.append("empty_translation")
    if source_len and translated_len / source_len > 1.6:
        flags.append("large_translation_expansion")
    if translated_len > 260:
        flags.append("long_translation")
    if source_line_count and translated_line_count > source_line_count + 1:
        flags.append("more_translated_lines_than_source")
    if translated_density > 18.0:
        flags.append("dense_text_for_region")

    return {
        "source_line_count": source_line_count,
        "translated_line_count": translated_line_count,
        "bbox_area": round(area, 2),
        "translated_chars_per_1000pt2": round(translated_density, 2),
        "flags": flags,
    }

def _analyze_ocr_rendering_context(
    source_text: str,
    translated_text: str,
    fit_risk: str,
    fit_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    source_len = len(source_text.replace("\n", " ").strip())
    translated_len = len(translated_text.replace("\n", " ").strip())
    source_word_count = len(source_text.split())
    translated_word_count = len(translated_text.split())
    source_lines = fit_diagnostics.get("source_line_count", 0)
    translated_lines = fit_diagnostics.get("translated_line_count", 0)
    bbox_area = float(fit_diagnostics.get("bbox_area", 0.0))
    translated_density = float(fit_diagnostics.get("translated_chars_per_1000pt2", 0.0))
    flags = set(fit_diagnostics.get("flags", []))

    if bbox_area >= 35000:
        visual_role = "large_text_region"
    elif translated_len <= 140 and translated_lines <= max(3, source_lines + 1):
        visual_role = "short_label_or_caption"
    else:
        visual_role = "medium_or_uncertain_region"

    return {
        "source_len": source_len,
        "translated_len": translated_len,
        "source_word_count": source_word_count,
        "translated_word_count": translated_word_count,
        "source_lines": source_lines,
        "translated_lines": translated_lines,
        "bbox_area": bbox_area,
        "translated_density": translated_density,
        "flags": flags,
        "fit_risk": fit_risk,
        "visual_role": visual_role,
    }


def _choose_ocr_apply_strategy(
    source_text: str,
    translated_text: str,
    fit_risk: str,
    fit_diagnostics: dict[str, Any],
) -> str:
    context = _analyze_ocr_rendering_context(
        source_text=source_text,
        translated_text=translated_text,
        fit_risk=fit_risk,
        fit_diagnostics=fit_diagnostics,
    )

    translated_len = context["translated_len"]
    source_lines = context["source_lines"]
    translated_lines = context["translated_lines"]
    bbox_area = context["bbox_area"]
    translated_density = context["translated_density"]
    flags = context["flags"]

    if translated_len == 0 or "missing_bbox" in flags or bbox_area <= 0:
        return "ocr_review_required"

    # Large OCR text zones are primary content blocks, not side notes.
    if bbox_area >= 35000 and translated_len <= 1200 and translated_density <= 18.0:
        return "ocr_overlay_candidate"

    # Small safe OCR regions: labels, buttons, short captions.
    if translated_len <= 140 and translated_lines <= max(3, source_lines + 1) and translated_density <= 16.0:
        return "ocr_overlay_candidate"

    if translated_density > 22.0:
        return "ocr_side_annotation"

    if fit_risk in {"low", "medium"} and translated_density <= 18.0:
        return "ocr_overlay_candidate"

    return "ocr_side_annotation"


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
            bbox = segment.get("bbox", {})
            fit_diagnostics = _build_fit_diagnostics(source_text, translated_text, bbox)

            if source_kind == "ocr":
                fit_risk = _estimate_fusion_fit_risk(source_text, translated_text, source_kind)
                apply_strategy = _choose_ocr_apply_strategy(source_text, translated_text, fit_risk, fit_diagnostics)
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
                    "bbox": bbox,
                    "status": segment.get("status", "missing"),
                    "source_length": source_len,
                    "translated_length": translated_len,
                    "overflow_ratio": round(overflow_ratio, 2),
                    "fit_risk": _estimate_fusion_fit_risk(source_text, translated_text, source_kind),
                    "fit_diagnostics": fit_diagnostics,
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


def _format_ocr_diagnostic_note(
    replacement: dict[str, Any],
    recommendation: str,
    reasons: list[str],
) -> str:
    fit_diagnostics = replacement.get("fit_diagnostics", {})
    flags = fit_diagnostics.get("flags", [])
    reason_text = ", ".join(reasons[:2]) if reasons else "review"
    flag_text = ", ".join(flags[:2]) if flags else "none"
    return (
        f"{replacement.get('segment_id')} OCR translation\n"
        f"recommendation={recommendation}\n"
        f"risk={replacement.get('fit_risk')} ratio={replacement.get('overflow_ratio', 1.0)}\n"
        f"reason={reason_text}\n"
        f"flags={flag_text}\n"
        f"{_truncate_preview(replacement.get('translated_text', ''), 220)}"
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
    total_ocr_overlay_applied = 0
    total_ocr_side_annotated = 0
    total_ocr_review_required = 0
    total_skipped = 0
    ocr_recommendation_summary: dict[str, int] = {}

    for page_report in fusion_replacement_plan.get("pages", []):
        page_number = int(page_report["page_number"])
        diagnostic_doc.insert_pdf(source_doc, from_page=page_number - 1, to_page=page_number - 1)
        page = diagnostic_doc[-1]

        native_applied = 0
        ocr_annotated = 0
        skipped = 0
        page_ocr_recommendations: dict[str, int] = {}

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
                translated_text = replacement.get("translated_text", "")

                approx_line_count = max(1, translated_text.count("\n") + len(translated_text) // 90)
                font_size = min(10, max(6, rect.height / (approx_line_count * 1.2)))

                page.insert_textbox(
                    rect + (2, 2, -2, -2),
                    translated_text,
                    fontsize=font_size,
                    fontname="helv",
                    color=(0, 0, 0),
                )
                native_applied += 1
                total_native_applied += 1
                continue

            if strategy == "ocr_overlay_candidate" and status == "translated":
                recommendation, reasons = _recommend_ocr_overlay_strategy(replacement)
                ocr_recommendation_summary[recommendation] = ocr_recommendation_summary.get(recommendation, 0) + 1

                if recommendation == "image_overlay_candidate":
                    total_ocr_overlay_applied += 1
                elif recommendation == "side_annotation_recommended":
                    total_ocr_side_annotated += 1
                else:
                    total_ocr_review_required += 1
                page_ocr_recommendations[recommendation] = page_ocr_recommendations.get(recommendation, 0) + 1
                page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
                translated_text = replacement.get("translated_text", "")
                approx_line_count = max(1, translated_text.count("\n") + len(translated_text) // 90)
                font_size = min(10, max(6, rect.height / (approx_line_count * 1.2)))
                page.insert_textbox(
                    rect + (2, 2, -2, -2),
                    translated_text,
                    fontsize=font_size,
                    fontname="helv",
                    color=(0, 0, 0),
                )
                page.draw_rect(rect, color=(0.0, 0.55, 0.0), width=0.8)
                ocr_annotated += 1
                total_ocr_annotated += 1
                continue

            if strategy in {"ocr_side_annotation", "ocr_review_required"}:
                recommendation, reasons = _recommend_ocr_overlay_strategy(replacement)
                ocr_recommendation_summary[recommendation] = ocr_recommendation_summary.get(recommendation, 0) + 1

                if recommendation == "image_overlay_candidate":
                    total_ocr_overlay_applied += 1
                elif recommendation == "side_annotation_recommended":
                    total_ocr_side_annotated += 1
                else:
                    total_ocr_review_required += 1
                page_ocr_recommendations[recommendation] = page_ocr_recommendations.get(recommendation, 0) + 1
                page.draw_rect(rect, color=(1.0, 0.45, 0.0), width=1.4)
                label_point = fitz.Point(rect.x0, max(10.0, rect.y0 - 4.0))
                page.insert_text(
                    label_point,
                    f"{replacement.get('segment_id')} OCR strategy",
                    fontsize=8,
                    fontname="helv",
                    color=(1.0, 0.35, 0.0),
                )
                _draw_diagnostic_note(
                    page,
                    rect,
                    _format_ocr_diagnostic_note(replacement, recommendation, reasons),
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
                "ocr_recommendations": page_ocr_recommendations,
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
        "total_ocr_overlay_applied": total_ocr_overlay_applied,
        "total_ocr_side_annotated": total_ocr_side_annotated,
        "total_ocr_review_required": total_ocr_review_required,
        "ocr_recommendation_summary": ocr_recommendation_summary,
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
        f"OCR recommendations: {json.dumps(summary.get('ocr_recommendation_summary', {}), ensure_ascii=False, sort_keys=True)}",
        f"Total skipped: {summary['total_skipped']}",
    ]

    for page in summary.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: native_applied={page['native_applied']} "
            f"ocr_annotated={page['ocr_annotated']} skipped={page['skipped']} "
            f"considered={page['considered_replacements']} "
            f"ocr_recommendations={json.dumps(page.get('ocr_recommendations', {}), ensure_ascii=False, sort_keys=True)}"
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
    fit_risk = replacement.get("fit_risk", "unknown")
    fit_diagnostics = replacement.get("fit_diagnostics", {})
    diagnostic_flags = set(fit_diagnostics.get("flags", []))
    translated_text = replacement.get("translated_text", "").strip()

    if status != "translated":
        return "manual_review", [f"status={status}"]
    if not translated_text:
        return "manual_review", ["empty_translation"]
    if _bbox_area(bbox) <= 0:
        return "manual_review", ["missing_bbox"]

    if fit_risk == "low" and overflow_ratio <= 1.25 and len(translated_text) <= 180:
        reasons.append("translation_size_close_to_source")
        reasons.append("low_fit_risk")
        return "image_overlay_candidate", reasons

    if "dense_text_for_region" in diagnostic_flags:
        reasons.append("dense_text_for_region")
    if "long_translation" in diagnostic_flags:
        reasons.append("long_translation")
    if overflow_ratio > 1.25:
        reasons.append("translation_expands_beyond_source_region")
    if not reasons:
        reasons.append(f"fit_risk={fit_risk}")
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
                    "fit_diagnostics": replacement.get("fit_diagnostics", {}),
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


def build_ocr_page_translation_preview_report(
    fusion_translation_preview_report: dict[str, Any],
    ocr_overlay_strategy_report: dict[str, Any],
) -> dict[str, Any]:
    strategy_by_page: dict[int, dict[str, dict[str, Any]]] = {}
    for page in ocr_overlay_strategy_report.get("pages", []):
        page_number = int(page.get("page_number"))
        strategy_by_page[page_number] = {
            decision.get("segment_id"): decision
            for decision in page.get("decisions", [])
        }

    page_reports: list[dict[str, Any]] = []
    total_segments = 0
    total_native_segments = 0
    total_ocr_segments = 0
    selected_pages = fusion_translation_preview_report.get("selected_pages")

    for page in fusion_translation_preview_report.get("pages", []):
        page_number = int(page.get("page_number"))
        page_strategies = strategy_by_page.get(page_number, {})
        segments: list[dict[str, Any]] = []
        native_count = 0
        ocr_count = 0

        for segment in page.get("segments", []):
            source_kind = segment.get("source_kind", "native")
            decision = page_strategies.get(segment.get("segment_id"), {})
            if source_kind == "ocr":
                ocr_count += 1
            else:
                native_count += 1

            segments.append(
                {
                    "segment_id": segment.get("segment_id"),
                    "source_kind": source_kind,
                    "source_ref": segment.get("source_ref", ""),
                    "status": segment.get("status", "missing"),
                    "source_text": segment.get("source_text", ""),
                    "translated_text": segment.get("translated_text", ""),
                    "translation_chunk_count": segment.get("translation_chunk_count", 0),
                    "recommendation": decision.get("recommendation"),
                    "fit_risk": decision.get("fit_risk"),
                    "overflow_ratio": decision.get("overflow_ratio"),
                    "reasons": decision.get("reasons", []),
                }
            )

        total_segments += len(segments)
        total_native_segments += native_count
        total_ocr_segments += ocr_count
        page_reports.append(
            {
                "page_number": page_number,
                "route": page.get("route", "unknown"),
                "segment_count": len(segments),
                "native_segment_count": native_count,
                "ocr_segment_count": ocr_count,
                "segments": segments,
            }
        )

    rendered_pages = [page["page_number"] for page in page_reports]
    missing_pages = [
        page_number
        for page_number in selected_pages or []
        if page_number not in rendered_pages
    ]

    return {
        "selected_pages": selected_pages,
        "page_count": len(page_reports),
        "rendered_pages": rendered_pages,
        "missing_pages": missing_pages,
        "total_segments": total_segments,
        "total_native_segments": total_native_segments,
        "total_ocr_segments": total_ocr_segments,
        "pages": page_reports,
    }


def ocr_page_translation_preview_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report.get('selected_pages') if report.get('selected_pages') is not None else 'all'}",
        f"Preview pages: {report['page_count']}",
        f"Rendered pages: {report.get('rendered_pages', [])}",
        f"Missing pages: {report.get('missing_pages', [])}",
        f"Total segments: {report['total_segments']}",
        f"Native segments: {report['total_native_segments']}",
        f"OCR segments: {report['total_ocr_segments']}",
    ]

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: route={page['route']} "
            f"native={page['native_segment_count']} ocr={page['ocr_segment_count']} segments={page['segment_count']}"
        )
        for segment in page.get("segments", []):
            lines.append(
                f"  {segment['segment_id']} kind={segment['source_kind']} "
                f"status={segment['status']} {segment['source_ref']}"
            )
            if segment.get("source_kind") == "ocr":
                lines.append(
                    f"    ocr_strategy: recommendation={segment.get('recommendation')} "
                    f"risk={segment.get('fit_risk')} ratio={segment.get('overflow_ratio')} "
                    f"reasons={', '.join(segment.get('reasons', []))}"
                )
                if segment.get("translation_chunk_count", 0) > 1:
                    lines.append(f"    translation_chunks: {segment['translation_chunk_count']}")
            lines.append(f"    source: {_truncate_preview(segment.get('source_text', ''), 220)}")
            lines.append(f"    translated: {_truncate_preview(segment.get('translated_text', ''), 260)}")

    return "\n".join(lines)


def write_ocr_page_translation_preview_report(
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
        ocr_page_translation_preview_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path
