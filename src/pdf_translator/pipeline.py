from __future__ import annotations

import json
from pathlib import Path

import requests

from pdf_translator.config import settings
from pdf_translator.extract.pymupdf_extract import extract_document
from pdf_translator.logging_utils import get_logger
from pdf_translator.qa.checks import annotate_repeated_blocks, collect_role_summary
from pdf_translator.translate.batching import (
    apply_batch_translations,
    build_batch_prompt,
    collect_translation_groups,
    make_translation_batches,
    parse_batch_response,
    validate_batch_output,
)
from pdf_translator.translate.placeholders import (
    is_translation_candidate,
    placeholders_are_preserved,
    protect_text,
    restore_text,
)
from pdf_translator.translate.translator import translate_batch, translate_text


logger = get_logger(__name__)


def _preserve_batch_text(batch: list[dict[str, str]]) -> dict[str, str]:
    return {
        line["segment_id"]: line["protected_text"]
        for group in batch
        for line in group["lines"]
    }


def run_extract_only(pdf_path: str | Path) -> Path:
    settings.debug_dir.mkdir(parents=True, exist_ok=True)

    document = extract_document(pdf_path)
    document_ir = document.model_dump()
    document_ir = annotate_repeated_blocks(document_ir)

    role_summary = collect_role_summary(document_ir)
    logger.info("Block role summary: %s", role_summary)

    for page in document_ir["pages"]:
        for block in page["text_blocks"]:
            block_role = block.get("role", "content")
            if block_role != "content":
                block["translate"] = False
                for line in block["lines"]:
                    line["protected_text"] = line["text"]
                    line["placeholders"] = []
                    line["translation_candidate"] = False
                    line["translated_text"] = line["text"]
                    line["restored_text"] = line["text"]
                continue

            for line in block["lines"]:
                protected_text, placeholders = protect_text(line["text"])
                line["protected_text"] = protected_text
                line["placeholders"] = [item.model_dump() for item in placeholders]
                line["translation_candidate"] = is_translation_candidate(line["text"])

                if line["translation_candidate"]:
                    line["translated_text"] = ""
                    line["restored_text"] = ""
                else:
                    line["translated_text"] = line["text"]
                    line["restored_text"] = line["text"]

    groups = collect_translation_groups(
        document_ir,
        max_group_lines=settings.context_group_max_lines,
        max_group_chars=settings.context_group_max_chars,
    )
    batches = make_translation_batches(
        groups,
        max_segments=settings.batch_max_segments,
        max_chars=settings.batch_max_chars,
    )
    translations_by_segment_id: dict[str, str] = {}

    logger.info(
        "Prepared %s contextual groups across %s batch(es) for %s",
        len(groups),
        len(batches),
        pdf_path,
    )

    for batch_index, batch in enumerate(batches, start=1):
        batch_chars = sum(
            len(
                "\n".join(
                    f"[{line['segment_id']}] {line['protected_text']}"
                    for line in group["lines"]
                )
            )
            for group in batch
        )
        batch_line_count = sum(len(group["lines"]) for group in batch)
        logger.info(
            "Running batch %s/%s with %s group(s), %s line(s) and %s chars",
            batch_index,
            len(batches),
            len(batch),
            batch_line_count,
            batch_chars,
        )
        try:
            prompt = build_batch_prompt(batch)
            raw_response = translate_batch(prompt)
            batch_translations = parse_batch_response(raw_response)
            validate_batch_output(batch, batch_translations)
            for group in batch:
                for line in group["lines"]:
                    translated_text = batch_translations[line["segment_id"]]
                    if not placeholders_are_preserved(
                        translated_text,
                        line.get("placeholders", []),
                    ):
                        raise ValueError(
                            f"Placeholder preservation failed for segment {line['segment_id']}"
                        )
            logger.info("Batch %s succeeded", batch_index)
        except Exception as exc:
            logger.exception("Batch %s failed, falling back to per-line translation", batch_index)
            if isinstance(exc, requests.exceptions.Timeout):
                logger.warning(
                    "Batch %s hit backend timeout, preserving protected text for the whole batch",
                    batch_index,
                )
                batch_translations = _preserve_batch_text(batch)
                translations_by_segment_id.update(batch_translations)
                continue

            batch_translations = {}
            for group in batch:
                for line in group["lines"]:
                    try:
                        translated_text = translate_text(line["protected_text"])
                        if not placeholders_are_preserved(
                            translated_text,
                            line.get("placeholders", []),
                        ):
                            raise ValueError(
                                f"Placeholder preservation failed for segment {line['segment_id']}"
                            )
                    except Exception:
                        logger.exception(
                            "Per-line fallback failed for segment %s, preserving protected text",
                            line["segment_id"],
                        )
                        translated_text = line["protected_text"]
                    batch_translations[line["segment_id"]] = translated_text

        translations_by_segment_id.update(batch_translations)

    document_ir = apply_batch_translations(
        document_ir=document_ir,
        translations_by_segment_id=translations_by_segment_id,
        restore_text_fn=restore_text,
    )

    output_path = settings.debug_dir / "document_ir.json"
    output_path.write_text(
        json.dumps(document_ir, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Wrote document IR to %s", output_path)
    return output_path
