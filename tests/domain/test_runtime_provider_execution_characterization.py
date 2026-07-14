from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderAdapter,
    ProviderCatalogSnapshot,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ProviderCallRecord, UsageMeterEvent
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService
from tests.conftest import seed_site_auth

SITE_ID = "site_provider_characterization"


class RecordingProviderAdapter:
    adapter_type = "characterization"

    def __init__(
        self,
        *,
        provider_id: str,
        model_id: str,
        instance_id: str,
        tier: str,
        outcomes: list[dict[str, object]],
        attempt_ledger: list[dict[str, object]] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = f"Characterization {provider_id}"
        self.model_id = model_id
        self.instance_id = instance_id
        self.tier = tier
        self.outcomes = outcomes
        self.attempts: list[dict[str, object]] = []
        self.attempt_ledger = attempt_ledger

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id=self.model_id,
                    family="characterization-text",
                    feature="text",
                    status="available",
                    price_input=0.01,
                    price_output=0.02,
                    fallback_candidate=True,
                    instances=[
                        CatalogInstanceSeed(
                            instance_id=self.instance_id,
                            endpoint_variant="characterization",
                            region="test-region",
                            capability_tags=["text", self.tier],
                            is_default=self.tier == "balanced",
                            weight=100,
                        )
                    ],
                )
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        attempt = {
            "provider_id": self.provider_id,
            "model_id": request.model_id,
            "instance_id": request.instance_id,
            "retry_count": request.retry_count,
        }
        self.attempts.append(attempt)
        if self.attempt_ledger is not None:
            self.attempt_ledger.append(dict(attempt))
        outcome_index = len(self.attempts) - 1
        if outcome_index >= len(self.outcomes):
            raise AssertionError(
                f"unexpected attempt {outcome_index} for provider {self.provider_id}"
            )
        outcome = self.outcomes[outcome_index]
        error_code = str(outcome.get("error_code") or "")
        if error_code:
            raise ProviderExecutionError(
                error_code,
                str(outcome.get("error_message") or error_code),
                retryable=(bool(outcome["retryable"]) if "retryable" in outcome else None),
                tokens_in=int(outcome.get("tokens_in") or 0),
                tokens_out=int(outcome.get("tokens_out") or 0),
                cost=float(outcome.get("cost") or 0.0),
            )

        output = outcome.get("output")
        if not isinstance(output, dict):
            raise AssertionError("successful characterization outcome requires output")
        return ProviderExecutionResult(
            output=dict(output),
            latency_ms=int(outcome.get("latency_ms") or 0),
            tokens_in=int(outcome.get("tokens_in") or 0),
            tokens_out=int(outcome.get("tokens_out") or 0),
            cost=float(outcome.get("cost") or 0.0),
        )


@dataclass(frozen=True, slots=True)
class RuntimeHarness:
    database_url: str
    service: RuntimeService


@contextmanager
def runtime_harness(
    tmp_path: Path,
    adapters: list[RecordingProviderAdapter],
) -> Iterator[RuntimeHarness]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'provider-execution.sqlite3'}"
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
    )
    providers: dict[str, ProviderAdapter] = {adapter.provider_id: adapter for adapter in adapters}
    init_schema(database_url)
    CatalogService(
        database_url,
        providers=providers,
        settings=settings,
    ).refresh_catalog()
    seed_site_auth(database_url, site_id=SITE_ID)
    try:
        yield RuntimeHarness(
            database_url=database_url,
            service=RuntimeService(
                database_url,
                settings=settings,
                providers=providers,
            ),
        )
    finally:
        dispose_engine(database_url)


