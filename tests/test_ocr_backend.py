from pathlib import Path

from pdf_translator.ocr.backend import run_ocr


def test_run_ocr_mock_backend_returns_text(tmp_path: Path) -> None:
    image_path = tmp_path / "crop.png"
    image_path.write_bytes(b"fake")

    result = run_ocr(image_path, backend="mock")

    assert result["backend"] == "mock"
    assert result["status"] == "ok"
    assert "[MOCK OCR]" in result["text"]


def test_run_ocr_unknown_backend_is_reported(tmp_path: Path) -> None:
    image_path = tmp_path / "crop.png"
    image_path.write_bytes(b"fake")

    result = run_ocr(image_path, backend="made-up")

    assert result["status"] == "unsupported"
    assert result["text"] == ""
