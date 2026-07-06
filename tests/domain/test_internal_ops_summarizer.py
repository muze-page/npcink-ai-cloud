from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.adapters.providers.base import (
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ProviderCallRecord,
    RunRecord,
    RuntimeGuardEvent,
    ServiceAuditEvent,
    SiteKnowledgeSearchMetric,
    SiteServiceProjection,
)
from app.domain.advisor.service import InternalAIAdvisorService
from app.domain.catalog.service import CatalogService
from tests.conftest import seed_site_auth


class _DraftProvider:
    provider_id = "fake_llm"
    display_name = "Fake LLM"
    adapter_type = "fake"

    def __init__(self) -> None:
        self.requests: list[ProviderExecutionRequest] = []

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        raise NotImplementedError

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        return ProviderExecutionResult(
            output={
                "output_text": json.dumps(
                    {
                        "operator_summary": "LLM summarized runtime guard pressure.",
                        "support_draft": (
                            "We are reviewing a cloud service signal and will "
                            "follow up after checking diagnostics."
                        ),
                        "operator_next_step": "inspect_commercial_entitlement_and_runtime_guard",
                        "safety_note": "Internal ops draft only.",
                    }
                )
            },
            latency_ms=10,
            tokens_in=20,
            tokens_out=16,
            cost=0.001,
        )


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'internal-ops-summarizer.sqlite3'}"


def test_ops_summary_llm_prompt_uses_redacted_advisor_context(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_ops_summary",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
    )
    with get_session(database_url) as session:
        session.add(
            RuntimeGuardEvent(
                auth_surface="public",
                scope_kind="site",
                scope_id="site_ops_summary",
                site_id="site_ops_summary",
                key_id="key_default",
                client_ref="127.0.0.1",
                event_code="auth.rate_limit_exceeded",
                status_code=429,
                method="POST",
                path="/v1/runtime/execute",
                trace_id="ops-summary-trace",
                payload_json={"raw": "must stay out of llm prompt"},
                created_at=datetime.now(UTC),
            )
        )
        session.commit()

    provider = _DraftProvider()
    result = InternalAIAdvisorService(
        database_url,
        providers={provider.provider_id: provider},
        allowed_summarizer_provider_ids={provider.provider_id},
    ).get_ops_summary(
        scope="runtime",
        site_id="site_ops_summary",
        provider_id=provider.provider_id,
        model_id="ops-model",
    )

    assert result["generation"]["mode"] == "llm"
    assert result["ai_disclosure"]["content_origin"] == "ai_generated"
    assert result["ai_disclosure"]["generated_by_ai"] is True
    assert result["ai_disclosure"]["visible_label_required"] is True
    assert result["ai_disclosure"]["brand_label"] == "Npcink AI"
    assert result["ai_disclosure"]["review_status"] == "needs_review"
    assert result["ai_disclosure"]["provider_brand_visible"] is False
    assert result["operator_summary"] == "LLM summarized runtime guard pressure."
    assert provider.requests
    prompt_context = _extract_prompt_context(provider.requests[0].input_payload)
    assert "source" not in prompt_context["redacted_context"]["advisor"]
    assert "payload_json" not in json.dumps(prompt_context)
    assert "must stay out" not in json.dumps(prompt_context)
    assert (
        "do_not_generate_customer_article_or_marketing_content"
        in (prompt_context["redacted_context"]["forbidden"])
    )
    with get_session(database_url) as session:
        audit_event = session.execute(
            select(ServiceAuditEvent).where(
                ServiceAuditEvent.event_kind == "internal_advisor.ops_summary"
            )
        ).scalar_one()
        audit_payload = audit_event.payload_json or {}
        audit_text = json.dumps(audit_payload)
    assert audit_event.outcome == "success"
    assert audit_payload["generation_mode"] == "llm"
    assert audit_payload["provider_id"] == provider.provider_id
    assert audit_payload["model_id"] == "ops-model"
    assert audit_payload["tokens_in"] == 20
    assert audit_payload["tokens_out"] == 16
    assert audit_payload["cost"] == 0.001
    assert audit_payload["prompt_saved"] is False
    assert audit_payload["output_text_saved"] is False
    assert "support_draft" not in audit_text
    assert "must stay out" not in audit_text

    dispose_engine(database_url)


