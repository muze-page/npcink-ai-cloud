from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import httpx

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.callback_security import validate_runtime_callback_target
from app.core.config import Settings, get_settings
from app.core.db import get_session, require_database_connection
from app.core.logging import configure_logging, get_logger
from app.core.models import SITE_STATUS_ACTIVE
from app.domain.usage.rollup import UsageRollupService

CALLBACK_ROUTE = "/npcink/open/v1/router/diagnostics/callback"
CALLBACK_EVENT = "router.diagnostics.batch"


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _dict_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _dict_items(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [
        {str(key): item for key, item in candidate.items()}
        for candidate in value
        if isinstance(candidate, dict)
    ]


def _build_trace_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _build_traceparent(trace_id: str) -> str:
    normalized = "".join(ch for ch in trace_id.lower() if ch in "0123456789abcdef")
    if len(normalized) != 32:
        normalized = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()[:32]
    parent_id = hashlib.sha256(f"{normalized}|parent".encode()).hexdigest()[:16]
    return f"00-{normalized}-{parent_id}-01"


def _callback_canonical(
    *,
    route: str,
    site_id: str,
    key_id: str,
    timestamp: str,
    event: str,
    callback_id: str,
    traceparent: str,
    raw_body: str,
) -> str:
    return "\n".join(
        [
            "POST",
            route,
            site_id,
            key_id,
            timestamp,
            event,
            callback_id,
            traceparent,
            hashlib.sha256(raw_body.encode("utf-8")).hexdigest(),
        ]
    )


def _build_callback_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/wp-json{CALLBACK_ROUTE}"


def _resolve_callback_config(site: Any) -> dict[str, str] | None:
    if site is None:
        return None
    metadata = _dict_value(getattr(site, "metadata_json", None))
    projection_callbacks = _dict_value(metadata.get("projection_callbacks"))
    diagnostics_callback = _dict_value(projection_callbacks.get("router_diagnostics"))

    enabled_raw = diagnostics_callback.get(
        "enabled", metadata.get("router_diagnostics_callback_enabled", True)
    )
    if enabled_raw in (False, 0, "0", "false", "False", "no", "off"):
        return None

    callback_url = str(
        diagnostics_callback.get("callback_url")
        or diagnostics_callback.get("url")
        or metadata.get("router_diagnostics_callback_url")
        or ""
    ).strip()
    public_base_url = str(metadata.get("public_base_url") or "").strip()
    if not callback_url and public_base_url:
        callback_url = _build_callback_url(public_base_url)

    key_id = str(
        diagnostics_callback.get("key_id")
        or metadata.get("router_diagnostics_callback_key_id")
        or ""
    ).strip()
    secret = str(
        diagnostics_callback.get("secret")
        or metadata.get("router_diagnostics_callback_secret")
        or ""
    ).strip()

    if not callback_url or not key_id or not secret:
        return None

    return {
        "callback_url": callback_url,
        "key_id": key_id,
        "secret": secret,
    }


def _dispatch_callback(
    *,
    callback_url: str,
    site_id: str,
    key_id: str,
    secret: str,
    payload: dict[str, Any],
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    validate_runtime_callback_target(callback_url)
    raw_body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    timestamp = str(int(datetime.now(UTC).timestamp()))
    callback_id = hashlib.sha256(
        f"{site_id}|{payload.get('generated_at', '')}|{payload.get('config_revision', '')}".encode()
    ).hexdigest()[:32]
    traceparent = _build_traceparent(_build_trace_id(f"{site_id}|{callback_id}|{CALLBACK_EVENT}"))
    canonical = _callback_canonical(
        route=CALLBACK_ROUTE,
        site_id=site_id,
        key_id=key_id,
        timestamp=timestamp,
        event=CALLBACK_EVENT,
        callback_id=callback_id,
        traceparent=traceparent,
        raw_body=raw_body,
    )
    signature = hmac.new(
        hashlib.sha256(secret.encode("utf-8")).hexdigest().encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers = {
        "content-type": "application/json",
        "X-Npcink-Site-Id": site_id,
        "X-Npcink-Key-Id": key_id,
        "X-Npcink-Timestamp": timestamp,
        "X-Npcink-Signature": signature,
        "X-Npcink-Cloud-Event": CALLBACK_EVENT,
        "X-Npcink-Callback-Id": callback_id,
        "traceparent": traceparent,
    }

    with httpx.Client(transport=transport, timeout=20.0) as client:
        response = client.post(callback_url, content=raw_body, headers=headers)
        response.raise_for_status()

    return {
        "status": "delivered",
        "callback_url": callback_url,
        "callback_id": callback_id,
        "event": CALLBACK_EVENT,
        "http_status": response.status_code,
    }


def run_once(
    settings: Settings,
    *,
    now_factory: Callable[[], datetime] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    factory = now_factory or (lambda: datetime.now(UTC))
    now = factory()

    with get_session(settings.database_url) as session:
        sites = CommercialRepository(session).list_sites(
            status=SITE_STATUS_ACTIVE,
            limit=settings.router_diagnostics_worker_site_limit,
        )

    rollup_service = UsageRollupService(settings.database_url, now_factory=lambda: now)
    sink_result = rollup_service.store_router_diagnostics_batches(
        site_ids=[site.site_id for site in sites],
        recent_minutes=settings.router_diagnostics_worker_recent_minutes,
        config_revision="cloud_runtime_summary_worker",
    )
    site_batches = _dict_items(sink_result.get("site_batches"))
    sites_by_id = {site.site_id: site for site in sites}
    callback_attempted_total = 0
    callback_delivered_total = 0
    callback_failed_total = 0
    callback_skipped_total = 0

    for site_batch in site_batches:
        site_id = str(site_batch.get("site_id") or "")
        callback_config = _resolve_callback_config(sites_by_id.get(site_id))
        if callback_config is None:
            site_batch["callback"] = {"status": "skipped"}
            callback_skipped_total += 1
            continue

        payload = rollup_service.get_router_diagnostics_batch(
            site_id=site_id,
            recent_minutes=settings.router_diagnostics_worker_recent_minutes,
        )
        if not payload:
            site_batch["callback"] = {"status": "failed", "error": "buffer_missing"}
            callback_attempted_total += 1
            callback_failed_total += 1
            continue

        callback_attempted_total += 1
        try:
            site_batch["callback"] = _dispatch_callback(
                callback_url=callback_config["callback_url"],
                site_id=site_id,
                key_id=callback_config["key_id"],
                secret=callback_config["secret"],
                payload=payload,
                transport=transport,
            )
            callback_delivered_total += 1
        except Exception as error:  # pragma: no cover - exercised via worker contract.
            site_batch["callback"] = {
                "status": "failed",
                "error": error.__class__.__name__,
                "message": str(error),
            }
            callback_failed_total += 1

    return {
        "source": "cloud_router_diagnostics_worker",
        "generated_at": now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "recent_minutes": settings.router_diagnostics_worker_recent_minutes,
        "site_limit": settings.router_diagnostics_worker_site_limit,
        "sites_total": len(site_batches),
        "stored_batches_total": _coerce_int(sink_result.get("stored_batches_total")),
        "delivery_owner": str(sink_result.get("delivery_owner") or ""),
        "rollup_scope_kind": str(sink_result.get("scope_kind") or ""),
        "regressions_total": _coerce_int(sink_result.get("regressions_total")),
        "quality_regressions_total": _coerce_int(sink_result.get("quality_regressions_total")),
        "callback_attempted_total": callback_attempted_total,
        "callback_delivered_total": callback_delivered_total,
        "callback_failed_total": callback_failed_total,
        "callback_skipped_total": callback_skipped_total,
        "site_batches": site_batches,
    }


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    require_database_connection(settings.database_url)

    result = run_once(settings)
    get_logger("npcink_ai_cloud.router_diagnostics_summary").info(
        "router diagnostics summary cadence generated: %s",
        result,
    )


if __name__ == "__main__":
    main()