def runtime_request(
    *,
    idempotency_key: str,
    allow_fallback: bool,
    retry_max: int,
    ability_family: str = "text",
    ability_name: str = "npcink-abilities-toolkit/inspect-site-health",
    input_payload: dict[str, Any] | None = None,
) -> RuntimeRequest:
    return RuntimeRequest(
        site_id=SITE_ID,
        ability_name=ability_name,
        ability_family=ability_family,
        channel="openapi",
        execution_kind="text",
        profile_id="text.balanced",
        input_payload=input_payload
        or {"messages": [{"role": "user", "content": "characterize provider execution"}]},
        idempotency_key=idempotency_key,
        trace_id=f"trace-{idempotency_key}",
        retry_max=retry_max,
        policy={"allow_fallback": allow_fallback},
    )


def test_retryable_candidate_recovers_on_same_instance_with_complete_evidence(
    tmp_path: Path,
) -> None:
    attempt_ledger: list[dict[str, object]] = []
    recovered_output = {
        "output_text": "recovered on the same provider candidate",
        "messages": [
            {
                "role": "assistant",
                "content": "recovered on the same provider candidate",
            }
        ],
        "provider_metadata": {"attempt": 2},
    }
    primary = RecordingProviderAdapter(
        provider_id="provider_primary",
        model_id="model_primary",
        instance_id="instance_primary_balanced",
        tier="balanced",
        attempt_ledger=attempt_ledger,
        outcomes=[
            {
                "error_code": "provider.rate_limited",
                "error_message": "retry the same candidate",
                "tokens_in": 11,
                "cost": 0.12,
            },
            {
                "output": recovered_output,
                "latency_ms": 47,
                "tokens_in": 8,
                "tokens_out": 5,
                "cost": 0.34,
            },
        ],
    )

    with runtime_harness(tmp_path, [primary]) as harness:
        response = harness.service.execute(
            runtime_request(
                idempotency_key="provider-retry-success-001",
                allow_fallback=True,
                retry_max=1,
                ability_family="openclaw",
                input_payload={
                    "messages": [{"role": "user", "content": "inspect runtime health"}],
                    "correlation_id": "correlation-provider-retry-001",
                },
            )
        )

        assert attempt_ledger == [
            {
                "provider_id": "provider_primary",
                "model_id": "model_primary",
                "instance_id": "instance_primary_balanced",
                "retry_count": 0,
            },
            {
                "provider_id": "provider_primary",
                "model_id": "model_primary",
                "instance_id": "instance_primary_balanced",
                "retry_count": 1,
            },
        ]
        assert response.status == "succeeded"
        assert (
            response.provider_id,
            response.model_id,
            response.instance_id,
        ) == ("provider_primary", "model_primary", "instance_primary_balanced")
        assert response.fallback_used is False
        assert response.provider_call_count == 2
        assert response.retryable is False
        assert response.retry_exhausted is False
        assert response.result == {
            "analysis_type": "report",
            "summary": "recovered on the same provider candidate",
            "findings": [],
            "recommendations": [],
            "requires_local_approval": False,
            "proposal_handoff": {
                "correlation_id": "correlation-provider-retry-001",
            },
            "_cloud_raw_result": recovered_output,
        }

        run = harness.service.get_run(response.run_id, site_id=SITE_ID)
        result = harness.service.get_run_result(response.run_id, site_id=SITE_ID)
        assert run["status"] == "succeeded"
        assert run["provider_call_count"] == 2
        assert run["fallback_used"] is False
        assert result["result"] == response.result
        assert result["provider_calls"] == [
            {
                "provider_id": "provider_primary",
                "model_id": "model_primary",
                "instance_id": "instance_primary_balanced",
                "region": "test-region",
                "latency_ms": 0,
                "tokens_in": 11,
                "tokens_out": 0,
                "cost": 0.12,
                "retry_count": 0,
                "fallback_used": False,
                "error_code": "provider.rate_limited",
                "error_stage": "provider",
                "retryable": True,
            },
            {
                "provider_id": "provider_primary",
                "model_id": "model_primary",
                "instance_id": "instance_primary_balanced",
                "region": "test-region",
                "latency_ms": 47,
                "tokens_in": 8,
                "tokens_out": 5,
                "cost": 0.34,
                "retry_count": 1,
                "fallback_used": False,
                "error_code": None,
                "error_stage": "",
                "retryable": False,
            },
        ]


