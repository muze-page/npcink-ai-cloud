from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.callback_security import (
    RuntimeCallbackTargetValidationError,
    validate_runtime_callback_target,
)
from app.core.config import Settings, get_settings
from app.core.db import get_session, require_database_connection
from app.core.logging import configure_logging, get_logger
from app.core.models import SITE_STATUS_ACTIVE
from app.domain.usage.rollup import UsageRollupService

CALLBACK_ROUTE = "/npcink/open/v1/router/performance-snapshot/callback"
CALLBACK_EVENT = "router.performance_snapshot.batch"
MAX_CALLBACK_RESPONSE_BODY_CHARS = 4000


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


def _truncate_callback_response_body(value: str) -> str:
    if len(value) <= MAX_CALLBACK_RESPONSE_BODY_CHARS:
        return value
    return f"{value[:MAX_CALLBACK_RESPONSE_BODY_CHARS]}...[truncated]"


def _build_projection_window(*, now: datetime, window_hours: int) -> tuple[datetime, datetime]:
    normalized_now = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return normalized_now - timedelta(hours=window_hours), normalized_now


def _build_trace_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _build_traceparent(trace_id: str) -> str:
    parent_id = hashlib.sha256(f"{trace_id}|parent".encode()).hexdigest()[:16]
    return f"00-{trace_id}-{parent_id}-01"


def _callback_canonical(
    *,
    route: str,
    site_id: str,
    key_id: str,
    timestamp: str,
    event: str,
    callback_id: str,
    traceparent: str,
    body: bytes,
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
            hashlib.sha256(body).hexdigest(),
        ]
    )


def _build_callback_url(base_url: str) -> str:
    return f"{str(base_url).strip().rstrip('/')}/wp-json{CALLBACK_ROUTE}"


def _resolve_callback_config(site: Any) -> dict[str, str | bool]:
    metadata = getattr(site, "metadata_json", None) or {}
    callbacks = metadata.get("projection_callbacks")
    callback = callbacks.get("router_performance_snapshot") if isinstance(callbacks, dict) else {}
    callback = callback if isinstance(callback, dict) else {}

    enabled_raw = callback.get("enabled")
    if enabled_raw is None:
        enabled_raw = metadata.get("router_performance_callback_enabled")
    enabled = True if enabled_raw is None else bool(enabled_raw)

    callback_url = str(
        callback.get("callback_url")
        or callback.get("url")
        or metadata.get("router_performance_callback_url")
        or ""
    ).strip()
    if not callback_url:
        public_base_url = str(metadata.get("public_base_url") or "").strip()
        if public_base_url:
            callback_url = _build_callback_url(public_base_url)

    return {
        "enabled": enabled,
        "callback_url": callback_url,
        "key_id": str(
            callback.get("key_id") or metadata.get("router_performance_callback_key_id") or ""
        ).strip(),
        "secret": str(
            callback.get("secret") or metadata.get("router_performance_callback_secret") or ""
        ).strip(),
    }


