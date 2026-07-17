from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/20260715_0063_drop_audio_assets.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("drop_audio_assets_0063", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _create_site_and_audio_table(engine: sa.Engine) -> None:
    metadata = sa.MetaData()
    sa.Table("sites", metadata, sa.Column("site_id", sa.String(191), primary_key=True))
    sa.Table(
        "audio_assets",
        metadata,
        sa.Column("asset_id", sa.String(191), primary_key=True),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("storage_key", sa.String(191), nullable=False),
    )
    metadata.create_all(engine)


def test_0063_refuses_to_drop_non_empty_audio_assets() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _create_site_and_audio_table(engine)
    migration = _load()

    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO sites (site_id) VALUES ('site_alpha')"))
        connection.execute(
            sa.text(
                "INSERT INTO audio_assets (asset_id, site_id, storage_key) "
                "VALUES ('aud_legacy', 'site_alpha', 'legacy/audio.bin')"
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        with pytest.raises(RuntimeError, match="pre-GA reset required"):
            migration.upgrade()

        assert "audio_assets" in sa.inspect(connection).get_table_names()
        assert connection.execute(sa.text("SELECT COUNT(*) FROM audio_assets")).scalar_one() == 1


def test_0063_drops_empty_table_and_downgrade_restores_empty_shape_only() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    _create_site_and_audio_table(engine)
    migration = _load()
    assert migration.revision == "20260715_0063"
    assert migration.down_revision == "20260715_0062"

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert "audio_assets" not in sa.inspect(connection).get_table_names()

        migration.downgrade()
        inspector = sa.inspect(connection)
        columns = {column["name"] for column in inspector.get_columns("audio_assets")}
        assert {
            "asset_id",
            "site_id",
            "source_artifact_id",
            "source_run_id",
            "status",
            "storage_key",
            "content_type",
            "format",
            "duration_seconds",
            "byte_size",
            "checksum",
            "source_content_hash",
            "provider_id",
            "model_id",
            "trace_id",
            "metadata_json",
            "revoked_at",
            "created_at",
            "updated_at",
        } == columns
        indexes = {index["name"] for index in inspector.get_indexes("audio_assets")}
        assert {
            "ix_audio_assets_site_id",
            "ix_audio_assets_source_artifact_id",
            "ix_audio_assets_source_run_id",
            "ix_audio_assets_status",
            "ix_audio_assets_checksum",
            "ix_audio_assets_source_content_hash",
            "ix_audio_assets_provider_id",
            "ix_audio_assets_model_id",
            "ix_audio_assets_trace_id",
        } <= indexes
        assert connection.execute(sa.text("SELECT COUNT(*) FROM audio_assets")).scalar_one() == 0
