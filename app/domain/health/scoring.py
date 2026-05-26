from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.models import ProviderCallRecord


@dataclass(slots=True)
class HealthAssessment:
    status: str
    score: float
    reason: str
    calls_total: int
    success_rate: float
    timeout_rate: float
    avg_latency_ms: int


def assess_instance_health(
    provider_calls: list[ProviderCallRecord],
    *,
    now: datetime,
    window_hours: int = 24,
) -> HealthAssessment:
    window_start = _normalize_datetime(now) - timedelta(hours=window_hours)
    scoped_calls = [
        call
        for call in provider_calls
        if window_start <= _normalize_datetime(call.created_at) <= _normalize_datetime(now)
    ]

    if not scoped_calls:
        return HealthAssessment(
            status="healthy",
            score=1.0,
            reason="no recent provider calls observed",
            calls_total=0,
            success_rate=1.0,
            timeout_rate=0.0,
            avg_latency_ms=0,
        )

    calls_total = len(scoped_calls)
    success_total = sum(1 for call in scoped_calls if not call.error_code)
    timeout_total = sum(1 for call in scoped_calls if call.error_code == "provider.timeout")
    success_rate = round(success_total / calls_total, 4)
    timeout_rate = round(timeout_total / calls_total, 4)
    avg_latency_ms = int(round(sum(call.latency_ms for call in scoped_calls) / calls_total))

    score = success_rate
    if timeout_total > 0:
        score -= min(0.25, timeout_rate * 0.25)
    if avg_latency_ms > 1500:
        score -= 0.1
    score = round(max(0.0, min(1.0, score)), 4)
    sample_adjusted = False

    if calls_total < 3 and score < 0.5:
        score = 0.5
        sample_adjusted = True

    if score >= 0.85:
        status = "healthy"
    elif score >= 0.5:
        status = "degraded"
    else:
        status = "unhealthy"

    return HealthAssessment(
        status=status,
        score=score,
        reason=(
            "recent calls="
            f"{calls_total}; success_rate={success_rate:.4f}; "
            f"timeout_rate={timeout_rate:.4f}; avg_latency_ms={avg_latency_ms}; "
            f"sample_adjusted={'true' if sample_adjusted else 'false'}"
        ),
        calls_total=calls_total,
        success_rate=success_rate,
        timeout_rate=timeout_rate,
        avg_latency_ms=avg_latency_ms,
    )


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
