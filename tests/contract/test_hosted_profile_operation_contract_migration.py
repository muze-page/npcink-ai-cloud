from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.db import dispose_engine, get_engine, get_session, init_schema
from app.core.models import RoutingBinding, RoutingProfile
from app.domain.catalog.service import CatalogService

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "migrations/versions/20260717_0068_hosted_profile_operation_contract.py"
)

LEGACY_MANAGED_SURFACE = "wordpress_ai_connector"
MANAGED_SURFACE = "hosted_runtime_profiles"
PLATFORM_KIND = "wordpress"
CONNECTOR_ID = "wordpress_ai_connector"
LEGACY_POLICY_KEY = "connector_contract_" + "version"
LEGACY_POLICY_VERSION = "wp_ai_connector_" + "runtime.v1"
OPERATION_POLICY_KEY = "operation_contract_version"
OPERATION_POLICY_VERSION = "wordpress_operation.v1"
LEGACY_ADMIN_REVISION_PREFIX = "ability-model-routing-admin-"
ADMIN_REVISION_PREFIX = "runtime-profiles-admin-"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hosted_profile_operation_contract_0068",
        MIGRATION,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _master_admin_profile_policy(*, note: str) -> dict[str, object]:
    return {
        "allow_fallback": True,
        "max_retries": 1,
        "timeout_ms": 12_000,
        "managed_surface": LEGACY_MANAGED_SURFACE,
        "task_group": "short_text",
        "routing_intent": "content.short_text",
        "tasks": ["excerpt_generation", "meta_description", "title_generation"],
        "operator_note": note,
    }


def _master_admin_binding_policy(*, note: str) -> dict[str, object]:
    return {
        "strategy": "ordered",
        "managed_surface": LEGACY_MANAGED_SURFACE,
        "task_group": "short_text",
        "routing_intent": "content.short_text",
        "operator_note": note,
    }


def _master_catalog_profile_policy() -> dict[str, object]:
    return {
        "allow_fallback": True,
        "max_retries": 0,
        "timeout_ms": 45_000,
        "managed_surface": LEGACY_MANAGED_SURFACE,
        "task_group": "editorial_text",
        "tasks": ["comment_reply_suggest", "content_rewrite", "content_summary"],
    }


