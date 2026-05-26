from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.adapters.callbacks.base import RuntimeCallbackDispatcher
from app.adapters.providers.base import ProviderExecutionError
from app.adapters.queue.base import RuntimeQueue, RuntimeQueueError
from app.core.config import Settings, get_settings
from app.core.db import get_session_factory
from app.core.logging import get_logger


def _get_db_session(database_url: str):
    """Returns a plain DB session (not a context manager)."""
    return get_session_factory(database_url)()
from app.core.models import RunRecord, Site
from app.domain.commercial.service import CommercialService
from app.domain.orchestration.models import (
    ALLOWED_ORCHESTRATION_STATUS,
    ALLOWED_STEP_STATUS,
    ALLOWED_WHEN_OPERATORS,
    COMPLEX_WHEN_OPERATORS,
    ORCHESTRATION_MAX_DURATION_DEFAULT,
    REF_PATH_PREFIXES,
    OrchestrationResult,
    OrchestrationStepDefinition,
    OrchestrationSubmission,
    StepResult,
)
from app.domain.runtime.service import RuntimeService
from app.domain.routing.service import RoutingService

logger = get_logger("magick_ai_cloud.orchestration")


class OrchestrationError(Exception):
    pass


class OrchestrationNotFoundError(OrchestrationError):
    def __init__(self, orchestration_run_id: str) -> None:
        self.orchestration_run_id = orchestration_run_id
        super().__init__(f"Orchestration run not found: {orchestration_run_id}")


class OrchestrationNotQueuedError(OrchestrationError):
    def __init__(self, orchestration_run_id: str, status: str) -> None:
        self.orchestration_run_id = orchestration_run_id
        self.status = status
        super().__init__(
            f"Orchestration run {orchestration_run_id} is not queued (current status: {status})"
        )


class OrchestrationStepError(OrchestrationError):
    def __init__(
        self,
        orchestration_run_id: str,
        step_index: int,
        error_code: str,
        error_message: str,
    ) -> None:
        self.orchestration_run_id = orchestration_run_id
        self.step_index = step_index
        self.error_code = error_code
        self.error_message = error_message
        super().__init__(
            f"Step {step_index} failed in orchestration {orchestration_run_id}: {error_code} - {error_message}"
        )


