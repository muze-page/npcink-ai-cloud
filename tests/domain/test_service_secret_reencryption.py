from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ProviderConnection, ServiceSetting
from app.core.secrets import (
    decrypt_provider_connection_secret,
    decrypt_service_setting_secret,
    encrypt_provider_connection_secret,
)
from app.dev.reencrypt_service_secrets import main as reencryption_cli_main
from app.domain import service_secret_reencryption as reencryption_module
from app.domain.service_secret_reencryption import (
    ServiceSecretReencryptionError,
    apply_service_secret_reencryption,
    dry_run_service_secret_reencryption,
    inventory_service_secret_ciphertexts,
    verify_service_secret_ciphertexts,
)

LEGACY_ROOT = "legacy-service-secret-root-at-least-32b"
CURRENT_ROOT = "Y2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2M="
CURRENT_KEY_ID = "service-key-2026-07"

# These are deterministic, known Fernet fixtures created before the test run
# with the historical purpose-bound helper. Tests deliberately do not derive a
# Fernet key from LEGACY_ROOT, so production migration code remains the only
# place that may call the historical key builder.
LEGACY_PROVIDER_TOKEN = (
    "gAAAAABlU_EAAAECAwQFBgcICQoLDA0OD_TK5RnFLhNtAmCGZ5Zufdh6Cbjz4tOATikPqzQFV5tf"
    "J0Ead_usLy7Wfk2pVMDNNdrTRNI-51fLuQyvTdaSAQ0="
)
LEGACY_SMTP_TOKEN = (
    "gAAAAABlU_EAEBESExQVFhcYGRobHB0eH5j45_I9Xu8LyS9AArJ_3yyO3HaZWH_O2eYpizanhG7E"
    "kKOSEr7x6-hFhM4r8ObjvP5YDfuqYOBQZO8ew4a_qkY="
)
LEGACY_WEBHOOK_TOKEN = (
    "gAAAAABlU_EAICEiIyQlJicoKSorLC0uLwpssGYU8JqM1GCJDkt0z5BewAbPbck2nSdVDE4A_g2Gv"
    "gMgNBPnnHU5kGi_xv4-JynCwHbH3GhtI4TF5zzExUA="
)
PROVIDER_PLAINTEXT = "provider-secret-value"
SMTP_PLAINTEXT = "smtp-password-value"
WEBHOOK_PLAINTEXT = "webhook-token-value"


@pytest.fixture
def migration_database(tmp_path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'service-secret-migration.db'}"
    init_schema(database_url)
    try:
        yield database_url
    finally:
        dispose_engine(database_url)


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        service_settings_secret=CURRENT_ROOT,
        service_settings_encryption_key_id=CURRENT_KEY_ID,
    )


def _seed_service_secrets(database_url: str) -> dict[str, object]:
    settings = _settings(database_url)
    current_provider_token = encrypt_provider_connection_secret(
        "already-current-provider-secret",
        settings=settings,
    )
    service_map: dict[str, Any] = {
        "smtp_password": LEGACY_SMTP_TOKEN,
        "webhook_token": LEGACY_WEBHOOK_TOKEN,
        "empty_value": "",
        "null_value": None,
    }
    with get_session(database_url) as session:
        session.add_all(
            [
                ProviderConnection(
                    connection_id="provider_current",
                    provider_type="test",
                    display_name="Current provider",
                    secret_ciphertext=current_provider_token,
                ),
                ProviderConnection(
                    connection_id="provider_legacy",
                    provider_type="test",
                    display_name="Legacy provider",
                    secret_ciphertext=LEGACY_PROVIDER_TOKEN,
                ),
                ProviderConnection(
                    connection_id="provider_empty",
                    provider_type="test",
                    display_name="Empty provider",
                    secret_ciphertext="",
                ),
                ServiceSetting(
                    setting_id="mail_delivery",
                    setting_kind="email",
                    config_json={"preserve": {"config": True}},
                    secret_ciphertext_json=deepcopy(service_map),
                    metadata_json={"preserve": {"metadata": True}},
                ),
            ]
        )
        session.commit()
    return {
        "provider_current": current_provider_token,
        "provider_legacy": LEGACY_PROVIDER_TOKEN,
        "service": service_map,
    }


