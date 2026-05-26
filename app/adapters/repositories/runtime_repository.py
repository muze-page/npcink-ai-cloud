from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.core.models import (
    RUN_CALLBACK_STATUS_DELIVERED,
    RUN_CALLBACK_STATUS_DISPATCHING,
    RUN_CALLBACK_STATUS_FAILED,
    RUN_CALLBACK_STATUS_NOT_REQUESTED,
    RUN_CALLBACK_STATUS_PENDING,
    ProviderCallRecord,
    ReplayReceipt,
    RunRecord,
    RuntimeGuardEvent,
    Site,
)
from app.domain.runtime.models import (
    RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_AFTER_SECONDS,
    RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE,
    RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS,
    RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS,
    RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL,
    RUNTIME_STORAGE_MODE_NO_STORE,
    RUNTIME_STORAGE_MODE_RESULT_ONLY,
)


class RuntimeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_site(self, site_id: str) -> Site | None:
        return self.session.get(Site, site_id)

    def get_run(self, run_id: str) -> RunRecord | None:
        return self.session.get(RunRecord, run_id)

    def get_run_by_idempotency(
        self,
        site_id: str,
        idempotency_key: str,
    ) -> RunRecord | None:
        statement = select(RunRecord).where(
            RunRecord.site_id == site_id,
            RunRecord.idempotency_key == idempotency_key,
        )
        return self.session.scalar(statement)

    def create_run(
        self,
        *,
        run_id: str,
        site_id: str,
        account_id: str | None,
        subscription_id: str | None,
        plan_version_id: str | None,
        ability_name: str,
        ability_family: str,
        skill_id: str,
        workflow_id: str,
        contract_version: str,
        channel: str,
        execution_kind: str,
        execution_tier: str,
        execution_pattern: str,
        data_classification: str,
        profile_id: str,
        canonical_run_id: str | None,
        status: str,
        idempotency_key: str | None,
        request_fingerprint: str,
        trace_id: str,
        input_json: dict[str, Any],
        execution_input_ciphertext: str | None,
        policy_json: dict[str, Any],
        selected_provider_id: str | None = None,
        selected_model_id: str | None = None,
        selected_instance_id: str | None = None,
    ) -> RunRecord:
        processing_started_at = datetime.now(UTC) if status == "running" else None
        run = RunRecord(
            run_id=run_id,
            site_id=site_id,
            account_id=account_id,
            subscription_id=subscription_id,
            plan_version_id=plan_version_id,
            ability_name=ability_name,
            ability_family=ability_family,
            skill_id=skill_id or None,
            workflow_id=workflow_id or None,
            contract_version=contract_version or None,
            channel=channel,
            execution_kind=execution_kind,
            execution_tier=execution_tier,
            execution_pattern=execution_pattern,
            data_classification=data_classification,
            profile_id=profile_id,
            canonical_run_id=canonical_run_id or None,
            status=status,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
            trace_id=trace_id,
            input_json=input_json,
            execution_input_ciphertext=execution_input_ciphertext,
            policy_json=policy_json,
            selected_provider_id=selected_provider_id,
            selected_model_id=selected_model_id,
            selected_instance_id=selected_instance_id,
            processing_started_at=processing_started_at,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def mark_run_succeeded(
        self,
        run: RunRecord,
        *,
        result_json: dict[str, Any],
        provider_id: str,
        model_id: str,
        instance_id: str,
        fallback_used: bool,
    ) -> RunRecord:
        terminal_at = datetime.now(UTC)
        run.status = "succeeded"
        run.result_ref = "inline"
        run.result_json = result_json
        run.selected_provider_id = provider_id
        run.selected_model_id = model_id
        run.selected_instance_id = instance_id
        run.fallback_used = fallback_used
        run.error_code = None
        run.error_message = None
        run.finished_at = terminal_at
        run.canceled_at = None
        run.retention_expires_at = self._resolve_retention_expires_at(run, terminal_at)
        run.execution_input_ciphertext = None
        self._apply_terminal_input_storage_policy(run)
        self._schedule_callback_delivery(run, terminal_at)
        self.session.flush()
        return run

    def claim_run_if_queued(self, run_id: str) -> RunRecord | None:
        return self._claim_queued_run(
            update(RunRecord)
            .where(
                RunRecord.run_id == run_id,
                RunRecord.status == "queued",
            )
        )

    def claim_next_queued_run(self) -> RunRecord | None:
        oldest_queued_run_id = (
            select(RunRecord.run_id)
            .where(RunRecord.status == "queued")
            .order_by(RunRecord.started_at.asc(), RunRecord.run_id.asc())
            .limit(1)
            .scalar_subquery()
        )
        return self._claim_queued_run(
            update(RunRecord).where(
                RunRecord.run_id == oldest_queued_run_id,
                RunRecord.status == "queued",
            )
        )

    def _claim_queued_run(self, statement: Any) -> RunRecord | None:
        claimed_row = self.session.execute(
            statement.values(
                status="running",
                processing_started_at=datetime.now(UTC),
            ).returning(RunRecord.run_id)
        ).first()
        if claimed_row is None:
            self.session.flush()
            return None

        claimed_run_id = str(claimed_row[0] or "")
        if not claimed_run_id:
            self.session.flush()
            return None

        self.session.flush()
        return self.get_run(claimed_run_id)

    def mark_run_failed(
        self,
        run: RunRecord,
        *,
        error_code: str,
        error_message: str,
        provider_id: str | None = None,
        model_id: str | None = None,
        instance_id: str | None = None,
        fallback_used: bool | None = None,
    ) -> RunRecord:
        terminal_at = datetime.now(UTC)
        run.status = "failed"
        run.error_code = error_code
        run.error_message = error_message
        if provider_id is not None:
            run.selected_provider_id = provider_id
        if model_id is not None:
            run.selected_model_id = model_id
        if instance_id is not None:
            run.selected_instance_id = instance_id
        if fallback_used is not None:
            run.fallback_used = fallback_used
        run.finished_at = terminal_at
        run.canceled_at = None
        run.retention_expires_at = self._resolve_retention_expires_at(run, terminal_at)
        run.execution_input_ciphertext = None
        self._apply_terminal_input_storage_policy(run)
        self._schedule_callback_delivery(run, terminal_at)
        self.session.flush()
        return run

    def request_run_cancel(self, run: RunRecord, *, now: datetime | None = None) -> RunRecord:
        requested_at = now or datetime.now(UTC)
        if run.cancel_requested_at is None:
            run.cancel_requested_at = requested_at
        self.session.flush()
        return run

    def mark_run_canceled(
        self,
        run: RunRecord,
        *,
        now: datetime | None = None,
        message: str = "run canceled before execution completed",
    ) -> RunRecord:
        terminal_at = now or datetime.now(UTC)
        run.status = "canceled"
        run.error_code = "runtime.canceled"
        run.error_message = message
        run.finished_at = terminal_at
        run.canceled_at = terminal_at
        if run.cancel_requested_at is None:
            run.cancel_requested_at = terminal_at
        run.retention_expires_at = self._resolve_retention_expires_at(run, terminal_at)
        run.execution_input_ciphertext = None
        self._apply_terminal_input_storage_policy(run)
        self._schedule_callback_delivery(run, terminal_at)
        self.session.flush()
        return run

    def record_provider_call(
        self,
        *,
        run_id: str,
        provider_id: str,
        model_id: str,
        instance_id: str,
        region: str,
        latency_ms: int,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        retry_count: int,
        fallback_used: bool,
        error_code: str | None = None,
    ) -> ProviderCallRecord:
        record = ProviderCallRecord(
            run_id=run_id,
            provider_id=provider_id,
            model_id=model_id,
            instance_id=instance_id,
            region=region,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            retry_count=retry_count,
            fallback_used=fallback_used,
            error_code=error_code,
        )
        self.session.add(record)
        self.session.flush()
        return record

    def list_provider_calls(self, run_id: str) -> list[ProviderCallRecord]:
        statement = select(ProviderCallRecord).where(
            ProviderCallRecord.run_id == run_id
        ).order_by(ProviderCallRecord.id.asc())
        return list(self.session.scalars(statement))

    def purge_expired_run_results(self, *, now: datetime | None = None) -> int:
        current_time = now or datetime.now(UTC)
        expired_runs = list(
            self.session.scalars(
                select(RunRecord).where(
                    RunRecord.retention_expires_at.is_not(None),
                    RunRecord.retention_expires_at <= current_time,
                    RunRecord.result_purged_at.is_(None),
                )
            )
        )
        for run in expired_runs:
            run.result_json = None
            run.input_json = None
            run.execution_input_ciphertext = None
            run.result_ref = "purged"
            run.result_purged_at = current_time
        self.session.flush()
        return len(expired_runs)

    def refresh_run(self, run: RunRecord) -> RunRecord:
        self.session.refresh(run)
        return run

    def list_due_callback_run_ids(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[str]:
        current_time = now or datetime.now(UTC)
        candidate_runs = list(
            self.session.scalars(
                select(RunRecord)
                .where(
                    RunRecord.finished_at.is_not(None),
                    RunRecord.callback_status.in_(
                        (
                            RUN_CALLBACK_STATUS_NOT_REQUESTED,
                            RUN_CALLBACK_STATUS_PENDING,
                        )
                    ),
                )
                .order_by(RunRecord.finished_at.asc(), RunRecord.started_at.asc())
                .limit(max(5, limit * 5))
            )
        )
        due_run_ids: list[str] = []
        for run in candidate_runs:
            policy = run.policy_json if isinstance(run.policy_json, dict) else {}
            if not self._has_callback_target(policy):
                continue
            callback_next_attempt_at = (
                self._normalize_timestamp(run.callback_next_attempt_at)
                if run.callback_next_attempt_at is not None
                else None
            )
            if callback_next_attempt_at is not None and callback_next_attempt_at > current_time:
                continue
            due_run_ids.append(run.run_id)
        return due_run_ids

    def list_runtime_backlog_runs(
        self,
        *,
        site_id: str | None = None,
    ) -> list[RunRecord]:
        return list(
            self.session.scalars(
                select(RunRecord)
                .where(
                    RunRecord.status.in_(("queued", "running")),
                    *self._site_filters(site_id),
                )
                .order_by(
                    RunRecord.status.asc(),
                    RunRecord.started_at.asc(),
                    RunRecord.processing_started_at.asc(),
                )
            )
        )

    def get_runtime_diagnostics_summary(
        self,
        *,
        site_id: str | None = None,
        now: datetime | None = None,
        recent_since: datetime | None = None,
    ) -> dict[str, object]:
        current_time = now or datetime.now(UTC)
        recent_window_start = recent_since or (current_time - timedelta(hours=1))
        callback_url = self._callback_url_expression()

        queued_filters = [RunRecord.status == "queued", *self._site_filters(site_id)]
        running_filters = [RunRecord.status == "running", *self._site_filters(site_id)]
        cancel_requested_filters = [
            RunRecord.cancel_requested_at.is_not(None),
            RunRecord.status.in_(("queued", "running")),
            *self._site_filters(site_id),
        ]
        callback_pending_filters = [
            RunRecord.finished_at.is_not(None),
            RunRecord.callback_status == RUN_CALLBACK_STATUS_PENDING,
            callback_url.is_not(None),
            callback_url != "",
            *self._site_filters(site_id),
        ]
        callback_due_filters = [
            *callback_pending_filters,
            RunRecord.callback_next_attempt_at.is_not(None),
            RunRecord.callback_next_attempt_at <= current_time,
        ]
        callback_failed_filters = [
            RunRecord.finished_at.is_not(None),
            RunRecord.callback_status == RUN_CALLBACK_STATUS_FAILED,
            callback_url.is_not(None),
            callback_url != "",
            *self._site_filters(site_id),
        ]
        callback_dispatching_filters = [
            RunRecord.finished_at.is_not(None),
            RunRecord.callback_status == RUN_CALLBACK_STATUS_DISPATCHING,
            callback_url.is_not(None),
            callback_url != "",
            *self._site_filters(site_id),
        ]
        callback_dispatching_recoverable_filters = [
            *callback_dispatching_filters,
            RunRecord.callback_last_attempt_at.is_not(None),
            RunRecord.callback_last_attempt_at
            <= (
                current_time
                - timedelta(seconds=RUNTIME_DIAGNOSTIC_CALLBACK_DISPATCHING_STALE_AFTER_SECONDS)
            ),
        ]
        callback_delivered_recent_filters = [
            RunRecord.callback_status == RUN_CALLBACK_STATUS_DELIVERED,
            RunRecord.callback_delivered_at.is_not(None),
            RunRecord.callback_delivered_at >= recent_window_start,
            callback_url.is_not(None),
            callback_url != "",
            *self._site_filters(site_id),
        ]
        retention_due_filters = [
            RunRecord.retention_expires_at.is_not(None),
            RunRecord.retention_expires_at <= current_time,
            RunRecord.result_purged_at.is_(None),
            RunRecord.result_json.is_not(None),
            *self._site_filters(site_id),
        ]
        retention_purged_recent_filters = [
            RunRecord.result_purged_at.is_not(None),
            RunRecord.result_purged_at >= recent_window_start,
            *self._site_filters(site_id),
        ]
        canceled_recent_filters = [
            RunRecord.status == "canceled",
            RunRecord.canceled_at.is_not(None),
            RunRecord.canceled_at >= recent_window_start,
            *self._site_filters(site_id),
        ]

        return {
            "queue": {
                "queued_runs": self._count_runs(queued_filters),
                "queued_oldest_requested_at": self._serialize_timestamp(
                    self._min_timestamp(queued_filters, RunRecord.started_at)
                ),
                "running_runs": self._count_runs(running_filters),
                "running_oldest_processing_started_at": self._serialize_timestamp(
                    self._min_timestamp(running_filters, RunRecord.processing_started_at)
                ),
            },
            "cancel": {
                "active_requests": self._count_runs(cancel_requested_filters),
                "oldest_requested_at": self._serialize_timestamp(
                    self._min_timestamp(cancel_requested_filters, RunRecord.cancel_requested_at)
                ),
                "canceled_recent": self._count_runs(canceled_recent_filters),
            },
            "callback": {
                "pending": self._count_runs(callback_pending_filters),
                "due_now": self._count_runs(callback_due_filters),
                "dispatching": self._count_runs(callback_dispatching_filters),
                "recoverable_dispatching": self._count_runs(
                    callback_dispatching_recoverable_filters
                ),
                "failed": self._count_runs(callback_failed_filters),
                "delivered_recent": self._count_runs(callback_delivered_recent_filters),
                "oldest_due_at": self._serialize_timestamp(
                    self._min_timestamp(callback_due_filters, RunRecord.callback_next_attempt_at)
                ),
                "dispatching_oldest_last_attempt_at": self._serialize_timestamp(
                    self._min_timestamp(
                        callback_dispatching_filters,
                        RunRecord.callback_last_attempt_at,
                    )
                ),
            },
            "retention": {
                "due_purge": self._count_runs(retention_due_filters),
                "oldest_due_expires_at": self._serialize_timestamp(
                    self._min_timestamp(retention_due_filters, RunRecord.retention_expires_at)
                ),
                "purged_recent": self._count_runs(retention_purged_recent_filters),
            },
        }

    def list_runtime_diagnostic_runs(
        self,
        *,
        issue_kind: str,
        site_id: str | None = None,
        limit: int = 20,
        now: datetime | None = None,
    ) -> list[RunRecord]:
        current_time = now or datetime.now(UTC)
        callback_url = self._callback_url_expression()
        queued_stale_before = current_time - timedelta(
            seconds=RUNTIME_DIAGNOSTIC_QUEUED_STALE_AFTER_SECONDS
        )
        running_stale_before = current_time - timedelta(
            seconds=RUNTIME_DIAGNOSTIC_RUNNING_STALE_AFTER_SECONDS
        )
        cancel_stuck_before = current_time - timedelta(
            seconds=RUNTIME_DIAGNOSTIC_CANCEL_STUCK_AFTER_SECONDS
        )
        callback_overdue_before = current_time - timedelta(
            seconds=RUNTIME_DIAGNOSTIC_CALLBACK_OVERDUE_AFTER_SECONDS
        )

        statement = select(RunRecord)
        order_by = (RunRecord.started_at.asc(),)

        if issue_kind == "queued":
            statement = statement.where(
                RunRecord.status == "queued",
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.started_at.asc(),)
        elif issue_kind == "queued_stale":
            statement = statement.where(
                RunRecord.status == "queued",
                RunRecord.started_at <= queued_stale_before,
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.started_at.asc(),)
        elif issue_kind == "running":
            statement = statement.where(
                RunRecord.status == "running",
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.processing_started_at.asc(), RunRecord.started_at.asc())
        elif issue_kind == "running_stale":
            statement = statement.where(
                RunRecord.status == "running",
                RunRecord.processing_started_at.is_not(None),
                RunRecord.processing_started_at <= running_stale_before,
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.processing_started_at.asc(), RunRecord.started_at.asc())
        elif issue_kind == "cancel_requested":
            statement = statement.where(
                RunRecord.cancel_requested_at.is_not(None),
                RunRecord.status.in_(("queued", "running")),
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.cancel_requested_at.asc(), RunRecord.started_at.asc())
        elif issue_kind == "cancel_stuck":
            statement = statement.where(
                RunRecord.cancel_requested_at.is_not(None),
                RunRecord.cancel_requested_at <= cancel_stuck_before,
                RunRecord.status.in_(("queued", "running")),
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.cancel_requested_at.asc(), RunRecord.started_at.asc())
        elif issue_kind == "callback_due":
            statement = statement.where(
                RunRecord.finished_at.is_not(None),
                RunRecord.callback_status == RUN_CALLBACK_STATUS_PENDING,
                RunRecord.callback_next_attempt_at.is_not(None),
                RunRecord.callback_next_attempt_at <= current_time,
                callback_url.is_not(None),
                callback_url != "",
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.callback_next_attempt_at.asc(), RunRecord.finished_at.asc())
        elif issue_kind == "callback_overdue":
            statement = statement.where(
                RunRecord.finished_at.is_not(None),
                RunRecord.callback_status == RUN_CALLBACK_STATUS_PENDING,
                RunRecord.callback_next_attempt_at.is_not(None),
                RunRecord.callback_next_attempt_at <= callback_overdue_before,
                callback_url.is_not(None),
                callback_url != "",
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.callback_next_attempt_at.asc(), RunRecord.finished_at.asc())
        elif issue_kind == "callback_failed":
            statement = statement.where(
                RunRecord.finished_at.is_not(None),
                RunRecord.callback_status == RUN_CALLBACK_STATUS_FAILED,
                callback_url.is_not(None),
                callback_url != "",
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.callback_last_attempt_at.desc(), RunRecord.finished_at.desc())
        elif issue_kind == "callback_dispatching":
            statement = statement.where(
                RunRecord.finished_at.is_not(None),
                RunRecord.callback_status == RUN_CALLBACK_STATUS_DISPATCHING,
                callback_url.is_not(None),
                callback_url != "",
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.callback_last_attempt_at.asc(), RunRecord.finished_at.asc())
        elif issue_kind == "canceled_recent":
            statement = statement.where(
                RunRecord.status == "canceled",
                RunRecord.canceled_at.is_not(None),
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.canceled_at.desc(), RunRecord.started_at.desc())
        elif issue_kind == "retention_due":
            statement = statement.where(
                RunRecord.retention_expires_at.is_not(None),
                RunRecord.retention_expires_at <= current_time,
                RunRecord.result_purged_at.is_(None),
                RunRecord.result_json.is_not(None),
                *self._site_filters(site_id),
            )
            order_by = (RunRecord.retention_expires_at.asc(), RunRecord.finished_at.asc())
        else:
            return []

        return list(
            self.session.scalars(statement.order_by(*order_by).limit(max(1, limit)))
        )

    def summarize_replay_receipts(
        self,
        *,
        scope_kinds: list[str],
        since: datetime,
        limit_per_scope: int,
        scope_id: str | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        if not scope_kinds:
            return {}

        request_count = func.count(ReplayReceipt.id).label("request_count")
        first_seen_at = func.min(ReplayReceipt.created_at).label("first_seen_at")
        last_seen_at = func.max(ReplayReceipt.created_at).label("last_seen_at")
        statement = (
            select(
                ReplayReceipt.scope_kind,
                ReplayReceipt.scope_id,
                request_count,
                first_seen_at,
                last_seen_at,
            )
            .where(
                ReplayReceipt.scope_kind.in_(tuple(scope_kinds)),
                ReplayReceipt.created_at >= since,
            )
            .group_by(ReplayReceipt.scope_kind, ReplayReceipt.scope_id)
            .order_by(
                ReplayReceipt.scope_kind.asc(),
                request_count.desc(),
                last_seen_at.desc(),
            )
        )
        if scope_id:
            statement = statement.where(ReplayReceipt.scope_id == scope_id)

        grouped: dict[str, list[dict[str, object]]] = {kind: [] for kind in scope_kinds}
        for scope_kind, grouped_scope_id, count, first_seen, last_seen in self.session.execute(
            statement
        ):
            if len(grouped[scope_kind]) >= max(1, limit_per_scope):
                continue
            grouped[scope_kind].append(
                {
                    "scope_id": str(grouped_scope_id or ""),
                    "request_count": int(count or 0),
                    "first_seen_at": self._serialize_timestamp(first_seen),
                    "last_seen_at": self._serialize_timestamp(last_seen),
                }
            )
        return grouped

    def count_runtime_guard_events(
        self,
        *,
        since: datetime,
        site_id: str | None = None,
        event_code: str | None = None,
    ) -> int:
        statement = select(func.count()).select_from(RuntimeGuardEvent).where(
            RuntimeGuardEvent.created_at >= since
        )
        if site_id:
            statement = statement.where(RuntimeGuardEvent.site_id == site_id)
        if event_code:
            statement = statement.where(RuntimeGuardEvent.event_code == event_code)
        return int(self.session.scalar(statement) or 0)

    def summarize_runtime_guard_event_codes(
        self,
        *,
        since: datetime,
        site_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, object]]:
        statement = (
            select(
                RuntimeGuardEvent.event_code,
                func.count(RuntimeGuardEvent.id).label("event_count"),
                func.max(RuntimeGuardEvent.created_at).label("last_seen_at"),
            )
            .where(RuntimeGuardEvent.created_at >= since)
            .group_by(RuntimeGuardEvent.event_code)
            .order_by(func.count(RuntimeGuardEvent.id).desc(), func.max(RuntimeGuardEvent.created_at).desc())
        )
        if site_id:
            statement = statement.where(RuntimeGuardEvent.site_id == site_id)

        items: list[dict[str, object]] = []
        for event_code, event_count, last_seen_at in self.session.execute(
            statement.limit(max(1, limit))
        ):
            items.append(
                {
                    "event_code": str(event_code),
                    "event_count": int(event_count or 0),
                    "last_seen_at": self._serialize_timestamp(last_seen_at),
                }
            )
        return items

    def summarize_runtime_guard_event_code_breakdown_by_scope(
        self,
        *,
        scope_kinds: list[str],
        since: datetime,
        site_id: str | None = None,
        limit_per_scope: int = 3,
    ) -> dict[tuple[str, str], list[dict[str, object]]]:
        if not scope_kinds:
            return {}

        statement = (
            select(
                RuntimeGuardEvent.scope_kind,
                RuntimeGuardEvent.scope_id,
                RuntimeGuardEvent.event_code,
                func.count(RuntimeGuardEvent.id).label("event_count"),
                func.max(RuntimeGuardEvent.created_at).label("last_seen_at"),
            )
            .where(
                RuntimeGuardEvent.scope_kind.in_(tuple(scope_kinds)),
                RuntimeGuardEvent.created_at >= since,
            )
            .group_by(
                RuntimeGuardEvent.scope_kind,
                RuntimeGuardEvent.scope_id,
                RuntimeGuardEvent.event_code,
            )
            .order_by(
                RuntimeGuardEvent.scope_kind.asc(),
                RuntimeGuardEvent.scope_id.asc(),
                func.count(RuntimeGuardEvent.id).desc(),
                func.max(RuntimeGuardEvent.created_at).desc(),
            )
        )
        if site_id:
            statement = statement.where(RuntimeGuardEvent.site_id == site_id)

        grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
        for scope_kind, scope_id, event_code, event_count, last_seen_at in self.session.execute(
            statement
        ):
            key = (str(scope_kind), str(scope_id or ""))
            if len(grouped.setdefault(key, [])) >= max(1, limit_per_scope):
                continue
            grouped[key].append(
                {
                    "event_code": str(event_code),
                    "event_count": int(event_count or 0),
                    "last_seen_at": self._serialize_timestamp(last_seen_at),
                }
            )
        return grouped

    def list_runtime_guard_events_since(
        self,
        *,
        since: datetime,
        site_id: str | None = None,
        event_code: str | None = None,
        limit: int = 10,
    ) -> list[RuntimeGuardEvent]:
        statement = select(RuntimeGuardEvent).where(RuntimeGuardEvent.created_at >= since)
        if site_id:
            statement = statement.where(RuntimeGuardEvent.site_id == site_id)
        if event_code:
            statement = statement.where(RuntimeGuardEvent.event_code == event_code)
        statement = statement.order_by(
            RuntimeGuardEvent.created_at.desc(),
            RuntimeGuardEvent.id.desc(),
        )
        return list(self.session.scalars(statement.limit(max(1, limit))))

    def summarize_runtime_guard_events(
        self,
        *,
        scope_kinds: list[str],
        since: datetime,
        limit_per_scope: int,
        site_id: str | None = None,
        event_code: str | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        if not scope_kinds:
            return {}

        event_count = func.count(RuntimeGuardEvent.id).label("event_count")
        first_seen_at = func.min(RuntimeGuardEvent.created_at).label("first_seen_at")
        last_seen_at = func.max(RuntimeGuardEvent.created_at).label("last_seen_at")
        statement = (
            select(
                RuntimeGuardEvent.scope_kind,
                RuntimeGuardEvent.scope_id,
                event_count,
                first_seen_at,
                last_seen_at,
            )
            .where(
                RuntimeGuardEvent.scope_kind.in_(tuple(scope_kinds)),
                RuntimeGuardEvent.created_at >= since,
            )
            .group_by(RuntimeGuardEvent.scope_kind, RuntimeGuardEvent.scope_id)
            .order_by(
                RuntimeGuardEvent.scope_kind.asc(),
                event_count.desc(),
                last_seen_at.desc(),
            )
        )
        if site_id:
            statement = statement.where(RuntimeGuardEvent.site_id == site_id)
        if event_code:
            statement = statement.where(RuntimeGuardEvent.event_code == event_code)

        grouped: dict[str, list[dict[str, object]]] = {kind: [] for kind in scope_kinds}
        for scope_kind, scope_id, count, first_seen, last_seen in self.session.execute(statement):
            if len(grouped[scope_kind]) >= max(1, limit_per_scope):
                continue
            grouped[scope_kind].append(
                {
                    "scope_id": str(scope_id or ""),
                    "event_count": int(count or 0),
                    "first_seen_at": self._serialize_timestamp(first_seen),
                    "last_seen_at": self._serialize_timestamp(last_seen),
                }
            )
        return grouped

    def list_runtime_guard_events(
        self,
        *,
        site_id: str | None = None,
        scope_kind: str | None = None,
        event_code: str | None = None,
        limit: int = 20,
    ) -> list[RuntimeGuardEvent]:
        statement = select(RuntimeGuardEvent)
        if site_id:
            statement = statement.where(RuntimeGuardEvent.site_id == site_id)
        if scope_kind:
            statement = statement.where(RuntimeGuardEvent.scope_kind == scope_kind)
        if event_code:
            statement = statement.where(RuntimeGuardEvent.event_code == event_code)

        return list(
            self.session.scalars(
                statement.order_by(RuntimeGuardEvent.created_at.desc()).limit(max(1, limit))
            )
        )

    def claim_callback_dispatch(
        self,
        run_id: str,
        *,
        now: datetime | None = None,
    ) -> RunRecord | None:
        claimed_at = now or datetime.now(UTC)
        result = cast(
            CursorResult[Any],
            self.session.execute(
                update(RunRecord)
                .where(
                    RunRecord.run_id == run_id,
                    RunRecord.callback_status.in_(
                        (
                            RUN_CALLBACK_STATUS_NOT_REQUESTED,
                            RUN_CALLBACK_STATUS_PENDING,
                        )
                    ),
                )
                .values(
                    callback_status=RUN_CALLBACK_STATUS_DISPATCHING,
                    callback_attempt_count=RunRecord.callback_attempt_count + 1,
                    callback_last_attempt_at=claimed_at,
                    callback_next_attempt_at=None,
                )
            ),
        )
        if result.rowcount != 1:
            self.session.flush()
            return None

        self.session.flush()
        return self.get_run(run_id)

    def reclaim_stale_callback_dispatches(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[RunRecord]:
        current_time = now or datetime.now(UTC)
        reclaim_before = current_time - timedelta(
            seconds=RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_AFTER_SECONDS
        )
        callback_url = self._callback_url_expression()
        candidates = list(
            self.session.scalars(
                select(RunRecord)
                .where(
                    RunRecord.finished_at.is_not(None),
                    RunRecord.callback_status == RUN_CALLBACK_STATUS_DISPATCHING,
                    RunRecord.callback_last_attempt_at.is_not(None),
                    RunRecord.callback_last_attempt_at <= reclaim_before,
                    callback_url.is_not(None),
                    callback_url != "",
                )
                .order_by(
                    RunRecord.callback_last_attempt_at.asc(),
                    RunRecord.finished_at.asc(),
                )
                .limit(max(1, limit))
            )
        )
        recovered: list[RunRecord] = []
        for candidate in candidates:
            result = cast(
                CursorResult[Any],
                self.session.execute(
                    update(RunRecord)
                    .where(
                        RunRecord.run_id == candidate.run_id,
                        RunRecord.callback_status == RUN_CALLBACK_STATUS_DISPATCHING,
                        RunRecord.callback_last_attempt_at.is_not(None),
                        RunRecord.callback_last_attempt_at <= reclaim_before,
                    )
                    .values(
                        callback_status=RUN_CALLBACK_STATUS_PENDING,
                        callback_next_attempt_at=current_time,
                        callback_delivered_at=None,
                        callback_last_error_code=(
                            RUNTIME_CALLBACK_DISPATCH_LEASE_RECOVERY_ERROR_CODE
                        ),
                        callback_last_error_message=(
                            "stale callback dispatch lease reclaimed and requeued"
                        ),
                    ),
                    execution_options={"synchronize_session": False},
                ),
            )
            if result.rowcount != 1:
                continue
            self.session.flush()
            recovered_run = self.get_run(candidate.run_id)
            if recovered_run is not None:
                recovered.append(recovered_run)
        return recovered

    def mark_callback_delivered(
        self,
        run: RunRecord,
        *,
        delivered_at: datetime | None = None,
    ) -> RunRecord:
        completed_at = delivered_at or datetime.now(UTC)
        run.callback_status = RUN_CALLBACK_STATUS_DELIVERED
        run.callback_delivered_at = completed_at
        run.callback_next_attempt_at = None
        run.callback_last_error_code = None
        run.callback_last_error_message = None
        self.session.flush()
        return run

    def mark_callback_delivery_failed(
        self,
        run: RunRecord,
        *,
        error_code: str,
        error_message: str,
        retry_at: datetime | None = None,
    ) -> RunRecord:
        run.callback_status = (
            RUN_CALLBACK_STATUS_PENDING if retry_at is not None else RUN_CALLBACK_STATUS_FAILED
        )
        run.callback_next_attempt_at = retry_at
        run.callback_delivered_at = None
        run.callback_last_error_code = error_code
        run.callback_last_error_message = error_message
        self.session.flush()
        return run

    def _resolve_retention_expires_at(
        self,
        run: RunRecord,
        terminal_at: datetime,
    ) -> datetime | None:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        if self._get_storage_mode(policy) == RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL:
            retention_ttl = self._coerce_int(policy.get("retention_ttl"))
            if retention_ttl <= 0:
                return None
            return terminal_at + timedelta(seconds=retention_ttl)
        retention_ttl = self._coerce_int(policy.get("retention_ttl"))
        if retention_ttl <= 0:
            return None
        return terminal_at + timedelta(seconds=retention_ttl)

    def _schedule_callback_delivery(
        self,
        run: RunRecord,
        scheduled_at: datetime,
    ) -> None:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        if not self._has_callback_target(policy):
            run.callback_status = RUN_CALLBACK_STATUS_NOT_REQUESTED
            run.callback_next_attempt_at = None
            run.callback_delivered_at = None
            run.callback_last_error_code = None
            run.callback_last_error_message = None
            return

        run.callback_status = RUN_CALLBACK_STATUS_PENDING
        run.callback_next_attempt_at = scheduled_at
        run.callback_delivered_at = None

    def _apply_terminal_input_storage_policy(self, run: RunRecord) -> None:
        policy = run.policy_json if isinstance(run.policy_json, dict) else {}
        storage_mode = self._get_storage_mode(policy)
        if storage_mode in {
            RUNTIME_STORAGE_MODE_NO_STORE,
            RUNTIME_STORAGE_MODE_RESULT_ONLY,
        }:
            run.input_json = {}
        run.callback_last_error_code = None
        run.callback_last_error_message = None

    def _coerce_int(self, value: object | None) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError:
                return 0
        return 0

    def _has_callback_target(self, policy: dict[str, object]) -> bool:
        runtime_callback = policy.get("runtime_callback")
        if isinstance(runtime_callback, dict):
            callback_url = str(runtime_callback.get("callback_url") or "").strip()
            if callback_url:
                return True
        callback_url = str(policy.get("callback_url") or "").strip()
        return bool(callback_url)

    def _get_storage_mode(self, policy: dict[str, object]) -> str:
        storage_mode = str(policy.get("storage_mode") or "")
        if storage_mode == RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL:
            return RUNTIME_STORAGE_MODE_FULL_STORE_WITH_TTL
        return storage_mode

    def _normalize_timestamp(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _site_filters(self, site_id: str | None) -> list[object]:
        if not site_id:
            return []
        return [RunRecord.site_id == site_id]

    def _count_runs(self, filters: list[object]) -> int:
        return int(
            self.session.scalar(select(func.count()).select_from(RunRecord).where(*filters)) or 0
        )

    def _min_timestamp(self, filters: list[object], column: object) -> datetime | None:
        return self.session.scalar(select(func.min(column)).select_from(RunRecord).where(*filters))

    def _callback_url_expression(self) -> Any:
        return func.coalesce(
            RunRecord.policy_json["runtime_callback"]["callback_url"].as_string(),
            RunRecord.policy_json["callback_url"].as_string(),
        )

    def _serialize_timestamp(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        normalized = self._normalize_timestamp(value)
        return normalized.isoformat().replace("+00:00", "Z")
