from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pdf_translator.translate.glossary import translate_scientific_label


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"\b(?:https?://|www\.|[A-Za-z0-9.-]+\.(?:fr|com|net|org)\b)")
PHONE_RE = re.compile(r"\b(?:\d[\s.]){3,}\d\b")
CUSTOMER_ID_RE = re.compile(
    r"\bn[°o]\s*(?:de\s*)?(?:client|compte(?:\s+internet)?|ligne(?:\s+livebox)?)\b"
    r"|\b(?:client|compte(?:\s+internet)?|ligne(?:\s+livebox)?)\s*:",
    re.IGNORECASE,
)
BILLING_METADATA_RE = re.compile(
    r"\b(?:"
    r"n[°o]\s*(?:de\s*)?facture"
    r"|facture\s*n[°o]?"
    r"|date de facture"
    r")",
    re.IGNORECASE,
)
CURRENCY_VALUE_RE = re.compile(r"^[+\-]?\d[\d\s,.]*(?:€|eur|%)?$", re.IGNORECASE)
SHORT_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
POSTAL_ADDRESS_RE = re.compile(r"\b\d{5}\s+[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ\s-]{2,}\b")
CAPTION_RE = re.compile(r"^(?:fig(?:ure)?\.?|tableau|table)\s*\d+\s*[:.-]", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"^\s*(?:[-•*]\s+|\d{1,2}[.)]\s+)")
QUANTITY_LIST_ITEM_RE = re.compile(
    r"^\s*\d+(?:[,.]\d+)?\s*(?:g|kg|mg|l|ml|cl|v|a|ma|ua|µa|k|%|[A-Za-zÀ-ÖØ-öø-ÿ]{2,})\b",
    re.IGNORECASE,
)
SECTION_STEP_RE = re.compile(r"^\s*(?:étape|etape|step|phase|partie|section)\s+\d+\b", re.IGNORECASE)


def _vertical_overlap_ratio(bbox_a: dict[str, Any], bbox_b: dict[str, Any]) -> float:
    a_y0 = float(bbox_a.get("y0", 0))
    a_y1 = float(bbox_a.get("y1", 0))
    b_y0 = float(bbox_b.get("y0", 0))
    b_y1 = float(bbox_b.get("y1", 0))
    overlap = max(0.0, min(a_y1, b_y1) - max(a_y0, b_y0))
    min_height = min(max(0.0, a_y1 - a_y0), max(0.0, b_y1 - b_y0))
    if min_height <= 0:
        return 0.0
    return overlap / min_height


def _merge_bboxes(blocks: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "x0": min(float(block.get("bbox", {}).get("x0", 0)) for block in blocks),
        "y0": min(float(block.get("bbox", {}).get("y0", 0)) for block in blocks),
        "x1": max(float(block.get("bbox", {}).get("x1", 0)) for block in blocks),
        "y1": max(float(block.get("bbox", {}).get("y1", 0)) for block in blocks),
    }


