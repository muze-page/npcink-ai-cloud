from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class RuntimeCallbackDispatchRequest:
    run_id: str
    trace_id: str
    callback_url: str
    payload: dict[str, Any]
    site_id: str = ""
    event: str = "runtime.run.terminal"
    key_id: str = ""
    secret: str = field(default="", repr=False)
    callback_id: str = ""
    timestamp: str = ""
    traceparent: str = ""


@dataclass(slots=True)
class RuntimeCallbackDispatchResult:
    status_code: int


class RuntimeCallbackDispatchError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int = 0,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


class RuntimeCallbackDispatcher(Protocol):
    def dispatch(
        self,
        request: RuntimeCallbackDispatchRequest,
    ) -> RuntimeCallbackDispatchResult: ...
