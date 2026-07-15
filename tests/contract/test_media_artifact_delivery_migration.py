from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/20260715_0062_media_artifact_deliveries.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("media_artifact_delivery_0062", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0062_creates_independent_delivery_evidence_and_round_trips() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "media_artifacts",
        metadata,
        sa.Column("artifact_id", sa.String(191), primary_key=True),
    )
    metadata.create_all(engine)
    migration = _load()

    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = sa.inspect(connection)
        columns = {
            column["name"]
            for column in inspector.get_columns("media_artifact_deliveries")
        }
        assert {
            "delivery_id",
            "artifact_id",
            "site_id",
            "expected_byte_size",
            "expected_checksum",
            "pull_trace_id",
            "started_at",
            "completed_at",
            "completed_byte_size",
            "completed_checksum",
            "ack_deadline_at",
            "revoked_at",
            "acked_at",
            "ack_idempotency_key",
            "ack_request_fingerprint",
            "ack_trace_id",
            "received_byte_size",
            "received_checksum",
            "byte_size_verified",
            "checksum_verified",
            "retention_expires_at_before",
            "retention_expires_at_after",
            "created_at",
        } == columns
        unique_constraints = inspector.get_unique_constraints(
            "media_artifact_deliveries"
        )
        assert {
            "name": "uq_media_artifact_deliveries_site_ack_key",
            "column_names": ["site_id", "ack_idempotency_key"],
        } in unique_constraints
        indexes = {
            index["name"] for index in inspector.get_indexes("media_artifact_deliveries")
        }
        assert {
            "ix_media_artifact_deliveries_artifact_id",
            "ix_media_artifact_deliveries_site_id",
            "ix_media_artifact_deliveries_pull_trace_id",
            "ix_media_artifact_deliveries_started_at",
            "ix_media_artifact_deliveries_ack_deadline_at",
            "ix_media_artifact_deliveries_ack_trace_id",
        } <= indexes

        migration.downgrade()
        assert "media_artifact_deliveries" not in sa.inspect(connection).get_table_names()
        assert "media_artifacts" in sa.inspect(connection).get_table_names()
