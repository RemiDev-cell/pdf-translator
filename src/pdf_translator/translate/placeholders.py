from __future__ import annotations

import re
from typing import Any

from pdf_translator.models import PlaceholderMap


PLACEHOLDER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("url", re.compile(r"\bhttps?://[^\s]+")),
    ("commit", re.compile(r"\b[a-f0-9]{32,64}\b")),
    ("iso_date", re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\b")),
    # Require at least 3 numeric groups to avoid masking scientific measurements like 1.2 mm.
    ("version", re.compile(r"\b\d+(?:\.\d+){2,5}\b")),
]


def protect_text(text: str) -> tuple[str, list[PlaceholderMap]]:
    protected = text
    placeholders: list[PlaceholderMap] = []
    counter = 1

    for kind, pattern in PLACEHOLDER_PATTERNS:
        matches = list(pattern.finditer(protected))
        if not matches:
            continue

        for match in matches:
            original = match.group(0)

            already_present = any(item.value == original for item in placeholders)
            if already_present:
                continue

            key = f"[[{kind.upper()}_{counter}]]"
            protected = protected.replace(original, key, 1)
            placeholders.append(
                PlaceholderMap(
                    key=key,
                    value=original,
                    kind=kind,
                )
            )
            counter += 1

    return protected, placeholders


def restore_text(text: str, placeholders: list[PlaceholderMap] | list[dict[str, Any]]) -> str:
    restored = text
    for item in placeholders:
        if isinstance(item, dict):
            key = item["key"]
            value = item["value"]
        else:
            key = item.key
            value = item.value

        restored = restored.replace(key, value)
    return restored


def placeholder_keys(placeholders: list[PlaceholderMap] | list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()

    for item in placeholders:
        if isinstance(item, dict):
            keys.add(item["key"])
        else:
            keys.add(item.key)

    return keys


def placeholders_are_preserved(
    text: str,
    placeholders: list[PlaceholderMap] | list[dict[str, Any]],
) -> bool:
    expected_keys = placeholder_keys(placeholders)
    found_keys = set(re.findall(r"\[\[[A-Z_0-9]+\]\]", text))

    if not expected_keys:
        return not found_keys

    return found_keys == expected_keys


def is_translation_candidate(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    alpha_count = sum(1 for char in stripped if char.isalpha())
    return alpha_count >= 3