def test_ops_summary_provider_must_be_allowlisted(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_ops_summary",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
    )

    provider = _DraftProvider()
    result = InternalAIAdvisorService(
        database_url,
        providers={provider.provider_id: provider},
        allowed_summarizer_provider_ids={"different_provider"},
    ).get_ops_summary(
        scope="runtime",
        site_id="site_ops_summary",
        provider_id=provider.provider_id,
        model_id="ops-model",
    )

    assert result["generation"]["mode"] == "deterministic_fallback"
    assert result["generation"]["error_code"] == "provider_not_allowlisted"
    assert result["ai_disclosure"]["content_origin"] == "rule_generated"
    assert result["ai_disclosure"]["generated_by_ai"] is False
    assert result["ai_disclosure"]["visible_label_required"] is False
    assert not provider.requests
    with get_session(database_url) as session:
        audit_event = session.execute(
            select(ServiceAuditEvent).where(
                ServiceAuditEvent.event_kind == "internal_advisor.ops_summary"
            )
        ).scalar_one()
        audit_payload = audit_event.payload_json or {}
    assert audit_event.outcome == "blocked"
    assert audit_payload["generation_mode"] == "deterministic_fallback"
    assert audit_payload["provider_id"] == provider.provider_id
    assert audit_payload["error_code"] == "provider_not_allowlisted"
    assert audit_payload["prompt_saved"] is False
    assert audit_payload["output_text_saved"] is False

    dispose_engine(database_url)


def test_ops_summary_preview_compares_baseline_and_ai_branch(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_ops_summary",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
    )
    with get_session(database_url) as session:
        session.add(
            RuntimeGuardEvent(
                auth_surface="public",
                scope_kind="site",
                scope_id="site_ops_summary",
                site_id="site_ops_summary",
                key_id="key_default",
                client_ref="127.0.0.1",
                event_code="auth.rate_limit_exceeded",
                status_code=429,
                method="POST",
                path="/v1/runtime/execute",
                trace_id="ops-summary-preview-trace",
                payload_json={"raw": "preview prompt must stay redacted"},
                created_at=datetime.now(UTC),
            )
        )
        session.commit()

    provider = _DraftProvider()
    result = InternalAIAdvisorService(
        database_url,
        providers={provider.provider_id: provider},
        allowed_summarizer_provider_ids={provider.provider_id},
    ).get_ops_summary_preview(
        scope="runtime",
        site_id="site_ops_summary",
        provider_id=provider.provider_id,
        model_id="ops-model",
    )

    assert result["preview_version"] == "internal-ops-summarizer-preview-v1"
    assert result["baseline"]["generation"]["mode"] == "deterministic_fallback"
    assert result["ai"]["generation"]["mode"] == "llm"
    assert result["baseline"]["ai_disclosure"]["content_origin"] == "rule_generated"
    assert result["ai"]["ai_disclosure"]["content_origin"] == "ai_generated"
    assert result["ai"]["ai_disclosure"]["visible_label"] == "AI generated"
    assert result["ai"]["ai_disclosure"]["visible_notice"] == (
        "Generated by Npcink AI. Human review required before use."
    )
    assert result["comparison"] == {
        "baseline_mode": "deterministic_fallback",
        "ai_mode": "llm",
        "requested_provider_id": provider.provider_id,
        "model_id": "ops-model",
        "ai_used": True,
        "ai_called": True,
        "cache_hit": False,
        "cache_status": "miss",
        "text_changed": True,
        "tokens_in": 20,
        "tokens_out": 16,
        "cost": 0.001,
        "request_cost": 0.001,
        "error_code": "",
        "value_check": "review_ai_output",
    }
    assert result["safety"]["prompt_saved"] is False
    assert result["safety"]["wordpress_write_allowed"] is False
    assert len(provider.requests) == 1
    with get_session(database_url) as session:
        audit_events = (
            session.execute(
                select(ServiceAuditEvent).where(
                    ServiceAuditEvent.event_kind == "internal_advisor.ops_summary"
                )
            )
            .scalars()
            .all()
        )
    assert len(audit_events) == 1
    assert (audit_events[0].payload_json or {})["generation_mode"] == "llm"

    dispose_engine(database_url)


