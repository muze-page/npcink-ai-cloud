from __future__ import annotations

import asyncio
import hashlib
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from app.api import main as main_module
from app.api.main import _create_setup_app
from app.api.routes import setup as setup_routes_module
from app.core.config import Settings
from app.setup.database import DatabaseValidationResult
from app.setup.errors import SetupError
from app.setup.models import DatabaseInput
from app.setup.security import sha256_text
from app.setup.service import SetupService
from app.setup.state import SetupConfigStore

SETUP_CODE = "nca_setup_" + "s" * 43


@pytest.fixture(autouse=True)
def private_rds_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.runtime_config.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("10.0.0.10", 5432))],
    )


def _ca_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Npcink Test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


class FakeDatabaseValidator:
    def __init__(self, *, fail_migration: bool = False) -> None:
        self.fail_migration = fail_migration
        self.events: list[str] = []

    def validate(
        self,
        database: DatabaseInput,
        *,
        ca_path: Path,
        interrupted_attempt_id: str = "",
    ) -> DatabaseValidationResult:
        assert ca_path.stat().st_mode & 0o777 == 0o600
        self.events.append(f"validate:{interrupted_attempt_id or 'fresh'}")
        return DatabaseValidationResult(
            postgres_major_version=18,
            ssl_mode="verify-full",
            database_empty=not bool(interrupted_attempt_id),
            alembic_state="interrupted" if interrupted_attempt_id else "empty",
            latency_ms=12,
            max_connections=100,
            database_url="postgresql+psycopg://unused:unused@127.0.0.1/unused",
        )

    def ensure_attempt_marker(self, database_url: str, *, attempt_id: str) -> None:
        self.events.append(f"marker:{attempt_id}")

    def run_migrations(self, database_url: str) -> None:
        self.events.append("migrate")
        if self.fail_migration:
            raise SetupError(500, "setup.migration_failed", "database migration failed")

    def remove_attempt_marker(self, database_url: str) -> None:
        self.events.append("marker_removed")


class LeakingDatabaseValidator(FakeDatabaseValidator):
    def validate(
        self,
        database: DatabaseInput,
        *,
        ca_path: Path,
        interrupted_attempt_id: str = "",
    ) -> DatabaseValidationResult:
        raise RuntimeError(f"could not connect with {database.password.get_secret_value()}")


class BlockingDatabaseValidator(FakeDatabaseValidator):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def validate(
        self,
        database: DatabaseInput,
        *,
        ca_path: Path,
        interrupted_attempt_id: str = "",
    ) -> DatabaseValidationResult:
        self.started.set()
        if not self.release.wait(timeout=3):
            raise AssertionError("test database validation was not released")
        return super().validate(
            database,
            ca_path=ca_path,
            interrupted_attempt_id=interrupted_attempt_id,
        )


def _database_payload(ca_pem: str) -> dict[str, object]:
    return {
        "host": "rm-test.pg.rds.aliyuncs.com",
        "port": 5432,
        "database": "npcink",
        "username": "npcink",
        "password": "database-secret",
        "ssl_mode": "verify-full",
        "ca_pem": ca_pem,
    }


def _service(
    tmp_path: Path,
    validator: FakeDatabaseValidator,
    *,
    runtime_activation_validator: Callable[[Settings], object] | None = None,
) -> SetupService:
    store = SetupConfigStore(tmp_path)
    store.mark_pending()
    store.atomic_write_json(
        store.setup_auth_path,
        {
            "setup_code_sha256": sha256_text(SETUP_CODE),
            "session_secret": secrets.token_urlsafe(32),
            "created_at": "2026-07-22T00:00:00Z",
        },
        mode=0o600,
    )
    activation_validator = runtime_activation_validator or (lambda _settings: None)
    return SetupService(
        store,
        database_validator=validator,  # type: ignore[arg-type]
        runtime_activation_validator=activation_validator,
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    service: SetupService,
) -> TestClient:
    monkeypatch.setenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "testserver")
    monkeypatch.setenv("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST", "https://testserver")
    return TestClient(_create_setup_app(service), base_url="https://testserver")


