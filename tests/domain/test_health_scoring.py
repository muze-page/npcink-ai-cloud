from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.models import ProviderCallRecord
from app.domain.health.scoring import assess_instance_health


def _provider_call(
    *,
    created_at: datetime,
    latency_ms: int,
    error_code: str | None = None,
) -> ProviderCallRecord:
    return ProviderCallRecord(
        run_id="run_test",
        provider_id="openai",
        model_id="gpt-4.1-mini",
        instance_id="openai-us-east-text-balanced",
        region="us-east",
        latency_ms=latency_ms,
        tokens_in=1,
        tokens_out=1,
        cost=0.0,
        retry_count=0,
        fallback_used=False,
        error_code=error_code,
        created_at=created_at,
    )


def test_assess_instance_health_returns_healthy_when_no_recent_calls() -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    assessment = assess_instance_health([], now=now)

    assert assessment.status == "healthy"
    assert assessment.score == 1.0
    assert assessment.calls_total == 0


def test_assess_instance_health_returns_degraded_for_mixed_success_and_failure() -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    calls = [
        _provider_call(created_at=now - timedelta(minutes=20), latency_ms=80),
        _provider_call(
            created_at=now - timedelta(minutes=10),
            latency_ms=100,
            error_code="provider.upstream_error",
        ),
    ]

    assessment = assess_instance_health(calls, now=now)

    assert assessment.status == "degraded"
    assert assessment.score == 0.5
    assert assessment.calls_total == 2


def test_assess_instance_health_returns_unhealthy_for_repeated_timeouts() -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    calls = [
        _provider_call(
            created_at=now - timedelta(minutes=20),
            latency_ms=2000,
            error_code="provider.timeout",
        ),
        _provider_call(
            created_at=now - timedelta(minutes=10),
            latency_ms=2200,
            error_code="provider.timeout",
        ),
        _provider_call(
            created_at=now - timedelta(minutes=5),
            latency_ms=2100,
            error_code="provider.timeout",
        ),
    ]

    assessment = assess_instance_health(calls, now=now)

    assert assessment.status == "unhealthy"
    assert assessment.score == 0.0
    assert assessment.timeout_rate == 1.0


def test_assess_instance_health_keeps_small_failure_sample_degraded() -> None:
    now = datetime(2026, 3, 12, 8, 0, tzinfo=UTC)
    calls = [
        _provider_call(
            created_at=now - timedelta(minutes=20),
            latency_ms=2000,
            error_code="provider.timeout",
        ),
        _provider_call(
            created_at=now - timedelta(minutes=10),
            latency_ms=2200,
            error_code="provider.timeout",
        ),
    ]

    assessment = assess_instance_health(calls, now=now)

    assert assessment.status == "degraded"
    assert assessment.score == 0.5
    assert assessment.timeout_rate == 1.0
