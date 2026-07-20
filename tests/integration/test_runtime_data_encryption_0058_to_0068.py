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
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
from app.core.secrets import decrypt_runtime_data_plaintext
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

ROOT = Path(__file__).resolve().parents[2]
ADMIN_DATABASE_URL = os.environ.get(
    "NPCINK_CLOUD_P1_E06_POSTGRES_ADMIN_URL",
    "",
).strip()
REVISION_0058 = "20260710_0058"
REVISION_0068 = "20260717_0068"
SITE_KEY_COUNT = 17
CURRENT_KEY_ID = "p1-e06-current"

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
    derived_key = hashlib.sha256(f"{purpose}:{root_secret}".encode()).digest()
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


def _seed_0058_production_shape(database_url: str, *, legacy_root: str) -> _SeedEvidence:
    now = datetime.now(UTC)
    metadata = sa.MetaData()
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    plaintext_digests: dict[tuple[str, str], bytes] = {}
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
    )


def _assert_0058_recovery_state(database_url: str, *, expected_fingerprint: bytes) -> None:
    engine = sa.create_engine(database_url, hide_parameters=True, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == REVISION_0058
            )
            assert connection.scalar(text("SELECT count(*) FROM site_api_keys")) == SITE_KEY_COUNT
            assert connection.scalar(text("SELECT count(*) FROM portal_oauth_states")) == 1
            assert connection.scalar(text("SELECT count(*) FROM media_derivative_artifacts")) == 1
            assert connection.scalar(text("SELECT count(*) FROM audio_assets")) == 1
    finally:
        engine.dispose()
    assert secrets.compare_digest(
        _ciphertext_fingerprint(database_url),
        expected_fingerprint,
    )


def _create_and_verify_0058_recovery_copy(
    databases: _DisposableDatabases,
    *,
    expected_fingerprint: bytes,
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


def test_postgresql_0058_to_0068_runtime_data_encryption_cutover(
    disposable_postgres_databases: _DisposableDatabases,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    databases = disposable_postgres_databases
    legacy_root = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    current_root = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()

    _upgrade(databases.source_url, REVISION_0058, monkeypatch=monkeypatch)
    seeded = _seed_0058_production_shape(databases.source_url, legacy_root=legacy_root)
    _assert_0058_recovery_state(
        databases.source_url,
        expected_fingerprint=seeded.ciphertext_fingerprint,
    )
    _create_and_verify_0058_recovery_copy(
        databases,
        expected_fingerprint=seeded.ciphertext_fingerprint,
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

    _assert_0058_recovery_state(
        databases.recovery_url,
        expected_fingerprint=seeded.ciphertext_fingerprint,
    )
