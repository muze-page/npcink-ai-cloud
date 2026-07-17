from __future__ import annotations

import logging

_SENSITIVE_HTTP_LOGGERS = ("httpx", "httpcore")


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    resolved_level = getattr(logging, level.upper(), logging.INFO)

    # HTTP client INFO/DEBUG records include complete request URLs. Provider
    # asset URLs may carry short-lived signatures in their query string, so
    # dependency request logging must stay below the application log surface.
    for logger_name in _SENSITIVE_HTTP_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    if root_logger.handlers:
        root_logger.setLevel(resolved_level)
        return

    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
