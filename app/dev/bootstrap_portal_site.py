from __future__ import annotations

import argparse
import json

from app.core.config import Settings
from app.domain.commercial.customer_api_keys import build_customer_api_key
from app.domain.commercial.errors import CommercialNotFoundError
from app.domain.commercial.service import CommercialService
from app.domain.usage.service import UsageService

DEFAULT_PORTAL_SCOPES = [
    "catalog:read",
    "runtime:resolve",
    "runtime:execute",
    "runtime:read",
    "stats:read",
]


def _dict_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Bind a user to one existing Cloud site so the workspace can expose "
            "real site/subscription/usage/billing data."
        )
    )
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--site-admin-email", dest="principal_email", required=True)
    parser.add_argument("--public-base-url", default="http://127.0.0.1:8010")
    parser.add_argument(
        "--skip-billing-rebuild",
        action="store_true",
        help="Do not rebuild the current billing snapshot before returning the payload.",
    )
    parser.add_argument(
        "--issue-key",
        action="store_true",
        help="Issue a fresh site key for the portal walkthrough.",
    )
    parser.add_argument("--key-id", default="")
    parser.add_argument("--secret", default="")
    parser.add_argument("--key-label", default="Portal bootstrap key")
    parser.add_argument(
        "--scopes",
        default="catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read,entitlement:read",
        help="Comma-separated scopes for --issue-key",
    )
    return parser.parse_args()


def _normalized_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    return raw or "http://127.0.0.1:8010"


def bootstrap_portal_site(
    *,
    settings: Settings,
    site_id: str,
    principal_email: str,
    public_base_url: str,
    rebuild_billing_snapshot: bool,
    issue_key: bool,
    key_id: str,
    secret: str,
    key_label: str,
    scopes: list[str],
) -> dict[str, object]:
    commercial_service = CommercialService(settings.database_url, settings=settings)
    normalized_email = principal_email.strip().lower()
    base_url = _normalized_base_url(public_base_url)

    policy = commercial_service.inspect_commercial_policy(site_id)
    site = _dict_value(policy.get("site"))
    account_id = str(site.get("account_id") or "").strip()
    subscription = policy.get("subscription")
    if not account_id:
        raise CommercialNotFoundError(
            "service.portal_account_not_found",
            f"site '{site_id}' is not bound to an account",
        )
    if (
        not isinstance(subscription, dict)
        or not str(subscription.get("subscription_id") or "").strip()
    ):
        raise CommercialNotFoundError(
            "service.subscription_not_found",
            f"no subscription was found for site '{site_id}'",
        )

    account_membership = commercial_service.upsert_account_member_access(
        account_id=account_id,
        email=normalized_email,
        status="active",
        metadata_json={
            "source": "bootstrap_portal_site",
            "site_id": site_id,
        },
    )
    principal_id = str(account_membership.get("principal_id") or "")
    portal_sites = commercial_service.list_portal_sites(principal_id=principal_id)
    usage_summary = UsageService(settings.database_url).get_usage_summary(site_id=site_id)
    usage_meter = commercial_service.inspect_usage_meter(site_id)
    billing_snapshot = (
        commercial_service.rebuild_billing_snapshot(site_id) if rebuild_billing_snapshot else None
    )
    billing_snapshots = commercial_service.list_billing_snapshots(site_id)
    entitlements = commercial_service.inspect_commercial_policy(site_id)
    keys = commercial_service.list_site_keys(site_id)

    issued_key: dict[str, object] | None = None
    if issue_key:
        issued_key = commercial_service.issue_site_key(
            site_id=site_id,
            key_id=key_id or None,
            secret=secret or None,
            scopes=scopes or list(DEFAULT_PORTAL_SCOPES),
            label=key_label,
            expires_at=None,
            metadata_json={"source": "bootstrap_portal_site"},
        )
        keys = commercial_service.list_site_keys(site_id)

    auth_configured = bool(settings.portal_jwt_secret)

    result: dict[str, object] = {
        "environment": settings.environment,
        "project_name": settings.project_name,
        "public_base_url": base_url,
        "data_mode": "real_site_bootstrap",
        "sample_site": {
            "site_id": site_id,
            "account_id": account_id,
            "subscription_id": str(subscription.get("subscription_id") or ""),
            "plan_id": str(subscription.get("plan_id") or ""),
            "plan_version_id": str(subscription.get("plan_version_id") or ""),
            "principal_email": normalized_email,
            "principal_id": principal_id,
            "identity_type": "principal",
            "routes": {
                "login_url": f"{base_url}/portal/login",
                "portal_url": f"{base_url}/portal",
                "overview_url": f"{base_url}/portal/overview",
                "sites_url": f"{base_url}/portal/sites",
            },
            "auth_mode": "email_code",
            "login_code_request": {
                "email": normalized_email,
                "request_url": f"{base_url}/portal/v1/auth/code/request",
                "verify_url": f"{base_url}/portal/v1/auth/code/verify",
            },
            "auth_configured": auth_configured,
        },
        "portal": {
            "account_membership": account_membership,
            "sites": portal_sites,
        },
        "site_summary": {
            "site": entitlements.get("site"),
            "subscription": entitlements.get("subscription"),
            "plan_version": entitlements.get("plan_version"),
        },
        "usage_summary": usage_summary,
        "usage_meter": usage_meter,
        "billing_snapshot": billing_snapshot,
        "billing_snapshots": billing_snapshots,
        "entitlements": {
            "usage_totals": entitlements.get("usage_totals"),
            "budget_state": entitlements.get("budget_state"),
            "subscription_grace": entitlements.get("subscription_grace"),
            "policy": entitlements.get("policy"),
        },
        "site_keys": keys,
        "issued_key": issued_key,
    }

    if issued_key is not None:
        sample_site = _dict_value(result.get("sample_site"))
        sample_site["cloud_api_key"] = build_customer_api_key(
            site_id=site_id,
            key_id=str(issued_key.get("key_id") or ""),
            secret=str(issued_key.get("secret") or ""),
        )
        result["sample_site"] = sample_site

    return result


def main() -> None:
    args = parse_args()
    settings = Settings()
    scopes = [scope.strip() for scope in args.scopes.split(",") if scope.strip()]
    bootstrap_portal_site(
        settings=settings,
        site_id=args.site_id,
        principal_email=args.principal_email,
        public_base_url=args.public_base_url,
        rebuild_billing_snapshot=not args.skip_billing_rebuild,
        issue_key=args.issue_key,
        key_id=args.key_id,
        secret=args.secret,
        key_label=args.key_label,
        scopes=scopes,
    )
    print(
        json.dumps(
            {
                "status": "ok",
                "site_id": args.site_id,
                "issued_key_created": bool(args.issue_key),
                "secret_output": "redacted",
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