def _merge_text_blocks(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    merged_lines: list[dict[str, Any]] = []
    merged_text_parts: list[str] = []

    for block in blocks:
        text = block.get("text", "").strip()
        if text:
            if text == "-":
                merged_text_parts.append("-")
            elif merged_text_parts and merged_text_parts[-1] == "-":
                merged_text_parts.append(text)
            else:
                merged_text_parts.append(text)

        for line in block.get("lines", []):
            merged_lines.append(
                {
                    "text": line.get("text", ""),
                    "bbox": line.get("bbox", {}),
                    "spans": line.get("spans", []),
                }
            )

    merged_text = ""
    for part in merged_text_parts:
        if not merged_text:
            merged_text = part
        elif part == "-":
            merged_text = f"{merged_text} -"
        elif merged_text.endswith("-"):
            merged_text = f"{merged_text} {part}"
        else:
            merged_text = f"{merged_text} {part}"

    first_block = blocks[0]
    return {
        "block_index": first_block.get("block_index"),
        "role": "slide_title",
        "bbox": _merge_bboxes(blocks),
        "text": merged_text,
        "line_count": len(merged_lines),
        "lines": merged_lines,
    }


def _should_merge_into_slide_title(base_block: dict[str, Any], candidate_block: dict[str, Any]) -> bool:
    if candidate_block.get("role") not in {"header", "page_number", "diagram_token"}:
        return False

    text = candidate_block.get("text", "").strip()
    if text != "-" and not re.fullmatch(r"\d+", text):
        return False

    base_bbox = base_block.get("bbox", {})
    candidate_bbox = candidate_block.get("bbox", {})
    x_gap = float(candidate_bbox.get("x0", 0)) - float(base_bbox.get("x1", 0))
    return x_gap <= 16 and _vertical_overlap_ratio(base_bbox, candidate_bbox) >= 0.9


def normalize_block_text(text: str) -> str:
    normalized = text.strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\b\d+\b", "{N}", normalized)
    return normalized


def _block_font_sizes(block: dict[str, Any]) -> list[float]:
    return [
        float(span["size"])
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span.get("size") is not None
    ]


def _page_font_sizes(page: dict[str, Any]) -> list[float]:
    return [
        size
        for block in page.get("text_blocks", [])
        for size in _block_font_sizes(block)
    ]


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _block_is_bold(block: dict[str, Any]) -> bool:
    return any(
        int(span.get("flags") or 0) & 16
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    )


def _looks_like_list_item(text: str) -> bool:
    stripped = text.strip()
    if LIST_ITEM_RE.match(stripped):
        return True
    if len(stripped) <= 80 and QUANTITY_LIST_ITEM_RE.match(stripped) and re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", stripped):
        return True
    return False


def _bbox_metrics(bbox: dict[str, Any], page_width: float, page_height: float) -> dict[str, float]:
    x0 = float(bbox.get("x0", 0.0) or 0.0)
    y0 = float(bbox.get("y0", 0.0) or 0.0)
    x1 = float(bbox.get("x1", 0.0) or 0.0)
    y1 = float(bbox.get("y1", 0.0) or 0.0)
    width = max(0.0, x1 - x0)
    height = max(0.0, y1 - y0)
    page_area = max(1.0, page_width * page_height)

    return {
        "width": width,
        "height": height,
        "area_ratio": (width * height) / page_area,
        "x_center": x0 + (width / 2),
        "y_center": y0 + (height / 2),
    }


def classify_page_zone(
    bbox: dict[str, Any],
    page_width: float,
    page_height: float,
) -> dict[str, str]:
    metrics = _bbox_metrics(bbox, page_width, page_height)

    if page_height <= 0:
        vertical = "unknown_vertical_zone"
    elif metrics["y_center"] <= page_height * 0.15:
        vertical = "header_zone"
    elif metrics["y_center"] >= page_height * 0.85:
        vertical = "footer_zone"
    else:
        vertical = "body_zone"

    if page_width <= 0:
        horizontal = "unknown_horizontal_zone"
    elif metrics["x_center"] <= page_width * 0.20:
        horizontal = "left_margin"
    elif metrics["x_center"] >= page_width * 0.80:
        horizontal = "right_margin"
    else:
        horizontal = "center_band"

    return {
        "vertical": vertical,
        "horizontal": horizontal,
    }


def _page_zone_summary(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    vertical: Counter[str] = Counter()
    horizontal: Counter[str] = Counter()

    for item in items:
        page_zone = item.get("page_zone", {})
        vertical.update([page_zone.get("vertical", "unknown_vertical_zone")])
        horizontal.update([page_zone.get("horizontal", "unknown_horizontal_zone")])

    return {
        "vertical": dict(vertical),
        "horizontal": dict(horizontal),
    }


def _page_zone_field_summary(
    items: list[dict[str, Any]],
    field_name: str,
    fallback_value: str,
) -> dict[str, dict[str, dict[str, int]]]:
    vertical: dict[str, Counter[str]] = {}
    horizontal: dict[str, Counter[str]] = {}

    for item in items:
        page_zone = item.get("page_zone", {})
        value = str(item.get(field_name) or fallback_value)
        vertical_zone = str(page_zone.get("vertical") or "unknown_vertical_zone")
        horizontal_zone = str(page_zone.get("horizontal") or "unknown_horizontal_zone")
        vertical.setdefault(vertical_zone, Counter()).update([value])
        horizontal.setdefault(horizontal_zone, Counter()).update([value])

    return {
        "vertical": {
            zone: dict(counter)
            for zone, counter in vertical.items()
        },
        "horizontal": {
            zone: dict(counter)
            for zone, counter in horizontal.items()
        },
    }


def _merge_page_zone_field_summary(
    target: dict[str, dict[str, Counter[str]]],
    source: dict[str, dict[str, dict[str, int]]],
) -> None:
    for dimension in ("vertical", "horizontal"):
        for zone, counts in source.get(dimension, {}).items():
            target[dimension].setdefault(zone, Counter()).update(counts)


def _serializable_page_zone_field_summary(
    summary: dict[str, dict[str, Counter[str]]],
) -> dict[str, dict[str, dict[str, int]]]:
    return {
        dimension: {
            zone: dict(counter)
            for zone, counter in zones.items()
        }
        for dimension, zones in summary.items()
    }


def _candidate_page_zone_flags(item: dict[str, Any]) -> list[str]:
    page_zone = item.get("page_zone", {})
    vertical = page_zone.get("vertical")
    horizontal = page_zone.get("horizontal")
    role = item.get("role")
    vertical_review_roles = {"content", "list_item", "caption", "table_cell", "table_header", "diagram_label"}
    margin_review_roles = {"content", "caption", "diagram_label"}

    flags: list[str] = []
    if role in vertical_review_roles and vertical == "header_zone":
        flags.append("review_candidate_content_role_in_header_zone")
    if role in vertical_review_roles and vertical == "footer_zone":
        flags.append("review_candidate_content_role_in_footer_zone")
    if (
        role in margin_review_roles
        and horizontal in {"left_margin", "right_margin"}
        and item.get("layout_group", {}).get("group_type") != "ingredient_list_group"
    ):
        flags.append("review_candidate_content_role_in_margin")

    return flags


def _excluded_page_zone_flags(item: dict[str, Any]) -> list[str]:
    page_zone = item.get("page_zone", {})
    vertical = page_zone.get("vertical")
    exclusion_reason = item.get("exclusion_reason")
    structural_reasons = {
        "excluded_as_footer",
        "excluded_as_header",
        "excluded_as_legal_footer",
        "excluded_as_page_number",
    }

    if vertical == "body_zone" and exclusion_reason in structural_reasons:
        return ["review_structural_exclusion_in_body_zone"]

    return []


def _annotate_page_zone_flags(
    candidates: list[dict[str, Any]],
    excluded_blocks: list[dict[str, Any]],
) -> Counter[str]:
    summary: Counter[str] = Counter()

    for candidate in candidates:
        flags = _candidate_page_zone_flags(candidate)
        candidate["page_zone_flags"] = flags
        summary.update(flags)

    for excluded in excluded_blocks:
        flags = _excluded_page_zone_flags(excluded)
        excluded["page_zone_flags"] = flags
        summary.update(flags)

    return summary


def _page_zone_review_item(
    item: dict[str, Any],
    item_type: str,
    page_number: int | None,
) -> dict[str, Any] | None:
    flags = item.get("page_zone_flags", [])
    if not flags:
        return None

    review_item = {
        "page_number": page_number,
        "item_type": item_type,
        "block_index": item.get("block_index"),
        "role": item.get("role"),
        "page_zone": item.get("page_zone", {}),
        "page_zone_flags": flags,
        "line_count": item.get("line_count", 0),
        "text_preview": item.get("text", "").replace("\n", " | ").strip()[:120],
    }
    if item_type == "candidate":
        review_item["selection_reason"] = item.get("selection_reason", "selected_as_unknown")
        layout_group = item.get("layout_group", {})
        if layout_group.get("group_type") != "isolated_group":
            review_item["layout_group_id"] = layout_group.get("group_id")
            review_item["layout_group_type"] = layout_group.get("group_type")
    else:
        review_item["exclusion_reason"] = item.get("exclusion_reason", "excluded_as_unknown")

    return review_item


def _page_zone_review_items(
    candidates: list[dict[str, Any]],
    excluded_blocks: list[dict[str, Any]],
    page_number: int | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        review_item = _page_zone_review_item(candidate, "candidate", page_number)
        if review_item is not None:
            items.append(review_item)
    for excluded in excluded_blocks:
        review_item = _page_zone_review_item(excluded, "excluded", page_number)
        if review_item is not None:
            items.append(review_item)

    return items


def _horizontal_overlap_ratio(bbox_a: dict[str, Any], bbox_b: dict[str, Any]) -> float:
    a_x0 = float(bbox_a.get("x0", 0))
    a_x1 = float(bbox_a.get("x1", 0))
    b_x0 = float(bbox_b.get("x0", 0))
    b_x1 = float(bbox_b.get("x1", 0))
    overlap = max(0.0, min(a_x1, b_x1) - max(a_x0, b_x0))
    min_width = min(max(0.0, a_x1 - a_x0), max(0.0, b_x1 - b_x0))
    if min_width <= 0:
        return 0.0
    return overlap / min_width


def _vertical_gap(previous_bbox: dict[str, Any], current_bbox: dict[str, Any]) -> float:
    return max(0.0, float(current_bbox.get("y0", 0)) - float(previous_bbox.get("y1", 0)))


def _candidate_gap(previous: dict[str, Any] | None, current: dict[str, Any] | None) -> dict[str, Any] | None:
    if previous is None or current is None:
        return None

    previous_bbox = previous.get("bbox", {})
    current_bbox = current.get("bbox", {})
    x_overlap = _horizontal_overlap_ratio(previous_bbox, current_bbox)

    return {
        "vertical_gap": _vertical_gap(previous_bbox, current_bbox),
        "x_overlap": x_overlap,
        "same_column": x_overlap >= 0.5,
    }


def _reading_flow_classification(
    candidate: dict[str, Any],
    candidate_count: int,
    previous_gap: dict[str, Any] | None,
) -> str:
    role = candidate.get("role")
    if candidate_count == 1:
        return "isolated_block"
    if role in {"table_header", "table_cell"}:
        return "table_like_flow"
    if role in {"caption", "diagram_label"}:
        return "floating_label_or_caption"
    if previous_gap is not None and not previous_gap["same_column"]:
        return "multi_column_candidate"
    return "single_column_flow"


def _reading_flow_flags(
    candidate: dict[str, Any],
    previous: dict[str, Any] | None,
    previous_gap: dict[str, Any] | None,
    page_height: float,
) -> list[str]:
    if previous is None or previous_gap is None:
        return []

    flags: list[str] = []
    current_bbox = candidate.get("bbox", {})
    previous_bbox = previous.get("bbox", {})
    upward_delta = float(previous_bbox.get("y0", 0)) - float(current_bbox.get("y0", 0))
    if upward_delta > max(48.0, page_height * 0.10):
        flags.append("review_candidate_order_moves_up_page")
    if previous_gap["vertical_gap"] > max(96.0, page_height * 0.25):
        flags.append("review_large_vertical_gap_between_candidates")

    return flags


def _annotate_reading_flow(
    candidates: list[dict[str, Any]],
    page_height: float,
) -> tuple[Counter[str], Counter[str]]:
    classification_summary: Counter[str] = Counter()
    flag_summary: Counter[str] = Counter()

    for index, candidate in enumerate(candidates):
        previous = candidates[index - 1] if index > 0 else None
        next_candidate = candidates[index + 1] if index + 1 < len(candidates) else None
        previous_gap = _candidate_gap(previous, candidate)
        next_gap = _candidate_gap(candidate, next_candidate)
        classification = _reading_flow_classification(candidate, len(candidates), previous_gap)
        flags = _reading_flow_flags(candidate, previous, previous_gap, page_height)

        candidate["reading_flow"] = {
            "reading_order_index": index,
            "previous_candidate_gap": previous_gap,
            "next_candidate_gap": next_gap,
            "same_column_as_previous": None if previous_gap is None else previous_gap["same_column"],
            "x_overlap_with_previous": None if previous_gap is None else previous_gap["x_overlap"],
            "vertical_gap_to_previous": None if previous_gap is None else previous_gap["vertical_gap"],
            "classification": classification,
            "flags": flags,
        }
        classification_summary.update([classification])
        flag_summary.update(flags)

    return classification_summary, flag_summary


def _reading_flow_review_item(
    candidate: dict[str, Any],
    page_number: int | None,
) -> dict[str, Any] | None:
    reading_flow = candidate.get("reading_flow", {})
    flags = reading_flow.get("flags", [])
    if not flags:
        return None

    review_item = {
        "page_number": page_number,
        "block_index": candidate.get("block_index"),
        "role": candidate.get("role"),
        "selection_reason": candidate.get("selection_reason", "selected_as_unknown"),
        "reading_order_index": reading_flow.get("reading_order_index"),
        "classification": reading_flow.get("classification", "unknown_flow"),
        "flags": flags,
        "vertical_gap_to_previous": reading_flow.get("vertical_gap_to_previous"),
        "x_overlap_with_previous": reading_flow.get("x_overlap_with_previous"),
        "same_column_as_previous": reading_flow.get("same_column_as_previous"),
        "line_count": candidate.get("line_count", 0),
        "text_preview": candidate.get("text", "").replace("\n", " | ").strip()[:120],
    }
    layout_group = candidate.get("layout_group", {})
    if layout_group.get("group_type") != "isolated_group":
        review_item["layout_group_id"] = layout_group.get("group_id")
        review_item["layout_group_type"] = layout_group.get("group_type")

    return review_item


def _reading_flow_review_items(
    candidates: list[dict[str, Any]],
    page_number: int | None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        review_item = _reading_flow_review_item(candidate, page_number)
        if review_item is not None:
            items.append(review_item)

    return items


def _candidate_y0(candidate: dict[str, Any]) -> float:
    return float(candidate.get("bbox", {}).get("y0", 0.0) or 0.0)


def _candidate_x0(candidate: dict[str, Any]) -> float:
    return float(candidate.get("bbox", {}).get("x0", 0.0) or 0.0)


def _is_quantity_list_candidate(candidate: dict[str, Any]) -> bool:
    return candidate.get("role") == "list_item" and bool(QUANTITY_LIST_ITEM_RE.match(candidate.get("text", "").strip()))


def _is_numbered_instruction_candidate(candidate: dict[str, Any]) -> bool:
    return candidate.get("role") == "list_item" and bool(re.match(r"^\s*\d{1,2}[.)]\s+", candidate.get("text", "")))


def _same_column_candidate(anchor: dict[str, Any], candidate: dict[str, Any], page_width: float) -> bool:
    overlap = _horizontal_overlap_ratio(anchor.get("bbox", {}), candidate.get("bbox", {}))
    if overlap >= 0.25:
        return True
    anchor_x = _bbox_metrics(anchor.get("bbox", {}), page_width, 1.0)["x_center"]
    candidate_x = _bbox_metrics(candidate.get("bbox", {}), page_width, 1.0)["x_center"]
    return abs(anchor_x - candidate_x) <= max(48.0, page_width * 0.18)


def _group_bbox(candidates: list[dict[str, Any]]) -> dict[str, float]:
    return _merge_bboxes(candidates) if candidates else {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 0.0}


def _make_layout_group(
    group_index: int,
    group_type: str,
    members: list[dict[str, Any]],
    page_number: int | None,
) -> dict[str, Any]:
    group_id = f"P{page_number or 0}G{group_index}"
    ordered_members = sorted(members, key=lambda item: (_candidate_y0(item), _candidate_x0(item)))
    return {
        "group_id": group_id,
        "group_index": group_index,
        "group_type": group_type,
        "candidate_count": len(ordered_members),
        "block_indices": [item.get("block_index") for item in ordered_members],
        "roles": [item.get("role") for item in ordered_members],
        "bbox": _group_bbox(ordered_members),
        "text_preview": " | ".join(
            item.get("text", "").replace("\n", " | ").strip()
            for item in ordered_members[:3]
            if item.get("text", "").strip()
        )[:160],
    }


def _assign_layout_group_to_members(group: dict[str, Any], members: list[dict[str, Any]]) -> None:
    ordered_members = sorted(members, key=lambda item: (_candidate_y0(item), _candidate_x0(item)))
    for position, candidate in enumerate(ordered_members):
        candidate["layout_group"] = {
            "group_id": group["group_id"],
            "group_index": group["group_index"],
            "group_type": group["group_type"],
            "position_in_group": position,
            "candidate_count": group["candidate_count"],
        }


def _add_layout_group(
    groups: list[dict[str, Any]],
    assigned: set[int],
    group_type: str,
    member_indexes: list[int],
    candidates: list[dict[str, Any]],
    page_number: int | None,
) -> None:
    unique_indexes = sorted(set(member_indexes), key=lambda idx: (_candidate_y0(candidates[idx]), _candidate_x0(candidates[idx])))
    if not unique_indexes:
        return

    members = [candidates[index] for index in unique_indexes]
    group = _make_layout_group(len(groups), group_type, members, page_number)
    groups.append(group)
    _assign_layout_group_to_members(group, members)
    assigned.update(unique_indexes)


def _annotate_layout_groups(
    candidates: list[dict[str, Any]],
    page_number: int | None,
    page_width: float,
    page_height: float,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    groups: list[dict[str, Any]] = []
    assigned: set[int] = set()

    table_indexes = [
        index
        for index, candidate in enumerate(candidates)
        if candidate.get("role") in {"table_header", "table_cell"}
    ]
    _add_layout_group(groups, assigned, "table_group", table_indexes, candidates, page_number)

    for index, candidate in enumerate(candidates):
        if index in assigned or candidate.get("role") != "section_step":
            continue
        members = [index]
        for other_index, other in enumerate(candidates):
            if other_index in assigned or other_index == index:
                continue
            if other.get("role") not in {"short_label", "content"}:
                continue
            if _candidate_y0(other) < _candidate_y0(candidate):
                continue
            if _candidate_y0(other) > _candidate_y0(candidate) + max(180.0, page_height * 0.28):
                continue
            if _same_column_candidate(candidate, other, page_width):
                members.append(other_index)
        _add_layout_group(groups, assigned, "step_group", members, candidates, page_number)

    quantity_ingredient_indexes = [
        index
        for index, candidate in enumerate(candidates)
        if index not in assigned
        and _is_quantity_list_candidate(candidate)
    ]
    ingredient_indexes = list(quantity_ingredient_indexes)
    if quantity_ingredient_indexes:
        for index, candidate in enumerate(candidates):
            if index in assigned or index in ingredient_indexes:
                continue
            if candidate.get("role") != "short_label" or "ingr" not in candidate.get("text", "").casefold():
                continue
            if any(_same_column_candidate(candidates[anchor_index], candidate, page_width) for anchor_index in quantity_ingredient_indexes):
                ingredient_indexes.append(index)
    if ingredient_indexes:
        ingredient_y_values = [_candidate_y0(candidates[index]) for index in ingredient_indexes]
        min_ingredient_y = min(ingredient_y_values) - 80.0
        max_ingredient_y = max(ingredient_y_values) + 140.0
        for index, candidate in enumerate(candidates):
            if index in assigned or index in ingredient_indexes:
                continue
            if candidate.get("role") != "content" or int(candidate.get("line_count", 0) or 0) > 2:
                continue
            if not (min_ingredient_y <= _candidate_y0(candidate) <= max_ingredient_y):
                continue
            if any(_same_column_candidate(candidates[anchor_index], candidate, page_width) for anchor_index in quantity_ingredient_indexes):
                ingredient_indexes.append(index)
    _add_layout_group(groups, assigned, "ingredient_list_group", ingredient_indexes, candidates, page_number)

    instruction_anchors = [
        index
        for index, candidate in enumerate(candidates)
        if index not in assigned and _is_numbered_instruction_candidate(candidate)
    ]
    instruction_indexes = list(instruction_anchors)
    for anchor_index in instruction_anchors:
        anchor = candidates[anchor_index]
        for other_index, other in enumerate(candidates):
            if other_index in assigned or other_index in instruction_indexes:
                continue
            if other.get("role") != "content":
                continue
            if _candidate_y0(other) < _candidate_y0(anchor):
                continue
            if _candidate_y0(other) > _candidate_y0(anchor) + max(220.0, page_height * 0.35):
                continue
            if _same_column_candidate(anchor, other, page_width):
                instruction_indexes.append(other_index)
    _add_layout_group(groups, assigned, "instruction_group", instruction_indexes, candidates, page_number)

    for index, candidate in enumerate(candidates):
        if index in assigned or candidate.get("role") not in {"title", "slide_title"}:
            continue
        members = [index]
        for other_index, other in enumerate(candidates):
            if other_index in assigned or other_index == index:
                continue
            if other.get("role") not in {"content", "short_label"}:
                continue
            if other.get("page_zone", {}).get("vertical") != "header_zone":
                continue
            if abs(_candidate_y0(other) - _candidate_y0(candidate)) <= max(80.0, page_height * 0.08):
                members.append(other_index)
        _add_layout_group(groups, assigned, "heading_group", members, candidates, page_number)

    for index, candidate in enumerate(candidates):
        if index in assigned or candidate.get("role") not in {"caption", "diagram_label"}:
            continue
        _add_layout_group(groups, assigned, "caption_group", [index], candidates, page_number)

    for index, candidate in enumerate(candidates):
        if index in assigned:
            continue
        _add_layout_group(groups, assigned, "isolated_group", [index], candidates, page_number)

    return groups, Counter(group["group_type"] for group in groups)


def _layout_group_review_items(groups: list[dict[str, Any]], page_number: int | None) -> list[dict[str, Any]]:
    return [
        {
            "page_number": page_number,
            "group_id": group["group_id"],
            "group_type": group["group_type"],
            "candidate_count": group["candidate_count"],
            "block_indices": group["block_indices"],
            "roles": group["roles"],
            "text_preview": group["text_preview"],
        }
        for group in groups
        if group["group_type"] != "isolated_group"
    ]


def _overlay_readiness_reason_severity(reason: str) -> str:
    return {
        "blocked_no_overlay_candidates": "blocked",
        "review_candidate_content_role_in_footer_zone": "hard_review",
        "review_candidate_content_role_in_header_zone": "hard_review",
        "review_candidate_order_moves_up_page": "hard_review",
        "review_structural_exclusion_in_body_zone": "hard_review",
        "review_candidate_content_role_in_margin": "soft_review",
        "review_large_vertical_gap_between_candidates": "soft_review",
        "review_layout_group_ingredient_list_group": "soft_review",
        "review_layout_group_instruction_group": "soft_review",
        "review_layout_group_step_group": "soft_review",
        "review_layout_group_table_group": "soft_review",
    }.get(reason, "soft_review")


def _overlay_readiness_item_reason_severity(reason: str, item: dict[str, Any]) -> str:
    severity = _overlay_readiness_reason_severity(reason)
    if severity != "hard_review":
        return severity

    if reason not in {
        "review_candidate_content_role_in_footer_zone",
        "review_candidate_content_role_in_header_zone",
        "review_candidate_order_moves_up_page",
    }:
        return severity

    if item.get("layout_group_type") in {
        "heading_group",
        "ingredient_list_group",
        "instruction_group",
        "step_group",
        "table_group",
    }:
        return "soft_review"

    return severity


def _readiness_status_from_severity(severity_summary: Counter[str]) -> str:
    if severity_summary.get("blocked", 0) > 0:
        return "blocked"
    if severity_summary.get("hard_review", 0) > 0:
        return "hard_review"
    if severity_summary.get("soft_review", 0) > 0:
        return "soft_review"
    return "ready"


def _build_overlay_readiness(
    candidates: list[dict[str, Any]],
    excluded_blocks: list[dict[str, Any]],
    page_zone_review_items: list[dict[str, Any]],
    reading_flow_review_items: list[dict[str, Any]],
    layout_group_review_items: list[dict[str, Any]],
) -> dict[str, Any]:
    reason_summary: Counter[str] = Counter()
    severity_summary: Counter[str] = Counter()

    def add_reason(reason: str, item: dict[str, Any] | None = None) -> None:
        reason_summary[reason] += 1
        if item is None:
            severity = _overlay_readiness_reason_severity(reason)
        else:
            severity = _overlay_readiness_item_reason_severity(reason, item)
        severity_summary[severity] += 1

    if not candidates:
        add_reason("blocked_no_overlay_candidates")

    for item in page_zone_review_items:
        for reason in item.get("page_zone_flags", []):
            add_reason(reason, item)

    for item in reading_flow_review_items:
        for reason in item.get("flags", []):
            add_reason(reason, item)

    complex_layout_review_count = 0
    for item in layout_group_review_items:
        group_type = item.get("group_type", "unknown_group")
        if group_type in {"ingredient_list_group", "instruction_group", "step_group", "table_group"}:
            add_reason(f"review_layout_group_{group_type}")
            complex_layout_review_count += 1

    status = _readiness_status_from_severity(severity_summary)

    return {
        "status": status,
        "reason_summary": dict(reason_summary),
        "severity_summary": dict(severity_summary),
        "review_item_count": (
            len(page_zone_review_items)
            + len(reading_flow_review_items)
            + complex_layout_review_count
        ),
        "soft_review_item_count": severity_summary.get("soft_review", 0),
        "hard_review_item_count": severity_summary.get("hard_review", 0),
        "candidate_block_count": len(candidates),
        "excluded_block_count": len(excluded_blocks),
    }


def _font_size_summary(lines: list[dict[str, Any]]) -> dict[str, float | int | None]:
    sizes = [
        float(span["size"])
        for line in lines
        for span in line.get("spans", [])
        if span.get("size") is not None
    ]
    if not sizes:
        return {
            "min": None,
            "max": None,
            "median": None,
            "span_count": 0,
        }

    return {
        "min": min(sizes),
        "max": max(sizes),
        "median": _median(sizes),
        "span_count": len(sizes),
    }


def _overlay_geometry(
    bbox: dict[str, Any],
    lines: list[dict[str, Any]],
    page_width: float,
    page_height: float,
) -> dict[str, Any]:
    return {
        **_bbox_metrics(bbox, page_width, page_height),
        "font_size_summary": _font_size_summary(lines),
    }


def infer_block_role(
    block: dict[str, Any],
    normalized_text: str,
    repeat_count: int,
    page_height: float,
    page_median_font_size: float = 0.0,
    page_max_font_size: float = 0.0,
) -> str:
    text = block.get("text", "").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bbox = block.get("bbox", {})
    y0 = float(bbox.get("y0", 0))
    y1 = float(bbox.get("y1", 0))
    compact_text = text.replace("\n", "").replace(" ", "")
    lowercase_text = text.lower()
    block_font_sizes = _block_font_sizes(block)
    block_max_font_size = max(block_font_sizes, default=0.0)
    is_bold = _block_is_bold(block)

    if re.fullmatch(r"\d+", text) or re.fullmatch(r"page\s*:\s*\d+\s*/\s*\d+", lowercase_text):
        return "page_number"

    if CURRENCY_VALUE_RE.fullmatch(text) and any(char.isdigit() for char in text):
        return "numeric_value"

    if y1 > page_height * 0.92 and any(token in lowercase_text for token in ("rcs", "sa au capital", "siret")):
        return "legal_footer"

    if any(
        token in lowercase_text
        for token in (
            "nous contacter",
            "vos espaces clients",
            "service clients",
            "assistance technique",
            "contact.orange",
            "orange et moi",
            "orange.fr",
            "tarifs de vos communications",
            "tarifsetcontrats",
            "paiement facture",
        )
    ):
        return "support_metadata"

    if BILLING_METADATA_RE.search(lowercase_text):
        return "billing_metadata"

    if SHORT_DATE_RE.fullmatch(text):
        return "billing_metadata"

    if (
        "vos coordonnées" in lowercase_text
        or CUSTOMER_ID_RE.search(lowercase_text)
        or EMAIL_RE.search(text)
        or PHONE_RE.search(text)
        or POSTAL_ADDRESS_RE.search(text)
    ):
        return "sensitive_metadata"

    if URL_RE.search(text) and len(text) <= 120:
        return "support_metadata"

    if CAPTION_RE.search(text):
        return "caption"

    uppercase_words = re.findall(r"[A-ZÀ-ÖØ-Þ]{2,}", text)

    if len(compact_text) <= 3:
        if re.fullmatch(r"[A-ZΑ-Ωα-ω]+", compact_text):
            return "diagram_token"
        if re.fullmatch(r"[+\-=/|*]+", compact_text):
            return "diagram_token"
        if re.fullmatch(r"[+\-=/|*A-ZΑ-Ωα-ω]+", compact_text):
            return "diagram_token"

    if (
        y0 < page_height * 0.08
        and len(text) >= 24
        and len(uppercase_words) >= 3
    ):
        return "slide_title"

    if (
        y0 < page_height * 0.18
        and 5 <= repeat_count < 80
        and len(text) >= 20
        and len(uppercase_words) >= 3
    ):
        return "slide_title"

    if repeat_count >= 20:
        if y0 < page_height * 0.18:
            return "header"
        if y1 > page_height * 0.82:
            return "footer"

    if text in {"-", "–", "—"}:
        return "ornament"

    if SECTION_STEP_RE.match(text):
        return "section_step"

    if _looks_like_list_item(text):
        return "list_item"

    if (
        page_median_font_size > 0
        and (
            block_max_font_size >= page_median_font_size * 1.7
            or (
                y0 < page_height * 0.25
                and block_max_font_size >= page_median_font_size * 1.15
                and (page_max_font_size <= 0 or block_max_font_size >= page_max_font_size * 0.9)
            )
        )
        and len(text) >= 8
        and len(lines) <= 2
        and y0 < page_height * 0.45
        and "@" not in text
    ):
        return "title"

    if uppercase_words and len(text) <= 24:
        if len(uppercase_words) >= 1 and re.fullmatch(r"[A-ZÀ-ÖØ-Þ0-9\s|+\-_/]+", text):
            return "diagram_label"

    if "|" in text and len(text) <= 32:
        tokens = [token.strip() for token in text.split("|")]
        non_empty_tokens = [token for token in tokens if token]
        if non_empty_tokens and all(len(token) <= 6 for token in non_empty_tokens):
            return "diagram_label"

    if 2 <= len(lines) <= 4:
        if all(len(line) <= 6 for line in lines) and all(
            re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9+\-=/|*.]+", line) for line in lines
        ):
            return "diagram_label"

    if "\uf06e" in text:
        return "diagram_label"

    if (
        page_median_font_size > 0
        and len(lines) == 1
        and 3 <= len(text) <= 60
        and (is_bold or block_max_font_size >= page_median_font_size * 1.25)
        and not re.search(r"[.!?;:]$", text)
        and "@" not in text
    ):
        return "short_label"

    if repeat_count >= 20 and len(normalized_text) < 80:
        return "repeated_chrome"

    return "content"


def _looks_like_table_row(block: dict[str, Any]) -> bool:
    if block.get("role", "content") != "content":
        return False

    lines = [
        line
        for line in block.get("lines", [])
        if line.get("text", "").strip() and line.get("bbox")
    ]
    if len(lines) < 2:
        return False

    y_centers = [
        (float(line["bbox"].get("y0", 0)) + float(line["bbox"].get("y1", 0))) / 2
        for line in lines
    ]
    x_starts = [float(line["bbox"].get("x0", 0)) for line in lines]
    if max(y_centers) - min(y_centers) > 4.0:
        return False

    return len(set(round(x_start / 8) for x_start in x_starts)) >= 2


def _mark_table_runs(page: dict[str, Any]) -> None:
    blocks = page.get("text_blocks", [])
    run: list[dict[str, Any]] = []

    def flush_run() -> None:
        if len(run) < 2:
            run.clear()
            return
        run[0]["role"] = "table_header"
        for row_block in run[1:]:
            row_block["role"] = "table_cell"
        run.clear()

    for block in blocks:
        if _looks_like_table_row(block):
            run.append(block)
            continue
        flush_run()

    flush_run()


def annotate_repeated_blocks(document_ir: dict[str, Any]) -> dict[str, Any]:
    normalized_blocks: list[str] = []

    for page in document_ir.get("pages", []):
        for block in page.get("text_blocks", []):
            normalized_blocks.append(normalize_block_text(block.get("text", "")))

    counts = Counter(normalized_blocks)

    for page in document_ir.get("pages", []):
        page_height = float(page.get("height", 0))
        page_font_sizes = _page_font_sizes(page)
        page_median_font_size = _median(page_font_sizes)
        page_max_font_size = max(page_font_sizes, default=0.0)
        for block in page.get("text_blocks", []):
            normalized_text = normalize_block_text(block.get("text", ""))
            repeat_count = counts[normalized_text]
            block["repeat_count"] = repeat_count
            block["role"] = infer_block_role(
                block=block,
                normalized_text=normalized_text,
                repeat_count=repeat_count,
                page_height=page_height,
                page_median_font_size=page_median_font_size,
                page_max_font_size=page_max_font_size,
            )
        _mark_table_runs(page)

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


def _review_item_layout_group_text(review_item: dict[str, Any]) -> str:
    group_type = review_item.get("layout_group_type")
    if not group_type:
        return ""
    return f" group={group_type}:{review_item.get('layout_group_id')}"


def _overlay_selection_reason(role: str) -> str:
    return {
        "content": "selected_as_content",
        "slide_title": "selected_as_title",
        "title": "selected_as_title",
        "section_step": "selected_as_section_step",
        "short_label": "selected_as_short_label",
        "list_item": "selected_as_list_item",
        "caption": "selected_as_caption",
        "table_header": "selected_as_table_header",
        "table_cell": "selected_as_table_cell",
        "diagram_label": "selected_as_glossary_backed_diagram_label",
    }.get(role, "selected_as_translatable_role")


def _overlay_exclusion_reason(role: str) -> str:
    return {
        "billing_metadata": "excluded_as_billing_metadata",
        "diagram_label": "excluded_as_untranslated_diagram_label",
        "diagram_token": "excluded_as_diagram_token",
        "footer": "excluded_as_footer",
        "header": "excluded_as_header",
        "legal_footer": "excluded_as_legal_footer",
        "numeric_value": "excluded_as_numeric_value",
        "ornament": "excluded_as_ornament",
        "page_number": "excluded_as_page_number",
        "repeated_chrome": "excluded_as_repeated_chrome",
        "sensitive_metadata": "excluded_as_sensitive_metadata",
        "support_metadata": "excluded_as_support_metadata",
    }.get(role, "excluded_as_non_translatable_role")


def _overlay_lines(block: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "text": line.get("text", ""),
            "bbox": line.get("bbox", {}),
            "spans": line.get("spans", []),
        }
        for line in block.get("lines", [])
    ]


def _make_overlay_exclusion(
    block: dict[str, Any],
    page_width: float,
    page_height: float,
    reason: str | None = None,
) -> dict[str, Any]:
    lines = _overlay_lines(block)
    role = block.get("role", "content")
    return {
        "block_index": block.get("block_index"),
        "role": role,
        "bbox": block.get("bbox", {}),
        "text": block.get("text", ""),
        "line_count": len(lines),
        "geometry": _overlay_geometry(block.get("bbox", {}), lines, page_width, page_height),
        "page_zone": classify_page_zone(block.get("bbox", {}), page_width, page_height),
        "exclusion_reason": reason or _overlay_exclusion_reason(role),
    }


def build_overlay_ready_report(
    document_ir: dict[str, Any],
    selected_pages: list[int],
) -> dict[str, Any]:
    candidate_roles = {
        "content",
        "slide_title",
        "title",
        "section_step",
        "short_label",
        "list_item",
        "caption",
        "table_cell",
        "table_header",
        "diagram_label",
    }
    pages = [
        page
        for page in document_ir.get("pages", [])
        if page.get("page_number") in selected_pages
    ]

    page_reports: list[dict[str, Any]] = []
    overall_page_zone_review_items: list[dict[str, Any]] = []
    overall_reading_flow_review_items: list[dict[str, Any]] = []
    overall_layout_group_review_items: list[dict[str, Any]] = []
    total_candidate_blocks = 0
    total_candidate_lines = 0
    total_excluded_blocks = 0
    overall_selection_reasons: Counter[str] = Counter()
    overall_exclusion_reasons: Counter[str] = Counter()
    overall_page_zone_flags: Counter[str] = Counter()
    overall_reading_flow_classifications: Counter[str] = Counter()
    overall_reading_flow_flags: Counter[str] = Counter()
    overall_layout_groups: Counter[str] = Counter()
    overall_overlay_readiness_statuses: Counter[str] = Counter()
    overall_overlay_readiness_reasons: Counter[str] = Counter()
    overall_overlay_readiness_severities: Counter[str] = Counter()
    overall_candidate_vertical_zones: Counter[str] = Counter()
    overall_candidate_horizontal_zones: Counter[str] = Counter()
    overall_excluded_vertical_zones: Counter[str] = Counter()
    overall_excluded_horizontal_zones: Counter[str] = Counter()
    overall_candidate_page_zone_role_summary: dict[str, dict[str, Counter[str]]] = {
        "vertical": {},
        "horizontal": {},
    }
    overall_excluded_page_zone_reason_summary: dict[str, dict[str, Counter[str]]] = {
        "vertical": {},
        "horizontal": {},
    }

    for page in pages:
        candidates: list[dict[str, Any]] = []
        excluded_blocks: list[dict[str, Any]] = []
        blocks = page.get("text_blocks", [])
        page_width = float(page.get("width", 0.0) or 0.0)
        page_height = float(page.get("height", 0.0) or 0.0)
        index = 0

        while index < len(blocks):
            block = blocks[index]
            if block.get("role") not in candidate_roles:
                excluded_blocks.append(_make_overlay_exclusion(block, page_width, page_height))
                index += 1
                continue

            if block.get("role") == "diagram_label" and translate_scientific_label(block.get("text", "")) is None:
                excluded_blocks.append(
                    _make_overlay_exclusion(
                        block,
                        page_width,
                        page_height,
                        "excluded_as_untranslated_diagram_label",
                    )
                )
                index += 1
                continue

            if block.get("role") == "slide_title":
                title_blocks = [block]
                lookahead = index + 1
                while lookahead < len(blocks) and _should_merge_into_slide_title(block, blocks[lookahead]):
                    title_blocks.append(blocks[lookahead])
                    lookahead += 1
                candidate = _merge_text_blocks(title_blocks)
                candidate["selection_reason"] = _overlay_selection_reason("slide_title")
                candidate["merged_block_indices"] = [
                    item.get("block_index")
                    for item in title_blocks
                ]
                candidate["geometry"] = _overlay_geometry(
                    candidate.get("bbox", {}),
                    candidate.get("lines", []),
                    page_width,
                    page_height,
                )
                candidate["page_zone"] = classify_page_zone(
                    candidate.get("bbox", {}),
                    page_width,
                    page_height,
                )
                index = lookahead
            else:
                lines = _overlay_lines(block)

                candidate = {
                    "block_index": block.get("block_index"),
                    "role": block.get("role"),
                    "bbox": block.get("bbox", {}),
                    "text": block.get("text", ""),
                    "line_count": len(lines),
                    "lines": lines,
                    "geometry": _overlay_geometry(
                        block.get("bbox", {}),
                        lines,
                        page_width,
                        page_height,
                    ),
                    "page_zone": classify_page_zone(
                        block.get("bbox", {}),
                        page_width,
                        page_height,
                    ),
                    "selection_reason": _overlay_selection_reason(block.get("role", "content")),
                }
                index += 1

            candidates.append(candidate)

        reading_flow_summary, reading_flow_flag_summary = _annotate_reading_flow(candidates, page_height)
        layout_groups, layout_group_summary = _annotate_layout_groups(
            candidates,
            page.get("page_number"),
            page_width,
            page_height,
        )
        layout_group_review_items = _layout_group_review_items(layout_groups, page.get("page_number"))
        reading_flow_review_items = _reading_flow_review_items(
            candidates,
            page.get("page_number"),
        )
        page_zone_flag_summary = _annotate_page_zone_flags(candidates, excluded_blocks)
        page_zone_review_items = _page_zone_review_items(
            candidates,
            excluded_blocks,
            page.get("page_number"),
        )
        overlay_readiness = _build_overlay_readiness(
            candidates,
            excluded_blocks,
            page_zone_review_items,
            reading_flow_review_items,
            layout_group_review_items,
        )
        overall_layout_group_review_items.extend(layout_group_review_items)
        overall_reading_flow_review_items.extend(reading_flow_review_items)
        overall_page_zone_review_items.extend(page_zone_review_items)
        total_candidate_blocks += len(candidates)
        total_candidate_lines += sum(item["line_count"] for item in candidates)
        total_excluded_blocks += len(excluded_blocks)
        selection_reason_summary = Counter(
            item.get("selection_reason", "selected_as_unknown")
            for item in candidates
        )
        exclusion_reason_summary = Counter(
            item.get("exclusion_reason", "excluded_as_unknown")
            for item in excluded_blocks
        )
        candidate_page_zone_summary = _page_zone_summary(candidates)
        excluded_page_zone_summary = _page_zone_summary(excluded_blocks)
        candidate_page_zone_role_summary = _page_zone_field_summary(candidates, "role", "unknown_role")
        excluded_page_zone_reason_summary = _page_zone_field_summary(
            excluded_blocks,
            "exclusion_reason",
            "excluded_as_unknown",
        )
        overall_selection_reasons.update(selection_reason_summary)
        overall_exclusion_reasons.update(exclusion_reason_summary)
        overall_candidate_vertical_zones.update(candidate_page_zone_summary["vertical"])
        overall_candidate_horizontal_zones.update(candidate_page_zone_summary["horizontal"])
        overall_excluded_vertical_zones.update(excluded_page_zone_summary["vertical"])
        overall_excluded_horizontal_zones.update(excluded_page_zone_summary["horizontal"])
        overall_page_zone_flags.update(page_zone_flag_summary)
        overall_reading_flow_classifications.update(reading_flow_summary)
        overall_reading_flow_flags.update(reading_flow_flag_summary)
        overall_layout_groups.update(layout_group_summary)
        overall_overlay_readiness_statuses.update([overlay_readiness["status"]])
        overall_overlay_readiness_reasons.update(overlay_readiness["reason_summary"])
        overall_overlay_readiness_severities.update(overlay_readiness["severity_summary"])
        _merge_page_zone_field_summary(
            overall_candidate_page_zone_role_summary,
            candidate_page_zone_role_summary,
        )
        _merge_page_zone_field_summary(
            overall_excluded_page_zone_reason_summary,
            excluded_page_zone_reason_summary,
        )

        page_reports.append(
            {
                "page_number": page.get("page_number"),
                "candidate_block_count": len(candidates),
                "candidate_line_count": sum(item["line_count"] for item in candidates),
                "excluded_block_count": len(excluded_blocks),
                "selection_reason_summary": dict(selection_reason_summary),
                "exclusion_reason_summary": dict(exclusion_reason_summary),
                "reading_flow_summary": dict(reading_flow_summary),
                "reading_flow_flag_summary": dict(reading_flow_flag_summary),
                "reading_flow_review_item_count": len(reading_flow_review_items),
                "reading_flow_review_items": reading_flow_review_items,
                "layout_group_summary": dict(layout_group_summary),
                "layout_group_count": len(layout_groups),
                "layout_groups": layout_groups,
                "layout_group_review_item_count": len(layout_group_review_items),
                "layout_group_review_items": layout_group_review_items,
                "overlay_readiness": overlay_readiness,
                "page_zone_flag_summary": dict(page_zone_flag_summary),
                "page_zone_review_item_count": len(page_zone_review_items),
                "page_zone_review_items": page_zone_review_items,
                "candidate_page_zone_summary": candidate_page_zone_summary,
                "excluded_page_zone_summary": excluded_page_zone_summary,
                "candidate_page_zone_role_summary": candidate_page_zone_role_summary,
                "excluded_page_zone_reason_summary": excluded_page_zone_reason_summary,
                "candidates": candidates,
                "excluded_blocks": excluded_blocks,
            }
        )

    return {
        "selected_pages": selected_pages,
        "page_count": len(page_reports),
        "total_candidate_blocks": total_candidate_blocks,
        "total_candidate_lines": total_candidate_lines,
        "total_excluded_blocks": total_excluded_blocks,
        "total_page_zone_review_items": len(overall_page_zone_review_items),
        "total_reading_flow_review_items": len(overall_reading_flow_review_items),
        "total_layout_group_review_items": len(overall_layout_group_review_items),
        "selection_reason_summary": dict(overall_selection_reasons),
        "exclusion_reason_summary": dict(overall_exclusion_reasons),
        "reading_flow_summary": dict(overall_reading_flow_classifications),
        "reading_flow_flag_summary": dict(overall_reading_flow_flags),
        "reading_flow_review_items": overall_reading_flow_review_items,
        "layout_group_summary": dict(overall_layout_groups),
        "layout_group_review_items": overall_layout_group_review_items,
        "overlay_readiness_summary": dict(overall_overlay_readiness_statuses),
        "overlay_readiness_reason_summary": dict(overall_overlay_readiness_reasons),
        "overlay_readiness_severity_summary": dict(overall_overlay_readiness_severities),
        "page_zone_flag_summary": dict(overall_page_zone_flags),
        "page_zone_review_items": overall_page_zone_review_items,
        "candidate_page_zone_summary": {
            "vertical": dict(overall_candidate_vertical_zones),
            "horizontal": dict(overall_candidate_horizontal_zones),
        },
        "excluded_page_zone_summary": {
            "vertical": dict(overall_excluded_vertical_zones),
            "horizontal": dict(overall_excluded_horizontal_zones),
        },
        "candidate_page_zone_role_summary": _serializable_page_zone_field_summary(
            overall_candidate_page_zone_role_summary
        ),
        "excluded_page_zone_reason_summary": _serializable_page_zone_field_summary(
            overall_excluded_page_zone_reason_summary
        ),
        "pages": page_reports,
    }


def overlay_ready_report_to_text(report: dict[str, Any]) -> str:
    lines = [
        f"Selected pages: {report['selected_pages']}",
        f"Overlay-ready pages: {report['page_count']}",
        f"Total candidate blocks: {report['total_candidate_blocks']}",
        f"Total candidate lines: {report['total_candidate_lines']}",
        f"Total excluded blocks: {report.get('total_excluded_blocks', 0)}",
        f"Total page zone review items: {report.get('total_page_zone_review_items', 0)}",
        f"Total reading flow review items: {report.get('total_reading_flow_review_items', 0)}",
        f"Total layout group review items: {report.get('total_layout_group_review_items', 0)}",
    ]
    if report.get("selection_reason_summary"):
        lines.append(
            f"Selection reasons: {json.dumps(report['selection_reason_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("exclusion_reason_summary"):
        lines.append(
            f"Exclusion reasons: {json.dumps(report['exclusion_reason_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("reading_flow_summary"):
        lines.append(
            f"Reading flow: {json.dumps(report['reading_flow_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("reading_flow_flag_summary"):
        lines.append(
            f"Reading flow flags: {json.dumps(report['reading_flow_flag_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("layout_group_summary"):
        lines.append(
            f"Layout groups: {json.dumps(report['layout_group_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("overlay_readiness_summary"):
        lines.append(
            f"Overlay readiness: {json.dumps(report['overlay_readiness_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("overlay_readiness_severity_summary"):
        lines.append(
            f"Overlay readiness severities: {json.dumps(report['overlay_readiness_severity_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("overlay_readiness_reason_summary"):
        lines.append(
            f"Overlay readiness reasons: {json.dumps(report['overlay_readiness_reason_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("page_zone_flag_summary"):
        lines.append(
            f"Page zone flags: {json.dumps(report['page_zone_flag_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("candidate_page_zone_summary"):
        lines.append(
            f"Candidate page zones: {json.dumps(report['candidate_page_zone_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("excluded_page_zone_summary"):
        lines.append(
            f"Excluded page zones: {json.dumps(report['excluded_page_zone_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("candidate_page_zone_role_summary"):
        lines.append(
            f"Candidate zone roles: {json.dumps(report['candidate_page_zone_role_summary'], ensure_ascii=False, sort_keys=True)}"
        )
    if report.get("excluded_page_zone_reason_summary"):
        lines.append(
            f"Excluded zone reasons: {json.dumps(report['excluded_page_zone_reason_summary'], ensure_ascii=False, sort_keys=True)}"
        )

    for page in report.get("pages", []):
        lines.append(
            f"Page {page['page_number']}: candidate_blocks={page['candidate_block_count']} "
            f"candidate_lines={page['candidate_line_count']} "
            f"excluded_blocks={page.get('excluded_block_count', 0)} "
            f"page_zone_review_items={page.get('page_zone_review_item_count', 0)} "
            f"reading_flow_review_items={page.get('reading_flow_review_item_count', 0)} "
            f"layout_groups={page.get('layout_group_count', 0)} "
            f"readiness={page.get('overlay_readiness', {}).get('status', 'unknown')}"
        )
        if page.get("overlay_readiness", {}).get("reason_summary"):
            lines.append(
                f"  readiness reasons: {json.dumps(page['overlay_readiness']['reason_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("overlay_readiness", {}).get("severity_summary"):
            lines.append(
                f"  readiness severities: {json.dumps(page['overlay_readiness']['severity_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("candidate_page_zone_summary"):
            lines.append(
                f"  candidate zones: {json.dumps(page['candidate_page_zone_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("excluded_page_zone_summary"):
            lines.append(
                f"  excluded zones: {json.dumps(page['excluded_page_zone_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("page_zone_flag_summary"):
            lines.append(
                f"  page zone flags: {json.dumps(page['page_zone_flag_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("reading_flow_summary"):
            lines.append(
                f"  reading flow: {json.dumps(page['reading_flow_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("reading_flow_flag_summary"):
            lines.append(
                f"  reading flow flags: {json.dumps(page['reading_flow_flag_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("layout_group_summary"):
            lines.append(
                f"  layout groups: {json.dumps(page['layout_group_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        for review_item in page.get("layout_group_review_items", [])[:5]:
            preview = review_item.get("text_preview", "")
            lines.append(
                f"  layout group {review_item.get('group_id')} [{review_item.get('group_type')}]: "
                f"blocks={review_item.get('block_indices', [])} text={preview}"
            )
        for review_item in page.get("reading_flow_review_items", [])[:5]:
            preview = review_item.get("text_preview", "")
            flags = ",".join(review_item.get("flags", [])) or "none"
            lines.append(
                f"  reading review block {review_item.get('block_index')}: "
                f"flow={review_item.get('classification', 'unknown_flow')} "
                f"flags={flags}{_review_item_layout_group_text(review_item)} text={preview}"
            )
        if page.get("candidate_page_zone_role_summary"):
            lines.append(
                f"  candidate zone roles: {json.dumps(page['candidate_page_zone_role_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        if page.get("excluded_page_zone_reason_summary"):
            lines.append(
                f"  excluded zone reasons: {json.dumps(page['excluded_page_zone_reason_summary'], ensure_ascii=False, sort_keys=True)}"
            )
        for review_item in page.get("page_zone_review_items", [])[:5]:
            preview = review_item.get("text_preview", "")
            flags = ",".join(review_item.get("page_zone_flags", [])) or "none"
            lines.append(
                f"  review {review_item.get('item_type', 'item')} block {review_item.get('block_index')}: "
                f"flags={flags}{_review_item_layout_group_text(review_item)} text={preview}"
            )
        for candidate in page.get("candidates", [])[:3]:
            preview = candidate["text"].replace("\n", " | ").strip()[:180]
            reading_flow = candidate.get("reading_flow", {})
            layout_group = candidate.get("layout_group", {})
            lines.append(
                f"  block {candidate['block_index']} [{candidate.get('selection_reason', 'selected_as_unknown')}]: "
                f"lines={candidate['line_count']} "
                f"flow={reading_flow.get('classification', 'unknown_flow')} "
                f"group={layout_group.get('group_type', 'unknown_group')} text={preview}"
            )
        for excluded in page.get("excluded_blocks", [])[:3]:
            preview = excluded["text"].replace("\n", " | ").strip()[:180]
            lines.append(
                f"  excluded block {excluded['block_index']} [{excluded.get('exclusion_reason', 'excluded_as_unknown')}]: "
                f"lines={excluded.get('line_count', 0)} text={preview}"
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
