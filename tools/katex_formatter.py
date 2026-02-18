# tools/katex_formatter.py
"""Renders KaTeX-style math expressions into PNG images using matplotlib mathtext."""

import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless backend — no display needed
import matplotlib.pyplot as plt

import settings


def render(expression: str) -> Path:
    """Render a bare math expression and return the path to a temporary PNG file.

    Expects a raw math expression with no delimiters, e.g.::

        render(r"\\frac{a}{b} = \\sqrt{x^2 + y^2}")

    The caller is responsible for deleting the file when done.

    Parameters
    ----------
    expression:
        A plain math expression (no ``$``, ``$$``, ``\\(``, or ``\\[``).

    Returns
    -------
    Path
        Absolute path to the generated PNG.

    Raises
    ------
    ValueError
        If the expression is blank.
    RuntimeError
        If matplotlib fails to render the expression.
    """
    expression = expression.strip()
    if not expression:
        raise ValueError("Expression must not be empty.")

    # Always wrap in display-math delimiters for matplotlib mathtext.
    expression = f"${expression}$"

    fig = plt.figure(figsize=(0.01, 0.01))  # will be resized to content
    fig.patch.set_alpha(0)  # transparent figure background

    try:
        text_obj = fig.text(
            0,
            0,
            expression,
            fontsize=settings.KATEX_FONT_SIZE,
            color=settings.KATEX_FG_COLOR,
            usetex=False,  # uses matplotlib mathtext, not a TeX installation
        )

        # Measure the rendered bounding box and resize the figure to fit.
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
        bbox = text_obj.get_window_extent(renderer=renderer)

        pad = 10  # pixels of padding on each side
        fig.set_size_inches(
            (bbox.width + pad * 2) / settings.KATEX_DPI,
            (bbox.height + pad * 2) / settings.KATEX_DPI,
        )

        # Re-position the text with padding offset.
        text_obj.set_position((pad / (bbox.width + pad * 2),
                               pad / (bbox.height + pad * 2)))

        # Write to a temp file.
        tmp = tempfile.NamedTemporaryFile(
            suffix=".png", prefix="katex_", delete=False
        )
        tmp.close()

        fig.savefig(
            tmp.name,
            dpi=settings.KATEX_DPI,
            bbox_inches="tight",
            facecolor=settings.KATEX_BG_COLOR,
            transparent=True,
        )

        return Path(tmp.name)

    except Exception as exc:
        raise RuntimeError(f"Failed to render expression: {exc}") from exc

    finally:
        plt.close(fig)


def cleanup(png_path: Path) -> None:
    """Delete a PNG file previously returned by :func:`render`."""
    try:
        png_path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"[KATEX CLEANUP] Warning: {exc}")