def test_fallback_eligible_error_moves_to_next_candidate_without_losing_result(
    tmp_path: Path,
) -> None:
    attempt_ledger: list[dict[str, object]] = []
    fallback_output = {
        "output_text": "fallback candidate result",
        "messages": [{"role": "assistant", "content": "fallback candidate result"}],
        "result_marker": "preserved",
    }
    primary = RecordingProviderAdapter(
        provider_id="provider_primary",
        model_id="model_primary",
        instance_id="instance_primary_balanced",
        tier="balanced",
        attempt_ledger=attempt_ledger,
        outcomes=[
            {
                "error_code": "provider.upstream_unavailable",
                "error_message": "primary unavailable",
                "tokens_in": 4,
                "cost": 0.08,
            }
        ],
    )
    fallback = RecordingProviderAdapter(
        provider_id="provider_fallback",
        model_id="model_fallback",
        instance_id="instance_fallback_economy",
        tier="economy",
        attempt_ledger=attempt_ledger,
        outcomes=[
            {
                "output": fallback_output,
                "latency_ms": 61,
                "tokens_in": 7,
                "tokens_out": 6,
                "cost": 0.27,
            }
        ],
    )

    with runtime_harness(tmp_path, [primary, fallback]) as harness:
        response = harness.service.execute(
            runtime_request(
                idempotency_key="provider-fallback-success-001",
                allow_fallback=True,
                retry_max=0,
            )
        )

        assert attempt_ledger == [
            {
                "provider_id": "provider_primary",
                "model_id": "model_primary",
                "instance_id": "instance_primary_balanced",
                "retry_count": 0,
            },
            {
                "provider_id": "provider_fallback",
                "model_id": "model_fallback",
                "instance_id": "instance_fallback_economy",
                "retry_count": 0,
            },
        ]
        assert response.status == "succeeded"
        assert (
            response.provider_id,
            response.model_id,
            response.instance_id,
        ) == ("provider_fallback", "model_fallback", "instance_fallback_economy")
        assert response.fallback_used is True
        assert response.provider_call_count == 2
        assert response.result == fallback_output

        run = harness.service.get_run(response.run_id, site_id=SITE_ID)
        result = harness.service.get_run_result(response.run_id, site_id=SITE_ID)
        assert run["fallback_used"] is True
        assert result["result"] == fallback_output
        assert [
            (
                call["provider_id"],
                call["error_code"],
                call["error_stage"],
                call["retryable"],
                call["fallback_used"],
            )
            for call in result["provider_calls"]
        ] == [
            (
                "provider_primary",
                "provider.upstream_unavailable",
                "provider",
                True,
                False,
            ),
            ("provider_fallback", None, "", False, True),
        ]
        assert result["provider_calls"][1] == {
            "provider_id": "provider_fallback",
            "model_id": "model_fallback",
            "instance_id": "instance_fallback_economy",
            "region": "test-region",
            "latency_ms": 61,
            "tokens_in": 7,
            "tokens_out": 6,
            "cost": 0.27,
            "retry_count": 0,
            "fallback_used": True,
            "error_code": None,
            "error_stage": "",
            "retryable": False,
        }


