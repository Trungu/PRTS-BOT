# tools/katex_formatter.py
"""Renders KaTeX-style math expressions into PNG images using matplotlib mathtext."""

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import settings


_FRAC_SHORTHAND_RE = re.compile(r"\\(?:d|t)?frac\s*([A-Za-z0-9])\s*([A-Za-z0-9])")
_SIZE_MACRO_RE = re.compile(r"\\(?:big|Big|bigg|Bigg)[lr]?\b")


def _unwrap_macro_block(expr: str, macro: str) -> str:
    r"""Replace ``\macro{...}`` with ``...`` while keeping the inner content."""
    token = f"\\{macro}"
    i = 0
    out: list[str] = []

    while i < len(expr):
        if not expr.startswith(token, i):
            out.append(expr[i])
            i += 1
            continue

        j = i + len(token)
        while j < len(expr) and expr[j].isspace():
            j += 1
        if j >= len(expr) or expr[j] != "{":
            out.append(token)
            i += len(token)
            continue

        depth = 0
        k = j
        while k < len(expr):
            ch = expr[k]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1

        if k >= len(expr) or depth != 0:
            out.append(token)
            i += len(token)
            continue

        inner = expr[j + 1 : k]
        out.append(inner)
        i = k + 1

    return "".join(out)


def _normalize_mathtext_expression(expression: str, *, keep_boxed: bool = False) -> str:
    """Normalize common KaTeX/LaTeX forms for renderer backends."""
    expr = expression

    # matplotlib mathtext doesn't support \tfrac/\dfrac variants.
    expr = expr.replace(r"\tfrac", r"\frac")
    expr = expr.replace(r"\dfrac", r"\frac")

    # matplotlib mathtext rejects shorthand forms like \frac12.
    expr = _FRAC_SHORTHAND_RE.sub(r"\\frac{\1}{\2}", expr)

    # Strip display-size directives unsupported by mathtext.
    expr = expr.replace(r"\displaystyle", "")

    # Remove size helpers (\bigl, \Bigr, ...) and keep delimiters.
    expr = _SIZE_MACRO_RE.sub("", expr)

    # matplotlib can't parse \boxed; mathjax can keep it.
    if not keep_boxed:
        expr = _unwrap_macro_block(expr, "boxed")

    return expr.strip()


def _adaptive_expression_scale(expression: str) -> float:
    """Return a scale multiplier for expression complexity."""
    if not settings.KATEX_ADAPTIVE_SCALE:
        return 1.0

    expr = expression.strip()
    complexity = len(expr)
    complexity += expr.count(r"\frac") * 20
    complexity += expr.count(r"\int") * 12
    complexity += expr.count("=") * 6
    complexity += expr.count(r"\Rightarrow") * 8
    complexity += expr.count("\n") * 18

    if complexity <= 55:
        scale = 1.0
    elif complexity <= 95:
        scale = 0.9
    elif complexity <= 145:
        scale = 0.82
    else:
        scale = 0.74

    # Multiline derivations are usually the tallest equations in Discord cards.
    line_count = expr.count("\n") + 1
    if line_count >= 2:
        scale *= 0.9
    if line_count >= 3:
        scale *= 0.92

    return max(0.55, scale)


def _should_mathjax_display(expression: str) -> bool:
    """Heuristic: use display math only for short standalone equations."""
    expr = expression.strip()
    if not expr:
        return False
    if "\n" in expr:
        return False
    # Short symbol-only expressions look oversized in display mode.
    if len(expr) <= 14 and "=" not in expr and r"\int" not in expr:
        return False
    complexity = len(expr)
    complexity += expr.count("=") * 8
    complexity += expr.count(r"\frac") * 16
    complexity += expr.count(r"\int") * 10
    complexity += expr.count(r"\sum") * 10
    complexity += expr.count(r"\Rightarrow") * 10
    return complexity <= 72


def _mathjax_render_scale(expression: str, *, display_mode: bool) -> float:
    """Compute a readability-biased MathJax scale."""
    base = float(settings.KATEX_RENDER_SCALE)
    adaptive = _adaptive_expression_scale(expression)

    # MathJax currently renders denser than the old matplotlib path; give it
    # a baseline boost and softer adaptive penalty.
    boosted = base * (1.22 if display_mode else 1.12)
    softened = boosted * (0.88 + 0.12 * adaptive)

    floor = 0.66 if display_mode else 0.58
    ceiling = 1.25
    return max(floor, min(ceiling, softened))