def test_setup_session_database_install_and_permanent_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = FakeDatabaseValidator()
    service = _service(tmp_path, validator)
    client = _client(monkeypatch, service)
    ca_pem = _ca_pem()
    offloaded_operations: list[str] = []
    original_to_thread = asyncio.to_thread

    async def recording_to_thread(function: object, *args: object, **kwargs: object) -> object:
        offloaded_operations.append(str(getattr(function, "__name__", "")))
        return await original_to_thread(function, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(setup_routes_module.asyncio, "to_thread", recording_to_thread)

    state = client.get("/setup/v1/state")
    assert state.status_code == 200
    assert state.json()["data"] == {
        "installation_state": "pending",
        "setup_revision": "first-install-v1",
        "retry_allowed": True,
    }
    assert state.headers["cache-control"] == "no-store"
    assert client.get("/v1/catalog/models").json()["error_code"] == (
        "setup.installation_required"
    )
    assert client.get("/setup/v1/not-a-route").status_code == 404
    assert client.get("/health/ready").status_code == 503

    for attempt in range(5):
        invalid = client.post(
            "/setup/v1/session",
            json={"setup_code": "wrong-setup-code-value"},
            headers={"X-Real-IP": "10.0.0.5"},
        )
        assert invalid.status_code == 401, attempt
    limited = client.post(
        "/setup/v1/session",
        json={"setup_code": SETUP_CODE},
        headers={"X-Real-IP": "10.0.0.5"},
    )
    assert limited.status_code == 429

    session = client.post(
        "/setup/v1/session",
        json={"setup_code": SETUP_CODE},
        headers={"X-Real-IP": "10.0.0.6"},
    )
    assert session.status_code == 200, session.text
    assert "npcink_setup_session" in session.headers["set-cookie"]
    assert "HttpOnly" in session.headers["set-cookie"]
    assert "SameSite=strict" in session.headers["set-cookie"]
    assert "Secure" in session.headers["set-cookie"]

    database_test = client.post("/setup/v1/database/test", json=_database_payload(ca_pem))
    assert database_test.status_code == 200, database_test.text
    assert database_test.json()["data"] == {
        "postgres_major_version": 18,
        "ssl_mode": "verify-full",
        "database_empty": True,
        "alembic_state": "empty",
        "latency_ms": 12,
        "max_connections": 100,
    }

    installed = client.post(
        "/setup/v1/install",
        json={
            "cloud_name": "Npcink Test Cloud",
            "public_base_url": "https://cloud.example.com",
            "database": _database_payload(ca_pem),
        },
        headers={"Idempotency-Key": "first-install-test"},
    )
    assert installed.status_code == 200, installed.text
    assert set(installed.json()["data"]) == {"admin_key", "next_url"}
    assert installed.json()["data"]["admin_key"].startswith("nca_admin_")
    assert installed.json()["data"]["next_url"] == "/admin/login"
    assert installed.headers["cache-control"] == "no-store"
    assert "Max-Age=0" in installed.headers["set-cookie"]

    complete = client.get("/setup/v1/state")
    assert complete.status_code == 200
    assert complete.json()["data"]["installation_state"] == "complete"
    closed = client.post("/setup/v1/database/test", json=_database_payload(ca_pem))
    assert closed.status_code == 404
    assert closed.json()["error_code"] == "setup.already_complete"
    assert not service.store.setup_auth_path.exists()
    assert service.store.internal_token_path.stat().st_mode & 0o777 == 0o640
    runtime_payload = service.store.runtime_config_path.read_text()
    assert "database-secret" in runtime_payload
    assert installed.json()["data"]["admin_key"] not in runtime_payload
    assert hashlib.sha256(runtime_payload.encode()).hexdigest() == (
        service.store.read_state().config_digest
    )
    assert service.store.read_state().database_contract == "pg18_empty_initialization.v1"
    assert validator.events[-1] == "marker_removed"
    assert offloaded_operations == ["test_database", "install"]


@pytest.mark.asyncio
async def test_setup_database_validation_does_not_block_liveness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = BlockingDatabaseValidator()
    service = _service(tmp_path, validator)
    monkeypatch.setenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "testserver")
    monkeypatch.setenv("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST", "https://testserver")
    transport = httpx.ASGITransport(app=_create_setup_app(service))

    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://testserver",
    ) as client:
        session = await client.post(
            "/setup/v1/session",
            json={"setup_code": SETUP_CODE},
            headers={"X-Real-IP": "10.0.0.9"},
        )
        assert session.status_code == 200

        database_request = asyncio.create_task(
            client.post(
                "/setup/v1/database/test",
                json=_database_payload(_ca_pem()),
            )
        )
        try:
            assert await asyncio.wait_for(
                asyncio.to_thread(validator.started.wait, 1),
                timeout=1.5,
            )
            live = await asyncio.wait_for(client.get("/health/live"), timeout=0.5)
            assert live.status_code == 200
        finally:
            validator.release.set()

        database_response = await asyncio.wait_for(database_request, timeout=2)
        assert database_response.status_code == 200


