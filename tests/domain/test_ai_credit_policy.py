from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.adapters.repositories.commercial_repository import CommercialRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.domain.commercial.credits import (
    AI_CREDIT_BREAKDOWN_ORDER,
    AI_CREDIT_CAPABILITY_POLICY_REGISTRY,
    AI_CREDIT_CHARGE_CAPABILITY_REQUIRED_FIELDS,
    AI_CREDIT_CHARGE_COMPONENT_REQUIRED_FIELDS,
    AI_CREDIT_CHARGE_CONTRACT_VERSION,
    AI_CREDIT_COMPONENT_POLICY_REGISTRY,
    AI_CREDIT_FEATURE_CHARGE_RULE_REQUIRED_FIELDS,
    AI_CREDIT_FEATURE_CHARGE_RULES,
    AI_CREDIT_FEATURE_CHARGE_RULES_VERSION,
    AI_CREDIT_RATE_VERSION,
    estimate_runtime_request_ai_credits,
    list_ai_credit_feature_charge_rules,
    record_credit_ledger_component,
)
from app.domain.commercial.service import CommercialService


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'ai-credit-policy.sqlite3'}"


def test_ai_credit_component_registry_covers_every_breakdown_key() -> None:
    assert set(AI_CREDIT_BREAKDOWN_ORDER) == set(AI_CREDIT_COMPONENT_POLICY_REGISTRY)
    for source_type, policy in AI_CREDIT_COMPONENT_POLICY_REGISTRY.items():
        assert policy["source_type"] == source_type
        assert set(AI_CREDIT_CHARGE_COMPONENT_REQUIRED_FIELDS) <= set(policy)
        assert policy["charge_mode"] in {"consume", "meter_only"}
        assert policy["unit"]
        assert float(policy["rate"]) >= 0
        assert float(policy["minimum_charge"]) >= 0
        assert policy["budget_key"] == "ai_credits"


def test_ai_credit_capability_registry_defines_required_runtime_families() -> None:
    required_keys = {
        "runtime:text",
        "runtime:web_search",
        "runtime:image",
        "runtime:site_knowledge",
        "runtime:batch",
    }
    assert required_keys <= set(AI_CREDIT_CAPABILITY_POLICY_REGISTRY)
    for capability_key, policy in AI_CREDIT_CAPABILITY_POLICY_REGISTRY.items():
        assert policy["capability_key"] == capability_key
        assert set(AI_CREDIT_CHARGE_CAPABILITY_REQUIRED_FIELDS) <= set(policy)
        assert policy["charge_mode"]
        assert float(policy["request_base_credits"]) >= 0
        assert policy["ledger_components"]
        assert policy["budget_key"] == "ai_credits"


def test_ai_credit_feature_charge_rules_cover_billable_components() -> None:
    assert list_ai_credit_feature_charge_rules()
    referenced_components: set[str] = set()
    for feature_key, rule in AI_CREDIT_FEATURE_CHARGE_RULES.items():
        assert rule["feature_key"] == feature_key
        assert set(AI_CREDIT_FEATURE_CHARGE_RULE_REQUIRED_FIELDS) <= set(rule)
        assert rule["contract_version"] == AI_CREDIT_FEATURE_CHARGE_RULES_VERSION
        assert rule["budget_key"] == "ai_credits"
        capability_key = str(rule["capability_key"])
        assert capability_key in AI_CREDIT_CAPABILITY_POLICY_REGISTRY
        capability_components = set(
            str(component)
            for component in AI_CREDIT_CAPABILITY_POLICY_REGISTRY[capability_key][
                "ledger_components"
            ]
        )
        rule_components = {str(component) for component in rule["ledger_components"]}
        assert rule_components <= capability_components
        assert rule_components <= set(AI_CREDIT_COMPONENT_POLICY_REGISTRY)
        referenced_components.update(rule_components)

    billable_components = {
        source_type
        for source_type, policy in AI_CREDIT_COMPONENT_POLICY_REGISTRY.items()
        if policy["charge_mode"] == "consume"
    }
    assert billable_components <= referenced_components


def test_ai_credit_charge_contract_document_points_to_single_registry() -> None:
    contract = Path("docs/ai-credit-charge-contract-v1.md").read_text(encoding="utf-8")
    assert AI_CREDIT_CHARGE_CONTRACT_VERSION == "ai-credit-charge-contract-v1"
    assert "app/domain/commercial/credits.py" in contract
    assert "Do not add a second billing registry" in contract
    assert AI_CREDIT_FEATURE_CHARGE_RULES_VERSION in contract


