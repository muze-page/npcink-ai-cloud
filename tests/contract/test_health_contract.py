from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.services import ReadyReport
from tests.conftest import TEST_INTERNAL_AUTH_TOKEN, build_internal_headers


class FailingStubServices:
    def __init__(self) -> None:
        self.settings = Settings(
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url="sqlite+pysqlite:///:memory:",
            redis_url="redis://localhost:6379/0",
            internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        )

    async def get_live_payload(self) -> dict[str, str]:
        return {
            "service": self.settings.project_name,
            "environment": self.settings.environment,
        }

    async def get_ready_report(self) -> ReadyReport:
        return ReadyReport(
            checks={
                "database": True,
                "redis": False,
            },
            details={
                "database": "database is reachable",
                "redis": "redis is unavailable",
            },
        )


def test_ready_failure_uses_standard_envelope() -> None:
    client = TestClient(create_app(FailingStubServices()))

    response = client.get(
        "/health/ready",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="healthcontract000100000000000000",
        ),
    )

    assert response.status_code == 503
    payload = response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert payload["status"] == "error"
    assert payload["error_code"] == "health.dependency_unavailable"
    assert payload["data"]["checks"]["redis"] is False


def test_ready_contract_rejects_missing_internal_token() -> None:
    client = TestClient(create_app(FailingStubServices()))

    response = client.get("/health/ready")

    assert response.status_code == 401
    payload = response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert payload["status"] == "error"
    assert payload["error_code"] == "auth.internal_token_required"


def test_operational_ready_contract_rejects_missing_internal_token() -> None:
    client = TestClient(create_app(FailingStubServices()))

    response = client.get("/health/operational-ready")

    assert response.status_code == 401
    payload = response.json()
    assert set(payload.keys()) == {"status", "error_code", "message", "data", "meta"}
    assert payload["status"] == "error"
    assert payload["error_code"] == "auth.internal_token_required"
