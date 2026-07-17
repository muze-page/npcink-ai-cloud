from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations/versions/20260717_0067_portal_mutation_idempotency.py"
TABLE_NAME = "portal_mutation_idempotency_receipts"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "portal_mutation_idempotency_0067",
        MIGRATION,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _processing_row(
    *,
    receipt_id: str,
    principal_id: str = "prn_migration_alpha",
    idempotency_key: str = "portal-migration-key",
) -> dict[str, object]:
    now = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)
    return {
        "receipt_id": receipt_id,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "request_method": "POST",
        "request_path": "/portal/v1/support-requests",
        "request_fingerprint": "f" * 64,
        "state": "processing",
        "claim_token": f"claim-{receipt_id}",
        "lease_expires_at": now + timedelta(seconds=30),
        "response_status": None,
        "retention_ttl_seconds": 3600,
        "expires_at": now + timedelta(hours=1),
        "completed_at": None,
    }


def _completed_row(*, receipt_id: str, idempotency_key: str) -> dict[str, object]:
    now = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)
    return {
        "receipt_id": receipt_id,
        "principal_id": "prn_migration_alpha",
        "idempotency_key": idempotency_key,
        "request_method": "POST",
        "request_path": "/portal/v1/support-requests",
        "request_fingerprint": "c" * 64,
        "state": "completed",
        "claim_token": None,
        "lease_expires_at": None,
        "response_status": 200,
        "response_body_ciphertext": "encrypted-response",
        "retention_ttl_seconds": 3600,
        "expires_at": now + timedelta(hours=1),
        "completed_at": now + timedelta(seconds=2),
    }


def test_0067_portal_idempotency_receipts_round_trip_and_enforce_contract() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    migration = _load()
    parent_metadata = sa.MetaData()
    principals = sa.Table(
        "principals",
        parent_metadata,
        sa.Column("principal_id", sa.String(191), primary_key=True),
    )

    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        parent_metadata.create_all(connection)
        connection.execute(
            principals.insert(),
            [
                {"principal_id": "prn_migration_alpha"},
                {"principal_id": "prn_migration_beta"},
            ],
        )
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        inspector = sa.inspect(connection)
        assert TABLE_NAME in inspector.get_table_names()
        assert {
            "receipt_id",
            "principal_id",
            "idempotency_key",
            "request_method",
            "request_path",
            "request_fingerprint",
            "state",
            "claim_token",
            "lease_expires_at",
            "response_status",
            "response_body_ciphertext",
            "retention_ttl_seconds",
            "expires_at",
            "completed_at",
            "created_at",
            "updated_at",
        } == {column["name"] for column in inspector.get_columns(TABLE_NAME)}

        unique_constraints = inspector.get_unique_constraints(TABLE_NAME)
        assert any(
            constraint["name"] == "uq_portal_mutation_idempotency_principal_key"
            and constraint["column_names"] == ["principal_id", "idempotency_key"]
            for constraint in unique_constraints
        )

        check_constraints = {
            str(constraint["name"]): str(constraint["sqltext"])
            for constraint in inspector.get_check_constraints(TABLE_NAME)
        }
        state_sql = check_constraints["ck_portal_mutation_idempotency_state"]
        assert "processing" in state_sql
        assert "completed" in state_sql
        assert "ck_portal_mutation_idempotency_lifecycle" in check_constraints

        indexes = {
            str(index["name"]): list(index["column_names"])
            for index in inspector.get_indexes(TABLE_NAME)
        }
        assert indexes["ix_portal_mutation_idempotency_principal_id"] == ["principal_id"]
        assert indexes["ix_portal_mutation_idempotency_expiry"] == [
            "expires_at",
            "receipt_id",
        ]
        assert indexes["ix_portal_mutation_idempotency_processing_lease"] == [
            "state",
            "lease_expires_at",
        ]

        receipts = sa.Table(TABLE_NAME, sa.MetaData(), autoload_with=connection)
        connection.execute(receipts.insert().values(**_processing_row(receipt_id="pidem_valid")))
        connection.execute(
            receipts.insert().values(
                **_processing_row(
                    receipt_id="pidem_other_principal",
                    principal_id="prn_migration_beta",
                )
            )
        )
        connection.execute(
            receipts.insert().values(
                **_completed_row(
                    receipt_id="pidem_completed",
                    idempotency_key="portal-completed-key",
                )
            )
        )

        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(
                receipts.insert().values(
                    **_processing_row(receipt_id="pidem_duplicate_principal_key")
                )
            )

        invalid_state = _processing_row(
            receipt_id="pidem_invalid_state",
            idempotency_key="portal-invalid-state",
        )
        invalid_state["state"] = "unknown"
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(receipts.insert().values(**invalid_state))

        processing_with_response = _processing_row(
            receipt_id="pidem_processing_with_response",
            idempotency_key="portal-processing-with-response",
        )
        processing_with_response.update(
            {
                "response_status": 200,
                "response_body_ciphertext": "encrypted-response",
            }
        )
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(receipts.insert().values(**processing_with_response))

        completed_without_response = _processing_row(
            receipt_id="pidem_completed_without_response",
            idempotency_key="portal-completed-without-response",
        )
        completed_without_response.update(
            {
                "state": "completed",
                "claim_token": None,
                "lease_expires_at": None,
            }
        )
        with pytest.raises(sa.exc.IntegrityError), connection.begin_nested():
            connection.execute(receipts.insert().values(**completed_without_response))

        migration.downgrade()
        assert TABLE_NAME not in sa.inspect(connection).get_table_names()

    engine.dispose()
