from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/20260715_0064_media_delivery_observability.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("media_delivery_observability_0064", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0064_drops_legacy_download_fields_and_downgrade_restores_defaults_only() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "run_records",
        metadata,
        sa.Column("run_id", sa.String(191), primary_key=True),
    )
    table = sa.Table(
        "media_derivative_job_metrics",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(191), sa.ForeignKey("run_records.run_id"), nullable=False),
        sa.Column("site_id", sa.String(191), nullable=False),
        sa.Column("account_id", sa.String(191)),
        sa.Column("subscription_id", sa.String(191)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(128)),
        sa.Column("target_format", sa.String(16), nullable=False),
        sa.Column("output_format", sa.String(16)),
        sa.Column("source_media_type", sa.String(16), nullable=False, server_default="image"),
        sa.Column("source_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_bytes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("source_height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_width", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_height", sa.Integer, nullable=False, server_default="0"),
        sa.Column("compression_ratio", sa.Float, nullable=False, server_default="0"),
        sa.Column("queue_wait_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processing_duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("watermark_applied", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("warnings_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("artifact_id", sa.String(191)),
        sa.Column("artifact_expires_at", sa.DateTime(timezone=True)),
        sa.Column("artifact_download_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("artifact_last_downloaded_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("run_id", name="uq_media_derivative_job_metrics_run"),
    )
    sa.Index("ix_mdjm_artifact_id", table.c.artifact_id)
    metadata.create_all(engine)
    migration = _load()
    assert migration.revision == "20260715_0064"
    assert migration.down_revision == "20260715_0063"

    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO run_records (run_id) VALUES ('run_legacy')"))
        connection.execute(
            table.insert().values(
                id=1,
                run_id="run_legacy",
                site_id="site_legacy",
                account_id="account_legacy",
                subscription_id="subscription_legacy",
                status="succeeded",
                target_format="webp",
                output_format="webp",
                source_media_type="image",
                source_bytes=1000,
                output_bytes=400,
                source_width=200,
                source_height=160,
                output_width=100,
                output_height=80,
                compression_ratio=0.6,
                queue_wait_ms=20,
                processing_duration_ms=120,
                total_duration_ms=140,
                watermark_applied=False,
                warnings_count=0,
                artifact_id="art_legacy",
                artifact_expires_at=datetime(2026, 7, 15, 2, 0, tzinfo=UTC),
                artifact_download_count=7,
                artifact_last_downloaded_at=datetime(2026, 7, 15, 1, 2, 3, tzinfo=UTC),
                created_at=datetime(2026, 7, 15, 1, 0, tzinfo=UTC),
                finished_at=datetime(2026, 7, 15, 1, 1, tzinfo=UTC),
            )
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = sa.inspect(connection)
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        assert "artifact_download_count" not in columns
        assert "artifact_last_downloaded_at" not in columns
        assert {
            "run_id",
            "site_id",
            "target_format",
            "source_bytes",
            "artifact_id",
            "finished_at",
        } <= columns
        preserved = connection.execute(
            sa.text(
                "SELECT run_id, site_id, target_format, source_bytes, artifact_id "
                "FROM media_derivative_job_metrics WHERE id = 1"
            )
        ).one()
        assert preserved == (
            "run_legacy",
            "site_legacy",
            "webp",
            1000,
            "art_legacy",
        )
        assert any(
            constraint["name"] == "uq_media_derivative_job_metrics_run"
            and constraint["column_names"] == ["run_id"]
            for constraint in inspector.get_unique_constraints(table.name)
        )
        assert any(
            index["name"] == "ix_mdjm_artifact_id"
            and index["column_names"] == ["artifact_id"]
            for index in inspector.get_indexes(table.name)
        )
        assert any(
            foreign_key["constrained_columns"] == ["run_id"]
            and foreign_key["referred_table"] == "run_records"
            and foreign_key["referred_columns"] == ["run_id"]
            for foreign_key in inspector.get_foreign_keys(table.name)
        )

        migration.downgrade()
        inspector = sa.inspect(connection)
        columns = {column["name"] for column in inspector.get_columns(table.name)}
        assert {"artifact_download_count", "artifact_last_downloaded_at"} <= columns
        restored = connection.execute(
            sa.text(
                "SELECT artifact_download_count, artifact_last_downloaded_at "
                "FROM media_derivative_job_metrics WHERE id = 1"
            )
        ).one()
        assert restored[0] == 0
        assert restored[1] is None
        assert (
            connection.execute(
                sa.text(
                    "SELECT site_id, target_format, source_bytes, artifact_id "
                    "FROM media_derivative_job_metrics WHERE id = 1"
                )
            ).one()
            == ("site_legacy", "webp", 1000, "art_legacy")
        )
        assert any(
            constraint["name"] == "uq_media_derivative_job_metrics_run"
            for constraint in inspector.get_unique_constraints(table.name)
        )
        assert "ix_mdjm_artifact_id" in {
            index["name"] for index in inspector.get_indexes(table.name)
        }
        assert any(
            foreign_key["constrained_columns"] == ["run_id"]
            and foreign_key["referred_table"] == "run_records"
            for foreign_key in inspector.get_foreign_keys(table.name)
        )
