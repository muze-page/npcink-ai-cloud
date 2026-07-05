from __future__ import annotations

import argparse
import json

from app.adapters.providers.registry import build_provider_adapters
from app.core.config import Settings
from app.core.security import build_secret_hash
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed one hosted runtime site + key for local smoke runs."
    )
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--key-id", default="key_default")
    parser.add_argument("--secret", required=True)
    parser.add_argument("--site-name", default="")
    parser.add_argument(
        "--scopes",
        default="catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read,entitlement:read",
        help="Comma-separated API key scopes",
    )
    parser.add_argument(
        "--skip-catalog-refresh",
        action="store_true",
        help="Skip provider catalog refresh/bootstrap",
    )
    parser.add_argument(
        "--skip-health-scan",
        action="store_true",
        help="Skip provider health snapshot scan",
    )
    return parser.parse_args()


def seed_site_auth(
    *,
    settings: Settings,
    site_id: str,
    key_id: str,
    secret: str,
    site_name: str,
    scopes: list[str],
    account_id: str | None = None,
    plan_id: str = "free",
    plan_version_id: str = "free_v1",
    subscription_id: str | None = None,
) -> dict[str, object]:
    result = CommercialService(settings.database_url, settings=settings).provision_runtime_baseline(
        site_id=site_id,
        key_id=key_id,
        secret=secret,
        site_name=site_name or site_id,
        scopes=scopes,
        account_id=account_id,
        plan_id=plan_id,
        plan_version_id=plan_version_id,
        subscription_id=subscription_id,
    )
    result["secret_hash"] = build_secret_hash(secret)
    return result


def main() -> None:
    args = parse_args()
    settings = Settings()
    catalog_service = CatalogService(
        settings.database_url,
        providers=build_provider_adapters(settings),
    )
    scopes = [scope.strip() for scope in args.scopes.split(",") if scope.strip()]

    result: dict[str, object] = {
        "environment": settings.environment,
        "database_url": settings.database_url,
    }

    if not args.skip_catalog_refresh:
        result["catalog"] = catalog_service.refresh_catalog()
    if not args.skip_health_scan:
        result["health"] = catalog_service.scan_provider_health()

    result["auth"] = seed_site_auth(
        settings=settings,
        site_id=args.site_id,
        key_id=args.key_id,
        secret=args.secret,
        site_name=args.site_name,
        scopes=scopes,
    )

    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
