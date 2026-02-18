from pathlib import Path

import pytest

from tools import katex_formatter


def test_render_creates_png_and_cleanup_removes_file() -> None:
    path = katex_formatter.render(r"\frac{a}{b}")
    try:
        assert isinstance(path, Path)
        assert path.exists()
        assert path.suffix == ".png"
    finally:
        katex_formatter.cleanup(path)

    assert not path.exists()


def test_render_blank_expression_raises() -> None:
    with pytest.raises(ValueError):
        katex_formatter.render("   ")
