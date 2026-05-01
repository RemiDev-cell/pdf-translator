from __future__ import annotations

import re

import requests

from pdf_translator.config import settings


IGNORED_TEXT_RESPONSE_LINES = {
    "### Response:",
    "Response:",
    "Translation:",
    "Output:",
    "```",
}

IGNORED_TEXT_RESPONSE_PREFIXES = (
    "- Return only",
    "- No title",
    "- No explanation",
    "- No markdown",
    "- Preserve placeholders",
    "- Keep labels",
)


def translate_text_mock(text: str) -> str:
    return f"[EN] {text}"


def build_translation_prompt(text: str) -> str:
    return f"""Translate the following French scientific/support text into English.

Rules:
- Return only the translated text.
- No title.
- No explanation.
- No markdown.
- Preserve placeholders exactly, including [[VERSION_1]], [[COMMIT_1]], [[ISO_DATE_1]], [[URL_1]], [[EMAIL_1]].
- Keep labels, punctuation, and scientific notation as close as possible to the source.

Text:
{text}
"""


def clean_text_response(response_text: str) -> str:
    cleaned_lines: list[str] = []

    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line in IGNORED_TEXT_RESPONSE_LINES:
            continue
        if line.startswith("Text:"):
            continue
        if line.startswith("Strict rules:"):
            continue
        if line.startswith("Rules:"):
            continue
        if any(line.startswith(prefix) for prefix in IGNORED_TEXT_RESPONSE_PREFIXES):
            continue
        cleaned_lines.append(raw_line)

    cleaned = "\n".join(cleaned_lines).strip()
    cleaned = re.sub(r"^###\s*Response:\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def run_llm_prompt(prompt: str) -> str:
    url = f"{settings.api_base}/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.model_name,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.0,
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=settings.request_timeout_seconds,
    )
    response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def translate_text_llm(text: str) -> str:
    raw_response = run_llm_prompt(build_translation_prompt(text))
    return clean_text_response(raw_response)


def translate_batch(prompt: str) -> str:
    return run_llm_prompt(prompt)


def translate_text(text: str) -> str:
    if settings.model_backend == "mock":
        return translate_text_mock(text)
    if settings.model_backend == "lmstudio":
        return translate_text_llm(text)

    raise ValueError(f"Unsupported model backend: {settings.model_backend}")
