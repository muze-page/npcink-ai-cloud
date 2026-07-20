"""Real PostgreSQL regression for the P1-E06 0058-to-0068 cutover.

Run explicitly against a disposable loopback PostgreSQL 16 server:

    NPCINK_CLOUD_P1_E06_POSTGRES_ADMIN_URL=\
postgresql+psycopg://postgres@127.0.0.1:55432/postgres \
      .venv/bin/python -m pytest \
      tests/integration/test_runtime_data_encryption_0058_to_0068.py -q

The test creates and drops two uniquely named databases. It never reads or
modifies the database named in the URL itself.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config as AlembicConfig
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import event, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.core.db import dispose_engine
from app.core.secrets import (
    decrypt_provider_connection_secret,
    decrypt_runtime_data_plaintext,
    decrypt_service_setting_secret,
)
from app.domain.runtime import runtime_data_reencryption as reencryption_module
from app.domain.runtime.runtime_data_reencryption import (
    ADDON_PAYLOAD_PURPOSE,
    RUNTIME_DATA_KINDS,
    SITE_API_KEY_PURPOSE,
    RuntimeDataReencryptionError,
    RuntimeDataReencryptionReport,
    apply_runtime_data_reencryption,
    dry_run_runtime_data_reencryption,
    inventory_runtime_data_ciphertexts,
    verify_runtime_data_ciphertexts,
)
from app.domain.service_secret_reencryption import (
    PROVIDER_CONNECTION_SECRET,
    SERVICE_SETTING_SECRET,
    ServiceSecretReencryptionError,
    ServiceSecretReencryptionReport,
    apply_service_secret_reencryption,
    dry_run_service_secret_reencryption,
    inventory_service_secret_ciphertexts,
    verify_service_secret_ciphertexts,
)

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DATABASE_URL = os.environ.get(
    "NPCINK_CLOUD_P1_E06_POSTGRES_ADMIN_URL",
    "",
).strip()
REVISION_0058 = "20260710_0058"
REVISION_0068 = "20260717_0068"
SITE_KEY_COUNT = 17
CURRENT_KEY_ID = "p1-e06-current"
LEGACY_RUNTIME_ROOT = base64.urlsafe_b64encode(b"L" * 32).decode()
CURRENT_RUNTIME_ROOT = base64.urlsafe_b64encode(b"R" * 32).decode()
LEGACY_SERVICE_ROOT = "legacy-service-settings-root-p1-e06-at-least-32b"
CURRENT_SERVICE_ROOT = base64.urlsafe_b64encode(b"S" * 32).decode()
CURRENT_SERVICE_KEY_ID = "p1-e06-service-current"
PROVIDER_CONNECTION_COUNT = 8
SERVICE_SETTING_COUNT = 4
SERVICE_SECRET_ENTRY_COUNT = 4
LEGACY_FERNET_KEY_BYTES = {
    (LEGACY_RUNTIME_ROOT, SITE_API_KEY_PURPOSE): bytes.fromhex(
        "54f535d0716da45179c5bc767e82da3fda1242ba47eeee567cc24d5dc8242e46"
    ),
    (LEGACY_RUNTIME_ROOT, ADDON_PAYLOAD_PURPOSE): bytes.fromhex(
        "e162351b23049bcfb970b1fb89724a5c85dd42b99ea6368dfc859a0d7cf2528b"
    ),
    (LEGACY_SERVICE_ROOT, PROVIDER_CONNECTION_SECRET): bytes.fromhex(
        "bd1aa3c79d98a4a03a0e0b7322e0402302263de4b26ff3d1fb08769c1487f41e"
    ),
    (LEGACY_SERVICE_ROOT, SERVICE_SETTING_SECRET): bytes.fromhex(
        "13de8a74236c62ead489a258cca9d859db0ec3dd6dbf3295ff7b590eecab0adb"
    ),
}

pytestmark = pytest.mark.skipif(
    not ADMIN_DATABASE_URL,
    reason=(
        "set NPCINK_CLOUD_P1_E06_POSTGRES_ADMIN_URL to a disposable "
        "loopback PostgreSQL 16 admin database"
    ),
)


@dataclass(frozen=True)
class _DisposableDatabases:
    admin_engine: Engine
    source_name: str
    recovery_name: str
    source_url: str
    recovery_url: str


@dataclass(frozen=True)
class _SeedEvidence:
    plaintext_digests: dict[tuple[str, str], bytes]
    ciphertext_fingerprint: bytes
    service_plaintexts: dict[tuple[str, str], str] = field(repr=False)
    service_ciphertext_fingerprint: bytes = field(repr=False)
    service_nonsecret_json: str


def _database_url(base: URL, database_name: str) -> str:
    return base.set(database=database_name).render_as_string(hide_password=False)


def _quoted_database_name(database_name: str) -> str:
    if not database_name.replace("_", "").isalnum():
        raise AssertionError("generated database name is not safe")
    return f'"{database_name}"'


def _terminate_database_connections(connection: sa.Connection, database_name: str) -> None:
    connection.execute(
        text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :database_name AND pid <> pg_backend_pid()"
        ),
        {"database_name": database_name},
    )


def _drop_database(connection: sa.Connection, database_name: str) -> None:
    _terminate_database_connections(connection, database_name)
    connection.execute(text(f"DROP DATABASE IF EXISTS {_quoted_database_name(database_name)}"))


@pytest.fixture
def disposable_postgres_databases() -> Iterator[_DisposableDatabases]:
    parsed = make_url(ADMIN_DATABASE_URL)
    if parsed.get_backend_name() != "postgresql":
        raise AssertionError("P1-E06 regression requires PostgreSQL")
    if parsed.host not in {"127.0.0.1", "localhost", "::1"}:
        raise AssertionError("P1-E06 regression accepts only a loopback PostgreSQL URL")

    parsed = parsed.set(drivername="postgresql+psycopg")
    suffix = secrets.token_hex(6)
    source_name = f"npcink_p1e06_source_{suffix}"
    recovery_name = f"npcink_p1e06_recovery_{suffix}"
    admin_engine = sa.create_engine(
        parsed,
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
        poolclass=NullPool,
    )
    source_url = _database_url(parsed, source_name)
    recovery_url = _database_url(parsed, recovery_name)

    with admin_engine.connect() as connection:
        server_version = int(connection.scalar(text("SHOW server_version_num")) or 0)
        assert 160000 <= server_version < 170000
        _drop_database(connection, recovery_name)
        _drop_database(connection, source_name)
        connection.execute(
            text(f"CREATE DATABASE {_quoted_database_name(source_name)} TEMPLATE template0")
        )

    databases = _DisposableDatabases(
        admin_engine=admin_engine,
        source_name=source_name,
        recovery_name=recovery_name,
        source_url=source_url,
        recovery_url=recovery_url,
    )
    try:
        yield databases
    finally:
        dispose_engine(source_url)
        get_settings.cache_clear()
        with admin_engine.connect() as connection:
            _drop_database(connection, recovery_name)
            _drop_database(connection, source_name)
        admin_engine.dispose()


def _upgrade(
    database_url: str,
    revision: str,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as isolated_environment:
        isolated_environment.setenv("NPCINK_CLOUD_DATABASE_URL", database_url)
        get_settings.cache_clear()
        config = AlembicConfig(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        command.upgrade(config, revision)
    get_settings.cache_clear()


def _legacy_fernet(root_secret: str, *, purpose: str) -> Fernet:
    derived_key = None
    for (fixture_root, fixture_purpose), fixture_key in LEGACY_FERNET_KEY_BYTES.items():
        if secrets.compare_digest(root_secret, fixture_root) and purpose == fixture_purpose:
            derived_key = fixture_key
            break
    if derived_key is None:
        raise AssertionError("legacy fixture has no matching known-answer key")
    return Fernet(base64.urlsafe_b64encode(derived_key))


def _legacy_encrypt(plaintext: bytes, *, root_secret: str, purpose: str) -> str:
    return _legacy_fernet(root_secret, purpose=purpose).encrypt(plaintext).decode("utf-8")


def _runtime_ciphertext_rows(database_url: str) -> tuple[tuple[str, str, str], ...]:
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            site_keys = connection.execute(
                text(
                    "SELECT key_id, signing_secret_ciphertext FROM site_api_keys "
                    "WHERE signing_secret_ciphertext IS NOT NULL ORDER BY key_id"
                )
            ).all()
            addon_payloads = connection.execute(
                text(
                    "SELECT state_id, metadata_json ->> 'payload_ciphertext' "
                    "FROM portal_oauth_states "
                    "WHERE metadata_json ->> 'payload_ciphertext' IS NOT NULL "
                    "ORDER BY state_id"
                )
            ).all()
        rows = [
            ("site_api_key", str(identifier), str(ciphertext))
            for identifier, ciphertext in site_keys
        ]
        rows.extend(
            ("addon_connection_payload", str(identifier), str(ciphertext))
            for identifier, ciphertext in addon_payloads
        )
        return tuple(rows)
    finally:
        engine.dispose()


def _ciphertext_fingerprint(database_url: str) -> bytes:
    digest = hashlib.sha256()
    for kind, identifier, ciphertext in _runtime_ciphertext_rows(database_url):
        digest.update(kind.encode())
        digest.update(b"\0")
        digest.update(identifier.encode())
        digest.update(b"\0")
        digest.update(ciphertext.encode())
        digest.update(b"\0")
    return digest.digest()


def _service_secret_ciphertext_rows(
    database_url: str,
) -> tuple[tuple[str, str, str, str], ...]:
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            provider_rows = connection.execute(
                text(
                    "SELECT connection_id, secret_ciphertext FROM provider_connections "
                    "WHERE secret_ciphertext IS NOT NULL AND secret_ciphertext <> '' "
                    "ORDER BY connection_id"
                )
            ).all()
            setting_rows = connection.execute(
                text(
                    "SELECT setting_id, secret_ciphertext_json FROM service_settings "
                    "ORDER BY setting_id"
                )
            ).all()
        rows = [
            (PROVIDER_CONNECTION_SECRET, str(identifier), "", str(ciphertext))
            for identifier, ciphertext in provider_rows
        ]
        for identifier, secret_map in setting_rows:
            normalized_map = secret_map if isinstance(secret_map, dict) else {}
            for entry_key in sorted(str(key) for key in normalized_map):
                ciphertext = str(normalized_map.get(entry_key) or "").strip()
                if ciphertext:
                    rows.append(
                        (
                            SERVICE_SETTING_SECRET,
                            str(identifier),
                            entry_key,
                            ciphertext,
                        )
                    )
        return tuple(sorted(rows))
    finally:
        engine.dispose()


def _service_secret_fingerprint(database_url: str) -> bytes:
    digest = hashlib.sha256()
    for kind, identifier, entry_key, ciphertext in _service_secret_ciphertext_rows(database_url):
        for value in (kind, identifier, entry_key, ciphertext):
            digest.update(value.encode())
            digest.update(b"\0")
    return digest.digest()


def _service_nonsecret_json(database_url: str) -> str:
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            providers = connection.execute(
                text(
                    "SELECT connection_id, config_json, metadata_json "
                    "FROM provider_connections ORDER BY connection_id"
                )
            ).mappings()
            settings = connection.execute(
                text(
                    "SELECT setting_id, config_json, metadata_json "
                    "FROM service_settings ORDER BY setting_id"
                )
            ).mappings()
            snapshot = {
                "providers": [dict(row) for row in providers],
                "settings": [dict(row) for row in settings],
            }
        return json.dumps(snapshot, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    finally:
        engine.dispose()


def _replace_service_setting_secret_entry(
    database_url: str,
    *,
    setting_id: str,
    entry_key: str,
    ciphertext: str,
) -> None:
    metadata = sa.MetaData()
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            service_settings = sa.Table("service_settings", metadata, autoload_with=connection)
            secret_map = connection.execute(
                sa.select(service_settings.c.secret_ciphertext_json).where(
                    service_settings.c.setting_id == setting_id
                )
            ).scalar_one()
            normalized_map = dict(secret_map) if isinstance(secret_map, dict) else {}
            normalized_map[entry_key] = ciphertext
            connection.execute(
                service_settings.update()
                .where(service_settings.c.setting_id == setting_id)
                .values(secret_ciphertext_json=normalized_map)
            )
    finally:
        engine.dispose()


def _service_setting_secret_map(database_url: str, *, setting_id: str) -> dict[str, object]:
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            secret_map = connection.scalar(
                text(
                    "SELECT secret_ciphertext_json FROM service_settings "
                    "WHERE setting_id = :setting_id"
                ),
                {"setting_id": setting_id},
            )
        return dict(secret_map) if isinstance(secret_map, dict) else {}
    finally:
        engine.dispose()


def _seed_0058_production_shape(database_url: str, *, legacy_root: str) -> _SeedEvidence:
    now = datetime.now(UTC)
    metadata = sa.MetaData()
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    plaintext_digests: dict[tuple[str, str], bytes] = {}
    service_plaintexts: dict[tuple[str, str], str] = {}
    try:
        with engine.begin() as connection:
            sites = sa.Table("sites", metadata, autoload_with=connection)
            site_api_keys = sa.Table("site_api_keys", metadata, autoload_with=connection)
            portal_oauth_states = sa.Table(
                "portal_oauth_states",
                metadata,
                autoload_with=connection,
            )
            run_records = sa.Table("run_records", metadata, autoload_with=connection)
            legacy_media = sa.Table(
                "media_derivative_artifacts",
                metadata,
                autoload_with=connection,
            )
            legacy_audio = sa.Table("audio_assets", metadata, autoload_with=connection)
            provider_connections = sa.Table(
                "provider_connections",
                metadata,
                autoload_with=connection,
            )
            service_settings = sa.Table(
                "service_settings",
                metadata,
                autoload_with=connection,
            )

            site_rows: list[dict[str, object]] = []
            key_rows: list[dict[str, object]] = []
            for index in range(SITE_KEY_COUNT):
                site_id = f"site_p1e06_{index:02d}"
                key_id = f"key_p1e06_{index:02d}"
                plaintext = secrets.token_bytes(32)
                plaintext_digests[("site_api_key", key_id)] = hashlib.sha256(plaintext).digest()
                site_rows.append(
                    {
                        "site_id": site_id,
                        "name": f"P1-E06 site {index:02d}",
                        "status": "active",
                        "metadata_json": {
                            "site_url": f"https://p1e06-{index:02d}.example.test"
                        },
                    }
                )
                key_rows.append(
                    {
                        "key_id": key_id,
                        "site_id": site_id,
                        "secret_hash": hashlib.sha256(plaintext).hexdigest(),
                        "signing_secret_ciphertext": _legacy_encrypt(
                            plaintext,
                            root_secret=legacy_root,
                            purpose=SITE_API_KEY_PURPOSE,
                        ),
                        "status": "active",
                    }
                )
            connection.execute(sites.insert(), site_rows)
            connection.execute(site_api_keys.insert(), key_rows)

            addon_state_id = "oauth_p1e06_addon"
            addon_plaintext = json.dumps(
                {
                    "api_key": secrets.token_urlsafe(32),
                    "site_id": "site_p1e06_00",
                    "site_url": "https://p1e06-00.example.test",
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            plaintext_digests[("addon_connection_payload", addon_state_id)] = hashlib.sha256(
                addon_plaintext
            ).digest()
            connection.execute(
                portal_oauth_states.insert().values(
                    state_id=addon_state_id,
                    provider="wordpress_addon_connection",
                    state_hash=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
                    status="pending",
                    expires_at=now + timedelta(hours=1),
                    metadata_json={
                        "payload_ciphertext": _legacy_encrypt(
                            addon_plaintext,
                            root_secret=legacy_root,
                            purpose=ADDON_PAYLOAD_PURPOSE,
                        )
                    },
                )
            )

            provider_specs = (
                ("provider_p1e06_openai", "openai_compatible"),
                ("provider_p1e06_anthropic", "anthropic"),
                ("provider_p1e06_openrouter", "openrouter"),
                ("provider_p1e06_siliconflow", "siliconflow"),
                ("provider_p1e06_minimax", "minimax"),
                ("provider_p1e06_tavily", "tavily"),
                ("provider_p1e06_bocha", "bocha"),
                ("provider_p1e06_apify", "apify"),
            )
            provider_rows: list[dict[str, object]] = []
            for index, (connection_id, provider_type) in enumerate(provider_specs):
                plaintext = secrets.token_urlsafe(32)
                service_plaintexts[(PROVIDER_CONNECTION_SECRET, connection_id)] = plaintext
                provider_rows.append(
                    {
                        "connection_id": connection_id,
                        "provider_type": provider_type,
                        "display_name": f"P1-E06 provider {index:02d}",
                        "enabled": True,
                        "base_url": f"https://provider-{index:02d}.example.test",
                        "config_json": {"preserve": {"provider": connection_id}},
                        "secret_ciphertext": _legacy_encrypt(
                            plaintext.encode(),
                            root_secret=LEGACY_SERVICE_ROOT,
                            purpose=PROVIDER_CONNECTION_SECRET,
                        ),
                        "status": "ready",
                        "source_role": "execution_source",
                        "metadata_json": {"preserve": {"provider_index": index}},
                    }
                )
            connection.execute(provider_connections.insert(), provider_rows)

            setting_specs = (
                (
                    "payment_alipay",
                    "payment",
                    ("private_key", "public_key"),
                ),
                ("portal_email", "portal", ("smtp_password",)),
                ("portal_qq_login", "portal", ("client_secret",)),
                ("portal_public", "portal", ()),
            )
            setting_rows: list[dict[str, object]] = []
            for index, (setting_id, setting_kind, entry_keys) in enumerate(setting_specs):
                secret_map: dict[str, str] = {}
                for entry_key in entry_keys:
                    plaintext = secrets.token_urlsafe(32)
                    service_plaintexts[
                        (SERVICE_SETTING_SECRET, f"{setting_id}:{entry_key}")
                    ] = plaintext
                    secret_map[entry_key] = _legacy_encrypt(
                        plaintext.encode(),
                        root_secret=LEGACY_SERVICE_ROOT,
                        purpose=SERVICE_SETTING_SECRET,
                    )
                setting_rows.append(
                    {
                        "setting_id": setting_id,
                        "setting_kind": setting_kind,
                        "enabled": True,
                        "config_json": {"preserve": {"setting": setting_id}},
                        "secret_ciphertext_json": secret_map,
                        "status": "ready",
                        "metadata_json": {"preserve": {"setting_index": index}},
                    }
                )
            connection.execute(service_settings.insert(), setting_rows)

            connection.execute(
                run_records.insert().values(
                    run_id="run_p1e06_media",
                    site_id="site_p1e06_00",
                    ability_name="media.transform",
                    channel="integration_test",
                    execution_kind="sync",
                    profile_id="media.balanced",
                    status="succeeded",
                    trace_id="0123456789abcdef0123456789abcdef",
                )
            )
            legacy_media_bytes = b"p1-e06-legacy-media-row"
            connection.execute(
                legacy_media.insert().values(
                    artifact_id="legacy_media_p1e06",
                    run_id="run_p1e06_media",
                    site_id="site_p1e06_00",
                    storage_ref="legacy://media/p1e06",
                    blob_data=legacy_media_bytes,
                    mime_type="image/png",
                    format="png",
                    checksum=hashlib.sha256(legacy_media_bytes).hexdigest(),
                    expires_at=now + timedelta(days=1),
                )
            )
            legacy_audio_bytes = b"p1-e06-legacy-audio-row"
            connection.execute(
                legacy_audio.insert().values(
                    asset_id="legacy_audio_p1e06",
                    site_id="site_p1e06_00",
                    storage_ref="legacy://audio/p1e06",
                    blob_data=legacy_audio_bytes,
                    mime_type="audio/mpeg",
                    format="mp3",
                    checksum=hashlib.sha256(legacy_audio_bytes).hexdigest(),
                )
            )
    finally:
        engine.dispose()
    return _SeedEvidence(
        plaintext_digests=plaintext_digests,
        ciphertext_fingerprint=_ciphertext_fingerprint(database_url),
        service_plaintexts=service_plaintexts,
        service_ciphertext_fingerprint=_service_secret_fingerprint(database_url),
        service_nonsecret_json=_service_nonsecret_json(database_url),
    )


def _assert_0058_recovery_state(
    database_url: str,
    *,
    expected_fingerprint: bytes,
    expected_service_fingerprint: bytes,
) -> None:
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION_0058
            )
            assert connection.scalar(text("SELECT count(*) FROM site_api_keys")) == SITE_KEY_COUNT
            assert connection.scalar(text("SELECT count(*) FROM portal_oauth_states")) == 1
            assert (
                connection.scalar(text("SELECT count(*) FROM provider_connections"))
                == PROVIDER_CONNECTION_COUNT
            )
            assert (
                connection.scalar(text("SELECT count(*) FROM service_settings"))
                == SERVICE_SETTING_COUNT
            )
            assert connection.scalar(text("SELECT count(*) FROM media_derivative_artifacts")) == 1
            assert connection.scalar(text("SELECT count(*) FROM audio_assets")) == 1
    finally:
        engine.dispose()
    assert secrets.compare_digest(
        _ciphertext_fingerprint(database_url),
        expected_fingerprint,
    )
    assert secrets.compare_digest(
        _service_secret_fingerprint(database_url),
        expected_service_fingerprint,
    )


def _create_and_verify_0058_recovery_copy(
    databases: _DisposableDatabases,
    *,
    expected_fingerprint: bytes,
    expected_service_fingerprint: bytes,
) -> None:
    with databases.admin_engine.connect() as connection:
        _terminate_database_connections(connection, databases.source_name)
        connection.execute(
            text(
                f"CREATE DATABASE {_quoted_database_name(databases.recovery_name)} "
                f"TEMPLATE {_quoted_database_name(databases.source_name)}"
            )
        )
    _assert_0058_recovery_state(
        databases.recovery_url,
        expected_fingerprint=expected_fingerprint,
        expected_service_fingerprint=expected_service_fingerprint,
    )


def _assert_0068_artifact_reset(database_url: str) -> None:
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        inspector = sa.inspect(engine)
        tables = set(inspector.get_table_names())
        assert "media_derivative_artifacts" not in tables
        assert "audio_assets" not in tables
        assert "media_artifacts" in tables
        assert "media_artifact_deliveries" in tables
        artifact_columns = {
            str(column["name"]) for column in inspector.get_columns("media_artifacts")
        }
        assert {
            "artifact_id",
            "content_type",
            "byte_size",
            "storage_key",
            "purge_claim_id",
            "purge_claim_expires_at",
        } <= artifact_columns
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION_0068
            )
            assert connection.scalar(text("SELECT count(*) FROM media_artifacts")) == 0
    finally:
        engine.dispose()


def _assert_legacy_plaintexts_are_maintenance_readable(
    database_url: str,
    *,
    legacy_root: str,
    expected_digests: dict[tuple[str, str], bytes],
) -> None:
    for kind, identifier, ciphertext in _runtime_ciphertext_rows(database_url):
        purpose = SITE_API_KEY_PURPOSE if kind == "site_api_key" else ADDON_PAYLOAD_PURPOSE
        plaintext = _legacy_fernet(legacy_root, purpose=purpose).decrypt(ciphertext.encode())
        assert secrets.compare_digest(
            hashlib.sha256(plaintext).digest(),
            expected_digests[(kind, identifier)],
        )


def _assert_current_plaintexts_are_runtime_readable(
    database_url: str,
    *,
    settings: Settings,
    expected_digests: dict[tuple[str, str], bytes],
) -> None:
    for kind, identifier, ciphertext in _runtime_ciphertext_rows(database_url):
        purpose = SITE_API_KEY_PURPOSE if kind == "site_api_key" else ADDON_PAYLOAD_PURPOSE
        plaintext = decrypt_runtime_data_plaintext(
            ciphertext,
            purpose=purpose,
            settings=settings,
        )
        assert secrets.compare_digest(
            hashlib.sha256(plaintext).digest(),
            expected_digests[(kind, identifier)],
        )


def _runtime_settings(database_url: str, *, current_root: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        service_settings_secret=CURRENT_SERVICE_ROOT,
        service_settings_encryption_key_id=CURRENT_SERVICE_KEY_ID,
        runtime_data_encryption_secret=current_root,
        runtime_data_encryption_key_id=CURRENT_KEY_ID,
    )


def _assert_exact_production_inventory(report: RuntimeDataReencryptionReport) -> None:
    assert report.total == 18
    assert report.legacy == 18
    assert report.current == 0
    assert report.counts_by_kind["site_api_key"]["total"] == SITE_KEY_COUNT
    assert report.counts_by_kind["addon_connection_payload"]["total"] == 1
    for kind in set(RUNTIME_DATA_KINDS) - {"site_api_key", "addon_connection_payload"}:
        assert report.counts_by_kind[kind]["total"] == 0


def _assert_exact_service_inventory(report: ServiceSecretReencryptionReport) -> None:
    assert (report.total, report.legacy, report.current) == (
        PROVIDER_CONNECTION_COUNT + SERVICE_SECRET_ENTRY_COUNT,
        PROVIDER_CONNECTION_COUNT + SERVICE_SECRET_ENTRY_COUNT,
        0,
    )
    assert report.counts_by_kind[PROVIDER_CONNECTION_SECRET]["total"] == (
        PROVIDER_CONNECTION_COUNT
    )
    assert report.counts_by_kind[SERVICE_SETTING_SECRET]["total"] == (
        SERVICE_SECRET_ENTRY_COUNT
    )


def _service_plaintext_key(kind: str, identifier: str, entry_key: str) -> tuple[str, str]:
    if kind == PROVIDER_CONNECTION_SECRET:
        return kind, identifier
    return kind, f"{identifier}:{entry_key}"


def _assert_current_service_plaintexts_are_readable(
    database_url: str,
    *,
    settings: Settings,
    expected_plaintexts: dict[tuple[str, str], str],
) -> None:
    for kind, identifier, entry_key, ciphertext in _service_secret_ciphertext_rows(database_url):
        if kind == PROVIDER_CONNECTION_SECRET:
            plaintext = decrypt_provider_connection_secret(ciphertext, settings=settings)
        else:
            plaintext = decrypt_service_setting_secret(ciphertext, settings=settings)
        expected = expected_plaintexts[_service_plaintext_key(kind, identifier, entry_key)]
        if not secrets.compare_digest(plaintext, expected):
            raise AssertionError(f"service plaintext mismatch for {kind}:{identifier}:{entry_key}")


def _assert_normal_runtime_rejects_legacy_and_unknown_service_ciphertexts(
    database_url: str,
    *,
    settings: Settings,
) -> None:
    rows = _service_secret_ciphertext_rows(database_url)
    provider_ciphertext = next(row[3] for row in rows if row[0] == PROVIDER_CONNECTION_SECRET)
    setting_ciphertext = next(row[3] for row in rows if row[0] == SERVICE_SETTING_SECRET)
    with pytest.raises(RuntimeError):
        decrypt_provider_connection_secret(provider_ciphertext, settings=settings)
    with pytest.raises(RuntimeError):
        decrypt_service_setting_secret(setting_ciphertext, settings=settings)
    with pytest.raises(RuntimeError):
        decrypt_provider_connection_secret(
            f"sse.v1.unknown-service-key.{provider_ciphertext}",
            settings=settings,
        )
    with pytest.raises(RuntimeError):
        decrypt_service_setting_secret(
            f"sse.v1.unknown-service-key.{setting_ciphertext}",
            settings=settings,
        )


def _assert_service_reports_redact_sensitive_material(
    reports: tuple[ServiceSecretReencryptionReport, ...],
    *,
    sensitive_values: tuple[str, ...],
) -> None:
    serialized = repr(tuple(report.as_dict() for report in reports))
    if any(value and value in serialized for value in sensitive_values):
        raise AssertionError("service secret migration report exposed sensitive fixture material")


def _run_maintenance_cli(
    module: str,
    *arguments: str,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module, *arguments],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _assert_successful_cli_report(
    completed: subprocess.CompletedProcess[str],
    *,
    mode: str,
    expected_counts: tuple[int, int, int, int, int],
) -> dict[str, object]:
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    report = json.loads(completed.stdout)
    assert isinstance(report, dict)
    assert set(report) == {
        "mode",
        "total",
        "legacy",
        "current",
        "migrated",
        "would_migrate",
        "counts_by_kind",
        "row_identifiers",
    }
    assert report["mode"] == mode
    assert tuple(
        int(report[key])
        for key in ("total", "legacy", "current", "migrated", "would_migrate")
    ) == expected_counts
    row_identifiers = report["row_identifiers"]
    assert isinstance(row_identifiers, list)
    assert len(row_identifiers) == expected_counts[0]
    assert len(set(row_identifiers)) == expected_counts[0]
    assert isinstance(report["counts_by_kind"], dict)
    return report


def test_postgresql_0058_to_0068_runtime_data_encryption_cutover(
    disposable_postgres_databases: _DisposableDatabases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    databases = disposable_postgres_databases
    legacy_root = LEGACY_RUNTIME_ROOT
    current_root = CURRENT_RUNTIME_ROOT

    _upgrade(databases.source_url, REVISION_0058, monkeypatch=monkeypatch)
    seeded = _seed_0058_production_shape(databases.source_url, legacy_root=legacy_root)
    _assert_0058_recovery_state(
        databases.source_url,
        expected_fingerprint=seeded.ciphertext_fingerprint,
        expected_service_fingerprint=seeded.service_ciphertext_fingerprint,
    )
    _create_and_verify_0058_recovery_copy(
        databases,
        expected_fingerprint=seeded.ciphertext_fingerprint,
        expected_service_fingerprint=seeded.service_ciphertext_fingerprint,
    )

    _upgrade(databases.source_url, REVISION_0068, monkeypatch=monkeypatch)
    _assert_0068_artifact_reset(databases.source_url)
    settings = _runtime_settings(databases.source_url, current_root=current_root)

    inventory = inventory_runtime_data_ciphertexts(
        databases.source_url,
        settings=settings,
    )
    _assert_exact_production_inventory(inventory)
    _assert_legacy_plaintexts_are_maintenance_readable(
        databases.source_url,
        legacy_root=legacy_root,
        expected_digests=seeded.plaintext_digests,
    )
    first_legacy_ciphertext = _runtime_ciphertext_rows(databases.source_url)[0][2]
    with pytest.raises(RuntimeError):
        decrypt_runtime_data_plaintext(
            first_legacy_ciphertext,
            purpose=SITE_API_KEY_PURPOSE,
            settings=settings,
        )
    with pytest.raises(RuntimeDataReencryptionError, match="legacy runtime data ciphertext"):
        verify_runtime_data_ciphertexts(databases.source_url, settings=settings)
    with pytest.raises(RuntimeDataReencryptionError, match="maintenance window"):
        apply_runtime_data_reencryption(
            databases.source_url,
            settings=settings,
            legacy_root_secrets=(legacy_root,),
            maintenance_confirmed=False,
        )

    dry_run = dry_run_runtime_data_reencryption(
        databases.source_url,
        settings=settings,
        legacy_root_secrets=(legacy_root,),
    )
    assert (dry_run.total, dry_run.legacy, dry_run.current) == (18, 18, 0)
    assert (dry_run.would_migrate, dry_run.migrated) == (18, 0)
    assert secrets.compare_digest(
        _ciphertext_fingerprint(databases.source_url),
        seeded.ciphertext_fingerprint,
    )

    rollback_hook_fired = False
    real_get_session = reencryption_module.get_session

    @contextmanager
    def fail_after_postgresql_flush(database_url: str) -> Iterator[Session]:
        nonlocal rollback_hook_fired
        with real_get_session(database_url) as session:

            def raise_after_flush(_session: Session, _flush_context: object) -> None:
                nonlocal rollback_hook_fired
                rollback_hook_fired = True
                raise RuntimeError("injected integration transaction failure")

            event.listen(session, "after_flush_postexec", raise_after_flush, once=True)
            yield session

    with monkeypatch.context() as transaction_failure:
        transaction_failure.setattr(
            reencryption_module,
            "get_session",
            fail_after_postgresql_flush,
        )
        with pytest.raises(RuntimeDataReencryptionError, match="re-encryption failed"):
            apply_runtime_data_reencryption(
                databases.source_url,
                settings=settings,
                legacy_root_secrets=(legacy_root,),
                maintenance_confirmed=True,
            )
    assert rollback_hook_fired is True
    assert secrets.compare_digest(
        _ciphertext_fingerprint(databases.source_url),
        seeded.ciphertext_fingerprint,
    )
    _assert_exact_production_inventory(
        inventory_runtime_data_ciphertexts(databases.source_url, settings=settings)
    )

    applied = apply_runtime_data_reencryption(
        databases.source_url,
        settings=settings,
        legacy_root_secrets=(legacy_root,),
        maintenance_confirmed=True,
    )
    assert (applied.total, applied.legacy, applied.current, applied.migrated) == (18, 0, 18, 18)
    verified = verify_runtime_data_ciphertexts(databases.source_url, settings=settings)
    assert (verified.total, verified.legacy, verified.current) == (18, 0, 18)
    assert all(
        ciphertext.startswith(f"rde.v1.{CURRENT_KEY_ID}.")
        for _kind, _identifier, ciphertext in _runtime_ciphertext_rows(databases.source_url)
    )
    _assert_current_plaintexts_are_runtime_readable(
        databases.source_url,
        settings=settings,
        expected_digests=seeded.plaintext_digests,
    )
    current_ciphertext = _runtime_ciphertext_rows(databases.source_url)[0][2]
    with pytest.raises(InvalidToken):
        _legacy_fernet(legacy_root, purpose=SITE_API_KEY_PURPOSE).decrypt(
            current_ciphertext.encode()
        )

    runtime_current_fingerprint = _ciphertext_fingerprint(databases.source_url)
    assert secrets.compare_digest(
        _service_secret_fingerprint(databases.source_url),
        seeded.service_ciphertext_fingerprint,
    )
    assert _service_nonsecret_json(databases.source_url) == seeded.service_nonsecret_json

    raw_service_rows = _service_secret_ciphertext_rows(databases.source_url)
    assert len(raw_service_rows) == PROVIDER_CONNECTION_COUNT + SERVICE_SECRET_ENTRY_COUNT
    _assert_normal_runtime_rejects_legacy_and_unknown_service_ciphertexts(
        databases.source_url,
        settings=settings,
    )
    service_inventory = inventory_service_secret_ciphertexts(
        databases.source_url,
        settings=settings,
    )
    _assert_exact_service_inventory(service_inventory)
    with pytest.raises(ServiceSecretReencryptionError, match="legacy service secret ciphertext"):
        verify_service_secret_ciphertexts(databases.source_url, settings=settings)

    service_dry_run = dry_run_service_secret_reencryption(
        databases.source_url,
        settings=settings,
        legacy_root_secrets=(LEGACY_SERVICE_ROOT,),
    )
    assert (
        service_dry_run.total,
        service_dry_run.legacy,
        service_dry_run.current,
        service_dry_run.would_migrate,
        service_dry_run.migrated,
    ) == (12, 12, 0, 12, 0)
    assert secrets.compare_digest(
        _service_secret_fingerprint(databases.source_url),
        seeded.service_ciphertext_fingerprint,
    )

    corrupt_setting_id = "payment_alipay"
    corrupt_entry_key = "public_key"
    original_corrupt_ciphertext = next(
        ciphertext
        for kind, identifier, entry_key, ciphertext in raw_service_rows
        if kind == SERVICE_SETTING_SECRET
        and identifier == corrupt_setting_id
        and entry_key == corrupt_entry_key
    )
    _replace_service_setting_secret_entry(
        databases.source_url,
        setting_id=corrupt_setting_id,
        entry_key=corrupt_entry_key,
        ciphertext="corrupt-legacy-service-token",
    )
    corrupt_service_fingerprint = _service_secret_fingerprint(databases.source_url)
    with pytest.raises(ServiceSecretReencryptionError, match="payment_alipay:public_key"):
        apply_service_secret_reencryption(
            databases.source_url,
            settings=settings,
            legacy_root_secrets=(LEGACY_SERVICE_ROOT,),
            maintenance_confirmed=True,
        )
    assert secrets.compare_digest(
        _service_secret_fingerprint(databases.source_url),
        corrupt_service_fingerprint,
    )
    if any(
        ciphertext.startswith("sse.")
        for _kind, _identifier, _entry_key, ciphertext in _service_secret_ciphertext_rows(
            databases.source_url
        )
    ):
        raise AssertionError("failed service apply left a partially migrated envelope")
    _replace_service_setting_secret_entry(
        databases.source_url,
        setting_id=corrupt_setting_id,
        entry_key=corrupt_entry_key,
        ciphertext=original_corrupt_ciphertext,
    )
    assert secrets.compare_digest(
        _service_secret_fingerprint(databases.source_url),
        seeded.service_ciphertext_fingerprint,
    )

    service_applied = apply_service_secret_reencryption(
        databases.source_url,
        settings=settings,
        legacy_root_secrets=(LEGACY_SERVICE_ROOT,),
        maintenance_confirmed=True,
    )
    assert (
        service_applied.total,
        service_applied.legacy,
        service_applied.current,
        service_applied.migrated,
    ) == (12, 0, 12, 12)
    service_verified = verify_service_secret_ciphertexts(
        databases.source_url,
        settings=settings,
    )
    assert (
        service_verified.total,
        service_verified.legacy,
        service_verified.current,
    ) == (12, 0, 12)
    current_service_rows = _service_secret_ciphertext_rows(databases.source_url)
    if not all(
        ciphertext.startswith(f"sse.v1.{CURRENT_SERVICE_KEY_ID}.")
        for _kind, _identifier, _entry_key, ciphertext in current_service_rows
    ):
        raise AssertionError("service apply did not produce only active sse.v1 envelopes")
    _assert_current_service_plaintexts_are_readable(
        databases.source_url,
        settings=settings,
        expected_plaintexts=seeded.service_plaintexts,
    )
    assert _service_nonsecret_json(databases.source_url) == seeded.service_nonsecret_json
    if _service_setting_secret_map(databases.source_url, setting_id="portal_public"):
        raise AssertionError("service apply changed an intentionally empty secret map")
    assert secrets.compare_digest(
        _ciphertext_fingerprint(databases.source_url),
        runtime_current_fingerprint,
    )
    _assert_service_reports_redact_sensitive_material(
        (service_inventory, service_dry_run, service_applied, service_verified),
        sensitive_values=(
            LEGACY_SERVICE_ROOT,
            CURRENT_SERVICE_ROOT,
            *seeded.service_plaintexts.values(),
            *(row[3] for row in raw_service_rows),
            *(row[3] for row in current_service_rows),
        ),
    )

    _assert_0058_recovery_state(
        databases.recovery_url,
        expected_fingerprint=seeded.ciphertext_fingerprint,
        expected_service_fingerprint=seeded.service_ciphertext_fingerprint,
    )


def test_postgresql_maintenance_clis_execute_both_encryption_cutovers_as_subprocesses(
    disposable_postgres_databases: _DisposableDatabases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    databases = disposable_postgres_databases
    _upgrade(databases.source_url, REVISION_0058, monkeypatch=monkeypatch)
    seeded = _seed_0058_production_shape(
        databases.source_url,
        legacy_root=LEGACY_RUNTIME_ROOT,
    )
    _upgrade(databases.source_url, REVISION_0068, monkeypatch=monkeypatch)
    _assert_0068_artifact_reset(databases.source_url)

    runtime_old_root_env = "NPCINK_CLOUD_P1_E06_RUNTIME_OLD_ROOT_FOR_TEST"
    service_old_root_env = "NPCINK_CLOUD_P1_E06_SERVICE_OLD_ROOT_FOR_TEST"
    cli_environment = os.environ.copy()
    cli_environment.update(
        {
            "NPCINK_CLOUD_ENVIRONMENT": "test",
            "NPCINK_CLOUD_DATABASE_URL": databases.source_url,
            "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_SECRET": CURRENT_RUNTIME_ROOT,
            "NPCINK_CLOUD_RUNTIME_DATA_ENCRYPTION_KEY_ID": CURRENT_KEY_ID,
            "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET": CURRENT_SERVICE_ROOT,
            "NPCINK_CLOUD_SERVICE_SETTINGS_ENCRYPTION_KEY_ID": CURRENT_SERVICE_KEY_ID,
            runtime_old_root_env: LEGACY_RUNTIME_ROOT,
            service_old_root_env: LEGACY_SERVICE_ROOT,
        }
    )
    runtime_module = "app.dev.reencrypt_runtime_data"
    service_module = "app.dev.reencrypt_service_secrets"
    completed_processes: list[subprocess.CompletedProcess[str]] = []

    for module in (runtime_module, service_module):
        invalid_arguments = _run_maintenance_cli(
            module,
            "inventory",
            "--unsupported-argument",
            environment=cli_environment,
        )
        completed_processes.append(invalid_arguments)
        assert invalid_arguments.returncode == 2
        assert invalid_arguments.stdout == ""
        assert "unrecognized arguments: --unsupported-argument" in invalid_arguments.stderr

        missing_old_root = _run_maintenance_cli(
            module,
            "dry-run",
            "--old-root-env",
            "NPCINK_CLOUD_P1_E06_MISSING_OLD_ROOT_FOR_TEST",
            environment=cli_environment,
        )
        completed_processes.append(missing_old_root)
        assert missing_old_root.returncode == 1
        assert missing_old_root.stdout == ""
        assert "old root environment variable is missing or empty" in missing_old_root.stderr

    runtime_inventory_process = _run_maintenance_cli(
        runtime_module,
        "inventory",
        environment=cli_environment,
    )
    completed_processes.append(runtime_inventory_process)
    runtime_inventory = _assert_successful_cli_report(
        runtime_inventory_process,
        mode="inventory",
        expected_counts=(18, 18, 0, 0, 18),
    )
    assert set(runtime_inventory["counts_by_kind"]) == set(RUNTIME_DATA_KINDS)

    service_inventory_process = _run_maintenance_cli(
        service_module,
        "inventory",
        environment=cli_environment,
    )
    completed_processes.append(service_inventory_process)
    service_inventory = _assert_successful_cli_report(
        service_inventory_process,
        mode="inventory",
        expected_counts=(12, 12, 0, 0, 12),
    )
    assert set(service_inventory["counts_by_kind"]) == {
        PROVIDER_CONNECTION_SECRET,
        SERVICE_SETTING_SECRET,
    }

    for module, expected_error in (
        (runtime_module, "legacy runtime data ciphertext remains"),
        (service_module, "legacy service secret ciphertext remains"),
    ):
        rejected_verify = _run_maintenance_cli(
            module,
            "verify",
            environment=cli_environment,
        )
        completed_processes.append(rejected_verify)
        assert rejected_verify.returncode == 1
        assert rejected_verify.stdout == ""
        assert expected_error in rejected_verify.stderr

    runtime_dry_run_process = _run_maintenance_cli(
        runtime_module,
        "dry-run",
        "--old-root-env",
        runtime_old_root_env,
        environment=cli_environment,
    )
    completed_processes.append(runtime_dry_run_process)
    _assert_successful_cli_report(
        runtime_dry_run_process,
        mode="dry-run",
        expected_counts=(18, 18, 0, 0, 18),
    )

    service_dry_run_process = _run_maintenance_cli(
        service_module,
        "dry-run",
        "--old-root-env",
        service_old_root_env,
        environment=cli_environment,
    )
    completed_processes.append(service_dry_run_process)
    _assert_successful_cli_report(
        service_dry_run_process,
        mode="dry-run",
        expected_counts=(12, 12, 0, 0, 12),
    )
    assert secrets.compare_digest(
        _ciphertext_fingerprint(databases.source_url),
        seeded.ciphertext_fingerprint,
    )
    assert secrets.compare_digest(
        _service_secret_fingerprint(databases.source_url),
        seeded.service_ciphertext_fingerprint,
    )

    for module, old_root_env in (
        (runtime_module, runtime_old_root_env),
        (service_module, service_old_root_env),
    ):
        rejected_apply = _run_maintenance_cli(
            module,
            "apply",
            "--old-root-env",
            old_root_env,
            environment=cli_environment,
        )
        completed_processes.append(rejected_apply)
        assert rejected_apply.returncode == 1
        assert rejected_apply.stdout == ""
        assert "maintenance window" in rejected_apply.stderr
    assert secrets.compare_digest(
        _ciphertext_fingerprint(databases.source_url),
        seeded.ciphertext_fingerprint,
    )
    assert secrets.compare_digest(
        _service_secret_fingerprint(databases.source_url),
        seeded.service_ciphertext_fingerprint,
    )

    runtime_apply_process = _run_maintenance_cli(
        runtime_module,
        "apply",
        "--confirm-maintenance-window",
        "--old-root-env",
        runtime_old_root_env,
        environment=cli_environment,
    )
    completed_processes.append(runtime_apply_process)
    _assert_successful_cli_report(
        runtime_apply_process,
        mode="apply",
        expected_counts=(18, 0, 18, 18, 18),
    )
    runtime_current_fingerprint = _ciphertext_fingerprint(databases.source_url)
    assert not secrets.compare_digest(
        runtime_current_fingerprint,
        seeded.ciphertext_fingerprint,
    )
    assert secrets.compare_digest(
        _service_secret_fingerprint(databases.source_url),
        seeded.service_ciphertext_fingerprint,
    )

    runtime_verify_process = _run_maintenance_cli(
        runtime_module,
        "verify",
        environment=cli_environment,
    )
    completed_processes.append(runtime_verify_process)
    _assert_successful_cli_report(
        runtime_verify_process,
        mode="verify",
        expected_counts=(18, 0, 18, 0, 0),
    )

    service_apply_process = _run_maintenance_cli(
        service_module,
        "apply",
        "--confirm-maintenance-window",
        "--old-root-env",
        service_old_root_env,
        environment=cli_environment,
    )
    completed_processes.append(service_apply_process)
    _assert_successful_cli_report(
        service_apply_process,
        mode="apply",
        expected_counts=(12, 0, 12, 12, 12),
    )
    assert secrets.compare_digest(
        _ciphertext_fingerprint(databases.source_url),
        runtime_current_fingerprint,
    )

    service_verify_process = _run_maintenance_cli(
        service_module,
        "verify",
        environment=cli_environment,
    )
    completed_processes.append(service_verify_process)
    _assert_successful_cli_report(
        service_verify_process,
        mode="verify",
        expected_counts=(12, 0, 12, 0, 0),
    )

    settings = _runtime_settings(
        databases.source_url,
        current_root=CURRENT_RUNTIME_ROOT,
    )
    _assert_current_plaintexts_are_runtime_readable(
        databases.source_url,
        settings=settings,
        expected_digests=seeded.plaintext_digests,
    )
    _assert_current_service_plaintexts_are_readable(
        databases.source_url,
        settings=settings,
        expected_plaintexts=seeded.service_plaintexts,
    )
    assert _service_nonsecret_json(databases.source_url) == seeded.service_nonsecret_json

    combined_cli_output = "".join(
        completed.stdout + completed.stderr for completed in completed_processes
    )
    sensitive_values = (
        LEGACY_RUNTIME_ROOT,
        CURRENT_RUNTIME_ROOT,
        LEGACY_SERVICE_ROOT,
        CURRENT_SERVICE_ROOT,
        *seeded.service_plaintexts.values(),
    )
    assert all(value not in combined_cli_output for value in sensitive_values)
