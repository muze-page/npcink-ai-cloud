from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.config import Settings, get_settings
from app.core.db import get_session, require_database_connection
from app.core.logging import configure_logging, get_logger
from app.core.models import SITE_STATUS_ACTIVE
from app.domain.usage.rollup import UsageRollupService


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _dict_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [
        {str(key): item for key, item in candidate.items()}
        for candidate in value
        if isinstance(candidate, dict)
    ]


def run_once(
    settings: Settings,
    *,
    now_factory: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    factory = now_factory or (lambda: datetime.now(UTC))
    now = factory()

    with get_session(settings.database_url) as session:
        sites = CommercialRepository(session).list_sites(
            status=SITE_STATUS_ACTIVE,
            limit=settings.alert_worker_site_limit,
        )

    rollup_service = UsageRollupService(settings.database_url, now_factory=lambda: now)
    sink_result = rollup_service.store_alert_provider_degradation_batches(
        site_ids=[site.site_id for site in sites],
        window_minutes=settings.alert_worker_window_minutes,
        min_requests=settings.alert_worker_min_requests,
        error_rate_threshold=settings.alert_worker_error_rate_threshold,
        latency_ms_threshold=settings.alert_worker_latency_ms_threshold,
    )
    site_batches = _dict_items(sink_result.get("site_batches"))

    return {
        "source": "cloud_alert_provider_degradation_worker",
        "generated_at": now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "window_minutes": settings.alert_worker_window_minutes,
        "site_limit": settings.alert_worker_site_limit,
        "min_requests": settings.alert_worker_min_requests,
        "error_rate_threshold": settings.alert_worker_error_rate_threshold,
        "latency_ms_threshold": settings.alert_worker_latency_ms_threshold,
        "sites_total": len(site_batches),
        "stored_batches_total": _coerce_int(sink_result.get("stored_batches_total")),
        "delivery_owner": str(sink_result.get("delivery_owner") or ""),
        "rollup_scope_kind": str(sink_result.get("scope_kind") or ""),
        "events_total": _coerce_int(sink_result.get("events_total")),
        "site_batches": site_batches,
    }


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    require_database_connection(settings.database_url)

    result = run_once(settings)
    get_logger("npcink_ai_cloud.alert_provider_degradation").info(
        "alert provider degradation cadence generated: %s",
        result,
    )


if __name__ == "__main__":
    main()
