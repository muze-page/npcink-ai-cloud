from __future__ import annotations

from collections import deque


class InMemoryRuntimeQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()

    def publish(self, run_id: str) -> None:
        self._items.append(run_id)

    def consume(self, timeout_seconds: int) -> str | None:
        del timeout_seconds
        if not self._items:
            return None
        return self._items.popleft()
