from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.callbacks.base import (
    RuntimeCallbackDispatchError,
    RuntimeCallbackDispatchRequest,
    RuntimeCallbackDispatchResult,
)
from app.core.config import Settings
from app.core.models import RunRecord
from app.core.secrets import encrypt_runtime_terminal_callback_secret
from app.domain.runtime.callback_delivery import RuntimeCallbackDeliveryService
from app.domain.runtime.errors import RuntimeCallbackConfigurationError
from app.domain.runtime.models import RuntimeRequest

NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


class FakeStore:
    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}
        self.sites: dict[str, object] = {}
        self.due_run_ids: list[str] = []
        self.recovered_runs: list[RunRecord] = []
        self.commit_count = 0
        self.reclaim_calls = 0


class FakeSession:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def commit(self) -> None:
        self.store.commit_count += 1


class FakeRuntimeRepository:
    def __init__(self, session: FakeSession) -> None:
        self.store = session.store

    def list_due_callback_run_ids(self, *, limit: int, now: datetime) -> list[str]:
        del now
        return self.store.due_run_ids[:limit]

    def claim_callback_dispatch(self, run_id: str, *, now: datetime) -> RunRecord | None:
        run = self.store.runs.get(run_id)
        if run is None:
            return None
        if run_id in self.store.due_run_ids:
            self.store.due_run_ids.remove(run_id)
        run.callback_status = "dispatching"
        run.callback_attempt_count = int(run.callback_attempt_count or 0) + 1
        run.callback_last_attempt_at = now
        run.callback_next_attempt_at = None
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        return self.store.runs.get(run_id)

    def get_site(self, site_id: str) -> object | None:
        return self.store.sites.get(site_id)

    def mark_callback_delivery_failed(
        self,
        run: RunRecord,
        *,
        error_code: str,
        error_message: str,
        retry_at: datetime | None,
    ) -> RunRecord:
        run.callback_status = "pending" if retry_at is not None else "failed"
        run.callback_next_attempt_at = retry_at
        run.callback_delivered_at = None
        run.callback_last_error_code = error_code
        run.callback_last_error_message = error_message
        return run

    def mark_callback_delivered(
        self,
        run: RunRecord,
        *,
        delivered_at: datetime,
    ) -> RunRecord:
        run.callback_status = "delivered"
        run.callback_delivered_at = delivered_at
        run.callback_next_attempt_at = None
        run.callback_last_error_code = None
        run.callback_last_error_message = None
        return run

    def reclaim_stale_callback_dispatches(
        self,
        *,
        limit: int,
        now: datetime,
    ) -> list[RunRecord]:
        del now
        self.store.reclaim_calls += 1
        recovered = self.store.recovered_runs[:limit]
        self.store.recovered_runs = self.store.recovered_runs[limit:]
        return recovered


class RecordingDispatcher:
    def __init__(
        self,
        *,
        status_code: int = 204,
        error: RuntimeCallbackDispatchError | None = None,
    ) -> None:
        self.status_code = status_code
        self.error = error
        self.requests: list[RuntimeCallbackDispatchRequest] = []

    def dispatch(
        self,
        request: RuntimeCallbackDispatchRequest,
    ) -> RuntimeCallbackDispatchResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return RuntimeCallbackDispatchResult(status_code=self.status_code)


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        admin_session_secret="a" * 32,
        portal_jwt_secret="p" * 32,
    )


def _request(*, callback_url: str = "") -> RuntimeRequest:
    return RuntimeRequest(
        site_id="site_alpha",
        ability_name="npcink/test-callback",
        contract_version="callback-test.v1",
        channel="openapi",
        execution_kind="text",
        profile_id="text.balanced",
        callback_url=callback_url,
        input_payload={"text": "callback delivery"},
    )


