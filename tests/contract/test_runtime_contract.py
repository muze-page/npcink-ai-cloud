from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.providers.base import ProviderAdapter
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ProviderCallRecord,
    ProviderConnection,
    ReplayReceipt,
    RunRecord,
    RuntimeGuardEvent,
)
from app.core.secrets import encrypt_runtime_terminal_callback_secret
from app.core.security import REPLAY_SCOPE_PUBLIC_POST_SITE
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import (
    TEST_INTERNAL_AUTH_TOKEN,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'runtime-contract.sqlite3'}"


def _seed_openai_model_allowlist(database_url: str) -> None:
    with get_session(database_url) as session:
        session.add(
            ProviderConnection(
                connection_id="openai",
                provider_type="openai_compatible",
                display_name="OpenAI",
                enabled=True,
                base_url="https://api.openai.test/v1",
                config_json={
                    "provider_id": "openai",
                    "kind": "openai_compatible",
                    "capability_ids": ["text_generation"],
                    "runtime_profile_ids": ["text.balanced"],
                    "model_ids": ["gpt-4.1-mini"],
                },
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
        )
        session.commit()


def _build_client(
    tmp_path: Path,
    *,
    providers: dict[str, ProviderAdapter] | None = None,
    settings_overrides: dict[str, object] | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    _seed_openai_model_allowlist(database_url)
    seed_site_auth(
        database_url,
        site_id="site_contract",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        **(settings_overrides or {}),
    )
    return database_url, TestClient(
        create_app(CloudServices(settings=settings, providers=providers or {}))
    )


def _runtime_callback_metadata(callback_url: str) -> dict[str, object]:
    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
    )
    return {
        "runtime_callbacks": {
            "terminal": {
                "enabled": True,
                "callback_url": callback_url,
                "key_id": "runtime_callback_key",
                "secret_ciphertext": encrypt_runtime_terminal_callback_secret(
                    "runtime-callback-secret-for-tests-32b",
                    settings=settings,
                ),
                "callback_id": "runtime_terminal_contract",
            }
        }
    }


def test_runtime_execute_response_shape_is_stable(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    request_payload = {
        "site_id": "site_contract",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "canonical_run_id": "wp_run_contract_execute_001",
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "timeout_seconds": 1800,
        "retry_max": 2,
        "retention_ttl": 86400,
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-001",
        "input": {"messages": [{"role": "user", "content": "contract shape"}]},
    }
    body = json.dumps(request_payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-001",
                trace_id="tracecontract001000000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert set(payload["data"].keys()) == {
        "run_id",
        "canonical_run_id",
        "status",
        "trace_id",
        "profile_id",
        "provider_id",
        "model_id",
        "instance_id",
        "fallback_used",
        "idempotent_replay",
        "error_code",
        "error_message",
        "error_stage",
        "retryable",
        "retry_exhausted",
        "provider_call_count",
        "execution_context",
        "task_backend",
        "run_lifecycle",
        "result",
    }
    assert payload["data"]["canonical_run_id"] == "wp_run_contract_execute_001"
    assert set(payload["data"]["execution_context"].keys()) == {
        "skill_id",
        "workflow_id",
        "contract_version",
        "ability_family",
        "execution_tier",
        "execution_pattern",
        "data_classification",
        "storage_mode",
    }
    assert set(payload["data"]["task_backend"].keys()) == {
        "enabled",
        "mode",
        "callback_mode",
        "polling_interval_sec",
        "callback_url",
        "timeout_seconds",
        "retry_max",
        "retention_ttl",
        "status",
    }
    assert set(payload["data"]["run_lifecycle"].keys()) == {
        "phase",
        "queue_mode",
        "requested_at",
        "processing_started_at",
        "terminal_at",
        "terminal_status",
        "cancel",
        "callback",
        "retention",
    }
    assert set(payload["data"]["run_lifecycle"]["cancel"].keys()) == {
        "supported",
        "state",
        "requested_at",
        "canceled_at",
    }
    assert set(payload["data"]["run_lifecycle"]["callback"].keys()) == {
        "requested",
        "mode",
        "url_present",
        "dispatch_status",
        "attempt_count",
        "last_attempt_at",
        "delivered_at",
        "next_attempt_at",
        "last_error_code",
    }

    run_id = payload["data"]["run_id"]
    status_response = client.get(
        f"/v1/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}",
            site_id="site_contract",
            trace_id="tracecontract002000000000000000",
        ),
    )
    status_payload = status_response.json()
    assert set(status_payload["data"].keys()) == {
        "run_id",
        "canonical_run_id",
        "site_id",
        "ability_name",
        "skill_id",
        "workflow_id",
        "contract_version",
        "channel",
        "execution_kind",
        "execution_tier",
        "execution_pattern",
        "data_classification",
        "profile_id",
        "status",
        "idempotency_key",
        "trace_id",
        "provider_id",
        "model_id",
        "instance_id",
        "fallback_used",
        "error_code",
        "error_message",
        "error_stage",
        "retryable",
        "retry_exhausted",
        "started_at",
        "finished_at",
        "provider_call_count",
        "task_backend",
        "run_lifecycle",
    }
    assert status_payload["data"]["canonical_run_id"] == "wp_run_contract_execute_001"

    result_response = client.get(
        f"/v1/runs/{run_id}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_contract",
            trace_id="tracecontract003000000000000000",
        ),
    )
    result_payload = result_response.json()
    assert set(result_payload["data"].keys()) == {
        "run_id",
        "canonical_run_id",
        "status",
        "execution_context",
        "task_backend",
        "run_lifecycle",
        "result",
        "provider_calls",
    }
    assert result_payload["data"]["canonical_run_id"] == "wp_run_contract_execute_001"
    assert set(result_payload["data"]["execution_context"].keys()) == {
        "skill_id",
        "workflow_id",
        "contract_version",
        "ability_family",
        "execution_tier",
        "execution_pattern",
        "data_classification",
        "storage_mode",
    }
    assert set(result_payload["data"]["task_backend"].keys()) == {
        "enabled",
        "mode",
        "callback_mode",
        "polling_interval_sec",
        "callback_url",
        "timeout_seconds",
        "retry_max",
        "retention_ttl",
        "status",
    }
    assert set(result_payload["data"]["run_lifecycle"].keys()) == {
        "phase",
        "queue_mode",
        "requested_at",
        "processing_started_at",
        "terminal_at",
        "terminal_status",
        "cancel",
        "callback",
        "retention",
    }
    assert set(result_payload["data"]["run_lifecycle"]["cancel"].keys()) == {
        "supported",
        "state",
        "requested_at",
        "canceled_at",
    }
    assert set(result_payload["data"]["run_lifecycle"]["callback"].keys()) == {
        "requested",
        "mode",
        "url_present",
        "dispatch_status",
        "attempt_count",
        "last_attempt_at",
        "delivered_at",
        "next_attempt_at",
        "last_error_code",
    }
    assert set(result_payload["data"]["provider_calls"][0].keys()) == {
        "provider_id",
        "model_id",
        "instance_id",
        "region",
        "latency_ms",
        "tokens_in",
        "tokens_out",
        "cost",
        "retry_count",
        "fallback_used",
        "error_code",
        "error_stage",
        "retryable",
    }

    dispose_engine(database_url)


