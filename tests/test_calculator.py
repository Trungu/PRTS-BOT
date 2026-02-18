from tools.toolcalls.calculator import calculator


def test_calculator_basic_math() -> None:
    assert calculator("2 + 2") == "4"
    assert calculator("sqrt(9)") == "3"


def test_calculator_float_integer_formatting() -> None:
    assert calculator("4.0") == "4"


def test_calculator_division_by_zero() -> None:
    assert calculator("1 / 0") == "Error: division by zero"


def test_calculator_rejects_unsafe_name() -> None:
    result = calculator("__import__('os').system('echo nope')")
    assert result.startswith("Error:")
    assert "Unknown name" in result or "Forbidden operation" in result


def test_calculator_handles_syntax_error() -> None:
    assert calculator("2 +").startswith("Error:")