def test_complete_liveness_survives_runtime_activation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, FakeDatabaseValidator())
    from app.setup.models import InstallInput

    service.install(
        InstallInput.model_validate(
            {
                "cloud_name": "Npcink Test Cloud",
                "public_base_url": "https://cloud.example.com",
                "database": _database_payload(_ca_pem()),
            }
        ),
        idempotency_key="complete-runtime-health-failure",
    )
    application = main_module.InstallAwareApplication(service)

    def unavailable_runtime() -> object:
        raise RuntimeError("simulated runtime database activation failure")

    monkeypatch.setattr(application, "_build_runtime_application", unavailable_runtime)
    client = TestClient(application, base_url="https://testserver")

    live = client.get("/health/live")
    assert live.status_code == 200
    assert live.json()["data"] == {
        "service": "Npcink AI Cloud",
        "environment": "production",
    }
    assert live.headers["cache-control"] == "no-store"
    disallowed_live = client.post("/health/live")
    assert disallowed_live.status_code == 405
    assert disallowed_live.headers["allow"] == "GET"

    unauthenticated_ready = client.get("/health/ready")
    assert unauthenticated_ready.status_code == 401
    assert unauthenticated_ready.json()["error_code"] == "auth.internal_token_required"

    ready = client.get(
        "/health/ready",
        headers={
            "X-Npcink-Internal-Token": service.store.internal_token_path.read_text(),
        },
    )
    assert ready.status_code == 503
    assert ready.json()["error_code"] == "health.dependency_unavailable"
    assert service.store.read_state().installation_state == "complete"


def test_install_retry_requires_same_idempotency_key(
    tmp_path: Path,
) -> None:
    validator = FakeDatabaseValidator(fail_migration=True)
    service = _service(tmp_path, validator)
    request = {
        "cloud_name": "Npcink Test Cloud",
        "public_base_url": "https://cloud.example.com",
        "database": _database_payload(_ca_pem()),
    }
    from app.setup.models import InstallInput

    payload = InstallInput.model_validate(request)
    with pytest.raises(SetupError) as first:
        service.install(payload, idempotency_key="install-attempt-one")
    assert first.value.error_code == "setup.migration_failed"
    state = service.store.read_state()
    assert state.installation_state == "pending"
    assert state.idempotency_key_sha256 == sha256_text("install-attempt-one")
    assert state.install_request_hmac_sha256

    with pytest.raises(SetupError) as conflict:
        service.install(payload, idempotency_key="install-attempt-two")
    assert conflict.value.error_code == "setup.idempotency_key_conflict"
    assert "install-attempt-one" not in service.store.state_path.read_text()
    assert "database-secret" not in service.store.state_path.read_text()

    changed_request = dict(request)
    changed_request["cloud_name"] = "Different Cloud"
    changed_payload = InstallInput.model_validate(changed_request)
    with pytest.raises(SetupError) as payload_conflict:
        service.install(changed_payload, idempotency_key="install-attempt-one")
    assert payload_conflict.value.error_code == "setup.idempotency_key_conflict"


