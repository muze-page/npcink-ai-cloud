from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.error_taxonomy import get_error_taxonomy


@dataclass(slots=True)
class CatalogInstanceSeed:
    instance_id: str
    endpoint_variant: str
    region: str
    capability_tags: list[str] = field(default_factory=list)
    health_status: str = "healthy"
    is_default: bool = False
    weight: int = 100


@dataclass(slots=True)
class CatalogModelSeed:
    model_id: str
    family: str
    feature: str
    status: str
    context_window: int | None = None
    price_input: float | None = None
    price_output: float | None = None
    is_deprecated: bool = False
    fallback_candidate: bool = False
    raw_json: dict[str, object] | None = None
    instances: list[CatalogInstanceSeed] = field(default_factory=list)


@dataclass(slots=True)
class ProviderCatalogSnapshot:
    provider_id: str
    display_name: str
    adapter_type: str
    models: list[CatalogModelSeed]


@dataclass(slots=True)
class ProviderExecutionRequest:
    run_id: str
    site_id: str
    ability_name: str
    profile_id: str
    execution_kind: str
    model_id: str
    instance_id: str
    endpoint_variant: str
    trace_id: str
    input_payload: dict[str, Any]
    policy: dict[str, Any]
    timeout_ms: int
    price_input: float | None = None
    price_output: float | None = None
    retry_count: int = 0


@dataclass(slots=True)
class ProviderExecutionResult:
    output: dict[str, Any]
    latency_ms: int
    tokens_in: int
    tokens_out: int
    cost: float
    finish_reason: str = "stop"


class ProviderExecutionError(Exception):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.retryable = (
            get_error_taxonomy(error_code).retryable
            if retryable is None
            else retryable
        )
        self.tokens_in = max(0, int(tokens_in))
        self.tokens_out = max(0, int(tokens_out))
        self.cost = max(0.0, float(cost))


class ProviderAdapter(Protocol):
    provider_id: str
    display_name: str
    adapter_type: str

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        ...

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        ...
