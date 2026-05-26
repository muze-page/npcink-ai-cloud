from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.api.envelope import build_envelope
from app.api.auth import PortalBearerTokenError
from app.domain.catalog.service import CatalogService
from app.domain.commercial.errors import CommercialServiceError
from app.domain.commercial.service import CommercialService, ServiceAuditContext

JsonErrorBuilder = Callable[[Request, int, str, str], JSONResponse]
InviteSender = Callable[[str, str, str], Any]


def invite_admin_account_member(
    *,
    request: Request,
    json_error: JsonErrorBuilder,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    account_id: str,
    email: str,
    role: str,
    locale: str,
    platform_role: str,
    send_invite: InviteSender,
) -> dict[str, Any] | JSONResponse:
    try:
        result = commercial_service.invite_admin_account_member(
            account_id=account_id,
            email=email,
            role=role,
            locale=locale,
            platform_role=platform_role,
            audit_context=audit_context,
            send_invite=send_invite,
        )
    except CommercialServiceError as error:
        return json_error(
            request,
            error.status_code,
            error.error_code,
            error.message,
        )
    except PortalBearerTokenError as error:
        return json_error(
            request,
            error.status_code,
            error.error_code,
            error.message,
        )

    return build_envelope(
        status="ok",
        message=f"portal invite sent to {email}",
        data=result,
        revision="m6",
    )


def resend_admin_account_member_invite(
    *,
    request: Request,
    json_error: JsonErrorBuilder,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    account_id: str,
    member_ref: str,
    locale: str,
    platform_role: str,
    send_invite: InviteSender,
) -> dict[str, Any] | JSONResponse:
    try:
        result = commercial_service.resend_admin_account_member_invite(
            account_id=account_id,
            member_ref=member_ref,
            locale=locale,
            platform_role=platform_role,
            audit_context=audit_context,
            send_invite=send_invite,
        )
    except CommercialServiceError as error:
        status_code = (
            404
            if error.error_code == "service.account_membership_not_found"
            else error.status_code
        )
        error_code = (
            "admin.member_not_found"
            if error.error_code == "service.account_membership_not_found"
            else error.error_code
        )
        message = (
            "member was not found"
            if error.error_code == "service.account_membership_not_found"
            else error.message
        )
        return json_error(
            request,
            status_code,
            error_code,
            message,
        )
    except PortalBearerTokenError as error:
        return json_error(
            request,
            error.status_code,
            error.error_code,
            error.message,
        )

    return build_envelope(
        status="ok",
        message="portal invite resent",
        data=result,
        revision="m6",
    )


