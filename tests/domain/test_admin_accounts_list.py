from __future__ import annotations

from pathlib import Path

from app.core.db import dispose_engine, init_schema
from app.domain.commercial.service import CommercialService


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'admin-accounts-list.sqlite3'}"


def test_list_admin_accounts_filters_by_operator_search(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = CommercialService(database_url)

    service.upsert_account(
        account_id="acct_zeta",
        name="Zeta Account",
        metadata_json={
            "operator_display_name": "Beta Customer",
            "operator_note": "Launch review",
        },
    )
    service.upsert_account(
        account_id="acct_alpha",
        name="Alpha Account",
        metadata_json={
            "operator_display_name": "Alpha Customer",
            "operator_note": "Stable",
        },
    )

    result = service.list_admin_accounts(q="beta launch", sort="display_name", limit=10)

    assert result["filters"]["q"] == "beta launch"
    assert result["filters"]["sort"] == "display_name"
    assert result["total"] == 1
    assert [item["account"]["account_id"] for item in result["items"]] == ["acct_zeta"]

    dispose_engine(database_url)


def test_list_admin_accounts_sorts_and_paginates_after_filtering(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = CommercialService(database_url)

    service.upsert_account(
        account_id="acct_zeta",
        name="Zeta Account",
        metadata_json={"operator_display_name": "Beta Customer"},
    )
    service.upsert_account(
        account_id="acct_alpha",
        name="Alpha Account",
        metadata_json={"operator_display_name": "Alpha Customer"},
    )

    result = service.list_admin_accounts(sort="display_name", offset=1, limit=1)

    assert result["filters"]["offset"] == 1
    assert result["total"] == 2
    assert [item["account"]["account_id"] for item in result["items"]] == ["acct_zeta"]

    dispose_engine(database_url)


def test_list_admin_accounts_can_exclude_internal_records_before_pagination(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    service = CommercialService(database_url)

    service.upsert_account(account_id="acct_smoke_alpha", name="Smoke Alpha")
    service.upsert_account(account_id="acct_customer", name="Customer")

    result = service.list_admin_accounts(
        exclude_internal=True,
        sort="display_name",
        offset=0,
        limit=1,
    )

    assert result["hidden_internal_total"] == 1
    assert result["total"] == 1
    assert result["pagination"] == {
        "offset": 0,
        "limit": 1,
        "total": 1,
        "has_more": False,
    }
    assert [item["account"]["account_id"] for item in result["items"]] == [
        "acct_customer"
    ]

    dispose_engine(database_url)