def _downscale_png_to_bounds(png_path: Path, *, max_width: int, max_height: int) -> None:
    """Downscale oversized PNGs to bounds without ever upscaling."""
    try:
        from PIL import Image
    except Exception:
        return

    try:
        with Image.open(png_path) as img:
            w, h = img.size
            if w <= max_width and h <= max_height:
                return
            img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
            img.save(png_path)
    except Exception:
        # Non-fatal: keep original render if resize fails.
        return


def _render_with_matplotlib(normalized_expression: str) -> Path:
    """Render with matplotlib mathtext backend."""
    try:
        import matplotlib
        matplotlib.use("Agg")  # headless backend — no display needed
        import matplotlib.pyplot as plt
    except Exception as exc:
        raise RuntimeError(
            "matplotlib is required for matplotlib renderer backend"
        ) from exc

    expression = normalized_expression
    # Always wrap in display-math delimiters for matplotlib mathtext.
    expression = f"${expression}$"

    fig = plt.figure(figsize=(0.01, 0.01))  # resized to content later
    fig.patch.set_alpha(0)  # transparent figure background

    try:
        adaptive = _adaptive_expression_scale(expression)
        base_font_size = (
            float(settings.KATEX_FONT_SIZE)
            * float(settings.KATEX_RENDER_SCALE)
            * adaptive
        )
        text_obj = fig.text(
            0,
            0,
            expression,
            fontsize=base_font_size,
            color=settings.KATEX_FG_COLOR,
            usetex=False,  # uses matplotlib mathtext, not a TeX installation
        )

        # Measure rendered bounds.
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
        bbox = text_obj.get_window_extent(renderer=renderer)

        pad = int(settings.KATEX_RENDER_PAD_PX)
        max_width = float(settings.KATEX_MAX_WIDTH_PX - pad * 2)
        max_height = float(settings.KATEX_MAX_HEIGHT_PX - pad * 2)

        # Downscale oversized expressions so output dimensions are consistent.
        if bbox.width > 0 and bbox.height > 0:
            scale = min(
                1.0,
                max_width / float(bbox.width),
                max_height / float(bbox.height),
            )
            if scale < 1.0:
                text_obj.set_fontsize(max(6.0, base_font_size * scale))
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()  # type: ignore[attr-defined]
                bbox = text_obj.get_window_extent(renderer=renderer)

        fig.set_size_inches(
            (min(float(bbox.width), max_width) + pad * 2) / settings.KATEX_DPI,
            (min(float(bbox.height), max_height) + pad * 2) / settings.KATEX_DPI,
        )

        # Re-position the text with padding offset.
        text_obj.set_position(
            (
                pad / (float(bbox.width) + pad * 2),
                pad / (float(bbox.height) + pad * 2),
            )
        )

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