def test_runtime_resolve_response_shape_includes_execution_context(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    request_payload = {
        "site_id": "site_contract",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "resolve shape"}]},
    }
    body = json.dumps(request_payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/resolve",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_contract",
                trace_id="tracecontractresolve001000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload["data"].keys()) == {
        "profile_id",
        "execution_kind",
        "revision",
        "policy",
        "selected_candidate",
        "candidates",
        "execution_context",
        "run_lifecycle",
        "task_backend",
    }
    assert set(payload["data"]["execution_context"].keys()) == {
        "skill_id",
        "workflow_id",
        "contract_version",
        "ability_family",
        "execution_tier",
        "execution_pattern",
        "data_classification",
        "storage_mode",
    }

    dispose_engine(database_url)


def test_runtime_public_ingress_rejects_step_offload(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    request_payload = {
        "site_id": "site_contract",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "skill_id": "content_summary_seo",
        "workflow_id": "content_summary_seo_completion",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "step_offload",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-step-offload-001",
        "input": {"messages": [{"role": "user", "content": "reject public ingress"}]},
    }
    request_body = json.dumps(request_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=request_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-step-offload-001",
                trace_id="tracecontractstepoffload000001",
                body=request_body,
            )
        ),
    )
    resolve_response = client.post(
        "/v1/runtime/resolve",
        content=request_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_contract",
                trace_id="tracecontractstepoffload000002",
                body=request_body,
            )
        ),
    )

    assert execute_response.status_code == 422
    assert resolve_response.status_code == 422

    dispose_engine(database_url)


