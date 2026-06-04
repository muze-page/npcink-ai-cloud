from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.adapters.providers.base import (
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import RuntimeGuardEvent, ServiceAuditEvent
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
    assert result["operator_summary"] == "LLM summarized runtime guard pressure."
    assert provider.requests
    prompt_context = _extract_prompt_context(provider.requests[0].input_payload)
    assert "source" not in prompt_context["redacted_context"]["advisor"]
    assert "payload_json" not in json.dumps(prompt_context)
    assert "must stay out" not in json.dumps(prompt_context)
    assert "do_not_generate_customer_article_or_marketing_content" in (
        prompt_context["redacted_context"]["forbidden"]
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
    assert result["comparison"] == {
        "baseline_mode": "deterministic_fallback",
        "ai_mode": "llm",
        "requested_provider_id": provider.provider_id,
        "model_id": "ops-model",
        "ai_called": True,
        "text_changed": True,
        "tokens_in": 20,
        "tokens_out": 16,
        "cost": 0.001,
        "error_code": "",
        "value_check": "review_ai_output",
    }
    assert result["safety"]["prompt_saved"] is False
    assert result["safety"]["wordpress_write_allowed"] is False
    assert len(provider.requests) == 1
    with get_session(database_url) as session:
        audit_events = session.execute(
            select(ServiceAuditEvent).where(
                ServiceAuditEvent.event_kind == "internal_advisor.ops_summary"
            )
        ).scalars().all()
    assert len(audit_events) == 1
    assert (audit_events[0].payload_json or {})["generation_mode"] == "llm"

    dispose_engine(database_url)


def _extract_prompt_context(input_payload: dict[str, Any]) -> dict[str, Any]:
    messages = input_payload["messages"]
    user_message = messages[1]
    return json.loads(user_message["content"])
