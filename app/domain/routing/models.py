from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RoutingCandidate:
    provider_id: str
    model_id: str
    instance_id: str
    endpoint_variant: str
    region: str
    weight: int
    health_status: str
    price_input: float | None = None
    price_output: float | None = None
    capability_tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RoutingResolution:
    profile_id: str
    execution_kind: str
    revision: str
    default_policy: dict[str, Any]
    selection_policy: dict[str, Any]
    candidates: list[RoutingCandidate] = field(default_factory=list)

    @property
    def selected_candidate(self) -> RoutingCandidate:
        return self.candidates[0]
