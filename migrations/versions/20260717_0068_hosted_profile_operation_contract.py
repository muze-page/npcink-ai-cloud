"""cut hosted runtime profiles over to the WordPress operation contract"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260717_0068"
down_revision = "20260717_0067"
branch_labels = None
depends_on = None

_MANAGED_SURFACE = "hosted_runtime_profiles"
_PLATFORM_KIND = "wordpress"
_CONNECTOR_ID = "wordpress_ai_connector"
_LEGACY_POLICY_KEY = "connector_contract_version"
_LEGACY_POLICY_VERSION = "wp_ai_connector_runtime.v1"
_OPERATION_POLICY_KEY = "operation_contract_version"
_OPERATION_POLICY_VERSION = "wordpress_operation.v1"
_POLICY_COLUMNS = (
    ("routing_profiles", "default_policy_json"),
    ("routing_bindings", "selection_policy_json"),
)


def _is_managed_wordpress_connector_policy(policy: dict[str, Any]) -> bool:
    return bool(
        policy.get("managed_surface") == _MANAGED_SURFACE
        and policy.get("platform_kind") == _PLATFORM_KIND
        and policy.get("connector_id") == _CONNECTOR_ID
    )


def _rewrite_policy(
    value: object,
    *,
    source_key: str,
    source_version: str,
    target_key: str,
    target_version: str,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if not _is_managed_wordpress_connector_policy(value):
        return None
    if value.get(source_key) != source_version:
        return None

    rewritten = dict(value)
    rewritten.pop(source_key, None)
    rewritten[target_key] = target_version
    return rewritten


def _rewrite_policy_column(
    table_name: str,
    column_name: str,
    *,
    source_key: str,
    source_version: str,
    target_key: str,
    target_version: str,
) -> None:
    bind = op.get_bind()
    table = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
    policy_column = table.c[column_name]
    rows = (
        bind.execute(sa.select(table.c.profile_id, policy_column).with_for_update())
        .mappings()
        .all()
    )

    for row in rows:
        rewritten = _rewrite_policy(
            row[column_name],
            source_key=source_key,
            source_version=source_version,
            target_key=target_key,
            target_version=target_version,
        )
        if rewritten is None:
            continue
        bind.execute(
            sa.update(table)
            .where(table.c.profile_id == row["profile_id"])
            .values({column_name: rewritten})
        )


def _rewrite_persisted_policies(
    *,
    source_key: str,
    source_version: str,
    target_key: str,
    target_version: str,
) -> None:
    for table_name, column_name in _POLICY_COLUMNS:
        _rewrite_policy_column(
            table_name,
            column_name,
            source_key=source_key,
            source_version=source_version,
            target_key=target_key,
            target_version=target_version,
        )


def upgrade() -> None:
    _rewrite_persisted_policies(
        source_key=_LEGACY_POLICY_KEY,
        source_version=_LEGACY_POLICY_VERSION,
        target_key=_OPERATION_POLICY_KEY,
        target_version=_OPERATION_POLICY_VERSION,
    )


def downgrade() -> None:
    _rewrite_persisted_policies(
        source_key=_OPERATION_POLICY_KEY,
        source_version=_OPERATION_POLICY_VERSION,
        target_key=_LEGACY_POLICY_KEY,
        target_version=_LEGACY_POLICY_VERSION,
    )
