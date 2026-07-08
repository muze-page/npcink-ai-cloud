from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.security import extract_trace_id
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import CommercialService

router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])

CONTRACT_VERSION = "cloud-billing-entitlement-v1"
PUBLIC_PACKAGE_BY_TIER = {
    "free": "Free",
    "pro": "Pro",
    "agency": "Agency",
}


def _get_commercial_service(request: Request) -> CommercialService:
    services = get_cloud_services(request)
    return CommercialService(services.settings.database_url, settings=services.settings)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _public_datetime(value: object) -> str:
    serialized = str(value or "")
    return f"{serialized[:-6]}Z" if serialized.endswith("+00:00") else serialized


def _error_response(
    request: Request,
    *,
    status_code: int,
    error_code: str,
    message: str,
    trace_id: str = "",
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=build_envelope(
            status="error",
            error_code=error_code,
            message=message,
            trace_id=trace_id or extract_trace_id(request.headers.get("traceparent", "")),
            revision="m1",
        ),
    )


def _resolve_package_tier(policy: dict[str, object]) -> str:
    candidates = [
        _dict(policy.get("subscription")).get("tier_id"),
        _dict(_dict(policy.get("plan_version")).get("metadata")).get("tier_id"),
        _dict(_dict(policy.get("entitlement_snapshot")).get("metadata")).get("tier_id"),
        _dict(policy.get("subscription")).get("plan_id"),
    ]
    for item in candidates:
        tier_id = str(item or "").strip().lower()
        if tier_id in PUBLIC_PACKAGE_BY_TIER:
            return tier_id
    return ""


def _resolve_status(policy: dict[str, object]) -> str:
    subscription = _dict(policy.get("subscription"))
    if not subscription:
        return "uncovered"

    subscription_status = str(subscription.get("status") or "").strip().lower()
    if subscription_status == "suspended":
        return "suspended"
    if subscription_status in {"active", "trialing"}:
        return "active"
    return "inactive"


def _resolve_usage_limits(
    policy: dict[str, object],
    *,
    site_limit: int,
) -> dict[str, object]:
    snapshot = _dict(policy.get("entitlement_snapshot"))
    plan_version = _dict(policy.get("plan_version"))
    budgets = _dict(plan_version.get("budgets")) or _dict(snapshot.get("budgets"))
    return {
        "period": "month",
        "max_ai_credits": _coerce_float(budgets.get("max_ai_credits_per_period")),
        "max_sites": site_limit,
    }


def _resolve_site_limit(policy: dict[str, object], tier_id: str) -> int:
    snapshot = _dict(policy.get("entitlement_snapshot"))
    plan_metadata = _dict(_dict(policy.get("plan_version")).get("metadata"))
    value = plan_metadata.get("site_limit")
    if value is None:
        value = snapshot.get("site_limit")
    resolved = _coerce_int(value, default=0)
    return max(0, resolved)


def _resolve_runtime_quota(policy: dict[str, object]) -> dict[str, object]:
    snapshot = _dict(policy.get("entitlement_snapshot"))
    plan_version = _dict(policy.get("plan_version"))
    entitlements = _dict(plan_version.get("entitlements")) or _dict(snapshot.get("entitlements"))
    concurrency = _dict(plan_version.get("concurrency")) or _dict(snapshot.get("concurrency"))
    batch_limits = _dict(policy.get("batch_limits"))
    return {
        "max_active_runs": _coerce_int(concurrency.get("max_active_runs")),
        "max_batch_items": _coerce_int(batch_limits.get("max_batch_items")),
        "execution_tiers": _list(entitlements.get("execution_tiers")) or ["cloud"],
    }


