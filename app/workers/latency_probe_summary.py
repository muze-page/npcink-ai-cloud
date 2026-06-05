from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.adapters.repositories.stats_repository import StatsRepository
from app.core.config import Settings, get_settings
from app.core.db import get_session, require_database_connection
from app.core.logging import configure_logging, get_logger
from app.core.models import SITE_STATUS_ACTIVE, ProviderCallRecord
from app.domain.usage.rollup import UsageRollupService


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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


def _collect_recent_instance_ids(
    provider_calls: list[ProviderCallRecord],
    *,
    since_at: datetime,
    limit: int,
) -> list[str]:
    recent_ids: list[str] = []
    seen: set[str] = set()
    for provider_call in reversed(provider_calls):
        created_at = _normalize_datetime(provider_call.created_at)
        if created_at is None or created_at < since_at:
            continue
        instance_id = str(provider_call.instance_id or "").strip()
        if not instance_id or instance_id in seen:
            continue
        recent_ids.append(instance_id)
        seen.add(instance_id)
        if len(recent_ids) >= limit:
            break
    return recent_ids


def run_once(
    settings: Settings,
    *,
    now_factory: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    factory = now_factory or (lambda: datetime.now(UTC))
    now = factory()
    since_at = now.astimezone(UTC) - timedelta(
        minutes=settings.latency_probe_worker_recent_minutes
    )

    with get_session(settings.database_url) as session:
        sites = CommercialRepository(session).list_sites(
            status=SITE_STATUS_ACTIVE,
            limit=settings.latency_probe_worker_site_limit,
        )
        stats_repository = StatsRepository(session)
        recent_instance_ids_by_site = {
            site.site_id: _collect_recent_instance_ids(
                stats_repository.list_provider_calls(site.site_id),
                since_at=since_at,
                limit=settings.latency_probe_worker_instance_limit,
            )
            for site in sites
        }

    rollup_service = UsageRollupService(settings.database_url, now_factory=lambda: now)
    sink_result = rollup_service.store_latency_probe_batches(
        site_instances=recent_instance_ids_by_site,
        start_at=since_at,
        end_at=now.astimezone(UTC),
    )
    site_batches = _dict_items(sink_result.get("site_batches"))

    return {
        "source": "cloud_latency_probe_worker",
        "generated_at": now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "window": {
            "start_gmt": since_at.strftime("%Y-%m-%d %H:%M:%S"),
            "end_gmt": now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        },
        "recent_minutes": settings.latency_probe_worker_recent_minutes,
        "site_limit": settings.latency_probe_worker_site_limit,
        "instance_limit": settings.latency_probe_worker_instance_limit,
        "sites_total": len(site_batches),
        "stored_batches_total": _coerce_int(sink_result.get("stored_batches_total")),
        "delivery_owner": str(sink_result.get("delivery_owner") or ""),
        "rollup_scope_kind": str(sink_result.get("scope_kind") or ""),
        "instances_total": _coerce_int(sink_result.get("instances_total")),
        "ready_total": _coerce_int(sink_result.get("ready_total")),
        "healthy_total": _coerce_int(sink_result.get("healthy_total")),
        "site_batches": site_batches,
    }


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    require_database_connection(settings.database_url)

    result = run_once(settings)
    get_logger("magick_ai_cloud.latency_probe_summary").info(
        "latency probe summary cadence generated: %s",
        result,
    )


if __name__ == "__main__":
    main()