def test_runtime_execute_authorization_calls_include_ai_credit_estimates() -> None:
    source = Path("app/domain/runtime/service.py").read_text(encoding="utf-8")
    for block in source.split("authorize_runtime_request(")[1:]:
        call = block.split(")\n", 1)[0]
        if 'request_kind="execute"' not in call and "SITE_KNOWLEDGE_STATUS_ABILITY" not in call:
            continue
        assert "estimated_ai_credits=" in call


def test_ai_credit_estimates_match_declared_provider_components() -> None:
    assert estimate_runtime_request_ai_credits(
        ability_family="workflow",
        execution_kind="text",
    ) == 1.0
    assert estimate_runtime_request_ai_credits(
        ability_family="tool",
        execution_kind="web_search",
        payload_json={"provider": "zhihu", "source_type": "zhida_deepsearch"},
    ) == 11.0
    assert estimate_runtime_request_ai_credits(
        ability_family="vision",
        execution_kind="image_source",
    ) == 4.0
    assert estimate_runtime_request_ai_credits(
        ability_name="npcink-cloud/site-knowledge-sync",
        ability_family="knowledge",
        execution_kind="site_knowledge",
        payload_json={"billing_mode": "consume_ai_credits"},
    ) == 0.0
    assert estimate_runtime_request_ai_credits(
        ability_name="npcink-cloud/site-knowledge-search",
        ability_family="knowledge",
        execution_kind="site_knowledge",
        payload_json={"billing_mode": "meter_only"},
    ) == 1.0


def test_record_credit_ledger_component_is_idempotent(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    component = {
        **AI_CREDIT_COMPONENT_POLICY_REGISTRY["runs"],
        "quantity": 2.0,
        "credits": 2.0,
    }
    with get_session(database_url) as session:
        repository = CommercialRepository(session)
        first = record_credit_ledger_component(
            repository=repository,
            account_id="acct_credit_policy",
            site_id="site_credit_policy",
            subscription_id="sub_credit_policy",
            plan_version_id="plan_credit_policy_v1",
            run_id="run-credit-policy-1",
            provider_call_id=None,
            component=component,
            source_id="run-credit-policy-1",
            idempotency_key="credit-policy-ledger-001",
            metadata_json={"source": "test"},
        )
        second = record_credit_ledger_component(
            repository=repository,
            account_id="acct_credit_policy",
            site_id="site_credit_policy",
            subscription_id="sub_credit_policy",
            plan_version_id="plan_credit_policy_v1",
            run_id="run-credit-policy-1",
            provider_call_id=None,
            component=component,
            source_id="run-credit-policy-1",
            idempotency_key="credit-policy-ledger-001",
            metadata_json={"source": "test"},
        )
        session.commit()

    assert first is not None
    assert second is not None
    assert first.ledger_entry_id == second.ledger_entry_id
    assert first.credit_delta == -2.0
    assert first.rate_version == AI_CREDIT_RATE_VERSION
    dispose_engine(database_url)


def test_site_knowledge_index_volume_is_meter_only() -> None:
    documents = AI_CREDIT_COMPONENT_POLICY_REGISTRY["vector_documents"]
    chunks = AI_CREDIT_COMPONENT_POLICY_REGISTRY["vector_chunks"]

    assert documents["charge_mode"] == "meter_only"
    assert documents["rate"] == 0.0
    assert chunks["charge_mode"] == "meter_only"
    assert chunks["rate"] == 0.0


def test_admin_credit_estimate_excludes_site_knowledge_index_maintenance(
    tmp_path: Path,
) -> None:
    service = CommercialService(_sqlite_url(tmp_path))
    maintenance = {"metering_class": "site_knowledge_index_maintenance"}
    meter_events = [
        SimpleNamespace(meter_key="runs", quantity=1, payload_json=maintenance),
        SimpleNamespace(meter_key="tokens_total", quantity=2000, payload_json=maintenance),
        SimpleNamespace(
            meter_key="provider_calls",
            quantity=1,
            execution_kind="site_knowledge",
            ability_family="knowledge",
            payload_json=maintenance,
        ),
        SimpleNamespace(meter_key="runs", quantity=1, payload_json={}),
        SimpleNamespace(meter_key="tokens_total", quantity=500, payload_json={}),
    ]

    breakdown = service._build_admin_account_credit_breakdown(
        meter_events=meter_events,
        totals={"runs": 2.0, "tokens_total": 2500.0},
        indexed_document_count=10,
        indexed_chunk_count=101,
    )
    by_key = {str(item["key"]): item for item in breakdown}

    assert by_key["runs"]["credits"] == 1.0
    assert by_key["tokens_total"]["quantity"] == 500.0
    assert by_key["tokens_total"]["credits"] == 1
    assert by_key["vector_documents"]["credits"] == 0.0
    assert by_key["vector_chunks"]["credits"] == 0.0
    assert "provider_calls_other" not in by_key
