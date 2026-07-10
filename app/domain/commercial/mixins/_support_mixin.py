"""Commercial service: bounded customer support requests."""

from __future__ import annotations

import base64
import binascii
from typing import TYPE_CHECKING
from uuid import uuid4

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import get_session
from app.core.models import (
    ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
    SUPPORT_REQUEST_ATTACHMENT_UPLOADER_CUSTOMER,
    SUPPORT_REQUEST_ATTACHMENT_UPLOADER_OPERATOR,
    SUPPORT_REQUEST_MESSAGE_AUTHOR_CUSTOMER,
    SUPPORT_REQUEST_MESSAGE_AUTHOR_OPERATOR,
    SUPPORT_REQUEST_MESSAGE_VISIBILITY_INTERNAL,
    SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC,
    SUPPORT_REQUEST_STATUS_CLOSED,
    SUPPORT_REQUEST_STATUS_IN_PROGRESS,
    SUPPORT_REQUEST_STATUS_OPEN,
    SUPPORT_REQUEST_STATUS_RESOLVED,
    SupportRequest,
    SupportRequestAttachment,
    SupportRequestFeedback,
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
SUPPORT_REQUEST_ATTACHMENT_CONTENT_TYPES = {
    "application/json",
    "application/pdf",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/csv",
    "text/plain",
}
SUPPORT_REQUEST_ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024
SUPPORT_REQUEST_ATTACHMENT_MAX_COUNT = 10


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


def _normalize_support_attachment_filename(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    normalized = " ".join(normalized.split())
    if not normalized:
        raise CommercialValidationError(
            "service.support_request_attachment_filename_required",
            "support request attachment filename is required",
        )
    return normalized[:191]


def _normalize_support_attachment_content_type(value: str) -> str:
    normalized = str(value or "").strip().lower().split(";", 1)[0]
    if normalized not in SUPPORT_REQUEST_ATTACHMENT_CONTENT_TYPES:
        raise CommercialValidationError(
            "service.support_request_attachment_content_type_invalid",
            "support request attachment content type is not supported",
        )
    return normalized


def _decode_support_attachment_content(value: str) -> bytes:
    raw_value = str(value or "").strip()
    if "," in raw_value and raw_value.lower().startswith("data:"):
        raw_value = raw_value.split(",", 1)[1]
    try:
        content = base64.b64decode(raw_value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise CommercialValidationError(
            "service.support_request_attachment_invalid",
            "support request attachment content is invalid",
        ) from error
    if not content:
        raise CommercialValidationError(
            "service.support_request_attachment_empty",
            "support request attachment is empty",
        )
    if len(content) > SUPPORT_REQUEST_ATTACHMENT_MAX_BYTES:
        raise CommercialValidationError(
            "service.support_request_attachment_too_large",
            "support request attachment is too large",
        )
    return content


class CommercialServiceSupportMixin(CommercialServiceAuditMixin):
    if TYPE_CHECKING:
        def resolve_portal_site_access(
            self,
            *,
            site_id: str,
            principal_id: str,
        ) -> dict[str, object]: ...

        def get_portal_principal_profile(
            self,
            *,
            principal_id: str,
        ) -> dict[str, object]: ...

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
            attachments = repository.list_support_request_attachments(
                request_id=str(request.request_id or ""),
                include_internal=False,
            )
            feedback = repository.get_support_request_feedback(str(request.request_id or ""))
            return {
                "request": self._serialize_support_request(request),
                "messages": [
                    self._serialize_support_request_message(message) for message in messages
                ],
                "attachments": [
                    self._serialize_support_request_attachment(attachment)
                    for attachment in attachments
                ],
                "feedback": self._serialize_support_request_feedback(feedback)
                if feedback is not None
                else None,
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
            attachments = repository.list_support_request_attachments(
                request_id=str(request.request_id or ""),
                include_internal=True,
            )
            feedback = repository.get_support_request_feedback(str(request.request_id or ""))
            return {
                "request": self._serialize_support_request(request),
                "messages": [
                    self._serialize_support_request_message(message) for message in messages
                ],
                "attachments": [
                    self._serialize_support_request_attachment(attachment)
                    for attachment in attachments
                ],
                "feedback": self._serialize_support_request_feedback(feedback)
                if feedback is not None
                else None,
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
            payload: dict[str, object] = {
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
            payload: dict[str, object] = {
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

    def create_portal_support_request_attachment(
        self,
        *,
        principal_id: str,
        request_id: str,
        filename: str,
        content_type: str,
        content_base64: str,
        message_id: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_principal_id = str(principal_id or "").strip()
        normalized_filename = _normalize_support_attachment_filename(filename)
        normalized_content_type = _normalize_support_attachment_content_type(content_type)
        content = _decode_support_attachment_content(content_base64)
        normalized_message_id = str(message_id or "").strip()
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
            if (
                repository.count_support_request_attachments(
                    request_id=str(request.request_id or "")
                )
                >= SUPPORT_REQUEST_ATTACHMENT_MAX_COUNT
            ):
                raise CommercialValidationError(
                    "service.support_request_attachment_limit_reached",
                    "support request attachment limit reached",
                )
            attachment = repository.create_support_request_attachment(
                attachment_id=f"sra_{uuid4().hex}",
                request=request,
                message_id=normalized_message_id or None,
                uploader_kind=SUPPORT_REQUEST_ATTACHMENT_UPLOADER_CUSTOMER,
                visibility=SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC,
                principal_id=normalized_principal_id,
                email=str(request.email or ""),
                filename=normalized_filename,
                content_type=normalized_content_type,
                content_bytes=content,
                metadata_json={"source": "portal_upload"},
            )
            payload: dict[str, object] = {
                "request": self._serialize_support_request(request),
                "attachment": self._serialize_support_request_attachment(attachment),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="support_request.attachment_created",
                outcome="succeeded",
                account_id=str(request.account_id or ""),
                site_id=str(request.site_id or ""),
                scope_kind="support_request",
                scope_id=str(request.request_id),
                payload_json={
                    "request_id": str(request.request_id),
                    "attachment_id": str(attachment.attachment_id),
                    "visibility": str(attachment.visibility),
                    "byte_size": int(attachment.byte_size or 0),
                    "content_type": str(attachment.content_type or ""),
                    "created_at": self._serialize_datetime(now),
                },
            )
            session.commit()
        return payload

    def create_admin_support_request_attachment(
        self,
        *,
        request_id: str,
        filename: str,
        content_type: str,
        content_base64: str,
        visibility: str = SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC,
        message_id: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_visibility = _normalize_support_message_visibility(visibility)
        normalized_filename = _normalize_support_attachment_filename(filename)
        normalized_content_type = _normalize_support_attachment_content_type(content_type)
        content = _decode_support_attachment_content(content_base64)
        normalized_message_id = str(message_id or "").strip()
        now = self.now_factory()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.get_support_request(str(request_id or "").strip())
            if request is None:
                raise CommercialNotFoundError(
                    "service.support_request_not_found",
                    "support request was not found",
                )
            if (
                repository.count_support_request_attachments(
                    request_id=str(request.request_id or "")
                )
                >= SUPPORT_REQUEST_ATTACHMENT_MAX_COUNT
            ):
                raise CommercialValidationError(
                    "service.support_request_attachment_limit_reached",
                    "support request attachment limit reached",
                )
            attachment = repository.create_support_request_attachment(
                attachment_id=f"sra_{uuid4().hex}",
                request=request,
                message_id=normalized_message_id or None,
                uploader_kind=SUPPORT_REQUEST_ATTACHMENT_UPLOADER_OPERATOR,
                visibility=normalized_visibility,
                principal_id=None,
                email="",
                filename=normalized_filename,
                content_type=normalized_content_type,
                content_bytes=content,
                metadata_json={"source": "admin_upload"},
            )
            payload: dict[str, object] = {
                "request": self._serialize_support_request(request),
                "attachment": self._serialize_support_request_attachment(attachment),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="support_request.attachment_created",
                outcome="succeeded",
                account_id=str(request.account_id or ""),
                site_id=str(request.site_id or ""),
                scope_kind="support_request",
                scope_id=str(request.request_id),
                payload_json={
                    "request_id": str(request.request_id),
                    "attachment_id": str(attachment.attachment_id),
                    "visibility": str(attachment.visibility),
                    "byte_size": int(attachment.byte_size or 0),
                    "content_type": str(attachment.content_type or ""),
                    "created_at": self._serialize_datetime(now),
                },
            )
            session.commit()
        return payload

    def get_portal_support_request_attachment(
        self,
        *,
        principal_id: str,
        request_id: str,
        attachment_id: str,
    ) -> dict[str, object]:
        normalized_principal_id = str(principal_id or "").strip()
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.get_support_request(str(request_id or "").strip())
            attachment = repository.get_support_request_attachment(
                str(attachment_id or "").strip()
            )
            if (
                request is None
                or attachment is None
                or attachment.request_id != request.request_id
                or request.principal_id != normalized_principal_id
                or attachment.visibility != SUPPORT_REQUEST_MESSAGE_VISIBILITY_PUBLIC
            ):
                raise CommercialNotFoundError(
                    "service.support_request_attachment_not_found",
                    "support request attachment was not found",
                )
            self._assert_portal_account_access_in_session(
                repository=repository,
                principal_id=normalized_principal_id,
                account_id=str(request.account_id or ""),
            )
            return {
                "attachment": self._serialize_support_request_attachment(
                    attachment,
                    include_content=True,
                )
            }

    def get_admin_support_request_attachment(
        self,
        *,
        request_id: str,
        attachment_id: str,
    ) -> dict[str, object]:
        with get_session(self.database_url) as session:
            repository = CommercialRepository(session)
            request = repository.get_support_request(str(request_id or "").strip())
            attachment = repository.get_support_request_attachment(
                str(attachment_id or "").strip()
            )
            if request is None or attachment is None or attachment.request_id != request.request_id:
                raise CommercialNotFoundError(
                    "service.support_request_attachment_not_found",
                    "support request attachment was not found",
                )
            return {
                "attachment": self._serialize_support_request_attachment(
                    attachment,
                    include_content=True,
                )
            }

    def submit_portal_support_request_feedback(
        self,
        *,
        principal_id: str,
        request_id: str,
        resolved: bool,
        rating: int,
        comment: str = "",
        audit_context: ServiceAuditContext | None = None,
    ) -> dict[str, object]:
        normalized_principal_id = str(principal_id or "").strip()
        normalized_rating = max(1, min(5, int(rating or 0)))
        normalized_comment = _trim_support_text(comment, max_length=2000)
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
            if str(request.status or "") not in {
                SUPPORT_REQUEST_STATUS_RESOLVED,
                SUPPORT_REQUEST_STATUS_CLOSED,
            }:
                raise CommercialValidationError(
                    "service.support_request_feedback_not_available",
                    "support request feedback is available after support marks it resolved",
                )
            request.status = (
                SUPPORT_REQUEST_STATUS_CLOSED if bool(resolved) else SUPPORT_REQUEST_STATUS_OPEN
            )
            request.closed_at = now if bool(resolved) else None
            request.resolved_at = request.resolved_at if bool(resolved) else None
            feedback = repository.upsert_support_request_feedback(
                feedback_id=f"srf_{uuid4().hex}",
                request=request,
                principal_id=normalized_principal_id,
                email=str(request.email or ""),
                resolved=bool(resolved),
                rating=normalized_rating,
                comment=normalized_comment,
                metadata_json={"source": "portal_close_evaluation"},
            )
            payload: dict[str, object] = {
                "request": self._serialize_support_request(request),
                "feedback": self._serialize_support_request_feedback(feedback),
            }
            self._record_service_audit_in_session(
                repository=repository,
                audit_context=audit_context,
                event_kind="support_request.feedback_submitted",
                outcome="succeeded",
                account_id=str(request.account_id or ""),
                site_id=str(request.site_id or ""),
                scope_kind="support_request",
                scope_id=str(request.request_id),
                payload_json={
                    "request_id": str(request.request_id),
                    "feedback_id": str(feedback.feedback_id),
                    "resolved": bool(feedback.resolved),
                    "rating": int(feedback.rating or 0),
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

    def _serialize_support_request_attachment(
        self,
        attachment: SupportRequestAttachment,
        *,
        include_content: bool = False,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "attachment_id": str(attachment.attachment_id or ""),
            "request_id": str(attachment.request_id or ""),
            "message_id": str(attachment.message_id or ""),
            "account_id": str(attachment.account_id or ""),
            "site_id": str(attachment.site_id or ""),
            "principal_id": str(attachment.principal_id or ""),
            "email": str(attachment.email or ""),
            "uploader_kind": str(attachment.uploader_kind or ""),
            "visibility": str(attachment.visibility or ""),
            "filename": str(attachment.filename or ""),
            "content_type": str(attachment.content_type or ""),
            "byte_size": int(attachment.byte_size or 0),
            "metadata": attachment.metadata_json
            if isinstance(attachment.metadata_json, dict)
            else {},
            "created_at": self._serialize_datetime(attachment.created_at),
        }
        if include_content:
            payload["content_base64"] = base64.b64encode(
                bytes(attachment.content_bytes or b"")
            ).decode("ascii")
        return payload

    def _serialize_support_request_feedback(
        self,
        feedback: SupportRequestFeedback,
    ) -> dict[str, object]:
        return {
            "feedback_id": str(feedback.feedback_id or ""),
            "request_id": str(feedback.request_id or ""),
            "account_id": str(feedback.account_id or ""),
            "site_id": str(feedback.site_id or ""),
            "principal_id": str(feedback.principal_id or ""),
            "email": str(feedback.email or ""),
            "resolved": bool(feedback.resolved),
            "rating": int(feedback.rating or 0),
            "comment": str(feedback.comment or ""),
            "metadata": feedback.metadata_json if isinstance(feedback.metadata_json, dict) else {},
            "created_at": self._serialize_datetime(feedback.created_at),
            "updated_at": self._serialize_datetime(feedback.updated_at),
        }
