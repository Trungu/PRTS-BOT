from utils import command_registry


def test_register_and_is_known_exact_and_prefix() -> None:
    command_registry._KNOWN.clear()

    command_registry.register("hello", "clear history")

    assert command_registry.is_known("hello")
    assert command_registry.is_known("clear history all")
    assert not command_registry.is_known("unknown")


def test_register_normalizes_case_and_spaces() -> None:
    command_registry._KNOWN.clear()

    command_registry.register("  HeLLo  ")

    assert command_registry.is_known("hello")
    assert command_registry.is_known("HELLO")
