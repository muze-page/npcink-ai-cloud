from __future__ import annotations

from pathlib import Path

from app.core.db import dispose_engine, get_session, init_schema
from app.domain.commercial.service import CommercialService
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'commercial-runtime-defaults.sqlite3'}"


def test_authorize_runtime_request_uses_starter_package_budgets_and_concurrency(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    service = CommercialService(database_url)
    with get_session(database_url) as session:
        decision = service.authorize_runtime_request(
            session=session,
            site_id="site_alpha",
            ability_family="workflow",
            channel="openapi",
            execution_kind="text",
            execution_tier="cloud",
            data_classification="internal",
            trace_id="trace-commercial-defaults-001",
            idempotency_key="idem-commercial-defaults-001",
            request_kind="resolve",
        )
        session.commit()

    assert decision["budgets"] == {
        "max_runs_per_period": 500.0,
        "max_tokens_per_period": 200_000.0,
        "max_cost_per_period": 5.0,
    }
    assert decision["concurrency"] == {
        "max_active_runs": 1,
    }

    dispose_engine(database_url)


def test_authorize_runtime_request_allows_cloud_managed_knowledge_family(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )

    service = CommercialService(database_url)
    with get_session(database_url) as session:
        decision = service.authorize_runtime_request(
            session=session,
            site_id="site_alpha",
            ability_family="knowledge",
            channel="openapi",
            execution_kind="embedding",
            execution_tier="cloud",
            data_classification="public_site_content",
            trace_id="trace-commercial-knowledge-001",
            idempotency_key="idem-commercial-knowledge-001",
            request_kind="resolve",
        )
        session.commit()

    assert decision["decision_code"] == "commercial.allowed"
    assert decision["entitlements"]["ability_families"] == ["*"]

    dispose_engine(database_url)
