from tools.toolcalls import tool_registry
import pytest


def test_tool_registry_has_calculator() -> None:
    assert "calculator" in tool_registry.TOOLS
    assert callable(tool_registry.TOOLS["calculator"])


def test_tool_registry_calculator_wrapper() -> None:
    result = tool_registry.TOOLS["calculator"]({"expression": "6 * 7"})
    assert result == "42"


def test_tool_definitions_include_calculator() -> None:
    names = [item["function"]["name"] for item in tool_registry.TOOL_DEFINITIONS]
    assert "calculator" in names


def test_tool_registry_has_send_crisis_response() -> None:
    assert "send_crisis_response" in tool_registry.TOOLS
    assert callable(tool_registry.TOOLS["send_crisis_response"])


def test_tool_registry_has_send_pr_deflection() -> None:
    assert "send_pr_deflection" in tool_registry.TOOLS
    assert callable(tool_registry.TOOLS["send_pr_deflection"])


def test_tool_definitions_include_crisis_and_pr() -> None:
    names = [item["function"]["name"] for item in tool_registry.TOOL_DEFINITIONS]
    assert "send_crisis_response" in names
    assert "send_pr_deflection" in names


def test_send_crisis_response_wrapper_callable() -> None:
    """The registry wrapper calls send_crisis_response with no args."""
    result = tool_registry.TOOLS["send_crisis_response"]({})
    assert "__safety_response__" in result


def test_send_pr_deflection_wrapper_callable() -> None:
    """The registry wrapper passes the topic argument through."""
    result = tool_registry.TOOLS["send_pr_deflection"]({"topic": "communist Russia"})
    assert "__safety_response__" in result
    assert "communist Russia" in result


def test_normalize_and_validate_attendees_valid_and_deduped() -> None:
    out = tool_registry._normalize_and_validate_attendees(
        [" Alice@example.com ", "alice@example.com", "bob@example.org"]
    )
    assert out == ["alice@example.com", "bob@example.org"]


def test_normalize_and_validate_attendees_invalid_raises() -> None:
    with pytest.raises(ValueError):
        tool_registry._normalize_and_validate_attendees(
            ["not-an-email", "ok@example.com"]
        )