def _read_service_secrets(database_url: str) -> dict[str, object]:
    with get_session(database_url) as session:
        providers = {
            row.connection_id: row.secret_ciphertext
            for row in session.query(ProviderConnection).order_by(
                ProviderConnection.connection_id
            )
        }
        service = session.get(ServiceSetting, "mail_delivery")
        assert service is not None
        return {
            "providers": providers,
            "service": deepcopy(service.secret_ciphertext_json),
            "config": deepcopy(service.config_json),
            "metadata": deepcopy(service.metadata_json),
        }


def test_inventory_dry_run_apply_verify_and_json_map_preservation(
    migration_database: str,
) -> None:
    original = _seed_service_secrets(migration_database)
    settings = _settings(migration_database)

    inventory = inventory_service_secret_ciphertexts(
        migration_database,
        settings=settings,
    )
    assert (inventory.total, inventory.legacy, inventory.current) == (4, 3, 1)
    assert inventory.row_identifiers == (
        "provider_connection_secret:provider_current",
        "provider_connection_secret:provider_legacy",
        "service_setting_secret:mail_delivery:smtp_password",
        "service_setting_secret:mail_delivery:webhook_token",
    )
    assert inventory.counts_by_kind == {
        "provider_connection_secret": {
            "total": 2,
            "legacy": 1,
            "current": 1,
            "would_migrate": 1,
            "migrated": 0,
        },
        "service_setting_secret": {
            "total": 2,
            "legacy": 2,
            "current": 0,
            "would_migrate": 2,
            "migrated": 0,
        },
    }

    before_dry_run = _read_service_secrets(migration_database)
    dry_run = dry_run_service_secret_reencryption(
        migration_database,
        settings=settings,
        legacy_root_secrets=(LEGACY_ROOT,),
    )
    assert (dry_run.would_migrate, dry_run.migrated) == (3, 0)
    assert _read_service_secrets(migration_database) == before_dry_run

    applied = apply_service_secret_reencryption(
        migration_database,
        settings=settings,
        legacy_root_secrets=(LEGACY_ROOT,),
        maintenance_confirmed=True,
    )
    assert (applied.legacy, applied.current, applied.migrated) == (0, 4, 3)
    assert all(
        counts["migrated"] == expected
        for counts, expected in zip(
            applied.counts_by_kind.values(),
            (1, 2),
            strict=True,
        )
    )

    migrated = _read_service_secrets(migration_database)
    providers = migrated["providers"]
    service_map = migrated["service"]
    assert isinstance(providers, dict)
    assert isinstance(service_map, dict)
    assert str(providers["provider_legacy"]).startswith(
        f"sse.v1.{CURRENT_KEY_ID}."
    )
    assert str(service_map["smtp_password"]).startswith(
        f"sse.v1.{CURRENT_KEY_ID}."
    )
    assert str(service_map["webhook_token"]).startswith(
        f"sse.v1.{CURRENT_KEY_ID}."
    )
    assert providers["provider_current"] == original["provider_current"]
    assert service_map["empty_value"] == ""
    assert service_map["null_value"] is None
    assert migrated["config"] == {"preserve": {"config": True}}
    assert migrated["metadata"] == {"preserve": {"metadata": True}}

    with get_session(migration_database) as session:
        provider = session.get(ProviderConnection, "provider_legacy")
        service = session.get(ServiceSetting, "mail_delivery")
        assert provider is not None and service is not None
        secrets = service.secret_ciphertext_json or {}
        assert (
            decrypt_provider_connection_secret(
                provider.secret_ciphertext,
                settings=settings,
            )
            == PROVIDER_PLAINTEXT
        )
        assert (
            decrypt_service_setting_secret(
                str(secrets["smtp_password"]),
                settings=settings,
            )
            == SMTP_PLAINTEXT
        )
        assert (
            decrypt_service_setting_secret(
                str(secrets["webhook_token"]),
                settings=settings,
            )
            == WEBHOOK_PLAINTEXT
        )

    verified = verify_service_secret_ciphertexts(
        migration_database,
        settings=settings,
    )
    assert (verified.total, verified.legacy, verified.current) == (4, 0, 4)


