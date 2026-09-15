import pytest

from author_agent.io_utils import validate_book, validate_date, validate_optional_image


def test_invalid_date_clear_message():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        validate_date("13/09/2026")


def test_missing_book_fails_before_llm(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        validate_book(tmp_path / "missing.pdf")


def test_image_suffix_validation(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("x")
    with pytest.raises(ValueError, match="Unsupported format"):
        validate_optional_image(p)