def _master_catalog_binding_policy() -> dict[str, object]:
    return {
        "strategy": "ordered",
        "ordered_tiers": ["free-gpt55", "hosted-free", "balanced"],
        "managed_surface": LEGACY_MANAGED_SURFACE,
        "task_group": "editorial_text",
    }


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
    non_target_policy = {
        "managed_surface": MANAGED_SURFACE,
        "platform_kind": "ghost",
        "connector_id": "ghost_connector",
        OPERATION_POLICY_KEY: "ghost_operation.v1",
        "operator_note": "unrelated platform",
    }

    connection.execute(
        profiles.insert(),
        [
            {
                "profile_id": "wp-ai.short-text",
                "execution_kind": "text",
                "default_policy_json": _master_admin_profile_policy(
                    note="operator canary"
                ),
                "updated_at": "2026-07-17T10:00:00Z",
            },
            {
                "profile_id": "wp-ai.editorial",
                "execution_kind": "text",
                "default_policy_json": _master_catalog_profile_policy(),
                "updated_at": "2026-07-17T10:01:00Z",
            },
            {
                "profile_id": "ghost.short-text",
                "execution_kind": "text",
                "default_policy_json": non_target_policy,
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
                "selection_policy_json": _master_admin_binding_policy(
                    note="operator canary"
                ),
                "revision": f"{LEGACY_ADMIN_REVISION_PREFIX}1721210400",
                "updated_at": "2026-07-17T10:00:00Z",
            },
            {
                "profile_id": "wp-ai.editorial",
                "candidate_instance_ids": ["instance-editorial"],
                "selection_policy_json": _master_catalog_binding_policy(),
                "revision": "catalog-20260717T100100Z",
                "updated_at": "2026-07-17T10:01:00Z",
            },
            {
                "profile_id": "ghost.short-text",
                "candidate_instance_ids": ["ghost-instance"],
                "selection_policy_json": non_target_policy,
                "revision": "ghost-admin-preserved",
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


def _assert_upgraded_policy(policy: object) -> None:
    assert isinstance(policy, dict)
    assert policy["managed_surface"] == MANAGED_SURFACE
    assert policy["platform_kind"] == PLATFORM_KIND
    assert policy["connector_id"] == CONNECTOR_ID
    assert policy[OPERATION_POLICY_KEY] == OPERATION_POLICY_VERSION
    assert LEGACY_POLICY_KEY not in policy


def test_0068_sqlite_upgrade_migrates_real_master_shapes_idempotently() -> None:
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

        for profile_id in ("wp-ai.short-text", "wp-ai.editorial"):
            _assert_upgraded_policy(
                upgraded_profiles[profile_id]["default_policy_json"]
            )
            _assert_upgraded_policy(
                upgraded_bindings[profile_id]["selection_policy_json"]
            )

        short_text_policy = upgraded_profiles["wp-ai.short-text"][
            "default_policy_json"
        ]
        assert isinstance(short_text_policy, dict)
        assert short_text_policy["operator_note"] == "operator canary"
        assert short_text_policy["timeout_ms"] == 12_000
        assert upgraded_bindings["wp-ai.short-text"]["candidate_instance_ids"] == [
            "instance-primary",
            "instance-fallback",
        ]
        assert upgraded_bindings["wp-ai.short-text"]["revision"] == (
            f"{ADMIN_REVISION_PREFIX}1721210400"
        )
        assert upgraded_bindings["wp-ai.editorial"]["revision"] == (
            before_bindings["wp-ai.editorial"]["revision"]
        )

        for profile_id in ("ghost.short-text", "wp-ai.null-policy"):
            assert upgraded_profiles[profile_id] == before_profiles[profile_id]
            assert upgraded_bindings[profile_id] == before_bindings[profile_id]

        assert _rows_by_id(connection, tables["runs"], "run_id") == before_runs
        assert _rows_by_id(connection, tables["audits"], "id") == before_audits

    engine.dispose()


def test_0068_sqlite_downgrade_restores_real_master_shapes_idempotently() -> None:
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    tables = _create_schema(engine)
    migration = _load()

    with engine.begin() as connection:
        _seed_rows(connection, tables)
        before_profiles = _rows_by_id(connection, tables["profiles"], "profile_id")
        before_bindings = _rows_by_id(connection, tables["bindings"], "profile_id")
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        profiles = tables["profiles"]
        bindings = tables["bindings"]
        non_target_new = {
            "managed_surface": MANAGED_SURFACE,
            "platform_kind": "wordpress",
            "connector_id": "other_connector",
            OPERATION_POLICY_KEY: OPERATION_POLICY_VERSION,
            "operator_note": "new but unrelated connector",
        }
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
                revision="runtime-profiles-admin-other",
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
        for profile_id in ("wp-ai.short-text", "wp-ai.editorial"):
            assert downgraded_profiles[profile_id] == before_profiles[profile_id]
            assert downgraded_bindings[profile_id] == before_bindings[profile_id]

        assert downgraded_profiles["other.new-contract"] == non_target_before
        assert downgraded_bindings["other.new-contract"] == non_target_binding_before

    engine.dispose()


def test_0068_upgrade_preserves_master_admin_state_through_catalog_refresh(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / '0068-refresh.sqlite3'}"
    init_schema(database_url)
    migration = _load()

    with get_session(database_url) as session:
        session.add(
            RoutingProfile(
                profile_id="wp-ai.short-text",
                execution_kind="text",
                default_policy_json=_master_admin_profile_policy(
                    note="operator canary"
                ),
            )
        )
        session.add(
            RoutingBinding(
                profile_id="wp-ai.short-text",
                candidate_instance_ids=["instance-primary", "instance-fallback"],
                selection_policy_json=_master_admin_binding_policy(
                    note="operator canary"
                ),
                revision=f"{LEGACY_ADMIN_REVISION_PREFIX}1721210400",
            )
        )
        session.commit()

    with get_engine(database_url).begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

    CatalogService(database_url, providers={}).refresh_catalog()

    with get_session(database_url) as session:
        profile = session.get(RoutingProfile, "wp-ai.short-text")
        binding = session.get(RoutingBinding, "wp-ai.short-text")
        assert profile is not None
        assert binding is not None
        _assert_upgraded_policy(profile.default_policy_json)
        _assert_upgraded_policy(binding.selection_policy_json)
        assert profile.default_policy_json["timeout_ms"] == 12_000
        assert profile.default_policy_json["operator_note"] == "operator canary"
        assert binding.candidate_instance_ids == [
            "instance-primary",
            "instance-fallback",
        ]
        assert binding.selection_policy_json["operator_note"] == "operator canary"
        assert binding.revision == f"{ADMIN_REVISION_PREFIX}1721210400"

    dispose_engine(database_url)


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