def test_apply_requires_maintenance_confirmation(migration_database: str) -> None:
    _seed_service_secrets(migration_database)

    with pytest.raises(ServiceSecretReencryptionError, match="maintenance window"):
        apply_service_secret_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
            maintenance_confirmed=False,
        )


def test_inventory_rejects_noncanonical_active_key_id_even_without_rows(
    migration_database: str,
) -> None:
    settings = Settings.model_construct(
        environment="test",
        database_url=migration_database,
        service_settings_secret=CURRENT_ROOT,
        service_settings_encryption_key_id=f" {CURRENT_KEY_ID}",
    )

    with pytest.raises(ServiceSecretReencryptionError, match="key id is invalid"):
        inventory_service_secret_ciphertexts(
            migration_database,
            settings=settings,
        )


def test_unknown_sse_key_fails_closed_without_writes(migration_database: str) -> None:
    _seed_service_secrets(migration_database)
    with get_session(migration_database) as session:
        provider = session.get(ProviderConnection, "provider_legacy")
        assert provider is not None
        provider.secret_ciphertext = f"sse.v1.unknown-key.{LEGACY_PROVIDER_TOKEN}"
        session.commit()
    before = _read_service_secrets(migration_database)

    with pytest.raises(ServiceSecretReencryptionError, match="unsupported service secret envelope"):
        apply_service_secret_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
            maintenance_confirmed=True,
        )

    assert _read_service_secrets(migration_database) == before


def test_corrupt_legacy_entry_rolls_back_the_entire_apply(
    migration_database: str,
) -> None:
    _seed_service_secrets(migration_database)
    with get_session(migration_database) as session:
        service = session.get(ServiceSetting, "mail_delivery")
        assert service is not None
        secret_map = deepcopy(service.secret_ciphertext_json or {})
        secret_map["webhook_token"] = "corrupt-legacy-token"
        service.secret_ciphertext_json = secret_map
        session.commit()
    before = _read_service_secrets(migration_database)

    with pytest.raises(ServiceSecretReencryptionError, match="webhook_token"):
        apply_service_secret_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
            maintenance_confirmed=True,
        )

    assert _read_service_secrets(migration_database) == before


