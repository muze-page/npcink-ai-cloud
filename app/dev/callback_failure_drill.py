from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.adapters.callbacks.base import (
    RuntimeCallbackDispatchError,
    RuntimeCallbackDispatchRequest,
    RuntimeCallbackDispatchResult,
)
from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderAdapter,
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import Site
from app.core.secrets import encrypt_runtime_terminal_callback_secret
from app.dev.seed_runtime import seed_site_auth
from app.domain.catalog.service import CatalogService
from app.domain.runtime.models import RuntimeRequest
from app.domain.runtime.service import RuntimeService


class SuccessfulProviderAdapter:
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
        output_text = "callback drill ok"
        return ProviderExecutionResult(
            output={
                "output_text": output_text,
                "messages": [{"role": "assistant", "content": output_text}],
                "model_id": request.model_id,
            },
            latency_ms=80,
            tokens_in=8,
            tokens_out=4,
            cost=0.0,
        )


class FailingCallbackDispatcher:
    def dispatch(
        self,
        request: RuntimeCallbackDispatchRequest,
    ) -> RuntimeCallbackDispatchResult:
        raise RuntimeCallbackDispatchError(
            "runtime.callback_delivery_failed",
            f"drill callback intentionally failed for run {request.run_id}",
            retryable=False,
            status_code=503,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an isolated callback-failure drill and print non-secret operator evidence."
        )
    )
    parser.add_argument("--site-id", default="site_callback_failure_drill")
    parser.add_argument("--key-id", default="key_callback_failure_drill")
    parser.add_argument("--secret", default="callback-failure-drill-secret-32b")
    parser.add_argument("--callback-url", default="https://example.com/runtime-callback")
    parser.add_argument("--recent-minutes", type=int, default=60)
    return parser.parse_args()


def _dict_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _settings(database_url: str) -> Settings:
    settings_kwargs: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": "callback-failure-drill-internal-token-32b",
        "dev_admin_key": "callback-failure-drill-admin-key-32b",
        "admin_session_secret": "callback-failure-drill-admin-session-secret-32b",
        "portal_jwt_secret": "callback-failure-drill-portal-jwt-secret-32b",
        "openai_api_key": None,
    }
    return Settings(**settings_kwargs)


def _register_runtime_callback(
    *,
    database_url: str,
    settings: Settings,
    site_id: str,
    callback_url: str,
) -> None:
    metadata = {
        "source": "callback_failure_drill",
        "runtime_callbacks": {
            "terminal": {
                "enabled": True,
                "callback_url": callback_url,
                "key_id": "runtime_callback_key",
                "secret_ciphertext": encrypt_runtime_terminal_callback_secret(
                    "runtime-callback-secret-for-drill-32b",
                    settings=settings,
                ),
                "callback_id": "runtime-terminal-callback-failure-drill",
            }
        },
    }
    with get_session(database_url) as session:
        site = session.get(Site, site_id)
        if site is None:
            raise RuntimeError(f"site was not provisioned: {site_id}")
        site.metadata_json = metadata
        session.commit()


def run_drill(
    *,
    site_id: str,
    key_id: str,
    secret: str,
    callback_url: str,
    recent_minutes: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="magick-callback-failure-drill-") as tmp_dir:
        database_url = f"sqlite+pysqlite:///{Path(tmp_dir) / 'drill.sqlite3'}"
        settings = _settings(database_url)
        providers: dict[str, ProviderAdapter] = {"openai": SuccessfulProviderAdapter()}
        init_schema(database_url)
        CatalogService(database_url, providers=providers).refresh_catalog()
        CatalogService(database_url, providers=providers).scan_provider_health()
        seed_site_auth(
            settings=settings,
            site_id=site_id,
            key_id=key_id,
            secret=secret,
            site_name="Callback failure drill",
            scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
        )
        _register_runtime_callback(
            database_url=database_url,
            settings=settings,
            site_id=site_id,
            callback_url=callback_url,
        )

        service = RuntimeService(
            database_url,
            providers=providers,
            settings=settings,
            callback_dispatcher=FailingCallbackDispatcher(),
            callback_max_attempts=1,
            callback_retry_backoff_seconds=0,
        )
        response = service.execute(
            RuntimeRequest(
                site_id=site_id,
                ability_name="npcink-abilities-toolkit/build-article-block-plan",
                ability_family="workflow",
                channel="openapi",
                execution_kind="text",
                profile_id="text.balanced",
                task_backend={
                    "enabled": True,
                    "mode": "polling",
                    "callback_mode": "polling_preferred",
                },
                idempotency_key=(
                    "callback-failure-drill-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
                ),
                trace_id="callbackfailuredrill0000000000",
                input_payload={
                    "messages": [
                        {
                            "role": "user",
                            "content": "force callback failure drill",
                        }
                    ]
                },
                policy={"allow_fallback": False},
            )
        )
        dispatch_results = service.dispatch_pending_callbacks(max_callbacks=1)
        run = service.get_run(response.run_id, site_id=site_id)
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
                "provider_call_count": response.provider_call_count,
                "callback": _dict_value(_dict_value(run.get("run_lifecycle")).get("callback")),
            },
            "callback_dispatch": dispatch_results,
            "diagnostics": {
                "callback": diagnostics.get("callback"),
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
        callback_url=args.callback_url,
        recent_minutes=max(1, int(args.recent_minutes)),
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
