from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.adapters.providers.registry import resolve_live_provider_adapters
from app.api.auth import authorize_internal_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.models import ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN
from app.core.security import extract_trace_id
from app.domain.catalog.service import CatalogService
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.observability.plugin_events import PluginObservabilityService
from app.domain.observability.service import ObservabilityService
from app.domain.runtime.models import (
    RUNTIME_BACKLOG_SCOPE_KIND_PATTERN,
    RUNTIME_DIAGNOSTIC_ISSUE_KIND_PATTERN,
)
from app.domain.runtime.service import RuntimeService
from app.workers.ops_cadence import build_cadence_summary

router = APIRouter(prefix="/internal/service", tags=["service"])


class AccountPayload(BaseModel):
    account_id: str
    name: str
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)
    bind_default_free: bool = False


class MembershipPayload(BaseModel):
    member_ref: str
    role: str = ACCOUNT_MEMBERSHIP_ROLE_USER_ADMIN
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteProvisionPayload(BaseModel):
    site_id: str
    account_id: str
    name: str = ""
    status: str = "provisioning"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SiteStatusPayload(BaseModel):
    reason: str = ""


class SiteKeyPayload(BaseModel):
    key_id: str | None = None
    secret: str | None = None
    scopes: list[str] = Field(default_factory=list)
    label: str = ""
    expires_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KeyExpirePayload(BaseModel):
    expires_at: datetime


class PlanPayload(BaseModel):
    plan_id: str
    name: str
    status: str = "active"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanVersionPayload(BaseModel):
    plan_version_id: str
    version_label: str
    status: str = "published"
    currency: str = "USD"
    entitlements: dict[str, Any] = Field(default_factory=dict)
    budgets: dict[str, Any] = Field(default_factory=dict)
    concurrency: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubscriptionPayload(BaseModel):
    subscription_id: str | None = None
    account_id: str
    plan_id: str
    plan_version_id: str
    status: str = "active"
    current_period_start_at: datetime | None = None
    current_period_end_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubscriptionTopUpPayload(BaseModel):
    target_period_start_at: datetime | None = None
    target_period_end_at: datetime | None = None
    runs_increment: float = 0.0
    tokens_increment: float = 0.0
    cost_increment: float = 0.0
    reason: str = ""
    note: str = ""


def _get_commercial_service(request: Request) -> CommercialService:
    services = get_cloud_services(request)
    return CommercialService(services.settings.database_url, settings=services.settings)


def _get_catalog_service(request: Request) -> CatalogService:
    services = get_cloud_services(request)
    return CatalogService(
        services.settings.database_url,
        providers=resolve_live_provider_adapters(
            services.settings,
            base_providers=services.providers,
            include_enabled_connections=True,
        ),
    )


def _service_error_response(
    error: CommercialServiceError,
    *,
    request: Request | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=build_envelope(
            status="error",
            error_code=error.error_code,
            message=error.message,
            trace_id=(
                extract_trace_id(request.headers.get("traceparent", ""))
                if request is not None
                else ""
            ),
            revision="m6",
        ),
    )


def _build_audit_context(request: Request) -> ServiceAuditContext:
    return ServiceAuditContext(
        trace_id=extract_trace_id(request.headers.get("traceparent", "")),
        idempotency_key=request.headers.get("Idempotency-Key", "").strip(),
        method=request.method,
        path=request.url.path,
        actor_kind="internal_token",
        actor_ref="internal",
    )


def _build_audit_payload(payload: BaseModel | None = None) -> dict[str, Any]:
    if payload is None:
        return {}
    return payload.model_dump(mode="json")


def _build_audit_filters(
    *,
    account_id: str | None = None,
    site_id: str | None = None,
    event_kind: str | None = None,
    outcome: str | None = None,
) -> dict[str, str]:
    filters: dict[str, str] = {}
    if account_id:
        filters["account_id"] = str(account_id)
    if site_id:
        filters["site_id"] = str(site_id)
    if event_kind:
        filters["event_kind"] = str(event_kind)
    if outcome:
        filters["outcome"] = str(outcome)
    return filters


