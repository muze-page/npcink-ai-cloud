from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_portal_runtime_has_one_account_membership_authorization_source() -> None:
    app_sources = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted((ROOT / "app").rglob("*.py"))
    )
    assert "site_user_grants" not in app_sources
    assert "SiteUserGrant" not in app_sources

    service_routes = (ROOT / "app/api/routes/service.py").read_text(encoding="utf-8")
    assert '@router.post("/accounts/{account_id}/members")' in service_routes
    assert "/sites/{site_id}/user-grants" not in service_routes


def test_site_grant_drop_migration_fails_closed_when_rows_exist() -> None:
    migration = (
        ROOT / "migrations/versions/20260710_0057_account_membership_authorization.py"
    ).read_text(encoding="utf-8")
    assert 'SELECT COUNT(*) FROM site_user_grants' in migration
    assert "site_user_grants must be empty" in migration
    assert 'op.drop_table("site_user_grants")' in migration


def test_addon_login_keeps_complete_portal_return_path() -> None:
    session_boundary = (
        ROOT / "frontend/src/components/portal/PortalSessionBoundary.tsx"
    ).read_text(encoding="utf-8")
    assert "const returnTo = `${pathname}${window.location.search}`" in session_boundary
    assert "`/portal/login?redirect=${encodeURIComponent(returnTo)}`" in session_boundary