def test_setup_auth_cleanup_failure_does_not_commit_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, FakeDatabaseValidator())

    def fail_cleanup() -> None:
        raise PermissionError("simulated protected-file cleanup failure")

    monkeypatch.setattr(service.store, "delete_setup_auth", fail_cleanup)
    from app.setup.models import InstallInput

    with pytest.raises(SetupError) as failure:
        service.install(
            InstallInput.model_validate(
                {
                    "cloud_name": "Npcink Test Cloud",
                    "public_base_url": "https://cloud.example.com",
                    "database": _database_payload(_ca_pem()),
                }
            ),
            idempotency_key="setup-auth-cleanup-is-required",
        )

    assert failure.value.error_code == "setup.config_write_failed"
    assert service.store.read_state().installation_state == "pending"
    assert service.store.setup_auth_path.exists()
    assert not service.store.runtime_config_path.exists()
    assert not service.store.ca_path.exists()
    assert not service.store.internal_token_path.exists()


def test_runtime_activation_failure_does_not_commit_complete(tmp_path: Path) -> None:
    validator = FakeDatabaseValidator()
    activation_states: list[str] = []

    def fail_activation(_settings: Settings) -> None:
        activation_states.append(service.store.read_state().installation_state)
        raise RuntimeError("simulated runtime activation failure")

    service = _service(
        tmp_path,
        validator,
        runtime_activation_validator=fail_activation,
    )
    from app.setup.models import InstallInput

    with pytest.raises(SetupError) as failure:
        service.install(
            InstallInput.model_validate(
                {
                    "cloud_name": "Npcink Test Cloud",
                    "public_base_url": "https://cloud.example.com",
                    "database": _database_payload(_ca_pem()),
                }
            ),
            idempotency_key="runtime-activation-must-pass",
        )

    state = service.store.read_state()
    assert failure.value.error_code == "setup.config_write_failed"
    assert activation_states == ["initializing"]
    assert state.installation_state == "pending"
    assert state.attempt_id.startswith("install_")
    assert service.store.setup_auth_path.exists()
    assert not service.store.runtime_config_path.exists()
    assert "marker_removed" not in validator.events


def test_default_runtime_activation_constructs_services_before_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validator = FakeDatabaseValidator()
    store = SetupConfigStore(tmp_path)
    store.mark_pending()
    store.atomic_write_json(
        store.setup_auth_path,
        {
            "setup_code_sha256": sha256_text(SETUP_CODE),
            "session_secret": secrets.token_urlsafe(32),
            "created_at": "2026-07-22T00:00:00Z",
        },
        mode=0o600,
    )
    service = SetupService(store, database_validator=validator)  # type: ignore[arg-type]
    activation_states: list[str] = []

    def capture_activation(settings: Settings) -> object:
        assert settings.project_name == "Npcink Test Cloud"
        activation_states.append(store.read_state().installation_state)
        return object()

    monkeypatch.setattr(
        "app.core.services.create_default_services",
        capture_activation,
    )
    from app.setup.models import InstallInput

    service.install(
        InstallInput.model_validate(
            {
                "cloud_name": "Npcink Test Cloud",
                "public_base_url": "https://cloud.example.com",
                "database": _database_payload(_ca_pem()),
            }
        ),
        idempotency_key="default-runtime-activation",
    )

    assert activation_states == ["initializing"]
    assert store.read_state().installation_state == "complete"
    assert not store.setup_auth_path.exists()


def test_install_rejects_public_origin_that_differs_from_bootstrap_origin(
    tmp_path: Path,
) -> None:
    validator = FakeDatabaseValidator()
    service = _service(tmp_path, validator)
    service.public_origin_allowlist = {"https://cloud.example.com"}
    from app.setup.models import InstallInput

    with pytest.raises(SetupError) as mismatch:
        service.install(
            InstallInput.model_validate(
                {
                    "cloud_name": "Npcink Test Cloud",
                    "public_base_url": "https://other.example.com",
                    "database": _database_payload(_ca_pem()),
                }
            ),
            idempotency_key="public-origin-must-match",
        )

    assert mismatch.value.error_code == "setup.public_base_url_mismatch"
    assert "migrate" not in validator.events


