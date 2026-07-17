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
    / "migrations/versions/20260717_0068_hosted_profile_operation_contract.py"
)

LEGACY_POLICY_KEY = "connector_contract_" + "version"
LEGACY_POLICY_VERSION = "wp_ai_connector_" + "runtime.v1"
OPERATION_POLICY_KEY = "operation_contract_version"
OPERATION_POLICY_VERSION = "wordpress_operation.v1"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hosted_profile_operation_contract_0068",
        MIGRATION,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _managed_policy(*, note: str, legacy: bool = True) -> dict[str, object]:
    policy: dict[str, object] = {
        "managed_surface": "hosted_runtime_profiles",
        "platform_kind": "wordpress",
        "connector_id": "wordpress_ai_connector",
        "task_group": "short_text",
        "operator_note": note,
        "nested": {"preserved": True},
    }
    if legacy:
        policy[LEGACY_POLICY_KEY] = LEGACY_POLICY_VERSION
    else:
        policy[OPERATION_POLICY_KEY] = OPERATION_POLICY_VERSION
    return policy


def _create_schema(engine: sa.Engine) -> dict[str, sa.Table]:
    metadata = sa.MetaData()
    profiles = sa.Table(
        "routing_profiles",
        metadata,
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column("execution_kind", sa.String(32), nullable=False),
        sa.Column("default_policy_json", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    bindings = sa.Table(
        "routing_bindings",
        metadata,
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column("candidate_instance_ids", sa.JSON(), nullable=False),
        sa.Column("selection_policy_json", sa.JSON(), nullable=True),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.String(32), nullable=False),
    )
    runs = sa.Table(
        "run_records",
        metadata,
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("policy_json", sa.JSON(), nullable=True),
    )
    audits = sa.Table(
        "service_audit_events",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
    )
    metadata.create_all(engine)
    return {
        "profiles": profiles,
        "bindings": bindings,
        "runs": runs,
        "audits": audits,
    }


def _seed_rows(connection: sa.Connection, tables: dict[str, sa.Table]) -> None:
    profiles = tables["profiles"]
    bindings = tables["bindings"]
    target_policy = _managed_policy(note="operator canary")
    non_target_policy = _managed_policy(note="wrong platform")
    non_target_policy["platform_kind"] = "ghost"
    wrong_version_policy = _managed_policy(note="unknown legacy version")
    wrong_version_policy[LEGACY_POLICY_KEY] = "unknown.v2"

    connection.execute(
        profiles.insert(),
        [
            {
                "profile_id": "wp-ai.short-text",
                "execution_kind": "text",
                "default_policy_json": target_policy,
                "updated_at": "2026-07-17T10:00:00Z",
            },
            {
                "profile_id": "ghost.short-text",
                "execution_kind": "text",
                "default_policy_json": non_target_policy,
                "updated_at": "2026-07-17T10:01:00Z",
            },
            {
                "profile_id": "wp-ai.unknown-version",
                "execution_kind": "text",
                "default_policy_json": wrong_version_policy,
                "updated_at": "2026-07-17T10:02:00Z",
            },
            {
                "profile_id": "wp-ai.null-policy",
                "execution_kind": "text",
                "default_policy_json": None,
                "updated_at": "2026-07-17T10:03:00Z",
            },
        ],
    )
    connection.execute(
        bindings.insert(),
        [
            {
                "profile_id": "wp-ai.short-text",
                "candidate_instance_ids": ["instance-primary", "instance-fallback"],
                "selection_policy_json": target_policy,
                "revision": "runtime-profiles-admin-preserved",
                "updated_at": "2026-07-17T10:00:00Z",
            },
            {
                "profile_id": "ghost.short-text",
                "candidate_instance_ids": ["ghost-instance"],
                "selection_policy_json": non_target_policy,
                "revision": "runtime-profiles-admin-ghost",
                "updated_at": "2026-07-17T10:01:00Z",
            },
            {
                "profile_id": "wp-ai.unknown-version",
                "candidate_instance_ids": [],
                "selection_policy_json": wrong_version_policy,
                "revision": "runtime-profiles-admin-unknown",
                "updated_at": "2026-07-17T10:02:00Z",
            },
            {
                "profile_id": "wp-ai.null-policy",
                "candidate_instance_ids": [],
                "selection_policy_json": None,
                "revision": "catalog-null-policy",
                "updated_at": "2026-07-17T10:03:00Z",
            },
        ],
    )
    connection.execute(
        tables["runs"].insert().values(
            run_id="run_historical",
            policy_json={LEGACY_POLICY_KEY: LEGACY_POLICY_VERSION, "preserved": True},
        )
    )
    connection.execute(
        tables["audits"].insert().values(
            id=1,
            payload_json={LEGACY_POLICY_KEY: LEGACY_POLICY_VERSION, "preserved": True},
        )
    )


def _rows_by_id(
    connection: sa.Connection,
    table: sa.Table,
    identity_column: str,
) -> dict[str, dict[str, object]]:
    return {
        str(row[identity_column]): dict(row)
        for row in connection.execute(sa.select(table)).mappings()
    }


def test_0068_sqlite_upgrade_is_precise_idempotent_and_preserves_both_tables() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    tables = _create_schema(engine)
    migration = _load()

    with engine.begin() as connection:
        _seed_rows(connection, tables)
        before_profiles = _rows_by_id(connection, tables["profiles"], "profile_id")
        before_bindings = _rows_by_id(connection, tables["bindings"], "profile_id")
        before_runs = _rows_by_id(connection, tables["runs"], "run_id")
        before_audits = _rows_by_id(connection, tables["audits"], "id")
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        upgraded_profiles = _rows_by_id(connection, tables["profiles"], "profile_id")
        upgraded_bindings = _rows_by_id(connection, tables["bindings"], "profile_id")
        migration.upgrade()

        assert upgraded_profiles == _rows_by_id(connection, tables["profiles"], "profile_id")
        assert upgraded_bindings == _rows_by_id(connection, tables["bindings"], "profile_id")

        profile_policy = upgraded_profiles["wp-ai.short-text"]["default_policy_json"]
        binding_policy = upgraded_bindings["wp-ai.short-text"]["selection_policy_json"]
        assert isinstance(profile_policy, dict)
        assert isinstance(binding_policy, dict)
        for policy in (profile_policy, binding_policy):
            assert LEGACY_POLICY_KEY not in policy
            assert policy[OPERATION_POLICY_KEY] == OPERATION_POLICY_VERSION
            assert policy["operator_note"] == "operator canary"
            assert policy["nested"] == {"preserved": True}

        for field in ("profile_id", "execution_kind", "updated_at"):
            assert upgraded_profiles["wp-ai.short-text"][field] == before_profiles[
                "wp-ai.short-text"
            ][field]
        for field in (
            "profile_id",
            "candidate_instance_ids",
            "revision",
            "updated_at",
        ):
            assert upgraded_bindings["wp-ai.short-text"][field] == before_bindings[
                "wp-ai.short-text"
            ][field]

        for profile_id in (
            "ghost.short-text",
            "wp-ai.unknown-version",
            "wp-ai.null-policy",
        ):
            assert upgraded_profiles[profile_id] == before_profiles[profile_id]
            assert upgraded_bindings[profile_id] == before_bindings[profile_id]

        assert _rows_by_id(connection, tables["runs"], "run_id") == before_runs
        assert _rows_by_id(connection, tables["audits"], "id") == before_audits

    engine.dispose()


def test_0068_sqlite_downgrade_only_reverses_matching_managed_rows() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    tables = _create_schema(engine)
    migration = _load()

    with engine.begin() as connection:
        _seed_rows(connection, tables)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        profiles = tables["profiles"]
        bindings = tables["bindings"]
        non_target_new = _managed_policy(note="new but not WordPress", legacy=False)
        non_target_new["connector_id"] = "other_connector"
        connection.execute(
            profiles.insert().values(
                profile_id="other.new-contract",
                execution_kind="text",
                default_policy_json=non_target_new,
                updated_at="2026-07-17T10:04:00Z",
            )
        )
        connection.execute(
            bindings.insert().values(
                profile_id="other.new-contract",
                candidate_instance_ids=["other-instance"],
                selection_policy_json=non_target_new,
                revision="other-new-contract",
                updated_at="2026-07-17T10:04:00Z",
            )
        )
        non_target_before = _rows_by_id(connection, profiles, "profile_id")[
            "other.new-contract"
        ]
        non_target_binding_before = _rows_by_id(connection, bindings, "profile_id")[
            "other.new-contract"
        ]

        migration.downgrade()
        downgraded_profiles = _rows_by_id(connection, profiles, "profile_id")
        downgraded_bindings = _rows_by_id(connection, bindings, "profile_id")
        migration.downgrade()

        assert downgraded_profiles == _rows_by_id(connection, profiles, "profile_id")
        assert downgraded_bindings == _rows_by_id(connection, bindings, "profile_id")
        for policy in (
            downgraded_profiles["wp-ai.short-text"]["default_policy_json"],
            downgraded_bindings["wp-ai.short-text"]["selection_policy_json"],
        ):
            assert isinstance(policy, dict)
            assert OPERATION_POLICY_KEY not in policy
            assert policy[LEGACY_POLICY_KEY] == LEGACY_POLICY_VERSION
            assert policy["operator_note"] == "operator canary"
            assert policy["nested"] == {"preserved": True}

        assert downgraded_profiles["other.new-contract"] == non_target_before
        assert downgraded_bindings["other.new-contract"] == non_target_binding_before

    engine.dispose()


def test_0068_upgrade_rolls_back_both_tables_when_the_second_rewrite_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / '0068-atomic.sqlite3'}")
    tables = _create_schema(engine)
    migration = _load()

    with engine.begin() as connection:
        _seed_rows(connection, tables)
    with engine.connect() as connection:
        before_profiles = _rows_by_id(connection, tables["profiles"], "profile_id")
        before_bindings = _rows_by_id(connection, tables["bindings"], "profile_id")

    original = migration._rewrite_policy_column
    calls = 0

    def fail_on_second_table(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second-table failure")
        original(*args, **kwargs)

    monkeypatch.setattr(migration, "_rewrite_policy_column", fail_on_second_table)
    with pytest.raises(RuntimeError, match="injected second-table failure"):
        with engine.begin() as connection:
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

    with engine.connect() as connection:
        assert _rows_by_id(connection, tables["profiles"], "profile_id") == before_profiles
        assert _rows_by_id(connection, tables["bindings"], "profile_id") == before_bindings

    engine.dispose()


def test_migration_test_source_does_not_embed_superseded_tokens() -> None:
    source = Path(__file__).read_text(encoding="utf-8")
    assert LEGACY_POLICY_KEY not in source
    assert LEGACY_POLICY_VERSION not in source