def test_flush_failure_rolls_back_all_ciphertexts(
    migration_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_service_secrets(migration_database)
    before = _read_service_secrets(migration_database)
    original_flush = Session.flush

    def fail_dirty_flush(self: Session, *args: object, **kwargs: object) -> None:
        if self.dirty:
            raise RuntimeError("database flush failed with TOP_SECRET_MARKER")
        original_flush(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "flush", fail_dirty_flush)
        with pytest.raises(ServiceSecretReencryptionError, match="re-encryption failed") as error:
            apply_service_secret_reencryption(
                migration_database,
                settings=_settings(migration_database),
                legacy_root_secrets=(LEGACY_ROOT,),
                maintenance_confirmed=True,
            )
        assert "TOP_SECRET_MARKER" not in str(error.value)

    assert _read_service_secrets(migration_database) == before


def test_apply_locks_both_complete_tables(
    migration_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_service_secrets(migration_database)
    original_scalars = Session.scalars
    observed: dict[type[object], tuple[bool, bool]] = {}

    def recording_scalars(
        self: Session,
        statement: Any,
        *args: object,
        **kwargs: object,
    ) -> Any:
        descriptions = getattr(statement, "column_descriptions", ())
        entity = descriptions[0].get("entity") if descriptions else None
        if entity in {ProviderConnection, ServiceSetting}:
            observed[entity] = (
                getattr(statement, "_for_update_arg", None) is not None,
                getattr(statement, "whereclause", None) is None,
            )
        return original_scalars(self, statement, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Session, "scalars", recording_scalars)
        apply_service_secret_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
            maintenance_confirmed=True,
        )

    assert observed == {
        ProviderConnection: (True, True),
        ServiceSetting: (True, True),
    }


def test_dry_run_rejects_failed_current_round_trip_without_writes(
    migration_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_service_secrets(migration_database)
    before = _read_service_secrets(migration_database)
    monkeypatch.setattr(
        reencryption_module,
        "encrypt_provider_connection_secret",
        lambda *_args, **_kwargs: f"sse.v1.{CURRENT_KEY_ID}.corrupt",
    )

    with pytest.raises(ServiceSecretReencryptionError, match="re-encryption failed"):
        dry_run_service_secret_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
        )

    assert _read_service_secrets(migration_database) == before


def test_verify_uses_normal_runtime_helper_for_current_ciphertext(
    migration_database: str,
) -> None:
    _seed_service_secrets(migration_database)
    with get_session(migration_database) as session:
        provider = session.get(ProviderConnection, "provider_legacy")
        service = session.get(ServiceSetting, "mail_delivery")
        assert provider is not None and service is not None
        provider.secret_ciphertext = f"sse.v1.{CURRENT_KEY_ID}.corrupt"
        service.secret_ciphertext_json = {"current_but_corrupt": provider.secret_ciphertext}
        session.commit()

    with pytest.raises(ServiceSecretReencryptionError, match="could not be decrypted"):
        verify_service_secret_ciphertexts(
            migration_database,
            settings=_settings(migration_database),
        )


def test_report_and_cli_output_never_include_sensitive_material(
    migration_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = _seed_service_secrets(migration_database)
    report = dry_run_service_secret_reencryption(
        migration_database,
        settings=_settings(migration_database),
        legacy_root_secrets=(LEGACY_ROOT,),
    ).as_dict()
    serialized = repr(report)
    forbidden = (
        LEGACY_ROOT,
        CURRENT_ROOT,
        LEGACY_PROVIDER_TOKEN,
        LEGACY_SMTP_TOKEN,
        LEGACY_WEBHOOK_TOKEN,
        PROVIDER_PLAINTEXT,
        SMTP_PLAINTEXT,
        WEBHOOK_PLAINTEXT,
        str(original["provider_current"]),
    )
    assert "provider_connection_secret:provider_legacy" in serialized
    assert all(value not in serialized for value in forbidden)

    monkeypatch.setenv("NPCINK_CLOUD_ENVIRONMENT", "test")
    monkeypatch.setenv("NPCINK_CLOUD_DATABASE_URL", migration_database)
    monkeypatch.setenv("NPCINK_CLOUD_SERVICE_SETTINGS_SECRET", CURRENT_ROOT)
    monkeypatch.setenv(
        "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID",
        CURRENT_KEY_ID,
    )
    monkeypatch.setenv("OLD_SERVICE_SECRET_ROOT_FOR_TEST", LEGACY_ROOT)
    assert (
        reencryption_cli_main(
            [
                "dry-run",
                "--old-root-env",
                "OLD_SERVICE_SECRET_ROOT_FOR_TEST",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert all(value not in captured.out for value in forbidden)
    assert '"would_migrate": 3' in captured.out

    with pytest.raises(SystemExit) as exit_info:
        reencryption_cli_main(["dry-run", "--old-root-env", LEGACY_ROOT])
    assert exit_info.value.code == 1
    rejected = capsys.readouterr()
    assert LEGACY_ROOT not in rejected.err
    assert "environment variable name is invalid" in rejected.err
