from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz
import requests


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


def build_translation_preview_segments(
    pre_overlay_report: dict[str, Any],
    selected_pages: list[int],
    max_lines_per_segment: int = 3,
    max_chars_per_segment: int = 320,
) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []

    for page in pre_overlay_report.get("pages", []):
        if page["page_number"] not in selected_pages:
            continue

        regions: list[dict[str, Any]] = []
        for region in page.get("regions", []):
            lines = region.get("lines", [])
            source_text = region.get("source_text", "")

            if _looks_symbolic(source_text):
                regions.append(
                    {
                        "source_text": source_text,
                        "bbox": region["bbox"],
                        "translate": False,
                    }
                )
                continue

            current_lines: list[str] = []
            current_chars = 0
            chunks: list[str] = []

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
                    chunks.append("\n".join(current_lines))
                    current_lines = []
                    current_chars = 0

                current_lines.append(line_text)
                current_chars += line_len

            if current_lines:
                chunks.append("\n".join(current_lines))

            if not chunks:
                chunks = [source_text]

            for chunk in chunks:
                regions.append(
                    {
                        "source_text": chunk,
                        "bbox": region["bbox"],
                        "translate": not _looks_symbolic(chunk),
                    }
                )

        page_reports.append({"page_number": page["page_number"], "regions": regions})

    return {"selected_pages": selected_pages, "pages": page_reports}


def build_translation_preview_report(
    segments_report: dict[str, Any],
    translate_text_fn,
) -> dict[str, Any]:
    page_reports: list[dict[str, Any]] = []

    for page in segments_report.get("pages", []):
        regions: list[dict[str, Any]] = []
        for region in page.get("regions", []):
            source_text = region["source_text"]

            if not region.get("translate", True):
                translated_text = source_text
                status = "skipped"
            else:
                try:
                    translated_text = translate_text_fn(source_text)
                    status = "translated"
                except requests.exceptions.Timeout:
                    translated_text = f"[TIMEOUT] {source_text.replace(chr(10), ' | ')}"
                    status = "timeout"

            regions.append(
                {
                    "source_text": source_text,
                    "translated_text": translated_text,
                    "bbox": region["bbox"],
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
