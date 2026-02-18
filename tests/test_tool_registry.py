from tools.toolcalls import tool_registry


def test_tool_registry_has_calculator() -> None:
    assert "calculator" in tool_registry.TOOLS
    assert callable(tool_registry.TOOLS["calculator"])


def test_tool_registry_calculator_wrapper() -> None:
    result = tool_registry.TOOLS["calculator"]({"expression": "6 * 7"})
    assert result == "42"


def test_tool_definitions_include_calculator() -> None:
    names = [item["function"]["name"] for item in tool_registry.TOOL_DEFINITIONS]
    assert "calculator" in names