def test_runtime_execute_requires_signed_headers(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    response = client.post(
        "/v1/runtime/execute",
        json={
            "site_id": "site_contract",
            "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
            "channel": "openapi",
            "execution_kind": "text",
            "profile_id": "text.balanced",
            "idempotency_key": "contract-runtime-002",
            "input": {"messages": [{"role": "user", "content": "unsigned"}]},
        },
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "auth.site_id_required"

    dispose_engine(database_url)


def test_runtime_cancel_response_shape_is_stable(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    request_payload = {
        "site_id": "site_contract",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "canonical_run_id": "wp_run_contract_cancel_001",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-cancel-001",
        "input": {"messages": [{"role": "user", "content": "cancel shape"}]},
    }
    execute_body = json.dumps(request_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=execute_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-cancel-001",
                trace_id="tracecontractcancel001000000000",
                body=execute_body,
            )
        ),
    )

    assert execute_response.status_code == 200
    run_id = str(execute_response.json()["data"]["run_id"])

    cancel_response = client.post(
        f"/v1/runs/{run_id}/cancel",
        content=b"",
        headers=build_auth_headers(
            "POST",
            f"/v1/runs/{run_id}/cancel",
            site_id="site_contract",
            idempotency_key="contract-runtime-cancel-002",
            trace_id="tracecontractcancel002000000000",
            body=b"",
        ),
    )

    assert cancel_response.status_code == 200
    payload = cancel_response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert set(payload["data"].keys()) == {
        "run_id",
        "canonical_run_id",
        "site_id",
        "ability_name",
        "skill_id",
        "workflow_id",
        "contract_version",
        "channel",
        "execution_kind",
        "execution_tier",
        "execution_pattern",
        "data_classification",
        "profile_id",
        "status",
        "idempotency_key",
        "trace_id",
        "provider_id",
        "model_id",
        "instance_id",
        "fallback_used",
        "error_code",
        "error_message",
        "error_stage",
        "retryable",
        "retry_exhausted",
        "started_at",
        "finished_at",
        "provider_call_count",
        "task_backend",
        "run_lifecycle",
    }
    assert payload["data"]["canonical_run_id"] == "wp_run_contract_cancel_001"
    assert set(payload["data"]["run_lifecycle"]["cancel"].keys()) == {
        "supported",
        "state",
        "requested_at",
        "canceled_at",
    }
    assert set(payload["data"]["run_lifecycle"]["callback"].keys()) == {
        "requested",
        "mode",
        "url_present",
        "dispatch_status",
        "attempt_count",
        "last_attempt_at",
        "delivered_at",
        "next_attempt_at",
        "last_error_code",
    }

    dispose_engine(database_url)


def test_runtime_request_policy_boundary_is_frozen(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    blocked_payload = {
        "site_id": "site_contract",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-policy-001",
        "input": {"messages": [{"role": "user", "content": "blocked policy"}]},
        "policy": {
            "allow_fallback": True,
            "requires_confirm": True,
            "tool_policy": {"allow_write": True},
            "approval_policy": {"mode": "proposal_only"},
            "apply_policy": {"post_write": True},
        },
    }
    blocked_body = json.dumps(blocked_payload).encode("utf-8")
    blocked_response = client.post(
        "/v1/runtime/execute",
        content=blocked_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-policy-001",
                trace_id="tracecontractpolicy00100000000",
                body=blocked_body,
            )
        ),
    )

    assert blocked_response.status_code == 422
    blocked_detail = json.dumps(blocked_response.json()["detail"])
    assert "local governance or final-write fields" in blocked_detail
    assert "requires_confirm" in blocked_detail
    assert "tool_policy" in blocked_detail
    assert "approval_policy" in blocked_detail
    assert "apply_policy" in blocked_detail

    allowed_payload = {
        "site_id": "site_contract",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-policy-002",
        "input": {"messages": [{"role": "user", "content": "allowed policy"}]},
        "policy": {"allow_fallback": True},
    }
    allowed_body = json.dumps(allowed_payload).encode("utf-8")
    allowed_response = client.post(
        "/v1/runtime/execute",
        content=allowed_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-policy-002",
                trace_id="tracecontractpolicy00200000000",
                body=allowed_body,
            )
        ),
    )

    assert allowed_response.status_code == 200
    assert allowed_response.json()["data"]["status"] == "succeeded"

    dispose_engine(database_url)