def test_database_failure_response_does_not_expose_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, LeakingDatabaseValidator())
    client = _client(monkeypatch, service)
    session = client.post(
        "/setup/v1/session",
        json={"setup_code": SETUP_CODE},
        headers={"X-Real-IP": "10.0.0.8"},
    )
    assert session.status_code == 200

    response = client.post(
        "/setup/v1/database/test",
        json=_database_payload(_ca_pem()),
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "setup.database_unreachable"
    assert "database-secret" not in response.text
    assert "could not connect" not in response.text


def test_pending_deployment_does_not_construct_database_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, FakeDatabaseValidator())
    monkeypatch.setenv("NPCINK_CLOUD_ENVIRONMENT", "production")
    monkeypatch.setenv("NPCINK_CLOUD_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "testserver")
    monkeypatch.setenv("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST", "https://testserver")

    def unexpected_runtime_build(*args: object, **kwargs: object) -> object:
        raise AssertionError("pending deployment must not construct runtime services")

    monkeypatch.setattr(main_module, "create_default_services", unexpected_runtime_build)
    application = main_module.create_deployment_app()
    client = TestClient(application, base_url="https://testserver")

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json()["data"]["environment"] == "setup"
    assert service.store.read_state().installation_state == "pending"


def test_cleared_complete_configuration_never_reopens_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path, FakeDatabaseValidator())
    from app.setup.models import InstallInput

    service.install(
        InstallInput.model_validate(
            {
                "cloud_name": "Npcink Test Cloud",
                "public_base_url": "https://cloud.example.com",
                "database": _database_payload(_ca_pem()),
            }
        ),
        idempotency_key="complete-before-config-loss",
    )
    for path in (
        service.store.state_path,
        service.store.runtime_config_path,
        service.store.ca_path,
        service.store.internal_token_path,
    ):
        path.unlink(missing_ok=True)

    monkeypatch.setenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "testserver")
    monkeypatch.setenv("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST", "https://testserver")
    application = main_module.InstallAwareApplication(service)
    client = TestClient(application, base_url="https://testserver")

    state = client.get("/setup/v1/state")
    session = client.post(
        "/setup/v1/session",
        json={"setup_code": SETUP_CODE},
        headers={"X-Real-IP": "10.0.0.10"},
    )

    assert state.status_code == 503
    assert state.json()["error_code"] == "setup.config_write_failed"
    assert session.status_code == 503
    assert session.json()["error_code"] == "setup.config_write_failed"
    assert "npcink_setup_session" not in session.headers.get("set-cookie", "")


def test_interrupted_install_recovery_removes_partial_runtime_before_pending(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path, FakeDatabaseValidator())
    service.store.mark_initializing(
        attempt_id="install_interrupted",
        idempotency_key_sha256="a" * 64,
        install_request_hmac_sha256="b" * 64,
    )
    service.store.write_runtime_config({"partial": True})
    service.store.write_ca("partial-ca")
    service.store.write_internal_auth_token("partial-internal-token-value")

    state = service.state()

    assert state.installation_state == "pending"
    assert state.attempt_id == "install_interrupted"
    assert not service.store.runtime_config_path.exists()
    assert not service.store.ca_path.exists()
    assert not service.store.internal_token_path.exists()


def test_setup_guard_rejects_malformed_forwarded_host_and_origin_without_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(monkeypatch, _service(tmp_path, FakeDatabaseValidator()))

    malformed_host = client.get(
        "/setup/v1/state",
        headers={"X-Forwarded-Host": "https://testserver:not-a-port"},
    )
    malformed_origin = client.get(
        "/setup/v1/state",
        headers={"Origin": "https://testserver:not-a-port"},
    )

    assert malformed_host.status_code == 400
    assert malformed_host.json()["error_code"] == "request.forwarded_host_invalid"
    assert malformed_origin.status_code == 403
    assert malformed_origin.json()["error_code"] == "request.browser_origin_invalid"