def _run(*, run_id: str = "run_callback") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        site_id="site_alpha",
        account_id="acct_alpha",
        subscription_id="sub_alpha",
        plan_version_id="plan-v1",
        ability_name="npcink/test-callback",
        ability_family="text",
        skill_id=None,
        workflow_id=None,
        contract_version="callback-test.v1",
        channel="openapi",
        execution_kind="text",
        execution_tier="cloud",
        execution_pattern="inline",
        data_classification="internal",
        profile_id="text.balanced",
        canonical_run_id="local_run_1",
        status="succeeded",
        idempotency_key="idem_callback",
        request_fingerprint="fingerprint_callback",
        trace_id="trace_callback",
        cancel_requested_at=None,
        canceled_at=None,
        input_json={},
        execution_input_ciphertext=None,
        policy_json={
            "storage_mode": "result_only",
            "runtime_callback": {
                "source": "site_registered",
                "callback_url": "https://callback.example.test/runtime",
                "key_id": "callback_key",
                "callback_id": "runtime_terminal_test",
                "registered": True,
            },
            "task_backend": {
                "enabled": False,
                "callback_mode": "polling_preferred",
            },
        },
        result_ref="inline",
        result_json={"output_text": "safe result"},
        error_code=None,
        error_message=None,
        callback_status="pending",
        callback_attempt_count=0,
        callback_last_attempt_at=None,
        callback_delivered_at=None,
        callback_next_attempt_at=NOW,
        callback_last_error_code=None,
        callback_last_error_message=None,
        selected_provider_id="openai",
        selected_model_id="gpt-test",
        selected_instance_id="openai:gpt-test",
        fallback_used=False,
        started_at=NOW - timedelta(minutes=1),
        processing_started_at=NOW - timedelta(seconds=50),
        finished_at=NOW,
        retention_expires_at=NOW + timedelta(hours=1),
        result_purged_at=None,
    )


def _site(settings: Settings, *, secret: str) -> SimpleNamespace:
    return SimpleNamespace(
        metadata_json={
            "runtime_callbacks": {
                "terminal": {
                    "enabled": True,
                    "callback_url": "https://callback.example.test/runtime",
                    "key_id": "callback_key",
                    "secret_ciphertext": encrypt_runtime_terminal_callback_secret(
                        secret,
                        settings=settings,
                    ),
                    "callback_id": "runtime_terminal_test",
                }
            }
        }
    )


def _install_fake_repository(
    monkeypatch: pytest.MonkeyPatch,
    store: FakeStore,
) -> None:
    monkeypatch.setattr(
        "app.domain.runtime.callback_delivery.get_session",
        lambda database_url: FakeSession(store),
    )
    monkeypatch.setattr(
        "app.domain.runtime.callback_delivery.RuntimeRepository",
        FakeRuntimeRepository,
    )


def test_disabled_callback_and_missing_dispatcher_do_not_deliver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    _install_fake_repository(monkeypatch, store)
    service = RuntimeCallbackDeliveryService(
        database_url="unused",
        settings=_settings(),
        dispatcher=None,
    )
    disabled_site = SimpleNamespace(
        metadata_json={"runtime_callbacks": {"terminal": {"enabled": False}}}
    )

    assert service.dispatch_pending_callbacks(max_callbacks=2) == []
    assert store.reclaim_calls == 0
    assert (
        service.resolve_callback_target(
            site=disabled_site,
            request=_request(),
            callback_mode="polling_preferred",
        )
        == {}
    )
    with pytest.raises(RuntimeCallbackConfigurationError, match="disabled"):
        service.resolve_callback_target(
            site=disabled_site,
            request=_request(),
            callback_mode="terminal_callback_required",
        )


def test_registered_target_resolution_rejects_override_plaintext_and_bad_ciphertext() -> None:
    settings = _settings()
    callback_secret = "callback-secret-used-only-for-signing"
    service = RuntimeCallbackDeliveryService(
        database_url="unused",
        settings=settings,
        dispatcher=None,
    )
    site = _site(settings, secret=callback_secret)

    target = service.resolve_callback_target(
        site=site,
        request=_request(),
        callback_mode="polling_preferred",
    )

    assert target == {
        "source": "site_registered",
        "callback_url": "https://callback.example.test/runtime",
        "key_id": "callback_key",
        "callback_id": "runtime_terminal_test",
        "registered": True,
    }
    assert callback_secret not in json.dumps(target)
    with pytest.raises(RuntimeCallbackConfigurationError, match="overrides are not accepted"):
        service.resolve_callback_target(
            site=site,
            request=_request(callback_url="https://override.example.test/runtime"),
            callback_mode="polling_preferred",
        )

    plaintext_site = SimpleNamespace(
        metadata_json={
            "runtime_callbacks": {
                "terminal": {
                    "callback_url": "https://callback.example.test/runtime",
                    "key_id": "callback_key",
                    "secret": callback_secret,
                }
            }
        }
    )
    with pytest.raises(RuntimeCallbackConfigurationError, match="re-saved as ciphertext"):
        service.resolve_callback_target(
            site=plaintext_site,
            request=_request(),
            callback_mode="polling_preferred",
        )

    bad_ciphertext_site = SimpleNamespace(
        metadata_json={
            "runtime_callbacks": {
                "terminal": {
                    "callback_url": "https://callback.example.test/runtime",
                    "key_id": "callback_key",
                    "secret_ciphertext": "not-valid-ciphertext",
                }
            }
        }
    )
    with pytest.raises(RuntimeCallbackConfigurationError, match="could not be decrypted"):
        service.resolve_callback_target(
            site=bad_ciphertext_site,
            request=_request(),
            callback_mode="polling_preferred",
        )


