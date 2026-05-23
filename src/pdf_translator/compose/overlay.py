from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import requests

from pdf_translator.translate.glossary import (
    translate_outline_sentence,
    translate_scientific_label,
    translate_slide_title,
)


PLACEHOLDER_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]")
CLAUSE_SPLIT_RE = re.compile(r"(\s*[:;,]\s*)")


def build_pre_overlay_report(overlay_ready_report: dict[str, Any]) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []
    total_regions = 0
    total_lines = 0

    for page in overlay_ready_report.get("pages", []):
        regions: list[dict[str, Any]] = []

        for candidate in page.get("candidates", []):
            region = {
                "page_number": page["page_number"],
                "block_index": candidate["block_index"],
                "role": candidate.get("role", "content"),
                "bbox": candidate["bbox"],
                "source_text": candidate["text"],
                "line_count": candidate["line_count"],
                "lines": candidate["lines"],
            }
            regions.append(region)

        total_regions += len(regions)
        total_lines += sum(region["line_count"] for region in regions)
        page_reports.append(
            {
                "page_number": page["page_number"],
                "region_count": len(regions),
                "regions": regions,
            }
        )

    return {
        "selected_pages": overlay_ready_report.get("selected_pages", []),
        "page_count": len(page_reports),
        "total_regions": total_regions,
        "total_lines": total_lines,
        "pages": page_reports,
    }


def _collect_span_colors(lines: list[dict[str, Any]]) -> list[int]:
    colors: list[int] = []
    for line in lines:
        for span in line.get("spans", []):
            color = span.get("color")
            if color is None:
                continue
            colors.append(int(color))
    return colors


def _summarize_region_color(lines: list[dict[str, Any]]) -> tuple[int | None, str]:
    colors = _collect_span_colors(lines)
    if not colors:
        return None, "unknown"

    counter = Counter(colors)
    if len(counter) == 1:
        return colors[0], "uniform"

    return counter.most_common(1)[0][0], "mixed"


def _build_source_line_payload(line: dict[str, Any], fallback_bbox: dict[str, float]) -> dict[str, Any] | None:
    line_text = line.get("text", "").strip()
    if not line_text:
        return None

    line_color, line_color_mode = _summarize_region_color([line])
    source_spans: list[dict[str, Any]] = []
    font_names: list[str] = []
    font_sizes: list[float] = []
    for span in line.get("spans", []):
        span_text = span.get("text", "")
        if not span_text.strip():
            continue
        if span.get("font"):
            font_names.append(str(span.get("font")))
        if span.get("size") is not None:
            font_sizes.append(float(span.get("size")))
        source_spans.append(
            {
                "text": span_text,
                "source_color": span.get("color"),
            }
        )

    if not source_spans:
        source_spans = [{"text": line_text, "source_color": line_color}]

    dominant_font = Counter(font_names).most_common(1)[0][0] if font_names else None
    average_size = sum(font_sizes) / len(font_sizes) if font_sizes else None

    return {
        "text": line_text,
        "bbox": line.get("bbox", fallback_bbox),
        "source_color": line_color,
        "source_color_mode": line_color_mode,
        "source_font": dominant_font,
        "source_font_size": average_size,
        "source_spans": source_spans,
    }


def _split_translated_text_by_source_spans(
    translated_text: str,
    source_spans: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    if not translated_text.strip():
        return None

    meaningful_spans = [span for span in source_spans if span.get("text", "").strip()]
    if len(meaningful_spans) <= 1:
        return None

    colors = {span.get("source_color") for span in meaningful_spans}
    if len(colors) <= 1:
        return None

    total_units = sum(max(1, len(span.get("text", "").strip())) for span in meaningful_spans)
    if total_units <= 0:
        return None

    translated_length = len(translated_text)
    if translated_length <= 1:
        return None

    segments: list[dict[str, Any]] = []
    start = 0
    consumed_units = 0

    for index, span in enumerate(meaningful_spans):
        consumed_units += max(1, len(span.get("text", "").strip()))
        if index == len(meaningful_spans) - 1:
            end = translated_length
        else:
            end = round(translated_length * (consumed_units / total_units))
            end = max(start + 1, min(end, translated_length - (len(meaningful_spans) - index - 1)))

        segment_text = translated_text[start:end]
        if segment_text:
            segments.append(
                {
                    "text": segment_text,
                    "source_color": span.get("source_color"),
                }
            )
        start = end

    return segments or None


def _split_text_to_source_lines(
    translated_text: str,
    source_lines: list[dict[str, Any]],
) -> list[str] | None:
    words = translated_text.split()
    if len(words) < len(source_lines) or len(source_lines) <= 1:
        return None

    source_units = [max(1, len(line.get("text", "").strip())) for line in source_lines]
    total_units = sum(source_units)
    if total_units <= 0:
        return None

    target_counts: list[int] = []
    assigned = 0
    for index, units in enumerate(source_units):
        if index == len(source_lines) - 1:
            count = max(1, len(words) - assigned)
        else:
            count = max(1, round(len(words) * (units / total_units)))
            remaining_slots = len(source_lines) - index - 1
            count = min(count, len(words) - assigned - remaining_slots)
        target_counts.append(count)
        assigned += count

    if sum(target_counts) != len(words):
        target_counts[-1] += len(words) - sum(target_counts)

    split_lines: list[str] = []
    cursor = 0
    for count in target_counts:
        split_lines.append(" ".join(words[cursor:cursor + count]))
        cursor += count

    return split_lines if len(split_lines) == len(source_lines) else None


def pre_overlay_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report['selected_pages']}",
        f"Pre-overlay pages: {report['page_count']}",
        f"Total regions: {report['total_regions']}",
        f"Total lines: {report['total_lines']}",
    ]

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: regions={page['region_count']}"
        )
        for region in page.get("regions", [])[:3]:
            preview = region["source_text"].replace("\n", " | ").strip()[:180]
            lines.append(
                f"  block {region['block_index']}: bbox={region['bbox']} text={preview}"
            )

    return "\n".join(lines)


