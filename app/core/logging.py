from __future__ import annotations

import logging
from threading import Lock
from typing import Any
from weakref import WeakSet

from app.core.redaction import (
    REDACTION_FAILED,
    redact_sensitive,
    redact_text,
    safe_exception_type,
)

_SENSITIVE_HTTP_LOGGERS = ("httpx", "httpcore")
_SERVER_LOGGERS = (
    "gunicorn",
    "gunicorn.access",
    "gunicorn.error",
    "uvicorn",
    "uvicorn.access",
    "uvicorn.error",
)
_UVICORN_ACCESS_MESSAGE = '%s - "%s %s HTTP/%s" %d'
_STANDARD_RECORD_ATTRIBUTES = frozenset(
    {
        *logging.makeLogRecord({}).__dict__,
        "asctime",
        "message",
    }
)


class _RedactedLogException(Exception):
    """Safe exception placeholder that carries no original message or traceback."""


class RedactingFilter(logging.Filter):
    _processed_records: WeakSet[logging.LogRecord] = WeakSet()
    _processed_records_lock = Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            with self._processed_records_lock:
                if record in self._processed_records:
                    return True
                self._processed_records.add(record)
            self._redact_record(record)
        except BaseException:
            self._fail_safe_record(record)
        return True

    def _redact_record(self, record: logging.LogRecord) -> None:
        is_uvicorn_access = self._redact_uvicorn_access_args(record)
        if not is_uvicorn_access:
            # Keep string format templates intact until their already-sanitized
            # arguments have been rendered. Redacting ``secret=%s`` first would
            # remove a placeholder and make ``LogRecord.getMessage`` fail closed.
            if not isinstance(record.msg, str):
                record.msg = redact_sensitive(record.msg)
            record.args = self._redact_args(record.args)
            try:
                rendered_message = record.getMessage()
            except BaseException:
                rendered_message = REDACTION_FAILED
            record.msg = redact_text(rendered_message)
            record.args = ()
        for key in tuple(record.__dict__):
            if key in _STANDARD_RECORD_ATTRIBUTES:
                continue
            record.__dict__[key] = redact_sensitive(record.__dict__[key], key=key)
        self._redact_exception(record)
        record.stack_info = None

    @staticmethod
    def _redact_uvicorn_access_args(record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
            return False
        if len(record.args) != 5 or record.msg != _UVICORN_ACCESS_MESSAGE:
            return False
        record.args = tuple(redact_sensitive(item) for item in record.args)
        return True

    @staticmethod
    def _redact_args(args: Any) -> Any:
        if isinstance(args, tuple):
            return tuple(redact_sensitive(item) for item in args)
        if isinstance(args, dict):
            redacted = redact_sensitive(args)
            return redacted if isinstance(redacted, dict) else {}
        if not args:
            return args
        return (redact_sensitive(args),)

    @staticmethod
    def _redact_exception(record: logging.LogRecord) -> None:
        if not record.exc_info:
            record.exc_text = None
            return
        error = record.exc_info[1] if len(record.exc_info) > 1 else record.exc_info[0]
        exception_type = safe_exception_type(error)
        record.exception_type = exception_type
        record.exc_info = (
            _RedactedLogException,
            _RedactedLogException(f"exception_type={exception_type}"),
            None,
        )
        record.exc_text = None

    @staticmethod
    def _fail_safe_record(record: logging.LogRecord) -> None:
        record.msg = REDACTION_FAILED
        record.args = ()
        record.exc_info = (
            _RedactedLogException,
            _RedactedLogException("exception_type=Exception"),
            None,
        )
        record.exc_text = None
        record.stack_info = None
        for key in tuple(record.__dict__):
            if key not in _STANDARD_RECORD_ATTRIBUTES:
                record.__dict__[key] = REDACTION_FAILED


_REDACTING_FILTER = RedactingFilter()


def _install_filter(target: logging.Filterer) -> None:
    if any(isinstance(item, RedactingFilter) for item in target.filters):
        return
    target.addFilter(_REDACTING_FILTER)


def _install_logger_filter(logger: logging.Logger) -> None:
    _install_filter(logger)
    for handler in logger.handlers:
        _install_filter(handler)


def _install_existing_logging_filters() -> None:
    root_logger = logging.getLogger()
    _install_logger_filter(root_logger)
    for logger_name in _SERVER_LOGGERS:
        _install_logger_filter(logging.getLogger(logger_name))
    for candidate in logging.Logger.manager.loggerDict.values():
        if isinstance(candidate, logging.Logger):
            _install_logger_filter(candidate)


def configure_logging(level: str) -> None:
    root_logger = logging.getLogger()
    resolved_level = getattr(logging, level.upper(), logging.INFO)

    # HTTP client INFO/DEBUG records include complete request URLs. Provider
    # asset URLs may carry short-lived signatures in their query string, so
    # dependency request logging must stay below the application log surface.
    for logger_name in _SENSITIVE_HTTP_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    if not root_logger.handlers:
        logging.basicConfig(
            level=resolved_level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    root_logger.setLevel(resolved_level)
    _install_existing_logging_filters()


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    _install_logger_filter(logger)
    return logger
