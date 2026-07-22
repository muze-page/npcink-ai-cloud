from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy.engine import make_url

from app.core import runtime_config as runtime_config_module
from app.core.config import get_settings
from app.core.runtime_config import (
    RuntimeConfigError,
    configure_alembic_database_url,
    load_runtime_settings_values,
    read_internal_auth_token,
    runtime_config_digest,
)
from app.setup.state import SetupConfigStore, SetupStateError
from app.workers import catalog_refresh


@pytest.fixture(autouse=True)
def private_rds_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.runtime_config.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (2, 1, 6, "", ("10.0.0.10", 5432)),
        ],
    )


def _runtime_payload(ca_pem: str) -> dict[str, object]:
    return {
        "config_version": "runtime-config-v1",
        "cloud": {
            "name": "Test Cloud",
            "public_base_url": "https://cloud.example.com",
        },
        "database": {
            "host": "rm-test.pg.rds.aliyuncs.com",
            "port": 5432,
            "database": "npcink",
            "username": "npcink",
            "password": "p@ss:/word",
            "ssl_mode": "verify-full",
            "ca_sha256": hashlib.sha256(ca_pem.encode()).hexdigest(),
        },
        "security": {
            "internal_auth_token_file": "frontend/internal-auth-token",
            "admin_key_sha256": "a" * 64,
            "admin_session_secret": "admin-session-secret-value-that-is-long-enough",
            "service_settings_secret": "U1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1NTU1M=",
            "service_settings_encryption_key_id": "service-key",
            "runtime_data_encryption_secret": "UlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlJSUlI=",
            "runtime_data_encryption_key_id": "runtime-key",
            "portal_jwt_secret": "portal-session-secret-value-that-is-long-enough",
        },
    }


def _complete_store(tmp_path: Path) -> tuple[SetupConfigStore, dict[str, object]]:
    store = SetupConfigStore(tmp_path)
    ca_pem = "test-ca-bytes\n"
    payload = _runtime_payload(ca_pem)
    store.write_ca(ca_pem)
    store.write_internal_auth_token("nca_internal_" + secrets.token_urlsafe(32))
    store.write_runtime_config(payload)
    store.mark_complete(config_digest=runtime_config_digest(payload))
    return store, payload


def _configure_production_runtime(
    monkeypatch: pytest.MonkeyPatch,
    config_dir: Path,
) -> None:
    for environment_name in runtime_config_module._PRODUCTION_RUNTIME_ENV_KEYS:
        monkeypatch.delenv(environment_name, raising=False)
    monkeypatch.setenv("NPCINK_CLOUD_ENVIRONMENT", "production")
    monkeypatch.setenv("NPCINK_CLOUD_CONFIG_DIR", str(config_dir))
    get_settings.cache_clear()


def test_completed_runtime_config_loads_structured_rds_and_secret_projection(
    tmp_path: Path,
) -> None:
    store, _payload = _complete_store(tmp_path)

    values = load_runtime_settings_values(store.config_dir)

    assert values["project_name"] == "Test Cloud"
    assert values["environment"] == "production"
    assert values["admin_key_sha256"] == "a" * 64
    assert values["internal_auth_token"].startswith("nca_internal_")
    database_url = make_url(str(values["database_url"]))
    assert database_url.host == "rm-test.pg.rds.aliyuncs.com"
    assert database_url.query["sslmode"] == "verify-full"
    assert database_url.query["connect_timeout"] == "5"
    assert database_url.query["hostaddr"] == "10.0.0.10"
    assert values["database_pool_size"] == 2
    assert values["database_max_overflow"] == 1
    assert (tmp_path / "runtime-config.json").stat().st_mode & 0o777 == 0o600
    assert (tmp_path / "frontend/internal-auth-token").stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("state_kind", ("pending", "missing", "corrupt"))
def test_production_get_settings_never_falls_back_when_installation_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state_kind: str,
) -> None:
    store = SetupConfigStore(tmp_path)
    if state_kind == "pending":
        store.mark_pending()
    elif state_kind == "corrupt":
        _complete_store(tmp_path)
        store.state_path.write_text("{not-json", encoding="utf-8")
        store.state_path.chmod(0o640)
    _configure_production_runtime(monkeypatch, tmp_path)

    try:
        with pytest.raises(RuntimeConfigError):
            get_settings()
    finally:
        get_settings.cache_clear()


