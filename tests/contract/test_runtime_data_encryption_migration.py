from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    PortalMutationIdempotencyReceipt,
    PortalOAuthState,
    Principal,
    ProviderConnection,
    RunRecord,
    ServiceSetting,
    Site,
    SiteApiKey,
)
from app.core.secrets import decrypt_runtime_data_plaintext
from app.dev.reencrypt_runtime_data import main as reencryption_cli_main
from app.domain.runtime import runtime_data_reencryption as reencryption_module
from app.domain.runtime.runtime_data_reencryption import (
    ADDON_PAYLOAD_PURPOSE,
    PORTAL_IDEMPOTENCY_PURPOSE,
    RUN_INPUT_PURPOSE,
    RUNTIME_CALLBACK_PURPOSE,
    SITE_API_KEY_PURPOSE,
    LegacyRuntimeDataKey,
    RuntimeDataReencryptionError,
    apply_runtime_data_reencryption,
    dry_run_runtime_data_reencryption,
    inventory_runtime_data_ciphertexts,
    verify_runtime_data_ciphertexts,
)

LEGACY_ROOT = "legacy-admin-session-root-secret-at-least-32b"
OLD_RDE_KEY_ID = "runtime-key-2026-06"


@pytest.fixture
def migration_database(tmp_path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'runtime-data-migration.db'}"
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
        runtime_data_encryption_secret="new-runtime-data-root-secret-at-least-32b",
        runtime_data_encryption_key_id="runtime-key-2026-07",
    )