def _dispatch_callback(
    *,
    callback_url: str,
    site_id: str,
    key_id: str,
    secret: str,
    callback_id: str,
    payload: dict[str, Any],
    timeout_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    validate_runtime_callback_target(callback_url)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(datetime.now(UTC).timestamp()))
    trace_id = _build_trace_id(f"{site_id}|{callback_id}|{timestamp}")
    traceparent = _build_traceparent(trace_id)
    canonical = _callback_canonical(
        route=CALLBACK_ROUTE,
        site_id=site_id,
        key_id=key_id,
        timestamp=timestamp,
        event=CALLBACK_EVENT,
        callback_id=callback_id,
        traceparent=traceparent,
        body=body,
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

    with httpx.Client(
        timeout=timeout_seconds, transport=transport, follow_redirects=False
    ) as client:
        response = client.post(callback_url, content=body, headers=headers)

    return {
        "callback_url": callback_url,
        "status_code": response.status_code,
        "delivered": 200 <= response.status_code < 300,
        "response_body": _truncate_callback_response_body(response.text),
    }


def run_once(
    settings: Settings,
    *,
    now_factory: Callable[[], datetime] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    factory = now_factory or (lambda: datetime.now(UTC))
    now = factory()
    start_at, end_at = _build_projection_window(
        now=now,
        window_hours=settings.router_performance_worker_window_hours,
    )

    with get_session(settings.database_url) as session:
        sites = CommercialRepository(session).list_sites(
            status=SITE_STATUS_ACTIVE,
            limit=settings.router_performance_worker_site_limit,
        )
    sites_by_id = {str(site.site_id): site for site in sites}

    rollup_service = UsageRollupService(settings.database_url, now_factory=lambda: now)
    sink_result = rollup_service.store_router_performance_snapshot_batches(
        site_ids=[site.site_id for site in sites],
        start_at=start_at,
        end_at=end_at,
    )
    site_batches = _dict_items(sink_result.get("site_batches"))
    callback_attempted_total = 0
    callback_delivered_total = 0
    callback_failed_total = 0
    callback_skipped_total = 0

    for site_batch in site_batches:
        site_id = str(site_batch.get("site_id") or "")
        callback_id = str(site_batch.get("scope_id") or "")
        site = sites_by_id.get(site_id)
        config = _resolve_callback_config(site) if site is not None else {}
        callback_url = str(config.get("callback_url") or "").strip()
        key_id = str(config.get("key_id") or "").strip()
        secret = str(config.get("secret") or "").strip()
        if not site_id or not site_batch.get("window"):
            site_batch["callback"] = {"status": "skipped_invalid_batch"}
            callback_skipped_total += 1
            continue
        if not bool(config.get("enabled")):
            site_batch["callback"] = {"status": "disabled"}
            callback_skipped_total += 1
            continue
        if not callback_url or not key_id or not secret:
            site_batch["callback"] = {"status": "not_configured"}
            callback_skipped_total += 1
            continue

        callback_attempted_total += 1
        payload = rollup_service.get_router_performance_snapshot_batch(
            site_id=site_id,
            start_at=start_at,
            end_at=end_at,
        )
        if not isinstance(payload, dict) or not payload:
            site_batch["callback"] = {"status": "buffer_unavailable"}
            callback_failed_total += 1
            continue
        try:
            delivery = _dispatch_callback(
                callback_url=callback_url,
                site_id=site_id,
                key_id=key_id,
                secret=secret,
                callback_id=callback_id,
                payload=payload,
                timeout_seconds=settings.runtime_callback_timeout_seconds,
                transport=transport,
            )
        except RuntimeCallbackTargetValidationError as error:
            site_batch["callback"] = {
                "status": "callback_target_invalid",
                "callback_url": callback_url,
                "error": str(error),
            }
            callback_failed_total += 1
            continue
        except httpx.HTTPError as error:
            site_batch["callback"] = {
                "status": "transport_error",
                "callback_url": callback_url,
                "error": str(error),
            }
            callback_failed_total += 1
            continue
        site_batch["callback"] = {
            "status": "delivered" if delivery["delivered"] else "delivery_failed",
            "callback_url": callback_url,
            "status_code": int(delivery["status_code"]),
        }
        if delivery["delivered"]:
            callback_delivered_total += 1
        else:
            callback_failed_total += 1

    return {
        "source": "cloud_router_performance_snapshot_worker",
        "generated_at": now.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        "window": {
            "start_gmt": start_at.strftime("%Y-%m-%d %H:%M:%S"),
            "end_gmt": end_at.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "site_limit": settings.router_performance_worker_site_limit,
        "window_hours": settings.router_performance_worker_window_hours,
        "sites_total": len(site_batches),
        "stored_batches_total": _coerce_int(sink_result.get("stored_batches_total")),
        "delivery_owner": str(sink_result.get("delivery_owner") or ""),
        "rollup_scope_kind": str(sink_result.get("scope_kind") or ""),
        "rows_total": _coerce_int(sink_result.get("rows_total")),
        "request_total": _coerce_int(sink_result.get("request_total")),
        "success_total": _coerce_int(sink_result.get("success_total")),
        "guard_fail_total": _coerce_int(sink_result.get("guard_fail_total")),
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
    get_logger("npcink_ai_cloud.router_performance_snapshot").info(
        "router performance projection cadence generated: %s",
        result,
    )


if __name__ == "__main__":
    main()