def test_ops_summary_caches_ai_analysis_until_refresh_or_expiry(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_ops_summary_cache",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
    )
    with get_session(database_url) as session:
        session.add(
            RuntimeGuardEvent(
                auth_surface="public",
                scope_kind="site",
                scope_id="site_ops_summary_cache",
                site_id="site_ops_summary_cache",
                key_id="key_default",
                client_ref="127.0.0.1",
                event_code="auth.rate_limit_exceeded",
                status_code=429,
                method="POST",
                path="/v1/runtime/execute",
                trace_id="ops-summary-cache-trace",
                payload_json={"raw": "cache prompt must stay redacted"},
                created_at=datetime.now(UTC),
            )
        )
        session.commit()

    provider = _DraftProvider()
    service = InternalAIAdvisorService(
        database_url,
        providers={provider.provider_id: provider},
        allowed_summarizer_provider_ids={provider.provider_id},
    )
    first = service.get_ops_summary(
        scope="runtime",
        site_id="site_ops_summary_cache",
        provider_id=provider.provider_id,
        model_id="ops-model",
        cache_ttl_seconds=1800,
    )
    second = service.get_ops_summary(
        scope="runtime",
        site_id="site_ops_summary_cache",
        provider_id=provider.provider_id,
        model_id="ops-model",
        cache_ttl_seconds=1800,
    )

    assert len(provider.requests) == 1
    assert first["generation"]["mode"] == "llm"
    assert first["generation"]["cache_status"] == "miss"
    assert first["generation"]["request_cost"] == 0.001
    assert second["generation"]["mode"] == "llm_cached"
    assert second["generation"]["cache_status"] == "hit"
    assert second["generation"]["cache_hit"] is True
    assert second["generation"]["request_cost"] == 0.0
    assert second["ai_disclosure"]["content_origin"] == "ai_generated"
    assert second["ai_disclosure"]["source_generation_mode"] == "llm_cached"
    assert second["ai_disclosure"]["copy_export_notice"] == (
        "AI generated by Npcink AI; human review required."
    )
    assert second["operator_summary"] == first["operator_summary"]

    with get_session(database_url) as session:
        projection = session.execute(
            select(SiteServiceProjection).where(
                SiteServiceProjection.projection_kind == "internal_ops_summary_cache"
            )
        ).scalar_one()
        projection_payload = projection.payload_json or {}
        audit_events = (
            session.execute(
                select(ServiceAuditEvent)
                .where(ServiceAuditEvent.event_kind == "internal_advisor.ops_summary")
                .order_by(ServiceAuditEvent.id)
            )
            .scalars()
            .all()
        )
    assert projection.site_id == "site_ops_summary_cache"
    assert projection_payload["prompt_saved"] is False
    assert projection_payload["raw_payload_saved"] is False
    assert projection_payload["summary"]["operator_summary"] == first["operator_summary"]
    assert [event.outcome for event in audit_events] == ["success", "cache_hit"]
    assert (audit_events[1].payload_json or {})["generation_mode"] == "llm_cached"

    reviewed = service.review_ops_summary_disclosure(
        cache_key=first["generation"]["cache_key"],
        review_status="human_confirmed",
        actor_ref="platform:tester",
    )
    assert reviewed["review_status"] == "human_confirmed"
    assert reviewed["ai_disclosure"]["review_status"] == "human_confirmed"
    assert reviewed["ai_disclosure"]["reviewed_by"] == "platform:tester"

    confirmed = service.get_ops_summary(
        scope="runtime",
        site_id="site_ops_summary_cache",
        provider_id=provider.provider_id,
        model_id="ops-model",
        cache_ttl_seconds=1800,
    )
    assert confirmed["generation"]["mode"] == "llm_cached"
    assert confirmed["ai_disclosure"]["review_status"] == "human_confirmed"
    assert confirmed["ai_disclosure"]["reviewed_by"] == "platform:tester"

    with get_session(database_url) as session:
        review_event = session.execute(
            select(ServiceAuditEvent).where(
                ServiceAuditEvent.event_kind == "internal_advisor.ai_disclosure_review"
            )
        ).scalar_one()
        review_payload = review_event.payload_json or {}
    assert review_event.outcome == "human_confirmed"
    assert review_event.actor_ref == "platform:tester"
    assert review_payload["cache_key"] == first["generation"]["cache_key"]
    assert review_payload["generated_by_ai"] is True
    assert review_payload["prompt_saved"] is False
    assert review_payload["output_text_saved"] is False

    history = service.list_ops_summary_history(
        site_id="site_ops_summary_cache",
        scope="runtime_operations",
        limit=5,
    )
    assert history["history_version"] == "internal-ops-summary-history-v1"
    assert len(history["items"]) == 1
    history_item = history["items"][0]
    assert history_item["cache_key"] == first["generation"]["cache_key"]
    assert history_item["scope"] == "runtime_operations"
    assert history_item["site_id"] == "site_ops_summary_cache"
    assert history_item["generation"]["mode"] == "llm"
    assert history_item["generation"]["cost"] == 0.001
    assert history_item["ai_disclosure"]["review_status"] == "human_confirmed"
    assert history_item["ai_disclosure"]["reviewed_by"] == "platform:tester"
    assert "source_context" not in json.dumps(history_item)

    value_metrics = service.get_ops_summary_value_metrics(
        site_id="site_ops_summary_cache",
        scope="runtime",
        window_days=7,
    )
    assert value_metrics["value_metrics_version"] == "internal-ops-summary-value-v1"
    assert value_metrics["filters"]["scope"] == "runtime_operations"
    assert value_metrics["totals"]["analysis_requests"] == 3
    assert value_metrics["totals"]["ai_called"] == 1
    assert value_metrics["totals"]["cache_hits"] == 2
    assert value_metrics["totals"]["request_cost"] == 0.001
    assert value_metrics["totals"]["estimated_cache_savings"] == 0.002
    assert value_metrics["review"]["cached_ai_items"] == 1
    assert value_metrics["review"]["human_confirmed"] == 1
    assert value_metrics["rates"]["confirmed_rate"] == 1.0
    assert value_metrics["value_signal"]["status"] == "promising"

    refreshed = service.get_ops_summary(
        scope="runtime",
        site_id="site_ops_summary_cache",
        provider_id=provider.provider_id,
        model_id="ops-model",
        force_refresh=True,
        cache_ttl_seconds=1800,
    )
    assert len(provider.requests) == 2
    assert refreshed["generation"]["mode"] == "llm"
    assert refreshed["generation"]["cache_status"] == "miss"

    dispose_engine(database_url)


