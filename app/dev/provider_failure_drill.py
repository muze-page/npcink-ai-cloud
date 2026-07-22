from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderAdapter,
    ProviderCatalogSnapshot,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.dev.seed_runtime import seed_site_auth
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService


class FailingProviderAdapter:
    provider_id = "openai"
    display_name = "OpenAI-compatible drill provider"
    adapter_type = "openai_compatible_drill"

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id="deepseek-v4-flash",
                    family="deepseek",
                    feature="text",
                    status="available",
                    context_window=128000,
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="openai-global-deepseek-v4-flash",
                            endpoint_variant="chat_completions",
                            region="global",
                            capability_tags=["text", "balanced"],
                            health_status="healthy",
                            is_default=True,
                        )
                    ],
                )
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        raise ProviderExecutionError(
            "provider.auth_invalid",
            "drill provider intentionally rejected the request",
            retryable=False,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an isolated provider-failure drill and print non-secret operator evidence."
        )
    )
    parser.add_argument("--site-id", default="site_provider_failure_drill")
    parser.add_argument("--key-id", default="key_provider_failure_drill")
    parser.add_argument("--secret", default="provider-failure-drill-secret-32b")
    parser.add_argument("--recent-minutes", type=int, default=60)
    return parser.parse_args()


def _settings(database_url: str) -> Settings:
    settings_kwargs: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": "provider-failure-drill-internal-token-32b",
        "dev_admin_key": "provider-failure-drill-admin-key-32b",
        "admin_session_secret": "provider-failure-drill-admin-session-secret-32b",
        "portal_jwt_secret": "provider-failure-drill-portal-jwt-secret-32b",
        "openai_api_key": None,
    }
    return Settings(**settings_kwargs)


def run_drill(
    *,
    site_id: str,
    key_id: str,
    secret: str,
    recent_minutes: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="magick-provider-failure-drill-") as tmp_dir:
        database_url = f"sqlite+pysqlite:///{Path(tmp_dir) / 'drill.sqlite3'}"
        settings = _settings(database_url)
        providers: dict[str, ProviderAdapter] = {"openai": FailingProviderAdapter()}
        init_schema(database_url)
        CatalogService(database_url, providers=providers).refresh_catalog()
        CatalogService(database_url, providers=providers).scan_provider_health()
        seed_site_auth(
            settings=settings,
            site_id=site_id,
            key_id=key_id,
            secret=secret,
            site_name="Provider failure drill",
            scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
        )

        service = RuntimeService(database_url, providers=providers, settings=settings)
        response = service.execute(
            RuntimeRequest(
                site_id=site_id,
                ability_name="npcink-abilities-toolkit/build-article-block-plan",
                channel="openapi",
                execution_kind="text",
                profile_id="text.balanced",
                idempotency_key=(
                    "provider-failure-drill-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
                ),
                trace_id="providerfailuredrill000000000000",
                input_payload={
                    "messages": [
                        {
                            "role": "user",
                            "content": "force provider failure drill",
                        }
                    ]
                },
                policy={"allow_fallback": False},
            )
        )
        diagnostics = service.get_runtime_diagnostics_summary(
            site_id=site_id,
            recent_minutes=recent_minutes,
        )

        evidence = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "site_id": site_id,
            "run": {
                "run_id": response.run_id,
                "status": response.status,
                "provider_id": response.provider_id,
                "model_id": response.model_id,
                "instance_id": response.instance_id,
                "error_code": response.error_code,
                "error_stage": response.error_stage,
                "retryable": response.retryable,
                "retry_exhausted": response.retry_exhausted,
                "provider_call_count": response.provider_call_count,
            },
            "diagnostics": {
                "failures": diagnostics.get("failures"),
                "operator_guidance": diagnostics.get("operator_guidance"),
            },
        }
        dispose_engine(database_url)
        return evidence


def main() -> None:
    args = parse_args()
    evidence = run_drill(
        site_id=args.site_id,
        key_id=args.key_id,
        secret=args.secret,
        recent_minutes=max(1, int(args.recent_minutes)),
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