def test_successful_delivery_preserves_signing_fields_and_excludes_secret_from_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    callback_secret = "callback-secret-used-only-for-signing"
    store = FakeStore()
    run = _run()
    store.runs[run.run_id] = run
    store.due_run_ids.append(run.run_id)
    store.sites[run.site_id] = _site(settings, secret=callback_secret)
    _install_fake_repository(monkeypatch, store)
    dispatcher = RecordingDispatcher(status_code=202)
    service = RuntimeCallbackDeliveryService(
        database_url="unused",
        settings=settings,
        dispatcher=dispatcher,
    )

    dispatched = service.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == [
        {
            "run_id": run.run_id,
            "callback_status": "delivered",
            "trace_id": run.trace_id,
            "status_code": 202,
        }
    ]
    assert len(dispatcher.requests) == 1
    callback_request = dispatcher.requests[0]
    assert callback_request.event == "runtime.run.terminal"
    assert callback_request.site_id == "site_alpha"
    assert callback_request.callback_url == "https://callback.example.test/runtime"
    assert callback_request.key_id == "callback_key"
    assert callback_request.callback_id == "runtime_terminal_test"
    assert callback_request.secret
    callback_request_repr = repr(callback_request)
    assert callback_secret not in callback_request_repr
    assert "secret=" not in callback_request_repr
    assert callback_request.payload["canonical_run_id"] == "local_run_1"
    serialized_payload = json.dumps(callback_request.payload, ensure_ascii=False)
    serialized_policy = json.dumps(run.policy_json, ensure_ascii=False)
    serialized_summary = json.dumps(dispatched, ensure_ascii=False)
    assert callback_secret not in serialized_payload
    assert callback_secret not in serialized_policy
    assert callback_secret not in serialized_summary
    assert callback_secret not in repr(service)
    assert "secret" not in serialized_payload.lower()
    assert run.callback_status == "delivered"