def write_pre_overlay_report(
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
        pre_overlay_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path


def render_pre_overlay_diagnostics(
    pdf_path: Path,
    pre_overlay_report: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, list[Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)

    source_doc = fitz.open(pdf_path)
    annotated_doc = fitz.open()
    image_paths: list[Path] = []

    for page_report in pre_overlay_report.get("pages", []):
        page_number = page_report["page_number"]
        annotated_doc.insert_pdf(source_doc, from_page=page_number - 1, to_page=page_number - 1)
        page = annotated_doc[-1]

        for region in page_report.get("regions", []):
            bbox = region["bbox"]
            rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
            page.draw_rect(rect, color=(1, 0, 0), width=1.2)

            label = f"B{region['block_index']}"
            label_point = fitz.Point(rect.x0, max(10, rect.y0 - 3))
            page.insert_text(
                label_point,
                label,
                fontsize=8,
                color=(1, 0, 0),
            )

    pdf_output_path = output_dir / f"{stem}.pdf"
    annotated_doc.save(pdf_output_path)

    for index, page in enumerate(annotated_doc, start=1):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        image_path = output_dir / f"{stem}_page_{index:03d}.png"
        pixmap.save(image_path)
        image_paths.append(image_path)

    annotated_doc.close()
    source_doc.close()

    return pdf_output_path, image_paths


def _looks_symbolic(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if "|" in stripped and len(stripped) <= 40:
        return True
    letters = sum(1 for char in stripped if char.isalpha())
    return letters <= 4 and len(stripped) <= 24


def _merge_line_bboxes(
    lines: list[dict[str, Any]],
    fallback_bbox: dict[str, float],
) -> dict[str, float]:
    bbox_lines = [line for line in lines if line.get("bbox")]
    if not bbox_lines:
        return fallback_bbox

    return {
        "x0": min(line["bbox"]["x0"] for line in bbox_lines),
        "y0": min(line["bbox"]["y0"] for line in bbox_lines),
        "x1": max(line["bbox"]["x1"] for line in bbox_lines),
        "y1": max(line["bbox"]["y1"] for line in bbox_lines),
    }


def _build_chunk_region(
    lines: list[dict[str, Any]],
    fallback_bbox: dict[str, float],
    role: str,
) -> dict[str, Any] | None:
    texts = [line.get("text", "").strip() for line in lines if line.get("text", "").strip()]
    if not texts:
        return None

    source_text = "\n".join(texts)
    source_color, source_color_mode = _summarize_region_color(lines)
    source_lines: list[dict[str, Any]] = []
    for line in lines:
        payload = _build_source_line_payload(line, fallback_bbox)
        if payload is not None:
            source_lines.append(payload)
    return {
        "source_text": source_text,
        "role": role,
        "bbox": _merge_line_bboxes(lines, fallback_bbox),
        "source_color": source_color,
        "source_color_mode": source_color_mode,
        "source_lines": source_lines,
        "translate": not _looks_symbolic(source_text),
    }


def build_translation_preview_segments(
    pre_overlay_report: dict[str, Any],
    selected_pages: list[int],
    max_lines_per_segment: int = 2,
    max_chars_per_segment: int = 220,
) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []

    for page in pre_overlay_report.get("pages", []):
        if page["page_number"] not in selected_pages:
            continue

        regions: list[dict[str, Any]] = []
        for region in page.get("regions", []):
            lines = region.get("lines", [])
            source_text = region.get("source_text", "")
            role = region.get("role", "content")
            source_color, source_color_mode = _summarize_region_color(lines)
            source_lines = [
                payload
                for line in lines
                for payload in [_build_source_line_payload(line, region["bbox"])]
                if payload is not None
            ]

            if _looks_symbolic(source_text):
                regions.append(
                    {
                        "source_text": source_text,
                        "role": role,
                        "bbox": region["bbox"],
                        "source_color": source_color,
                        "source_color_mode": source_color_mode,
                        "source_lines": source_lines,
                        "translate": False,
                    }
                )
                continue

            if role == "slide_title":
                regions.append(
                    {
                        "source_text": source_text,
                        "role": role,
                        "bbox": region["bbox"],
                        "source_color": source_color,
                        "source_color_mode": source_color_mode,
                        "source_lines": source_lines,
                        "translate": True,
                    }
                )
                continue

            current_lines: list[dict[str, Any]] = []
            current_chars = 0
            chunks: list[dict[str, Any]] = []

            for line in lines:
                line_text = line.get("text", "").strip()
                if not line_text:
                    continue

                line_len = len(line_text)
                should_split = current_lines and (
                    len(current_lines) >= max_lines_per_segment
                    or current_chars + line_len > max_chars_per_segment
                )

                if should_split:
                    chunk = _build_chunk_region(current_lines, region["bbox"], region.get("role", "content"))
                    if chunk is not None:
                        chunks.append(chunk)
                    current_lines = []
                    current_chars = 0

                current_lines.append(line)
                current_chars += line_len

            if current_lines:
                chunk = _build_chunk_region(current_lines, region["bbox"], region.get("role", "content"))
                if chunk is not None:
                    chunks.append(chunk)

            if not chunks:
                chunks = [
                    {
                        "source_text": source_text,
                        "role": region.get("role", "content"),
                        "bbox": region["bbox"],
                        "source_color": source_color,
                        "source_color_mode": source_color_mode,
                        "source_lines": source_lines,
                        "translate": not _looks_symbolic(source_text),
                    }
                ]

            for chunk in chunks:
                regions.append(chunk)

        page_reports.append({"page_number": page["page_number"], "regions": regions})

    return {"selected_pages": selected_pages, "pages": page_reports}


def _translate_region_with_timeout_fallback(
    source_text: str,
    translate_text_fn,
    role: str = "content",
) -> tuple[str, str]:
    if role == "slide_title":
        return translate_slide_title(source_text), "translated"

    outline_translation = translate_outline_sentence(source_text)
    if outline_translation is not None:
        return outline_translation, "translated"

    label_translation = translate_scientific_label(source_text)
    if label_translation is not None:
        return label_translation, "translated"

    try:
        return translate_text_fn(source_text), "translated"
    except requests.exceptions.Timeout:
        source_lines = [line.strip() for line in source_text.splitlines() if line.strip()]
        if len(source_lines) == 1:
            parts = [part for part in CLAUSE_SPLIT_RE.split(source_lines[0]) if part]
            if len(parts) > 1:
                translated_parts: list[str] = []
                for part in parts:
                    if CLAUSE_SPLIT_RE.fullmatch(part):
                        translated_parts.append(part)
                        continue
                    try:
                        translated_parts.append(translate_text_fn(part.strip()))
                    except requests.exceptions.Timeout:
                        break
                else:
                    return "".join(translated_parts), "translated"

        if len(source_lines) <= 1:
            return f"[TIMEOUT] {source_text.replace(chr(10), ' | ')}", "timeout"

        translated_lines: list[str] = []
        for line in source_lines:
            try:
                translated_lines.append(translate_text_fn(line))
            except requests.exceptions.Timeout:
                return f"[TIMEOUT] {source_text.replace(chr(10), ' | ')}", "timeout"

        return "\n".join(translated_lines), "translated"


def _sanitize_translated_text(source_text: str, translated_text: str) -> str:
    source_placeholders = set(PLACEHOLDER_RE.findall(source_text))
    translated_placeholders = set(PLACEHOLDER_RE.findall(translated_text))
    unexpected = translated_placeholders - source_placeholders

    if not unexpected:
        return translated_text.strip()

    sanitized = translated_text
    for placeholder in unexpected:
        sanitized = sanitized.replace(placeholder, "")

    sanitized_lines: list[str] = []
    for raw_line in sanitized.splitlines():
        cleaned_line = re.sub(r"\s+", " ", raw_line).strip()
        if not cleaned_line:
            continue
        if PLACEHOLDER_RE.fullmatch(cleaned_line):
            continue
        sanitized_lines.append(cleaned_line)

    return "\n".join(sanitized_lines).strip()


def build_translation_preview_report(
    segments_report: dict[str, Any],
    translate_text_fn,
) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []

    for page in segments_report.get("pages", []):
        regions: list[dict[str, Any]] = []
        for region in page.get("regions", []):
            source_text = region["source_text"]
            source_lines = region.get("source_lines", [])

            if not region.get("translate", True):
                translated_text = source_text
                status = "skipped"
                translated_lines = [
                    {
                        "text": line["text"],
                        "bbox": line["bbox"],
                        "source_color": line.get("source_color"),
                        "source_color_mode": line.get("source_color_mode", "unknown"),
                    }
                    for line in source_lines
                ]
            elif region.get("role") == "slide_title":
                translated_text = translate_slide_title(source_text)
                translated_text = _sanitize_translated_text(source_text, translated_text)
                status = "translated"
                translated_lines = None
            elif region.get("role") == "diagram_label":
                translated_text = translate_scientific_label(source_text) or source_text
                translated_text = _sanitize_translated_text(source_text, translated_text)
                status = "translated" if translated_text != source_text else "skipped"
                translated_lines = None
            else:
                translated_text, status = _translate_region_with_timeout_fallback(
                    source_text,
                    translate_text_fn,
                    region.get("role", "content"),
                )
                translated_text = _sanitize_translated_text(source_text, translated_text)
                translated_lines = None

                if status == "translated" and source_lines:
                    translated_line_texts = [line.strip() for line in translated_text.splitlines() if line.strip()]
                    if len(translated_line_texts) != len(source_lines):
                        inferred_lines = _split_text_to_source_lines(translated_text, source_lines)
                        if inferred_lines is not None:
                            translated_line_texts = inferred_lines
                    if len(translated_line_texts) == len(source_lines):
                        translated_lines = [
                            {
                                "text": translated_line_texts[index],
                                "bbox": line["bbox"],
                                "source_color": line.get("source_color"),
                                "source_color_mode": line.get("source_color_mode", "unknown"),
                                "source_font": line.get("source_font"),
                                "source_font_size": line.get("source_font_size"),
                                "translated_segments": _split_translated_text_by_source_spans(
                                    translated_line_texts[index],
                                    line.get("source_spans", []),
                                ),
                            }
                            for index, line in enumerate(source_lines)
                        ]
                    elif len(source_lines) == 1:
                        translated_lines = [
                            {
                                "text": translated_text,
                                "bbox": source_lines[0]["bbox"],
                                "source_color": source_lines[0].get("source_color"),
                                "source_color_mode": source_lines[0].get("source_color_mode", "unknown"),
                                "source_font": source_lines[0].get("source_font"),
                                "source_font_size": source_lines[0].get("source_font_size"),
                                "translated_segments": _split_translated_text_by_source_spans(
                                    translated_text,
                                    source_lines[0].get("source_spans", []),
                                ),
                            }
                        ]

            regions.append(
                {
                    "role": region.get("role", "content"),
                    "source_text": source_text,
                    "translated_text": translated_text,
                    "bbox": region["bbox"],
                    "source_color": region.get("source_color"),
                    "source_color_mode": region.get("source_color_mode", "unknown"),
                    "translated_lines": translated_lines,
                    "status": status,
                }
            )

        page_reports.append({"page_number": page["page_number"], "regions": regions})

    return {"selected_pages": segments_report.get("selected_pages", []), "pages": page_reports}


def translation_preview_report_to_text(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for page in report.get("pages", []):
        lines.append(f"PAGE {page['page_number']}")
        for index, region in enumerate(page.get("regions", []), start=1):
            lines.append(f"Region {index} [{region['status']}]")
            lines.append("FR: " + region["source_text"].replace("\n", " | "))
            lines.append("EN: " + region["translated_text"].replace("\n", " | "))
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def write_translation_preview_report(
    report: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    text_path.write_text(translation_preview_report_to_text(report), encoding="utf-8")
    return json_path, text_path


def _text_length(text: str) -> int:
    return len(text.replace("\n", " ").strip())


def _line_count(text: str) -> int:
    return len([line for line in text.splitlines() if line.strip()])


def _bbox_dimensions(bbox: dict[str, Any]) -> tuple[float, float, float]:
    width = max(0.0, float(bbox.get("x1", 0.0)) - float(bbox.get("x0", 0.0)))
    height = max(0.0, float(bbox.get("y1", 0.0)) - float(bbox.get("y0", 0.0)))
    return width, height, width * height


def _line_fit_diagnostics(line: dict[str, Any]) -> dict[str, Any]:
    text = line.get("text", "")
    bbox = line.get("bbox", {})
    width, height, _ = _bbox_dimensions(bbox)
    usable_width = max(1.0, width - 4.0)
    source_font_size = float(line.get("source_font_size") or 12.0)
    fontname = _map_source_font_to_overlay_font(line.get("source_font"))
    rendered_width = fitz.get_text_length(text, fontname=fontname, fontsize=source_font_size)
    width_ratio = rendered_width / usable_width if usable_width else 0.0
    fitted_font_size = _fit_single_line_fontsize(
        fitz.Rect(0, 0, max(1.0, width), max(1.0, height)),
        text,
        fontname,
        source_font_size,
        max(6.0, source_font_size - 3.0),
    )

    return {
        "text_length": _text_length(text),
        "bbox_width": round(width, 2),
        "bbox_height": round(height, 2),
        "source_font_size": round(source_font_size, 2),
        "rendered_width_at_source_size": round(rendered_width, 2),
        "width_ratio_at_source_size": round(width_ratio, 2),
        "fitted_font_size": round(fitted_font_size, 2),
    }


def _build_native_fit_diagnostics(region: dict[str, Any]) -> dict[str, Any]:
    source_text = region.get("source_text", "")
    translated_text = region.get("translated_text", "")
    bbox = region.get("bbox", {})
    translated_lines = region.get("translated_lines") or []
    source_len = _text_length(source_text)
    translated_len = _text_length(translated_text)
    width, height, area = _bbox_dimensions(bbox)
    translated_density = (translated_len / area * 1000.0) if area else 0.0
    source_line_count = _line_count(source_text)
    translated_line_count = len(translated_lines) if translated_lines else _line_count(translated_text)

    line_diagnostics = [_line_fit_diagnostics(line) for line in translated_lines if line.get("bbox")]
    max_line_width_ratio = max(
        (line["width_ratio_at_source_size"] for line in line_diagnostics),
        default=0.0,
    )
    min_fitted_font_size = min(
        (line["fitted_font_size"] for line in line_diagnostics),
        default=None,
    )
    min_source_font_size = min(
        (line["source_font_size"] for line in line_diagnostics),
        default=None,
    )

    flags: list[str] = []
    if area <= 0:
        flags.append("missing_bbox")
    if width < 24 or height < 6:
        flags.append("very_small_region")
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
    if max_line_width_ratio > 1.0:
        flags.append("translated_line_overflow")
    if max_line_width_ratio > 1.35:
        flags.append("severe_line_overflow")
    if (
        min_fitted_font_size is not None
        and min_source_font_size is not None
        and min_fitted_font_size <= min_source_font_size - 2.5
    ):
        flags.append("requires_significant_font_shrink")

    return {
        "bbox_width": round(width, 2),
        "bbox_height": round(height, 2),
        "bbox_area": round(area, 2),
        "source_line_count": source_line_count,
        "translated_line_count": translated_line_count,
        "translated_chars_per_1000pt2": round(translated_density, 2),
        "max_line_width_ratio_at_source_size": round(max_line_width_ratio, 2),
        "min_fitted_font_size": min_fitted_font_size,
        "line_diagnostics": line_diagnostics,
        "flags": sorted(flags),
    }


def _estimate_native_fit_risk(
    role: str,
    status: str,
    overflow_ratio: float,
    fit_diagnostics: dict[str, Any],
) -> str:
    flags = set(fit_diagnostics.get("flags", []))
    density = float(fit_diagnostics.get("translated_chars_per_1000pt2", 0.0))
    max_line_ratio = float(fit_diagnostics.get("max_line_width_ratio_at_source_size", 0.0))

    if status == "timeout":
        return "high"
    if status != "translated":
        return "low"
    if flags & {"missing_bbox", "empty_translation", "severe_line_overflow"}:
        return "high"
    if "very_small_region" in flags and overflow_ratio > 1.15:
        return "high"
    if "large_translation_expansion" in flags and (density > 18.0 or max_line_ratio > 1.2):
        return "high"
    if density > 24.0 and not fit_diagnostics.get("line_diagnostics"):
        return "high"

    if role == "slide_title" and overflow_ratio <= 1.5:
        return "medium" if overflow_ratio > 1.1 else "low"
    if flags & {"translated_line_overflow", "requires_significant_font_shrink", "dense_text_for_region"}:
        return "medium"
    if overflow_ratio > 1.35:
        return "high"
    if overflow_ratio > 1.1:
        return "medium"
    return "low"


def _native_apply_strategy(status: str, fit_risk: str, fit_diagnostics: dict[str, Any]) -> str:
    flags = set(fit_diagnostics.get("flags", []))
    if status == "timeout":
        return "native_review_required"
    if status != "translated":
        return "native_skipped"
    if fit_risk == "high" or flags & {"missing_bbox", "empty_translation", "severe_line_overflow"}:
        return "native_review_required"
    if flags & {"translated_line_overflow", "requires_significant_font_shrink", "dense_text_for_region"}:
        return "native_overlay_with_fit_adjustment"
    return "native_overlay_candidate"


def _page_apply_policy_for_readiness(status: str) -> str:
    return {
        "ready": "apply_overlay",
        "soft_review": "apply_overlay_with_soft_review",
        "hard_review": "skip_overlay_hard_review",
        "blocked": "skip_overlay_blocked",
    }.get(status, "apply_overlay")


def _overlay_readiness_by_page(
    overlay_ready_report: dict[str, Any] | None,
) -> dict[int, dict[str, Any]]:
    if overlay_ready_report is None:
        return {}
    return {
        int(page.get("page_number")): page.get("overlay_readiness", {})
        for page in overlay_ready_report.get("pages", [])
        if page.get("page_number") is not None
    }


def build_replacement_plan(
    translation_preview_report: dict[str, Any],
    overlay_ready_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []
    total_replacements = 0
    fit_risk_summary: Counter[str] = Counter()
    apply_strategy_summary: Counter[str] = Counter()
    page_apply_policy_summary: Counter[str] = Counter()
    readiness_by_page = _overlay_readiness_by_page(overlay_ready_report)

    for page in translation_preview_report.get("pages", []):
        replacements: list[dict[str, Any]] = []
        page_number = int(page["page_number"])
        readiness = readiness_by_page.get(page_number, {})
        readiness_status = readiness.get("status", "ready")
        page_apply_policy = _page_apply_policy_for_readiness(readiness_status)
        page_apply_policy_summary[page_apply_policy] += 1

        for index, region in enumerate(page.get("regions", []), start=1):
            source_text = region["source_text"]
            translated_text = region["translated_text"]
            status = region["status"]
            bbox = region["bbox"]
            role = region.get("role", "content")

            source_len = _text_length(source_text)
            translated_len = _text_length(translated_text)
            overflow_ratio = (translated_len / source_len) if source_len else 1.0
            fit_diagnostics = _build_native_fit_diagnostics(region)
            fit_risk = _estimate_native_fit_risk(role, status, overflow_ratio, fit_diagnostics)
            apply_strategy = _native_apply_strategy(status, fit_risk, fit_diagnostics)
            fit_risk_summary[fit_risk] += 1
            apply_strategy_summary[apply_strategy] += 1

            replacements.append(
                {
                    "replacement_index": index,
                    "role": role,
                    "bbox": bbox,
                    "source_text": source_text,
                    "translated_text": translated_text,
                    "source_color": region.get("source_color"),
                    "source_color_mode": region.get("source_color_mode", "unknown"),
                    "translated_lines": region.get("translated_lines"),
                    "status": status,
                    "source_length": source_len,
                    "translated_length": translated_len,
                    "overflow_ratio": round(overflow_ratio, 2),
                    "fit_risk": fit_risk,
                    "fit_diagnostics": fit_diagnostics,
                    "apply_strategy": apply_strategy,
                }
            )

        total_replacements += len(replacements)
        page_reports.append(
            {
                "page_number": page_number,
                "overlay_readiness_status": readiness_status,
                "overlay_readiness_reason_summary": readiness.get("reason_summary", {}),
                "overlay_readiness_severity_summary": readiness.get("severity_summary", {}),
                "page_apply_policy": page_apply_policy,
                "replacement_count": len(replacements),
                "replacements": replacements,
            }
        )

    return {
        "selected_pages": translation_preview_report.get("selected_pages", []),
        "page_count": len(page_reports),
        "total_replacements": total_replacements,
        "fit_risk_summary": dict(fit_risk_summary),
        "apply_strategy_summary": dict(apply_strategy_summary),
        "page_apply_policy_summary": dict(page_apply_policy_summary),
        "pages": page_reports,
    }


def replacement_plan_to_text(plan: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {plan['selected_pages']}",
        f"Replacement-plan pages: {plan['page_count']}",
        f"Total replacements: {plan['total_replacements']}",
        f"Fit risks: {json.dumps(plan.get('fit_risk_summary', {}), ensure_ascii=False, sort_keys=True)}",
        f"Apply strategies: {json.dumps(plan.get('apply_strategy_summary', {}), ensure_ascii=False, sort_keys=True)}",
        f"Page apply policies: {json.dumps(plan.get('page_apply_policy_summary', {}), ensure_ascii=False, sort_keys=True)}",
    ]

    for page in plan.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: replacements={page['replacement_count']} "
            f"policy={page.get('page_apply_policy', 'apply_overlay')} "
            f"readiness={page.get('overlay_readiness_status', 'ready')}"
        )
        for item in page.get("replacements", [])[:4]:
            preview = item["translated_text"].replace("\n", " | ").strip()[:160]
            flags = ",".join(item.get("fit_diagnostics", {}).get("flags", [])) or "none"
            lines.append(
                f"  region {item['replacement_index']} [{item['status']}] risk={item['fit_risk']} "
                f"strategy={item.get('apply_strategy', 'unknown')} ratio={item['overflow_ratio']} "
                f"flags={flags} bbox={item['bbox']} text={preview}"
            )

    return "\n".join(lines)


def write_replacement_plan(
    plan: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    text_path = output_dir / f"{stem}.txt"
    json_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    text_path.write_text(replacement_plan_to_text(plan), encoding="utf-8")
    return json_path, text_path


def _fit_text_in_rect(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    fontname: str = "helv",
    color: tuple[float, float, float] = (0, 0, 0),
    align: int = 0,
    max_fontsize: float = 12,
    min_fontsize: float = 6,
    fill_color: tuple[float, float, float] = (1, 1, 1),
) -> float:
    fontsize = max_fontsize

    while fontsize >= min_fontsize:
        remaining = page.insert_textbox(
            rect,
            text,
            fontsize=fontsize,
            fontname=fontname,
            color=color,
            align=align,
        )
        if remaining >= 0:
            return fontsize

        # Remove the failed draw by redrawing the region before retrying.
        page.draw_rect(rect, color=fill_color, fill=fill_color, width=0)
        fontsize -= 0.5

    page.insert_textbox(
        rect,
        text,
        fontsize=min_fontsize,
        fontname=fontname,
        color=(0.7, 0, 0),
        align=align,
    )
    return min_fontsize


def _draw_centered_single_line_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    fontname: str,
    color: tuple[float, float, float],
    max_fontsize: float,
    min_fontsize: float,
) -> float:
    fontsize = max_fontsize
    usable_width = max(1.0, rect.width - 8)

    while fontsize >= min_fontsize:
        text_width = fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
        if text_width <= usable_width:
            x = rect.x0 + max(0.0, (rect.width - text_width) / 2)
            y = rect.y1 - max(1.5, (rect.height - fontsize) / 2.8)
            page.insert_text(
                fitz.Point(x, y),
                text,
                fontsize=fontsize,
                fontname=fontname,
                color=color,
            )
            return fontsize
        fontsize -= 0.5

    text_width = fitz.get_text_length(text, fontname=fontname, fontsize=min_fontsize)
    x = rect.x0 + max(0.0, (rect.width - text_width) / 2)
    y = rect.y1 - max(1.0, (rect.height - min_fontsize) / 2.8)
    page.insert_text(
        fitz.Point(x, y),
        text,
        fontsize=min_fontsize,
        fontname=fontname,
        color=color,
    )
    return min_fontsize


def _fit_single_line_fontsize(
    rect: fitz.Rect,
    text: str,
    fontname: str,
    max_fontsize: float,
    min_fontsize: float,
    padding: float = 2.0,
) -> float:
    usable_width = max(1.0, rect.width - (padding * 2))
    fontsize = max_fontsize
    while fontsize >= min_fontsize:
        if fitz.get_text_length(text, fontname=fontname, fontsize=fontsize) <= usable_width:
            return fontsize
        fontsize -= 0.5
    return min_fontsize


def _draw_left_aligned_single_line_segments(
    page: fitz.Page,
    rect: fitz.Rect,
    segments: list[dict[str, Any]],
    fontname: str,
    default_color: tuple[float, float, float],
    max_fontsize: float,
    min_fontsize: float,
) -> float:
    text = "".join(segment.get("text", "") for segment in segments)
    fontsize = _fit_single_line_fontsize(rect, text, fontname, max_fontsize, min_fontsize)
    x = rect.x0 + 2
    y = rect.y1 - max(1.0, (rect.height - fontsize) / 2.8)

    for segment in segments:
        segment_text = segment.get("text", "")
        if not segment_text:
            continue
        source_color = segment.get("source_color")
        color = _int_to_rgb(source_color) if source_color is not None else default_color
        page.insert_text(
            fitz.Point(x, y),
            segment_text,
            fontsize=fontsize,
            fontname=fontname,
            color=color,
        )
        x += fitz.get_text_length(segment_text, fontname=fontname, fontsize=fontsize)

    return fontsize


def _draw_left_aligned_single_line_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    fontname: str,
    color: tuple[float, float, float],
    max_fontsize: float,
    min_fontsize: float,
    draw_twice: bool = False,
    horizontal_scale_to_fit: bool = False,
    min_horizontal_scale: float = 0.88,
) -> float:
    usable_width = max(1.0, rect.width - 4)
    source_text_width = fitz.get_text_length(text, fontname=fontname, fontsize=max_fontsize)
    if horizontal_scale_to_fit and source_text_width > usable_width:
        horizontal_scale = usable_width / max(source_text_width, 1.0)
        if horizontal_scale >= min_horizontal_scale:
            x = rect.x0 + 2
            y = rect.y1 - max(1.0, (rect.height - max_fontsize) / 2.8)
            morph = (fitz.Point(x, y), fitz.Matrix(horizontal_scale, 1))
            page.insert_text(
                fitz.Point(x, y),
                text,
                fontsize=max_fontsize,
                fontname=fontname,
                color=color,
                morph=morph,
            )
            if draw_twice:
                page.insert_text(
                    fitz.Point(x + 0.15, y),
                    text,
                    fontsize=max_fontsize,
                    fontname=fontname,
                    color=color,
                    morph=(fitz.Point(x + 0.15, y), fitz.Matrix(horizontal_scale, 1)),
                )
            return max_fontsize

    fontsize = _fit_single_line_fontsize(rect, text, fontname, max_fontsize, min_fontsize)
    x = rect.x0 + 2
    y = rect.y1 - max(1.0, (rect.height - fontsize) / 2.8)
    page.insert_text(
        fitz.Point(x, y),
        text,
        fontsize=fontsize,
        fontname=fontname,
        color=color,
    )
    if draw_twice:
        page.insert_text(
            fitz.Point(x + 0.15, y),
            text,
            fontsize=fontsize,
            fontname=fontname,
            color=color,
        )
    return fontsize


def _draw_text_lines(
    page: fitz.Page,
    lines: list[dict[str, Any]],
    fontname: str,
    default_color: tuple[float, float, float],
    max_fontsize: float,
    min_fontsize: float,
    fill_color: tuple[float, float, float],
    fit_risk: str = "low",
) -> None:
    for line in lines:
        bbox = line.get("bbox")
        if not bbox:
            continue
        rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
        line_fontname = _map_source_font_to_overlay_font(line.get("source_font")) if line.get("source_font") else fontname
        line_source_size = line.get("source_font_size")
        line_max_fontsize = float(line_source_size) if line_source_size else max_fontsize
        line_min_fontsize = max(min_fontsize, line_max_fontsize - 3) if line_source_size else min_fontsize
        source_font_name = (line.get("source_font") or "").lower()
        is_bold_source = "bold" in source_font_name
        if fit_risk == "medium" and is_bold_source and "\n" not in line.get("text", ""):
            extra_width = min(24.0, rect.width * 0.25)
            rect.x1 = min(page.rect.width - 24, rect.x1 + extra_width)
        translated_segments = line.get("translated_segments")
        if translated_segments:
            _draw_left_aligned_single_line_segments(
                page,
                rect,
                translated_segments,
                fontname=line_fontname,
                default_color=default_color,
                max_fontsize=line_max_fontsize,
                min_fontsize=line_min_fontsize,
            )
            continue
        if line.get("source_color") is not None and line.get("source_color_mode") == "uniform":
            color = _int_to_rgb(line["source_color"])
        else:
            color = default_color
        if "\n" not in line.get("text", ""):
            adjusted_max_fontsize = line_max_fontsize
            draw_twice = False
            horizontal_scale_to_fit = fit_risk == "medium" and is_bold_source
            if is_bold_source and line.get("source_color") not in (None, 0):
                adjusted_max_fontsize = line_max_fontsize + 0.6
                draw_twice = True
            _draw_left_aligned_single_line_text(
                page,
                rect,
                line.get("text", ""),
                fontname=line_fontname,
                color=color,
                max_fontsize=adjusted_max_fontsize,
                min_fontsize=line_min_fontsize,
                draw_twice=draw_twice,
                horizontal_scale_to_fit=horizontal_scale_to_fit,
            )
            continue
        _fit_text_in_rect(
            page,
            rect,
            line.get("text", ""),
            fontname=line_fontname,
            color=color,
            align=0,
            max_fontsize=line_max_fontsize,
            min_fontsize=line_min_fontsize,
            fill_color=fill_color,
        )


def _estimate_fill_color(
    page: fitz.Page,
    rect: fitz.Rect,
) -> tuple[float, float, float]:
    pix = page.get_pixmap(clip=rect, alpha=False)
    width = pix.width
    height = pix.height
    samples = pix.samples
    channels = pix.n

    if width <= 0 or height <= 0 or channels < 3:
        return (1, 1, 1)

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        offset = (y * width + x) * channels
        return samples[offset], samples[offset + 1], samples[offset + 2]

    colors: Counter[tuple[int, int, int]] = Counter()
    for x in range(width):
        colors[pixel(x, 0)] += 1
        colors[pixel(x, height - 1)] += 1
    for y in range(height):
        colors[pixel(0, y)] += 1
        colors[pixel(width - 1, y)] += 1

    if not colors:
        return (1, 1, 1)

    r, g, b = colors.most_common(1)[0][0]
    return (r / 255.0, g / 255.0, b / 255.0)


def _luminance(color: tuple[float, float, float]) -> float:
    r, g, b = color
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _int_to_rgb(color_value: int) -> tuple[float, float, float]:
    red = (int(color_value) >> 16) & 255
    green = (int(color_value) >> 8) & 255
    blue = int(color_value) & 255
    return (red / 255.0, green / 255.0, blue / 255.0)


def _map_source_font_to_overlay_font(font_name: str | None) -> str:
    if not font_name:
        return "helv"

    normalized = font_name.lower()
    if "bold" in normalized:
        if "times" in normalized:
            return "tibo"
        if "courier" in normalized:
            return "cobo"
        return "hebo"
    if "italic" in normalized or "oblique" in normalized:
        if "times" in normalized:
            return "tiro"
        if "courier" in normalized:
            return "coit"
        return "heit"
    if "times" in normalized:
        return "tiro"
    if "courier" in normalized:
        return "cour"
    return "helv"


def _overlay_style_for_replacement(
    page: fitz.Page,
    replacement: dict[str, Any],
) -> dict[str, Any]:
    role = replacement.get("role", "content")
    bbox = replacement["bbox"]
    rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
    source_color = replacement.get("source_color")
    source_color_mode = replacement.get("source_color_mode", "unknown")

    if role == "slide_title":
        fill_color = _estimate_fill_color(page, rect)
        if source_color is not None:
            text_color = _int_to_rgb(source_color)
        else:
            text_color = (1, 1, 1) if _luminance(fill_color) < 0.72 else (0, 0, 0)
        return {
            "fill_color": fill_color,
            "text_color": text_color,
            "fontname": "hebo",
            "align": 1,
            "max_fontsize": 20,
            "min_fontsize": 12,
        }

    if source_color is not None and source_color_mode == "uniform":
        text_color = _int_to_rgb(source_color)
    else:
        text_color = (0, 0, 0)

    return {
        "fill_color": (1, 1, 1),
        "text_color": text_color,
        "fontname": "helv",
        "align": 0,
        "max_fontsize": 12,
        "min_fontsize": 6,
    }


def render_overlay_prototype(
    pdf_path: Path,
    replacement_plan: dict[str, Any],
    output_dir: Path,
    stem: str,
    allowed_fit_risks: tuple[str, ...] = ("low", "medium"),
    allowed_statuses: tuple[str, ...] = ("translated",),
) -> tuple[Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    source_doc = fitz.open(pdf_path)
    overlay_doc = fitz.open()

    summary_pages: list[dict[str, Any]] = []
    total_considered = 0
    total_applied = 0
    total_skipped_due_to_page_policy = 0
    page_apply_policy_summary: Counter[str] = Counter()

    for page_report in replacement_plan.get("pages", []):
        page_number = page_report["page_number"]
        overlay_doc.insert_pdf(source_doc, from_page=page_number - 1, to_page=page_number - 1)
        page = overlay_doc[-1]

        applied = 0
        considered = 0
        skipped_due_to_page_policy = 0
        page_apply_policy = page_report.get("page_apply_policy", "apply_overlay")
        page_apply_policy_summary[page_apply_policy] += 1

        for replacement in page_report.get("replacements", []):
            considered += 1
            total_considered += 1

            if str(page_apply_policy).startswith("skip_overlay_"):
                skipped_due_to_page_policy += 1
                total_skipped_due_to_page_policy += 1
                continue
            if replacement.get("status") not in allowed_statuses:
                continue
            if replacement.get("apply_strategy") in {"native_review_required", "native_skipped"}:
                continue
            if replacement.get("fit_risk") not in allowed_fit_risks:
                continue

            bbox = replacement["bbox"]
            rect = fitz.Rect(bbox["x0"], bbox["y0"], bbox["x1"], bbox["y1"])
            style = _overlay_style_for_replacement(page, replacement)
            page.draw_rect(rect, color=style["fill_color"], fill=style["fill_color"], width=0)
            if replacement.get("role") == "slide_title":
                _draw_centered_single_line_text(
                    page,
                    rect,
                    replacement["translated_text"],
                    fontname=style["fontname"],
                    color=style["text_color"],
                    max_fontsize=style["max_fontsize"],
                    min_fontsize=style["min_fontsize"],
                )
            elif replacement.get("translated_lines"):
                _draw_text_lines(
                    page,
                    replacement["translated_lines"],
                    fontname=style["fontname"],
                    default_color=style["text_color"],
                    max_fontsize=style["max_fontsize"],
                    min_fontsize=style["min_fontsize"],
                    fill_color=style["fill_color"],
                    fit_risk=replacement.get("fit_risk", "low"),
                )
            else:
                _fit_text_in_rect(
                    page,
                    rect,
                    replacement["translated_text"],
                    fontname=style["fontname"],
                    color=style["text_color"],
                    align=style["align"],
                    max_fontsize=style["max_fontsize"],
                    min_fontsize=style["min_fontsize"],
                    fill_color=style["fill_color"],
                )
            applied += 1
            total_applied += 1

        summary_pages.append(
            {
                "page_number": page_number,
                "page_apply_policy": page_apply_policy,
                "considered_replacements": considered,
                "applied_replacements": applied,
                "skipped_replacements_due_to_page_policy": skipped_due_to_page_policy,
            }
        )

    pdf_output_path = output_dir / f"{stem}.pdf"
    overlay_doc.save(pdf_output_path)
    overlay_doc.close()
    source_doc.close()

    summary = {
        "selected_pages": replacement_plan.get("selected_pages", []),
        "page_count": len(summary_pages),
        "total_considered_replacements": total_considered,
        "total_applied_replacements": total_applied,
        "total_skipped_replacements_due_to_page_policy": total_skipped_due_to_page_policy,
        "page_apply_policy_summary": dict(page_apply_policy_summary),
        "pages": summary_pages,
        "allowed_fit_risks": list(allowed_fit_risks),
        "allowed_statuses": list(allowed_statuses),
    }

    return pdf_output_path, summary


def overlay_prototype_summary_to_text(summary: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {summary['selected_pages']}",
        f"Page count: {summary['page_count']}",
        f"Allowed statuses: {summary['allowed_statuses']}",
        f"Allowed fit risks: {summary['allowed_fit_risks']}",
        f"Total considered replacements: {summary['total_considered_replacements']}",
        f"Total applied replacements: {summary['total_applied_replacements']}",
        f"Total skipped by page policy: {summary.get('total_skipped_replacements_due_to_page_policy', 0)}",
    ]
    if summary.get("page_apply_policy_summary"):
        lines.append(
            f"Page apply policies: {json.dumps(summary.get('page_apply_policy_summary', {}), ensure_ascii=False, sort_keys=True)}"
        )

    for page in summary.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: policy={page.get('page_apply_policy', 'apply_overlay')} "
            f"applied={page['applied_replacements']} / considered={page['considered_replacements']} "
            f"skipped_by_policy={page.get('skipped_replacements_due_to_page_policy', 0)}"
        )

    return "\n".join(lines)


def write_overlay_prototype_summary(
    summary: dict[str, Any],
    output_dir: Path,
    stem: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    text_path = output_dir / f"{stem}.txt"
    text_path.write_text(overlay_prototype_summary_to_text(summary), encoding="utf-8")
    return text_path