def _build_operator_receipt(
    *,
    event_kind: str,
    scope_kind: str,
    scope_id: str,
    outcome: str,
    effective_summary: str,
    audit_event: dict[str, Any] | None = None,
    account_id: str | None = None,
    site_id: str | None = None,
) -> dict[str, Any]:
    resolved_account_id = str(
        (audit_event or {}).get("account_id") or account_id or ""
    ).strip()
    resolved_site_id = str((audit_event or {}).get("site_id") or site_id or "").strip()
    receipt: dict[str, Any] = {
        "event_kind": event_kind,
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "outcome": outcome,
        "effective_summary": effective_summary,
        "audit_filters": _build_audit_filters(
            account_id=resolved_account_id,
            site_id=resolved_site_id,
            event_kind=event_kind,
            outcome=outcome,
        ),
    }
    audit_event_id = int((audit_event or {}).get("event_id") or 0)
    if audit_event_id > 0:
        receipt["audit_event_id"] = audit_event_id
    return receipt


def _merge_receipt(data: Any, receipt: dict[str, Any]) -> Any:
    if isinstance(data, dict):
        return {**data, "receipt": receipt}
    return {"value": data, "receipt": receipt}


def _build_runtime_explanations(
    runtime_diagnostics: dict[str, Any] | None,
    *,
    site_id: str | None = None,
    account_id: str | None = None,
    subscription_id: str | None = None,
) -> list[dict[str, str]]:
    diagnostics = runtime_diagnostics or {}
    queue = diagnostics.get("queue") if isinstance(diagnostics.get("queue"), dict) else {}
    callback = (
        diagnostics.get("callback") if isinstance(diagnostics.get("callback"), dict) else {}
    )
    guard = diagnostics.get("guard") if isinstance(diagnostics.get("guard"), dict) else {}
    items: list[dict[str, str]] = []

    if int(callback.get("failed") or 0) > 0 or callback.get("pressure_state") in {"attention", "critical"}:
        items.append(
            {
                "state": "degraded",
                "explain_text": "Callback delivery is already degraded. Operator follow-up should start from site runtime posture before widening provider or customer support work.",
                "next_step_kind": "site",
                "next_step_ref": str(site_id or ""),
            }
        )
    if int(queue.get("queued_runs") or 0) > 0 or queue.get("pressure_state") in {"attention", "critical"}:
        items.append(
            {
                "state": "queued",
                "explain_text": "Queued or backlogged runs are accumulating. Confirm the affected site first, then inspect provider or model surfaces only if the queue remains the leading blocker.",
                "next_step_kind": "site",
                "next_step_ref": str(site_id or ""),
            }
        )
    if int(guard.get("recent_events") or 0) > 0:
        items.append(
            {
                "state": "policy_gated",
                "explain_text": "Recent guard events suggest a policy or throttle gate is already affecting runtime behavior. Check commercial entitlement and support visibility before treating this as a pure execution-source failure.",
                "next_step_kind": "subscription" if subscription_id else "account",
                "next_step_ref": str(subscription_id or account_id or ""),
            }
        )

    if not items:
        items.append(
            {
                "state": "ok",
                "explain_text": "Current runtime summary does not surface an immediate operator-critical blocker.",
                "next_step_kind": "site" if site_id else "account",
                "next_step_ref": str(site_id or account_id or ""),
            }
        )

    return items


def _record_service_failure(
    request: Request,
    *,
    event_kind: str,
    error: CommercialServiceError,
    payload_json: dict[str, Any] | None = None,
    account_id: str | None = None,
    site_id: str | None = None,
    key_id: str | None = None,
    subscription_id: str | None = None,
    plan_id: str | None = None,
    plan_version_id: str | None = None,
    scope_kind: str | None = None,
    scope_id: str | None = None,
) -> None:
    try:
        _get_commercial_service(request).record_service_audit_event(
            audit_context=_build_audit_context(request),
            event_kind=event_kind,
            outcome="error",
            account_id=account_id,
            site_id=site_id,
            key_id=key_id,
            subscription_id=subscription_id,
            plan_id=plan_id,
            plan_version_id=plan_version_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
            payload_json={
                "error_code": error.error_code,
                "message": error.message,
                "request": payload_json or {},
            },
        )
    except Exception:
        return


