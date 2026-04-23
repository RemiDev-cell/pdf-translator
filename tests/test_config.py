from pdf_translator.config import settings


def test_batch_settings_are_positive() -> None:
    assert settings.request_timeout_seconds > 0
    assert settings.batch_max_segments > 0
    assert settings.batch_max_chars > 0