def test_operations_summary_uses_real_operating_metrics_for_ai_prompt(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_ops_metrics",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
    )
    now = datetime.now(UTC)
    with get_session(database_url) as session:
        failed_run = _run_record(
            run_id="run_ops_metrics_failed",
            site_id="site_ops_metrics",
            now=now,
            status="failed",
            error_code="provider.timeout",
        )
        succeeded_run = _run_record(
            run_id="run_ops_metrics_succeeded",
            site_id="site_ops_metrics",
            now=now,
            status="succeeded",
        )
        session.add_all([failed_run, succeeded_run])
        session.flush()
        session.add(
            ProviderCallRecord(
                run_id=failed_run.run_id,
                provider_id="openai",
                model_id="deepseek-v4-flash",
                instance_id="openai:deepseek-v4-flash",
                region="global",
                latency_ms=1200,
                tokens_in=400,
                tokens_out=120,
                cost=0.002,
                retry_count=1,
                fallback_used=True,
                error_code="provider.timeout",
                created_at=now,
            )
        )
        for index in range(4):
            search_run = _run_record(
                run_id=f"run_ops_metrics_search_{index}",
                site_id="site_ops_metrics",
                now=now,
                status="succeeded",
            )
            session.add(search_run)
            session.flush()
            session.add(
                SiteKnowledgeSearchMetric(
                    run_id=search_run.run_id,
                    site_id="site_ops_metrics",
                    account_id="acct_site_ops_metrics",
                    subscription_id="sub_site_ops_metrics",
                    status="succeeded",
                    error_code=None,
                    intent="site_search",
                    result_count=0,
                    no_hit=True,
                    top1_score=0.0,
                    avg_score=0.0,
                    query_hash=f"query-{index}",
                    query_chars=24,
                    max_results=5,
                    filter_json={},
                    embedding_provider="deterministic",
                    embedding_model="deterministic",
                    embedding_dimensions=3,
                    vector_backend="memory",
                    latency_ms=35,
                    created_at=now,
                    finished_at=now,
                )
            )
        session.commit()

    provider = _DraftProvider()
    result = InternalAIAdvisorService(
        database_url,
        providers={provider.provider_id: provider},
        allowed_summarizer_provider_ids={provider.provider_id},
    ).get_ops_summary(
        scope="operations",
        site_id="site_ops_metrics",
        provider_id=provider.provider_id,
        model_id="ops-model",
    )

    assert result["generation"]["mode"] == "llm"
    prompt_context = _extract_prompt_context(provider.requests[0].input_payload)
    signals = prompt_context["redacted_context"]["advisor"]["signals"]
    runtime_signal = next(item for item in signals if item["code"] == "ops.runtime_quality")
    provider_signal = next(item for item in signals if item["code"] == "ops.provider_quality")
    knowledge_signal = next(item for item in signals if item["code"] == "ops.knowledge_quality")
    drilldown = prompt_context["redacted_context"]["advisor"]["drilldown"]
    assert runtime_signal["total_runs"] == 6
    assert runtime_signal["failed_runs"] == 1
    assert provider_signal["provider_errors"] == 1
    assert provider_signal["fallbacks"] == 1
    assert knowledge_signal["knowledge_searches"] == 4
    assert knowledge_signal["knowledge_no_hit_rate"] == 1.0
    assert drilldown["failed_runs"][0]["run_id"] == "run_ops_metrics_failed"
    assert drilldown["failed_runs"][0]["error_code"] == "provider.timeout"
    assert drilldown["run_sites"][0]["site_id"] == "site_ops_metrics"
    assert drilldown["provider_breakdown"][0]["provider_id"] == "openai"
    assert drilldown["knowledge_sites"][0]["no_hit_rate"] == 1.0
    assert "input_json" not in json.dumps(prompt_context)
    assert "result_json" not in json.dumps(prompt_context)

    dispose_engine(database_url)