@router.post("/accounts")
async def upsert_account(
    request: Request,
    payload: AccountPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_account(
            account_id=payload.account_id,
            name=payload.name,
            status=payload.status,
            metadata_json=payload.metadata,
            bind_default_free=payload.bind_default_free,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="account.upsert",
            error=error,
            account_id=payload.account_id,
            scope_kind="account",
            scope_id=payload.account_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="account saved", data=result, revision="m6")


@router.post("/accounts/{account_id}/memberships")
async def upsert_account_membership(
    request: Request,
    account_id: str,
    payload: MembershipPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_account_membership(
            account_id=account_id,
            member_ref=payload.member_ref,
            role=payload.role,
            status=payload.status,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="account_membership.upsert",
            error=error,
            account_id=account_id,
            scope_kind="account",
            scope_id=account_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="account membership saved",
        data=result,
        revision="m6",
    )


@router.post("/sites")
async def provision_site(
    request: Request,
    payload: SiteProvisionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.provision_site(
            site_id=payload.site_id,
            account_id=payload.account_id,
            name=payload.name,
            status=payload.status,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site.provision",
            error=error,
            account_id=payload.account_id,
            site_id=payload.site_id,
            scope_kind="site",
            scope_id=payload.site_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site provisioned", data=result, revision="m6")


@router.post("/sites/{site_id}/activate")
async def activate_site(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.activate_site(site_id, audit_context=audit_context)
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site.activate",
            error=error,
            site_id=site_id,
            scope_kind="site",
            scope_id=site_id,
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site activated", data=result, revision="m6")


@router.post("/sites/{site_id}/suspend")
async def suspend_site(
    request: Request,
    site_id: str,
    payload: SiteStatusPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.suspend_site(
            site_id,
            reason=payload.reason,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site.suspend",
            error=error,
            site_id=site_id,
            scope_kind="site",
            scope_id=site_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site suspended", data=result, revision="m6")


@router.get("/sites/{site_id}/keys")
async def list_site_keys(
    request: Request,
    site_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_site_keys(
            site_id,
            limit=limit,
            offset=offset,
        )
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(status="ok", message="site keys loaded", data=result, revision="m6")


@router.post("/sites/{site_id}/keys")
async def issue_site_key(
    request: Request,
    site_id: str,
    payload: SiteKeyPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.issue_site_key(
            site_id=site_id,
            key_id=payload.key_id,
            secret=payload.secret,
            scopes=payload.scopes,
            label=payload.label,
            expires_at=payload.expires_at,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_key.issue",
            error=error,
            site_id=site_id,
            key_id=payload.key_id,
            scope_kind="site_key",
            scope_id=payload.key_id or "",
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site key issued", data=result, revision="m6")


@router.post("/sites/{site_id}/keys/{key_id}/rotate")
async def rotate_site_key(
    request: Request,
    site_id: str,
    key_id: str,
    payload: SiteKeyPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.rotate_site_key(
            site_id=site_id,
            key_id=key_id,
            next_key_id=payload.key_id,
            secret=payload.secret,
            scopes=payload.scopes if payload.scopes else None,
            label=payload.label,
            expires_at=payload.expires_at,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_key.rotate",
            error=error,
            site_id=site_id,
            key_id=key_id,
            scope_kind="site_key",
            scope_id=key_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site key rotated", data=result, revision="m6")


@router.post("/sites/{site_id}/keys/{key_id}/revoke")
async def revoke_site_key(
    request: Request,
    site_id: str,
    key_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.revoke_site_key(
            site_id=site_id,
            key_id=key_id,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_key.revoke",
            error=error,
            site_id=site_id,
            key_id=key_id,
            scope_kind="site_key",
            scope_id=key_id,
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site key revoked", data=result, revision="m6")


@router.post("/sites/{site_id}/keys/{key_id}/expire")
async def expire_site_key(
    request: Request,
    site_id: str,
    key_id: str,
    payload: KeyExpirePayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.expire_site_key(
            site_id=site_id,
            key_id=key_id,
            expires_at=payload.expires_at,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="site_key.expire",
            error=error,
            site_id=site_id,
            key_id=key_id,
            scope_kind="site_key",
            scope_id=key_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(status="ok", message="site key expired", data=result, revision="m6")


@router.post("/plans")
async def upsert_plan(
    request: Request,
    payload: PlanPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_plan(
            plan_id=payload.plan_id,
            name=payload.name,
            status=payload.status,
            description=payload.description,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="plan.upsert",
            error=error,
            plan_id=payload.plan_id,
            scope_kind="plan",
            scope_id=payload.plan_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="plan saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="plan.upsert",
                scope_kind="plan",
                scope_id=payload.plan_id,
                outcome="succeeded",
                effective_summary=f"Plan {payload.plan_id} is now saved on the commercial truth plane.",
            ),
        ),
        revision="m6",
    )


@router.post("/plans/{plan_id}/versions")
async def publish_plan_version(
    request: Request,
    plan_id: str,
    payload: PlanVersionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.publish_plan_version(
            plan_id=plan_id,
            plan_version_id=payload.plan_version_id,
            version_label=payload.version_label,
            status=payload.status,
            currency=payload.currency,
            entitlements_json=payload.entitlements,
            budgets_json=payload.budgets,
            concurrency_json=payload.concurrency,
            policy_json=payload.policy,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="plan_version.publish",
            error=error,
            plan_id=plan_id,
            plan_version_id=payload.plan_version_id,
            scope_kind="plan_version",
            scope_id=payload.plan_version_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="plan version published",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="plan_version.publish",
                scope_kind="plan_version",
                scope_id=payload.plan_version_id,
                outcome="succeeded",
                effective_summary=f"Plan version {payload.plan_version_id} is now published and ready for subscription binding.",
            ),
        ),
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/subscription")
@router.patch("/admin/accounts/{account_id}/subscription")
async def upsert_account_subscription(
    request: Request,
    account_id: str,
    payload: SubscriptionPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.upsert_account_subscription(
            subscription_id=payload.subscription_id,
            account_id=account_id,
            plan_id=payload.plan_id,
            plan_version_id=payload.plan_version_id,
            status=payload.status,
            current_period_start_at=payload.current_period_start_at,
            current_period_end_at=payload.current_period_end_at,
            metadata_json=payload.metadata,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.upsert",
            error=error,
            account_id=account_id,
            subscription_id=payload.subscription_id,
            plan_id=payload.plan_id,
            plan_version_id=payload.plan_version_id,
            scope_kind="subscription",
            scope_id=payload.subscription_id or "",
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="account subscription saved",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.upsert",
                scope_kind="subscription",
                scope_id=str(result.get("subscription_id") or payload.subscription_id or account_id),
                outcome="succeeded",
                effective_summary=f"Account {account_id} now resolves to subscription {result.get('subscription_id') or payload.subscription_id or account_id}.",
                account_id=account_id,
            ),
        ),
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/subscription/suspend")
async def suspend_account_subscription(request: Request, account_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.suspend_account_subscription(account_id, audit_context=audit_context)
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.suspend",
            error=error,
            account_id=account_id,
            scope_kind="subscription",
            scope_id=account_id,
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="account subscription suspended",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.suspend",
                scope_kind="subscription",
                scope_id=str(result.get("subscription_id") or account_id),
                outcome="succeeded",
                effective_summary=f"Current subscription coverage for account {account_id} is now suspended.",
                account_id=str(result.get("account_id") or ""),
            ),
        ),
        revision="m6",
    )


@router.post("/subscriptions/{subscription_id}/topup")
async def apply_subscription_topup(
    request: Request,
    subscription_id: str,
    payload: SubscriptionTopUpPayload,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.apply_operator_managed_subscription_topup(
            subscription_id=subscription_id,
            pack_id="",
            runs_increment=payload.runs_increment,
            tokens_increment=payload.tokens_increment,
            cost_increment=payload.cost_increment,
            reason=payload.reason,
            note=payload.note,
            target_period_start_at=payload.target_period_start_at,
            target_period_end_at=payload.target_period_end_at,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.topup",
            error=error,
            subscription_id=subscription_id,
            scope_kind="subscription",
            scope_id=subscription_id,
            payload_json=_build_audit_payload(payload),
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="subscription top-up applied",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.topup",
                scope_kind="subscription",
                scope_id=subscription_id,
                outcome="succeeded",
                effective_summary=(
                    f"Subscription {subscription_id} now has operator-managed budget headroom added "
                    f"for the current billing period"
                    + (
                        f" via pack {result.get('topup', {}).get('pack_id')}."
                        if str((result.get("topup") or {}).get("pack_id") or "").strip()
                        else "."
                    )
                ),
            ),
        ),
        revision="m6",
    )


@router.post("/admin/accounts/{account_id}/subscription/cancel")
async def cancel_account_subscription(request: Request, account_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.cancel_account_subscription(account_id, audit_context=audit_context)
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.cancel",
            error=error,
            account_id=account_id,
            scope_kind="subscription",
            scope_id=account_id,
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="account subscription canceled",
        data=_merge_receipt(
            result,
            _build_operator_receipt(
                event_kind="subscription.cancel",
                scope_kind="subscription",
                scope_id=str(result.get("subscription_id") or account_id),
                outcome="succeeded",
                effective_summary=f"Current subscription coverage for account {account_id} is now canceled.",
                account_id=str(result.get("account_id") or ""),
            ),
        ),
        revision="m6",
    )


@router.get("/sites/{site_id}/usage-meter")
async def inspect_usage_meter(
    request: Request,
    site_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).inspect_usage_meter(site_id, limit=limit)
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="usage meter loaded",
        data=result,
        revision="m6",
    )


@router.get("/sites/{site_id}/billing-snapshots")
async def list_billing_snapshots(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_billing_snapshots(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="billing snapshots loaded",
        data=result,
        revision="m6",
    )


@router.get("/sites/{site_id}/billing-snapshots/reconciliation")
async def reconcile_billing_snapshot(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).reconcile_billing_snapshot(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="billing snapshot reconciliation loaded",
        data=result,
        revision="m6",
    )


@router.post("/sites/{site_id}/billing-snapshots/rebuild")
async def rebuild_billing_snapshot(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.rebuild_billing_snapshot(site_id, audit_context=audit_context)
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="billing_snapshot.rebuild",
            error=error,
            site_id=site_id,
            scope_kind="billing_snapshot",
            scope_id=site_id,
        )
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="billing snapshot rebuilt",
        data=result,
        revision="m6",
    )


@router.get("/sites/{site_id}/commercial-policy")
async def inspect_commercial_policy(request: Request, site_id: str) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).inspect_commercial_policy(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error)
    return build_envelope(
        status="ok",
        message="commercial policy loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/overview")
async def get_admin_overview(
    request: Request,
    usage_window_days: int = Query(default=7, ge=1, le=90),
    audit_window_minutes: int = Query(default=1440, ge=1, le=10080),
    runtime_recent_minutes: int = Query(default=60, ge=1, le=1440),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    service = _get_commercial_service(request)
    try:
        result = service.get_admin_overview(
            usage_window_days=usage_window_days,
            audit_window_minutes=audit_window_minutes,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    result["runtime_diagnostics"] = RuntimeService(
        services.settings.database_url
    ).get_runtime_diagnostics_summary(
        recent_minutes=runtime_recent_minutes,
    )
    attention_subscriptions = (
        result.get("attention_subscriptions")
        if isinstance(result.get("attention_subscriptions"), list)
        else []
    )
    first_attention = attention_subscriptions[0] if attention_subscriptions else {}
    first_attention_account_id = ""
    first_attention_site_id = ""
    first_attention_subscription_id = ""
    if isinstance(first_attention, dict):
        first_attention_account_id = str(
            (first_attention.get("account") or {}).get("account_id")
            or first_attention.get("account_id")
            or ""
        )
        first_attention_site_id = str(
            (first_attention.get("site") or {}).get("site_id")
            or first_attention.get("site_id")
            or ""
        )
        first_attention_subscription_id = str(
            (first_attention.get("subscription") or {}).get("subscription_id")
            or first_attention.get("subscription_id")
            or ""
        )
    result["runtime_operator_explanations"] = _build_runtime_explanations(
        result["runtime_diagnostics"],
        site_id=first_attention_site_id,
        account_id=first_attention_account_id,
        subscription_id=first_attention_subscription_id,
    )
    return build_envelope(
        status="ok",
        message="admin overview loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/accounts")
async def list_admin_accounts(
    request: Request,
    status: str | None = Query(default=None),
    member_ref: str | None = Query(default=None),
    expires_before: datetime | None = Query(default=None),
    coverage_state: str | None = Query(default=None),
    package_kind: str | None = Query(default=None),
    top_plan_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_accounts(
            status=status,
            member_ref=member_ref,
            expires_before=expires_before,
            coverage_state=coverage_state,
            package_kind=package_kind,
            top_plan_id=top_plan_id,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin accounts loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}")
async def get_admin_account(
    request: Request,
    account_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_account(account_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin account loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}/subscription")
async def get_admin_account_subscription(
    request: Request,
    account_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        account = _get_commercial_service(request).get_admin_account(account_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    subscriptions = list(account.get("subscriptions") or [])
    current = subscriptions[0] if subscriptions else None
    return build_envelope(
        status="ok",
        message="admin account subscription loaded",
        data={
            "account": account.get("account"),
            "current_subscription": current,
            "subscriptions": subscriptions,
        },
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}/member-plan-coverage")
async def get_admin_account_member_plan_coverage(
    request: Request,
    account_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_account_member_plan_coverage(account_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin account member coverage loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}/members")
async def list_admin_account_members(
    request: Request,
    account_id: str,
    status: str | None = Query(default=None),
    invite_state: str | None = Query(default=None),
    delivery_status: str | None = Query(default=None),
    never_logged_in: bool = Query(default=False),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_account_members(
            account_id=account_id,
            status=status,
            invite_state=invite_state,
            delivery_status=delivery_status,
            never_logged_in=never_logged_in,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin account members loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/accounts/{account_id}/members/{member_ref:path}")
async def get_admin_account_member(
    request: Request,
    account_id: str,
    member_ref: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_account_member(
            account_id=account_id,
            member_ref=member_ref,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin account member loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/sites")
async def list_admin_sites(
    request: Request,
    status: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    subscription_status: str | None = Query(default=None),
    expires_before: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    usage_window_days: int = Query(default=7, ge=1, le=90),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_sites(
            status=status,
            account_id=account_id,
            subscription_status=subscription_status,
            expires_before=expires_before,
            limit=limit,
            usage_window_days=usage_window_days,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin sites loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/sites/{site_id}")
async def get_admin_site(
    request: Request,
    site_id: str,
    runtime_recent_minutes: int = Query(default=60, ge=1, le=1440),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    try:
        result = _get_commercial_service(request).get_admin_site(site_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    result["runtime_diagnostics"] = RuntimeService(
        services.settings.database_url
    ).get_runtime_diagnostics_summary(
        site_id=site_id,
        recent_minutes=runtime_recent_minutes,
    )
    result["runtime_operator_explanations"] = _build_runtime_explanations(
        result["runtime_diagnostics"],
        site_id=site_id,
        account_id=str((result.get("account") or {}).get("account_id") or ""),
        subscription_id=str((result.get("subscription") or {}).get("subscription_id") or ""),
    )
    related_account_id = str((result.get("account") or {}).get("account_id") or "")
    related_subscription_id = str(
        (result.get("subscription") or {}).get("subscription_id") or ""
    )
    result["related_surfaces"] = {
        "account_href": f"/admin/accounts/{related_account_id}" if related_account_id else "",
        "subscription_href": (
            f"/admin/subscriptions/{related_subscription_id}"
            if related_subscription_id
            else ""
        ),
        "audit_href": f"/api/admin/audit-events?site_id={site_id}&limit=20",
    }
    result["commercial_follow_up"] = {
        "entitlement_summary": "Use the linked plan and version snapshot as the current commercial entitlement boundary for this site.",
        "budget_headroom_summary": "Budget headroom should be read before widening runtime troubleshooting, because over-limit posture can be the real blocker.",
        "runtime_gating_summary": "If runtime posture is degraded or policy-gated, confirm whether subscription state, grace, or downgrade policy is already constraining this site.",
        "next_operator_follow_up": "Open the current customer subscription when commercial coverage is the blocker; stay on site detail when runtime posture is the blocker.",
    }
    return build_envelope(
        status="ok",
        message="admin site loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/subscriptions")
async def list_admin_subscriptions(
    request: Request,
    status: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    plan_id: str | None = Query(default=None),
    expires_before: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_subscriptions(
            status=status,
            account_id=account_id,
            plan_id=plan_id,
            expires_before=expires_before,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin subscriptions loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/subscriptions/{subscription_id}")
async def get_admin_subscription(
    request: Request,
    subscription_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_subscription(subscription_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    site_id = str((result.get("site") or {}).get("site_id") or "")
    account_id = str((result.get("account") or {}).get("account_id") or "")
    result["related_surfaces"] = {
        "site_href": f"/admin/sites/{site_id}" if site_id else "",
        "account_href": f"/admin/accounts/{account_id}" if account_id else "",
        "audit_href": (
            f"/api/admin/audit-events?site_id={site_id}&account_id={account_id}&limit=20"
            if site_id or account_id
            else ""
        ),
    }
    result["commercial_follow_up"] = {
        "lifecycle_posture": "Read current status and grace posture first; commercial follow-up should lead before runtime debugging when the subscription is degraded.",
        "snapshot_reconciliation_summary": "Use site detail and filtered audit evidence to confirm whether snapshot posture and current operational impact are still aligned.",
        "next_operator_follow_up": "Open site detail for runtime and entitlement impact, or customer detail for support scope.",
    }
    return build_envelope(
        status="ok",
        message="admin subscription loaded",
        data=result,
        revision="m6",
    )


@router.post("/admin/subscriptions/{subscription_id}/billing-snapshots/rebuild")
async def rebuild_admin_subscription_billing_snapshots(
    request: Request,
    subscription_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth
    service = _get_commercial_service(request)
    audit_context = _build_audit_context(request)
    try:
        result = service.rebuild_subscription_billing_snapshots(
            subscription_id,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        _record_service_failure(
            request,
            event_kind="subscription.billing_snapshot.rebuild",
            error=error,
            subscription_id=subscription_id,
            scope_kind="subscription",
            scope_id=subscription_id,
        )
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="subscription billing snapshots rebuilt",
        data=result,
        revision="m6",
    )


@router.get("/admin/plans")
async def list_admin_plans(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).list_admin_plans(
            status=status,
            limit=limit,
        )
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin plans loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/plans/{plan_id}")
async def get_admin_plan(
    request: Request,
    plan_id: str,
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    try:
        result = _get_commercial_service(request).get_admin_plan(plan_id)
    except CommercialServiceError as error:
        return _service_error_response(error, request=request)
    return build_envelope(
        status="ok",
        message="admin plan loaded",
        data=result,
        revision="m6",
    )


@router.get("/admin/plugin-observability")
async def get_admin_plugin_observability(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168),
    site_id: str = Query(default=""),
    plugin_slug: str = Query(default=""),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    service = PluginObservabilityService(services.settings.database_url)
    result = service.get_admin_summary(
        window_hours=window_hours,
        site_id=site_id,
        plugin_slug=plugin_slug,
    )
    return build_envelope(
        status="ok",
        message="plugin observability admin summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/audit-events")
async def list_service_audit_events(
    request: Request,
    site_id: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    event_kind: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_commercial_service(request).list_service_audit_events(
        site_id=site_id,
        account_id=account_id,
        event_kind=event_kind,
        outcome=outcome,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="service audit events loaded",
        data=result,
        revision="m6",
    )


@router.get("/audit-events/summary")
async def summarize_service_audit_events(
    request: Request,
    site_id: str | None = Query(default=None),
    account_id: str | None = Query(default=None),
    window_minutes: int = Query(default=1440, ge=1, le=10080),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_commercial_service(request).summarize_service_audit_events(
        site_id=site_id,
        account_id=account_id,
        window_minutes=window_minutes,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="service audit summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/ops/cadence")
async def get_ops_cadence_summary(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = build_cadence_summary(get_cloud_services(request).settings)
    return build_envelope(
        status="ok",
        message="ops cadence summary loaded",
        data=result,
        revision="m7",
    )


@router.get("/observability/summary")
async def get_observability_summary(
    request: Request,
    recent_minutes: int = Query(default=60, ge=1, le=1440),
    backlog_limit: int = Query(default=10, ge=1, le=50),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    ready_report = await services.get_ready_report()
    result = ObservabilityService(services.settings).build_summary(
        ready_report=ready_report,
        recent_minutes=recent_minutes,
        backlog_limit=backlog_limit,
    )
    return build_envelope(
        status="ok",
        message="observability summary loaded",
        data=result,
        revision="m1",
    )


@router.get("/commercial-decisions")
async def list_commercial_decision_events(
    request: Request,
    site_id: str | None = Query(default=None),
    decision: str | None = Query(default=None),
    request_kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_commercial_service(request).list_commercial_decision_events(
        site_id=site_id,
        decision=decision,
        request_kind=request_kind,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="commercial decision events loaded",
        data=result,
        revision="m6",
    )


@router.get("/commercial-decisions/summary")
async def summarize_commercial_decision_events(
    request: Request,
    site_id: str | None = Query(default=None),
    request_kind: str | None = Query(default=None),
    window_minutes: int = Query(default=1440, ge=1, le=10080),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    result = _get_commercial_service(request).summarize_commercial_decision_events(
        site_id=site_id,
        request_kind=request_kind,
        window_minutes=window_minutes,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="commercial decision summary loaded",
        data=result,
        revision="m6",
    )


@router.get("/runtime/diagnostics/summary")
async def get_runtime_diagnostics_summary(
    request: Request,
    site_id: str | None = Query(default=None),
    recent_minutes: int = Query(default=60, ge=1, le=1440),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).get_runtime_diagnostics_summary(
        site_id=site_id,
        recent_minutes=recent_minutes,
    )
    return build_envelope(
        status="ok",
        message="runtime diagnostics summary loaded",
        data=result,
        revision="m8",
    )


@router.get("/runtime/diagnostics/backlog")
async def get_runtime_backlog_diagnostics(
    request: Request,
    scope_kind: str = Query(default="site_id", pattern=RUNTIME_BACKLOG_SCOPE_KIND_PATTERN),
    site_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).get_runtime_backlog_diagnostics(
        scope_kind=scope_kind,
        site_id=site_id,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="runtime backlog diagnostics loaded",
        data=result,
        revision="m1",
    )


@router.get("/runtime/diagnostics/runs")
async def list_runtime_diagnostic_runs(
    request: Request,
    issue_kind: str = Query(
        default="callback_failed",
        pattern=RUNTIME_DIAGNOSTIC_ISSUE_KIND_PATTERN,
    ),
    site_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).list_runtime_diagnostic_runs(
        issue_kind=issue_kind,
        site_id=site_id,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="runtime diagnostic runs loaded",
        data=result,
        revision="m7",
    )


@router.get("/runtime/diagnostics/guard-events")
async def list_runtime_guard_events(
    request: Request,
    site_id: str | None = Query(default=None),
    scope_kind: str | None = Query(default=None),
    event_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).list_runtime_guard_events(
        site_id=site_id,
        scope_kind=scope_kind,
        event_code=event_code,
        limit=limit,
    )
    return build_envelope(
        status="ok",
        message="runtime guard events loaded",
        data=result,
        revision="m6",
    )


@router.get("/runtime/diagnostics/abuse-guard")
async def get_runtime_abuse_guard_diagnostics(
    request: Request,
    window_seconds: int = Query(default=60, ge=1, le=3600),
    cooldown_window_seconds: int = Query(default=1800, ge=60, le=86400),
    limit_per_scope: int = Query(default=10, ge=1, le=50),
) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=False)
    if auth is not None:
        return auth
    services = get_cloud_services(request)
    result = RuntimeService(services.settings.database_url).get_abuse_guard_diagnostics(
        window_seconds=window_seconds,
        cooldown_window_seconds=cooldown_window_seconds,
        limit_per_scope=limit_per_scope,
        public_post_site_limit=services.settings.public_post_max_requests_per_window,
        public_post_key_limit=services.settings.public_post_max_requests_per_key_window,
        public_post_ip_limit=services.settings.public_post_max_requests_per_ip_window,
        public_guard_site_cooldown_limit=(
            services.settings.public_guard_max_reject_events_per_site_window
        ),
        public_guard_key_cooldown_limit=(
            services.settings.public_guard_max_reject_events_per_key_window
        ),
        public_guard_ip_cooldown_limit=(
            services.settings.public_guard_max_reject_events_per_ip_window
        ),
        internal_post_token_limit=services.settings.internal_post_max_requests_per_window,
        internal_post_ip_limit=services.settings.internal_post_max_requests_per_ip_window,
        internal_guard_token_cooldown_limit=(
            services.settings.internal_guard_max_reject_events_per_token_window
        ),
        internal_guard_ip_cooldown_limit=(
            services.settings.internal_guard_max_reject_events_per_ip_window
        ),
    )
    return build_envelope(
        status="ok",
        message="runtime abuse guard diagnostics loaded",
        data=result,
        revision="m7",
    )


@router.post("/runtime/retention/cleanup")
async def cleanup_runtime_retention(request: Request) -> Any:
    auth = await authorize_internal_request(request, require_idempotency=True)
    if auth is not None:
        return auth

    audit_context = _build_audit_context(request)
    try:
        services = get_cloud_services(request)
        purged = RuntimeService(services.settings.database_url).cleanup_expired_run_results()
        _get_commercial_service(request).record_service_audit_event(
            audit_context=audit_context,
            event_kind="runtime.retention_cleanup",
            outcome="succeeded",
            scope_kind="runtime",
            scope_id="retention_cleanup",
            payload_json={"purged_runs": purged},
        )
    except Exception as error:
        _get_commercial_service(request).record_service_audit_event(
            audit_context=audit_context,
            event_kind="runtime.retention_cleanup",
            outcome="error",
            scope_kind="runtime",
            scope_id="retention_cleanup",
            payload_json={"message": str(error)},
        )
        return JSONResponse(
            status_code=500,
            content=build_envelope(
                status="error",
                error_code="service.retention_cleanup_failed",
                message="runtime retention cleanup failed",
                revision="m6",
            ),
        )

    return build_envelope(
        status="ok",
        message="runtime retention cleanup completed",
        data={"purged_runs": purged},
        revision="m6",
    )