def _render_with_mathjax(normalized_expression: str) -> Path:
    """Render with MathJax (Node) and rasterize SVG to PNG."""
    node_bin = shutil.which("node")
    if not node_bin:
        raise RuntimeError("node executable not found")

    script_path = Path(__file__).resolve().parent / "mathjax" / "render_mathjax.cjs"
    if not script_path.exists():
        raise RuntimeError(f"MathJax renderer script missing: {script_path}")

    script_dir = str(script_path.parent)
    display_mode = _should_mathjax_display(normalized_expression)
    mathjax_scale = _mathjax_render_scale(normalized_expression, display_mode=display_mode)

    svg_tmp = tempfile.NamedTemporaryFile(suffix=".svg", prefix="mathjax_", delete=False)
    svg_tmp.close()
    png_tmp = tempfile.NamedTemporaryFile(suffix=".png", prefix="katex_", delete=False)
    png_tmp.close()
    svg_path = Path(svg_tmp.name)
    png_path = Path(png_tmp.name)

    try:
        proc = subprocess.run(
            [
                node_bin,
                str(script_path),
                "--out",
                str(svg_path),
                "--color",
                str(settings.KATEX_FG_COLOR),
                "--scale",
                str(mathjax_scale),
                "--display",
                "true" if display_mode else "false",
            ],
            input=normalized_expression,
            text=True,
            capture_output=True,
            check=False,
            cwd=script_dir,
            timeout=10,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            stdout = (proc.stdout or "").strip()
            raise RuntimeError(f"MathJax node render failed: {stderr or stdout or 'unknown error'}")

        rsvg_bin = shutil.which("rsvg-convert")
        if rsvg_bin:
            zoom = max(1.0, float(settings.KATEX_DPI) / 96.0)
            cmd = [
                rsvg_bin,
                "-f",
                "png",
                "-o",
                str(png_path),
                "-z",
                str(zoom),
                str(svg_path),
            ]
            rsvg_proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            if rsvg_proc.returncode != 0:
                rerr = (rsvg_proc.stderr or "").strip()
                rout = (rsvg_proc.stdout or "").strip()
                raise RuntimeError(f"rsvg-convert failed: {rerr or rout or 'unknown error'}")
        else:
            # Secondary path for environments with CairoSVG available.
            try:
                import cairosvg  # type: ignore
            except Exception as exc:
                raise RuntimeError(
                    "No SVG rasterizer available. Install librsvg (rsvg-convert) or cairosvg+cairo."
                ) from exc

            cairosvg.svg2png(
                url=str(svg_path),
                write_to=str(png_path),
                dpi=float(settings.KATEX_DPI),
            )
        _downscale_png_to_bounds(
            png_path,
            max_width=int(settings.KATEX_MAX_WIDTH_PX),
            max_height=int(settings.KATEX_MAX_HEIGHT_PX),
        )
        return png_path
    except Exception:
        png_path.unlink(missing_ok=True)
        raise
    finally:
        svg_path.unlink(missing_ok=True)


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

    normalized_mathjax = _normalize_mathtext_expression(expression, keep_boxed=True)
    normalized_matplotlib = _normalize_mathtext_expression(expression, keep_boxed=False)

    if settings.LATEX_RENDERER == "mathjax":
        try:
            return _render_with_mathjax(normalized_mathjax)
        except Exception as exc:
            if not settings.LATEX_RENDERER_FALLBACK:
                raise RuntimeError(f"Failed to render expression: {exc}") from exc
            # Keep bot responses alive when mathjax runtime/deps are missing.
            return _render_with_matplotlib(normalized_matplotlib)

    return _render_with_matplotlib(normalized_matplotlib)


def cleanup(png_path: Path) -> None:
    """Delete a PNG file previously returned by :func:`render`."""
    try:
        png_path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"[KATEX CLEANUP] Warning: {exc}")


# ---------------------------------------------------------------------------
# Math-segment parser
# ---------------------------------------------------------------------------

# Matches four LaTeX delimiter styles, in priority order:
#   1. $$…$$  — display math  (checked before single $ to prevent mis-parsing)
#   2. \[…\]  — display math
#   3. \(…\)  — inline math
#   4. $…$    — inline math  (no $$ overlap; multiline supported)
_MATH_RE = re.compile(
    r'\$\$(.*?)\$\$'                   # Group 1: $$…$$ display
    r'|\\\[(.*?)\\\]'                  # Group 2: \[…\] display
    r'|\\\((.*?)\\\)'                  # Group 3: \(…\) inline
    r'|(?<!\$)\$([^$]+?)\$(?!\$)',     # Group 4: $…$ inline, supports newline
    re.DOTALL,
)


def parse_math_segments(text: str) -> list[dict]:
    """Split *text* into alternating plain-text and math segments.

    Recognises four delimiter styles:

    * ``$$...$$``   — display math
    * ``\\[...\\]`` — display math
    * ``\\(...\\)`` — inline math
    * ``$...$``     — inline math (single ``$``, can span lines)

    Returns
    -------
    list[dict]
        Each element is either::

            {"type": "text",  "content":    "<plain text>"}
            {"type": "math",  "expression": "<bare LaTeX expression>"}

    The returned expressions are already stripped of their delimiters and
    leading/trailing whitespace, ready to be passed directly to :func:`render`.
    """
    segments: list[dict] = []
    last_end = 0

    for m in _MATH_RE.finditer(text):
        # Plain text that precedes this math block.
        if m.start() > last_end:
            content = text[last_end : m.start()]
            if content:
                segments.append({"type": "text", "content": content})

        # The first non-None captured group holds the bare expression.
        expr = next((g for g in m.groups() if g is not None), "").strip()
        if expr:
            segments.append({"type": "math", "expression": expr})

        last_end = m.end()

    # Any trailing plain text after the last match.
    if last_end < len(text):
        tail = text[last_end:]
        if tail:
            segments.append({"type": "text", "content": tail})

    return segments
