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


# ---------------------------------------------------------------------------
# parse_math_segments
# ---------------------------------------------------------------------------

def test_parse_math_segments_empty_string() -> None:
    assert katex_formatter.parse_math_segments("") == []


def test_parse_math_segments_no_math() -> None:
    segs = katex_formatter.parse_math_segments("Hello, world!")
    assert segs == [{"type": "text", "content": "Hello, world!"}]


def test_parse_math_segments_display_dollar_dollar() -> None:
    segs = katex_formatter.parse_math_segments(r"here $$\frac{a}{b}$$ end")
    assert len(segs) == 3
    assert segs[0] == {"type": "text", "content": "here "}
    assert segs[1] == {"type": "math", "expression": r"\frac{a}{b}"}
    assert segs[2] == {"type": "text", "content": " end"}


def test_parse_math_segments_display_backslash_bracket() -> None:
    segs = katex_formatter.parse_math_segments(r"before \[\sum_{n=1}^{\infty} x\] after")
    assert len(segs) == 3
    assert segs[1] == {"type": "math", "expression": r"\sum_{n=1}^{\infty} x"}


def test_parse_math_segments_inline_backslash_paren() -> None:
    segs = katex_formatter.parse_math_segments(r"Euler: \(e^{i\pi}+1=0\).")
    assert len(segs) == 3
    assert segs[1] == {"type": "math", "expression": r"e^{i\pi}+1=0"}


def test_parse_math_segments_inline_single_dollar() -> None:
    segs = katex_formatter.parse_math_segments(r"value $\sqrt{2}$ here")
    assert len(segs) == 3
    assert segs[1] == {"type": "math", "expression": r"\sqrt{2}"}


def test_parse_math_segments_double_dollar_not_parsed_as_two_singles() -> None:
    """$$…$$ must be consumed as one display-math block, not two bare $."""
    segs = katex_formatter.parse_math_segments(r"$$x^2$$")
    assert len(segs) == 1
    assert segs[0] == {"type": "math", "expression": "x^2"}


def test_parse_math_segments_multiline_display_math() -> None:
    text = "$$\n\\int_0^\\infty e^{-x^2}\\,dx = \\frac{\\sqrt{\\pi}}{2}\n$$"
    segs = katex_formatter.parse_math_segments(text)
    assert len(segs) == 1
    assert segs[0]["type"] == "math"
    assert "\\int" in segs[0]["expression"]


def test_parse_math_segments_multiline_single_dollar() -> None:
    text = "before $\n\\int_0^1 x^2\\,dx\n$ after"
    segs = katex_formatter.parse_math_segments(text)
    assert len(segs) == 3
    assert segs[0]["type"] == "text"
    assert segs[1]["type"] == "math"
    assert "\\int_0^1" in segs[1]["expression"]
    assert segs[2]["type"] == "text"


def test_parse_math_segments_mixed_text_and_math() -> None:
    text = r"Euler: \(e^{i\pi}+1=0\). Also $$\frac{a}{b}$$."
    segs = katex_formatter.parse_math_segments(text)
    math_segs = [s for s in segs if s["type"] == "math"]
    assert len(math_segs) == 2
    assert math_segs[0]["expression"] == r"e^{i\pi}+1=0"
    assert math_segs[1]["expression"] == r"\frac{a}{b}"


def test_parse_math_segments_multiple_inline_dollars() -> None:
    text = r"Let $a$ and $b$ be integers."
    segs = katex_formatter.parse_math_segments(text)
    math_segs = [s for s in segs if s["type"] == "math"]
    assert len(math_segs) == 2
    assert math_segs[0]["expression"] == "a"
    assert math_segs[1]["expression"] == "b"


def test_parse_math_segments_matrix_in_display_math() -> None:
    text = r"$$\begin{bmatrix} a & b \\ c & d \end{bmatrix}$$"
    segs = katex_formatter.parse_math_segments(text)
    assert len(segs) == 1
    assert segs[0]["type"] == "math"
    assert "bmatrix" in segs[0]["expression"]


def test_parse_math_segments_preserves_surrounding_text() -> None:
    text = r"**Sum:** $$\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}$$ done"
    segs = katex_formatter.parse_math_segments(text)
    assert segs[0] == {"type": "text", "content": "**Sum:** "}
    assert segs[1]["type"] == "math"
    assert segs[2] == {"type": "text", "content": " done"}


