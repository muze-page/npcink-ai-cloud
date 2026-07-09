"""Commercial service: bounded customer support requests."""

from __future__ import annotations

from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
    SUPPORT_REQUEST_MESSAGE_AUTHOR_CUSTOMER,
    SUPPORT_REQUEST_MESSAGE_AUTHOR_OPERATOR,
    SUPPORT_REQUEST_MESSAGE_VISIBILITY_INTERNAL,
    SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC,
    SUPPORT_REQUEST_STATUS_CLOSED,
    SUPPORT_REQUEST_STATUS_IN_PROGRESS,
    SUPPORT_REQUEST_STATUS_OPEN,
    SUPPORT_REQUEST_STATUS_RESOLVED,
    SupportRequest,
    SupportRequestMessage,
)
from app.domain.commercial.audit_context import ServiceAuditContext
from app.domain.commercial.errors import (
    CommercialNotFoundError,
    CommercialPermissionError,
    CommercialValidationError,
)
from app.domain.commercial.mixins._audit_mixin import CommercialServiceAuditMixin

SUPPORT_REQUEST_STATUSES = {
    SUPPORT_REQUEST_STATUS_OPEN,
    SUPPORT_REQUEST_STATUS_IN_PROGRESS,
    SUPPORT_REQUEST_STATUS_RESOLVED,
    SUPPORT_REQUEST_STATUS_CLOSED,
}
SUPPORT_REQUEST_TOPICS = {
    "general",
    "billing",
    "payment",
    "site",
    "usage",
    "account",
}
SUPPORT_REQUEST_MESSAGE_VISIBILITIES = {
    SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC,
    SUPPORT_REQUEST_MESSAGE_VISIBILITY_INTERNAL,
}


def _normalize_support_status(value: str, *, allow_empty: bool = False) -> str:
    normalized = str(value or "").strip().lower()
    if allow_empty and not normalized:
        return ""
    if normalized not in SUPPORT_REQUEST_STATUSES:
        raise CommercialValidationError(
            "service.support_request_status_invalid",
            "support request status is not supported",
        )
    return normalized