def _legacy_ciphertext(plaintext: bytes, *, purpose: str) -> str:
    derived_key = hashlib.sha256(f"{purpose}:{LEGACY_ROOT}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key)).encrypt(plaintext).decode("utf-8")


def _seed_all_five_legacy_ciphertexts(
    database_url: str,
    *,
    envelope_key_id: str | None = None,
) -> dict[str, str]:
    now = datetime.now(UTC)
    ciphertexts = {
        "site_api_key": _legacy_ciphertext(b"site-signing-secret", purpose=SITE_API_KEY_PURPOSE),
        "site_runtime_callback": _legacy_ciphertext(
            b"callback-secret",
            purpose=RUNTIME_CALLBACK_PURPOSE,
        ),
        "addon_connection_payload": _legacy_ciphertext(
            b'{"api_key":"addon-secret"}',
            purpose=ADDON_PAYLOAD_PURPOSE,
        ),
        "portal_idempotency_response": _legacy_ciphertext(
            b'{"ok":true}',
            purpose=PORTAL_IDEMPOTENCY_PURPOSE,
        ),
        "runtime_execution_input": _legacy_ciphertext(
            b'{"prompt":"hello"}',
            purpose=RUN_INPUT_PURPOSE,
        ),
    }
    if envelope_key_id is not None:
        ciphertexts = {
            kind: f"rde.v1.{envelope_key_id}.{ciphertext}"
            for kind, ciphertext in ciphertexts.items()
        }
    with get_session(database_url) as session:
        session.add(
            Principal(
                principal_id="prn_migration",
                email="migration@example.com",
                status="active",
                session_version=1,
                metadata_json={"preserve": True},
            )
        )
        session.add(
            Site(
                site_id="site_migration",
                account_id=None,
                name="Migration site",
                status="active",
                site_url="https://example.com",
                platform_kind="wordpress",
                metadata_json={
                    "preserve": {"site": True},
                    "runtime_callbacks": {
                        "terminal": {
                            "url": "https://example.com/callback",
                            "secret_ciphertext": ciphertexts["site_runtime_callback"],
                        },
                        "preserve": True,
                    },
                },
            )
        )
        session.flush()
        session.add(
            SiteApiKey(
                key_id="key_migration",
                site_id="site_migration",
                secret_hash="hash",
                signing_secret_ciphertext=ciphertexts["site_api_key"],
                status="active",
                metadata_json={"preserve": True},
            )
        )
        session.add(
            PortalOAuthState(
                state_id="oauth_migration",
                provider="wordpress_addon_connection",
                state_hash="state-hash",
                status="pending",
                expires_at=now + timedelta(hours=1),
                metadata_json={
                    "payload_ciphertext": ciphertexts["addon_connection_payload"],
                    "preserve": {"oauth": True},
                },
            )
        )
        session.add(
            PortalMutationIdempotencyReceipt(
                receipt_id="receipt_migration",
                principal_id="prn_migration",
                idempotency_key="idempotency-key",
                request_method="POST",
                request_path="/portal/test",
                request_fingerprint="fingerprint",
                state="completed",
                claim_token=None,
                lease_expires_at=None,
                response_status=200,
                response_body_ciphertext=ciphertexts["portal_idempotency_response"],
                retention_ttl_seconds=3600,
                expires_at=now + timedelta(hours=1),
                completed_at=now,
            )
        )
        session.add(
            RunRecord(
                run_id="run_migration",
                site_id="site_migration",
                ability_name="test.ability",
                channel="test",
                execution_kind="queued",
                profile_id="test-profile",
                status="queued",
                trace_id="trace-migration",
                execution_input_ciphertext=ciphertexts["runtime_execution_input"],
            )
        )
        session.add(
            ProviderConnection(
                connection_id="provider_sentinel",
                provider_type="test",
                display_name="Provider sentinel",
                secret_ciphertext="provider-secret-ciphertext-must-not-change",
            )
        )
        session.add(
            ServiceSetting(
                setting_id="service_sentinel",
                setting_kind="test",
                secret_ciphertext_json={"secret": "service-setting-ciphertext-must-not-change"},
            )
        )
        session.commit()
    return ciphertexts


def _read_all_five_ciphertexts(database_url: str) -> dict[str, str]:
    with get_session(database_url) as session:
        site = session.get(Site, "site_migration")
        key = session.get(SiteApiKey, "key_migration")
        oauth = session.get(PortalOAuthState, "oauth_migration")
        receipt = session.get(PortalMutationIdempotencyReceipt, "receipt_migration")
        run = session.get(RunRecord, "run_migration")
        assert site is not None
        assert key is not None
        assert oauth is not None
        assert receipt is not None
        assert run is not None
        site_metadata = site.metadata_json or {}
        oauth_metadata = oauth.metadata_json or {}
        return {
            "site_api_key": str(key.signing_secret_ciphertext),
            "site_runtime_callback": str(
                site_metadata["runtime_callbacks"]["terminal"]["secret_ciphertext"]
            ),
            "addon_connection_payload": str(oauth_metadata["payload_ciphertext"]),
            "portal_idempotency_response": str(receipt.response_body_ciphertext),
            "runtime_execution_input": str(run.execution_input_ciphertext),
        }


def test_inventory_dry_run_apply_verify_and_repeat_apply(
    migration_database: str,
) -> None:
    original = _seed_all_five_legacy_ciphertexts(migration_database)
    settings = _settings(migration_database)

    inventory = inventory_runtime_data_ciphertexts(migration_database, settings=settings)
    assert (inventory.total, inventory.legacy, inventory.current) == (5, 5, 0)
    assert set(inventory.counts_by_kind) == set(original)
    assert all(counts["total"] == 1 for counts in inventory.counts_by_kind.values())

    dry_run = dry_run_runtime_data_reencryption(
        migration_database,
        settings=settings,
        legacy_root_secrets=(LEGACY_ROOT,),
    )
    assert dry_run.would_migrate == 5
    assert dry_run.migrated == 0
    assert _read_all_five_ciphertexts(migration_database) == original

    applied = apply_runtime_data_reencryption(
        migration_database,
        settings=settings,
        legacy_root_secrets=(LEGACY_ROOT,),
        maintenance_confirmed=True,
    )
    assert (applied.legacy, applied.current, applied.migrated) == (0, 5, 5)
    assert all(counts["migrated"] == 1 for counts in applied.counts_by_kind.values())
    migrated = _read_all_five_ciphertexts(migration_database)
    assert all(
        ciphertext.startswith("rde.v1.runtime-key-2026-07.") for ciphertext in migrated.values()
    )

    verified = verify_runtime_data_ciphertexts(migration_database, settings=settings)
    assert (verified.total, verified.legacy, verified.current) == (5, 0, 5)

    repeated = apply_runtime_data_reencryption(
        migration_database,
        settings=settings,
        legacy_root_secrets=(LEGACY_ROOT,),
        maintenance_confirmed=True,
    )
    assert repeated.migrated == 0
    assert _read_all_five_ciphertexts(migration_database) == migrated

    with get_session(migration_database) as session:
        site = session.get(Site, "site_migration")
        oauth = session.get(PortalOAuthState, "oauth_migration")
        assert site is not None and site.metadata_json is not None
        assert oauth is not None and oauth.metadata_json is not None
        assert site.metadata_json["preserve"] == {"site": True}
        assert site.metadata_json["runtime_callbacks"]["preserve"] is True
        assert oauth.metadata_json["preserve"] == {"oauth": True}


def test_explicit_old_rde_envelope_migrates_to_the_active_rde_key(
    migration_database: str,
) -> None:
    original = _seed_all_five_legacy_ciphertexts(
        migration_database,
        envelope_key_id=OLD_RDE_KEY_ID,
    )
    settings = _settings(migration_database)
    legacy_envelope_keys = (LegacyRuntimeDataKey(key_id=OLD_RDE_KEY_ID, root_secret=LEGACY_ROOT),)

    with pytest.raises(RuntimeDataReencryptionError, match="unsupported runtime data envelope"):
        inventory_runtime_data_ciphertexts(migration_database, settings=settings)
    inventory = inventory_runtime_data_ciphertexts(
        migration_database,
        settings=settings,
        allowed_legacy_envelope_key_ids=frozenset({OLD_RDE_KEY_ID}),
    )
    assert (inventory.total, inventory.legacy, inventory.current) == (5, 5, 0)

    dry_run = dry_run_runtime_data_reencryption(
        migration_database,
        settings=settings,
        legacy_root_secrets=(LEGACY_ROOT,),
        legacy_envelope_keys=legacy_envelope_keys,
    )
    assert (dry_run.legacy, dry_run.would_migrate, dry_run.migrated) == (5, 5, 0)
    assert _read_all_five_ciphertexts(migration_database) == original

    applied = apply_runtime_data_reencryption(
        migration_database,
        settings=settings,
        legacy_root_secrets=(LEGACY_ROOT,),
        legacy_envelope_keys=legacy_envelope_keys,
        maintenance_confirmed=True,
    )
    assert (applied.legacy, applied.current, applied.migrated) == (0, 5, 5)
    assert all(
        ciphertext.startswith("rde.v1.runtime-key-2026-07.")
        for ciphertext in _read_all_five_ciphertexts(migration_database).values()
    )
    assert verify_runtime_data_ciphertexts(migration_database, settings=settings).current == 5


def test_unknown_old_rde_key_id_fails_closed_without_writes(migration_database: str) -> None:
    _seed_all_five_legacy_ciphertexts(
        migration_database,
        envelope_key_id="unknown-old-key",
    )
    before_apply = _read_all_five_ciphertexts(migration_database)

    with pytest.raises(RuntimeDataReencryptionError, match="unsupported runtime data envelope"):
        apply_runtime_data_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
            legacy_envelope_keys=(
                LegacyRuntimeDataKey(key_id=OLD_RDE_KEY_ID, root_secret=LEGACY_ROOT),
            ),
            maintenance_confirmed=True,
        )

    assert _read_all_five_ciphertexts(migration_database) == before_apply