def _extract_prompt_context(input_payload: dict[str, Any]) -> dict[str, Any]:
    messages = input_payload["messages"]
    user_message = messages[1]
    return json.loads(user_message["content"])


def _run_record(
    *,
    run_id: str,
    site_id: str,
    now: datetime,
    status: str,
    error_code: str | None = None,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        site_id=site_id,
        account_id=f"acct_{site_id}",
        subscription_id=f"sub_{site_id}",
        plan_version_id="free-v1",
        ability_name="ops-metrics-test",
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
        status=status,
        idempotency_key=run_id,
        request_fingerprint=f"{run_id}-fingerprint",
        trace_id=f"{run_id}-trace",
        cancel_requested_at=None,
        canceled_at=None,
        input_json={"raw": "must stay out of prompt"},
        execution_input_ciphertext=None,
        policy_json={},
        result_ref="inline",
        result_json={"raw": "must stay out of prompt"},
        error_code=error_code,
        error_message=None,
        callback_status="not_requested",
        callback_attempt_count=0,
        callback_last_attempt_at=None,
        callback_delivered_at=None,
        callback_next_attempt_at=None,
        callback_last_error_code=None,
        callback_last_error_message=None,
        selected_provider_id="openai",
        selected_model_id="deepseek-v4-flash",
        selected_instance_id="openai:deepseek-v4-flash",
        fallback_used=False,
        started_at=now,
        processing_started_at=now,
        finished_at=now,
        retention_expires_at=now + timedelta(days=1),
        result_purged_at=None,
    )