def test_worker_like_production_settings_call_rejects_legacy_database_env_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    SetupConfigStore(tmp_path).mark_pending()
    _configure_production_runtime(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "NPCINK_CLOUD_DATABASE_URL",
        "postgresql+psycopg://legacy:legacy-secret@old-db.invalid/legacy",
    )

    def unexpected_database_connection(_database_url: str) -> None:
        raise AssertionError("worker must fail before consuming a legacy database URL")

    monkeypatch.setattr(
        catalog_refresh,
        "require_database_connection",
        unexpected_database_connection,
    )
    try:
        with pytest.raises(RuntimeConfigError, match="must not be duplicated"):
            catalog_refresh.main()
    finally:
        get_settings.cache_clear()


def test_alembic_runtime_url_escapes_percent_interpolation_without_leaking_errors(
    tmp_path: Path,
) -> None:
    store, _payload = _complete_store(tmp_path)
    database_url = str(load_runtime_settings_values(store.config_dir)["database_url"])
    assert "%40" in database_url

    config = AlembicConfig()
    configure_alembic_database_url(config, database_url)

    assert config.get_main_option("sqlalchemy.url") == database_url

    class RejectingConfig:
        def set_main_option(self, _name: str, value: str) -> None:
            raise ValueError(f"rejected URL: {value}")

    with pytest.raises(RuntimeConfigError) as captured:
        configure_alembic_database_url(RejectingConfig(), database_url)

    assert str(captured.value) == "migration database configuration is invalid"
    assert database_url not in str(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True


@pytest.mark.parametrize(
    ("artifact", "invalid_mode"),
    (("rds-ca.pem", 0o640), ("frontend/internal-auth-token", 0o600)),
)
def test_runtime_ca_and_internal_token_require_exact_modes(
    tmp_path: Path,
    artifact: str,
    invalid_mode: int,
) -> None:
    store, _payload = _complete_store(tmp_path)
    (tmp_path / artifact).chmod(invalid_mode)

    with pytest.raises(RuntimeConfigError, match="permissions"):
        load_runtime_settings_values(store.config_dir)


@pytest.mark.parametrize("artifact", ("rds-ca.pem", "frontend/internal-auth-token"))
def test_runtime_ca_and_internal_token_reject_symlinks(
    tmp_path: Path,
    artifact: str,
) -> None:
    store, _payload = _complete_store(tmp_path)
    artifact_path = tmp_path / artifact
    regular_path = artifact_path.with_name(f"{artifact_path.name}.regular")
    artifact_path.rename(regular_path)
    artifact_path.symlink_to(regular_path.name)

    with pytest.raises(RuntimeConfigError, match="file is invalid"):
        load_runtime_settings_values(store.config_dir)


@pytest.mark.parametrize("artifact", ("rds-ca.pem", "frontend/internal-auth-token"))
def test_runtime_ca_and_internal_token_require_regular_files(
    tmp_path: Path,
    artifact: str,
) -> None:
    store, _payload = _complete_store(tmp_path)
    artifact_path = tmp_path / artifact
    artifact_path.unlink()
    artifact_path.mkdir()

    with pytest.raises(RuntimeConfigError, match="file is invalid"):
        load_runtime_settings_values(store.config_dir)


def test_runtime_ca_and_internal_token_require_process_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _payload = _complete_store(tmp_path)
    actual_uid = runtime_config_module.os.geteuid()

    monkeypatch.setattr(runtime_config_module.os, "geteuid", lambda: actual_uid + 1)
    with pytest.raises(RuntimeConfigError, match="owner"):
        load_runtime_settings_values(store.config_dir)

    owner_checks = iter((actual_uid, actual_uid + 1))
    monkeypatch.setattr(runtime_config_module.os, "geteuid", lambda: next(owner_checks))
    with pytest.raises(RuntimeConfigError, match="owner"):
        read_internal_auth_token(store.config_dir)


def test_runtime_config_digest_tamper_fails_closed(tmp_path: Path) -> None:
    store, payload = _complete_store(tmp_path)
    changed = json.loads(json.dumps(payload))
    changed["cloud"]["name"] = "Tampered"  # type: ignore[index]
    store.write_runtime_config(changed)

    with pytest.raises(RuntimeConfigError, match="digest"):
        load_runtime_settings_values(store.config_dir)


def test_broad_install_state_permissions_fail_closed(tmp_path: Path) -> None:
    store, _payload = _complete_store(tmp_path)
    store.state_path.chmod(0o666)

    with pytest.raises(SetupStateError, match="permissions"):
        store.read_state()
    with pytest.raises(RuntimeConfigError, match="permissions"):
        load_runtime_settings_values(store.config_dir)


def test_symlinked_configuration_directory_fails_closed(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir(mode=0o700)
    _complete_store(real_dir)
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(SetupStateError, match="directory"):
        SetupConfigStore(linked_dir).read_state()
    with pytest.raises(RuntimeConfigError, match="directory"):
        load_runtime_settings_values(linked_dir)


def test_completed_runtime_rechecks_private_rds_dns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _payload = _complete_store(tmp_path)
    monkeypatch.setattr(
        "app.core.runtime_config.socket.getaddrinfo",
        lambda *_args, **_kwargs: [(2, 1, 6, "", ("8.8.8.8", 5432))],
    )

    with pytest.raises(RuntimeConfigError, match="private addresses"):
        load_runtime_settings_values(store.config_dir)


def test_admin_key_rotation_transition_accepts_only_old_or_new_runtime_digest(
    tmp_path: Path,
) -> None:
    store, payload = _complete_store(tmp_path)
    old_digest = runtime_config_digest(payload)
    rotated = json.loads(json.dumps(payload))
    rotated["security"]["admin_key_sha256"] = "b" * 64
    new_digest = runtime_config_digest(rotated)
    state = json.loads(store.state_path.read_text())
    state["config_digest"] = new_digest
    state["config_transition"] = "admin_key_rotation.v1"
    state["previous_config_digest"] = old_digest
    store.atomic_write_json(store.state_path, state, mode=0o640)

    assert load_runtime_settings_values(store.config_dir)["admin_key_sha256"] == "a" * 64
    assert store.read_state().installation_state == "complete"

    store.write_runtime_config(rotated)
    assert load_runtime_settings_values(store.config_dir)["admin_key_sha256"] == "b" * 64

    unrelated = json.loads(json.dumps(rotated))
    unrelated["security"]["admin_key_sha256"] = "c" * 64
    store.write_runtime_config(unrelated)
    with pytest.raises(RuntimeConfigError, match="digest"):
        load_runtime_settings_values(store.config_dir)


def test_admin_key_rotation_transition_requires_bounded_marker(tmp_path: Path) -> None:
    store, payload = _complete_store(tmp_path)
    state = json.loads(store.state_path.read_text())
    state["previous_config_digest"] = runtime_config_digest(payload)
    store.atomic_write_json(store.state_path, state, mode=0o640)

    with pytest.raises(RuntimeConfigError, match="transition"):
        load_runtime_settings_values(store.config_dir)
    with pytest.raises(RuntimeError, match="transition"):
        store.read_state()


def test_only_complete_state_carries_pg18_database_contract(tmp_path: Path) -> None:
    store = SetupConfigStore(tmp_path)
    store.mark_pending(
        attempt_id="install_attempt",
        idempotency_key_sha256="b" * 64,
        install_request_hmac_sha256="e" * 64,
    )
    pending = store.read_state()
    assert pending.database_contract == ""
    assert pending.idempotency_key_sha256 == "b" * 64
    assert pending.install_request_hmac_sha256 == "e" * 64

    store.mark_complete(config_digest="c" * 64)
    complete = store.read_state()
    assert complete.database_contract == "pg18_empty_initialization.v1"
    assert complete.config_digest == "c" * 64


def test_completed_state_without_database_contract_is_rejected(tmp_path: Path) -> None:
    store = SetupConfigStore(tmp_path)
    store.atomic_write_json(
        store.state_path,
        {
            "installation_state": "complete",
            "setup_revision": "first-install-v1",
            "retry_allowed": False,
            "updated_at": "2026-07-22T00:00:00Z",
            "config_digest": "d" * 64,
            "attempt_id": "",
            "idempotency_key_sha256": "",
            "install_request_hmac_sha256": "",
            "database_contract": "",
        },
        mode=0o640,
    )

    with pytest.raises(RuntimeError, match="completed installation evidence"):
        store.read_state()


@pytest.mark.parametrize(
    "artifact",
    ("runtime-config.json", "rds-ca.pem", "frontend/internal-auth-token"),
)
def test_missing_install_state_with_runtime_artifact_fails_closed(
    tmp_path: Path,
    artifact: str,
) -> None:
    store = SetupConfigStore(tmp_path)
    artifact_path = tmp_path / artifact
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text("protected-runtime-evidence")

    with pytest.raises(RuntimeError, match="state is missing"):
        store.read_state()


def test_missing_install_state_without_artifacts_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="state is missing"):
        SetupConfigStore(tmp_path).read_state()


def test_pending_install_state_with_runtime_artifact_fails_closed(tmp_path: Path) -> None:
    store = SetupConfigStore(tmp_path)
    store.mark_pending()
    store.write_runtime_config({"partial": True})

    with pytest.raises(RuntimeError, match="pending installation"):
        store.read_state()
