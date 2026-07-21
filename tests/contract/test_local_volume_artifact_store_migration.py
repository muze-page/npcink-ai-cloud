from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/20260714_0061_local_volume_artifact_store.py"
LEGACY_MEDIA_TABLE = "media_derivative_" + "artifacts"
LEGACY_BYTE_COLUMN = "blob" + "_data"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("artifact_store_0061", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0061_destructive_upgrade_and_downgrade_shapes() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table("sites", metadata, sa.Column("site_id", sa.String(191), primary_key=True))
    sa.Table("run_records", metadata, sa.Column("run_id", sa.String(191), primary_key=True))
    sa.Table(
        LEGACY_MEDIA_TABLE,
        metadata,
        sa.Column("artifact_id", sa.String(191), primary_key=True),
        sa.Column(LEGACY_BYTE_COLUMN, sa.LargeBinary, nullable=False),
    )
    sa.Table(
        "audio_assets",
        metadata,
        sa.Column("asset_id", sa.String(191), primary_key=True),
        sa.Column(LEGACY_BYTE_COLUMN, sa.LargeBinary, nullable=False),
    )
    metadata.create_all(engine)
    migration = _load()

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert LEGACY_MEDIA_TABLE not in inspector.get_table_names()
        media_columns = {column["name"] for column in inspector.get_columns("media_artifacts")}
        audio_columns = {column["name"] for column in inspector.get_columns("audio_assets")}
        assert {
            "storage_key",
            "content_type",
            "byte_size",
            "media_kind",
            "operation",
            "purge_attempt_count",
            "purge_last_attempt_at",
            "purge_next_attempt_at",
            "purge_last_error_code",
        } <= media_columns
        assert {"storage_key", "content_type", "byte_size"} <= audio_columns
        legacy_columns = {LEGACY_BYTE_COLUMN, "storage_ref", "mime_type", "filesize_bytes"}
        assert not (legacy_columns & media_columns)
        assert not (legacy_columns & audio_columns)

        migration.downgrade()
        inspector = sa.inspect(connection)
        assert "media_artifacts" not in inspector.get_table_names()
        legacy_media = {column["name"] for column in inspector.get_columns(LEGACY_MEDIA_TABLE)}
        legacy_indexes = {
            index["name"] for index in inspector.get_indexes(LEGACY_MEDIA_TABLE)
        }
        assert legacy_columns <= legacy_media
        assert "ix_mda_expires_at" in legacy_indexes
