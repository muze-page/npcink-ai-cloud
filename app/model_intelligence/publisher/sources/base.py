from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class PublisherSource(Protocol):
    id: str

    def fetch_bundle(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class SourceClientOptions:
    transport: httpx.BaseTransport | None = None
