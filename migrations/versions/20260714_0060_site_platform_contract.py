"""promote canonical site URL and platform kind to first-class site columns

Revision ID: 20260714_0060
Revises: 20260711_0059
Create Date: 2026-07-14 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260714_0060"
down_revision = "20260711_0059"
branch_labels = None
depends_on = None

PLATFORM_KIND_WORDPRESS = "wordpress"


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {
        str(column["name"])
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _index_names(table_name: str) -> set[str]:
    return {
        str(index["name"])
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def _sites_table() -> sa.Table:
    metadata = sa.MetaData()
    return sa.Table(
        "sites",
        metadata,
        sa.Column("site_id", sa.String(length=191), primary_key=True),
        sa.Column("site_url", sa.String(length=2048), nullable=False),
        sa.Column("platform_kind", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
    )


def _backfill_first_class_fields() -> None:
    bind = op.get_bind()
    sites = _sites_table()
    rows = list(
        bind.execute(
            sa.select(
                sites.c.site_id,
                sites.c.site_url,
                sites.c.metadata_json,
            )
        ).mappings()
    )
    for row in rows:
        original_metadata = row["metadata_json"]
        metadata = dict(original_metadata) if isinstance(original_metadata, dict) else None
        legacy_site_url = metadata.pop("wordpress_url", None) if metadata is not None else None
        legacy_url = metadata.pop("url", None) if metadata is not None else None
        current_site_url = str(row["site_url"] or "").strip()
        canonical_site_url = current_site_url or str(legacy_site_url or legacy_url or "").strip()
        values: dict[str, object] = {
            "site_url": canonical_site_url,
            "platform_kind": PLATFORM_KIND_WORDPRESS,
        }
        if metadata is not None:
            values["metadata_json"] = metadata
        bind.execute(
            sa.update(sites)
            .where(sites.c.site_id == row["site_id"])
            .values(**values)
        )


def _restore_legacy_metadata() -> None:
    bind = op.get_bind()
    sites = _sites_table()
    rows = list(
        bind.execute(
            sa.select(
                sites.c.site_id,
                sites.c.site_url,
                sites.c.metadata_json,
            )
        ).mappings()
    )
    for row in rows:
        metadata = (
            dict(row["metadata_json"])
            if isinstance(row["metadata_json"], dict)
            else {}
        )
        site_url = str(row["site_url"] or "").strip()
        if site_url:
            metadata["wordpress_url"] = site_url
        bind.execute(
            sa.update(sites)
            .where(sites.c.site_id == row["site_id"])
            .values(metadata_json=metadata)
        )


def upgrade() -> None:
    if "sites" not in _table_names():
        return
    columns = _column_names("sites")
    if "site_url" not in columns:
        op.add_column(
            "sites",
            sa.Column(
                "site_url",
                sa.String(length=2048),
                nullable=False,
                server_default="",
            ),
        )
    if "platform_kind" not in columns:
        op.add_column(
            "sites",
            sa.Column(
                "platform_kind",
                sa.String(length=32),
                nullable=False,
                server_default=PLATFORM_KIND_WORDPRESS,
            ),
        )
    if "ix_sites_platform_kind" not in _index_names("sites"):
        op.create_index(
            "ix_sites_platform_kind",
            "sites",
            ["platform_kind"],
        )
    _backfill_first_class_fields()


def downgrade() -> None:
    if "sites" not in _table_names():
        return
    columns = _column_names("sites")
    if "site_url" in columns:
        _restore_legacy_metadata()
    if "ix_sites_platform_kind" in _index_names("sites"):
        op.drop_index("ix_sites_platform_kind", table_name="sites")
    columns_to_drop = [
        column_name
        for column_name in ("platform_kind", "site_url")
        if column_name in _column_names("sites")
    ]
    if columns_to_drop:
        with op.batch_alter_table("sites") as batch:
            for column_name in columns_to_drop:
                batch.drop_column(column_name)
