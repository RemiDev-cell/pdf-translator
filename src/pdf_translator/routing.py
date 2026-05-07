from __future__ import annotations

import json
from collections import Counter
from typing import Any


PageRoute = str


def _classify_page_route(page: dict[str, Any]) -> tuple[PageRoute, list[str]]:
    image_count = int(page.get("image_count", 0) or 0)
    text_blocks = page.get("text_blocks", [])
    ocr_candidates = page.get("ocr_candidates", [])
    content_blocks = [block for block in text_blocks if block.get("role", "content") == "content"]

    has_images = image_count > 0
    has_ocr_candidates = bool(ocr_candidates)
    has_native_content = bool(content_blocks)
    has_native_non_content = bool(text_blocks) and not has_native_content

    reasons: list[str] = []
    if has_native_content:
        reasons.append("has_native_content_blocks")
    if has_images:
        reasons.append("contains_raster_images")
    if has_images and not has_ocr_candidates:
        reasons.append("no_ocr_sized_image_regions")
    if has_ocr_candidates:
        reasons.append("has_ocr_candidate_regions")
    if has_native_non_content:
        reasons.append("native_text_classified_as_non_content_only")

    if has_native_content and has_ocr_candidates:
        return "native_plus_ocr_candidates", reasons
    if has_native_content:
        return "native_only", reasons
    if has_ocr_candidates:
        return "ocr_only", reasons
    if has_images:
        return "image_only_no_ocr_candidates", reasons
    if has_native_non_content:
        return "native_non_content_only", reasons
    return "empty", reasons


def build_document_routing_report(
    document_ir: dict[str, Any],
    selected_pages: list[int] | None = None,
) -> dict[str, Any]:
    pages = document_ir.get("pages", [])
    if selected_pages is not None:
        selected = set(selected_pages)
        pages = [page for page in pages if page.get("page_number") in selected]

    page_reports: list[dict[str, Any]] = []
    route_counts: Counter[str] = Counter()

    for page in pages:
        text_blocks = page.get("text_blocks", [])
        ocr_candidates = page.get("ocr_candidates", [])
        ignored_ocr_images = page.get("ignored_ocr_images", [])
        content_blocks = [block for block in text_blocks if block.get("role", "content") == "content"]
        excluded_blocks = [block for block in text_blocks if block.get("role", "content") != "content"]
        excluded_role_summary = Counter(
            block.get("role", "unknown")
            for block in excluded_blocks
        )
        ignored_ocr_image_reason_summary = Counter(
            image.get("reason", "unknown")
            for image in ignored_ocr_images
        )
        image_count = int(page.get("image_count", 0) or 0)
        untracked_ignored_images = max(
            0,
            image_count - len(ocr_candidates) - len(ignored_ocr_images),
        )
        if untracked_ignored_images:
            ignored_ocr_image_reason_summary["image_not_reported_as_text_dict_block"] += untracked_ignored_images
        image_block_count = len(ocr_candidates) + len(ignored_ocr_images) + untracked_ignored_images
        native_text_chars = len(page.get("raw_text", ""))
        route, reasons = _classify_page_route(page)
        route_counts[route] += 1

        page_reports.append(
            {
                "page_number": page.get("page_number"),
                "route": route,
                "reasons": reasons,
                "native_text_chars": native_text_chars,
                "raw_chars": native_text_chars,
                "image_count": image_count,
                "image_block_count": image_block_count,
                "block_count": page.get("block_count", len(text_blocks)),
                "content_blocks": len(content_blocks),
                "content_block_count": len(content_blocks),
                "excluded_blocks": len(excluded_blocks),
                "non_content_block_count": len(text_blocks) - len(content_blocks),
                "excluded_role_summary": dict(excluded_role_summary),
                "ocr_candidate_count": len(ocr_candidates),
                "ignored_ocr_image_count": len(ignored_ocr_images) + untracked_ignored_images,
                "ignored_ocr_image_reason_summary": dict(ignored_ocr_image_reason_summary),
            }
        )

    return {
        "selected_pages": selected_pages,
        "page_count": len(page_reports),
        "pdf_kind": document_ir.get("pdf_kind", "unknown"),
        "route_summary": dict(route_counts),
        "pages": page_reports,
    }


def routing_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report.get('selected_pages') if report.get('selected_pages') is not None else 'all'}",
        f"Routed pages: {report['page_count']}",
        f"PDF kind: {report['pdf_kind']}",
        f"Route summary: {json.dumps(report['route_summary'], ensure_ascii=False, sort_keys=True)}",
    ]

    for page in report.get("pages", []):
        excluded_summary = page.get("excluded_role_summary", {})
        ignored_image_summary = page.get("ignored_ocr_image_reason_summary", {})
        lines.append(
            f"Page {page['page_number']}: route={page['route']} "
            f"native_text_chars={page.get('native_text_chars', page.get('raw_chars', 0))} "
            f"image_count={page['image_count']} image_block_count={page.get('image_block_count', page['image_count'])} "
            f"ocr_candidate_count={page.get('ocr_candidate_count', 0)} "
            f"ignored_ocr_image_count={page.get('ignored_ocr_image_count', 0)} "
            f"blocks={page['block_count']} content_blocks={page.get('content_blocks', page.get('content_block_count', 0))} "
            f"excluded_blocks={page.get('excluded_blocks', page.get('non_content_block_count', 0))}"
        )
        if ignored_image_summary:
            lines.append(
                f"  ignored_ocr_images: {json.dumps(ignored_image_summary, ensure_ascii=False, sort_keys=True)}"
            )
        if excluded_summary:
            lines.append(
                f"  excluded_roles: {json.dumps(excluded_summary, ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("reasons"):
            lines.append(f"  reasons: {', '.join(page['reasons'])}")

    return "\n".join(lines)



def build_ocr_candidate_report(
    document_ir: dict[str, Any],
    selected_pages: list[int] | None = None,
) -> dict[str, Any]:
    pages = document_ir.get("pages", [])
    if selected_pages is not None:
        selected = set(selected_pages)
        pages = [page for page in pages if page.get("page_number") in selected]

    page_reports: list[dict[str, Any]] = []
    total_candidates = 0

    for page in pages:
        candidates = page.get("ocr_candidates", [])
        total_candidates += len(candidates)
        page_reports.append(
            {
                "page_number": page.get("page_number"),
                "route": _classify_page_route(page)[0],
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
        )

    return {
        "selected_pages": selected_pages,
        "page_count": len(page_reports),
        "pdf_kind": document_ir.get("pdf_kind", "unknown"),
        "total_candidates": total_candidates,
        "pages": page_reports,
    }


def ocr_candidate_report_to_text(report: dict[str, Any]) -> str:
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
