"""cut hosted runtime profiles over to the WordPress operation contract"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260717_0068"
down_revision = "20260717_0067"
branch_labels = None
depends_on = None

_LEGACY_MANAGED_SURFACE = "wordpress_ai_connector"
_MANAGED_SURFACE = "hosted_runtime_profiles"
_PLATFORM_KIND = "wordpress"
_CONNECTOR_ID = "wordpress_ai_connector"
_LEGACY_POLICY_KEY = "connector_contract_version"
_OPERATION_POLICY_KEY = "operation_contract_version"
_OPERATION_POLICY_VERSION = "wordpress_operation.v1"
_LEGACY_ADMIN_REVISION_PREFIX = "ability-model-routing-admin-"
_ADMIN_REVISION_PREFIX = "runtime-profiles-admin-"
_POLICY_COLUMNS = (
    ("routing_profiles", "default_policy_json"),
    ("routing_bindings", "selection_policy_json"),
)


def _upgrade_policy(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if value.get("managed_surface") != _LEGACY_MANAGED_SURFACE:
        return None

    rewritten = dict(value)
    rewritten["managed_surface"] = _MANAGED_SURFACE
    rewritten["platform_kind"] = _PLATFORM_KIND
    rewritten["connector_id"] = _CONNECTOR_ID
    rewritten.pop(_LEGACY_POLICY_KEY, None)
    rewritten[_OPERATION_POLICY_KEY] = _OPERATION_POLICY_VERSION
    return rewritten


def _downgrade_policy(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    if (
        value.get("managed_surface") != _MANAGED_SURFACE
        or value.get("platform_kind") != _PLATFORM_KIND
        or value.get("connector_id") != _CONNECTOR_ID
        or value.get(_OPERATION_POLICY_KEY) != _OPERATION_POLICY_VERSION
    ):
        return None

    rewritten = dict(value)
    rewritten["managed_surface"] = _LEGACY_MANAGED_SURFACE
    rewritten.pop("platform_kind", None)
    rewritten.pop("connector_id", None)
    rewritten.pop(_LEGACY_POLICY_KEY, None)
    rewritten.pop(_OPERATION_POLICY_KEY, None)
    return rewritten


def _replace_revision_prefix(value: object, *, source: str, target: str) -> object:
    if not isinstance(value, str) or not value.startswith(source):
        return value
    return f"{target}{value.removeprefix(source)}"


def _upgrade_revision(value: object) -> object:
    return _replace_revision_prefix(
        value,
        source=_LEGACY_ADMIN_REVISION_PREFIX,
        target=_ADMIN_REVISION_PREFIX,
    )


def _downgrade_revision(value: object) -> object:
    return _replace_revision_prefix(
        value,
        source=_ADMIN_REVISION_PREFIX,
        target=_LEGACY_ADMIN_REVISION_PREFIX,
    )


def _rewrite_policy_column(
    table_name: str,
    column_name: str,
    transform: Callable[[object], dict[str, Any] | None],
    revision_transform: Callable[[object], object],
) -> None:
    bind = op.get_bind()
    table = sa.Table(table_name, sa.MetaData(), autoload_with=bind)
    policy_column = table.c[column_name]
    selected_columns = [table.c.profile_id, policy_column]
    if table_name == "routing_bindings":
        selected_columns.append(table.c.revision)
    rows = bind.execute(sa.select(*selected_columns).with_for_update()).mappings().all()

    for row in rows:
        rewritten = transform(row[column_name])
        if rewritten is None:
            continue
        values: dict[str, object] = {column_name: rewritten}
        if table_name == "routing_bindings":
            values["revision"] = revision_transform(row["revision"])
        bind.execute(
            sa.update(table)
            .where(table.c.profile_id == row["profile_id"])
            .values(values)
        )


def _rewrite_persisted_policies(
    transform: Callable[[object], dict[str, Any] | None],
    revision_transform: Callable[[object], object],
) -> None:
    for table_name, column_name in _POLICY_COLUMNS:
        _rewrite_policy_column(
            table_name,
            column_name,
            transform,
            revision_transform,
        )


def upgrade() -> None:
    _rewrite_persisted_policies(_upgrade_policy, _upgrade_revision)


def downgrade() -> None:
    _rewrite_persisted_policies(_downgrade_policy, _downgrade_revision)