@pytest.mark.parametrize(
    "scenario",
    [
        "non_site_registered",
        "missing_site",
        "missing_registration",
        "disabled_registration",
        "changed_callback_id",
        "callback_url_mismatch",
        "key_id_mismatch",
    ],
)
def test_claim_fails_closed_when_persisted_target_is_not_current_registration(
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    settings = _settings()
    callback_secret = "config-invalid-signing-secret"
    store = FakeStore()
    run = _run(run_id=f"run_config_invalid_{scenario}")
    assert isinstance(run.policy_json, dict)
    callback_policy = run.policy_json["runtime_callback"]
    assert isinstance(callback_policy, dict)
    if scenario == "non_site_registered":
        callback_policy["source"] = "request_override"

    site = _site(settings, secret=callback_secret)
    callbacks = site.metadata_json["runtime_callbacks"]
    assert isinstance(callbacks, dict)
    registration = callbacks["terminal"]
    assert isinstance(registration, dict)
    if scenario == "missing_registration":
        site = SimpleNamespace(metadata_json={})
    elif scenario == "disabled_registration":
        registration["enabled"] = False
    elif scenario == "changed_callback_id":
        registration["callback_id"] = "runtime_terminal_changed"
    elif scenario == "callback_url_mismatch":
        registration["callback_url"] = "https://changed.example.test/runtime"
    elif scenario == "key_id_mismatch":
        registration["key_id"] = "changed_callback_key"

    store.runs[run.run_id] = run
    store.due_run_ids.append(run.run_id)
    if scenario != "missing_site":
        store.sites[run.site_id] = site
    _install_fake_repository(monkeypatch, store)
    dispatcher = RecordingDispatcher()
    service = RuntimeCallbackDeliveryService(
        database_url="unused",
        settings=settings,
        dispatcher=dispatcher,
    )

    dispatched = service.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == []
    assert dispatcher.requests == []
    assert run.callback_status == "failed"
    assert run.callback_next_attempt_at is None
    assert run.callback_last_error_code == "runtime.callback_config_invalid"
    assert callback_secret not in str(run.callback_last_error_message)
    assert callback_secret not in json.dumps(run.policy_json, ensure_ascii=False)
    assert callback_secret not in json.dumps(dispatched, ensure_ascii=False)


@pytest.mark.parametrize(
    ("retryable", "expected_status", "expects_retry"),
    [(True, "pending", True), (False, "failed", False)],
)
def test_delivery_failure_preserves_retry_semantics(
    monkeypatch: pytest.MonkeyPatch,
    retryable: bool,
    expected_status: str,
    expects_retry: bool,
) -> None:
    settings = _settings()
    store = FakeStore()
    run = _run(run_id=f"run_failure_{retryable}")
    store.runs[run.run_id] = run
    store.due_run_ids.append(run.run_id)
    store.sites[run.site_id] = _site(settings, secret="callback-failure-signing-secret")
    _install_fake_repository(monkeypatch, store)
    dispatcher = RecordingDispatcher(
        error=RuntimeCallbackDispatchError(
            "runtime.callback_upstream_error",
            "callback upstream failed",
            retryable=retryable,
        )
    )
    service = RuntimeCallbackDeliveryService(
        database_url="unused",
        settings=settings,
        dispatcher=dispatcher,
        max_attempts=2,
        retry_backoff_seconds=30,
    )

    dispatched = service.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == [
        {
            "run_id": run.run_id,
            "callback_status": expected_status,
            "trace_id": run.trace_id,
        }
    ]
    assert (run.callback_next_attempt_at is not None) is expects_retry
    assert run.callback_last_error_code == "runtime.callback_upstream_error"
    assert "secret" not in json.dumps(dispatched).lower()


def test_stale_dispatch_recovery_invokes_explicit_audit_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeStore()
    recovered = _run(run_id="run_recovered")
    recovered.callback_status = "dispatching"
    recovered.callback_last_attempt_at = NOW - timedelta(minutes=7)
    store.recovered_runs.append(recovered)
    _install_fake_repository(monkeypatch, store)
    dispatcher = RecordingDispatcher()
    audit_calls: list[tuple[str, datetime]] = []

    def record_recovery(run: RunRecord, *, recovered_at: datetime) -> None:
        audit_calls.append((run.run_id, recovered_at))

    service = RuntimeCallbackDeliveryService(
        database_url="unused",
        settings=_settings(),
        dispatcher=dispatcher,
        recovery_audit_callback=record_recovery,
    )

    assert service.dispatch_pending_callbacks(max_callbacks=1) == []
    assert store.reclaim_calls == 1
    assert len(audit_calls) == 1
    assert audit_calls[0][0] == "run_recovered"
    assert audit_calls[0][1].tzinfo is UTC


def test_runtime_service_no_longer_owns_callback_delivery_details() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    service_path = repository_root / "app/domain/runtime/service.py"
    delivery_path = repository_root / "app/domain/runtime/callback_delivery.py"
    service_tree = ast.parse(service_path.read_text(encoding="utf-8"))
    delivery_tree = ast.parse(delivery_path.read_text(encoding="utf-8"))
    service_class = next(
        node
        for node in service_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeService"
    )
    delivery_class = next(
        node
        for node in delivery_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeCallbackDeliveryService"
    )
    service_methods = {
        node.name for node in service_class.body if isinstance(node, ast.FunctionDef)
    }
    delivery_methods = {
        node.name for node in delivery_class.body if isinstance(node, ast.FunctionDef)
    }
    moved_methods = {
        "_resolve_callback_target",
        "_resolve_registered_callback_config",
        "_dispatch_single_pending_callback",
        "_claim_next_pending_callback",
        "_recover_stale_callback_dispatches",
        "_build_callback_payload",
        "_build_callback_result_payload",
        "_resolve_callback_retry_at",
    }
    imported_modules = {
        alias.name
        for node in ast.walk(delivery_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_modules.update(
        node.module
        for node in ast.walk(delivery_tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    forbidden_import_prefixes = (
        "app.domain.runtime.service",
        "app.domain.commercial",
        "app.adapters.queue",
        "app.adapters.providers",
        "app.domain.runtime.execution",
    )

    assert "dispatch_pending_callbacks" in service_methods
    assert service_methods.isdisjoint(moved_methods)
    assert {
        "resolve_callback_target",
        "dispatch_pending_callbacks",
        "_resolve_registered_callback_config",
        "_dispatch_single_pending_callback",
        "_claim_next_pending_callback",
        "_recover_stale_callback_dispatches",
        "_build_callback_payload",
        "_resolve_callback_retry_at",
    } <= delivery_methods
    assert not {
        module
        for module in imported_modules
        if any(
            module == prefix or module.startswith(f"{prefix}.")
            for prefix in forbidden_import_prefixes
        )
    }
