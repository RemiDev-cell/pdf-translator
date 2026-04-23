from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


class Settings:
    log_level: str = os.getenv("PDF_TRANSLATOR_LOG_LEVEL", "INFO")
    input_dir: Path = Path(os.getenv("PDF_TRANSLATOR_INPUT_DIR", "data/input"))
    output_dir: Path = Path(os.getenv("PDF_TRANSLATOR_OUTPUT_DIR", "data/output"))
    debug_dir: Path = Path(os.getenv("PDF_TRANSLATOR_DEBUG_DIR", "data/debug"))

    model_backend: str = os.getenv("PDF_TRANSLATOR_MODEL_BACKEND", "mock")
    api_base: str = os.getenv("PDF_TRANSLATOR_API_BASE", "http://localhost:4000/v1")
    api_key: str = os.getenv("PDF_TRANSLATOR_API_KEY", "lm-studio")
    model_name: str = os.getenv("PDF_TRANSLATOR_MODEL_NAME", "translategemma-4b-it")
    request_timeout_seconds: int = int(os.getenv("PDF_TRANSLATOR_REQUEST_TIMEOUT_SECONDS", "45"))
    context_group_max_lines: int = int(os.getenv("PDF_TRANSLATOR_CONTEXT_GROUP_MAX_LINES", "1"))
    context_group_max_chars: int = int(os.getenv("PDF_TRANSLATOR_CONTEXT_GROUP_MAX_CHARS", "160"))
    batch_max_segments: int = int(os.getenv("PDF_TRANSLATOR_BATCH_MAX_SEGMENTS", "2"))
    batch_max_chars: int = int(os.getenv("PDF_TRANSLATOR_BATCH_MAX_CHARS", "800"))


settings = Settings()
