from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.callbacks.http import HttpRuntimeCallbackDispatcher
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    SUBSCRIPTION_STATUS_PAST_DUE,
    AccountEntitlementSnapshot,
    AccountSubscription,
    BillingSnapshot,
    ProviderCallRecord,
    ReplayReceipt,
    RunRecord,
    RuntimeGuardEvent,
    UsageMeterEvent,
)
from app.core.security import REPLAY_SCOPE_PUBLIC_POST_SITE
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from app.domain.runtime.service import RuntimeService
from app.domain.usage.rollup import UsageRollupService
from app.workers.ops_cadence import run_due_tasks
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    build_internal_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'service-routes.sqlite3'}"


def _build_client(
    tmp_path: Path,
    *,
    settings_overrides: dict[str, object] | None = None,
) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    settings_kwargs = {
        "_env_file": None,
        "project_name": "Magick AI Cloud Test",
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": TEST_INTERNAL_AUTH_TOKEN,
        "admin_session_secret": TEST_ADMIN_SESSION_SECRET,
        "portal_jwt_secret": TEST_PORTAL_JWT_SECRET,
        "openai_api_key": "",
        "anthropic_api_key": "",
        "litellm_provider_enabled": False,
        "litellm_api_key": "",
        "vllm_provider_enabled": False,
        "vllm_api_key": "",
        "tei_provider_enabled": False,
        "tei_api_key": "",
        "openrouter_provider_enabled": False,
        "openrouter_api_key": "",
        "siliconflow_provider_enabled": False,
        "siliconflow_api_key": "",
        "web_search_provider": "disabled",
        "web_search_tavily_api_key": "",
        "web_search_bocha_api_key": "",
        "web_search_jina_reader_api_key": "",
        "web_search_apify_api_token": "",
        "image_source_provider": "disabled",
        "image_source_auto_strategy": "first_available",
        "image_source_unsplash_access_key": "",
        "image_source_pixabay_api_key": "",
        "image_source_pexels_api_key": "",
        "site_knowledge_embedding_provider": "deterministic",
    }
    settings_kwargs.update(settings_overrides or {})
    settings = Settings(**settings_kwargs)
    return database_url, TestClient(create_app(CloudServices(settings=settings)))


def _runtime_service_settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        openai_api_key="",
        anthropic_api_key="",
        litellm_provider_enabled=False,
        litellm_api_key="",
        vllm_provider_enabled=False,
        vllm_api_key="",
        tei_provider_enabled=False,
        tei_api_key="",
        openrouter_provider_enabled=False,
        openrouter_api_key="",
        siliconflow_provider_enabled=False,
        siliconflow_api_key="",
        site_knowledge_embedding_provider="deterministic",
    )


