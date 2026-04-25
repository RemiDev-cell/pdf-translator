import pytest
import typer

from pdf_translator.cli import _parse_pages_arg


def test_parse_pages_arg_accepts_ranges_and_deduplicates() -> None:
    assert _parse_pages_arg("1-3, 3, 5") == [1, 2, 3, 5]


def test_parse_pages_arg_rejects_descending_ranges() -> None:
    with pytest.raises(typer.BadParameter):
        _parse_pages_arg("4-2")


def test_parse_pages_arg_rejects_zero_page() -> None:
    with pytest.raises(typer.BadParameter):
        _parse_pages_arg("0")