def _normalize_support_topic(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in SUPPORT_REQUEST_TOPICS else "general"


def _trim_support_text(value: str, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _normalize_support_message_visibility(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in SUPPORT_REQUEST_MESSAGE_VISIBILITIES:
        raise CommercialValidationError(
            "service.support_request_message_visibility_invalid",
            "support request message visibility is not supported",
        )
    return normalized


class CommercialServiceSupportMixin(CommercialServiceAuditMixin):
    def create_portal_support_request(
        self,
        *,
        principal_id: str,
        account_id: str,
        site_id: str = "",
        topic: str = "general",
        title: str,
        description: str,
        source_path: str = "",
        context_json: dict[str, object] | None = None,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_principal_id = str(principal_id or "").strip()
        normalized_account_id = str(account_id or "").strip()
        normalized_site_id = str(site_id or "").strip()
        normalized_title = _trim_support_text(title, max_length=191)
        normalized_description = _trim_support_text(description, max_length=4000)
        if not normalized_title:
            raise CommercialValidationError(
                "service.support_request_title_required",
                "support request title is required",
            )
        if len(normalized_description) < 10:
            raise CommercialValidationError(
                "service.support_request_description_required",
                "support request description is required",
            )
        if not normalized_principal_id:
            raise CommercialPermissionError(
                "service.principal_access_required",
                "portal principal is required",
            )
        if normalized_site_id:
            access = self.resolve_portal_site_access(
                site_id=normalized_site_id,
                principal_id=normalized_principal_id,
            )
            normalized_account_id = str(access.get("account_id") or "").strip()
        self._assert_portal_account_access(
            principal_id=normalized_principal_id,
            account_id=normalized_account_id,
        )
        profile = self.get_portal_principal_profile(principal_id=normalized_principal_id)
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.create_support_request(
                request_id=f"sr_{uuid4().hex}",
                account_id=normalized_account_id,
                site_id=normalized_site_id or None,
                principal_id=normalized_principal_id,
                email=str(profile.get("email") or ""),
                topic=_normalize_support_topic(topic),
                title=normalized_title,
                description=normalized_description,
                status=SUPPORT_REQUEST_STATUS_OPEN,
                priority="normal",
                source_path=_trim_support_text(source_path, max_length=191),
                context_json=dict(context_json or {}),
            )
            repository.create_support_request_message(
                message_id=f"srm_{uuid4().hex}",
                request=request,
                author_kind=SUPPORT_REQUEST_MESSAGE_AUTHOR_CUSTOMER,
                visibility=SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC,
                principal_id=normalized_principal_id,
                email=str(profile.get("email") or ""),
                body=normalized_description,
                metadata_json={"source": "initial_description"},
            )
            payload = self._serialize_support_request(request)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="support_request.created",
                outcome="succeeded",
                account_id=normalized_account_id,
                site_id=normalized_site_id,
                scope_kind="support_request",
                scope_id=str(request.request_id),
                payload_json={
                    "request_id": str(request.request_id),
                    "topic": str(request.topic),
                    "status": str(request.status),
                    "source_path": str(request.source_path or ""),
                    "created_at": self._serialize_datetime(now),
                },
            )
            session.commit()
        return payload

    def list_portal_support_requests(
        self,
        *,
        principal_id: str,
        account_id: str,
        status: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, object]:
        normalized_principal_id = str(principal_id or "").strip()
        normalized_account_id = str(account_id or "").strip()
        self._assert_portal_account_access(
            principal_id=normalized_principal_id,
            account_id=normalized_account_id,
        )
        normalized_status = _normalize_support_status(status, allow_empty=True)
        safe_limit = max(1, min(100, int(limit or 20)))
        safe_offset = max(0, int(offset or 0))
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            items = repository.list_support_requests(
                account_id=normalized_account_id,
                principal_id=normalized_principal_id,
                status=normalized_status or None,
                limit=safe_limit,
                offset=safe_offset,
            )
            total = repository.count_support_requests(
                account_id=normalized_account_id,
                principal_id=normalized_principal_id,
                status=normalized_status or None,
            )
            open_count = repository.count_support_requests(
                account_id=normalized_account_id,
                principal_id=normalized_principal_id,
                status=SUPPORT_REQUEST_STATUS_OPEN,
            )
        return {
            "account_id": normalized_account_id,
            "principal_id": normalized_principal_id,
            "items": [self._serialize_support_request(item) for item in items],
            "pagination": {
                "limit": safe_limit,
                "offset": safe_offset,
                "total": total,
                "has_more": safe_offset + len(items) < total,
            },
            "summary": {
                "open": open_count,
            },
        }

    def get_portal_support_request(
        self,
        *,
        principal_id: str,
        request_id: str,
    ) -> dict[str, object]:
        normalized_principal_id = str(principal_id or "").strip()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.get_support_request(str(request_id or "").strip())
            if request is None or request.principal_id != normalized_principal_id:
                raise CommercialNotFoundError(
                    "service.support_request_not_found",
                    "support request was not found",
                )
            self._assert_portal_account_access_in_session(
                repository=repository,
                principal_id=normalized_principal_id,
                account_id=str(request.account_id or ""),
            )
            messages = repository.list_support_request_messages(
                request_id=str(request.request_id or ""),
                include_internal=False,
            )
            return {
                "request": self._serialize_support_request(request),
                "messages": [
                    self._serialize_support_request_message(message) for message in messages
                ],
            }

    def list_admin_support_requests(
        self,
        *,
        status: str = "",
        topic: str = "",
        query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        normalized_status = _normalize_support_status(status, allow_empty=True)
        normalized_topic = _normalize_support_topic(topic) if str(topic or "").strip() else ""
        safe_limit = max(1, min(200, int(limit or 100)))
        safe_offset = max(0, int(offset or 0))
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            items = repository.list_support_requests(
                status=normalized_status or None,
                topic=normalized_topic or None,
                query=query,
                limit=safe_limit,
                offset=safe_offset,
            )
            total = repository.count_support_requests(
                status=normalized_status or None,
                topic=normalized_topic or None,
                query=query,
            )
            open_count = repository.count_support_requests(status=SUPPORT_REQUEST_STATUS_OPEN)
            in_progress_count = repository.count_support_requests(
                status=SUPPORT_REQUEST_STATUS_IN_PROGRESS
            )
        return {
            "items": [self._serialize_support_request(item) for item in items],
            "pagination": {
                "limit": safe_limit,
                "offset": safe_offset,
                "total": total,
                "has_more": safe_offset + len(items) < total,
            },
            "summary": {
                "open": open_count,
                "in_progress": in_progress_count,
            },
        }

    def get_admin_support_request(
        self,
        *,
        request_id: str,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.get_support_request(str(request_id or "").strip())
            if request is None:
                raise CommercialNotFoundError(
                    "service.support_request_not_found",
                    "support request was not found",
                )
            messages = repository.list_support_request_messages(
                request_id=str(request.request_id or ""),
                include_internal=True,
            )
            return {
                "request": self._serialize_support_request(request),
                "messages": [
                    self._serialize_support_request_message(message) for message in messages
                ],
            }

    def create_portal_support_request_message(
        self,
        *,
        principal_id: str,
        request_id: str,
        body: str,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_principal_id = str(principal_id or "").strip()
        normalized_body = _trim_support_text(body, max_length=4000)
        if len(normalized_body) < 2:
            raise CommercialValidationError(
                "service.support_request_message_required",
                "support request message is required",
            )
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.get_support_request(str(request_id or "").strip())
            if request is None or request.principal_id != normalized_principal_id:
                raise CommercialNotFoundError(
                    "service.support_request_not_found",
                    "support request was not found",
                )
            self._assert_portal_account_access_in_session(
                repository=repository,
                principal_id=normalized_principal_id,
                account_id=str(request.account_id or ""),
            )
            if str(request.status or "") in {
                SUPPORT_REQUEST_STATUS_RESOLVED,
                SUPPORT_REQUEST_STATUS_CLOSED,
            }:
                request.status = SUPPORT_REQUEST_STATUS_OPEN
                request.resolved_at = None
                request.closed_at = None
            message = repository.create_support_request_message(
                message_id=f"srm_{uuid4().hex}",
                request=request,
                author_kind=SUPPORT_REQUEST_MESSAGE_AUTHOR_CUSTOMER,
                visibility=SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC,
                principal_id=normalized_principal_id,
                email=str(request.email or ""),
                body=normalized_body,
                metadata_json={"source": "portal_reply"},
            )
            payload = {
                "request": self._serialize_support_request(request),
                "message": self._serialize_support_request_message(message),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="support_request.message_created",
                outcome="succeeded",
                account_id=str(request.account_id or ""),
                site_id=str(request.site_id or ""),
                scope_kind="support_request",
                scope_id=str(request.request_id),
                payload_json={
                    "request_id": str(request.request_id),
                    "message_id": str(message.message_id),
                    "author_kind": str(message.author_kind),
                    "visibility": str(message.visibility),
                    "status": str(request.status or ""),
                    "created_at": self._serialize_datetime(now),
                },
            )
            session.commit()
        return payload

    def create_admin_support_request_message(
        self,
        *,
        request_id: str,
        body: str,
        visibility: str = SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC,
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_visibility = _normalize_support_message_visibility(visibility)
        normalized_body = _trim_support_text(body, max_length=4000)
        if len(normalized_body) < 2:
            raise CommercialValidationError(
                "service.support_request_message_required",
                "support request message is required",
            )
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.get_support_request(str(request_id or "").strip())
            if request is None:
                raise CommercialNotFoundError(
                    "service.support_request_not_found",
                    "support request was not found",
                )
            if normalized_visibility == SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC and (
                str(request.status or "") == SUPPORT_REQUEST_STATUS_OPEN
            ):
                request.status = SUPPORT_REQUEST_STATUS_IN_PROGRESS
            if normalized_visibility == SUPPORT_REQUEST_MESSAGE_VISIBILITY_INTERNAL:
                request.admin_note = normalized_body
            message = repository.create_support_request_message(
                message_id=f"srm_{uuid4().hex}",
                request=request,
                author_kind=SUPPORT_REQUEST_MESSAGE_AUTHOR_OPERATOR,
                visibility=normalized_visibility,
                principal_id=None,
                email="",
                body=normalized_body,
                metadata_json={"source": "admin_reply"},
            )
            payload = {
                "request": self._serialize_support_request(request),
                "message": self._serialize_support_request_message(message),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="support_request.message_created",
                outcome="succeeded",
                account_id=str(request.account_id or ""),
                site_id=str(request.site_id or ""),
                scope_kind="support_request",
                scope_id=str(request.request_id),
                payload_json={
                    "request_id": str(request.request_id),
                    "message_id": str(message.message_id),
                    "author_kind": str(message.author_kind),
                    "visibility": str(message.visibility),
                    "status": str(request.status or ""),
                    "created_at": self._serialize_datetime(now),
                },
            )
            session.commit()
        return payload

    def update_admin_support_request(
        self,
        *,
        request_id: str,
        status: str = "",
        admin_note: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_status = _normalize_support_status(status, allow_empty=True)
        normalized_note = _trim_support_text(admin_note, max_length=2000)
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.get_support_request(str(request_id or "").strip())
            if request is None:
                raise CommercialNotFoundError(
                    "service.support_request_not_found",
                    "support request was not found",
                )
            previous_status = str(request.status or "")
            if normalized_status:
                request.status = normalized_status
                request.resolved_at = (
                    now if normalized_status == SUPPORT_REQUEST_STATUS_RESOLVED else None
                )
                request.closed_at = (
                    now if normalized_status == SUPPORT_REQUEST_STATUS_CLOSED else None
                )
            if normalized_note:
                request.admin_note = normalized_note
                repository.create_support_request_message(
                    message_id=f"srm_{uuid4().hex}",
                    request=request,
                    author_kind=SUPPORT_REQUEST_MESSAGE_AUTHOR_OPERATOR,
                    visibility=SUPPORT_REQUEST_MESSAGE_VISIBILITY_INTERNAL,
                    principal_id=None,
                    email="",
                    body=normalized_note,
                    metadata_json={"source": "admin_status_update"},
                )
            session.flush()
            payload = self._serialize_support_request(request)
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="support_request.updated",
                outcome="succeeded",
                account_id=str(request.account_id or ""),
                site_id=str(request.site_id or ""),
                scope_kind="support_request",
                scope_id=str(request.request_id),
                payload_json={
                    "request_id": str(request.request_id),
                    "previous_status": previous_status,
                    "status": str(request.status or ""),
                    "has_admin_note": bool(request.admin_note),
                },
            )
            session.commit()
        return payload

    def _assert_portal_account_access(
        self,
        *,
        principal_id: str,
        account_id: str,
    ) -> None:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            self._assert_portal_account_access_in_session(
                repository=repository,
                principal_id=principal_id,
                account_id=account_id,
            )

    def _assert_portal_account_access_in_session(
        self,
        *,
        repository: CommercialRepository,
        principal_id: str,
        account_id: str,
    ) -> None:
        normalized_account_id = str(account_id or "").strip()
        if not normalized_account_id:
            raise CommercialPermissionError(
                "service.portal_account_required",
                "portal account access is required",
            )
        membership_row = repository.get_account_user_membership(
            principal_id=str(principal_id or "").strip(),
            account_id=normalized_account_id,
        )
        if membership_row is None:
            raise CommercialPermissionError(
                "service.principal_access_required",
                f"principal '{principal_id}' is not active for account '{normalized_account_id}'",
            )
        account, identity, membership = membership_row
        if (
            str(getattr(account, "status", "") or "") != "active"
            or str(getattr(identity, "status", "") or "") != "active"
            or str(getattr(membership, "status", "") or "") != ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE
        ):
            raise CommercialPermissionError(
                "service.principal_access_required",
                f"principal '{principal_id}' is not active for account '{normalized_account_id}'",
            )

    def _serialize_support_request(self, request: SupportRequest) -> dict[str, object]:
        return {
            "request_id": str(request.request_id or ""),
            "account_id": str(request.account_id or ""),
            "site_id": str(request.site_id or ""),
            "principal_id": str(request.principal_id or ""),
            "email": str(request.email or ""),
            "topic": str(request.topic or ""),
            "title": str(request.title or ""),
            "description": str(request.description or ""),
            "status": str(request.status or ""),
            "priority": str(request.priority or ""),
            "source_path": str(request.source_path or ""),
            "admin_note": str(request.admin_note or ""),
            "context": request.context_json if isinstance(request.context_json, dict) else {},
            "created_at": self._serialize_datetime(request.created_at),
            "updated_at": self._serialize_datetime(request.updated_at),
            "resolved_at": self._serialize_datetime(request.resolved_at),
            "closed_at": self._serialize_datetime(request.closed_at),
        }

    def _serialize_support_request_message(
        self,
        message: SupportRequestMessage,
    ) -> dict[str, object]:
        return {
            "message_id": str(message.message_id or ""),
            "request_id": str(message.request_id or ""),
            "account_id": str(message.account_id or ""),
            "site_id": str(message.site_id or ""),
            "principal_id": str(message.principal_id or ""),
            "email": str(message.email or ""),
            "author_kind": str(message.author_kind or ""),
            "visibility": str(message.visibility or ""),
            "body": str(message.body or ""),
            "metadata": message.metadata_json if isinstance(message.metadata_json, dict) else {},
            "created_at": self._serialize_datetime(message.created_at),
        }