def test_admin_web_search_provider_settings_are_masked_and_update_runtime(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "web_search_admin_env_path": str(env_path),
        },
    )

    initial = client.get(
        "/internal/service/admin/web-search-providers",
        headers=build_internal_headers(),
    )
    assert initial.status_code == 200
    assert initial.json()["data"]["providers"]["tavily"]["configured"] is False
    assert initial.json()["data"]["workflow_metadata"]["workflow_id"] == (
        "external_web_evidence_preflight"
    )
    assert initial.json()["data"]["workflow_metadata"]["direct_wordpress_write"] is False

    response = client.post(
        "/internal/service/admin/web-search-providers",
        headers=build_internal_headers(idempotency_key="web-search-provider-save"),
        json={
            "provider_mode": "auto",
            "providers": {
                "tavily": {
                    "base_url": "https://api.tavily.com",
                    "secret": "tvly-test-secret",
                    "secret_pool": ["tvly-pool-a", "tvly-pool-b"],
                    "secret_pool_labels": ["account-a", "account-b"],
                    "timeout_seconds": 9,
                    "cost": 0.001,
                },
                "bocha": {
                    "base_url": "https://api.bochaai.com/v1",
                    "secret": "bocha-test-secret",
                    "timeout_seconds": 11,
                    "cost": 0.002,
                },
                "jina_reader": {
                    "enabled": True,
                    "base_url": "https://r.jina.ai",
                    "secret": "jina-test-secret",
                    "timeout_seconds": 7,
                    "max_pages": 3,
                    "cost": 0.0003,
                },
                "apify": {
                    "base_url": "https://api.apify.com/v2",
                    "secret": "apify-test-token",
                    "actor_id": "apify/google-search-scraper",
                    "timeout_seconds": 30,
                    "cost": 0.01,
                },
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider_mode"] == "auto"
    assert data["providers"]["tavily"]["configured"] is True
    assert data["providers"]["tavily"]["key_pool_count"] == 2
    assert data["providers"]["tavily"]["key_pool_labels"] == ["account-a", "account-b"]
    assert data["providers"]["bocha"]["configured"] is True
    assert data["providers"]["jina_reader"]["enabled"] is True
    assert data["workflow_metadata"]["workflow_version"] == ("web_search_evidence_workflow.v1")
    assert "tvly-test-secret" not in json.dumps(data)
    assert "tvly-pool-a" not in json.dumps(data)
    assert "tvly-pool-b" not in json.dumps(data)
    assert "bocha-test-secret" not in json.dumps(data)
    assert "jina-test-secret" not in json.dumps(data)
    assert "apify-test-token" not in json.dumps(data)
    env_text = env_path.read_text(encoding="utf-8")
    assert "MAGICK_CLOUD_WEB_SEARCH_PROVIDER=auto" in env_text
    assert "MAGICK_CLOUD_WEB_SEARCH_TAVILY_API_KEY=tvly-test-secret" in env_text
    assert "MAGICK_CLOUD_WEB_SEARCH_TAVILY_API_KEYS=tvly-pool-a,tvly-pool-b" in env_text
    assert "MAGICK_CLOUD_WEB_SEARCH_TAVILY_API_KEY_LABELS=account-a,account-b" in env_text
    assert "MAGICK_CLOUD_WEB_SEARCH_BOCHA_API_KEY=bocha-test-secret" in env_text
    assert "MAGICK_CLOUD_WEB_SEARCH_JINA_READER_API_KEY=jina-test-secret" in env_text
    assert "MAGICK_CLOUD_WEB_SEARCH_APIFY_API_TOKEN=apify-test-token" in env_text

    services = client.app.state.services
    assert services.settings.web_search_provider == "auto"
    assert services.settings.web_search_tavily_api_keys == "tvly-pool-a,tvly-pool-b"
    assert services.settings.web_search_tavily_api_key_labels == "account-a,account-b"
    assert services.settings.web_search_bocha_api_key == "bocha-test-secret"


def test_admin_agent_workflow_metadata_projection_is_read_only(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)

    response = client.get(
        "/internal/service/admin/agent-workflow-metadata",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["projection_version"] == "cloud-agent-workflow-metadata.v1"
    assert data["projection_kind"] == "read_only_runtime_metadata"
    assert data["registry_version"] == "cloud-agent-workflow-metadata.v1"
    agents = {item["agent_id"]: item for item in data["agents"]}
    assert "internal_ops_advisor_agent" in agents
    assert agents["site_knowledge_suggestion_agent"]["handoff_owner"] == ("wordpress_local")
    assert agents["site_knowledge_suggestion_agent"]["direct_wordpress_write"] is False
    workflows = {item["workflow_id"]: item for item in data["workflows"]}
    assert workflows["external_web_evidence_preflight"]["handoff_owner"] == ("wordpress_local")
    assert workflows["media_derivative_artifact_generation"]["direct_wordpress_write"] is False

    unauthorized = client.get("/internal/service/admin/agent-workflow-metadata")
    assert unauthorized.status_code in (401, 403)


def test_admin_image_source_provider_settings_are_masked_and_update_runtime(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env.local"
    _, client = _build_client(
        tmp_path,
        settings_overrides={
            "image_source_admin_env_path": str(env_path),
            "image_source_provider": "disabled",
        },
    )

    initial = client.get(
        "/internal/service/admin/image-source-providers",
        headers=build_internal_headers(),
    )
    assert initial.status_code == 200
    assert initial.json()["data"]["providers"]["unsplash"]["configured"] is False

    response = client.post(
        "/internal/service/admin/image-source-providers",
        headers=build_internal_headers(idempotency_key="image-source-provider-save"),
        json={
            "provider_mode": "auto",
            "providers": {
                "unsplash": {
                    "base_url": "https://api.unsplash.com",
                    "secret": "unsplash-test-secret",
                },
                "pixabay": {
                    "base_url": "https://pixabay.com/api/",
                    "secret": "pixabay-test-secret",
                },
                "pexels": {
                    "base_url": "https://api.pexels.com/v1",
                    "secret": "pexels-test-secret",
                },
            },
            "runtime": {
                "timeout_seconds": 8,
                "cost_per_query": 0.004,
                "auto_strategy": "random",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider_mode"] == "auto"
    assert data["auto_strategy"] == "random"
    assert data["runtime"]["auto_strategy"] == "random"
    assert data["providers"]["unsplash"]["configured"] is True
    assert data["providers"]["pixabay"]["configured"] is True
    assert data["providers"]["pexels"]["configured"] is True
    assert data["boundary"]["final_writes"] == "core_proposal_required"
    assert "unsplash-test-secret" not in json.dumps(data)
    assert "pixabay-test-secret" not in json.dumps(data)
    assert "pexels-test-secret" not in json.dumps(data)
    env_text = env_path.read_text(encoding="utf-8")
    assert "MAGICK_CLOUD_IMAGE_SOURCE_PROVIDER=auto" in env_text
    assert "MAGICK_CLOUD_IMAGE_SOURCE_AUTO_STRATEGY=random" in env_text
    assert "MAGICK_CLOUD_IMAGE_SOURCE_UNSPLASH_ACCESS_KEY=unsplash-test-secret" in env_text
    assert "MAGICK_CLOUD_IMAGE_SOURCE_PIXABAY_API_KEY=pixabay-test-secret" in env_text
    assert "MAGICK_CLOUD_IMAGE_SOURCE_PEXELS_API_KEY=pexels-test-secret" in env_text

    services = client.app.state.services
    assert services.settings.image_source_provider == "auto"
    assert services.settings.image_source_auto_strategy == "random"
    assert services.settings.image_source_pixabay_api_key == "pixabay-test-secret"
    assert services.settings.image_source_timeout_seconds == 8


def test_hosted_model_governance_diagnostics_summarizes_runtime_families(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    site_id = "site_model_gov"
    seed_site_auth(
        database_url,
        site_id=site_id,
        scopes=["runtime:execute", "runtime:read"],
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == f"acct_{site_id}")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None

        def add_run(
            *,
            run_id: str,
            ability_family: str,
            execution_kind: str,
            profile_id: str,
            provider_id: str,
            model_id: str,
            instance_id: str,
        ) -> None:
            session.add(
                RunRecord(
                    run_id=run_id,
                    site_id=site_id,
                    account_id=subscription.account_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    ability_name=f"magick-ai-cloud/{execution_kind}",
                    ability_family=ability_family,
                    skill_id="",
                    workflow_id="",
                    contract_version="test.v1",
                    channel="openapi",
                    execution_kind=execution_kind,
                    execution_tier="cloud",
                    execution_pattern="inline",
                    data_classification=(
                        "public_site_content" if ability_family == "knowledge" else "internal"
                    ),
                    profile_id=profile_id,
                    canonical_run_id=None,
                    status="succeeded",
                    idempotency_key=f"idem-{run_id}",
                    request_fingerprint=f"fingerprint-{run_id}",
                    trace_id=f"trace-{run_id}",
                    cancel_requested_at=None,
                    canceled_at=None,
                    input_json={},
                    execution_input_ciphertext=None,
                    policy_json={},
                    result_ref="inline",
                    result_json={"status": "ready"},
                    error_code=None,
                    error_message=None,
                    callback_status="not_requested",
                    callback_attempt_count=0,
                    callback_last_attempt_at=None,
                    callback_delivered_at=None,
                    callback_next_attempt_at=None,
                    callback_last_error_code=None,
                    callback_last_error_message=None,
                    selected_provider_id=provider_id,
                    selected_model_id=model_id,
                    selected_instance_id=instance_id,
                    fallback_used=False,
                    started_at=now - timedelta(minutes=5),
                    processing_started_at=now - timedelta(minutes=5),
                    finished_at=now - timedelta(minutes=4),
                    retention_expires_at=now + timedelta(days=1),
                    result_purged_at=None,
                )
            )

        add_run(
            run_id="run-model-gov-text",
            ability_family="text",
            execution_kind="text",
            profile_id="text.free-gpt55",
            provider_id="openai-global-gpt-5-5",
            model_id="gpt-5.5",
            instance_id="openai-global-gpt-5-5-text",
        )
        add_run(
            run_id="run-model-gov-knowledge",
            ability_family="knowledge",
            execution_kind="embedding",
            profile_id="site-knowledge.managed",
            provider_id="tei",
            model_id="tei/BAAI/bge-m3",
            instance_id="tei-site-knowledge-embedding",
        )
        add_run(
            run_id="run-model-gov-vision",
            ability_family="vision",
            execution_kind="media_derivative",
            profile_id="media_derivative.worker",
            provider_id="media_derivative",
            model_id="pillow",
            instance_id="cloud-worker",
        )
        session.flush()
        session.add_all(
            [
                ProviderCallRecord(
                    run_id="run-model-gov-text",
                    provider_id="openai-global-gpt-5-5",
                    model_id="gpt-5.5",
                    instance_id="openai-global-gpt-5-5-text",
                    region="global",
                    latency_ms=180,
                    tokens_in=20,
                    tokens_out=40,
                    cost=0.0,
                    retry_count=0,
                    fallback_used=False,
                    error_code=None,
                    created_at=now - timedelta(minutes=4),
                ),
                ProviderCallRecord(
                    run_id="run-model-gov-knowledge",
                    provider_id="tei",
                    model_id="tei/BAAI/bge-m3",
                    instance_id="tei-site-knowledge-embedding",
                    region="unspecified",
                    latency_ms=45,
                    tokens_in=5,
                    tokens_out=0,
                    cost=0.0,
                    retry_count=0,
                    fallback_used=False,
                    error_code=None,
                    created_at=now - timedelta(minutes=4),
                ),
            ]
        )
        for run_id, ability_family, execution_kind, meter_key, quantity in [
            ("run-model-gov-text", "text", "text", "runs", 1),
            ("run-model-gov-text", "text", "text", "tokens_total", 60),
            ("run-model-gov-knowledge", "knowledge", "embedding", "runs", 1),
            ("run-model-gov-knowledge", "knowledge", "embedding", "tokens_total", 5),
            ("run-model-gov-vision", "vision", "media_derivative", "runs", 1),
        ]:
            session.add(
                UsageMeterEvent(
                    account_id=subscription.account_id,
                    site_id=site_id,
                    subscription_id=subscription.subscription_id,
                    plan_version_id=subscription.plan_version_id,
                    run_id=run_id,
                    provider_call_id=None,
                    event_kind="meter",
                    meter_key=meter_key,
                    quantity=quantity,
                    ability_family=ability_family,
                    channel="openapi",
                    execution_kind=execution_kind,
                    execution_tier="cloud",
                    data_classification=(
                        "public_site_content" if ability_family == "knowledge" else "internal"
                    ),
                    currency="USD",
                    dedupe_key=f"model-gov-{run_id}-{meter_key}",
                    payload_json={},
                    created_at=now - timedelta(minutes=4),
                )
            )
        session.commit()

    unauthenticated = client.get("/internal/service/runtime/diagnostics/hosted-model-governance")
    assert unauthenticated.status_code == 401

    response = client.get(
        "/internal/service/runtime/diagnostics/hosted-model-governance"
        f"?site_id={site_id}&recent_minutes=60&limit=10",
        headers=build_internal_headers(),
    )
    admin_alias_response = client.get(
        "/internal/service/admin/hosted-model-governance"
        f"?site_id={site_id}&recent_minutes=10080&limit=10",
        headers=build_internal_headers(),
    )
    empty_cadence_response = client.get(
        "/internal/service/admin/hosted-model-governance-cadence?recent_minutes=60",
        headers=build_internal_headers(),
    )
    UsageRollupService(database_url).store_hosted_model_governance_batch(
        window_minutes=60,
        limit=10,
    )
    cadence_response = client.get(
        "/internal/service/admin/hosted-model-governance-cadence?recent_minutes=60",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    assert admin_alias_response.status_code == 200
    assert empty_cadence_response.status_code == 200
    assert empty_cadence_response.json()["data"]["available"] is False
    assert cadence_response.status_code == 200
    cadence_payload = cadence_response.json()["data"]
    assert cadence_payload["available"] is True
    assert cadence_payload["source"] == "cloud_hosted_model_governance"
    assert cadence_payload["delivery"]["owner"] == "internal_admin_readonly"
    data = response.json()["data"]
    assert admin_alias_response.json()["data"]["totals"]["runs"] == 3
    assert admin_alias_response.json()["data"]["filters"]["recent_minutes"] == 10080
    assert data["totals"]["runs"] == 3
    assert data["totals"]["provider_calls"] == 2
    assert data["boundary"]["direct_wordpress_write"] is False
    assert data["boundary"]["contains_prompt_or_result_payloads"] is False
    capability_by_id = {item["group_id"]: item for item in data["capability_groups"]}
    assert capability_by_id["text"]["tokens_total"] == 60
    assert capability_by_id["knowledge"]["tokens_total"] == 5
    assert capability_by_id["knowledge"]["provider_calls"] == 1
    assert "site-knowledge.managed" in capability_by_id["knowledge"]["profile_ids"]
    assert capability_by_id["vision"]["provider_calls"] == 0
    assert data["governance_gaps"]["unmetered_capabilities"] == []
    assert data["alert_summary"]["status"] == "warning"
    assert any(
        alert["code"] == "hosted_model.provider_call_gap"
        and alert["count"] == 1
        and "vision" in alert["capabilities"]
        for alert in data["alert_summary"]["alerts"]
    )
    assert data["alert_summary"]["boundary"]["direct_wordpress_write"] is False


def test_internal_ai_advisor_routes_are_internal_and_evidence_backed(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_advisor",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription).where(AccountSubscription.account_id == "acct_site_advisor")
        )
        assert subscription is not None
        subscription.status = SUBSCRIPTION_STATUS_PAST_DUE
        session.add(
            RuntimeGuardEvent(
                auth_surface="public",
                scope_kind="site",
                scope_id="site_advisor",
                site_id="site_advisor",
                key_id="key_default",
                client_ref="127.0.0.1",
                event_code="auth.rate_limit_exceeded",
                status_code=429,
                method="POST",
                path="/v1/runtime/execute",
                trace_id="advisor-runtime-trace",
                payload_json={"reason": "test"},
                created_at=now,
            )
        )
        session.add(
            RunRecord(
                run_id="run_advisor",
                site_id="site_advisor",
                account_id="acct_site_advisor",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                ability_name="advisor-test",
                ability_family="text",
                skill_id=None,
                workflow_id=None,
                contract_version="test",
                channel="api",
                execution_kind="text",
                execution_tier="cloud",
                execution_pattern="step_offload",
                data_classification="internal",
                profile_id="text.balanced",
                canonical_run_id=None,
                status="succeeded",
                idempotency_key="advisor-run",
                request_fingerprint="advisor-fingerprint",
                trace_id="advisor-routing-trace",
                cancel_requested_at=None,
                canceled_at=None,
                input_json={},
                execution_input_ciphertext=None,
                policy_json={},
                result_ref="inline",
                result_json={"ok": True},
                error_code=None,
                error_message=None,
                callback_status="not_requested",
                callback_attempt_count=0,
                callback_last_attempt_at=None,
                callback_delivered_at=None,
                callback_next_attempt_at=None,
                callback_last_error_code=None,
                callback_last_error_message=None,
                selected_provider_id="openai",
                selected_model_id="gpt-4o-mini",
                selected_instance_id="openai-us-east-text-balanced",
                fallback_used=False,
                started_at=now,
                processing_started_at=now,
                finished_at=now,
                retention_expires_at=now + timedelta(days=1),
                result_purged_at=None,
            )
        )
        session.flush()
        session.add(
            ProviderCallRecord(
                run_id="run_advisor",
                provider_id="openai",
                model_id="gpt-4o-mini",
                instance_id="openai-us-east-text-balanced",
                region="us-east",
                latency_ms=250,
                tokens_in=10,
                tokens_out=20,
                cost=0.001,
                retry_count=0,
                fallback_used=False,
                error_code=None,
                created_at=now,
            )
        )
        session.commit()

    unauthenticated = client.get("/internal/service/advisor/runtime")
    runtime_response = client.get(
        "/internal/service/advisor/runtime?site_id=site_advisor&recent_minutes=60",
        headers=build_internal_headers(),
    )
    commercial_response = client.get(
        "/internal/service/advisor/commercial",
        headers=build_internal_headers(),
    )
    routing_response = client.get(
        "/internal/service/advisor/routing?site_id=site_advisor",
        headers=build_internal_headers(),
    )
    operations_response = client.get(
        "/internal/service/advisor/operations?site_id=site_advisor&range=24h",
        headers=build_internal_headers(),
    )
    ops_summary_response = client.get(
        "/internal/service/advisor/ops-summary?scope=runtime&site_id=site_advisor",
        headers=build_internal_headers(),
    )
    ops_summary_preview_response = client.get(
        "/internal/service/advisor/ops-summary-preview?scope=runtime&site_id=site_advisor",
        headers=build_internal_headers(),
    )
    ops_summary_value_response = client.get(
        "/internal/service/advisor/ops-summary-value?scope=runtime&site_id=site_advisor",
        headers=build_internal_headers(),
    )

    assert unauthenticated.status_code == 401
    assert runtime_response.status_code == 200
    runtime_payload = runtime_response.json()["data"]
    assert runtime_payload["advisor_version"] == "internal-ai-advisor-v1"
    assert runtime_payload["scope"] == "runtime_operations"
    assert runtime_payload["agent_handoff"]["agent_id"] == "internal_ops_advisor_agent"
    assert runtime_payload["agent_handoff"]["handoff_type"] == "operator_recommendation"
    assert runtime_payload["agent_handoff"]["requires_operator_review"] is True
    assert runtime_payload["agent_handoff"]["direct_wordpress_write"] is False
    assert runtime_payload["agent_handoff"]["execution_pattern"] == "inline"
    assert (
        "automatic_commercial_state_mutation"
        in runtime_payload["agent_handoff"]["forbidden_actions"]
    )
    assert runtime_payload["status"] == "attention"
    assert runtime_payload["evidence"][0]["ref"] == (
        "/internal/service/runtime/diagnostics/summary"
    )
    assert {item["action"] for item in runtime_payload["recommended_actions"]} >= {
        "inspect_commercial_entitlement_and_runtime_guard"
    }
    assert any(
        signal["code"] == "runtime.guard_events" and signal["recent_rate_limit_exceeded"] == 1
        for signal in runtime_payload["signals"]
    )

    assert commercial_response.status_code == 200
    commercial_payload = commercial_response.json()["data"]
    assert commercial_payload["scope"] == "commercial_operations"
    assert commercial_payload["status"] == "attention"
    assert any(
        signal["code"] == "commercial.subscription_attention"
        for signal in commercial_payload["signals"]
    )
    assert commercial_payload["recommended_actions"][0]["requires_operator"] is True

    assert routing_response.status_code == 200
    routing_payload = routing_response.json()["data"]
    assert routing_payload["scope"] == "routing_operations"
    assert routing_payload["status"] == "ready"
    assert "text.balanced" in routing_payload["signals"][0]["recommended_profile_ids"]
    assert routing_payload["evidence"][0]["kind"] == "router_recommendation_summary"

    assert operations_response.status_code == 200
    operations_payload = operations_response.json()["data"]
    assert operations_payload["scope"] == "operations_analysis"
    assert operations_payload["agent_handoff"]["agent_role"] == "operations_analysis"
    assert operations_payload["agent_handoff"]["handoff_owner"] == "cloud_internal_operator"
    assert operations_payload["agent_handoff"]["fail_closed_behavior"] == (
        "return_deterministic_advisory_summary"
    )
    assert operations_payload["evidence"][0]["kind"] == "admin_overview"
    assert any(signal["code"] == "ops.runtime_quality" for signal in operations_payload["signals"])
    assert any(signal["code"] == "ops.provider_quality" for signal in operations_payload["signals"])
    assert operations_payload["recommended_actions"][0]["requires_operator"] is True

    assert ops_summary_response.status_code == 200
    ops_summary_payload = ops_summary_response.json()["data"]
    assert ops_summary_payload["summarizer_version"] == "internal-ops-summarizer-v1"
    assert ops_summary_payload["generation"]["mode"] == "deterministic_fallback"
    assert ops_summary_payload["source_context"]["advisor"]["agent_handoff"]["agent_id"] == (
        "internal_ops_advisor_agent"
    )
    assert (
        ops_summary_payload["source_context"]["advisor"]["agent_handoff"]["direct_wordpress_write"]
        is False
    )
    assert ops_summary_payload["agent_registry_metadata"]["agent_id"] == (
        "internal_ops_advisor_agent"
    )
    assert (
        ops_summary_payload["agent_registry_metadata"]["agent_role"]
        == (ops_summary_payload["source_context"]["advisor"]["agent_handoff"]["agent_role"])
    )
    assert ops_summary_payload["agent_registry_metadata"]["direct_wordpress_write"] is False
    assert (
        "cloud_workflow_truth"
        in ops_summary_payload["agent_registry_metadata"]["forbidden_actions"]
    )
    assert ops_summary_payload["support_draft"]
    assert "article" not in ops_summary_payload["support_draft"].lower()
    assert "write WordPress" in ops_summary_payload["safety_note"]

    assert ops_summary_preview_response.status_code == 200
    preview_payload = ops_summary_preview_response.json()["data"]
    assert preview_payload["preview_version"] == "internal-ops-summarizer-preview-v1"
    assert preview_payload["baseline"]["generation"]["mode"] == "deterministic_fallback"
    assert preview_payload["ai"]["generation"]["mode"] == "deterministic_fallback"
    assert preview_payload["comparison"]["ai_called"] is False
    assert preview_payload["comparison"]["value_check"] == "pass_provider_id_to_test_llm"
    assert preview_payload["safety"]["wordpress_write_allowed"] is False

    assert ops_summary_value_response.status_code == 200
    value_payload = ops_summary_value_response.json()["data"]
    assert value_payload["value_metrics_version"] == "internal-ops-summary-value-v1"
    assert value_payload["filters"]["scope"] == "runtime_operations"
    assert value_payload["totals"]["analysis_requests"] >= 1
    assert value_payload["totals"]["deterministic_fallbacks"] >= 1
    assert value_payload["value_signal"]["status"] in {
        "not_using_ai",
        "monitor",
        "insufficient_data",
    }

    dispose_engine(database_url)


def test_service_routes_manage_account_site_and_keys(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    account_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_service", "name": "Service Account"},
        headers=build_internal_headers(idempotency_key="svc-account-001"),
    )
    site_response = client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_service",
            "account_id": "acct_service",
            "name": "Service Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="svc-site-001"),
    )
    activate_response = client.post(
        "/internal/service/sites/site_service/activate",
        headers=build_internal_headers(idempotency_key="svc-site-activate-001"),
    )
    issue_key_response = client.post(
        "/internal/service/sites/site_service/keys",
        json={
            "key_id": "key_service_primary",
            "secret": "svc-primary-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve"],
            "label": "primary",
        },
        headers=build_internal_headers(idempotency_key="svc-key-issue-001"),
    )
    list_keys_response = client.get(
        "/internal/service/sites/site_service/keys",
        headers=build_internal_headers(),
    )
    rotate_key_response = client.post(
        "/internal/service/sites/site_service/keys/key_service_primary/rotate",
        json={
            "key_id": "key_service_rotated",
            "secret": "svc-rotated-secret",
            "label": "rotated",
        },
        headers=build_internal_headers(idempotency_key="svc-key-rotate-001"),
    )
    expire_at = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    expire_key_response = client.post(
        "/internal/service/sites/site_service/keys/key_service_rotated/expire",
        json={"expires_at": expire_at},
        headers=build_internal_headers(idempotency_key="svc-key-expire-001"),
    )
    revoke_key_response = client.post(
        "/internal/service/sites/site_service/keys/key_service_rotated/revoke",
        headers=build_internal_headers(idempotency_key="svc-key-revoke-001"),
    )
    suspend_response = client.post(
        "/internal/service/sites/site_service/suspend",
        json={"reason": "manual hold"},
        headers=build_internal_headers(idempotency_key="svc-site-suspend-001"),
    )
    audit_response = client.get(
        "/internal/service/audit-events?site_id=site_service&limit=20",
        headers=build_internal_headers(),
    )
    missing_activate_response = client.post(
        "/internal/service/sites/site_missing/activate",
        headers=build_internal_headers(idempotency_key="svc-site-activate-missing-001"),
    )
    error_audit_response = client.get(
        "/internal/service/audit-events?event_kind=site.activate&outcome=error&limit=5",
        headers=build_internal_headers(),
    )

    assert account_response.status_code == 200
    assert "current_subscription" not in account_response.json()["data"]
    assert site_response.status_code == 200
    assert site_response.json()["data"]["status"] == "provisioning"
    assert activate_response.status_code == 200
    assert activate_response.json()["data"]["status"] == "active"
    assert issue_key_response.status_code == 200
    assert issue_key_response.json()["data"]["secret"] == "svc-primary-secret"
    assert list_keys_response.status_code == 200
    assert len(list_keys_response.json()["data"]["items"]) == 1
    assert list_keys_response.json()["data"]["pagination"] == {
        "limit": 20,
        "offset": 0,
        "total": 1,
        "has_more": False,
        "next_offset": None,
    }
    assert list_keys_response.json()["data"]["sort"] == {
        "created_at": "desc",
        "key_id": "desc",
    }
    assert rotate_key_response.status_code == 200
    assert rotate_key_response.json()["data"]["previous"]["status"] == "revoked"
    assert rotate_key_response.json()["data"]["current"]["key_id"] == "key_service_rotated"
    assert expire_key_response.status_code == 200
    assert expire_key_response.json()["data"]["status"] == "expired"
    assert revoke_key_response.status_code == 200
    assert revoke_key_response.json()["data"]["status"] == "revoked"
    assert suspend_response.status_code == 200
    assert suspend_response.json()["data"]["status"] == "suspended"
    assert suspend_response.json()["data"]["suspension_reason"] == "manual hold"
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["data"]["items"]
    assert {item["event_kind"] for item in audit_items} >= {
        "site.provision",
        "site.activate",
        "site_key.issue",
        "site_key.rotate",
        "site_key.expire",
        "site_key.revoke",
        "site.suspend",
    }
    issue_audit = next(item for item in audit_items if item["event_kind"] == "site_key.issue")
    rotate_audit = next(item for item in audit_items if item["event_kind"] == "site_key.rotate")
    assert issue_audit["payload"]["secret"] == "[redacted]"
    assert rotate_audit["payload"]["current"]["secret"] == "[redacted]"
    assert missing_activate_response.status_code == 404
    assert error_audit_response.status_code == 200
    error_items = error_audit_response.json()["data"]["items"]
    assert any(
        item["payload"]["error_code"] == "service.site_not_found"
        and item["payload"]["request"] == {}
        for item in error_items
    )

    dispose_engine(database_url)


def test_service_routes_account_default_free_binding_is_explicit(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    generic_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_ops_only", "name": "Ops Only Account"},
        headers=build_internal_headers(idempotency_key="svc-account-explicit-001"),
    )
    onboarding_response = client.post(
        "/internal/service/accounts",
        json={
            "account_id": "acct_customer_free",
            "name": "Customer Free Account",
            "bind_default_free": True,
        },
        headers=build_internal_headers(idempotency_key="svc-account-explicit-002"),
    )

    assert generic_response.status_code == 200
    assert "current_subscription" not in generic_response.json()["data"]
    assert onboarding_response.status_code == 200
    onboarding_payload = onboarding_response.json()["data"]
    assert onboarding_payload["current_subscription"]["plan_id"] == "plan_free"
    assert onboarding_payload["current_subscription"]["plan_version_id"] == "plan_free_v1"
    assert onboarding_payload["current_subscription"]["package_alias"] == "Free"

    with get_session(database_url) as session:
        generic_subscription = session.scalar(
            select(AccountSubscription).where(AccountSubscription.account_id == "acct_ops_only")
        )
        free_subscription = session.scalar(
            select(AccountSubscription).where(
                AccountSubscription.account_id == "acct_customer_free"
            )
        )
        free_snapshot = session.scalar(
            select(AccountEntitlementSnapshot).where(
                AccountEntitlementSnapshot.account_id == "acct_customer_free",
                AccountEntitlementSnapshot.status == "active",
            )
        )

    assert generic_subscription is None
    assert free_subscription is not None
    assert free_subscription.plan_id == "plan_free"
    assert free_subscription.plan_version_id == "plan_free_v1"
    assert free_snapshot is not None
    assert free_snapshot.plan_version_id == "plan_free_v1"

    dispose_engine(database_url)


def test_service_site_keys_support_limit_offset_and_desc_sort(tmp_path: Path) -> None:
    _, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_keys_page", "name": "Paged Keys Account"},
        headers=build_internal_headers(idempotency_key="svc-page-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_keys_page",
            "account_id": "acct_keys_page",
            "name": "Paged Keys Site",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-page-site-001"),
    )

    for index in range(3):
        client.post(
            "/internal/service/sites/site_keys_page/keys",
            json={
                "key_id": f"key_page_{index}",
                "secret": f"svc-page-secret-{index}",
                "scopes": ["runtime:read"],
                "label": f"page-{index}",
            },
            headers=build_internal_headers(idempotency_key=f"svc-page-key-{index:03d}"),
        )

    response = client.get(
        "/internal/service/sites/site_keys_page/keys?limit=2&offset=0",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert [item["key_id"] for item in payload["items"]] == [
        "key_page_2",
        "key_page_1",
    ]
    assert payload["pagination"] == {
        "limit": 2,
        "offset": 0,
        "total": 3,
        "has_more": True,
        "next_offset": 2,
    }
    assert payload["sort"] == {"created_at": "desc", "key_id": "desc"}


def test_service_routes_bind_subscription_and_rebuild_billing_snapshot(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_billing", "name": "Billing Account"},
        headers=build_internal_headers(idempotency_key="svc-account-101"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_billing",
            "account_id": "acct_billing",
            "name": "Billing Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="svc-site-101"),
    )
    client.post(
        "/internal/service/sites/site_billing/activate",
        headers=build_internal_headers(idempotency_key="svc-site-activate-101"),
    )
    key_response = client.post(
        "/internal/service/sites/site_billing/keys",
        json={
            "key_id": "key_billing_primary",
            "secret": "billing-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
            "label": "billing-primary",
        },
        headers=build_internal_headers(idempotency_key="svc-key-101"),
    )
    plan_response = client.post(
        "/internal/service/plans",
        json={"plan_id": "plan_pro_topup", "name": "Pro"},
        headers=build_internal_headers(idempotency_key="svc-plan-101"),
    )
    version_response = client.post(
        "/internal/service/plans/plan_pro_topup/versions",
        json={
            "plan_version_id": "plan_pro_topup_v1",
            "version_label": "v1",
            "entitlements": {
                "ability_families": ["workflow"],
                "channels": ["openapi"],
                "execution_kinds": ["text"],
                "execution_tiers": ["cloud"],
                "data_classifications": ["internal"],
            },
            "budgets": {"max_runs_per_period": 10, "max_tokens_per_period": 5000},
            "concurrency": {"max_active_runs": 2},
        },
        headers=build_internal_headers(idempotency_key="svc-plan-version-101"),
    )
    subscription_response = client.post(
        "/internal/service/admin/accounts/acct_billing/subscription",
        json={
            "subscription_id": "sub_pro_topup",
            "account_id": "acct_billing",
            "plan_id": "plan_pro_topup",
            "plan_version_id": "plan_pro_topup_v1",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-subscription-101"),
    )
    topup_response = client.post(
        "/internal/service/subscriptions/sub_pro_topup/topup",
        json={
            "target_period_start_at": subscription_response.json()["data"]["subscription"][
                "current_period_start_at"
            ],
            "target_period_end_at": subscription_response.json()["data"]["subscription"][
                "current_period_end_at"
            ],
            "runs_increment": 10000,
            "tokens_increment": 2000000,
            "cost_increment": 99,
            "reason": "operator_overage_buffer",
            "note": "Customer needs temporary headroom before tier review.",
        },
        headers=build_internal_headers(idempotency_key="svc-subscription-topup-101"),
    )

    assert key_response.status_code == 200
    assert plan_response.status_code == 200
    assert plan_response.json()["data"]["receipt"]["event_kind"] == "plan.upsert"
    assert plan_response.json()["data"]["receipt"]["audit_filters"]["event_kind"] == "plan.upsert"
    assert plan_response.json()["data"]["receipt"]["audit_filters"]["outcome"] == "succeeded"
    assert version_response.status_code == 200
    assert version_response.json()["data"]["receipt"]["event_kind"] == "plan_version.publish"
    assert (
        version_response.json()["data"]["receipt"]["audit_filters"]["event_kind"]
        == "plan_version.publish"
    )
    assert subscription_response.status_code == 200
    assert subscription_response.json()["data"]["receipt"]["event_kind"] == "subscription.upsert"
    assert (
        subscription_response.json()["data"]["receipt"]["audit_filters"]["account_id"]
        == "acct_billing"
    )
    assert topup_response.status_code == 200
    topup_payload = topup_response.json()["data"]
    assert topup_payload["receipt"]["event_kind"] == "subscription.topup"
    assert topup_payload["topup"]["pack_id"] == ""
    assert topup_payload["topup"]["reason"] == "operator_overage_buffer"
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_runs_per_period"] == 10010.0
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_tokens_per_period"] == 2005000.0
    assert topup_payload["entitlement_snapshot"]["budgets"]["max_cost_per_period"] == 99.0
    assert topup_payload["topup_summary"]["current_period_count"] == 1
    assert topup_payload["topup_summary"]["current_period_totals"]["runs"] == 10000.0
    assert topup_payload["topup_summary"]["current_period_totals"]["tokens"] == 2000000.0
    assert topup_payload["topup_summary"]["current_period_totals"]["cost"] == 99.0
    assert topup_payload["billing_snapshot_refresh"]["status"] == "refreshed"
    assert topup_payload["billing_snapshot_refresh"]["site_count"] == 1
    assert topup_payload["billing_snapshot_refresh"]["snapshots"][0]["site_id"] == "site_billing"
    assert topup_payload["billing_snapshot_status"]["status"] == "fresh"
    assert topup_payload["billing_snapshot_status"]["next_action"] is None

    admin_subscription_response = client.get(
        "/internal/service/admin/subscriptions/sub_pro_topup",
        headers=build_internal_headers(),
    )
    assert admin_subscription_response.status_code == 200
    admin_subscription = admin_subscription_response.json()["data"]
    assert admin_subscription["topup_summary"]["count"] == 1
    assert admin_subscription["topup_summary"]["latest"]["pack_id"] == ""
    assert admin_subscription["topup_summary"]["latest"]["reason"] == "operator_overage_buffer"
    assert admin_subscription["topup_summary"]["current_period_totals"]["cost"] == 99.0
    assert admin_subscription["budget_headroom"]["base_budget"]["runs"] == 10.0
    assert admin_subscription["budget_headroom"]["current_period_topup_delta"]["runs"] == 10000.0
    assert admin_subscription["budget_headroom"]["effective_budget"]["runs"] == 10010.0
    assert admin_subscription["billing_snapshot_status"]["status"] == "fresh"
    assert admin_subscription["billing_snapshot_status"]["fresh_site_count"] == 1
    assert admin_subscription["billing_snapshot_status"]["next_action"] is None

    rebuild_subscription_response = client.post(
        "/internal/service/admin/subscriptions/sub_pro_topup/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-subscription-rebuild-101"),
    )
    assert rebuild_subscription_response.status_code == 200
    rebuild_payload = rebuild_subscription_response.json()["data"]
    assert rebuild_payload["billing_snapshot_refresh"]["status"] == "refreshed"
    assert rebuild_payload["billing_snapshot_refresh"]["site_count"] == 1
    assert rebuild_payload["billing_snapshot_status"]["status"] == "fresh"
    assert rebuild_payload["billing_snapshot_status"]["next_action"] is None

    execute_payload = {
        "site_id": "site_billing",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-billing-001",
        "input": {"messages": [{"role": "user", "content": "meter this run"}]},
    }
    body = json.dumps(execute_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_billing",
                key_id="key_billing_primary",
                secret="billing-secret",
                idempotency_key="idem-service-billing-001",
                trace_id="traceservicebilling001000000",
                body=body,
            )
        ),
    )
    usage_response = client.get(
        "/internal/service/sites/site_billing/usage-meter?limit=20",
        headers=build_internal_headers(),
    )
    rebuild_response = client.post(
        "/internal/service/sites/site_billing/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-billing-rebuild-101"),
    )
    list_billing_response = client.get(
        "/internal/service/sites/site_billing/billing-snapshots",
        headers=build_internal_headers(),
    )
    suspend_subscription_response = client.post(
        "/internal/service/admin/accounts/acct_billing/subscription/suspend",
        headers=build_internal_headers(idempotency_key="svc-subscription-suspend-101"),
    )
    cancel_subscription_response = client.post(
        "/internal/service/admin/accounts/acct_billing/subscription/cancel",
        headers=build_internal_headers(idempotency_key="svc-subscription-cancel-101"),
    )
    denied_resolve_response = client.post(
        "/v1/runtime/resolve",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/resolve",
                site_id="site_billing",
                key_id="key_billing_primary",
                secret="billing-secret",
                nonce="svc-billing-deny-nonce-001",
                trace_id="traceservicebillingdeny00100",
                body=body,
            )
        ),
    )
    commercial_decisions_response = client.get(
        "/internal/service/commercial-decisions?site_id=site_billing&limit=10",
        headers=build_internal_headers(),
    )

    assert execute_response.status_code == 200
    assert execute_response.json()["data"]["status"] == "succeeded"
    assert usage_response.status_code == 200
    assert usage_response.json()["data"]["totals"]["runs"] == 1.0
    assert usage_response.json()["data"]["totals"]["provider_calls"] == 1.0
    assert usage_response.json()["data"]["totals"]["tokens_total"] > 0
    assert rebuild_response.status_code == 200
    assert rebuild_response.json()["data"]["totals"]["runs"] == 1.0
    assert (
        rebuild_response.json()["data"]["breakdown"]["ability_families"]["workflow"]["runs"] == 1.0
    )
    assert list_billing_response.status_code == 200
    assert len(list_billing_response.json()["data"]["items"]) == 1
    assert suspend_subscription_response.status_code == 200
    assert suspend_subscription_response.json()["data"]["status"] == "suspended"
    assert (
        suspend_subscription_response.json()["data"]["receipt"]["event_kind"]
        == "subscription.suspend"
    )
    assert (
        suspend_subscription_response.json()["data"]["receipt"]["audit_filters"]["event_kind"]
        == "subscription.suspend"
    )
    assert denied_resolve_response.status_code == 403
    assert denied_resolve_response.json()["error_code"] in {
        "commercial.subscription_inactive",
        "commercial.entitlement_denied",
    }
    assert cancel_subscription_response.status_code == 200
    assert cancel_subscription_response.json()["data"]["status"] == "canceled"
    assert (
        cancel_subscription_response.json()["data"]["receipt"]["event_kind"]
        == "subscription.cancel"
    )
    assert (
        cancel_subscription_response.json()["data"]["receipt"]["audit_filters"]["event_kind"]
        == "subscription.cancel"
    )
    assert commercial_decisions_response.status_code == 200
    decision_items = commercial_decisions_response.json()["data"]["items"]
    assert {item["decision"] for item in decision_items} >= {"allow", "deny"}
    assert {item["request_kind"] for item in decision_items} >= {"execute", "resolve"}
    assert any(item["decision_code"] == "commercial.allowed" for item in decision_items)
    assert any(
        item["decision_code"]
        in {"commercial.subscription_inactive", "commercial.entitlement_denied"}
        for item in decision_items
    )

    dispose_engine(database_url)


def test_service_routes_admin_read_facade(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_admin", "name": "Admin Account"},
        headers=build_internal_headers(idempotency_key="svc-admin-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_primary",
            "account_id": "acct_admin",
            "name": "Admin Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="svc-admin-site-001"),
    )
    client.post(
        "/internal/service/sites/site_primary/activate",
        headers=build_internal_headers(idempotency_key="svc-admin-site-activate-001"),
    )
    client.post(
        "/internal/service/sites/site_primary/site-admin-access",
        json={"email": "admin@example.com"},
        headers=build_internal_headers(idempotency_key="svc-admin-site-admin-access-001"),
    )
    client.post(
        "/internal/service/sites/site_primary/keys",
        json={
            "key_id": "key_admin_primary",
            "secret": "admin-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
            "label": "admin-primary",
        },
        headers=build_internal_headers(idempotency_key="svc-admin-key-001"),
    )
    client.post(
        "/internal/service/plans",
        json={"plan_id": "plan_admin", "name": "Admin Plan"},
        headers=build_internal_headers(idempotency_key="svc-admin-plan-001"),
    )
    client.post(
        "/internal/service/plans/plan_admin/versions",
        json={
            "plan_version_id": "plan_admin_v1",
            "version_label": "v1",
            "entitlements": {
                "ability_families": ["workflow"],
                "channels": ["openapi"],
                "execution_kinds": ["text"],
                "execution_tiers": ["cloud"],
                "data_classifications": ["internal"],
            },
            "budgets": {"max_runs_per_period": 25, "max_tokens_per_period": 12000},
            "concurrency": {"max_active_runs": 3},
        },
        headers=build_internal_headers(idempotency_key="svc-admin-version-001"),
    )
    client.post(
        "/internal/service/admin/accounts/acct_admin/subscription",
        json={
            "subscription_id": "sub_admin",
            "account_id": "acct_admin",
            "plan_id": "plan_admin",
            "plan_version_id": "plan_admin_v1",
            "status": "active",
            "current_period_end_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        },
        headers=build_internal_headers(idempotency_key="svc-admin-subscription-001"),
    )

    execute_payload = {
        "site_id": "site_primary",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-admin-facade-001",
        "input": {"messages": [{"role": "user", "content": "exercise admin overview"}]},
    }
    body = json.dumps(execute_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_primary",
                key_id="key_admin_primary",
                secret="admin-secret",
                idempotency_key="idem-admin-facade-001",
                trace_id="traceadminfacade001000000",
                body=body,
            )
        ),
    )
    assert execute_response.status_code == 200

    client.post(
        "/internal/service/sites/site_primary/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-admin-billing-001"),
    )

    overview_response = client.get(
        "/internal/service/admin/overview",
        headers=build_internal_headers(),
    )
    accounts_response = client.get(
        "/internal/service/admin/accounts",
        headers=build_internal_headers(),
    )
    account_detail_response = client.get(
        "/internal/service/admin/accounts/acct_admin",
        headers=build_internal_headers(),
    )
    sites_response = client.get(
        "/internal/service/admin/sites",
        headers=build_internal_headers(),
    )
    site_detail_response = client.get(
        "/internal/service/admin/sites/site_primary",
        headers=build_internal_headers(),
    )
    subscriptions_response = client.get(
        "/internal/service/admin/subscriptions",
        headers=build_internal_headers(),
    )
    plans_response = client.get(
        "/internal/service/admin/plans",
        headers=build_internal_headers(),
    )
    plan_detail_response = client.get(
        "/internal/service/admin/plans/plan_admin",
        headers=build_internal_headers(),
    )
    subscription_detail_response = client.get(
        "/internal/service/admin/subscriptions/sub_admin",
        headers=build_internal_headers(),
    )
    package_filtered_accounts_response = client.get(
        "/internal/service/admin/accounts?coverage_state=covered&package_kind=tier_package&top_plan_id=plan_admin",
        headers=build_internal_headers(),
    )
    filtered_sites_response = client.get(
        "/internal/service/admin/sites?account_id=acct_admin&subscription_status=active",
        headers=build_internal_headers(),
    )
    filtered_subscriptions_response = client.get(
        "/internal/service/admin/subscriptions?plan_id=plan_admin",
        headers=build_internal_headers(),
    )
    expiring_accounts_response = client.get(
        "/internal/service/admin/accounts",
        params={"expires_before": (datetime.now(UTC) + timedelta(days=30)).isoformat()},
        headers=build_internal_headers(),
    )
    unauthorized_response = client.get("/internal/service/admin/overview")

    assert overview_response.status_code == 200
    overview = overview_response.json()["data"]
    assert overview["counts"]["accounts_total"] == 1
    assert overview["counts"]["site_admins_active"] == 1
    assert overview["counts"]["sites_active"] == 1
    assert overview["counts"]["site_keys_active"] == 1
    assert overview["recent_usage"]["event_count"] >= 1
    assert "runtime_diagnostics" in overview
    assert overview["hosted_model_governance"]["filters"]["recent_minutes"] == 1440
    assert overview["hosted_model_governance"]["alert_summary"]["status"] in {
        "ok",
        "warning",
        "error",
        "inactive",
    }
    assert (
        overview["hosted_model_governance"]["alert_summary"]["boundary"]["direct_wordpress_write"]
        is False
    )
    assert overview["runtime_operator_explanations"]
    assert len(overview["expiring_subscriptions"]["items"]) >= 1
    assert any(
        item["subscription"]["account_id"] == "acct_admin"
        for item in overview["expiring_subscriptions"]["items"]
    )
    assert overview["expiring_subscriptions"]["within_30_days_expires_before"]
    assert overview["attention_subscriptions"] == []

    assert accounts_response.status_code == 200
    accounts = accounts_response.json()["data"]["items"]
    assert len(accounts) == 1
    assert accounts[0]["account"]["account_id"] == "acct_admin"
    assert accounts[0]["site_count"] == 1
    assert accounts[0]["active_subscription_count"] >= 1
    assert accounts[0]["display_package_label"] == "Pro"
    assert accounts[0]["package_kind"] == "tier_package"
    assert accounts[0]["coverage_state"] == "covered"
    assert accounts[0]["primary_subscription_id"] == "sub_admin"
    assert package_filtered_accounts_response.status_code == 200
    assert (
        package_filtered_accounts_response.json()["data"]["filters"]["coverage_state"] == "covered"
    )
    assert (
        package_filtered_accounts_response.json()["data"]["filters"]["package_kind"]
        == "tier_package"
    )
    assert (
        package_filtered_accounts_response.json()["data"]["filters"]["top_plan_id"] == "plan_admin"
    )
    assert len(package_filtered_accounts_response.json()["data"]["items"]) == 1

    assert account_detail_response.status_code == 200
    account_detail = account_detail_response.json()["data"]
    assert len(account_detail["sites"]) == 1
    assert len(account_detail["subscriptions"]) >= 1

    suspend_account_response = client.post(
        "/internal/service/admin/accounts/acct_admin/suspend",
        json={"reason": "billing review"},
        headers=build_internal_headers(idempotency_key="svc-admin-account-suspend-001"),
    )
    assert suspend_account_response.status_code == 200
    assert suspend_account_response.json()["data"]["status"] == "suspended"
    assert (
        suspend_account_response.json()["data"]["metadata"]["account_status_note"]
        == "billing review"
    )
    assert suspend_account_response.json()["data"]["receipt"]["event_kind"] == "account.suspend"

    suspended_account_detail_response = client.get(
        "/internal/service/admin/accounts/acct_admin",
        headers=build_internal_headers(),
    )
    assert suspended_account_detail_response.status_code == 200
    assert suspended_account_detail_response.json()["data"]["account"]["status"] == "suspended"
    assert (
        suspended_account_detail_response.json()["data"]["account"]["metadata"][
            "account_status_note"
        ]
        == "billing review"
    )

    restore_account_response = client.post(
        "/internal/service/admin/accounts/acct_admin/restore",
        headers=build_internal_headers(idempotency_key="svc-admin-account-restore-001"),
    )
    assert restore_account_response.status_code == 200
    assert restore_account_response.json()["data"]["status"] == "active"
    assert restore_account_response.json()["data"]["receipt"]["event_kind"] == "account.restore"

    assert sites_response.status_code == 200
    sites = sites_response.json()["data"]["items"]
    assert len(sites) == 1
    assert sites[0]["site"]["site_id"] == "site_primary"
    assert sites[0]["active_key_count"] == 1
    assert sites[0]["coverage"]["covered_by_subscription_id"]
    assert sites[0]["coverage"]["subscription_status"] == "active"
    assert filtered_sites_response.status_code == 200
    assert filtered_sites_response.json()["data"]["filters"]["account_id"] == "acct_admin"
    assert filtered_sites_response.json()["data"]["filters"]["subscription_status"] == "active"
    assert len(filtered_sites_response.json()["data"]["items"]) == 1

    assert site_detail_response.status_code == 200
    site_detail = site_detail_response.json()["data"]
    assert site_detail["site"]["site_id"] == "site_primary"
    assert len(site_detail["site_keys"]) == 1
    assert site_detail["subscription"]["account_id"] == "acct_admin"
    assert site_detail["usage_meter"]["totals"]["runs"] >= 1
    assert site_detail["billing_reconciliation"]["site_id"] == "site_primary"
    assert site_detail["commercial_policy"]["policy"]["subscription"]["grace_period_days"] == 0
    assert "runtime_diagnostics" in site_detail
    assert site_detail["related_surfaces"]["account_href"] == "/admin/accounts/acct_admin"
    assert "/admin/subscriptions/" in site_detail["related_surfaces"]["subscription_href"]
    assert site_detail["commercial_follow_up"]["next_operator_follow_up"]
    assert site_detail["runtime_operator_explanations"]

    assert subscriptions_response.status_code == 200
    subscriptions = subscriptions_response.json()["data"]["items"]
    assert len(subscriptions) >= 1
    assert any(item["subscription"]["subscription_id"] == "sub_admin" for item in subscriptions)
    assert all(
        item["account"]["account_id"] == "acct_admin"
        for item in subscriptions
        if item.get("account")
    )
    assert any(
        any(site["site_id"] == "site_primary" for site in item.get("covered_sites") or [])
        for item in subscriptions
    )
    subscription_summary = next(
        item for item in subscriptions if item["subscription"]["subscription_id"] == "sub_admin"
    )
    assert subscription_summary["billing_snapshot_status"]["status"] == "fresh"
    assert subscription_summary["billing_snapshot_status"]["fresh_site_count"] == 1
    assert subscription_summary["billing_snapshot_status"]["stale_site_count"] == 0
    assert subscription_summary["billing_snapshot_status"]["missing_site_count"] == 0
    assert plans_response.status_code == 200
    plans = plans_response.json()["data"]["items"]
    tier_templates = plans_response.json()["data"]["tier_templates"]
    assert len(plans) >= 1
    assert [item["tier_id"] for item in tier_templates] == ["free", "pro", "agency"]
    assert tier_templates[0]["package_alias"] == "Free"
    assert tier_templates[1]["monthly_included_points"] == 0
    assert tier_templates[2]["concurrency_template"]["max_active_runs"] == 0
    assert tier_templates[0]["canonical_shell"]["entitlements"]["execution_tiers"] == ["cloud"]
    assert tier_templates[1]["canonical_shell"]["budgets"]["max_runs_per_period"] == 0
    assert tier_templates[2]["canonical_shell"]["metadata"]["max_batch_items"] == 0
    admin_plan_summary = next(item for item in plans if item["plan"]["plan_id"] == "plan_admin")
    assert admin_plan_summary["tier_summary"]["tier_id"] == "pro"
    assert admin_plan_summary["tier_summary"]["label"] == "Pro"
    assert admin_plan_summary["tier_summary"]["package_alias"] == "Pro"
    assert admin_plan_summary["tier_summary"]["monthly_included_points"] == 0
    assert admin_plan_summary["tier_summary"]["site_limit"] == 0
    assert admin_plan_summary["tier_summary"]["max_batch_items"] == 0
    assert admin_plan_summary["tier_summary"]["automation_enabled"] is True
    assert admin_plan_summary["tier_summary"]["api_enabled"] is True
    assert admin_plan_summary["tier_summary"]["openclaw_enabled"] is True
    assert (
        "internal development is temporarily unlimited"
        in admin_plan_summary["tier_summary"]["package_operator_note"].lower()
    )
    assert admin_plan_summary["latest_version"]["plan_version_id"] == "plan_admin_v1"
    assert admin_plan_summary["published_version_count"] == 1
    assert plan_detail_response.status_code == 200
    plan_detail = plan_detail_response.json()["data"]
    assert plan_detail["plan"]["plan_id"] == "plan_admin"
    assert plan_detail["tier_summary"]["tier_id"] == "pro"
    assert plan_detail["tier_summary"]["package_alias"] == "Pro"
    assert plan_detail["tier_summary"]["monthly_included_points"] == 0
    assert plan_detail["tier_summary"]["site_limit"] == 0
    assert plan_detail["tier_summary"]["max_batch_items"] == 0
    assert plan_detail["tier_summary"]["automation_enabled"] is True
    assert plan_detail["tier_summary"]["api_enabled"] is True
    assert plan_detail["tier_summary"]["openclaw_enabled"] is True
    assert plan_detail["tier_summary"]["concurrency_template"]["max_active_runs"] == 0
    assert plan_detail["latest_version"]["plan_version_id"] == "plan_admin_v1"
    assert plan_detail["package_fit_cues"]
    cue_codes = {item["code"] for item in plan_detail["package_fit_cues"]}
    assert "package_fit.cost_ceiling_missing" in cue_codes
    assert subscription_detail_response.status_code == 200
    subscription_detail = subscription_detail_response.json()["data"]
    assert subscription_detail["subscription"]["subscription_id"] == "sub_admin"
    assert subscription_detail["account"]["account_id"] == "acct_admin"
    assert subscription_detail["covered_sites"][0]["site_id"] == "site_primary"
    assert subscription_detail["plan"]["plan_id"] == "plan_admin"
    assert subscription_detail["plan_version"]["plan_version_id"] == "plan_admin_v1"
    assert subscription_detail["commercial_policy"]["subscription"]["grace_period_days"] == 0
    assert "runs" in subscription_detail["budget_state"]
    assert "tokens" in subscription_detail["budget_state"]
    assert "cost" in subscription_detail["budget_state"]
    assert subscription_detail["subscription_grace"]["subscription_status"] == "active"
    assert subscription_detail["usage_totals"]["runs"] >= 1
    assert subscription_detail["related_surfaces"]["site_href"] in {"", "/admin/sites/site_primary"}
    assert subscription_detail["related_surfaces"]["account_href"] == "/admin/accounts/acct_admin"
    assert subscription_detail["commercial_follow_up"]["next_operator_follow_up"]
    assert filtered_subscriptions_response.status_code == 200
    assert filtered_subscriptions_response.json()["data"]["filters"]["plan_id"] == "plan_admin"
    assert len(filtered_subscriptions_response.json()["data"]["items"]) == 1
    assert (
        filtered_subscriptions_response.json()["data"]["items"][0]["billing_snapshot_status"][
            "status"
        ]
        == "fresh"
    )
    assert expiring_accounts_response.status_code == 200
    assert len(expiring_accounts_response.json()["data"]["items"]) == 1

    assert unauthorized_response.status_code == 401
    assert unauthorized_response.json()["error_code"] == "auth.internal_token_required"

    dispose_engine(database_url)


def test_service_routes_plan_tier_fallback_and_package_fit_cues(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    create_plan_responses = [
        client.post(
            "/internal/service/plans",
            json={
                "plan_id": "free_ops",
                "name": "Free Ops",
                "metadata": {"tier_id": "free"},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-plan-free-001"),
        ),
        client.post(
            "/internal/service/plans",
            json={"plan_id": "plan_version_tier", "name": "Version Tier Plan"},
            headers=build_internal_headers(idempotency_key="svc-tier-plan-version-001"),
        ),
        client.post(
            "/internal/service/plans",
            json={"plan_id": "agency_ops", "name": "Agency Operations"},
            headers=build_internal_headers(idempotency_key="svc-tier-plan-name-001"),
        ),
        client.post(
            "/internal/service/plans",
            json={"plan_id": "general_ops", "name": "General Operations"},
            headers=build_internal_headers(idempotency_key="svc-tier-plan-default-001"),
        ),
    ]
    assert all(response.status_code == 200 for response in create_plan_responses)

    create_version_responses = [
        client.post(
            "/internal/service/plans/free_ops/versions",
            json={
                "plan_version_id": "free_ops_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 100,
                    "max_tokens_per_period": 50_000,
                },
                "concurrency": {"max_active_runs": 1},
                "metadata": {"tier_id": "agency"},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-free-001"),
        ),
        client.post(
            "/internal/service/plans/plan_version_tier/versions",
            json={
                "plan_version_id": "plan_version_tier_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 8_000,
                    "max_tokens_per_period": 6_000_000,
                    "max_cost_per_period": 220,
                },
                "concurrency": {"max_active_runs": 12},
                "metadata": {"tier_id": "agency"},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-agency-001"),
        ),
        client.post(
            "/internal/service/plans/agency_ops/versions",
            json={
                "plan_version_id": "agency_ops_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 12_000,
                    "max_tokens_per_period": 9_000_000,
                    "max_cost_per_period": 260,
                },
                "concurrency": {"max_active_runs": 18},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-name-001"),
        ),
        client.post(
            "/internal/service/plans/general_ops/versions",
            json={
                "plan_version_id": "general_ops_v1",
                "version_label": "v1",
                "budgets": {
                    "max_runs_per_period": 10_000,
                    "max_tokens_per_period": 2_000_000,
                    "max_cost_per_period": 99,
                },
                "concurrency": {"max_active_runs": 2},
            },
            headers=build_internal_headers(idempotency_key="svc-tier-version-default-001"),
        ),
    ]
    assert all(response.status_code == 200 for response in create_version_responses)

    plans_response = client.get(
        "/internal/service/admin/plans",
        headers=build_internal_headers(),
    )
    free_detail_response = client.get(
        "/internal/service/admin/plans/free_ops",
        headers=build_internal_headers(),
    )
    version_tier_detail_response = client.get(
        "/internal/service/admin/plans/plan_version_tier",
        headers=build_internal_headers(),
    )
    name_tier_detail_response = client.get(
        "/internal/service/admin/plans/agency_ops",
        headers=build_internal_headers(),
    )
    default_tier_detail_response = client.get(
        "/internal/service/admin/plans/general_ops",
        headers=build_internal_headers(),
    )

    assert plans_response.status_code == 200
    plans = {item["plan"]["plan_id"]: item for item in plans_response.json()["data"]["items"]}
    assert plans["free_ops"]["tier_summary"]["tier_id"] == "free"
    assert plans["free_ops"]["tier_summary"]["package_alias"] == "Free"
    assert plans["free_ops"]["tier_summary"]["monthly_included_points"] == 0
    assert plans["free_ops"]["tier_summary"]["max_batch_items"] == 0
    assert plans["free_ops"]["tier_summary"]["automation_enabled"] is True
    assert plans["free_ops"]["tier_summary"]["api_enabled"] is True
    assert plans["free_ops"]["tier_summary"]["openclaw_enabled"] is True
    assert plans["plan_version_tier"]["tier_summary"]["tier_id"] == "agency"
    assert plans["plan_version_tier"]["tier_summary"]["package_alias"] == "Agency"
    assert plans["plan_version_tier"]["tier_summary"]["monthly_included_points"] == 0
    assert plans["plan_version_tier"]["tier_summary"]["max_batch_items"] == 0
    assert plans["plan_version_tier"]["tier_summary"]["openclaw_enabled"] is True
    assert plans["agency_ops"]["tier_summary"]["tier_id"] == "agency"
    assert plans["general_ops"]["tier_summary"]["tier_id"] == "pro"

    assert free_detail_response.status_code == 200
    free_detail = free_detail_response.json()["data"]
    assert free_detail["tier_summary"]["tier_id"] == "free"
    assert free_detail["tier_summary"]["package_alias"] == "Free"
    assert free_detail["tier_summary"]["monthly_included_points"] == 0
    free_cue_codes = {item["code"] for item in free_detail["package_fit_cues"]}
    assert "package_fit.cost_ceiling_missing" in free_cue_codes

    assert version_tier_detail_response.status_code == 200
    version_tier_detail = version_tier_detail_response.json()["data"]
    assert version_tier_detail["tier_summary"]["tier_id"] == "agency"
    assert version_tier_detail["tier_summary"]["package_alias"] == "Agency"
    assert version_tier_detail["tier_summary"]["openclaw_enabled"] is True

    assert name_tier_detail_response.status_code == 200
    name_tier_detail = name_tier_detail_response.json()["data"]
    assert name_tier_detail["tier_summary"]["tier_id"] == "agency"

    assert default_tier_detail_response.status_code == 200
    default_tier_detail = default_tier_detail_response.json()["data"]
    assert default_tier_detail["tier_summary"]["tier_id"] == "pro"
    assert default_tier_detail["tier_summary"]["package_alias"] == "Pro"
    assert default_tier_detail["tier_summary"]["automation_enabled"] is True
    assert default_tier_detail["tier_summary"]["api_enabled"] is True
    assert default_tier_detail["tier_summary"]["openclaw_enabled"] is True
    assert default_tier_detail["package_fit_cues"][0]["code"] == "package_fit.within_band"

    dispose_engine(database_url)


def test_service_routes_removed_platform_admin_identity_routes(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)

    response = client.post(
        "/internal/service/platform-admin-identities",
        json={
            "admin_ref": "platform:founder",
            "role": "platform_admin",
            "email": "founder@example.com",
            "provider": "manual",
        },
        headers=build_internal_headers(idempotency_key="svc-platform-admin-001"),
    )

    assert response.status_code == 404

    delete_response = client.delete(
        "/internal/service/platform-admin-identities/platform:founder",
        headers=build_internal_headers(idempotency_key="svc-platform-admin-delete-001"),
    )

    assert delete_response.status_code == 404

    missing_response = client.delete(
        "/internal/service/platform-admin-identities/platform:founder",
        headers=build_internal_headers(idempotency_key="svc-platform-admin-delete-002"),
    )

    assert missing_response.status_code == 404

    dispose_engine(database_url)


def test_admin_account_quota_summary_reports_ai_credits_and_resource_limits(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_quota",
        scopes=["runtime:execute", "runtime:read", "stats:read"],
        budgets={
            "max_ai_credits_per_period": 20,
            "max_runs_per_period": 10,
            "max_tokens_per_period": 5000,
        },
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == "acct_site_quota")
            .order_by(AccountSubscription.created_at.desc())
        )
        assert subscription is not None
        events = [
            UsageMeterEvent(
                account_id="acct_site_quota",
                site_id="site_quota",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run-quota-1",
                provider_call_id=None,
                event_kind="runtime.run",
                meter_key="runs",
                quantity=2,
                ability_family="text",
                channel="api",
                execution_kind="text",
                execution_tier="cloud",
                data_classification="internal",
                currency=None,
                dedupe_key="quota-summary-runs",
                payload_json={},
                created_at=now,
            ),
            UsageMeterEvent(
                account_id="acct_site_quota",
                site_id="site_quota",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run-quota-1",
                provider_call_id=None,
                event_kind="runtime.tokens",
                meter_key="tokens_total",
                quantity=1500,
                ability_family="text",
                channel="api",
                execution_kind="text",
                execution_tier="cloud",
                data_classification="internal",
                currency=None,
                dedupe_key="quota-summary-tokens",
                payload_json={},
                created_at=now,
            ),
            UsageMeterEvent(
                account_id="acct_site_quota",
                site_id="site_quota",
                subscription_id=subscription.subscription_id,
                plan_version_id=subscription.plan_version_id,
                run_id="run-quota-1",
                provider_call_id=None,
                event_kind="provider.call",
                meter_key="provider_calls",
                quantity=1,
                ability_family="tool",
                channel="api",
                execution_kind="web_search",
                execution_tier="cloud",
                data_classification="internal",
                currency=None,
                dedupe_key="quota-summary-search",
                payload_json={},
                created_at=now,
            ),
        ]
        session.add_all(events)
        session.commit()

    response = client.get(
        "/internal/service/admin/accounts/acct_site_quota/quota-summary",
        headers=build_internal_headers(),
    )
    unauthenticated = client.get(
        "/internal/service/admin/accounts/acct_site_quota/quota-summary",
    )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_id"] == "acct_site_quota"
    assert data["credit"]["key"] == "ai_credits"
    assert data["credit"]["used"] == 8.5
    assert data["credit"]["limit"] == 20.0
    assert data["credit"]["remaining"] == 11.5
    assert data["credit"]["status"] == "ok"
    assert data["credit"]["estimated"] is True
    assert data["credit"]["rate_version"] == "ai-credit-estimate-v1"
    assert {item["key"]: item["credits"] for item in data["breakdown"]} == {
        "runs": 2.0,
        "tokens_total": 1.5,
        "web_search": 5.0,
    }
    resource_limits = {item["key"]: item for item in data["resource_limits"]}
    assert resource_limits["bound_sites"]["used"] == 1.0
    assert resource_limits["active_api_key_sites"]["used"] == 1.0
    assert resource_limits["vector_documents"]["unit"] == "document"
    assert data["coverage"]["active_key_site_count"] == 1


def test_service_routes_inspect_commercial_policy_and_reconciliation(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)

    client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_policy", "name": "Policy Account"},
        headers=build_internal_headers(idempotency_key="svc-policy-account-001"),
    )
    client.post(
        "/internal/service/sites",
        json={
            "site_id": "site_policy",
            "account_id": "acct_policy",
            "name": "Policy Site",
            "status": "provisioning",
        },
        headers=build_internal_headers(idempotency_key="svc-policy-site-001"),
    )
    client.post(
        "/internal/service/sites/site_policy/activate",
        headers=build_internal_headers(idempotency_key="svc-policy-site-activate-001"),
    )
    client.post(
        "/internal/service/sites/site_policy/keys",
        json={
            "key_id": "key_policy_primary",
            "secret": "policy-secret",
            "scopes": ["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
            "label": "policy-primary",
        },
        headers=build_internal_headers(idempotency_key="svc-policy-key-001"),
    )
    client.post(
        "/internal/service/plans",
        json={"plan_id": "plan_policy", "name": "Policy"},
        headers=build_internal_headers(idempotency_key="svc-policy-plan-001"),
    )
    version_response = client.post(
        "/internal/service/plans/plan_policy/versions",
        json={
            "plan_version_id": "plan_policy_v1",
            "version_label": "v1",
            "entitlements": {
                "ability_families": ["workflow", "automation"],
                "channels": ["openapi"],
                "execution_kinds": ["text"],
                "execution_tiers": ["cloud"],
                "data_classifications": ["internal"],
            },
            "budgets": {"max_runs_per_period": 1},
            "concurrency": {"max_active_runs": 2},
            "policy": {
                "subscription": {
                    "grace_period_days": 2,
                    "downgrade_policy": {
                        "retry_max": 0,
                        "task_backend": {
                            "enabled": False,
                            "mode": "inline",
                            "callback_mode": "polling_only",
                        },
                    },
                },
                "budgets": {
                    "runs": {
                        "grace_requests": 1,
                        "downgrade_policy": {
                            "retry_max": 0,
                            "task_backend": {
                                "enabled": False,
                                "mode": "inline",
                                "callback_mode": "polling_only",
                            },
                        },
                    }
                },
                "reconciliation": {
                    "tolerance": {
                        "runs": 0,
                        "provider_calls": 0,
                        "tokens_total": 0,
                        "cost": 0,
                    }
                },
            },
        },
        headers=build_internal_headers(idempotency_key="svc-policy-plan-version-001"),
    )
    bind_response = client.post(
        "/internal/service/admin/accounts/acct_policy/subscription",
        json={
            "subscription_id": "sub_policy",
            "account_id": "acct_policy",
            "plan_id": "plan_policy",
            "plan_version_id": "plan_policy_v1",
            "status": "active",
        },
        headers=build_internal_headers(idempotency_key="svc-policy-subscription-001"),
    )

    assert version_response.status_code == 200
    assert version_response.json()["data"]["policy"]["budgets"]["runs"]["grace_requests"] == 1
    assert bind_response.status_code == 200

    execute_payload = {
        "site_id": "site_policy",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-policy-run-001",
        "input": {"messages": [{"role": "user", "content": "policy run"}]},
    }
    execute_body = json.dumps(execute_payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=execute_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_policy",
                key_id="key_policy_primary",
                secret="policy-secret",
                idempotency_key="idem-policy-run-001",
                trace_id="tracepolicyrun0010000000000",
                body=execute_body,
            )
        ),
    )
    policy_response = client.get(
        "/internal/service/sites/site_policy/commercial-policy",
        headers=build_internal_headers(),
    )
    reconciliation_before_response = client.get(
        "/internal/service/sites/site_policy/billing-snapshots/reconciliation",
        headers=build_internal_headers(),
    )
    rebuild_response = client.post(
        "/internal/service/sites/site_policy/billing-snapshots/rebuild",
        headers=build_internal_headers(idempotency_key="svc-policy-rebuild-001"),
    )

    assert execute_response.status_code == 200
    assert policy_response.status_code == 200
    assert policy_response.json()["data"]["policy"]["budgets"]["runs"]["grace_requests"] == 1
    assert policy_response.json()["data"]["budget_state"]["runs"]["limit"] == 1.0
    assert reconciliation_before_response.status_code == 200
    assert "snapshot_present" in reconciliation_before_response.json()["data"]["reconciliation"]
    assert rebuild_response.status_code == 200

    with get_session(database_url) as session:
        snapshot = session.scalar(
            select(BillingSnapshot)
            .where(BillingSnapshot.site_id == "site_policy")
            .order_by(BillingSnapshot.generated_at.desc())
        )
        assert snapshot is not None
        snapshot.totals_json = {
            **(snapshot.totals_json or {}),
            "runs": 0.0,
        }
        session.commit()

    reconciliation_after_response = client.get(
        "/internal/service/sites/site_policy/billing-snapshots/reconciliation",
        headers=build_internal_headers(),
    )

    assert reconciliation_after_response.status_code == 200
    mismatch = reconciliation_after_response.json()["data"]["reconciliation"]
    assert mismatch["snapshot_present"] is True
    assert mismatch["in_sync"] is False
    assert mismatch["recommended_action"] == "rebuild_snapshot"
    assert mismatch["mismatches"]["runs"]["delta"] == 1.0

    dispose_engine(database_url)


def test_service_routes_cleanup_retention_and_record_audit(tmp_path: Path) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_cleanup",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    payload = {
        "site_id": "site_cleanup",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-cleanup-001",
        "retention_ttl": 60,
        "input": {"messages": [{"role": "user", "content": "expire this result"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_cleanup",
                idempotency_key="idem-cleanup-001",
                trace_id="tracecleanup0010000000000000000",
                body=body,
            )
        ),
    )
    assert execute_response.status_code == 200
    run_id = execute_response.json()["data"]["run_id"]

    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.completed_at = datetime.now(UTC) - timedelta(hours=2)
        run.retention_expires_at = datetime.now(UTC) - timedelta(minutes=10)
        session.commit()

    cleanup_response = client.post(
        "/internal/service/runtime/retention/cleanup",
        headers=build_internal_headers(idempotency_key="svc-retention-cleanup-001"),
    )
    assert cleanup_response.status_code == 200
    assert cleanup_response.json()["data"]["purged_runs"] == 1

    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        assert run.result_json is None

    audit_response = client.get(
        "/internal/service/audit-events?event_kind=runtime.retention_cleanup&limit=5",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200
    assert audit_response.json()["data"]["items"][0]["payload"]["purged_runs"] == 1

    dispose_engine(database_url)


def test_service_routes_expose_ops_cadence_summary(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "retention_cleanup_interval_seconds": 60,
            "plugin_observability_cleanup_interval_seconds": 60,
            "usage_rollup_interval_seconds": 60,
            "router_diagnostics_interval_seconds": 60,
            "latency_probe_interval_seconds": 60,
            "alert_provider_degradation_interval_seconds": 60,
            "hosted_model_governance_interval_seconds": 60,
            "provider_health_scan_interval_seconds": 60,
        },
    )

    service = CommercialService(database_url)
    now = datetime(2026, 4, 12, 12, 0, tzinfo=UTC)
    audit_context = ServiceAuditContext(
        trace_id="",
        idempotency_key="",
        method="POST",
        path="/internal/workers/test",
        actor_kind="system_worker",
        actor_ref="ops_cadence_test",
    )
    service.record_service_audit_event(
        audit_context=audit_context,
        event_kind="runtime.retention_cleanup.cadence",
        outcome="succeeded",
        scope_kind="ops_cadence",
        scope_id="retention_cleanup",
        payload_json={"purged_runs": 1},
    )
    run_due_tasks(_runtime_service_settings(database_url), now=now + timedelta(seconds=1))
    response = client.get(
        "/internal/service/ops/cadence",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["totals"]["tasks_total"] == 9
    assert any(item["task_id"] == "retention_cleanup" for item in payload["items"])
    assert any(item["task_id"] == "hosted_model_governance" for item in payload["items"])
    retention_item = next(
        item for item in payload["items"] if item["task_id"] == "retention_cleanup"
    )
    assert retention_item["last_run_at"] != ""
    assert retention_item["freshness"] in {"fresh", "attention"}

    dispose_engine(database_url)


def test_service_routes_expose_observability_summary(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "worker_heartbeat_interval_seconds": 60,
            "provider_health_scan_interval_seconds": 60,
        },
    )
    settings = _runtime_service_settings(database_url)
    now = datetime(2026, 4, 12, 12, 0, tzinfo=UTC)
    run_due_tasks(settings, now=now)
    CommercialService(database_url, settings=settings).record_service_audit_event(
        audit_context=ServiceAuditContext(
            trace_id="",
            idempotency_key="",
            method="POST",
            path="/internal/workers/runtime_queue/heartbeat",
            actor_kind="system_worker",
            actor_ref="runtime_queue",
        ),
        event_kind="worker.heartbeat",
        outcome="succeeded",
        scope_kind="worker",
        scope_id="runtime_queue",
        payload_json={
            "worker_id": "runtime_queue",
            "status": "idle",
            "recorded_at": now.isoformat().replace("+00:00", "Z"),
        },
    )

    response = client.get(
        "/internal/service/observability/summary?recent_minutes=60&backlog_limit=10",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["ready"]["status"] == "error"
    assert payload["tracing"]["service_name"] == "magick-ai-cloud"
    assert isinstance(payload["tracing"]["trace_sink_configured"], bool)
    assert payload["feature_flags"]["summary"]["flags_total"] >= 1
    assert payload["feature_flags"]["summary"]["overridden_total"] == 0
    assert any(
        item["key"] == "admin.commercial_ops.enabled" for item in payload["feature_flags"]["items"]
    )
    assert payload["workers"]["totals"]["workers_total"] == 3
    assert any(item["worker_id"] == "runtime_queue" for item in payload["workers"]["items"])
    assert payload["cadence"]["totals"]["tasks_total"] == 9
    assert "status_counts" in payload["providers"]
    assert "summary" in payload["runtime"]
    assert "backlog" in payload["runtime"]

    dispose_engine(database_url)


def test_service_routes_observability_summary_marks_trace_sink_configured_when_present(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "otel_exporter_otlp_endpoint": "http://host.docker.internal:4318/v1/traces",
            "otel_trace_sink_otlp_endpoint": "host.docker.internal:4318",
            "otel_trace_query_url": "http://mini.example:16686",
        },
    )

    response = client.get(
        "/internal/service/observability/summary",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["tracing"]["otlp_configured"] is True
    assert payload["tracing"]["trace_sink_configured"] is True
    assert payload["tracing"]["otlp_endpoint"] == "http://host.docker.internal:4318/v1/traces"
    assert payload["tracing"]["trace_sink_otlp_endpoint"] == "host.docker.internal:4318"
    assert payload["tracing"]["trace_sink_query_url"] == "http://mini.example:16686"

    dispose_engine(database_url)


def test_service_routes_observability_summary_surfaces_feature_flag_overrides(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "feature_flags_json": (
                '{"portal.billing.readonly.enabled": false,'
                ' "runtime.experimental_probe.enabled": true}'
            ),
        },
    )

    response = client.get(
        "/internal/service/observability/summary",
        headers=build_internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["feature_flags"]["parse_error"] == ""
    assert payload["feature_flags"]["summary"]["overridden_total"] == 2
    assert any(
        item["key"] == "portal.billing.readonly.enabled"
        and item["enabled"] is False
        and item["source"] == "env_override"
        for item in payload["feature_flags"]["items"]
    )
    assert any(
        item["key"] == "runtime.experimental_probe.enabled"
        and item["enabled"] is True
        and item["source"] == "env_override"
        for item in payload["feature_flags"]["items"]
    )

    dispose_engine(database_url)


def test_service_routes_runtime_diagnostics_summaries_and_abuse_guard(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "public_post_rate_limit_window_seconds": 600,
            "public_post_max_requests_per_window": 10,
            "public_post_max_requests_per_key_window": 10,
            "public_post_max_requests_per_ip_window": 10,
            "public_guard_max_reject_events_per_site_window": 3,
            "internal_post_rate_limit_window_seconds": 600,
            "internal_post_max_requests_per_window": 10,
            "internal_post_max_requests_per_ip_window": 10,
        },
    )
    seed_site_auth(
        database_url,
        site_id="site_diag",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    account_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_diag", "name": "Diagnostics Account"},
        headers=build_internal_headers(idempotency_key="svc-diag-account-001"),
    )
    internal_replay_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_diag_replay", "name": "Diagnostics Account Replay"},
        headers=build_internal_headers(idempotency_key="svc-diag-account-001"),
    )
    missing_activate_response = client.post(
        "/internal/service/sites/site_missing/activate",
        headers=build_internal_headers(idempotency_key="svc-diag-activate-missing-001"),
    )

    CommercialService(
        database_url,
        settings=_runtime_service_settings(database_url),
    ).update_site_runtime_callbacks(
        site_id="site_diag",
        terminal_callback={
            "enabled": True,
            "callback_url": "https://example.com/diag",
            "key_id": "runtime_callback_key",
            "secret": "runtime-callback-secret-for-tests-32b",
            "callback_id": "runtime_terminal",
        },
    )

    callback_payload = {
        "site_id": "site_diag",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-diag-callback-001",
        "retention_ttl": 60,
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "terminal_callback_required",
            "polling_interval_sec": 60,
        },
        "input": {"messages": [{"role": "user", "content": "diag callback"}]},
    }
    callback_body = json.dumps(callback_payload).encode("utf-8")
    callback_response = client.post(
        "/v1/runtime/execute",
        content=callback_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-callback-001",
                trace_id="tracediagcallback001000000000",
                body=callback_body,
            )
        ),
    )
    callback_replay_response = client.post(
        "/v1/runtime/execute",
        content=callback_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-callback-001",
                trace_id="tracediagcallback001000000000",
                body=callback_body,
            )
        ),
    )
    queued_payload = {
        "site_id": "site_diag",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input": {"messages": [{"role": "user", "content": "diag queue"}]},
    }
    queued_body = json.dumps({**queued_payload, "idempotency_key": "idem-diag-queued-001"}).encode(
        "utf-8"
    )
    running_body = json.dumps(
        {**queued_payload, "idempotency_key": "idem-diag-running-001"}
    ).encode("utf-8")
    queued_response = client.post(
        "/v1/runtime/execute",
        content=queued_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-queued-001",
                trace_id="tracediagqueued0010000000000",
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
                site_id="site_diag",
                idempotency_key="idem-diag-running-001",
                trace_id="tracediagrunning001000000000",
                body=running_body,
            )
        ),
    )
    dispatching_payload = {
        **callback_payload,
        "idempotency_key": "idem-diag-dispatching-001",
    }
    overdue_payload = {
        **callback_payload,
        "idempotency_key": "idem-diag-overdue-001",
    }
    dispatching_body = json.dumps(dispatching_payload).encode("utf-8")
    overdue_body = json.dumps(overdue_payload).encode("utf-8")
    dispatching_response = client.post(
        "/v1/runtime/execute",
        content=dispatching_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-dispatching-001",
                trace_id="tracediagdispatch00100000000",
                body=dispatching_body,
            )
        ),
    )
    overdue_response = client.post(
        "/v1/runtime/execute",
        content=overdue_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_diag",
                idempotency_key="idem-diag-overdue-001",
                trace_id="tracediagoverdue001000000000",
                body=overdue_body,
            )
        ),
    )

    assert account_response.status_code == 200
    assert internal_replay_response.status_code == 409
    assert missing_activate_response.status_code == 404
    assert callback_response.status_code == 200
    assert callback_replay_response.status_code == 409
    assert queued_response.status_code == 200
    assert running_response.status_code == 200
    assert dispatching_response.status_code == 200
    assert overdue_response.status_code == 200

    callback_run_id = callback_response.json()["data"]["run_id"]
    queued_run_id = queued_response.json()["data"]["run_id"]
    running_run_id = running_response.json()["data"]["run_id"]
    dispatching_run_id = dispatching_response.json()["data"]["run_id"]
    overdue_run_id = overdue_response.json()["data"]["run_id"]

    with get_session(database_url) as session:
        callback_run = session.get(RunRecord, callback_run_id)
        queued_run = session.get(RunRecord, queued_run_id)
        running_run = session.get(RunRecord, running_run_id)
        dispatching_run = session.get(RunRecord, dispatching_run_id)
        overdue_run = session.get(RunRecord, overdue_run_id)
        assert callback_run is not None
        assert queued_run is not None
        assert running_run is not None
        assert dispatching_run is not None
        assert overdue_run is not None

        callback_run.callback_status = "failed"
        callback_run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=15)
        callback_run.callback_last_error_code = "runtime.callback_delivery_failed"
        callback_run.retention_expires_at = datetime.now(UTC) - timedelta(minutes=5)

        queued_run.status = "queued"
        queued_run.started_at = datetime.now(UTC) - timedelta(minutes=11)
        queued_run.processing_started_at = None
        queued_run.finished_at = None

        dispatching_run.callback_status = "dispatching"
        dispatching_run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=6)

        running_run.status = "running"
        running_run.processing_started_at = datetime.now(UTC) - timedelta(minutes=7)
        running_run.cancel_requested_at = datetime.now(UTC) - timedelta(minutes=7)

        overdue_run.callback_status = "pending"
        overdue_run.callback_next_attempt_at = datetime.now(UTC) - timedelta(minutes=12)

        for index in range(12):
            session.add(
                ReplayReceipt(
                    scope_kind=REPLAY_SCOPE_PUBLIC_POST_SITE,
                    scope_id="site_diag",
                    replay_key=f"manual-burst-{index}",
                    method="POST",
                    path="/v1/runtime/execute",
                    trace_id=f"manualburst{index:02d}",
                    created_at=datetime.now(UTC) - timedelta(minutes=2),
                    expires_at=datetime.now(UTC) + timedelta(minutes=8),
                )
            )

        for index in range(4):
            session.add(
                RuntimeGuardEvent(
                    auth_surface="public_runtime",
                    scope_kind=REPLAY_SCOPE_PUBLIC_POST_SITE,
                    scope_id="site_diag",
                    site_id="site_diag",
                    key_id="key_default",
                    client_ref="127.0.0.1",
                    event_code="auth.rate_limit_exceeded" if index < 3 else "auth.replay_blocked",
                    status_code=429 if index < 3 else 409,
                    method="POST",
                    path="/v1/runtime/execute",
                    trace_id=f"manualguard{index:02d}",
                    payload_json={"source": "test_seed"},
                    created_at=datetime.now(UTC) - timedelta(minutes=3),
                )
            )

        session.commit()

    runtime_summary_response = client.get(
        "/internal/service/runtime/diagnostics/summary?site_id=site_diag&recent_minutes=120",
        headers=build_internal_headers(),
    )
    callback_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=callback_failed&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    cancel_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=cancel_requested&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    dispatching_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=callback_dispatching&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    queued_stale_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=queued_stale&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    cancel_stuck_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=cancel_stuck&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    callback_overdue_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=callback_overdue&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    guard_events_response = client.get(
        "/internal/service/runtime/diagnostics/guard-events?site_id=site_diag&limit=20",
        headers=build_internal_headers(),
    )
    audit_summary_response = client.get(
        "/internal/service/audit-events/summary?window_minutes=120&limit=10",
        headers=build_internal_headers(),
    )
    decision_summary_response = client.get(
        "/internal/service/commercial-decisions/summary?site_id=site_diag&window_minutes=120&limit=10",
        headers=build_internal_headers(),
    )
    abuse_guard_response = client.get(
        "/internal/service/runtime/diagnostics/abuse-guard?window_seconds=600&limit_per_scope=5",
        headers=build_internal_headers(),
    )

    assert runtime_summary_response.status_code == 200
    runtime_summary = runtime_summary_response.json()["data"]
    assert runtime_summary["queue"]["queued_runs"] == 1
    assert runtime_summary["queue"]["running_runs"] == 1
    assert runtime_summary["queue"]["pressure_state"] == "attention"
    assert "queue.queued_stale" in runtime_summary["queue"]["pressure_reasons"]
    assert runtime_summary["queue"]["queued_oldest_age_seconds"] >= 600
    assert runtime_summary["cancel"]["active_requests"] == 1
    assert runtime_summary["cancel"]["pressure_state"] == "attention"
    assert "cancel.request_stuck" in runtime_summary["cancel"]["pressure_reasons"]
    assert runtime_summary["cancel"]["oldest_request_age_seconds"] >= 300
    assert runtime_summary["callback"]["failed"] == 1
    assert runtime_summary["callback"]["recoverable_dispatching"] == 1
    assert runtime_summary["callback"]["recovery_action"] == (
        "requeue_pending_after_stale_dispatch_lease"
    )
    assert runtime_summary["callback"]["pressure_state"] == "attention"
    assert "callback.failed" in runtime_summary["callback"]["pressure_reasons"]
    assert "callback.overdue" in runtime_summary["callback"]["pressure_reasons"]
    assert "callback.dispatching_stale" in runtime_summary["callback"]["pressure_reasons"]
    assert runtime_summary["callback"]["pending_not_due"] == 0
    assert runtime_summary["callback"]["oldest_due_age_seconds"] >= 600
    assert runtime_summary["retention"]["due_purge"] == 1

    assert callback_runs_response.status_code == 200
    callback_items = callback_runs_response.json()["data"]["items"]
    assert any(
        item["run_id"] == callback_run_id
        and item["callback_last_error_code"] == "runtime.callback_delivery_failed"
        for item in callback_items
    )

    assert cancel_runs_response.status_code == 200
    cancel_items = cancel_runs_response.json()["data"]["items"]
    assert any(item["run_id"] == running_run_id for item in cancel_items)
    assert all(item["run_id"] != queued_run_id for item in cancel_items)

    assert dispatching_runs_response.status_code == 200
    dispatching_items = dispatching_runs_response.json()["data"]["items"]
    assert any(item["run_id"] == dispatching_run_id for item in dispatching_items)

    assert queued_stale_runs_response.status_code == 200
    queued_stale_items = queued_stale_runs_response.json()["data"]["items"]
    assert any(
        item["run_id"] == queued_run_id
        and item["suggested_actions"][0]["action"] == "requeue_stale_queued"
        and item["suggested_actions"][0]["mode"] == "worker_auto"
        for item in queued_stale_items
    )

    assert cancel_stuck_runs_response.status_code == 200
    cancel_stuck_items = cancel_stuck_runs_response.json()["data"]["items"]
    assert any(item["run_id"] == running_run_id for item in cancel_stuck_items)

    assert callback_overdue_runs_response.status_code == 200
    callback_overdue_items = callback_overdue_runs_response.json()["data"]["items"]
    assert any(
        item["run_id"] == overdue_run_id
        and item["suggested_actions"][0]["action"] == "redeliver_failed_callback"
        and item["suggested_actions"][0]["mode"] == "worker_auto"
        for item in callback_overdue_items
    )

    assert guard_events_response.status_code == 200
    guard_items = guard_events_response.json()["data"]["items"]
    assert any(item["event_code"] == "auth.replay_blocked" for item in guard_items)

    assert audit_summary_response.status_code == 200
    audit_summary = audit_summary_response.json()["data"]
    assert audit_summary["totals"]["succeeded"] >= 1
    assert audit_summary["totals"]["error"] >= 1
    assert any(
        item["event_kind"] == "account.upsert" and item["outcome"] == "succeeded"
        for item in audit_summary["groups"]
    )
    assert any(
        item["event_kind"] == "site.activate" and item["outcome"] == "error"
        for item in audit_summary["groups"]
    )

    assert decision_summary_response.status_code == 200
    decision_summary = decision_summary_response.json()["data"]
    assert decision_summary["totals"]["events"] >= 3
    assert decision_summary["totals"]["allow"] >= 3
    assert any(item["decision_code"] == "commercial.allowed" for item in decision_summary["groups"])

    assert abuse_guard_response.status_code == 200
    abuse_guard_payload = abuse_guard_response.json()["data"]
    abuse_guard = abuse_guard_payload["scopes"]
    assert abuse_guard["public_post_site"]["max_requests_per_window"] == 10
    assert any(item["scope_id"] == "site_diag" for item in abuse_guard["public_post_site"]["items"])
    assert abuse_guard["internal_post_token"]["items"][0]["scope_id"] == "internal"
    assert abuse_guard_payload["watchlist_summary"]["highest_severity"] == "critical"
    assert abuse_guard_payload["watchlist_summary"]["request_burst_count"] >= 1
    assert abuse_guard_payload["watchlist_summary"]["reject_storm_count"] >= 1
    public_site_request_item = next(
        item for item in abuse_guard["public_post_site"]["items"] if item["scope_id"] == "site_diag"
    )
    assert public_site_request_item["severity"] == "critical"
    assert public_site_request_item["signal_kind"] == "request_burst"
    assert "request_burst_limit_exceeded" in public_site_request_item["reason_codes"]
    assert public_site_request_item["limit_ratio"] > 1.0
    public_site_cooldown_item = next(
        item
        for item in abuse_guard["public_post_site"]["cooldown_items"]
        if item["scope_id"] == "site_diag"
    )
    assert public_site_cooldown_item["severity"] == "critical"
    assert public_site_cooldown_item["signal_kind"] == "reject_storm"
    assert "reject_storm_limit_exceeded" in public_site_cooldown_item["reason_codes"]
    assert "rejects_include_rate_limits" in public_site_cooldown_item["reason_codes"]
    assert any(
        item["event_code"] == "auth.rate_limit_exceeded"
        for item in public_site_cooldown_item["event_code_breakdown"]
    )
    assert any(
        item["scope_kind"] == REPLAY_SCOPE_PUBLIC_POST_SITE
        and item["scope_id"] == "site_diag"
        and item["signal_kind"] == "reject_storm"
        for item in abuse_guard_payload["watchlist"]
    )
    assert any(
        item["event_code"] == "auth.replay_blocked"
        for item in abuse_guard_payload["guard_event_codes"]
    )
    assert any(
        item["scope_id"] == "site_diag"
        for item in abuse_guard["public_post_site"]["cooldown_items"]
    )

    with get_session(database_url) as session:
        guard_events = list(
            session.scalars(
                select(RuntimeGuardEvent)
                .where(RuntimeGuardEvent.site_id == "site_diag")
                .order_by(RuntimeGuardEvent.id.asc())
            )
        )
    assert any(event.event_code == "auth.replay_blocked" for event in guard_events)

    with get_session(database_url) as session:
        running_run = session.get(RunRecord, running_run_id)
        assert running_run is not None
        running_run.status = "canceled"
        running_run.canceled_at = datetime.now(UTC)
        session.commit()

    canceled_runs_response = client.get(
        "/internal/service/runtime/diagnostics/runs?issue_kind=canceled_recent&site_id=site_diag&limit=5",
        headers=build_internal_headers(),
    )
    assert canceled_runs_response.status_code == 200
    canceled_items = canceled_runs_response.json()["data"]["items"]
    assert any(item["run_id"] == running_run_id for item in canceled_items)

    dispose_engine(database_url)