def _resolve_pro_cloud_runtime(policy: dict[str, object]) -> dict[str, object]:
    pro_runtime = _dict(policy.get("pro_cloud_runtime"))
    batch_limits = _dict(policy.get("batch_limits"))
    payload_modes = _list(pro_runtime.get("payload_modes")) or _list(
        batch_limits.get("nightly_inspection_payload_modes")
    )
    max_runs = _coerce_int(pro_runtime.get("max_nightly_inspection_runs_per_period"))
    used_runs = _coerce_int(pro_runtime.get("used_nightly_inspection_runs"))
    return {
        "contract_version": "pro-cloud-runtime-entitlement-v1",
        "feature_id": "nightly_site_inspection",
        "execution_pattern": "whole_run_offload",
        "meter_key": "ai_credits",
        "limit_enforced": False,
        "max_nightly_inspection_runs_per_period": max_runs,
        "used_nightly_inspection_runs": used_runs,
        "remaining_nightly_inspection_runs": 0,
        "quota_exhausted": False,
        "max_batch_items": _coerce_int(
            pro_runtime.get("max_batch_items") or batch_limits.get("max_batch_items")
        ),
        "result_retention_days": _coerce_int(
            pro_runtime.get("result_retention_days")
            or batch_limits.get("nightly_inspection_retention_days")
        ),
        "payload_modes": payload_modes or ["metadata_only", "excerpt"],
        "cloud_role": "runtime_detail",
        "local_truth": {
            "schedule_owner": "wordpress_wp_cron_or_local_runtime",
            "runtime_owner": "npcink-local-automation-runtime",
            "final_write_path": "core_proposal_required",
            "direct_wordpress_write": False,
        },
        "contract_reuse": {
            "cloud_role": "runtime_detail",
            "toolbox_role": "product_surface",
            "core_role": "proposal_handoff",
            "adapter_role": "execution_profiles",
            "toolkit_role": "ability_contracts",
            "addon_role": "signed_transport",
            "adds_registry": False,
            "adds_scheduler_truth": False,
            "adds_approval_store": False,
            "adds_queue": False,
            "adds_write_executor": False,
        },
    }


def _resolve_credit_usage_detail(request: Request, account_id: str) -> dict[str, object]:
    if not account_id:
        return {}
    try:
        quota_summary = _get_commercial_service(request).get_portal_account_quota_summary(
            account_id
        )
    except CommercialServiceError:
        return {}
    credit_usage_detail = quota_summary.get("credit_usage_detail")
    if not isinstance(credit_usage_detail, dict):
        return {}
    return {
        key: value
        for key, value in credit_usage_detail.items()
        if key != "recent_items"
    }


def _build_entitlement_payload(
    request: Request,
    *,
    policy: dict[str, object],
    object_type: str,
    object_id: str,
) -> dict[str, object]:
    site = _dict(policy.get("site"))
    account_id = str(site.get("account_id") or "")
    tier_id = _resolve_package_tier(policy)
    site_limit = _resolve_site_limit(policy, tier_id)
    settings = get_cloud_services(request).settings
    return {
        "contract_version": CONTRACT_VERSION,
        "paid_object": {
            "type": object_type,
            "id": object_id,
            "account_id": account_id,
        },
        "package": PUBLIC_PACKAGE_BY_TIER.get(tier_id, ""),
        "package_tier": tier_id,
        "status": _resolve_status(policy),
        "period": {
            "start_at": _public_datetime(policy.get("period_start_at")),
            "end_at": _public_datetime(policy.get("period_end_at")),
        },
        "entitlement": {
            "usage_limits": _resolve_usage_limits(policy, site_limit=site_limit),
            "analytics_retention": {
                "days": max(0, int(settings.audit_retention_days_default or 0)),
            },
            "hosted_runtime_quota": _resolve_runtime_quota(policy),
            "pro_cloud_runtime": _resolve_pro_cloud_runtime(policy),
        },
        "quota_summary": {
            "credit_usage_detail": _resolve_credit_usage_detail(request, account_id),
        },
    }


@router.get("/current")
async def get_current_entitlement(
    request: Request,
    object_type: str = Query(default="site"),
    object_id: str = Query(default="", min_length=1),
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="entitlement:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    normalized_object_type = object_type.strip().lower()
    normalized_object_id = object_id.strip()
    if normalized_object_type != "site":
        return _error_response(
            request,
            status_code=400,
            error_code="entitlement.object_type_unsupported",
            message="object_type must be site",
            trace_id=auth.trace_id,
        )
    if normalized_object_id != auth.site_id:
        return _error_response(
            request,
            status_code=403,
            error_code="auth.object_mismatch",
            message="object_id does not match authenticated site",
            trace_id=auth.trace_id,
        )

    try:
        policy = _get_commercial_service(request).inspect_commercial_policy(auth.site_id)
    except CommercialServiceError as error:
        return _error_response(
            request,
            status_code=error.status_code,
            error_code=error.error_code,
            message=error.message,
            trace_id=auth.trace_id,
        )

    return JSONResponse(
        content=build_envelope(
            status="ok",
            message="entitlement loaded",
            data=_build_entitlement_payload(
                request,
                policy=policy,
                object_type=normalized_object_type,
                object_id=normalized_object_id,
            ),
            trace_id=auth.trace_id,
            revision="m1",
        ),
    )
