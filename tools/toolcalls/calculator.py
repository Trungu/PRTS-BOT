# tools/calculator.py — safe arithmetic calculator tool for the LLM agent.
#
# The LLM can call `calculator` with a mathematical expression string.
# Only safe numeric operations are allowed — no builtins, no imports.

from __future__ import annotations

import math
import operator
import ast

# ---------------------------------------------------------------------------
# Allowed names inside expressions
# ---------------------------------------------------------------------------

_SAFE_NAMES: dict[str, object] = {
    # Constants
    "pi": math.pi,
    "e":  math.e,
    "tau": math.tau,
    "inf": math.inf,
    # Common functions
    "abs":   abs,
    "round": round,
    "sqrt":  math.sqrt,
    "cbrt":  math.cbrt if hasattr(math, "cbrt") else (lambda x: x ** (1/3)),
    "log":   math.log,
    "log2":  math.log2,
    "log10": math.log10,
    "exp":   math.exp,
    "pow":   math.pow,
    "sin":   math.sin,
    "cos":   math.cos,
    "tan":   math.tan,
    "asin":  math.asin,
    "acos":  math.acos,
    "atan":  math.atan,
    "atan2": math.atan2,
    "sinh":  math.sinh,
    "cosh":  math.cosh,
    "tanh":  math.tanh,
    "ceil":  math.ceil,
    "floor": math.floor,
    "factorial": math.factorial,
    "gcd":   math.gcd,
    "lcm":   math.lcm if hasattr(math, "lcm") else (lambda a, b: abs(a*b) // math.gcd(a, b)),
    "degrees": math.degrees,
    "radians": math.radians,
    "hypot": math.hypot,
    "min":   min,
    "max":   max,
    "sum":   sum,
}

# Allowed AST node types — built dynamically so missing names in any Python
# version are silently skipped rather than crashing at import time.
_ALLOWED_NODE_NAMES = [
    "Expression", "BoolOp", "BinOp", "UnaryOp", "IfExp",
    "Call", "Constant", "Name", "Load",
    "Add", "Sub", "Mult", "Div", "FloorDiv", "Mod",
    "Pow", "UAdd", "USub", "BitOr", "BitAnd", "BitXor",
    "LShift", "RShift", "Invert",
    "Compare", "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE",
    "And", "Or", "Not",
    "List", "Tuple",
]
_ALLOWED_NODES = tuple(
    getattr(ast, name) for name in _ALLOWED_NODE_NAMES if hasattr(ast, name)
)


def _safe_eval(expr: str) -> object:
    """Parse and evaluate *expr* using only allowed AST nodes and names."""
    tree = ast.parse(expr.strip(), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"Forbidden operation in expression: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in _SAFE_NAMES:
            raise ValueError(f"Unknown name: '{node.id}'")
    # compile + eval with restricted namespace
    code = compile(tree, "<calculator>", "eval")
    return eval(code, {"__builtins__": {}}, _SAFE_NAMES)  # noqa: S307


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------

def calculator(expression: str) -> str:
    """Evaluate a mathematical *expression* and return the result as a string.

    Parameters
    ----------
    expression:
        A Python-style arithmetic expression, e.g. ``"2 ** 10"``,
        ``"sqrt(2) * pi"``, ``"factorial(10)"``.

    Returns
    -------
    str
        The numeric result, or an error message prefixed with ``"Error:"``
        if the expression is invalid or unsafe.
    """
    try:
        result = _safe_eval(expression)
        # Format cleanly: strip trailing .0 for whole floats
        if isinstance(result, float) and result.is_integer():
            return str(int(result))
        return str(result)
    except ZeroDivisionError:
        return "Error: division by zero"
    except (ValueError, TypeError, SyntaxError, OverflowError) as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# OpenAI-style tool definition (used by llm_api agentic loop)
# ---------------------------------------------------------------------------

TOOL_DEFINITION = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": (
            "Evaluate a mathematical expression and return the numeric result. "
            "Supports arithmetic (+, -, *, /, //, %, **), common math functions "
            "(sqrt, log, sin, cos, tan, factorial, gcd, lcm, …), and constants "
            "(pi, e, tau). Use this any time you need to compute a number precisely."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "A Python-style arithmetic expression, e.g. '2 ** 10', "
                        "'sqrt(2) * pi', 'factorial(12) / 2'."
                    ),
                }
            },
            "required": ["expression"],
        },
    },
}
