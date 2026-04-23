from pdf_translator.translate.batching import (
    build_batch_prompt,
    collect_translation_groups,
    make_translation_batches,
    parse_batch_response,
    validate_batch_output,
)
from pdf_translator.translate.placeholders import (
    placeholders_are_preserved,
    protect_text,
)
from pdf_translator.translate.translator import clean_text_response


def test_make_translation_batches_respects_limits() -> None:
    groups = [
        {"group_id": "P1B0G0", "lines": [{"segment_id": "P1B0L0", "protected_text": "Bonjour"}]},
        {"group_id": "P1B0G1", "lines": [{"segment_id": "P1B0L1", "protected_text": "Salut"}]},
        {"group_id": "P1B0G2", "lines": [{"segment_id": "P1B0L2", "protected_text": "Bonsoir"}]},
    ]

    batches = make_translation_batches(groups, max_segments=2, max_chars=100)

    assert len(batches) == 2
    assert [group["group_id"] for group in batches[0]] == ["P1B0G0", "P1B0G1"]
    assert [group["group_id"] for group in batches[1]] == ["P1B0G2"]


def test_build_and_parse_batch_prompt_round_trip_shape() -> None:
    batch = [
        {
            "group_id": "P1B0G0",
            "lines": [
                {"segment_id": "P1B0L0", "protected_text": "Bonjour le monde"},
                {"segment_id": "P1B0L1", "protected_text": "Version: [[VERSION_1]]"},
            ],
        }
    ]

    prompt = build_batch_prompt(batch)

    assert "<GROUP P1B0G0>" in prompt
    assert "[P1B0L0] Bonjour le monde" in prompt
    assert "[P1B0L1] Version: [[VERSION_1]]" in prompt
    assert "</GROUP>" in prompt

    response = "[P1B0L0] Hello world\n[P1B0L1] Version: [[VERSION_1]]"
    parsed = parse_batch_response(response)

    assert parsed == {
        "P1B0L0": "Hello world",
        "P1B0L1": "Version: [[VERSION_1]]",
    }

    validate_batch_output(batch, parsed)


def test_parse_batch_response_rejects_unstructured_output() -> None:
    response = "Here are the translations:\n[P1B0L0] Hello world"

    try:
        parse_batch_response(response)
    except ValueError as exc:
        assert "Invalid batch response line" in str(exc)
    else:
        raise AssertionError("Expected parse_batch_response to reject unstructured output")


def test_parse_batch_response_ignores_known_preamble_lines() -> None:
    response = "### Response:\n[P1B0L0] Hello world"

    assert parse_batch_response(response) == {"P1B0L0": "Hello world"}


def test_parse_batch_response_ignores_group_tags() -> None:
    response = "<GROUP P1B0G0>\n[P1B0L0] Hello world\n</GROUP>"

    assert parse_batch_response(response) == {"P1B0L0": "Hello world"}


def test_collect_translation_groups_keeps_wrapped_sentence_together() -> None:
    document_ir = {
        "pages": [
            {
                "page_number": 1,
                "text_blocks": [
                    {
                        "lines": [
                            {
                                "text": "Cette phrase commence ici",
                                "protected_text": "Cette phrase commence ici",
                                "translation_candidate": True,
                                "placeholders": [],
                            },
                            {
                                "text": "et se termine ici.",
                                "protected_text": "et se termine ici.",
                                "translation_candidate": True,
                                "placeholders": [],
                            },
                            {
                                "text": "2. Resultats numeriques",
                                "protected_text": "2. Resultats numeriques",
                                "translation_candidate": True,
                                "placeholders": [],
                            },
                        ]
                    }
                ]
            }
        ]
    }

    groups = collect_translation_groups(document_ir, max_group_lines=3, max_group_chars=280)

    assert len(groups) == 2
    assert [line["segment_id"] for line in groups[0]["lines"]] == ["P1B0L0", "P1B0L1"]
    assert [line["segment_id"] for line in groups[1]["lines"]] == ["P1B0L2"]


def test_placeholders_are_preserved_rejects_invented_placeholders() -> None:
    assert not placeholders_are_preserved(
        "3. Implementation Notes\n\n[[VERSION_1]]",
        [],
    )


def test_version_protection_ignores_measurements_like_1_2_mm() -> None:
    protected, placeholders = protect_text("effective depasse 1.2 mm")

    assert protected == "effective depasse 1.2 mm"
    assert placeholders == []


def test_clean_text_response_removes_prompt_noise() -> None:
    response = (
        "Strict rules:\n"
        "- Return only the translated text.\n"
        "Text:\n"
        "### Response:\n"
        "Hello world"
    )

    assert clean_text_response(response) == "Hello world"