def test_non_fallbackable_error_stops_immediately_and_preserves_usage_evidence(
    tmp_path: Path,
) -> None:
    primary = RecordingProviderAdapter(
        provider_id="provider_primary",
        model_id="model_primary",
        instance_id="instance_primary_balanced",
        tier="balanced",
        outcomes=[
            {
                "error_code": "provider.invalid_request",
                "error_message": "invalid provider payload",
                "retryable": False,
                "tokens_in": 19,
                "tokens_out": 3,
                "cost": 0.91,
            }
        ],
    )
    fallback = RecordingProviderAdapter(
        provider_id="provider_fallback",
        model_id="model_fallback",
        instance_id="instance_fallback_economy",
        tier="economy",
        outcomes=[
            {
                "output": {"output_text": "must not execute"},
                "latency_ms": 10,
                "tokens_in": 1,
                "tokens_out": 1,
                "cost": 0.01,
            }
        ],
    )

    with runtime_harness(tmp_path, [primary, fallback]) as harness:
        response = harness.service.execute(
            runtime_request(
                idempotency_key="provider-non-fallbackable-001",
                allow_fallback=True,
                retry_max=2,
            )
        )

        assert [attempt["retry_count"] for attempt in primary.attempts] == [0]
        assert fallback.attempts == []
        assert response.status == "failed"
        assert response.error_code == "provider.invalid_request"
        assert response.error_message == "invalid provider payload"
        assert response.error_stage == "provider"
        assert response.retryable is False
        assert response.retry_exhausted is False
        assert response.provider_call_count == 1
        assert (
            response.provider_id,
            response.model_id,
            response.instance_id,
        ) == ("provider_primary", "model_primary", "instance_primary_balanced")

        run = harness.service.get_run(response.run_id, site_id=SITE_ID)
        assert run["status"] == "failed"
        assert run["error_code"] == "provider.invalid_request"
        assert run["error_message"] == "invalid provider payload"
        assert run["error_stage"] == "provider"
        assert run["retryable"] is False
        assert run["retry_exhausted"] is False

        with get_session(harness.database_url) as session:
            provider_calls = list(
                session.scalars(
                    select(ProviderCallRecord)
                    .where(ProviderCallRecord.run_id == response.run_id)
                    .order_by(ProviderCallRecord.id.asc())
                )
            )
            meter_events = list(
                session.scalars(
                    select(UsageMeterEvent)
                    .where(UsageMeterEvent.run_id == response.run_id)
                    .order_by(UsageMeterEvent.id.asc())
                )
            )

        assert len(provider_calls) == 1
        assert (
            provider_calls[0].provider_id,
            provider_calls[0].tokens_in,
            provider_calls[0].tokens_out,
            provider_calls[0].cost,
            provider_calls[0].retry_count,
            provider_calls[0].fallback_used,
            provider_calls[0].error_code,
        ) == (
            "provider_primary",
            19,
            3,
            0.91,
            0,
            False,
            "provider.invalid_request",
        )
        assert [(event.meter_key, event.quantity) for event in meter_events] == [
            ("runs", 1.0),
            ("provider_calls", 1.0),
            ("tokens_in", 19.0),
            ("tokens_out", 3.0),
            ("tokens_total", 22.0),
            ("cost", 0.91),
        ]


def test_retryable_error_marks_exhaustion_after_the_configured_last_attempt(
    tmp_path: Path,
) -> None:
    primary = RecordingProviderAdapter(
        provider_id="provider_primary",
        model_id="model_primary",
        instance_id="instance_primary_balanced",
        tier="balanced",
        outcomes=[
            {
                "error_code": "provider.rate_limited",
                "error_message": f"rate limited attempt {attempt}",
            }
            for attempt in range(1, 4)
        ],
    )

    with runtime_harness(tmp_path, [primary]) as harness:
        response = harness.service.execute(
            runtime_request(
                idempotency_key="provider-retry-exhausted-001",
                allow_fallback=False,
                retry_max=2,
            )
        )

        assert [attempt["retry_count"] for attempt in primary.attempts] == [0, 1, 2]
        assert response.status == "failed"
        assert response.error_code == "provider.rate_limited"
        assert response.error_message == "rate limited attempt 3"
        assert response.error_stage == "provider"
        assert response.retryable is True
        assert response.retry_exhausted is True
        assert response.provider_call_count == 3
        run = harness.service.get_run(response.run_id, site_id=SITE_ID)
        assert run["retryable"] is True
        assert run["retry_exhausted"] is True
        assert run["provider_call_count"] == 3
