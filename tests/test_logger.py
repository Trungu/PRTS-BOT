from utils import logger


def test_log_calls_registered_handlers() -> None:
    captured = []

    def handler(message: str) -> None:
        captured.append(message)

    logger.add_handler(handler)
    try:
        logger.log("hello", level=logger.LogLevel.WARNING, timestamp=False)
    finally:
        logger.remove_handler(handler)

    assert captured
    assert captured[0] == "[WARNING] hello"


def test_remove_handler_stops_calls() -> None:
    captured = []

    def handler(message: str) -> None:
        captured.append(message)

    logger.add_handler(handler)
    logger.remove_handler(handler)

    logger.log("msg", timestamp=False)

    assert captured == []
