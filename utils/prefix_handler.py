#utils/prefix_handler.py
from settings import BOT_PREFIX, PREFIX_SMART_CHARS, PREFIX_CASE_SENSITIVE


def _build_prefix_variants(prefix: str, smart_chars: list[str], case_sensitive: bool) -> list[str]:
    """
    Build all valid prefix variants from the base prefix and smart punctuation/space characters.
    Each smart char is appended after the prefix (e.g. 'prts ', 'prts, ', 'prts. ').
    The bare prefix itself is also included.
    """
    base = prefix if case_sensitive else prefix.lower()

    # Always include bare prefix
    variants = [base]

    for char in smart_chars:
        # Each smart char forms: prefix + char + (optional trailing space already in char or not)
        variant = base + char
        if variant not in variants:
            variants.append(variant)

    # Sort longest-first so 'bot, ' is tried before bare 'bot'.
    # Without this, 'bot, hello' would match 'bot' first and pass
    # ', hello' to handlers instead of the intended 'hello'.
    return sorted(variants, key=len, reverse=True)


# Pre-build variants at import time so we don't recompute on every message
_VARIANTS = _build_prefix_variants(BOT_PREFIX, PREFIX_SMART_CHARS, PREFIX_CASE_SENSITIVE)


def get_command(content: str) -> str | None:
    """
    Given a message's content string, check whether it starts with any valid
    prefix variant and return the remaining command/text (stripped), or None
    if no prefix matched.
    """
    check = content if PREFIX_CASE_SENSITIVE else content.lower()

    for variant in _VARIANTS:
        if check.startswith(variant):
            # Slice off the matched prefix and strip leading whitespace
            command = content[len(variant):].lstrip()
            return command

    return None


def has_prefix(content: str) -> bool:
    """Return True if the message content starts with any valid prefix variant."""
    return get_command(content) is not None
