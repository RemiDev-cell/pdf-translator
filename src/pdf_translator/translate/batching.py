from __future__ import annotations

import re
from typing import Any


SEGMENT_LINE_RE = re.compile(r"^\[(?P<segment_id>P\d+B\d+L\d+)\]\s?(?P<text>.*)$")
IGNORED_RESPONSE_LINES = {
    "### Response:",
    "Response:",
    "Translation:",
    "Translated segments:",
    "Output:",
    "```",
    "</GROUP>",
}


def collect_translation_segments(document_ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten translatable lines from the document IR into segment records."""
    segments: list[dict[str, Any]] = []

    for page in document_ir.get("pages", []):
        page_number = page["page_number"]

        for block_index, block in enumerate(page.get("text_blocks", [])):
            for line_index, line in enumerate(block.get("lines", [])):
                if not line.get("translation_candidate", False):
                    continue

                segment_id = f"P{page_number}B{block_index}L{line_index}"
                segments.append(
                    {
                        "segment_id": segment_id,
                        "page_number": page_number,
                        "block_index": block_index,
                        "line_index": line_index,
                        "source_text": line.get("text", ""),
                        "protected_text": line.get("protected_text", ""),
                        "placeholders": line.get("placeholders", []),
                    }
                )

    return segments


def _is_list_like(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("- ") or bool(re.match(r"^\d+\.\s", stripped))


def _is_heading_like(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if len(stripped) > 60:
        return False
    if _is_list_like(stripped):
        return False
    return bool(re.match(r"^\d+\.\s+[A-Z]", stripped)) or stripped.istitle()


def _ends_sentence(text: str) -> bool:
    return text.strip().endswith((".", "?", "!", ":"))


def collect_translation_groups(
    document_ir: dict[str, Any],
    max_group_lines: int = 3,
    max_group_chars: int = 280,
) -> list[dict[str, Any]]:
    """Build small coherent multi-line groups while keeping per-line IDs for reinjection."""
    segments = collect_translation_segments(document_ir)
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}

    for segment in segments:
        key = (segment["page_number"], segment["block_index"])
        grouped.setdefault(key, []).append(segment)

    groups: list[dict[str, Any]] = []

    for (page_number, block_index), block_segments in grouped.items():
        current_lines: list[dict[str, Any]] = []
        current_chars = 0
        group_index = 0

        for segment in block_segments:
            line_text = segment["protected_text"].strip()
            line_chars = len(line_text)

            starts_new_group = False
            if current_lines:
                previous_text = current_lines[-1]["source_text"]
                if _is_heading_like(segment["source_text"]) or _is_list_like(segment["source_text"]):
                    starts_new_group = True
                elif _is_list_like(previous_text):
                    starts_new_group = True
                elif len(current_lines) >= max_group_lines:
                    starts_new_group = True
                elif current_chars + line_chars > max_group_chars:
                    starts_new_group = True

            if starts_new_group:
                groups.append(
                    {
                        "group_id": f"P{page_number}B{block_index}G{group_index}",
                        "page_number": page_number,
                        "block_index": block_index,
                        "lines": current_lines,
                    }
                )
                group_index += 1
                current_lines = []
                current_chars = 0

            current_lines.append(segment)
            current_chars += line_chars

            if _is_heading_like(segment["source_text"]) or _is_list_like(segment["source_text"]) or _ends_sentence(segment["source_text"]):
                groups.append(
                    {
                        "group_id": f"P{page_number}B{block_index}G{group_index}",
                        "page_number": page_number,
                        "block_index": block_index,
                        "lines": current_lines,
                    }
                )
                group_index += 1
                current_lines = []
                current_chars = 0

        if current_lines:
            groups.append(
                {
                    "group_id": f"P{page_number}B{block_index}G{group_index}",
                    "page_number": page_number,
                    "block_index": block_index,
                    "lines": current_lines,
                }
            )

    return groups


def make_translation_batches(
    groups: list[dict[str, Any]],
    max_segments: int = 8,
    max_chars: int = 2500,
) -> list[list[dict[str, Any]]]:
    """Group contextual translation groups into batches under size constraints."""
    batches: list[list[dict[str, Any]]] = []
    current_batch: list[dict[str, Any]] = []
    current_chars = 0

    for group in groups:
        group_text = "\n".join(
            f"[{line['segment_id']}] {line['protected_text']}"
            for line in group["lines"]
        )
        group_len = len(group_text)

        exceeds_segment_limit = len(current_batch) >= max_segments
        exceeds_char_limit = current_batch and (current_chars + group_len > max_chars)

        if exceeds_segment_limit or exceeds_char_limit:
            batches.append(current_batch)
            current_batch = []
            current_chars = 0

        current_batch.append(group)
        current_chars += group_len

    if current_batch:
        batches.append(current_batch)

    return batches


def build_batch_prompt(batch: list[dict[str, Any]]) -> str:
    """Build a strict translation prompt for contextual multi-line groups."""
    use_group_tags = any(len(group["lines"]) > 1 for group in batch)
    lines = [
        "Translate French to English.",
        "Return only the translated lines.",
        "No title.",
        "No explanation.",
        "No markdown.",
        "Keep each segment ID exactly.",
        "Valid output IDs look like [P1B0L0].",
        "Keep placeholders exactly, including [[VERSION_1]], [[ISO_DATE_1]], [[URL_1]], [[EMAIL_1]], [[COMMIT_1]].",
        "Do not merge lines.",
        "Do not split lines.",
        "Output format: [SEGMENT_ID] translated text",
    ]

    if use_group_tags:
        lines.append("Use neighboring lines inside each group as context.")
        lines.append("Never output group tags.")
        lines.append("Groups:")

        for group in batch:
            lines.append(f"<GROUP {group['group_id']}>")
            for line in group["lines"]:
                lines.append(f"[{line['segment_id']}] {line['protected_text']}")
            lines.append("</GROUP>")
    else:
        lines.append("Segments:")
        for group in batch:
            line = group["lines"][0]
            lines.append(f"[{line['segment_id']}] {line['protected_text']}")

    return "\n".join(lines)


def parse_batch_response(response_text: str) -> dict[str, str]:
    """Parse LLM batch output into a mapping {segment_id: translated_text}."""
    translations: dict[str, str] = {}

    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line in IGNORED_RESPONSE_LINES:
            continue
        if line.startswith("<GROUP "):
            continue

        match = SEGMENT_LINE_RE.match(line)
        if match is None:
            raise ValueError(f"Invalid batch response line: {raw_line!r}")

        segment_id = match.group("segment_id").strip()
        text = match.group("text").strip()
        translations[segment_id] = text

    return translations


def validate_batch_output(
    batch: list[dict[str, Any]],
    translations_by_segment_id: dict[str, str],
) -> None:
    """Ensure the batch output contains exactly the expected segment IDs."""
    expected_ids = [
        line["segment_id"]
        for group in batch
        for line in group["lines"]
    ]
    received_ids = list(translations_by_segment_id.keys())

    if set(expected_ids) != set(received_ids):
        raise ValueError(
            f"Batch output IDs mismatch. expected={expected_ids}, received={received_ids}"
        )


def apply_batch_translations(
    document_ir: dict[str, Any],
    translations_by_segment_id: dict[str, str],
    restore_text_fn,
) -> dict[str, Any]:
    """Write translated_text and restored_text back into the IR."""
    for page in document_ir.get("pages", []):
        page_number = page["page_number"]

        for block_index, block in enumerate(page.get("text_blocks", [])):
            for line_index, line in enumerate(block.get("lines", [])):
                segment_id = f"P{page_number}B{block_index}L{line_index}"

                if segment_id not in translations_by_segment_id:
                    continue

                translated_text = translations_by_segment_id[segment_id]
                placeholders = line.get("placeholders", [])

                line["translated_text"] = translated_text
                line["restored_text"] = restore_text_fn(translated_text, placeholders)

    return document_ir