def test_service_routes_runtime_callback_dispatch_recovery_is_operator_visible(
    tmp_path: Path,
    allow_example_callback_dns: None,
) -> None:
    callback_requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        callback_requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(202)

    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_recovery",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    CommercialService(
        database_url,
        settings=_runtime_service_settings(database_url),
    ).update_site_runtime_callbacks(
        site_id="site_recovery",
        terminal_callback={
            "enabled": True,
            "callback_url": "https://example.com/recover",
            "key_id": "runtime_callback_key",
            "secret": "runtime-callback-secret-for-tests-32b",
            "callback_id": "runtime_terminal",
        },
    )

    payload = {
        "site_id": "site_recovery",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-recover-001",
        "task_backend": {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "terminal_callback_required",
            "polling_interval_sec": 60,
        },
        "input": {"messages": [{"role": "user", "content": "recover callback dispatch"}]},
    }
    body = json.dumps(payload).encode("utf-8")
    execute_response = client.post(
        "/v1/runtime/execute",
        content=body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_recovery",
                idempotency_key="idem-service-recover-001",
                trace_id="traceservicerecover001000000",
                body=body,
            )
        ),
    )

    assert execute_response.status_code == 200
    run_id = str(execute_response.json()["data"]["run_id"])
    trace_id = str(execute_response.json()["data"]["trace_id"])

    with get_session(database_url) as session:
        run = session.get(RunRecord, run_id)
        assert run is not None
        run.callback_status = "dispatching"
        run.callback_attempt_count = 1
        run.callback_last_attempt_at = datetime.now(UTC) - timedelta(minutes=6)
        run.callback_next_attempt_at = None
        session.commit()

    summary_before_response = client.get(
        "/internal/service/runtime/diagnostics/summary?site_id=site_recovery&recent_minutes=120",
        headers=build_internal_headers(),
    )
    assert summary_before_response.status_code == 200
    summary_before = summary_before_response.json()
    assert summary_before["meta"]["revision"] == "m8"
    assert summary_before["data"]["callback"]["recoverable_dispatching"] == 1

    worker = RuntimeService(
        database_url,
        settings=_runtime_service_settings(database_url),
        callback_dispatcher=HttpRuntimeCallbackDispatcher(
            transport=httpx.MockTransport(handler),
        ),
        callback_max_attempts=3,
        callback_retry_backoff_seconds=0,
    )
    dispatched = worker.dispatch_pending_callbacks(max_callbacks=1)

    assert dispatched == [
        {
            "run_id": run_id,
            "callback_status": "delivered",
            "trace_id": trace_id,
            "status_code": 202,
        }
    ]
    assert callback_requests[0]["run_id"] == run_id

    audit_response = client.get(
        "/internal/service/audit-events?event_kind=runtime.callback_dispatch_recovered&site_id=site_recovery&limit=5",
        headers=build_internal_headers(),
    )
    assert audit_response.status_code == 200
    audit_items = audit_response.json()["data"]["items"]
    assert any(
        item["scope_id"] == run_id
        and item["payload"]["recovery_action"] == "requeue_pending_after_stale_dispatch_lease"
        for item in audit_items
    )

    dispose_engine(database_url)


