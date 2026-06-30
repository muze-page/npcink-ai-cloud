from __future__ import annotations

from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import ReadyReport
from app.domain.commercial.service import CommercialService, ServiceAuditContext
from tests.conftest import TEST_INTERNAL_AUTH_TOKEN, build_internal_headers


class StubServices:
    def __init__(self) -> None:
        self.settings = Settings(
            project_name="Npcink AI Cloud Test",
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
                "redis": True,
            },
            details={
                "database": "database is reachable",
                "redis": "redis is reachable",
            },
        )


class _CollectingSpanExporter(SpanExporter):
    def __init__(self) -> None:
        self.names: list[str] = []
        self.status_codes: list[str] = []

    def export(self, spans) -> SpanExportResult:  # type: ignore[no-untyped-def]
        for span in spans:
            self.names.append(span.name)
            self.status_codes.append(str(span.attributes.get("http.response.status_code", "")))
        return SpanExportResult.SUCCESS


def test_live_endpoint_returns_ok_envelope() -> None:
    client = TestClient(create_app(StubServices()))

    response = client.get("/health/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["error_code"] == ""
    assert payload["data"]["service"] == "Npcink AI Cloud Test"


def test_live_endpoint_emits_request_span_when_tracing_is_configured() -> None:
    services = StubServices()
    services.settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        otel_exporter_otlp_endpoint="http://example.invalid/v1/traces",
    )
    client = TestClient(create_app(services))
    exporter = _CollectingSpanExporter()
    provider = trace.get_tracer_provider()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)  # type: ignore[no-untyped-call]

    response = client.get("/health/live")

    processor.force_flush()
    assert response.status_code == 200
    assert "GET /health/live" in exporter.names
    assert "200" in exporter.status_codes


def test_ready_endpoint_returns_ok_envelope() -> None:
    client = TestClient(create_app(StubServices()))

    response = client.get(
        "/health/ready",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="healthready0001000000000000000000",
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["checks"] == {"database": True, "redis": True}


def test_ready_endpoint_requires_internal_token() -> None:
    client = TestClient(create_app(StubServices()))

    response = client.get("/health/ready")

    assert response.status_code == 401
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error_code"] == "auth.internal_token_required"


def test_live_endpoint_sets_baseline_security_headers() -> None:
    client = TestClient(create_app(StubServices()))

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["x-frame-options"] == "DENY"


def test_operational_ready_endpoint_requires_fresh_workers_and_cadence(tmp_path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'operational-ready.sqlite3'}"
    init_schema(database_url)

    class OperationalStubServices(StubServices):
        def __init__(self) -> None:
            super().__init__()
            self.settings = Settings(
                project_name="Npcink AI Cloud Test",
                environment="test",
                database_url=database_url,
                redis_url="redis://localhost:6379/0",
                internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
                worker_heartbeat_interval_seconds=60,
                provider_health_scan_interval_seconds=60,
            )

    services = OperationalStubServices()
    audit_context = ServiceAuditContext(
        trace_id="",
        idempotency_key="",
        method="POST",
        path="/internal/test",
        actor_kind="system_worker",
        actor_ref="test",
    )
    commercial = CommercialService(database_url, settings=services.settings)
    for worker_id in ("runtime_queue", "callback_dispatch", "ops_cadence"):
        commercial.record_service_audit_event(
            audit_context=audit_context,
            event_kind="worker.heartbeat",
            outcome="succeeded",
            scope_kind="worker",
            scope_id=worker_id,
            payload_json={"worker_id": worker_id, "status": "idle"},
        )
    for task_id, event_kind in (
        ("retention_cleanup", "runtime.retention_cleanup.cadence"),
        (
            "plugin_observability_cleanup",
            "plugin_observability.retention_cleanup.cadence",
        ),
        ("usage_rollup", "usage.rollup_cadence"),
        ("router_diagnostics_summary", "router.diagnostics_summary_cadence"),
        ("latency_probe_summary", "latency.probe_summary_cadence"),
        ("alert_provider_degradation", "alert.provider_degradation_cadence"),
        ("provider_health_scan", "provider.health_scan_cadence"),
    ):
        commercial.record_service_audit_event(
            audit_context=audit_context,
            event_kind=event_kind,
            outcome="succeeded",
            scope_kind="ops_cadence",
            scope_id=task_id,
            payload_json={"status": "ok"},
        )

    client = TestClient(create_app(services))
    response = client.get(
        "/health/operational-ready",
        headers=build_internal_headers(
            internal_token=TEST_INTERNAL_AUTH_TOKEN,
            trace_id="healthopready000100000000000000",
        ),
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error_code"] == "health.operational_not_ready"
    assert payload["data"]["checks"]["providers.fresh"] is False
    dispose_engine(database_url)
