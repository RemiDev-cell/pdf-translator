from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz

from pdf_translator.ocr.backend import run_ocr
from pdf_translator.translate.placeholders import protect_text, restore_text


DEFAULT_OCR_ZOOM = 2.0
DEFAULT_OCR_CROP_PADDING_PT = 8.0


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
    crop_padding_pt: float = DEFAULT_OCR_CROP_PADDING_PT,
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
            requested_crop_rect = rect + (-crop_padding_pt, -crop_padding_pt, crop_padding_pt, crop_padding_pt)
            crop_rect = requested_crop_rect & page.rect
            applied_padding = {
                "left": round(max(0.0, rect.x0 - crop_rect.x0), 2),
                "top": round(max(0.0, rect.y0 - crop_rect.y0), 2),
                "right": round(max(0.0, crop_rect.x1 - rect.x1), 2),
                "bottom": round(max(0.0, crop_rect.y1 - rect.y1), 2),
            }
            crop_constrained_edges = [
                edge
                for edge, constrained in {
                    "left": requested_crop_rect.x0 < page.rect.x0,
                    "top": requested_crop_rect.y0 < page.rect.y0,
                    "right": requested_crop_rect.x1 > page.rect.x1,
                    "bottom": requested_crop_rect.y1 > page.rect.y1,
                }.items()
                if constrained
            ]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=crop_rect, alpha=False)
            image_path = output_dir / f"{stem}_page_{page_number:03d}_ocr_{int(candidate['candidate_index']):03d}.png"
            pixmap.save(image_path)
            image_paths.append(image_path)

            manifest_candidates.append(
                {
                    "candidate_index": candidate["candidate_index"],
                    "bbox": candidate.get("bbox", {}),
                    "crop_bbox": {
                        "x0": crop_rect.x0,
                        "y0": crop_rect.y0,
                        "x1": crop_rect.x1,
                        "y1": crop_rect.y1,
                    },
                    "crop_padding_pt": crop_padding_pt,
                    "crop_padding_applied_pt": applied_padding,
                    "crop_constrained_edges": crop_constrained_edges,
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
        "crop_padding_pt": crop_padding_pt,
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
    crop_padding_pt: float = DEFAULT_OCR_CROP_PADDING_PT,
) -> tuple[Path, list[Path]]:
    manifest_path, image_paths = render_ocr_candidate_diagnostics(
        pdf_path=pdf_path,
        report=report,
        output_dir=output_dir,
        stem=stem,
        zoom=zoom,
        crop_padding_pt=crop_padding_pt,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    for page in manifest.get("pages", []):
        for candidate in page.get("candidates", []):
            image_path = Path(candidate["image_path"])
            ocr_result = run_ocr(image_path, backend=backend)
            candidate["ocr_backend"] = ocr_result["backend"]
            candidate["ocr_status"] = ocr_result["status"]
            candidate["ocr_text"] = ocr_result["text"]
            candidate["ocr_layout"] = ocr_result.get("layout", [])
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




def _ocr_layout_has_edge_clipping(ocr_layout: list[dict[str, Any]]) -> bool:
    """Return True when OCR lines touch crop edges, suggesting clipped source text."""
    for line in ocr_layout:
        if (
            line.get("touches_left_edge")
            or line.get("touches_right_edge")
            or line.get("touches_top_edge")
            or line.get("touches_bottom_edge")
        ):
            return True
    return False


def _ocr_layout_edge_clipping_count(ocr_layout: list[dict[str, Any]]) -> int:
    """Count OCR lines touching crop edges."""
    count = 0
    for line in ocr_layout:
        if (
            line.get("touches_left_edge")
            or line.get("touches_right_edge")
            or line.get("touches_top_edge")
            or line.get("touches_bottom_edge")
        ):
            count += 1
    return count

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
                    "edge_clipping_detected": _ocr_layout_has_edge_clipping(candidate.get("ocr_layout", [])),
                    "edge_clipping_line_count": _ocr_layout_edge_clipping_count(candidate.get("ocr_layout", [])),
                    "text": normalized_text,
                    "preview": normalized_text[:240],
                    "ocr_layout": candidate.get("ocr_layout", []),
                    "detail": candidate.get("ocr_detail", ""),
                    "image_path": candidate.get("image_path", ""),
                    "bbox": candidate.get("bbox", {}),
                    "crop_bbox": candidate.get("crop_bbox", candidate.get("bbox", {})),
                    "crop_padding_pt": candidate.get("crop_padding_pt", 0.0),
                    "crop_padding_applied_pt": candidate.get("crop_padding_applied_pt", {}),
                    "crop_constrained_edges": candidate.get("crop_constrained_edges", []),
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


def _normalize_native_extraction_artifacts(text: str) -> str:
    normalized_lines = []
    for line in text.splitlines():
        stripped = line.lstrip()
        leading = line[: len(line) - len(stripped)]
        if stripped.startswith("? ") and stripped.count("?") == 1:
            normalized_lines.append(f"{leading}- {stripped[2:]}")
            continue
        normalized_lines.append(line)
    return "\n".join(normalized_lines)


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
            candidate_text = _normalize_native_extraction_artifacts(candidate.get("text", ""))
            preview = _truncate_preview(candidate_text)
            native_regions.append(
                {
                    "block_index": candidate.get("block_index"),
                    "role": candidate.get("role", "content"),
                    "line_count": candidate.get("line_count", 0),
                    "bbox": candidate.get("bbox", {}),
                    "lines": [
                        {
                            **line,
                            "text": _normalize_native_extraction_artifacts(str(line.get("text", ""))),
                        }
                        for line in candidate.get("lines", [])
                    ],
                    "text": candidate_text,
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
                    "edge_clipping_detected": bool(region.get("edge_clipping_detected", False)),
                    "edge_clipping_line_count": int(region.get("edge_clipping_line_count", 0) or 0),
                    "bbox": region.get("bbox", {}),
                    "crop_bbox": region.get("crop_bbox", region.get("bbox", {})),
                    "crop_padding_pt": region.get("crop_padding_pt", 0.0),
                    "text": region.get("text", region.get("preview", "")),
                    "preview": _truncate_preview(region.get("preview", "")),
                    "ocr_layout": region.get("ocr_layout", []),
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
                    "edge_clipping_detected": bool(region.get("edge_clipping_detected", False)),
                    "edge_clipping_line_count": int(region.get("edge_clipping_line_count", 0) or 0),
                    "bbox": region.get("bbox", {}),
                    "crop_bbox": region.get("crop_bbox", region.get("bbox", {})),
                    "crop_padding_pt": region.get("crop_padding_pt", 0.0),
                    "text": region.get("text", region.get("preview", "")),
                    "preview": _truncate_preview(region.get("preview", "")),
                    "ocr_layout": region.get("ocr_layout", []),
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




def _bbox_float(region: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float((region.get("bbox") or {}).get(key, default))
    except (TypeError, ValueError):
        return default


def _order_native_regions_for_reading(native_regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order native regions conservatively for reading.

    For simple pages, keep the existing y/x order. For clear two-column pages,
    read header first, then left column top-to-bottom, then right column
    top-to-bottom, then centered/side-note regions near the bottom.
    """
    if len(native_regions) < 8:
        return list(native_regions)

    regions = list(native_regions)
    x0_values = sorted(round(_bbox_float(region, "x0"), 1) for region in regions)

    unique_x0 = []
    for value in x0_values:
        if not unique_x0 or abs(value - unique_x0[-1]) > 8:
            unique_x0.append(value)

    if len(unique_x0) < 2:
        return sorted(regions, key=lambda r: (_bbox_float(r, "y0"), _bbox_float(r, "x0")))

    # Detect the common two-column case: a left cluster and a right cluster
    # separated by a large gap.
    gaps = [
        (unique_x0[index + 1] - unique_x0[index], unique_x0[index], unique_x0[index + 1])
        for index in range(len(unique_x0) - 1)
    ]
    large_gaps = [gap for gap in gaps if gap[0] >= 80]

    if not large_gaps:
        return sorted(regions, key=lambda r: (_bbox_float(r, "y0"), _bbox_float(r, "x0")))

    # Prefer the gap before the right text column. In this benchmark-like layout,
    # the right column starts after the last large x cluster.
    _, left_edge, right_edge = sorted(large_gaps, key=lambda item: item[2])[-1]
    column_threshold = (left_edge + right_edge) / 2.0

    page_top = min(_bbox_float(region, "y0") for region in regions)
    page_bottom = max(_bbox_float(region, "y1") for region in regions)
    page_height = max(1.0, page_bottom - page_top)

    candidate_left = [
        region for region in regions
        if _bbox_float(region, "x0") < column_threshold
        and (_bbox_float(region, "y1") - _bbox_float(region, "y0")) >= 12
    ]
    candidate_right = [
        region for region in regions
        if _bbox_float(region, "x0") >= column_threshold
        and (_bbox_float(region, "y1") - _bbox_float(region, "y0")) >= 12
    ]

    # Avoid applying column ordering to brochures/cards/forms where x clusters
    # exist but do not represent two sustained text columns.
    if len(candidate_left) < 4 or len(candidate_right) < 4:
        return sorted(regions, key=lambda r: (_bbox_float(r, "y0"), _bbox_float(r, "x0")))

    headers: list[dict[str, Any]] = []
    left_column: list[dict[str, Any]] = []
    right_column: list[dict[str, Any]] = []
    footnotes: list[dict[str, Any]] = []

    for region in regions:
        x0 = _bbox_float(region, "x0")
        x1 = _bbox_float(region, "x1")
        y0 = _bbox_float(region, "y0")
        width = x1 - x0

        # Full-width or upper title/objective blocks should remain first.
        if y0 <= page_top + page_height * 0.10 and width >= 220:
            headers.append(region)
            continue

        # Bottom centered notes should not be interleaved with columns.
        if y0 >= page_top + page_height * 0.82:
            footnotes.append(region)
            continue

        if x0 < column_threshold:
            left_column.append(region)
        else:
            right_column.append(region)

    return (
        sorted(headers, key=lambda r: (_bbox_float(r, "y0"), _bbox_float(r, "x0")))
        + sorted(left_column, key=lambda r: (_bbox_float(r, "y0"), _bbox_float(r, "x0")))
        + sorted(right_column, key=lambda r: (_bbox_float(r, "y0"), _bbox_float(r, "x0")))
        + sorted(footnotes, key=lambda r: (_bbox_float(r, "y0"), _bbox_float(r, "x0")))
    )


def _is_native_ui_control_text(text: str) -> bool:
    normalized = " ".join(text.lower().split()).strip(" :")
    native_ui_controls = {
        "traduction complete",
        "ocr uniquement",
        "relecture humaine",
        "export debug",
        "valider",
    }
    return normalized in native_ui_controls


def _looks_like_native_table_row(text: str) -> bool:
    cells = [cell.strip() for cell in text.splitlines() if cell.strip()]
    if len(cells) < 2:
        return False
    if len(text) > 220 or any(len(cell) > 80 for cell in cells):
        return False

    numeric_cells = sum(1 for cell in cells if any(char.isdigit() for char in cell))
    if numeric_cells >= 1 and len(cells) >= 2:
        return True

    normalized_cells = {" ".join(cell.lower().split()) for cell in cells}
    known_table_headers = {
        "designation",
        "désignation",
        "quantite",
        "quantité",
        "unite",
        "unité",
        "prix ht",
        "total ht",
    }
    return len(normalized_cells & known_table_headers) >= 3


def _looks_like_native_table_header(text: str) -> bool:
    cells = [cell.strip() for cell in text.splitlines() if cell.strip()]
    if len(cells) < 2:
        return False

    normalized_cells = {" ".join(cell.lower().split()) for cell in cells}
    known_table_headers = {
        "designation",
        "désignation",
        "quantite",
        "quantité",
        "unite",
        "unité",
        "prix ht",
        "total ht",
    }
    return len(normalized_cells & known_table_headers) >= 3


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

        for native_region in _order_native_regions_for_reading(page.get("native_regions", [])):
            native_text = native_region.get("text") or native_region.get("preview", "")
            is_ui_control = _is_native_ui_control_text(native_text)
            is_table_row = _looks_like_native_table_row(native_text)
            is_table_header = _looks_like_native_table_header(native_text)
            if is_table_header and native_region.get("lines"):
                for line_index, line in enumerate(native_region.get("lines", []), start=1):
                    line_text = str(line.get("text", "")).strip()
                    if not line_text:
                        continue
                    segments.append(
                        {
                            "segment_id": f"P{page['page_number']}N{native_region['block_index']}L{line_index}",
                            "source_kind": "native",
                            "source_ref": f"block:{native_region['block_index']}:line:{line_index}",
                            "role": "table_header_cell",
                            "text": line_text,
                            "bbox": line.get("bbox") or native_region.get("bbox", {}),
                            "translate": True,
                        }
                    )
                    total_segments += 1
                    translatable_segments += 1
                continue

            role = native_region.get("role", "content")
            if is_ui_control:
                role = "ui_control"
            elif is_table_row:
                role = "table_row"
            segment = {
                "segment_id": f"P{page['page_number']}N{native_region['block_index']}",
                "source_kind": "native",
                "source_ref": f"block:{native_region['block_index']}",
                "role": role,
                "text": native_text,
                "bbox": native_region.get("bbox", {}),
                "translate": not (is_ui_control or is_table_row),
            }
            segments.append(segment)
            total_segments += 1
            if segment["translate"]:
                translatable_segments += 1

        for ocr_region in page.get("ocr_regions", []):
            should_translate = ocr_region.get("ocr_status") == "ok" and ocr_region.get("quality") in {"usable", "review"}
            ocr_text = _clean_ocr_overlay_text(ocr_region.get("text", ocr_region.get("preview", "")))
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
                    "edge_clipping_detected": bool(ocr_region.get("edge_clipping_detected", False)),
                    "edge_clipping_line_count": int(ocr_region.get("edge_clipping_line_count", 0) or 0),
                    "bbox": ocr_region.get("bbox", {}),
                    "crop_bbox": ocr_region.get("crop_bbox", ocr_region.get("bbox", {})),
                    "crop_padding_pt": ocr_region.get("crop_padding_pt", 0.0),
                    "ocr_layout": ocr_region.get("ocr_layout", []),
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
                            "source_endswith_ellipsis": source_chunk.strip().endswith("..."),
                            "translated_endswith_ellipsis": translated_chunk.strip().endswith("..."),
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
                    "source_length": len(source_text),
                    "translated_length": len(translated_text),
                    "source_endswith_ellipsis": source_text.strip().endswith("..."),
                    "translated_endswith_ellipsis": translated_text.strip().endswith("..."),
                    "role": segment.get("role", "content"),
                    "bbox": segment.get("bbox", {}),
                    "crop_bbox": segment.get("crop_bbox", segment.get("bbox", {})),
                    "crop_padding_pt": segment.get("crop_padding_pt", 0.0),
                    "ocr_layout": segment.get("ocr_layout", []),
                    "edge_clipping_detected": bool(segment.get("edge_clipping_detected", False)),
                    "edge_clipping_line_count": int(segment.get("edge_clipping_line_count", 0) or 0),
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
        "flags": sorted(flags),
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
        "flags": sorted(flags),
        "fit_risk": fit_risk,
        "visual_role": visual_role,
    }


def _build_ocr_strategy_decision(
    source_text: str,
    translated_text: str,
    fit_risk: str,
    fit_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    context = _analyze_ocr_rendering_context(
        source_text=source_text,
        translated_text=translated_text,
        fit_risk=fit_risk,
        fit_diagnostics=fit_diagnostics,
    )

    strategy = _choose_ocr_apply_strategy(
        source_text=source_text,
        translated_text=translated_text,
        fit_risk=fit_risk,
        fit_diagnostics=fit_diagnostics,
    )

    reasons = []

    if context["visual_role"] == "large_text_region":
        reasons.append("large_text_region")
    if context["translated_density"] <= 18.0:
        reasons.append("acceptable_density")
    if fit_risk in {"low", "medium"}:
        reasons.append(f"fit_risk={fit_risk}")
    if context["translated_len"] <= 140:
        reasons.append("short_text")

    if strategy == "ocr_overlay_candidate":
        confidence = "high" if "large_text_region" in reasons else "medium"
    elif strategy == "ocr_side_annotation":
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "apply_strategy": strategy,
        "confidence": confidence,
        "reasons": reasons,
        "context": context,
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
    if "edge_clipping_detected" in flags:
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
                edge_clipping_detected = bool(segment.get("edge_clipping_detected", False))
                edge_clipping_line_count = int(segment.get("edge_clipping_line_count", 0) or 0)
                if edge_clipping_detected:
                    fit_diagnostics["flags"] = sorted(
                        set(fit_diagnostics.get("flags", [])) | {"edge_clipping_detected"}
                    )
                fit_risk = _estimate_fusion_fit_risk(source_text, translated_text, source_kind)
                decision = _build_ocr_strategy_decision(
                    source_text=source_text,
                    translated_text=translated_text,
                    fit_risk=fit_risk,
                    fit_diagnostics=fit_diagnostics,
                )
                apply_strategy = decision["apply_strategy"]
            else:
                apply_strategy = "native_overlay_candidate"
                decision = None
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
                    "crop_bbox": segment.get("crop_bbox", bbox),
                    "crop_padding_pt": segment.get("crop_padding_pt", 0.0),
                    "ocr_layout": segment.get("ocr_layout", []),
                    "edge_clipping_detected": bool(segment.get("edge_clipping_detected", False)),
                    "edge_clipping_line_count": int(segment.get("edge_clipping_line_count", 0) or 0),
                    "status": segment.get("status", "missing"),
                    "source_length": source_len,
                    "translated_length": translated_len,
                    "overflow_ratio": round(overflow_ratio, 2),
                    "fit_risk": _estimate_fusion_fit_risk(source_text, translated_text, source_kind),
                    "fit_diagnostics": fit_diagnostics,
                    "apply_strategy": apply_strategy,
                    "ocr_decision": decision,
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
    note_width = min(260.0, max(150.0, page.rect.width * 0.38))
    note_height = 118.0
    x0 = min(max(12.0, anchor_rect.x1 + 10.0), page.rect.width - note_width - 12.0)
    y0 = min(max(12.0, anchor_rect.y0), page.rect.height - note_height - 12.0)
    note_rect = fitz.Rect(x0, y0, x0 + note_width, y0 + note_height)
    page.draw_rect(note_rect, color=(1.0, 0.55, 0.0), fill=(1.0, 0.96, 0.86), width=0.8)
    text_rect = note_rect + (5, 5, -5, -5)
    font_size = _fit_ocr_textbox_font_size(
        page,
        text_rect,
        text,
        min_size=5.0,
        max_size=7.2,
        color=(0.2, 0.12, 0.0),
    )
    overflow = page.insert_textbox(
        text_rect,
        text,
        fontsize=font_size,
        fontname="helv",
        color=(0.2, 0.12, 0.0),
    )
    if overflow < 0:
        fallback_lines = text.splitlines()[:5]
        page.insert_textbox(
            text_rect,
            "\n".join(fallback_lines),
            fontsize=5.0,
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
        f"{_truncate_preview(replacement.get('translated_text', ''), 120)}"
    )


def _split_text_to_line_count(text: str, line_count: int) -> list[str]:
    normalized = " ".join(text.split())
    if line_count <= 0:
        return []
    if not normalized:
        return [""] * line_count

    words = normalized.split()
    lines: list[str] = []
    current_words: list[str] = []
    target_chars = max(1, len(normalized) / line_count)

    for word in words:
        remaining_lines = line_count - len(lines)
        remaining_words = len(words) - sum(len(line.split()) for line in lines) - len(current_words)
        if (
            current_words
            and len(lines) < line_count - 1
            and len(" ".join(current_words + [word])) > target_chars
            and remaining_words >= remaining_lines
        ):
            lines.append(" ".join(current_words))
            current_words = [word]
            continue
        current_words.append(word)

    if current_words:
        lines.append(" ".join(current_words))

    while len(lines) < line_count:
        lines.append("")
    return lines[:line_count]


def _split_text_by_line_budgets(text: str, line_budgets: list[int]) -> list[str]:
    normalized = " ".join(text.split())
    if not line_budgets:
        return []
    if not normalized:
        return [""] * len(line_budgets)

    total_budget = sum(max(1, budget) for budget in line_budgets)
    words = normalized.split()
    lines: list[str] = []
    word_index = 0

    for line_index, budget in enumerate(line_budgets):
        remaining_lines = len(line_budgets) - line_index
        if remaining_lines == 1:
            lines.append(" ".join(words[word_index:]))
            break

        target_chars = max(1, len(normalized) * max(1, budget) / total_budget)
        current_words: list[str] = []
        while word_index < len(words):
            next_words = current_words + [words[word_index]]
            next_text = " ".join(next_words)
            remaining_words_after_next = len(words) - word_index - 1
            if (
                current_words
                and len(next_text) > target_chars
                and remaining_words_after_next >= remaining_lines - 1
            ):
                break
            current_words = next_words
            word_index += 1

        lines.append(" ".join(current_words))

    while len(lines) < len(line_budgets):
        lines.append("")
    return lines[: len(line_budgets)]


def _is_ocr_ui_line(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if not normalized:
        return False

    # Only remove lines that look like form controls, not normal prose.
    radio_like_prefixes = ("o ", "0 ", "® ", "☐ ", "☑ ", "[ ] ", "[x] ", "[ x ] ")
    if normalized.startswith(radio_like_prefixes) and len(normalized) <= 140:
        return True

    exact_ui_phrases = (
        "generate lorem ipsum",
        "générer du lorem ipsum",
        "generer du lorem ipsum",
    )
    if normalized in exact_ui_phrases:
        return True

    return False


def _clean_ocr_overlay_text(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(line)
            continue
        if _is_ocr_ui_line(stripped):
            continue
        cleaned_lines.append(line)

    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or text.strip()



def _filter_ocr_layout_text_lines(
    ocr_layout: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop OCR layout lines that correspond to UI controls, not body text."""
    filtered = []
    for line in ocr_layout:
        text = str(line.get("text", "")).strip()
        if text and _is_ocr_ui_line(text):
            continue
        filtered.append(line)
    return filtered

def _ocr_layout_render_lines(
    replacement: dict[str, Any],
    line_count: int,
    ocr_layout: list[dict[str, Any]] | None = None,
) -> list[str]:
    translated_text = _clean_ocr_overlay_text(replacement.get("translated_text", ""))
    source_text = replacement.get("source_text", "")
    if not translated_text.strip():
        return [line.strip() for line in source_text.splitlines() if line.strip()][:line_count]

    line_budgets = [
        max(1, len(str(layout_line.get("text", "")).strip()))
        for layout_line in (ocr_layout or [])
    ]

    translated_paragraphs = [
        " ".join(paragraph.split())
        for paragraph in translated_text.split("\n\n")
        if paragraph.strip()
    ]
    source_paragraphs = [
        [line.strip() for line in paragraph.splitlines() if line.strip()]
        for paragraph in source_text.split("\n\n")
        if paragraph.strip()
    ]

    if translated_paragraphs and len(translated_paragraphs) == len(source_paragraphs):
        lines: list[str] = []
        for paragraph_index, source_lines in enumerate(source_paragraphs):
            lines.extend(
                _split_text_to_line_count(
                    translated_paragraphs[paragraph_index],
                    len(source_lines),
                )
            )
        if len(lines) == line_count:
            return lines

    explicit_lines = [line.strip() for line in translated_text.splitlines() if line.strip()]
    if len(explicit_lines) == line_count:
        return explicit_lines

    if len(line_budgets) == line_count:
        return _split_text_by_line_budgets(translated_text, line_budgets)

    return _split_text_to_line_count(translated_text, line_count)


def _group_ocr_layout_blocks(ocr_layout: list[dict]) -> list[list[dict]]:
    blocks = {}
    for line in ocr_layout:
        key = (line.get("block_num"), line.get("par_num"))
        blocks.setdefault(key, []).append(line)

    return list(blocks.values())


def _compute_block_bbox(block_lines, rect, crop_width_px, crop_height_px):
    x0s, y0s, x1s, y1s = [], [], [], []

    for l in block_lines:
        b = l.get("bbox_px") or {}
        try:
            x0s.append(float(b.get("x0", 0)))
            y0s.append(float(b.get("y0", 0)))
            x1s.append(float(b.get("x1", 0)))
            y1s.append(float(b.get("y1", 0)))
        except (TypeError, ValueError):
            continue

    if not x0s:
        return None

    return fitz.Rect(
        rect.x0 + (min(x0s) / crop_width_px) * rect.width,
        rect.y0 + (min(y0s) / crop_height_px) * rect.height,
        rect.x0 + (max(x1s) / crop_width_px) * rect.width,
        rect.y0 + (max(y1s) / crop_height_px) * rect.height,
    ) & rect



def _fit_ocr_textbox_font_size(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontname: str = "helv",
    min_size: float = 4.5,
    max_size: float = 9.0,
    color: tuple[float, float, float] = (0, 0, 0),
) -> float:
    """Return the largest font size that fits text inside rect.

    Trial insertions are performed on a scratch page so the real page is not
    mutated during fitting.
    """
    cleaned = text.strip()
    if not cleaned:
        return min_size

    doc = fitz.open()
    try:
        scratch = doc.new_page(width=page.rect.width, height=page.rect.height)

        low = min_size
        high = max_size
        best = min_size

        for _ in range(10):
            mid = (low + high) / 2.0

            result = scratch.insert_textbox(
                rect,
                cleaned,
                fontsize=mid,
                fontname=fontname,
                color=color,
                align=fitz.TEXT_ALIGN_LEFT,
            )

            fits = result >= 0
            scratch.clean_contents()

            if fits:
                best = mid
                low = mid
            else:
                high = mid

        return max(min_size, min(best, max_size))
    finally:
        doc.close()

def _render_ocr_layout_overlay(
    page: fitz.Page,
    rect: fitz.Rect,
    replacement: dict[str, Any],
) -> bool:
    ocr_layout = _filter_ocr_layout_text_lines(replacement.get("ocr_layout") or [])
    if not ocr_layout:
        return False

    crop_rect = _rect_from_bbox(replacement.get("crop_bbox", {})) or rect
    crop_width_px = crop_rect.width * DEFAULT_OCR_ZOOM
    crop_height_px = crop_rect.height * DEFAULT_OCR_ZOOM
    if crop_width_px <= 0 or crop_height_px <= 0:
        return False

    blocks = _group_ocr_layout_blocks(ocr_layout)

    # Heuristic: if many lines → render by OCR blocks, preserving a short
    # first title line separately from the body paragraph.
    if len(ocr_layout) >= 6:
        translated_text = _clean_ocr_overlay_text(replacement.get("translated_text", ""))
        paragraphs = [p.strip() for p in translated_text.split("\n\n") if p.strip()]

        rendered_blocks = 0

        # Common scanned-layout case: one short title line followed by body text.
        has_title_block = bool(blocks and len(blocks[0]) == 1 and len(str(blocks[0][0].get("text", "")).strip()) <= 80)

        if has_title_block and paragraphs:
            title_text = paragraphs[0].splitlines()[0].strip()
            body_text = "\n\n".join(paragraphs[1:]).strip()
            if not body_text:
                body_text = translated_text.replace(title_text, "", 1).strip()

            title_rect = _compute_block_bbox(blocks[0], crop_rect, crop_width_px, crop_height_px)
            body_lines = [line for block in blocks[1:] for line in block]
            body_rect = _compute_block_bbox(body_lines, crop_rect, crop_width_px, crop_height_px)

            if title_rect and not title_rect.is_empty and title_text:
                title_box = title_rect + (2, 0, -2, 2)
                page.draw_rect(title_rect + (-1, -1, 1, 3), color=(1, 1, 1), fill=(1, 1, 1), width=0)
                title_size = _fit_ocr_textbox_font_size(
                    page,
                    title_box,
                    title_text,
                    min_size=5.5,
                    max_size=13.0,
                )
                page.insert_textbox(
                    title_box,
                    title_text,
                    fontsize=title_size,
                    fontname="helv",
                    color=(0, 0, 0),
                )
                rendered_blocks += 1

            if body_rect and not body_rect.is_empty and body_text:
                text_box = body_rect + (2, 2, -2, -2)
                page.draw_rect(body_rect + (-1, -1, 1, 1), color=(1, 1, 1), fill=(1, 1, 1), width=0)
                font_size = _fit_ocr_textbox_font_size(
                    page,
                    text_box,
                    body_text,
                    min_size=5.0,
                    max_size=13.0,
                )
                page.insert_textbox(
                    text_box,
                    body_text,
                    fontsize=font_size,
                    fontname="helv",
                    color=(0, 0, 0),
                )
                rendered_blocks += 1

            return rendered_blocks > 0

        render_lines = _ocr_layout_render_lines(replacement, len(ocr_layout), ocr_layout)
        line_offset = 0

        for block in blocks:
            block_rect = _compute_block_bbox(block, crop_rect, crop_width_px, crop_height_px)
            if not block_rect or block_rect.is_empty:
                line_offset += len(block)
                continue

            block_lines = render_lines[line_offset : line_offset + len(block)]
            line_offset += len(block)

            block_text = "\n".join(line.strip() for line in block_lines if line.strip())
            if not block_text:
                continue

            text_box = block_rect + (2, 2, -2, -2)
            page.draw_rect(block_rect + (-1, -1, 1, 1), color=(1, 1, 1), fill=(1, 1, 1), width=0)
            font_size = _fit_ocr_textbox_font_size(
                page,
                text_box,
                block_text,
                min_size=5.0,
                max_size=13.0,
            )

            page.insert_textbox(
                text_box,
                block_text,
                fontsize=font_size,
                fontname="helv",
                color=(0, 0, 0),
            )
            rendered_blocks += 1

        return rendered_blocks > 0

    render_lines = _ocr_layout_render_lines(replacement, len(ocr_layout), ocr_layout)

    rendered_count = 0
    for index, layout_line in enumerate(ocr_layout):
        bbox_px = layout_line.get("bbox_px") or {}
        try:
            x0 = float(bbox_px.get("x0", 0.0))
            y0 = float(bbox_px.get("y0", 0.0))
            x1 = float(bbox_px.get("x1", 0.0))
            y1 = float(bbox_px.get("y1", 0.0))
        except (TypeError, ValueError):
            continue

        if x1 <= x0 or y1 <= y0:
            continue

        line_rect = fitz.Rect(
            crop_rect.x0 + (x0 / crop_width_px) * crop_rect.width,
            crop_rect.y0 + (y0 / crop_height_px) * crop_rect.height,
            crop_rect.x0 + (x1 / crop_width_px) * crop_rect.width,
            crop_rect.y0 + (y1 / crop_height_px) * crop_rect.height,
        ) & page.rect
        if line_rect.is_empty:
            continue

        line_text = render_lines[index].strip() if index < len(render_lines) else ""
        if not line_text:
            line_text = str(layout_line.get("text", "")).strip()
        if not line_text:
            continue

        page.draw_rect(line_rect + (-0.5, -0.5, 0.5, 0.5), color=(1, 1, 1), fill=(1, 1, 1), width=0)
        font_size = max(5.0, min(12.5, line_rect.height * 0.95))
        text_width = fitz.get_text_length(line_text, fontname="helv", fontsize=font_size)
        if text_width > line_rect.width and text_width > 0:
            font_size = max(4.0, font_size * (line_rect.width / text_width))

        page.insert_text(
            fitz.Point(line_rect.x0, line_rect.y1),
            line_text,
            fontsize=font_size,
            fontname="helv",
            color=(0, 0, 0),
        )
        rendered_count += 1

    return rendered_count > 0


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

            if (
                strategy == "native_overlay_candidate"
                and status == "translated"
                and (
                    fit_risk in allowed_native_fit_risks
                    or replacement.get("role") == "table_header_cell"
                )
            ):
                page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
                translated_text = replacement.get("translated_text", "")

                approx_line_count = max(1, translated_text.count("\n") + len(translated_text) // 90)
                font_size = min(10, max(6, rect.height / (approx_line_count * 1.2)))
                text_box = rect + (2, 2, -2, -2)
                font_size = _fit_ocr_textbox_font_size(
                    page,
                    text_box,
                    translated_text,
                    min_size=4.0,
                    max_size=font_size,
                )

                overflow = page.insert_textbox(
                    text_box,
                    translated_text,
                    fontsize=font_size,
                    fontname="helv",
                    color=(0, 0, 0),
                )
                if overflow < 0:
                    page.insert_text(
                        fitz.Point(text_box.x0, text_box.y1),
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
                page_ocr_recommendations[recommendation] = page_ocr_recommendations.get(recommendation, 0) + 1

                decision = replacement.get("ocr_decision") or {}
                confidence = decision.get("confidence", "medium")

                if confidence in {"high", "medium"}:
                    translated_text = _clean_ocr_overlay_text(replacement.get("translated_text", ""))

                    rendered_with_layout = _render_ocr_layout_overlay(page, rect, replacement)

                    if not rendered_with_layout:
                        page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), width=0)
                        # Conservative OCR block fitting: avoid silent truncation in dense translated OCR regions.
                        text_box = rect + (4, 4, -4, -4)
                        approx_line_count = max(
                            1,
                            translated_text.count("\n") + len(translated_text) // 65,
                        )
                        font_size = min(8.0, max(4.5, text_box.height / (approx_line_count * 1.45)))
                        page.insert_textbox(
                            text_box,
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
    if replacement.get("edge_clipping_detected") or "edge_clipping_detected" in diagnostic_flags:
        return "manual_review", [
            "edge_clipping_detected",
            f"edge_clipping_lines={replacement.get('edge_clipping_line_count', 0)}",
        ]

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
                    "edge_clipping_detected": bool(replacement.get("edge_clipping_detected", False)),
                    "edge_clipping_line_count": int(replacement.get("edge_clipping_line_count", 0) or 0),
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
