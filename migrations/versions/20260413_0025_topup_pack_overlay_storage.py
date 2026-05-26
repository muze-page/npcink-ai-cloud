"""store bounded operator-managed top-up pack overlays outside decision events"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260413_0025"
down_revision = "20260413_0024"
branch_labels = None
depends_on = None

TOPUP_PACK_CATALOG_REQUEST_KIND = "topup_pack_catalog"
TOPUP_PACK_OVERLAY_DECISION_PREFIX = "topup_pack_catalog.overlay."
TOPUP_PACK_EDITABLE_FIELDS = {
    "label",
    "points_label",
    "runs_increment",
    "tokens_increment",
    "cost_increment",
    "operator_note",
    "recommended_for_tiers",
    "display_order",
    "active",
}
CANONICAL_PACK_IDS = ("pack_small", "pack_medium", "pack_large")


def _coerce_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_overlay(payload: Any) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {}
    overlay = payload.get("overlay")
    if not isinstance(overlay, dict):
        return {}
    result = {key: overlay[key] for key in TOPUP_PACK_EDITABLE_FIELDS if key in overlay}
    tiers = result.get("recommended_for_tiers")
    if isinstance(tiers, list):
        result["recommended_for_tiers"] = [str(item or "").strip() for item in tiers if str(item or "").strip()]
    else:
        result["recommended_for_tiers"] = []
    result["label"] = str(result.get("label") or "")
    result["points_label"] = str(result.get("points_label") or "")
    result["runs_increment"] = round(max(0.0, _coerce_float(result.get("runs_increment"))), 6)
    result["tokens_increment"] = round(max(0.0, _coerce_float(result.get("tokens_increment"))), 6)
    result["cost_increment"] = round(max(0.0, _coerce_float(result.get("cost_increment"))), 6)
    result["operator_note"] = str(result.get("operator_note") or "")
    result["display_order"] = max(1, int(result.get("display_order") or 1))
    result["active"] = bool(result.get("active", True))
    return result


def upgrade() -> None:
    op.create_table(
        "operator_managed_topup_pack_overlays",
        sa.Column("pack_id", sa.String(length=191), primary_key=True, nullable=False),
        sa.Column("label", sa.String(length=191), nullable=False, server_default=""),
        sa.Column("points_label", sa.String(length=191), nullable=False, server_default=""),
        sa.Column("runs_increment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tokens_increment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_increment", sa.Float(), nullable=False, server_default="0"),
        sa.Column("operator_note", sa.Text(), nullable=False, server_default=""),
        sa.Column("recommended_for_tiers_json", sa.JSON(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_operator_managed_topup_pack_overlays_updated_at",
        "operator_managed_topup_pack_overlays",
        ["updated_at"],
    )

    bind = op.get_bind()
    metadata = sa.MetaData()
    decision_events = sa.Table(
        "commercial_decision_events",
        metadata,
        sa.Column("id", sa.Integer()),
        sa.Column("request_kind", sa.String(length=32)),
        sa.Column("decision_code", sa.String(length=64)),
        sa.Column("payload_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )
    overlays = sa.Table(
        "operator_managed_topup_pack_overlays",
        metadata,
        sa.Column("pack_id", sa.String(length=191)),
        sa.Column("label", sa.String(length=191)),
        sa.Column("points_label", sa.String(length=191)),
        sa.Column("runs_increment", sa.Float()),
        sa.Column("tokens_increment", sa.Float()),
        sa.Column("cost_increment", sa.Float()),
        sa.Column("operator_note", sa.Text()),
        sa.Column("recommended_for_tiers_json", sa.JSON()),
        sa.Column("display_order", sa.Integer()),
        sa.Column("active", sa.Boolean()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )

    rows = bind.execute(
        sa.select(
            decision_events.c.id,
            decision_events.c.decision_code,
            decision_events.c.payload_json,
            decision_events.c.created_at,
        )
        .where(decision_events.c.request_kind == TOPUP_PACK_CATALOG_REQUEST_KIND)
        .order_by(decision_events.c.created_at.desc(), decision_events.c.id.desc())
    ).mappings().all()

    seen: set[str] = set()
    for row in rows:
        payload = row["payload_json"] if isinstance(row["payload_json"], dict) else {}
        pack_id = str(payload.get("pack_id") or "").strip()
        if (
            not pack_id
            or pack_id in seen
            or pack_id not in CANONICAL_PACK_IDS
            or not str(row["decision_code"] or "").startswith(TOPUP_PACK_OVERLAY_DECISION_PREFIX)
        ):
            continue
        overlay = _normalize_overlay(payload)
        if not overlay:
            continue
        bind.execute(
            sa.insert(overlays).values(
                pack_id=pack_id,
                label=str(overlay.get("label") or ""),
                points_label=str(overlay.get("points_label") or ""),
                runs_increment=float(overlay.get("runs_increment") or 0.0),
                tokens_increment=float(overlay.get("tokens_increment") or 0.0),
                cost_increment=float(overlay.get("cost_increment") or 0.0),
                operator_note=str(overlay.get("operator_note") or ""),
                recommended_for_tiers_json=list(overlay.get("recommended_for_tiers") or []),
                display_order=int(overlay.get("display_order") or 1),
                active=bool(overlay.get("active", True)),
                updated_at=row["created_at"] or datetime.now(UTC),
            )
        )
        seen.add(pack_id)


def downgrade() -> None:
    op.drop_index(
        "ix_operator_managed_topup_pack_overlays_updated_at",
        table_name="operator_managed_topup_pack_overlays",
    )
    op.drop_table("operator_managed_topup_pack_overlays")
