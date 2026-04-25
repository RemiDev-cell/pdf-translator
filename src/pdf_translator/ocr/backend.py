from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, TypedDict

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



def _parse_tesseract_tsv_lines(tsv_text: str) -> list[dict[str, Any]]:
    lines = [line for line in tsv_text.splitlines() if line.strip()]
    if len(lines) <= 1:
        return []

    header = lines[0].split("\t")
    rows: list[dict[str, str]] = []
    for raw_line in lines[1:]:
        values = raw_line.split("\t")
        if len(values) < len(header):
            values = values + [""] * (len(header) - len(values))
        rows.append(dict(zip(header, values)))

    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        if row.get("level") != "5":
            continue
        text = row.get("text", "").strip()
        if not text:
            continue
        key = (
            row.get("page_num", "1"),
            row.get("block_num", "0"),
            row.get("par_num", "0"),
            row.get("line_num", "0"),
        )
        grouped.setdefault(key, []).append(row)

    layout_lines: list[dict[str, Any]] = []
    for line_index, (key, words) in enumerate(grouped.items(), start=1):
        lefts = [int(word.get("left", 0) or 0) for word in words]
        tops = [int(word.get("top", 0) or 0) for word in words]
        rights = [int(word.get("left", 0) or 0) + int(word.get("width", 0) or 0) for word in words]
        bottoms = [int(word.get("top", 0) or 0) + int(word.get("height", 0) or 0) for word in words]
        confidences = [float(word.get("conf", -1) or -1) for word in words if float(word.get("conf", -1) or -1) >= 0]

        layout_lines.append(
            {
                "line_index": line_index,
                "page_num": int(key[0]),
                "block_num": int(key[1]),
                "par_num": int(key[2]),
                "line_num": int(key[3]),
                "text": " ".join(word.get("text", "").strip() for word in words if word.get("text", "").strip()),
                "bbox_px": {
                    "x0": min(lefts) if lefts else 0,
                    "y0": min(tops) if tops else 0,
                    "x1": max(rights) if rights else 0,
                    "y1": max(bottoms) if bottoms else 0,
                },
                "confidence": round(sum(confidences) / len(confidences), 2) if confidences else None,
                "word_count": len(words),
            }
        )

    return layout_lines


def _run_tesseract_layout(image_path: Path) -> list[dict[str, Any]]:
    tesseract_bin = _resolve_tesseract_binary()
    process = subprocess.run(
        [tesseract_bin, str(image_path), "stdout", "tsv"],
        capture_output=True,
        text=True,
        check=False,
    )
    if process.returncode != 0:
        return []
    return _parse_tesseract_tsv_lines(process.stdout)


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

    layout = _run_tesseract_layout(image_path)
    return {
        "backend": "tesseract",
        "status": "ok",
        "text": process.stdout.strip(),
        "detail": "tesseract cli output",
        "layout": layout,
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
