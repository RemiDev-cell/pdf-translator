from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def normalize_block_text(text: str) -> str:
    normalized = text.strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\b\d+\b", "{N}", normalized)
    return normalized


def infer_block_role(
    block: dict[str, Any],
    normalized_text: str,
    repeat_count: int,
    page_height: float,
) -> str:
    text = block.get("text", "").strip()
    bbox = block.get("bbox", {})
    y0 = float(bbox.get("y0", 0))
    y1 = float(bbox.get("y1", 0))

    if re.fullmatch(r"\d+", text):
        return "page_number"

    compact_text = text.replace("\n", "").replace(" ", "")
    if len(compact_text) <= 3:
        if re.fullmatch(r"[A-ZΑ-Ωα-ω]+", compact_text):
            return "diagram_token"
        if re.fullmatch(r"[+\-=/|*]+", compact_text):
            return "diagram_token"
        if re.fullmatch(r"[+\-=/|*A-ZΑ-Ωα-ω]+", compact_text):
            return "diagram_token"

    if repeat_count >= 20:
        if y0 < page_height * 0.18:
            return "header"
        if y1 > page_height * 0.82:
            return "footer"

    if text in {"-", "–", "—"}:
        return "ornament"

    uppercase_words = re.findall(r"[A-ZÀ-ÖØ-Þ]{2,}", text)
    if uppercase_words and len(text) <= 24:
        if len(uppercase_words) >= 1 and re.fullmatch(r"[A-ZÀ-ÖØ-Þ0-9\s|+\-_/]+", text):
            return "diagram_label"

    if "|" in text and len(text) <= 32:
        tokens = [token.strip() for token in text.split("|")]
        non_empty_tokens = [token for token in tokens if token]
        if non_empty_tokens and all(len(token) <= 6 for token in non_empty_tokens):
            return "diagram_label"

    if "\uf06e" in text:
        return "diagram_label"

    if repeat_count >= 20 and len(normalized_text) < 80:
        return "repeated_chrome"

    return "content"


def annotate_repeated_blocks(document_ir: dict[str, Any]) -> dict[str, Any]:
    normalized_blocks: list[str] = []

    for page in document_ir.get("pages", []):
        for block in page.get("text_blocks", []):
            normalized_blocks.append(normalize_block_text(block.get("text", "")))

    counts = Counter(normalized_blocks)

    for page in document_ir.get("pages", []):
        page_height = float(page.get("height", 0))
        for block in page.get("text_blocks", []):
            normalized_text = normalize_block_text(block.get("text", ""))
            repeat_count = counts[normalized_text]
            block["repeat_count"] = repeat_count
            block["role"] = infer_block_role(
                block=block,
                normalized_text=normalized_text,
                repeat_count=repeat_count,
                page_height=page_height,
            )

    return document_ir


def collect_role_summary(document_ir: dict[str, Any]) -> dict[str, int]:
    counter: Counter[str] = Counter()

    for page in document_ir.get("pages", []):
        for block in page.get("text_blocks", []):
            counter[block.get("role", "content")] += 1

    return dict(counter)


def build_page_audit(
    document_ir: dict[str, Any],
    selected_pages: list[int],
) -> dict[str, Any]:
    pages = [
        page
        for page in document_ir.get("pages", [])
        if page.get("page_number") in selected_pages
    ]

    page_reports: list[dict[str, Any]] = []
    overall_roles: Counter[str] = Counter()

    for page in pages:
        role_counts: Counter[str] = Counter()
        content_examples: list[str] = []
        excluded_examples: list[str] = []

        for block in page.get("text_blocks", []):
            role = block.get("role", "content")
            role_counts[role] += 1
            overall_roles[role] += 1

            text = block.get("text", "").replace("\n", " | ").strip()
            if not text:
                continue

            if role == "content" and len(content_examples) < 3:
                content_examples.append(text[:180])
            if role != "content" and len(excluded_examples) < 3:
                excluded_examples.append(f"{role}: {text[:180]}")

        page_reports.append(
            {
                "page_number": page["page_number"],
                "raw_chars": len(page.get("raw_text", "")),
                "image_count": page.get("image_count", 0),
                "block_count": page.get("block_count", 0),
                "role_counts": dict(role_counts),
                "content_examples": content_examples,
                "excluded_examples": excluded_examples,
            }
        )

    repeated_blocks: Counter[str] = Counter()
    repeated_block_examples: dict[str, str] = {}

    for page in document_ir.get("pages", []):
        for block in page.get("text_blocks", []):
            normalized_text = normalize_block_text(block.get("text", ""))
            repeat_count = block.get("repeat_count", 1)
            if repeat_count < 5 or not normalized_text:
                continue
            repeated_blocks[normalized_text] = max(repeated_blocks[normalized_text], repeat_count)
            repeated_block_examples.setdefault(
                normalized_text,
                block.get("text", "").replace("\n", " | ").strip()[:180],
            )

    top_repeated_blocks = [
        {
            "normalized_text": normalized_text,
            "repeat_count": repeat_count,
            "example": repeated_block_examples.get(normalized_text, ""),
        }
        for normalized_text, repeat_count in repeated_blocks.most_common(10)
    ]

    return {
        "selected_pages": selected_pages,
        "page_count": len(page_reports),
        "role_summary": dict(overall_roles),
        "top_repeated_blocks": top_repeated_blocks,
        "pages": page_reports,
    }