def test_service_routes_runtime_backlog_diagnostics_exposes_scope_and_stale_layers(
    tmp_path: Path,
) -> None:
    database_url, client = _build_client(tmp_path)
    seed_site_auth(
        database_url,
        site_id="site_backlog_a",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    seed_site_auth(
        database_url,
        site_id="site_backlog_b",
        key_id="key_backlog_b",
        secret="magick-cloud-test-secret-backlog-b",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    queued_payload = {
        "site_id": "site_backlog_a",
        "ability_name": "workflow/media_nightly_image_optimize",
        "ability_family": "automation",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-backlog-queued-001",
        "input": {"messages": [{"role": "user", "content": "queued backlog"}]},
    }
    running_payload = {
        "site_id": "site_backlog_a",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-backlog-running-001",
        "input": {"messages": [{"role": "user", "content": "running backlog"}]},
    }
    other_payload = {
        "site_id": "site_backlog_b",
        "ability_name": "magick-ai/workflows/generate-post-draft",
        "ability_family": "workflow",
        "channel": "openapi",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "idempotency_key": "idem-service-backlog-other-001",
        "input": {"messages": [{"role": "user", "content": "fresh second scope"}]},
    }

    queued_body = json.dumps(queued_payload).encode("utf-8")
    running_body = json.dumps(running_payload).encode("utf-8")
    other_body = json.dumps(other_payload).encode("utf-8")
    queued_response = client.post(
        "/v1/runtime/execute",
        content=queued_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_backlog_a",
                idempotency_key="idem-service-backlog-queued-001",
                trace_id="traceservicebacklogqueued0001",
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
                site_id="site_backlog_a",
                idempotency_key="idem-service-backlog-running-001",
                trace_id="traceservicebacklogrunning001",
                body=running_body,
            )
        ),
    )
    other_response = client.post(
        "/v1/runtime/execute",
        content=other_body,
        headers=merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_backlog_b",
                key_id="key_backlog_b",
                secret="magick-cloud-test-secret-backlog-b",
                idempotency_key="idem-service-backlog-other-001",
                trace_id="traceservicebacklogother0001",
                body=other_body,
            )
        ),
    )

    assert queued_response.status_code == 200
    assert running_response.status_code == 200
    assert other_response.status_code == 200

    queued_run_id = str(queued_response.json()["data"]["run_id"])
    running_run_id = str(running_response.json()["data"]["run_id"])
    other_run_id = str(other_response.json()["data"]["run_id"])

    with get_session(database_url) as session:
        queued_run = session.get(RunRecord, queued_run_id)
        running_run = session.get(RunRecord, running_run_id)
        other_run = session.get(RunRecord, other_run_id)
        assert queued_run is not None
        assert running_run is not None
        assert other_run is not None
        queued_run.status = "queued"
        queued_run.started_at = datetime.now(UTC) - timedelta(minutes=9)
        running_run.status = "running"
        running_run.processing_started_at = datetime.now(UTC) - timedelta(minutes=18)
        other_run.status = "queued"
        other_run.started_at = datetime.now(UTC) - timedelta(seconds=45)
        session.commit()

    site_backlog_response = client.get(
        "/internal/service/runtime/diagnostics/backlog?scope_kind=site_id&limit=10",
        headers=build_internal_headers(),
    )
    family_backlog_response = client.get(
        "/internal/service/runtime/diagnostics/backlog?scope_kind=ability_family&limit=10",
        headers=build_internal_headers(),
    )

    assert site_backlog_response.status_code == 200
    site_payload = site_backlog_response.json()
    assert site_payload["meta"]["revision"] == "m1"
    assert site_payload["data"]["totals"]["queued"]["state"] == "stale"
    assert site_payload["data"]["totals"]["running"]["state"] == "stale"
    assert site_payload["data"]["totals"]["bottleneck_state"] == "mixed"
    assert site_payload["data"]["totals"]["lease_recovery_inputs"]["queued_stale_runs"] == 1
    assert site_payload["data"]["totals"]["lease_recovery_inputs"]["running_stale_runs"] == 1
    assert site_payload["data"]["scope_pressure"]["spread_state"] == "isolated"
    assert site_payload["data"]["scope_pressure"]["stale_scope_count"] == 1
    first_site_item = site_payload["data"]["items"][0]
    assert first_site_item["scope_kind"] == "site_id"
    assert first_site_item["scope_id"] == "site_backlog_a"
    assert first_site_item["queued"]["state"] == "stale"
    assert first_site_item["running"]["state"] == "stale"
    assert first_site_item["bottleneck_state"] == "mixed"
    assert "queue.stale" in first_site_item["pressure_reasons"]
    assert "worker.stale" in first_site_item["pressure_reasons"]

    assert family_backlog_response.status_code == 200
    family_payload = family_backlog_response.json()["data"]
    assert family_payload["scope_pressure"]["scope_kind"] == "ability_family"
    assert any(item["scope_id"] == "automation" for item in family_payload["items"])
    assert any(item["scope_id"] == "workflow" for item in family_payload["items"])

    dispose_engine(database_url)