def test_render_normalizes_frac_shorthand() -> None:
    path = katex_formatter.render(r"\int x\,dx = \frac12 x^2 + C")
    try:
        assert path.exists()
        assert path.suffix == ".png"
    finally:
        katex_formatter.cleanup(path)


def test_render_normalizes_tfrac_and_dfrac() -> None:
    path = katex_formatter.render(r"\cos^2 x = \tfrac{1+\cos 2x}{2} = \dfrac{1+\cos 2x}{2}")
    try:
        assert path.exists()
        assert path.suffix == ".png"
    finally:
        katex_formatter.cleanup(path)


def test_render_strips_boxed_and_size_macros() -> None:
    path = katex_formatter.render(
        r"\boxed{\displaystyle \int \arctan(x)\,dx = x\arctan(x) - \frac{1}{2}\ln\!\bigl(1+x^{2}\bigr) + C}"
    )
    try:
        assert path.exists()
        assert path.suffix == ".png"
    finally:
        katex_formatter.cleanup(path)


def test_adaptive_expression_scale_shrinks_complex_expressions() -> None:
    simple = katex_formatter._adaptive_expression_scale("x+y")
    complex_expr = katex_formatter._adaptive_expression_scale(
        r"\int \frac{x}{1+x^2}\,dx = \frac{1}{2}\int\frac{dw}{w} = \frac{1}{2}\ln|w| + C"
    )
    assert simple >= complex_expr


def test_adaptive_expression_scale_penalizes_multiline() -> None:
    single_line = katex_formatter._adaptive_expression_scale(r"\int x\,dx = \frac{x^2}{2}")
    multi_line = katex_formatter._adaptive_expression_scale(
        r"\int x\,dx = \frac{x^2}{2}\n= \frac{1}{2}x^2 + C"
    )
    assert single_line >= multi_line


def test_should_mathjax_display_prefers_short_equations() -> None:
    assert katex_formatter._should_mathjax_display(r"\int \cos^2 x\,dx")
    assert not katex_formatter._should_mathjax_display(
        r"\int \cos^2 x\,dx = \int \frac{1+\cos(2x)}{2}\,dx = \frac{1}{2}\int 1\,dx + \frac{1}{2}\int \cos(2x)\,dx"
    )


def test_mathjax_render_scale_has_readable_floors() -> None:
    display_scale = katex_formatter._mathjax_render_scale(r"\int \cos^2 x\,dx", display_mode=True)
    inline_scale = katex_formatter._mathjax_render_scale(
        r"\int \cos^2 x\,dx = \int \frac{1+\cos(2x)}{2}\,dx",
        display_mode=False,
    )
    assert display_scale >= 0.66
    assert inline_scale >= 0.58


def test_normalize_expression_keeps_boxed_for_mathjax() -> None:
    kept = katex_formatter._normalize_mathtext_expression(r"\boxed{x+1}", keep_boxed=True)
    stripped = katex_formatter._normalize_mathtext_expression(r"\boxed{x+1}", keep_boxed=False)
    assert r"\boxed" in kept
    assert r"\boxed" not in stripped


def test_render_uses_mathjax_backend_when_selected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = tmp_path / "mathjax.png"
    out.write_bytes(b"x")
    monkeypatch.setattr(katex_formatter.settings, "LATEX_RENDERER", "mathjax", raising=False)
    monkeypatch.setattr(katex_formatter.settings, "LATEX_RENDERER_FALLBACK", True, raising=False)
    monkeypatch.setattr(katex_formatter, "_render_with_mathjax", lambda _expr: out)

    path = katex_formatter.render(r"\frac{a}{b}")
    assert path == out


def test_render_falls_back_to_matplotlib_when_mathjax_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "mpl.png"
    out.write_bytes(b"x")
    monkeypatch.setattr(katex_formatter.settings, "LATEX_RENDERER", "mathjax", raising=False)
    monkeypatch.setattr(katex_formatter.settings, "LATEX_RENDERER_FALLBACK", True, raising=False)

    def _boom(_expr: str):
        raise RuntimeError("mathjax unavailable")

    monkeypatch.setattr(katex_formatter, "_render_with_mathjax", _boom)
    monkeypatch.setattr(katex_formatter, "_render_with_matplotlib", lambda _expr: out)

    path = katex_formatter.render(r"\frac{a}{b}")
    assert path == out