def audit_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report['selected_pages']}",
        f"Audited pages: {report['page_count']}",
        f"Role summary: {json.dumps(report['role_summary'], ensure_ascii=False, sort_keys=True)}",
    ]

    if report.get("top_repeated_blocks"):
        lines.append("Top repeated blocks:")
        for item in report["top_repeated_blocks"][:5]:
            lines.append(
                f"  repeat={item['repeat_count']}: {item['example']}"
            )

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: chars={page['raw_chars']} images={page['image_count']} "
            f"blocks={page['block_count']} roles={json.dumps(page['role_counts'], ensure_ascii=False, sort_keys=True)}"
        )
        if page["content_examples"]:
            lines.append(f"  content: {page['content_examples'][0]}")
        if page["excluded_examples"]:
            lines.append(f"  excluded: {page['excluded_examples'][0]}")

    return "\n".join(lines)


def write_audit_report(
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
        audit_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path


def build_overlay_ready_report(
    document_ir: dict[str, Any],
    selected_pages: list[int],
) -> dict[str, Any]:
    pages = [
        page
        for page in document_ir.get("pages", [])
        if page.get("page_number") in selected_pages
    ]

    page_reports: list[dict[str, Any]] = []
    total_candidate_blocks = 0
    total_candidate_lines = 0

    for page in pages:
        candidates: list[dict[str, Any]] = []

        for block in page.get("text_blocks", []):
            if block.get("role") != "content":
                continue

            lines = [
                {
                    "text": line.get("text", ""),
                    "bbox": line.get("bbox", {}),
                }
                for line in block.get("lines", [])
            ]

            candidates.append(
                {
                    "block_index": block.get("block_index"),
                    "bbox": block.get("bbox", {}),
                    "text": block.get("text", ""),
                    "line_count": len(lines),
                    "lines": lines,
                }
            )

        total_candidate_blocks += len(candidates)
        total_candidate_lines += sum(item["line_count"] for item in candidates)

        page_reports.append(
            {
                "page_number": page.get("page_number"),
                "candidate_block_count": len(candidates),
                "candidate_line_count": sum(item["line_count"] for item in candidates),
                "candidates": candidates,
            }
        )

    return {
        "selected_pages": selected_pages,
        "page_count": len(page_reports),
        "total_candidate_blocks": total_candidate_blocks,
        "total_candidate_lines": total_candidate_lines,
        "pages": page_reports,
    }


def overlay_ready_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report['selected_pages']}",
        f"Overlay-ready pages: {report['page_count']}",
        f"Total candidate blocks: {report['total_candidate_blocks']}",
        f"Total candidate lines: {report['total_candidate_lines']}",
    ]

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: candidate_blocks={page['candidate_block_count']} "
            f"candidate_lines={page['candidate_line_count']}"
        )
        for candidate in page.get("candidates", [])[:3]:
            preview = candidate["text"].replace("\n", " | ").strip()[:180]
            lines.append(
                f"  block {candidate['block_index']}: lines={candidate['line_count']} text={preview}"
            )

    return "\n".join(lines)


def write_overlay_ready_report(
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
        overlay_ready_report_to_text(report),
        encoding="utf-8",
    )

    return json_path, text_path
