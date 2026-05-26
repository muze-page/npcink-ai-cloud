from __future__ import annotations

from typing import Protocol


class RuntimeQueue(Protocol):
    def publish(self, run_id: str) -> None:
        ...

    def consume(self, timeout_seconds: int) -> str | None:
        ...


class RuntimeQueueError(RuntimeError):
    pass