def test_runtime_internal_diagnostics_shape_exposes_pressure_and_stale_issue_kinds(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_contract",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        concurrency={"max_active_runs": 3},
        site_metadata=_runtime_callback_metadata("https://callbacks.magick.test/contracts"),
    )
    queued_payload = {
        "site_id": "site_contract",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 120,
        },
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-diag-queued-001",
        "input": {"messages": [{"role": "user", "content": "queued stale shape"}]},
    }
    queued_body = json.dumps(queued_payload).encode("utf-8")
    queued_response = client.post(
        "/v1/runtime/execute",
        content=queued_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-diag-queued-001",
                trace_id="tracecontractdiagqueued00100000",
                body=queued_body,
            )
        ),
    )

    callback_payload = {
        "site_id": "site_contract",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "contract_version": "v1",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-diag-callback-001",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
        },
        "input": {"messages": [{"role": "user", "content": "callback overdue shape"}]},
    }
    callback_body = json.dumps(callback_payload).encode("utf-8")
    callback_response = client.post(
        "/v1/runtime/execute",
        content=callback_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-diag-callback-001",
                trace_id="tracecontractdiagcallback0010",
                body=callback_body,
            )
        ),
    )
    dispatching_payload = {
        **callback_payload,
        "idempotency_key": "contract-runtime-diag-dispatching-001",
    }
    dispatching_body = json.dumps(dispatching_payload).encode("utf-8")
    dispatching_response = client.post(
        "/v1/runtime/execute",
        content=dispatching_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-diag-dispatching-001",
                trace_id="tracecontractdiagdispatching01",
                body=dispatching_body,
            )
        ),
    )

    assert queued_response.status_code == 200
    assert callback_response.status_code == 200
    assert dispatching_response.status_code == 200

    queued_run_id = str(queued_response.json()["data"]["run_id"])
    callback_run_id = str(callback_response.json()["data"]["run_id"])
    dispatching_run_id = str(dispatching_response.json()["data"]["run_id"])

    with get_session(database_url) as session:
        queued_run = session.scalar(select(RunRecord).where(RunRecord.run_id == queued_run_id))
        callback_run = session.scalar(select(RunRecord).where(RunRecord.run_id == callback_run_id))
        dispatching_run = session.scalar(
            select(RunRecord).where(RunRecord.run_id == dispatching_run_id)
        )
        assert queued_run is not None
        assert callback_run is not None
        assert dispatching_run is not None
        queued_run.started_at = datetime.now(UTC) - timedelta(minutes=10)
        callback_run.status = "failed"
        callback_run.error_code = "provider.rate_limited"
        callback_run.error_message = "provider rate limited"
        callback_run.finished_at = datetime.now(UTC) - timedelta(minutes=8)
        callback_run.selected_provider_id = "openai"
        callback_run.selected_model_id = "gpt-4o-mini"
        callback_run.selected_instance_id = "openai-global-gpt-4o-mini"
        callback_run.callback_status = "pending"
        callback_run.callback_next_attempt_at = datetime.now(UTC) - timedelta(minutes=9)
        session.add(
            ProviderCallRecord(
                run_id=callback_run.run_id,
                provider_id="openai",
                model_id="gpt-4o-mini",
                instance_id="openai-global-gpt-4o-mini",
                region="global",
                latency_ms=0,
                tokens_in=0,
                tokens_out=0,
                cost=0.0,
                retry_count=1,
                fallback_used=False,
                error_code="provider.rate_limited",
                created_at=datetime.now(UTC) - timedelta(minutes=8),
            )
        )
        dispatching_run.callback_status = "dispatching"
        dispatching_run.callback_attempt_count = 1
        dispatching_run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=6)
        session.commit()

    summary_response = client.get(
        "/internal/service/runtime/diagnostics/summary?site_id=site_contract&recent_minutes=120",
        headers=build_internal_headers(),
    )
    queued_stale_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=queued_stale&site_id=site_contract&limit=5",
        headers=build_internal_headers(),
    )
    callback_overdue_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=callback_overdue&site_id=site_contract&limit=5",
        headers=build_internal_headers(),
    )

    assert summary_response.status_code == 200
    summary_payload = summary_response.json()
    assert summary_payload["meta"]["revision"] == "m8"
    assert set(summary_payload["data"].keys()) == {
        "filters",
        "generated_at",
        "guard",
        "queue",
        "cancel",
        "callback",
        "retention",
        "failures",
        "operator_guidance",
    }
    assert set(summary_payload["data"]["queue"].keys()) == {
        "queued_runs",
        "queued_oldest_requested_at",
        "running_runs",
        "running_oldest_processing_started_at",
        "queued_oldest_age_seconds",
        "running_oldest_age_seconds",
        "pressure_thresholds",
        "pressure_state",
        "pressure_reasons",
    }
    assert set(summary_payload["data"]["cancel"].keys()) == {
        "active_requests",
        "oldest_requested_at",
        "canceled_recent",
        "oldest_request_age_seconds",
        "pressure_thresholds",
        "pressure_state",
        "pressure_reasons",
    }
    assert set(summary_payload["data"]["callback"].keys()) == {
        "pending",
        "due_now",
        "dispatching",
        "recoverable_dispatching",
        "failed",
        "delivered_recent",
        "oldest_due_at",
        "dispatching_oldest_last_attempt_at",
        "pending_not_due",
        "oldest_due_age_seconds",
        "dispatching_oldest_age_seconds",
        "recovery_action",
        "pressure_thresholds",
        "pressure_state",
        "pressure_reasons",
    }
    assert set(summary_payload["data"]["failures"].keys()) == {
        "failed_recent",
        "last_failed_at",
        "top_error_codes",
        "provider_error_calls_recent",
        "top_provider_errors",
        "pressure_state",
        "pressure_reasons",
        "dominant_error",
    }
    assert set(summary_payload["data"]["operator_guidance"].keys()) == {
        "state",
        "primary_reason",
        "primary_evidence_path",
        "suggested_actions",
    }
    assert summary_payload["data"]["queue"]["pressure_state"] == "attention"
    assert "queue.queued_stale" in summary_payload["data"]["queue"]["pressure_reasons"]
    assert summary_payload["data"]["callback"]["pressure_state"] == "attention"
    assert "callback.overdue" in summary_payload["data"]["callback"]["pressure_reasons"]
    assert "callback.dispatching_stale" in summary_payload["data"]["callback"]["pressure_reasons"]
    assert summary_payload["data"]["callback"]["recoverable_dispatching"] == 1
    assert summary_payload["data"]["callback"]["recovery_action"] == (
        "requeue_pending_after_stale_dispatch_lease"
    )
    assert summary_payload["data"]["failures"]["failed_recent"] == 1
    assert summary_payload["data"]["failures"]["provider_error_calls_recent"] == 1
    assert summary_payload["data"]["failures"]["dominant_error"]["error_code"] == (
        "provider.rate_limited"
    )
    assert summary_payload["data"]["failures"]["dominant_error"]["error_stage"] == "provider"
    assert summary_payload["data"]["operator_guidance"]["primary_reason"] == ("callback_delivery")
    assert any(
        item["action"] == "inspect_provider_credentials_quota_and_health"
        for item in summary_payload["data"]["operator_guidance"]["suggested_actions"]
    )

    assert queued_stale_response.status_code == 200
    queued_stale_payload = queued_stale_response.json()
    assert queued_stale_payload["meta"]["revision"] == "m7"
    assert queued_stale_payload["data"]["filters"]["issue_kind"] == "queued_stale"
    assert set(queued_stale_payload["data"]["items"][0].keys()) == {
        "run_id",
        "site_id",
        "status",
        "trace_id",
        "ability_name",
        "ability_family",
        "profile_id",
        "execution_pattern",
        "callback_requested",
        "callback_status",
        "callback_attempt_count",
        "callback_next_attempt_at",
        "callback_last_attempt_at",
        "callback_last_error_code",
        "cancel_requested_at",
        "canceled_at",
        "retention_expires_at",
        "result_purged_at",
        "started_at",
        "processing_started_at",
        "finished_at",
        "suggested_actions",
    }
    assert queued_stale_payload["data"]["items"][0]["suggested_actions"][0]["action"] == (
        "requeue_stale_queued"
    )
    assert queued_stale_payload["data"]["items"][0]["suggested_actions"][0]["mode"] == (
        "worker_auto"
    )

    assert callback_overdue_response.status_code == 200
    callback_overdue_payload = callback_overdue_response.json()
    assert callback_overdue_payload["meta"]["revision"] == "m7"
    assert callback_overdue_payload["data"]["filters"]["issue_kind"] == "callback_overdue"
    assert any(
        item["run_id"] == callback_run_id
        and item["suggested_actions"][0]["action"] == "redeliver_failed_callback"
        and item["suggested_actions"][0]["mode"] == "worker_auto"
        for item in callback_overdue_payload["data"]["items"]
    )

    dispose_engine(database_url)


