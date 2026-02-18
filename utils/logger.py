#utils/logger.py
import sys
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


# --- Output handlers ---
# Each handler is a callable: (message: str) -> None
# Add or replace handlers here in the future to support file output, etc.

def _terminal_handler(message: str) -> None:
    print(message, file=sys.stdout, flush=True)


_handlers: list = [_terminal_handler]


def log(
    message: str,
    level: LogLevel = LogLevel.INFO,
    *,
    timestamp: bool = True,
) -> None:
    """Log a message to all registered output handlers.

    Args:
        message:   The message to log.
        level:     Severity level (DEBUG, INFO, WARNING, ERROR).
        timestamp: Whether to prepend a UTC timestamp.
    """
    ts = f"[{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}] " if timestamp else ""
    formatted = f"{ts}[{level.value}] {message}"

    for handler in _handlers:
        handler(formatted)


def add_handler(handler) -> None:
    """Register an additional output handler (e.g. a file writer)."""
    _handlers.append(handler)


def remove_handler(handler) -> None:
    """Remove a previously registered output handler."""
    _handlers.remove(handler)
