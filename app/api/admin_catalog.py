from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

from app.api.envelope import build_envelope
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService, ServiceAuditContext


def _build_receipt(
    *,
    event_kind: str,
    scope_kind: str,
    scope_id: str,
    outcome: str,
    effective_summary: str,
    audit_event: dict[str, object] | None,
) -> dict[str, object]:
    receipt: dict[str, object] = {
        "event_kind": event_kind,
        "scope_kind": scope_kind,
        "scope_id": scope_id,
        "outcome": outcome,
        "effective_summary": effective_summary,
        "audit_filters": {
            "event_kind": event_kind,
            "outcome": outcome,
        },
    }
    if audit_event:
        event_id = int(audit_event.get("event_id") or 0)
        if event_id > 0:
            receipt["audit_event_id"] = event_id
    return receipt


def save_admin_model_annotation(
    *,
    catalog_service: CatalogService,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    model_id: str,
    recommended: bool,
    cost_tier: str,
    visibility: str,
    badges: list[str],
    operator_notes: str,
) -> dict[str, Any] | JSONResponse:
    try:
        result = catalog_service.upsert_admin_model_annotation(
            model_id=model_id,
            recommended=recommended,
            cost_tier=cost_tier,
            visibility=visibility,
            badges=badges,
            operator_notes=operator_notes,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="catalog.admin_model_annotation_invalid",
                message=str(error),
                data={"model_id": model_id},
                revision="m6",
            ),
        )
    if result is None:
        return JSONResponse(
            status_code=404,
            content=build_envelope(
                status="error",
                error_code="catalog.admin_model_not_found",
                message="admin model not found",
                data={"model_id": model_id},
                revision="m6",
            ),
        )

    audit_event = commercial_service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="catalog_model_annotation.upsert",
        outcome="succeeded",
        scope_kind="catalog_model",
        scope_id=model_id,
        payload_json={
            "model_id": model_id,
            "annotation": result["annotation"],
        },
    )
    return build_envelope(
        status="ok",
        message="admin model annotation saved",
        data={
            **result,
            "receipt": _build_receipt(
                event_kind="catalog_model_annotation.upsert",
                scope_kind="catalog_model",
                scope_id=model_id,
                outcome="succeeded",
                effective_summary=f"Hosted annotation for model {model_id} is now saved.",
                audit_event=audit_event,
            ),
        },
        revision="m6",
    )


def save_admin_recognition_annotation(
    *,
    catalog_service: CatalogService,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    provider_id: str,
    model_id: str,
    review_status: str,
    manual_tags: list[str],
    operator_notes: str,
    recommended: bool,
    cost_tier_override: str,
    visibility: str,
    badges: list[str],
) -> dict[str, Any] | JSONResponse:
    try:
        result = catalog_service.upsert_admin_recognition_annotation(
            provider_id=provider_id,
            model_id=model_id,
            review_status=review_status,
            manual_tags=manual_tags,
            operator_notes=operator_notes,
            recommended=recommended,
            cost_tier_override=cost_tier_override,
            visibility=visibility,
            badges=badges,
        )
    except ValueError as error:
        return JSONResponse(
            status_code=400,
            content=build_envelope(
                status="error",
                error_code="catalog.admin_recognition_annotation_invalid",
                message=str(error),
                data={"provider_id": provider_id, "model_id": model_id},
                revision="m6",
            ),
        )
    if result is None:
        return JSONResponse(
            status_code=404,
            content=build_envelope(
                status="error",
                error_code="catalog.admin_recognition_not_found",
                message="admin recognition model not found",
                data={"provider_id": provider_id, "model_id": model_id},
                revision="m6",
            ),
        )

    audit_event = commercial_service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="recognition_model_annotation.upsert",
        outcome="succeeded",
        scope_kind="recognition_model",
        scope_id=f"{provider_id}:{model_id}",
        payload_json={
            "provider_id": provider_id,
            "model_id": model_id,
            "annotation": result["annotation"],
        },
    )
    return build_envelope(
        status="ok",
        message="admin recognition annotation saved",
        data={
            **result,
            "receipt": _build_receipt(
                event_kind="recognition_model_annotation.upsert",
                scope_kind="recognition_model",
                scope_id=f"{provider_id}:{model_id}",
                outcome="succeeded",
                effective_summary=f"Recognition review for {provider_id}:{model_id} is now saved.",
                audit_event=audit_event,
            ),
        },
        revision="m6",
    )