def test_runtime_internal_abuse_guard_contract_exposes_watchlist_and_scope_severity(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "public_post_max_requests_per_window": 3,
            "public_guard_max_reject_events_per_site_window": 2,
        },
    )

    with get_session(database_url) as session:
        for index in range(4):
            session.add(
                ReplayReceipt(
                    scope_kind=REPLAY_SCOPE_PUBLIC_POST_SITE,
                    scope_id="site_contract",
                    replay_key=f"contract-burst-{index}",
                    method="POST",
                    path="/v1/runtime/execute",
                    trace_id=f"contract-burst-{index}",
                    created_at=datetime.now(UTC) - timedelta(minutes=1),
                    expires_at=datetime.now(UTC) + timedelta(minutes=9),
                )
            )
        for index in range(3):
            session.add(
                RuntimeGuardEvent(
                    auth_surface="public_runtime",
                    scope_kind=REPLAY_SCOPE_PUBLIC_POST_SITE,
                    scope_id="site_contract",
                    site_id="site_contract",
                    key_id="key_default",
                    client_ref="127.0.0.1",
                    event_code="auth.rate_limit_exceeded" if index < 2 else "auth.replay_blocked",
                    status_code=429 if index < 2 else 409,
                    method="POST",
                    path="/v1/runtime/execute",
                    trace_id=f"contract-guard-{index}",
                    payload_json={"source": "contract_test"},
                    created_at=datetime.now(UTC) - timedelta(minutes=2),
                )
            )
        session.commit()

    response = client.get(
        "/internal/service/runtime/diagnostics/abuse-guard?window_seconds=600&cooldown_window_seconds=1800&limit_per_scope=5",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["revision"] == "m7"
    assert set(payload["data"].keys()) == {
        "generated_at",
        "window_seconds",
        "cooldown_window_seconds",
        "limit_per_scope",
        "guard_event_codes",
        "watchlist_summary",
        "watchlist",
        "scopes",
    }
    assert set(payload["data"]["watchlist_summary"].keys()) == {
        "highest_severity",
        "attention_count",
        "critical_count",
        "request_burst_count",
        "reject_storm_count",
    }
    assert payload["data"]["watchlist_summary"]["highest_severity"] in {
        "healthy",
        "attention",
        "critical",
    }
    public_site_scope = payload["data"]["scopes"][REPLAY_SCOPE_PUBLIC_POST_SITE]
    assert set(public_site_scope.keys()) == {
        "max_requests_per_window",
        "items",
        "request_pressure",
        "max_reject_events_per_cooldown_window",
        "cooldown_items",
        "cooldown_pressure",
    }
    assert set(public_site_scope["request_pressure"].keys()) == {
        "highest_severity",
        "healthy_count",
        "attention_count",
        "critical_count",
    }
    assert set(public_site_scope["cooldown_pressure"].keys()) == {
        "highest_severity",
        "healthy_count",
        "attention_count",
        "critical_count",
    }
    assert set(public_site_scope["items"][0].keys()) == {
        "scope_id",
        "request_count",
        "first_seen_at",
        "last_seen_at",
        "scope_kind",
        "signal_kind",
        "severity",
        "observed_count",
        "limit",
        "limit_ratio",
        "remaining_before_limit",
        "exceeded_by",
        "reason_codes",
        "event_code_breakdown",
    }
    assert set(public_site_scope["cooldown_items"][0].keys()) == {
        "scope_id",
        "event_count",
        "first_seen_at",
        "last_seen_at",
        "scope_kind",
        "signal_kind",
        "severity",
        "observed_count",
        "limit",
        "limit_ratio",
        "remaining_before_limit",
        "exceeded_by",
        "reason_codes",
        "event_code_breakdown",
    }
    assert payload["data"]["watchlist"]
    watchlist_item = payload["data"]["watchlist"][0]
    assert {
        "scope_id",
        "first_seen_at",
        "last_seen_at",
        "scope_kind",
        "signal_kind",
        "severity",
        "observed_count",
        "limit",
        "limit_ratio",
        "remaining_before_limit",
        "exceeded_by",
        "reason_codes",
        "event_code_breakdown",
    }.issubset(set(watchlist_item.keys()))
    assert "request_count" in watchlist_item or "event_count" in watchlist_item

    dispose_engine(database_url)


def test_runtime_internal_backlog_diagnostics_contract_exposes_scope_layering(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_contract",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
        concurrency={"max_active_runs": 2},
    )

    queued_payload = {
        "site_id": "site_contract",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_pattern": "whole_run_offload",
        "task_backend": {"enabled": True, "mode": "polling"},
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-backlog-queued-001",
        "input": {"messages": [{"role": "user", "content": "queued backlog shape"}]},
    }
    running_payload = {
        "site_id": "site_contract",
        "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "contract-runtime-backlog-running-001",
        "input": {"messages": [{"role": "user", "content": "running backlog shape"}]},
    }
    queued_body = json.dumps(queued_payload).encode("utf-8")
    running_body = json.dumps(running_payload).encode("utf-8")
    queued_response = client.post(
        "/v1/runtime/execute",
        content=queued_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-backlog-queued-001",
                trace_id="tracecontractbacklogqueued001",
                body=queued_body,
            )
        ),
    )
    running_response = client.post(
        "/v1/runtime/execute",
        content=running_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-runtime-backlog-running-001",
                trace_id="tracecontractbacklogrunning01",
                body=running_body,
            )
        ),
    )

    assert queued_response.status_code == 200
    assert running_response.status_code == 200

    queued_run_id = str(queued_response.json()["data"]["run_id"])
    running_run_id = str(running_response.json()["data"]["run_id"])

    with get_session(database_url) as session:
        queued_run = session.scalar(select(RunRecord).where(RunRecord.run_id == queued_run_id))
        running_run = session.scalar(select(RunRecord).where(RunRecord.run_id == running_run_id))
        assert queued_run is not None
        assert running_run is not None
        queued_run.status = "queued"
        queued_run.started_at = datetime.now(UTC) - timedelta(minutes=8)
        running_run.status = "running"
        running_run.processing_started_at = datetime.now(UTC) - timedelta(minutes=16)
        session.commit()

    response = client.get(
        "/internal/service/runtime/diagnostics/backlog?scope_kind=ability_family&site_id=site_contract&limit=5",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["revision"] == "m1"
    assert set(payload["data"].keys()) == {
        "filters",
        "generated_at",
        "thresholds",
        "totals",
        "scope_pressure",
        "items",
    }
    assert set(payload["data"]["thresholds"].keys()) == {
        "queued_aging_after_seconds",
        "queued_stale_after_seconds",
        "running_aging_after_seconds",
        "running_stale_after_seconds",
    }
    assert set(payload["data"]["totals"].keys()) == {
        "queued",
        "running",
        "bottleneck_state",
        "pressure_state",
        "pressure_reasons",
        "lease_recovery_inputs",
    }
    assert set(payload["data"]["totals"]["queued"].keys()) == {
        "runs",
        "stale_runs",
        "oldest_age_seconds",
        "p95_age_seconds",
        "state",
        "age_buckets",
    }
    assert set(payload["data"]["totals"]["running"].keys()) == {
        "runs",
        "stale_runs",
        "oldest_age_seconds",
        "p95_age_seconds",
        "state",
        "age_buckets",
    }
    assert set(payload["data"]["scope_pressure"].keys()) == {
        "scope_kind",
        "active_scope_count",
        "pressured_scope_count",
        "stale_scope_count",
        "spread_state",
        "dominant_scope_share",
    }
    assert set(payload["data"]["items"][0].keys()) == {
        "scope_kind",
        "scope_id",
        "total_runs",
        "queued",
        "running",
        "bottleneck_state",
        "pressure_state",
        "pressure_reasons",
        "lease_recovery_inputs",
    }
    assert set(payload["data"]["items"][0]["queued"].keys()) == {
        "runs",
        "stale_runs",
        "oldest_age_seconds",
        "p95_age_seconds",
        "state",
        "age_buckets",
    }
    assert set(payload["data"]["items"][0]["running"].keys()) == {
        "runs",
        "stale_runs",
        "oldest_age_seconds",
        "p95_age_seconds",
        "state",
        "age_buckets",
    }
    assert set(payload["data"]["items"][0]["lease_recovery_inputs"].keys()) == {
        "queued_stale_runs",
        "running_stale_runs",
        "total_stale_runs",
    }
    assert payload["data"]["scope_pressure"]["scope_kind"] == "ability_family"
    assert any(item["scope_id"] == "automation" for item in payload["data"]["items"])
    assert any(item["scope_id"] == "workflow" for item in payload["data"]["items"])

    dispose_engine(database_url)


class _ContractFixedTextProviderAdapter(ProviderAdapter):
    """Minimal provider adapter that returns a fixed text result for contract tests."""

    provider_id = "openai"

    def __init__(self, output_text: str) -> None:
        self._output_text = output_text

    def execute(self, request: object) -> object:
        from app.adapters.providers.base import ProviderExecutionResult

        return ProviderExecutionResult(
            output={
                "output_text": self._output_text,
                "messages": [{"role": "assistant", "content": self._output_text}],
                "model_id": getattr(request, "model_id", "gpt-4.1-mini"),
            },
            latency_ms=80,
            tokens_in=10,
            tokens_out=max(1, len(self._output_text.split())),
            cost=0.0,
        )

    def fetch_catalog(self) -> object:
        from app.adapters.providers.base import ProviderCatalogSnapshot

        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name="OpenAI Compatible",
            adapter_type="openai",
            models=[],
        )