def test_service_routes_enforce_internal_short_window_rate_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "internal_post_rate_limit_window_seconds": 60,
            "internal_post_max_requests_per_window": 1,
        },
    )

    first_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_limit_1", "name": "Limit One"},
        headers=build_internal_headers(idempotency_key="svc-limit-001"),
    )
    second_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_limit_2", "name": "Limit Two"},
        headers=build_internal_headers(idempotency_key="svc-limit-002"),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "auth.rate_limit_exceeded"

    dispose_engine(database_url)


def test_service_routes_enforce_internal_ip_short_window_rate_limit(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "internal_post_rate_limit_window_seconds": 60,
            "internal_post_max_requests_per_window": 10,
            "internal_post_max_requests_per_ip_window": 1,
        },
    )

    first_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_ip_limit_1", "name": "IP Limit One"},
        headers=build_internal_headers(idempotency_key="svc-ip-limit-001"),
    )
    second_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_ip_limit_2", "name": "IP Limit Two"},
        headers=build_internal_headers(idempotency_key="svc-ip-limit-002"),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "auth.rate_limit_exceeded"

    dispose_engine(database_url)


def test_service_routes_enforce_internal_guard_cooldown_after_rejects(tmp_path: Path) -> None:
    database_url, client = _build_client(
        tmp_path,
        settings_overrides={
            "internal_post_rate_limit_window_seconds": 600,
            "internal_post_max_requests_per_window": 10,
            "internal_post_max_requests_per_ip_window": 10,
            "internal_guard_cooldown_window_seconds": 3600,
            "internal_guard_max_reject_events_per_token_window": 1,
            "internal_guard_max_reject_events_per_ip_window": 1,
        },
    )

    first_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_cooldown_1", "name": "Cooldown One"},
        headers=build_internal_headers(idempotency_key="svc-cooldown-001"),
    )
    replay_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_cooldown_replay", "name": "Cooldown Replay"},
        headers=build_internal_headers(idempotency_key="svc-cooldown-001"),
    )
    cooldown_response = client.post(
        "/internal/service/accounts",
        json={"account_id": "acct_cooldown_2", "name": "Cooldown Two"},
        headers=build_internal_headers(idempotency_key="svc-cooldown-002"),
    )

    assert first_response.status_code == 200
    assert replay_response.status_code == 409
    assert replay_response.json()["error_code"] == "auth.replay_blocked"
    assert cooldown_response.status_code == 429
    assert cooldown_response.json()["error_code"] == "auth.rate_limit_exceeded"

    with get_session(database_url) as session:
        events = list(
            session.scalars(select(RuntimeGuardEvent).order_by(RuntimeGuardEvent.id.asc()))
        )
    assert any(event.event_code == "auth.replay_blocked" for event in events)
    assert any(event.event_code == "auth.rate_limit_exceeded" for event in events)

    dispose_engine(database_url)