class OrchestrationService:
    def __init__(
        self,
        database_url: str,
        *,
        settings: Settings | None = None,
        runtime_service: RuntimeService | None = None,
        routing_service: RoutingService | None = None,
        commercial_service: CommercialService | None = None,
        runtime_queue: RuntimeQueue | None = None,
        callback_dispatcher: RuntimeCallbackDispatcher | None = None,
        callback_max_attempts: int = 3,
        callback_retry_backoff_seconds: int = 30,
    ) -> None:
        self.database_url = database_url
        self.settings = settings or get_settings()
        self.runtime_service = runtime_service
        self.routing_service = routing_service
        self.commercial_service = commercial_service
        self.runtime_queue = runtime_queue
        self.callback_dispatcher = callback_dispatcher
        self.callback_max_attempts = callback_max_attempts
        self.callback_retry_backoff_seconds = callback_retry_backoff_seconds

    def submit(
        self,
        site_id: str,
        submission: OrchestrationSubmission,
    ) -> OrchestrationResult:
        session = _get_db_session(self.database_url)
        try:
            site = session.query(Site).filter_by(site_id=site_id, status="active").first()
            if not site:
                raise OrchestrationError(f"Site {site_id} not found or not active")

            if submission.max_duration_seconds <= 0:
                submission.max_duration_seconds = ORCHESTRATION_MAX_DURATION_DEFAULT

            orchestration_run_id = f"orch_{uuid4().hex}"

            run_row = {
                "orchestration_run_id": orchestration_run_id,
                "site_id": site_id,
                "workflow_id": submission.workflow_id,
                "workflow_version": submission.workflow_version,
                "status": "queued",
                "callback_url": submission.callback_url,
                "max_duration_seconds": submission.max_duration_seconds,
            }
            session.execute(
                self._orchestration_runs_insert(), run_row
            )

            for idx, step_def in enumerate(submission.steps):
                step_id = f"step_{orchestration_run_id}_{idx}"
                step_row = {
                    "step_id": step_id,
                    "orchestration_run_id": orchestration_run_id,
                    "step_index": idx,
                    "ability_name": step_def.ability_name,
                    "input_payload": json.dumps(step_def.input_map) if step_def.input_map else None,
                    "status": "pending",
                    "retry_count": 0,
                    "max_retries": step_def.retry,
                    "timeout_seconds": step_def.timeout,
                    "when_condition": json.dumps(step_def.when) if step_def.when else None,
                    "foreach_path": step_def.foreach,
                }
                session.execute(
                    self._orchestration_steps_insert(), step_row
                )

            session.commit()

            if self.runtime_queue:
                try:
                    self.runtime_queue.publish(orchestration_run_id)
                except RuntimeQueueError as e:
                    logger.warning(
                        "Failed to publish orchestration to queue: %s", e
                    )

            result = self._build_result(session, orchestration_run_id)
            session.close()
            return result
        except Exception:
            session.rollback()
            session.close()
            raise

    def get_run(self, orchestration_run_id: str) -> OrchestrationResult:
        session = _get_db_session(self.database_url)
        result = self._build_result(session, orchestration_run_id)
        session.close()
        return result

    def get_steps(self, orchestration_run_id: str) -> list[StepResult]:
        session = _get_db_session(self.database_url)
        run = session.execute(
            self._orchestration_runs_select_by_id(),
            {"orchestration_run_id": orchestration_run_id},
        ).fetchone()
        if not run:
            session.close()
            raise OrchestrationNotFoundError(orchestration_run_id)

        rows = session.execute(
            self._orchestration_steps_select_by_run(),
            {"orchestration_run_id": orchestration_run_id},
        ).fetchall()

        steps = []
        for row in rows:
            steps.append(
                StepResult(
                    step_id=row._mapping["step_id"],
                    step_index=row._mapping["step_index"],
                    ability_name=row._mapping["ability_name"],
                    status=row._mapping["status"],
                    input_payload=row._mapping["input_payload"] if row._mapping["input_payload"] else None,
                    step_output=row._mapping["step_output"] if row._mapping["step_output"] else None,
                    started_at=row._mapping["started_at"].isoformat() if row._mapping["started_at"] else None,
                    completed_at=row._mapping["completed_at"].isoformat() if row._mapping["completed_at"] else None,
                    error_code=row._mapping["error_code"],
                    error_message=row._mapping["error_message"],
                    retry_count=row._mapping["retry_count"],
                    max_retries=row._mapping["max_retries"],
                    timeout_seconds=row._mapping["timeout_seconds"],
                    foreach_iteration_count=row._mapping["foreach_iteration_count"],
                )
            )
        session.close()
        return steps

    def cancel(self, orchestration_run_id: str) -> OrchestrationResult:
        session = _get_db_session(self.database_url)
        try:
            run = session.execute(
                self._orchestration_runs_select_by_id(),
                {"orchestration_run_id": orchestration_run_id},
            ).fetchone()
            if not run:
                raise OrchestrationNotFoundError(orchestration_run_id)

            if run._mapping["status"] not in ("queued", "running"):
                raise OrchestrationError(
                    f"Cannot cancel orchestration in status: {run._mapping['status']}"
                )

            now = datetime.now(UTC)
            if run._mapping["status"] == "queued":
                session.execute(
                    self._orchestration_runs_update_status(),
                    {
                        "orchestration_run_id": orchestration_run_id,
                        "status": "canceled",
                        "completed_at": now,
                        "error_code": "orchestration.canceled",
                        "error_message": "Canceled by user",
                    },
                )
            else:
                session.execute(
                    self._orchestration_runs_update_cancel_requested(),
                    {
                        "orchestration_run_id": orchestration_run_id,
                        "cancel_requested_at": now,
                    },
                )

            session.commit()
            result = self._build_result(session, orchestration_run_id)
            session.close()
            return result
        except Exception:
            session.rollback()
            session.close()
            raise

    def execute_next_step(self, orchestration_run_id: str) -> dict[str, Any]:
        session = _get_db_session(self.database_url)
        try:
            run = session.execute(
                self._orchestration_runs_select_by_id(),
                {"orchestration_run_id": orchestration_run_id},
            ).fetchone()
            if not run:
                raise OrchestrationNotFoundError(orchestration_run_id)

            if run._mapping["status"] != "queued":
                session.close()
                return {"status": "already_processed", "run_status": run._mapping["status"]}

            if run._mapping["cancel_requested_at"]:
                self._mark_canceled(session, orchestration_run_id)
                session.commit()
                session.close()
                return {"status": "canceled"}

            now = datetime.now(UTC)
            session.execute(
                self._orchestration_runs_update_status(),
                {
                    "orchestration_run_id": orchestration_run_id,
                    "status": "running",
                },
            )
            session.commit()

            steps = session.execute(
                self._orchestration_steps_select_by_run_ordered(),
                {"orchestration_run_id": orchestration_run_id},
            ).fetchall()

            state = {"input": self._load_initial_input(session, orchestration_run_id), "steps": {}}

            for step_row in steps:
                step_status = step_row._mapping["status"]
                if step_status in ("succeeded", "skipped"):
                    step_output_raw = step_row._mapping["step_output"]
                    if step_output_raw:
                        if isinstance(step_output_raw, dict):
                            state["steps"][step_row._mapping["step_id"]] = {"data": step_output_raw}
                        else:
                            state["steps"][step_row._mapping["step_id"]] = {
                                "data": json.loads(step_output_raw)
                            }
                    continue

                if step_status == "failed":
                    self._mark_orchestration_failed(
                        session,
                        orchestration_run_id,
                        step_row._mapping["step_index"],
                        step_row._mapping["error_code"] or "orchestration.step_failed",
                        step_row._mapping["error_message"] or f"Step {step_row._mapping['step_index']} failed",
                    )
                    session.commit()
                    session.close()
                    return {"status": "failed", "failed_step": step_row._mapping["step_index"]}

                when_condition = None
                when_raw = step_row._mapping["when_condition"]
                if when_raw:
                    if isinstance(when_raw, dict):
                        when_condition = when_raw
                    else:
                        when_condition = json.loads(when_raw)

                if not self._evaluate_when(when_condition, state):
                    session.execute(
                        self._orchestration_steps_update_status(),
                        {
                            "step_id": step_row._mapping["step_id"],
                            "status": "skipped",
                            "completed_at": now,
                        },
                    )
                    session.commit()
                    state["steps"][step_row._mapping["step_id"]] = {"data": {}}
                    continue

                input_payload_raw = step_row._mapping["input_payload"]
                if isinstance(input_payload_raw, dict):
                    input_map = input_payload_raw
                else:
                    input_map = json.loads(input_payload_raw) if input_payload_raw else {}
                resolved_input = self._resolve_input_map(input_map, state)

                session.execute(
                    self._orchestration_steps_update_running(),
                    {
                        "step_id": step_row._mapping["step_id"],
                        "status": "running",
                        "input_payload": json.dumps(resolved_input),
                        "started_at": now,
                    },
                )
                session.commit()

                try:
                    step_output = self._execute_step(
                        session,
                        orchestration_run_id,
                        step_row,
                        resolved_input,
                    )

                    session.execute(
                        self._orchestration_steps_update_succeeded(),
                        {
                            "step_id": step_row._mapping["step_id"],
                            "status": "succeeded",
                            "step_output": json.dumps(step_output),
                            "completed_at": datetime.now(UTC),
                        },
                    )
                    session.commit()

                    state["steps"][step_row._mapping["step_id"]] = {"data": step_output}

                except OrchestrationStepError as e:
                    session.execute(
                        self._orchestration_steps_update_failed(),
                        {
                            "step_id": step_row._mapping["step_id"],
                            "status": "failed",
                            "error_code": e.error_code,
                            "error_message": e.error_message,
                            "completed_at": datetime.now(UTC),
                        },
                    )
                    self._mark_orchestration_failed(
                        session,
                        orchestration_run_id,
                        step_row._mapping["step_index"],
                        e.error_code,
                        e.error_message,
                    )
                    session.commit()
                    session.close()
                    return {"status": "failed", "failed_step": step_row._mapping["step_index"]}

            self._mark_orchestration_succeeded(session, orchestration_run_id)
            session.commit()

            self._dispatch_callback(orchestration_run_id)
            session.close()
            return {"status": "succeeded"}
        except Exception as e:
            session.rollback()
            # If we've already marked as running, mark as failed for consistency
            try:
                run_check = session.execute(
                    self._orchestration_runs_select_by_id(),
                    {"orchestration_run_id": orchestration_run_id},
                ).fetchone()
                if run_check and run_check._mapping["status"] == "running":
                    self._mark_orchestration_failed(
                        session,
                        orchestration_run_id,
                        -1,
                        "orchestration.internal_error",
                        str(e),
                    )
                    session.commit()
            except Exception:
                pass  # Best effort cleanup
            session.close()
            raise

    def _execute_step(
        self,
        session: Any,
        orchestration_run_id: str,
        step_row: Any,
        resolved_input: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.runtime_service:
            raise OrchestrationError("RuntimeService not available")

        run = session.execute(
            self._orchestration_runs_select_by_id(),
            {"orchestration_run_id": orchestration_run_id},
        ).fetchone()

        from app.domain.runtime.models import RuntimeRequest

        max_attempts = step_row._mapping["max_retries"] + 1
        for attempt in range(max_attempts):
            run_id = f"run_{uuid4().hex}"
            try:
                request = RuntimeRequest(
                    site_id=run._mapping["site_id"],
                    ability_name=step_row._mapping["ability_name"],
                    channel="orchestration",
                    execution_kind="text",
                    profile_id="text.balanced",
                    input_payload=resolved_input,
                    canonical_run_id=run_id,
                    timeout_seconds=step_row._mapping["timeout_seconds"],
                    execution_pattern="orchestrated",
                )
                response = self.runtime_service.execute(request)
                return response.result if hasattr(response, 'result') else {}
            except (ProviderExecutionError, Exception) as e:
                if attempt < max_attempts - 1:
                    logger.warning(
                        "Step %s attempt %d failed, retrying: %s",
                        step_row._mapping["step_id"],
                        attempt + 1,
                        e,
                    )
                    session.execute(
                        self._orchestration_steps_update_retry(),
                        {
                            "step_id": step_row._mapping["step_id"],
                            "retry_count": attempt + 1,
                        },
                    )
                    session.commit()
                    continue
                error_code = getattr(e, "error_code", "orchestration.step_execution_failed")
                error_message = str(e)
                raise OrchestrationStepError(
                    orchestration_run_id,
                    step_row._mapping["step_index"],
                    str(error_code),
                    error_message,
                )

        raise OrchestrationStepError(
            orchestration_run_id,
            step_row._mapping["step_index"],
            "orchestration.step_retries_exhausted",
            f"Step {step_row._mapping['step_index']} exhausted {max_attempts} attempts",
        )

    def _resolve_input_map(
        self,
        input_map: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        resolved = {}
        for key, value in input_map.items():
            resolved[key] = self._resolve_input_map_value(value, state)
        return resolved

    def _resolve_input_map_value(
        self,
        value: Any,
        state: dict[str, Any],
    ) -> Any:
        if isinstance(value, dict):
            return {k: self._resolve_input_map_value(v, state) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_input_map_value(item, state) for item in value]
        if isinstance(value, str) and value.startswith("$"):
            return self._read_ref_path(value, state)
        return value

    def _read_ref_path(self, ref_path: str, state: dict[str, Any]) -> Any:
        parts = ref_path.split(".")
        if not parts:
            return None

        root = parts[0]
        if root not in REF_PATH_PREFIXES:
            return None

        current: Any = state.get(root)
        for part in parts[1:]:
            if current is None or not isinstance(current, dict):
                return None
            current = current.get(part)
        return current

    def _evaluate_when(
        self,
        condition: dict[str, Any] | None,
        state: dict[str, Any],
    ) -> bool:
        if not condition:
            return True

        operator = condition.get("op", "")
        if operator not in ALLOWED_WHEN_OPERATORS:
            if operator in COMPLEX_WHEN_OPERATORS:
                return self._evaluate_complex_when(condition, state)
            return True

        ref = condition.get("ref", "")
        ref_value = self._read_ref_path(ref, state) if ref else None

        if operator == "always":
            return True
        if operator == "never":
            return False
        if operator == "truthy":
            return bool(ref_value)
        if operator == "falsy":
            return not ref_value
        if operator == "exists":
            return ref_value is not None
        if operator == "not_exists":
            return ref_value is None
        if operator == "empty":
            return ref_value is None or ref_value == "" or ref_value == [] or ref_value == {}
        if operator == "not_empty":
            return ref_value is not None and ref_value != "" and ref_value != [] and ref_value != {}
        if operator == "eq":
            expected = condition.get("value")
            return ref_value == expected
        if operator == "neq":
            expected = condition.get("value")
            return ref_value != expected

        return True

    def _evaluate_complex_when(
        self,
        condition: dict[str, Any],
        state: dict[str, Any],
    ) -> bool:
        operator = condition.get("op", "")
        conditions = condition.get("conditions", [])

        if operator == "any":
            return any(self._evaluate_when(c, state) for c in conditions)
        if operator == "all":
            return all(self._evaluate_when(c, state) for c in conditions)

        return True

    def _dispatch_callback(self, orchestration_run_id: str) -> None:
        session = _get_db_session(self.database_url)
        try:
            run = session.execute(
                self._orchestration_runs_select_by_id(),
                {"orchestration_run_id": orchestration_run_id},
            ).fetchone()
            if not run or not run._mapping.get("callback_url"):
                session.close()
                return

            result = self._build_result(session, orchestration_run_id)
            payload = {
                "orchestration_run_id": orchestration_run_id,
                "workflow_id": result.workflow_id,
                "status": result.status,
                "result_summary": result.result_summary,
                "error_code": result.error_code,
                "error_message": result.error_message,
            }

            if self.callback_dispatcher:
                from app.adapters.callbacks.base import RuntimeCallbackDispatchRequest

                request = RuntimeCallbackDispatchRequest(
                    run_id=orchestration_run_id,
                    trace_id=orchestration_run_id,
                    callback_url=run._mapping["callback_url"],
                    payload=payload,
                    site_id=run._mapping["site_id"],
                )
                try:
                    self.callback_dispatcher.dispatch(request)
                except Exception as e:
                    logger.error(
                        "Failed to dispatch orchestration callback: %s", e
                    )
            session.close()
        except Exception:
            session.close()
            raise

    def _build_result(self, session: Any, orchestration_run_id: str) -> OrchestrationResult:
        run = session.execute(
            self._orchestration_runs_select_by_id(),
            {"orchestration_run_id": orchestration_run_id},
        ).fetchone()
        if not run:
            raise OrchestrationNotFoundError(orchestration_run_id)

        counts = session.execute(
            self._orchestration_steps_count_by_status(),
            {"orchestration_run_id": orchestration_run_id},
        ).fetchone()

        run_map = run._mapping
        counts_map = counts._mapping if counts else {}

        return OrchestrationResult(
            orchestration_run_id=run_map["orchestration_run_id"],
            status=run_map["status"],
            workflow_id=run_map["workflow_id"],
            workflow_version=run_map["workflow_version"],
            submitted_at=run_map["submitted_at"].isoformat() if run_map["submitted_at"] else "",
            completed_at=run_map["completed_at"].isoformat() if run_map["completed_at"] else None,
            callback_url=run_map.get("callback_url", ""),
            result_summary=(
                json.loads(run_map["result_summary"]) if run_map.get("result_summary") and not isinstance(run_map["result_summary"], dict)
                else run_map.get("result_summary")
            ),
            error_code=run_map.get("error_code"),
            error_message=run_map.get("error_message"),
            failed_step_index=run_map.get("failed_step_index"),
            step_count=counts_map.get("total", 0),
            succeeded_count=counts_map.get("succeeded", 0),
            failed_count=counts_map.get("failed", 0),
            skipped_count=counts_map.get("skipped", 0),
        )

    def _mark_orchestration_failed(
        self,
        session: Any,
        orchestration_run_id: str,
        failed_step_index: int,
        error_code: str,
        error_message: str,
    ) -> None:
        now = datetime.now(UTC)
        session.execute(
            self._orchestration_runs_update_failed(),
            {
                "orchestration_run_id": orchestration_run_id,
                "status": "failed",
                "completed_at": now,
                "error_code": error_code,
                "error_message": error_message,
                "failed_step_index": failed_step_index,
            },
        )

    def _mark_orchestration_succeeded(
        self,
        session: Any,
        orchestration_run_id: str,
    ) -> None:
        now = datetime.now(UTC)
        session.execute(
            self._orchestration_runs_update_succeeded(),
            {
                "orchestration_run_id": orchestration_run_id,
                "status": "succeeded",
                "completed_at": now,
            },
        )

    def _mark_canceled(
        self,
        session: Any,
        orchestration_run_id: str,
    ) -> None:
        now = datetime.now(UTC)
        session.execute(
            self._orchestration_runs_update_canceled(),
            {
                "orchestration_run_id": orchestration_run_id,
                "status": "canceled",
                "completed_at": now,
                "error_code": "orchestration.canceled",
                "error_message": "Canceled by user",
            },
        )

    def _load_initial_input(
        self,
        session: Any,
        orchestration_run_id: str,
    ) -> dict[str, Any]:
        run = session.execute(
            self._orchestration_runs_select_by_id(),
            {"orchestration_run_id": orchestration_run_id},
        ).fetchone()
        if run and run._mapping.get("result_summary"):
            summary = json.loads(run._mapping["result_summary"])
            if isinstance(summary, dict) and "initial_input" in summary:
                return summary["initial_input"]
        return {}

    def _orchestration_runs_insert(self):
        from sqlalchemy import text
        return text(
            "INSERT INTO orchestration_runs "
            "(orchestration_run_id, site_id, workflow_id, workflow_version, status, "
            "callback_url, max_duration_seconds) "
            "VALUES (:orchestration_run_id, :site_id, :workflow_id, :workflow_version, "
            ":status, :callback_url, :max_duration_seconds)"
        )

    def _orchestration_steps_insert(self):
        from sqlalchemy import text
        return text(
            "INSERT INTO orchestration_steps "
            "(step_id, orchestration_run_id, step_index, ability_name, input_payload, "
            "status, retry_count, max_retries, timeout_seconds, when_condition, foreach_path) "
            "VALUES (:step_id, :orchestration_run_id, :step_index, :ability_name, "
            ":input_payload, :status, :retry_count, :max_retries, :timeout_seconds, "
            ":when_condition, :foreach_path)"
        )

    def _orchestration_runs_select_by_id(self):
        from sqlalchemy import text
        return text(
            "SELECT * FROM orchestration_runs "
            "WHERE orchestration_run_id = :orchestration_run_id"
        )

    def _orchestration_steps_select_by_run(self):
        from sqlalchemy import text
        return text(
            "SELECT * FROM orchestration_steps "
            "WHERE orchestration_run_id = :orchestration_run_id"
        )

    def _orchestration_steps_select_by_run_ordered(self):
        from sqlalchemy import text
        return text(
            "SELECT * FROM orchestration_steps "
            "WHERE orchestration_run_id = :orchestration_run_id "
            "ORDER BY step_index ASC"
        )

    def _orchestration_runs_update_status(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_runs SET status = :status, updated_at = NOW() "
            "WHERE orchestration_run_id = :orchestration_run_id"
        )

    def _orchestration_runs_update_cancel_requested(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_runs SET cancel_requested_at = :cancel_requested_at, "
            "updated_at = NOW() WHERE orchestration_run_id = :orchestration_run_id"
        )

    def _orchestration_runs_update_failed(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_runs SET status = :status, completed_at = :completed_at, "
            "error_code = :error_code, error_message = :error_message, "
            "failed_step_index = :failed_step_index, updated_at = NOW() "
            "WHERE orchestration_run_id = :orchestration_run_id"
        )

    def _orchestration_runs_update_succeeded(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_runs SET status = :status, completed_at = :completed_at, "
            "updated_at = NOW() WHERE orchestration_run_id = :orchestration_run_id"
        )

    def _orchestration_runs_update_canceled(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_runs SET status = :status, completed_at = :completed_at, "
            "error_code = :error_code, error_message = :error_message, "
            "updated_at = NOW() WHERE orchestration_run_id = :orchestration_run_id"
        )

    def _orchestration_steps_update_status(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_steps SET status = :status, completed_at = :completed_at, "
            "updated_at = NOW() WHERE step_id = :step_id"
        )

    def _orchestration_steps_update_running(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_steps SET status = :status, input_payload = :input_payload, "
            "started_at = :started_at, updated_at = NOW() WHERE step_id = :step_id"
        )

    def _orchestration_steps_update_succeeded(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_steps SET status = :status, step_output = :step_output, "
            "completed_at = :completed_at, updated_at = NOW() WHERE step_id = :step_id"
        )

    def _orchestration_steps_update_failed(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_steps SET status = :status, error_code = :error_code, "
            "error_message = :error_message, completed_at = :completed_at, "
            "updated_at = NOW() WHERE step_id = :step_id"
        )

    def _orchestration_steps_update_retry(self):
        from sqlalchemy import text
        return text(
            "UPDATE orchestration_steps SET retry_count = :retry_count, "
            "updated_at = NOW() WHERE step_id = :step_id"
        )

    def _orchestration_steps_count_by_status(self):
        from sqlalchemy import text
        return text(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) as succeeded, "
            "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed, "
            "SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) as skipped "
            "FROM orchestration_steps "
            "WHERE orchestration_run_id = :orchestration_run_id"
        )
