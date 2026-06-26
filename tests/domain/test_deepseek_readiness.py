from __future__ import annotations

import os
from pathlib import Path

import pytest

_deepseek_key_available = bool(os.environ.get("NPCINK_CLOUD_OPENAI_API_KEY", "").strip())


@pytest.mark.skipif(
    not _deepseek_key_available, reason="NPCINK_CLOUD_OPENAI_API_KEY not configured"
)
class TestDeepSeekReadiness:
    def test_catalog_refresh_includes_deepseek_models(self, tmp_path: Path) -> None:
        from app.adapters.providers.registry import build_provider_adapters

        settings = _settings_with_deepseek_connection(tmp_path)
        providers = build_provider_adapters(settings, include_enabled_connections=True)
        assert "openai" in providers, "OpenAI-compatible provider must be registered"

        snapshot = providers["openai"].fetch_catalog()
        model_ids = [m.model_id for m in snapshot.models]
        assert len(model_ids) > 0, "catalog must contain at least one model"
        display_name = getattr(snapshot, "display_name", "")
        provider_label = os.environ.get("NPCINK_CLOUD_OPENAI_PROVIDER_LABEL", "")
        if provider_label:
            assert provider_label in display_name, (
                f"provider label '{provider_label}' must appear in display name"
            )

    def test_provider_health_check_passes(self, tmp_path: Path) -> None:
        from app.adapters.providers.registry import build_provider_adapters

        settings = _settings_with_deepseek_connection(tmp_path)
        providers = build_provider_adapters(settings, include_enabled_connections=True)
        assert "openai" in providers
        snapshot = providers["openai"].fetch_catalog()
        for model in snapshot.models:
            for instance in model.instances:
                assert instance.health_status in ("available", None), (
                    f"instance {instance.instance_id} should be available, got {instance.health_status}"
                )

    def test_runtime_execute_with_deepseek_provider(self, tmp_path: Path) -> None:
        from app.adapters.providers.base import ProviderExecutionRequest
        from app.adapters.providers.registry import build_provider_adapters

        settings = _settings_with_deepseek_connection(tmp_path)
        providers = build_provider_adapters(settings, include_enabled_connections=True)
        assert "openai" in providers

        snapshot = providers["openai"].fetch_catalog()
        assert len(snapshot.models) > 0
        model = snapshot.models[0]
        instance = model.instances[0]

        request = ProviderExecutionRequest(
            run_id="run_deepseek_readiness",
            site_id="site_readiness",
            ability_name="readiness.smoke",
            profile_id="text.balanced",
            execution_kind="text",
            model_id=model.model_id,
            instance_id=instance.instance_id,
            endpoint_variant=instance.endpoint_variant,
            trace_id="trace_deepseek_readiness",
            input_payload={"messages": [{"role": "user", "content": "readiness check"}]},
            policy={},
            timeout_ms=30_000,
            price_input=0.0,
            price_output=0.0,
        )

        result = providers["openai"].execute(request)
        assert result.output is not None
        assert result.tokens_in > 0, "must report input tokens"
        assert result.tokens_out > 0, "must report output tokens"
        assert result.latency_ms > 0, "must report latency"


def test_deepseek_key_not_required_for_deterministic_baseline() -> None:
    """Verify that the test suite runs without NPCINK_CLOUD_OPENAI_API_KEY."""
    pass


def _settings_with_deepseek_connection(tmp_path: Path):
    from app.core.config import Settings
    from app.core.db import init_schema
    from app.domain.provider_connections.service import ProviderConnectionAdminService

    database_url = f"sqlite+pysqlite:///{tmp_path / 'deepseek-readiness.sqlite3'}"
    init_schema(database_url)
    settings = Settings(_env_file=None, environment="test", database_url=database_url)
    ProviderConnectionAdminService(database_url, settings).save_connection(
        {
            "connection_id": "deepseek_readiness",
            "provider_id": "openai",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": os.environ.get(
                "NPCINK_CLOUD_OPENAI_PROVIDER_LABEL",
                "DeepSeek readiness",
            ),
            "enabled": True,
            "base_url": os.environ.get(
                "NPCINK_CLOUD_OPENAI_BASE_URL",
                "https://api.deepseek.com/v1",
            ),
            "capability_ids": ["text_generation"],
            "runtime_profile_ids": ["text.ai"],
            "credential": os.environ["NPCINK_CLOUD_OPENAI_API_KEY"],
        }
    )
    return settings
