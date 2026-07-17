from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "migrations/versions/20260716_0066_media_artifact_orphan_reconciliation.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "media_artifact_orphan_reconciliation_0066",
        MIGRATION,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0066_creates_durable_pass_candidate_state_and_round_trips() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    migration = _load()
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        inspector = sa.inspect(connection)
        assert {
            "media_artifact_reconciliation_passes",
            "media_artifact_orphan_candidates",
        } <= set(inspector.get_table_names())
        pass_columns = {
            item["name"]
            for item in inspector.get_columns("media_artifact_reconciliation_passes")
        }
        assert {
            "pass_id",
            "state",
            "active_slot",
            "head_slot",
            "scan_claim_id",
            "lease_expires_at",
            "previous_completed_pass_id",
            "store_generation",
            "next_cursor",
            "last_storage_key",
            "started_at",
            "cutoff_at",
            "completed_at",
        } <= pass_columns
        candidate_columns = {
            item["name"]
            for item in inspector.get_columns("media_artifact_orphan_candidates")
        }
        assert {
            "storage_key",
            "object_version",
            "store_generation",
            "first_pass_id",
            "last_pass_id",
            "state",
            "claim_id",
            "claim_expires_at",
            "attempt_count",
            "retry_at",
            "last_error_code",
            "resolved_at",
        } <= candidate_columns
        assert {
            item["name"]
            for item in inspector.get_unique_constraints(
                "media_artifact_reconciliation_passes"
            )
        } == {
            "uq_media_artifact_reconciliation_passes_active_slot",
            "uq_media_artifact_reconciliation_passes_head_slot",
        }
        assert {
            item["name"]
            for item in inspector.get_check_constraints(
                "media_artifact_reconciliation_passes"
            )
        } >= {
            "ck_media_artifact_reconciliation_passes_state",
            "ck_media_artifact_reconciliation_passes_claim_pair",
            "ck_media_artifact_reconciliation_passes_lifecycle",
        }
        assert {
            item["name"]
            for item in inspector.get_check_constraints(
                "media_artifact_orphan_candidates"
            )
        } >= {
            "ck_media_artifact_orphan_candidates_state",
            "ck_media_artifact_orphan_candidates_claim_pair",
            "ck_media_artifact_orphan_candidates_claim_state",
            "ck_media_artifact_orphan_candidates_retry_state",
            "ck_media_artifact_orphan_candidates_resolution",
        }
        assert "ix_media_artifact_recon_passes_previous_id" in {
            item["name"]
            for item in inspector.get_indexes(
                "media_artifact_reconciliation_passes"
            )
        }
        explicit_names: list[str] = []
        for table_name in (
            "media_artifact_reconciliation_passes",
            "media_artifact_orphan_candidates",
        ):
            for collection in (
                inspector.get_indexes(table_name),
                inspector.get_unique_constraints(table_name),
                inspector.get_check_constraints(table_name),
                inspector.get_foreign_keys(table_name),
            ):
                explicit_names.extend(
                    str(item["name"])
                    for item in collection
                    if item.get("name") is not None
                )
        assert explicit_names
        assert all(len(name) <= 63 for name in explicit_names)
        connection.execute(
            sa.text(
                "INSERT INTO media_artifact_reconciliation_passes "
                "(pass_id, state, active_slot, scan_claim_id, lease_expires_at, "
                "store_generation, started_at, cutoff_at) VALUES "
                "('rcp_valid', 'running', 'active', 'rcl_valid', "
                "'2026-07-16 12:05:00', 'gen_valid', "
                "'2026-07-16 12:00:00', '2026-07-15 12:00:00')"
            )
        )
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(
                sa.text(
                    "INSERT INTO media_artifact_reconciliation_passes "
                    "(pass_id, state, active_slot, scan_claim_id, lease_expires_at, "
                    "store_generation, started_at, cutoff_at) VALUES "
                    "('rcp_invalid', 'running', 'wrong', 'rcl_invalid', "
                    "'2026-07-16 12:05:00', 'gen_invalid', "
                    "'2026-07-16 12:00:00', '2026-07-15 12:00:00')"
                )
            )
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(
                sa.text(
                    "INSERT INTO media_artifact_reconciliation_passes "
                    "(pass_id, state, store_generation, started_at, cutoff_at, "
                    "completed_at) VALUES "
                    "('rcp_abandoned_completed', 'abandoned', 'gen_invalid', "
                    "'2026-07-16 12:00:00', '2026-07-15 12:00:00', "
                    "'2026-07-16 13:00:00')"
                )
            )
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(
                sa.text(
                    "INSERT INTO media_artifact_orphan_candidates "
                    "(storage_key, object_version, store_generation, first_pass_id, "
                    "last_pass_id, state, attempt_count, first_observed_at, "
                    "last_observed_at) VALUES "
                    "('obj_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'token', 'gen_valid', "
                    "'rcp_valid', 'rcp_valid', 'retry_wait', 1, "
                    "'2026-07-16 12:00:00', '2026-07-16 12:00:00')"
                )
            )
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(
                sa.text(
                    "INSERT INTO media_artifact_orphan_candidates "
                    "(storage_key, object_version, store_generation, first_pass_id, "
                    "last_pass_id, state, attempt_count, retry_at, last_error_code, "
                    "first_observed_at, last_observed_at) VALUES "
                    "('obj_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 'token', 'gen_valid', "
                    "'rcp_valid', 'rcp_valid', 'observed', 1, "
                    "'2026-07-16 13:00:00', 'unexpected', "
                    "'2026-07-16 12:00:00', '2026-07-16 12:00:00')"
                )
            )

        migration.downgrade()
        assert not {
            "media_artifact_reconciliation_passes",
            "media_artifact_orphan_candidates",
        } & set(sa.inspect(connection).get_table_names())
    engine.dispose()
