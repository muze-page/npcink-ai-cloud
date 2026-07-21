from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.adapters.callbacks.base import (
    RuntimeCallbackDispatcher,
    RuntimeCallbackDispatchError,
    RuntimeCallbackDispatchRequest,
)
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import RunRecord
from app.core.secrets import decrypt_runtime_terminal_callback_secret
from app.domain.media_artifacts.projection import project_media_artifact_lifecycle
from app.domain.runtime.errors import RuntimeCallbackConfigurationError
from app.domain.runtime.models import RUNTIME_CALLBACK_EVENT, RuntimeRequest
from app.domain.runtime.run_projection import RuntimeRunProjector


class RecoveryAuditCallback(Protocol):
    def __call__(self, run: RunRecord, *, recovered_at: datetime) -> None: ...


class RuntimeCallbackDeliveryService:
    """Owns hosted runtime callback delivery and its bounded state transitions."""

    def __init__(
        self,
        *,
        database_url: str,
        settings: Settings,
        dispatcher: RuntimeCallbackDispatcher | None,
        max_attempts: int = 3,
        retry_backoff_seconds: int = 30,
        run_projector: RuntimeRunProjector | None = None,
        recovery_audit_callback: RecoveryAuditCallback | None = None,
    ) -> None:
        self.database_url = database_url
        self.settings = settings
        self.dispatcher = dispatcher
        self.max_attempts = max(1, max_attempts)
        self.retry_backoff_seconds = max(0, retry_backoff_seconds)
        self.run_projector = run_projector or RuntimeRunProjector()
        self.recovery_audit_callback = recovery_audit_callback

    def resolve_callback_target(
        self,
        *,
        site: Any,
        request: RuntimeRequest,
        callback_mode: str,
    ) -> dict[str, object]:
        registered = self._resolve_registered_callback_config(site)
        requires_callback = callback_mode in {
            "polling_preferred",
            "terminal_callback_required",
        }
        if request.callback_url:
            raise RuntimeCallbackConfigurationError(
                request.site_id,
                "runtime callback_url overrides are not accepted; "
                "register runtime_callbacks.terminal on the site instead",
            )
        if not requires_callback:
            return {}
        if not bool(registered.get("enabled")):
            if callback_mode == "terminal_callback_required":
                raise RuntimeCallbackConfigurationError(
                    request.site_id,
                    "terminal callback is disabled for the site",
                )
            return {}
        callback_url = str(registered.get("callback_url") or "").strip()
        key_id = str(registered.get("key_id") or "").strip()
        secret = str(registered.get("secret") or "").strip()
        secret_error = str(registered.get("secret_error") or "").strip()
        if secret_error:
            raise RuntimeCallbackConfigurationError(request.site_id, secret_error)
        if not callback_url or not key_id or not secret:
            if callback_mode == "terminal_callback_required":
                raise RuntimeCallbackConfigurationError(
                    request.site_id,
                    "terminal callback requires registered callback_url, key_id, and secret",
                )
            return {}
        return {
            "source": "site_registered",
            "callback_url": callback_url,
            "key_id": key_id,
            "callback_id": str(registered.get("callback_id") or "runtime_terminal"),
            "registered": True,
        }

    def dispatch_pending_callbacks(
        self,
        *,
        max_callbacks: int = 1,
    ) -> list[dict[str, object]]:
        if self.dispatcher is None:
            return []

        self._recover_stale_callback_dispatches(limit=max(1, max_callbacks))
        dispatched: list[dict[str, object]] = []
        for _ in range(max(1, max_callbacks)):
            result = self._dispatch_single_pending_callback()
            if result is None:
                break
            dispatched.append(result)
        return dispatched

    def _resolve_registered_callback_config(self, site: Any) -> dict[str, object]:
        metadata = getattr(site, "metadata_json", None) or {}
        callbacks = metadata.get("runtime_callbacks")
        callback = callbacks.get("terminal") if isinstance(callbacks, dict) else {}
        callback = callback if isinstance(callback, dict) else {}

        enabled_raw = callback.get("enabled")
        if enabled_raw is None:
            enabled_raw = metadata.get("runtime_terminal_callback_enabled")

        secret_ciphertext = str(callback.get("secret_ciphertext") or "").strip()
        legacy_secret = str(
            callback.get("secret") or metadata.get("runtime_terminal_callback_secret") or ""
        ).strip()
        secret = ""
        secret_error = ""
        if secret_ciphertext:
            try:
                secret = decrypt_runtime_terminal_callback_secret(
                    secret_ciphertext,
                    settings=self.settings,
                )
            except RuntimeError as error:
                secret_error = str(error)
        elif legacy_secret:
            secret_error = (
                "terminal callback secret must be re-saved as ciphertext before hosted callbacks "
                "can run"
            )

        return {
            "enabled": True if enabled_raw is None else bool(enabled_raw),
            "callback_url": str(
                callback.get("callback_url")
                or callback.get("url")
                or metadata.get("runtime_terminal_callback_url")
                or ""
            ).strip(),
            "key_id": str(
                callback.get("key_id")
                or metadata.get("runtime_terminal_callback_key_id")
                or ""
            ).strip(),
            "secret": secret.strip(),
            "secret_error": secret_error.strip(),
            "callback_id": str(
                callback.get("callback_id")
                or metadata.get("runtime_terminal_callback_id")
                or "runtime_terminal"
            ).strip()
            or "runtime_terminal",
        }

    def _dispatch_single_pending_callback(self) -> dict[str, object] | None:
        callback_request = self._claim_next_pending_callback()
        if callback_request is None:
            return None

        attempted_at = datetime.now(UTC)
        dispatcher = self.dispatcher
        if dispatcher is None:
            return None
        try:
            result = dispatcher.dispatch(callback_request)
        except RuntimeCallbackDispatchError as error:
            retry_at = self._resolve_callback_retry_at(
                callback_request.run_id,
                retryable=error.retryable,
                attempted_at=attempted_at,
            )
            with get_session(self.database_url) as session:
                repository = RuntimeRepository(session)
                run = repository.get_run(callback_request.run_id)
                if run is None:
                    session.commit()
                    return None
                repository.mark_callback_delivery_failed(
                    run,
                    error_code=error.error_code,
                    error_message=error.message,
                    retry_at=retry_at,
                )
                session.commit()
                return {
                    "run_id": run.run_id,
                    "callback_status": run.callback_status,
                    "trace_id": run.trace_id,
                }

        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(callback_request.run_id)
            if run is None:
                session.commit()
                return None
            repository.mark_callback_delivered(run, delivered_at=attempted_at)
            session.commit()
            return {
                "run_id": run.run_id,
                "callback_status": run.callback_status,
                "trace_id": run.trace_id,
                "status_code": result.status_code,
            }

    def _claim_next_pending_callback(self) -> RuntimeCallbackDispatchRequest | None:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            due_run_ids = repository.list_due_callback_run_ids(
                limit=1,
                now=datetime.now(UTC),
            )
            if not due_run_ids:
                session.commit()
                return None

            run = repository.claim_callback_dispatch(due_run_ids[0], now=datetime.now(UTC))
            if run is None:
                session.commit()
                return None

            callback_policy = run.policy_json if isinstance(run.policy_json, dict) else {}
            callback_target = self.run_projector.get_callback_target(callback_policy)
            if str(callback_target.get("source") or "") != "site_registered":
                self._mark_callback_config_invalid(
                    repository,
                    run,
                    message="persisted terminal callback target is not site-registered",
                )
                session.commit()
                return None

            site = repository.get_site(run.site_id)
            if site is None:
                self._mark_callback_config_invalid(
                    repository,
                    run,
                    message="registered terminal callback site is unavailable",
                )
                session.commit()
                return None

            registered = self._resolve_registered_callback_config(site)
            registered_callback_url = str(registered.get("callback_url") or "")
            registered_key_id = str(registered.get("key_id") or "")
            registered_secret = str(registered.get("secret") or "")
            registered_callback_id = str(registered.get("callback_id") or "")
            if (
                not bool(registered.get("enabled"))
                or bool(str(registered.get("secret_error") or ""))
                or not registered_callback_url
                or not registered_key_id
                or not registered_secret
                or not registered_callback_id
            ):
                self._mark_callback_config_invalid(
                    repository,
                    run,
                    message="terminal callback registration is disabled or incomplete",
                )
                session.commit()
                return None

            if (
                str(callback_target.get("callback_url") or "")
                != registered_callback_url
                or str(callback_target.get("key_id") or "") != registered_key_id
                or str(callback_target.get("callback_id") or "")
                != registered_callback_id
            ):
                self._mark_callback_config_invalid(
                    repository,
                    run,
                    message=(
                        "persisted terminal callback target no longer matches site registration"
                    ),
                )
                session.commit()
                return None

            payload = self._build_callback_payload(run, session=session)
            session.commit()
            return RuntimeCallbackDispatchRequest(
                run_id=run.run_id,
                trace_id=run.trace_id,
                callback_url=str(callback_target.get("callback_url") or ""),
                payload=payload,
                site_id=run.site_id,
                event=RUNTIME_CALLBACK_EVENT,
                key_id=str(callback_target.get("key_id") or ""),
                secret=registered_secret,
                callback_id=str(callback_target.get("callback_id") or run.run_id),
            )

    @staticmethod
    def _mark_callback_config_invalid(
        repository: RuntimeRepository,
        run: RunRecord,
        *,
        message: str,
    ) -> None:
        repository.mark_callback_delivery_failed(
            run,
            error_code="runtime.callback_config_invalid",
            error_message=message,
            retry_at=None,
        )

    def _recover_stale_callback_dispatches(self, *, limit: int) -> None:
        current_time = datetime.now(UTC)
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            recovered_runs = repository.reclaim_stale_callback_dispatches(
                limit=limit,
                now=current_time,
            )
            session.commit()

        if self.recovery_audit_callback is None:
            return
        for run in recovered_runs:
            self.recovery_audit_callback(run, recovered_at=current_time)

    def _build_callback_payload(
        self,
        run: RunRecord,
        *,
        session: Session,
    ) -> dict[str, object]:
        return {
            "event": "runtime.run.terminal",
            "run_id": run.run_id,
            "canonical_run_id": run.canonical_run_id or "",
            "site_id": run.site_id,
            "trace_id": run.trace_id,
            "status": run.status,
            "error_code": run.error_code or "",
            "error_message": run.error_message or "",
            "execution_context": self.run_projector.build_execution_context_payload(run),
            "task_backend": self.run_projector.build_task_backend_payload(run),
            "run_lifecycle": self.run_projector.build_run_lifecycle(run),
            "result": self._build_callback_result_payload(run, session=session),
        }

    @staticmethod
    def _build_callback_result_payload(
        run: RunRecord,
        *,
        session: Session,
    ) -> dict[str, object]:
        return project_media_artifact_lifecycle(
            run.result_json if isinstance(run.result_json, dict) else {},
            session=session,
            site_id=run.site_id,
            run_id=run.run_id,
        )

    def _resolve_callback_retry_at(
        self,
        run_id: str,
        *,
        retryable: bool,
        attempted_at: datetime,
    ) -> datetime | None:
        with get_session(self.database_url) as session:
            repository = RuntimeRepository(session)
            run = repository.get_run(run_id)
            session.commit()

        if run is None:
            return None
        if not retryable or run.callback_attempt_count >= self.max_attempts:
            return None
        return attempted_at + timedelta(seconds=self.retry_backoff_seconds)