def test_runtime_execute_adapter_origin_analysis_shape(tmp_path: Path) -> None:
    """Adapter-origin analysis using ability_family=openclaw produces the analysis envelope."""
    providers: dict[str, ProviderAdapter] = {
        "openai": _ContractFixedTextProviderAdapter("Top sellers are A, B, C.")
    }
    database_url, client = _build_client(tmp_path, providers=providers)
    request_payload = {
        "site_id": "site_contract",
        "ability_name": "openclaw/analysis/product-recommendation",
        "ability_family": "openclaw",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "profile_id": "text.balanced",
        "idempotency_key": "contract-analysis-001",
        "trace_id": "trace-analysis-001",
        "input": {
            "messages": [{"role": "user", "content": "analyze top sellers"}],
            "proposal_id": "proposal_abc_123",
            "correlation_id": "corr_xyz_789",
            "external_thread_id": "ext_thread_001",
            "openclaw_thread_id": "oc_thread_002",
        },
        "policy": {"allow_fallback": True},
    }
    body = json.dumps(request_payload).encode("utf-8")
    response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_contract",
                idempotency_key="contract-analysis-001",
                trace_id="traceanalysis00100000000000000",
                body=body,
            )
        ),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution_context"]["ability_family"] == "openclaw"

    result = data["result"]
    assert result["analysis_type"] in {"report", "recommendation", "proposal_input"}
    assert "summary" in result
    assert "findings" in result
    assert "recommendations" in result
    assert "requires_local_approval" in result
    assert "proposal_handoff" in result
    assert "_cloud_raw_result" in result

    handoff = result["proposal_handoff"]
    assert handoff["proposal_id"] == "proposal_abc_123"
    assert handoff["correlation_id"] == "corr_xyz_789"
    assert handoff["external_thread_id"] == "ext_thread_001"
    assert handoff["openclaw_thread_id"] == "oc_thread_002"

    run_id = data["run_id"]

    # Run status endpoint still uses the existing stable shape
    status_response = client.get(
        f"/v1/runs/{run_id}",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}",
            site_id="site_contract",
            trace_id="traceanalysis00200000000000000",
        ),
    )
    assert status_response.status_code == 200
    status_data = status_response.json()["data"]
    assert "run_id" in status_data
    assert status_data["ability_name"] == "openclaw/analysis/product-recommendation"

    # Result endpoint also exposes the analysis envelope
    result_response = client.get(
        f"/v1/runs/{run_id}/result",
        headers=build_auth_headers(
            "GET",
            f"/v1/runs/{run_id}/result",
            site_id="site_contract",
            trace_id="traceanalysis00300000000000000",
        ),
    )
    assert result_response.status_code == 200
    result_data = result_response.json()["data"]
    assert result_data["execution_context"]["ability_family"] == "openclaw"
    assert result_data["result"]["proposal_handoff"]["proposal_id"] == "proposal_abc_123"

    dispose_engine(database_url)
