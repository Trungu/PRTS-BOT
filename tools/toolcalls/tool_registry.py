from __future__ import annotations

from typing import Callable

from tools.toolcalls.calculator import calculator, TOOL_DEFINITION as _CALC_DEF
from tools.toolcalls.code_runner import (
    run_python,           TOOL_DEFINITION                as _CODE_DEF,
    list_workspace,       LIST_WORKSPACE_TOOL_DEFINITION  as _LIST_DEF,
    get_workspace_file,   GET_WORKSPACE_FILE_TOOL_DEFINITION as _GET_FILE_DEF,
)
from tools.toolcalls.terminal_runner import run_terminal, TOOL_DEFINITION as _TERM_DEF
from tools.toolcalls.unit_converter import unit_converter, TOOL_DEFINITION as _UNIT_DEF

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Maps tool name → callable(arguments_dict) → str
TOOLS: dict[str, Callable[[dict], str]] = {
    "calculator":         lambda args: calculator(args["expression"]),
    "run_python":         lambda args: run_python(args["code"]),
    "list_workspace":     lambda args: list_workspace(),
    "get_workspace_file": lambda args: get_workspace_file(args["filename"]),
    "run_terminal":        lambda args: run_terminal(args["command"]),
    "unit_converter":     lambda args: unit_converter(
                              args["value"], args["from_unit"], args["to_unit"]
                          ),
}

# List of OpenAI-style tool definitions sent with every API request.
TOOL_DEFINITIONS: list[dict] = [
    _CALC_DEF,
    _CODE_DEF,
    _LIST_DEF,
    _GET_FILE_DEF,
    _TERM_DEF,
    _UNIT_DEF,
]
