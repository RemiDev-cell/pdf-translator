from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TypedDict

from pdf_translator.config import settings


class OcrResult(TypedDict):
    backend: str
    status: str
    text: str
    detail: str


class OcrBackendUnavailableError(RuntimeError):
    pass



def _mock_ocr(image_path: Path) -> OcrResult:
    return {
        "backend": "mock",
        "status": "ok",
        "text": f"[MOCK OCR] {image_path.stem}",
        "detail": "mock backend output",
    }



def _resolve_tesseract_binary() -> str:
    tesseract_bin = settings.ocr_tesseract_bin
    if shutil.which(tesseract_bin):
        return tesseract_bin
    raise OcrBackendUnavailableError(f"Tesseract binary not found: {tesseract_bin}")



def _run_tesseract(image_path: Path) -> OcrResult:
    tesseract_bin = _resolve_tesseract_binary()
    process = subprocess.run(
        [tesseract_bin, str(image_path), "stdout"],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or f"tesseract exited with code {process.returncode}"
        return {
            "backend": "tesseract",
            "status": "error",
            "text": "",
            "detail": detail,
        }

    return {
        "backend": "tesseract",
        "status": "ok",
        "text": process.stdout.strip(),
        "detail": "tesseract cli output",
    }



def _auto_backend() -> str:
    if shutil.which(settings.ocr_tesseract_bin):
        return "tesseract"
    raise OcrBackendUnavailableError("No OCR backend available in auto mode")



def run_ocr(image_path: Path, backend: str | None = None) -> OcrResult:
    selected_backend = (backend or settings.ocr_backend).strip().lower()

    if selected_backend == "auto":
        try:
            selected_backend = _auto_backend()
        except OcrBackendUnavailableError as exc:
            return {
                "backend": "auto",
                "status": "unavailable",
                "text": "",
                "detail": str(exc),
            }

    if selected_backend == "mock":
        return _mock_ocr(image_path)

    if selected_backend == "tesseract":
        try:
            return _run_tesseract(image_path)
        except OcrBackendUnavailableError as exc:
            return {
                "backend": "tesseract",
                "status": "unavailable",
                "text": "",
                "detail": str(exc),
            }

    return {
        "backend": selected_backend,
        "status": "unsupported",
        "text": "",
        "detail": f"Unsupported OCR backend: {selected_backend}",
    }
