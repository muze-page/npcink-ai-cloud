from __future__ import annotations

from pathlib import Path

from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import CommercialDecisionEvent, OperatorManagedTopupPackOverlay
from app.domain.commercial.errors import CommercialValidationError
from app.domain.commercial.service import (
    CommercialService,
    TOPUP_PACK_CATALOG_REQUEST_KIND,
    TOPUP_PACK_OVERLAY_DECISION_PREFIX,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'commercial-topup-pack-overlays.sqlite3'}"


def test_topup_pack_overlay_survives_more_than_fifty_newer_overlay_events(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CommercialService(database_url)
    service.update_operator_managed_points_pack(
        pack_id="pack_small",
        label="Starter durable buffer",
        points_label="11,000 points equivalent",
        runs_increment=11_000,
        tokens_increment=2_200_000,
        cost_increment=109,
        operator_note="Keep starter overage bounded without changing the package tier.",
        recommended_for_tiers=["starter"],
        display_order=1,
        active=True,
    )

    for iteration in range(60):
        service.update_operator_managed_points_pack(
            pack_id="pack_medium",
            label=f"Medium pack rev {iteration}",
            points_label=f"{35_000 + iteration} points equivalent",
            runs_increment=35_000 + iteration,
            tokens_increment=7_000_000 + iteration,
            cost_increment=349 + iteration,
            operator_note=f"Medium pack overlay revision {iteration}",
            recommended_for_tiers=["pro", "agency"],
            display_order=2,
            active=True,
        )

    items = service.list_admin_topup_packs()["items"]
    small_pack = next(item for item in items if item["pack_id"] == "pack_small")
    medium_pack = next(item for item in items if item["pack_id"] == "pack_medium")

    assert small_pack["label"] == "Starter durable buffer"
    assert small_pack["points_label"] == "11,000 points equivalent"
    assert small_pack["runs_increment"] == 11_000.0
    assert small_pack["recommended_for_tiers"] == ["starter"]
    assert small_pack["has_operator_overlay"] is True
    assert medium_pack["label"] == "Medium pack rev 59"

    dispose_engine(database_url)


def test_topup_pack_catalog_stays_bounded_to_three_fixed_pack_ids(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CommercialService(database_url)
    items = service.list_admin_topup_packs()["items"]

    assert [item["pack_id"] for item in items] == ["pack_small", "pack_medium", "pack_large"]

    dispose_engine(database_url)


def test_topup_pack_overlay_state_is_read_from_bounded_storage_not_decision_replay(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CommercialService(database_url)
    service.update_operator_managed_points_pack(
        pack_id="pack_small",
        label="Storage-owned buffer",
        points_label="13,000 points equivalent",
        runs_increment=13_000,
        tokens_increment=2_600_000,
        cost_increment=130,
        operator_note="bounded storage should stay canonical",
        recommended_for_tiers=["starter"],
        display_order=1,
        active=True,
    )

    with get_session(database_url) as session:
        session.add(
            CommercialDecisionEvent(
                request_kind=TOPUP_PACK_CATALOG_REQUEST_KIND,
                decision="allow",
                decision_code=f"{TOPUP_PACK_OVERLAY_DECISION_PREFIX}pack_small",
                payload_json={
                    "pack_id": "pack_small",
                    "overlay": {
                        "label": "Replay drifted buffer",
                        "points_label": "99,999 points equivalent",
                        "runs_increment": 99_999,
                        "tokens_increment": 9_999_999,
                        "cost_increment": 999,
                        "operator_note": "this should not become canonical again",
                        "recommended_for_tiers": ["agency"],
                        "display_order": 9,
                        "active": False,
                    },
                },
            )
        )
        session.commit()

    items = service.list_admin_topup_packs()["items"]
    small_pack = next(item for item in items if item["pack_id"] == "pack_small")

    assert small_pack["label"] == "Storage-owned buffer"
    assert small_pack["points_label"] == "13,000 points equivalent"
    assert small_pack["runs_increment"] == 13_000.0
    assert small_pack["active"] is True

    with get_session(database_url) as session:
        stored_overlay = session.get(OperatorManagedTopupPackOverlay, "pack_small")
        assert stored_overlay is not None
        assert stored_overlay.label == "Storage-owned buffer"

    dispose_engine(database_url)


def test_topup_pack_overlay_rejects_noncanonical_tiers(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)

    service = CommercialService(database_url)

    try:
        service.update_operator_managed_points_pack(
            pack_id="pack_small",
            label="Small pack",
            points_label="10,000 points equivalent",
            runs_increment=10_000,
            tokens_increment=2_000_000,
            cost_increment=99,
            operator_note="invalid tier test",
            recommended_for_tiers=["starter", "enterprise"],
            display_order=1,
            active=True,
        )
    except CommercialValidationError as error:
        assert error.error_code == "service.topup_pack_invalid_tiers"
    else:
        raise AssertionError("expected invalid tiers to be rejected")

    dispose_engine(database_url)