def disable_admin_account_member(
    *,
    request: Request,
    json_error: JsonErrorBuilder,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    account_id: str,
    member_ref: str,
    platform_role: str,
) -> dict[str, Any] | JSONResponse:
    try:
        result = commercial_service.disable_admin_account_member(
            account_id=account_id,
            member_ref=member_ref,
            platform_role=platform_role,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        if error.error_code == "service.account_membership_not_found":
            return json_error(
                request,
                404,
                "admin.member_not_found",
                "member was not found",
            )
        return json_error(
            request,
            error.status_code,
            error.error_code,
            error.message,
        )

    return build_envelope(
        status="ok",
        message=(
            "portal member already disabled"
            if str(result.get("status") or "") == "disabled"
            and not result.get("disabled_at")
            else "portal member disabled"
        ),
        data=result,
        revision="m6",
    )


def enable_admin_account_member(
    *,
    request: Request,
    json_error: JsonErrorBuilder,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    account_id: str,
    member_ref: str,
    platform_role: str,
) -> dict[str, Any] | JSONResponse:
    try:
        result = commercial_service.enable_admin_account_member(
            account_id=account_id,
            member_ref=member_ref,
            platform_role=platform_role,
            audit_context=audit_context,
        )
    except CommercialServiceError as error:
        if error.error_code == "service.account_membership_not_found":
            return json_error(
                request,
                404,
                "admin.member_not_found",
                "member was not found",
            )
        return json_error(
            request,
            error.status_code,
            error.error_code,
            error.message,
        )

    return build_envelope(
        status="ok",
        message=(
            "portal member already active"
            if str(result.get("status") or "") == "active"
            and not result.get("enabled_at")
            else "portal member enabled"
        ),
        data=result,
        revision="m6",
    )


def upsert_admin_provider_connection(
    *,
    request: Request,
    json_error: JsonErrorBuilder,
    catalog_service: CatalogService,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    connection_id: str,
    provider_type: str,
    source_role: str | None,
    display_name: str,
    enabled: bool,
    base_url: str,
    config: dict[str, Any] | None,
    api_key: str | None,
) -> dict[str, Any] | JSONResponse:
    try:
        result = catalog_service.upsert_admin_provider_connection(
            connection_id=connection_id,
            provider_type=provider_type,
            source_role=source_role,
            display_name=display_name,
            enabled=enabled,
            base_url=base_url,
            config=config,
            api_key=api_key,
        )
    except ValueError as error:
        return json_error(
            request,
            400,
            "admin.provider_connection_invalid",
            str(error),
        )
    except RuntimeError as error:
        return json_error(
            request,
            503,
            "admin.provider_connection_unavailable",
            str(error),
        )

    commercial_service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="provider_connection.upsert",
        outcome="succeeded",
        scope_kind="provider_connection",
        scope_id=connection_id,
        payload_json={"connection": result},
    )
    return build_envelope(
        status="ok",
        message="provider connection saved",
        data=result,
        revision="m6",
    )


def test_admin_provider_connection(
    *,
    request: Request,
    json_error: JsonErrorBuilder,
    catalog_service: CatalogService,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    connection_id: str,
) -> dict[str, Any] | JSONResponse:
    try:
        result = catalog_service.test_admin_provider_connection(connection_id)
    except ValueError as error:
        return json_error(
            request,
            400,
            "admin.provider_connection_invalid",
            str(error),
        )
    except RuntimeError as error:
        return json_error(
            request,
            503,
            "admin.provider_connection_unavailable",
            str(error),
        )
    except Exception as error:
        return json_error(
            request,
            502,
            "admin.provider_connection_test_failed",
            str(error),
        )
    if result is None:
        return json_error(
            request,
            404,
            "admin.provider_connection_not_found",
            "provider connection was not found",
        )

    commercial_service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="provider_connection.test",
        outcome="succeeded",
        scope_kind="provider_connection",
        scope_id=connection_id,
        payload_json=result,
    )
    return build_envelope(
        status="ok",
        message="provider connection tested",
        data=result,
        revision="m6",
    )


def sync_admin_provider_connection_catalog(
    *,
    request: Request,
    json_error: JsonErrorBuilder,
    catalog_service: CatalogService,
    commercial_service: CommercialService,
    audit_context: ServiceAuditContext,
    connection_id: str,
) -> dict[str, Any] | JSONResponse:
    try:
        result = catalog_service.sync_admin_provider_connection_catalog(connection_id)
    except ValueError as error:
        return json_error(
            request,
            400,
            "admin.provider_connection_invalid",
            str(error),
        )
    except RuntimeError as error:
        return json_error(
            request,
            503,
            "admin.provider_connection_unavailable",
            str(error),
        )
    except Exception as error:
        return json_error(
            request,
            502,
            "admin.provider_connection_sync_failed",
            str(error),
        )
    if result is None:
        return json_error(
            request,
            404,
            "admin.provider_connection_not_found",
            "provider connection was not found",
        )

    commercial_service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="provider_connection.sync",
        outcome="succeeded",
        scope_kind="provider_connection",
        scope_id=connection_id,
        payload_json=result,
    )
    return build_envelope(
        status="ok",
        message="provider connection synced",
        data=result,
        revision="m6",
    )