def test_apply_does_not_touch_provider_or_service_setting_ciphertexts(
    migration_database: str,
) -> None:
    _seed_all_five_legacy_ciphertexts(migration_database)
    apply_runtime_data_reencryption(
        migration_database,
        settings=_settings(migration_database),
        legacy_root_secrets=(LEGACY_ROOT,),
        maintenance_confirmed=True,
    )

    with get_session(migration_database) as session:
        provider = session.get(ProviderConnection, "provider_sentinel")
        service_setting = session.get(ServiceSetting, "service_sentinel")
        assert provider is not None
        assert service_setting is not None
        assert provider.secret_ciphertext == "provider-secret-ciphertext-must-not-change"
        assert service_setting.secret_ciphertext_json == {
            "secret": "service-setting-ciphertext-must-not-change"
        }


def test_apply_requires_maintenance_confirmation(migration_database: str) -> None:
    _seed_all_five_legacy_ciphertexts(migration_database)
    with pytest.raises(RuntimeDataReencryptionError, match="maintenance window"):
        apply_runtime_data_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
            maintenance_confirmed=False,
        )


def test_dry_run_verifies_the_new_envelope_round_trip(
    migration_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _seed_all_five_legacy_ciphertexts(migration_database)
    monkeypatch.setattr(
        reencryption_module,
        "encrypt_runtime_data_plaintext",
        lambda *_args, **_kwargs: "rde.v1.runtime-key-2026-07.invalid",
    )

    with pytest.raises(RuntimeDataReencryptionError, match="re-encryption failed"):
        dry_run_runtime_data_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
        )

    assert _read_all_five_ciphertexts(migration_database) == original


def test_corrupt_row_rolls_back_the_entire_apply(migration_database: str) -> None:
    original = _seed_all_five_legacy_ciphertexts(migration_database)
    with get_session(migration_database) as session:
        run = session.get(RunRecord, "run_migration")
        assert run is not None
        run.execution_input_ciphertext = "corrupt-legacy-token"
        session.commit()
    before_apply = _read_all_five_ciphertexts(migration_database)

    with pytest.raises(RuntimeDataReencryptionError, match="run_migration"):
        apply_runtime_data_reencryption(
            migration_database,
            settings=_settings(migration_database),
            legacy_root_secrets=(LEGACY_ROOT,),
            maintenance_confirmed=True,
        )

    assert _read_all_five_ciphertexts(migration_database) == before_apply
    assert before_apply["site_api_key"] == original["site_api_key"]


def test_verify_rejects_wrong_key_id_and_legacy_ciphertext(migration_database: str) -> None:
    _seed_all_five_legacy_ciphertexts(migration_database)
    with pytest.raises(RuntimeDataReencryptionError, match="legacy runtime data ciphertext"):
        verify_runtime_data_ciphertexts(migration_database, settings=_settings(migration_database))

    apply_runtime_data_reencryption(
        migration_database,
        settings=_settings(migration_database),
        legacy_root_secrets=(LEGACY_ROOT,),
        maintenance_confirmed=True,
    )
    wrong_key_id = Settings(
        _env_file=None,
        environment="test",
        database_url=migration_database,
        runtime_data_encryption_secret="new-runtime-data-root-secret-at-least-32b",
        runtime_data_encryption_key_id="wrong-key-id",
    )
    with pytest.raises(RuntimeDataReencryptionError, match="unsupported runtime data envelope"):
        verify_runtime_data_ciphertexts(migration_database, settings=wrong_key_id)


def test_report_contains_only_counts_and_row_identifiers(migration_database: str) -> None:
    original = _seed_all_five_legacy_ciphertexts(migration_database)
    report = dry_run_runtime_data_reencryption(
        migration_database,
        settings=_settings(migration_database),
        legacy_root_secrets=(LEGACY_ROOT,),
    ).as_dict()
    serialized = repr(report)

    assert "site_api_key:key_migration" in serialized
    assert "site-signing-secret" not in serialized
    assert LEGACY_ROOT not in serialized
    assert all(ciphertext not in serialized for ciphertext in original.values())


def test_cli_redacts_settings_validation_details_and_secret_marker(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_marker = "TOP_SECRET_MARKER"
    monkeypatch.setenv("NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET", secret_marker)

    with pytest.raises(SystemExit) as exit_info:
        reencryption_cli_main(["inventory"])

    captured = capsys.readouterr()
    assert exit_info.value.code == 1
    assert captured.out == ""
    assert captured.err == "runtime data re-encryption configuration is invalid\n"
    assert secret_marker not in captured.out
    assert secret_marker not in captured.err


def test_cli_pairs_old_key_id_with_explicit_old_root_environment(
    migration_database: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = _seed_all_five_legacy_ciphertexts(
        migration_database,
        envelope_key_id=OLD_RDE_KEY_ID,
    )
    monkeypatch.setenv("NPCINK_CLOUD_DATABASE_URL", migration_database)
    monkeypatch.setenv(
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET",
        "new-runtime-data-root-secret-at-least-32b",
    )
    monkeypatch.setenv(
        "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID",
        "runtime-key-2026-07",
    )
    monkeypatch.setenv("OLD_RUNTIME_DATA_ROOT_FOR_TEST", LEGACY_ROOT)

    assert (
        reencryption_cli_main(
            [
                "inventory",
                "--old-key-id",
                OLD_RDE_KEY_ID,
            ]
        )
        == 0
    )
    inventory_output = capsys.readouterr()
    assert '"legacy": 5' in inventory_output.out
    assert inventory_output.err == ""

    assert (
        reencryption_cli_main(
            [
                "dry-run",
                "--old-root-env",
                "OLD_RUNTIME_DATA_ROOT_FOR_TEST",
                "--old-key-id",
                OLD_RDE_KEY_ID,
            ]
        )
        == 0
    )

    captured = capsys.readouterr()
    assert '"would_migrate": 5' in captured.out
    assert LEGACY_ROOT not in captured.out
    assert captured.err == ""
    assert _read_all_five_ciphertexts(migration_database) == original


def test_migrated_ciphertexts_remain_purpose_bound(migration_database: str) -> None:
    _seed_all_five_legacy_ciphertexts(migration_database)
    settings = _settings(migration_database)
    apply_runtime_data_reencryption(
        migration_database,
        settings=settings,
        legacy_root_secrets=(LEGACY_ROOT,),
        maintenance_confirmed=True,
    )
    migrated = _read_all_five_ciphertexts(migration_database)

    assert (
        decrypt_runtime_data_plaintext(
            migrated["runtime_execution_input"],
            purpose=RUN_INPUT_PURPOSE,
            settings=settings,
        )
        == b'{"prompt":"hello"}'
    )
    with pytest.raises(RuntimeError, match="could not be decrypted"):
        decrypt_runtime_data_plaintext(
            migrated["runtime_execution_input"],
            purpose=SITE_API_KEY_PURPOSE,
            settings=settings,
        )
