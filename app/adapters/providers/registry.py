from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from app.adapters.providers.anthropic import AnthropicProviderAdapter
from app.adapters.providers.base import ProviderAdapter
from app.adapters.providers.litellm_gateway import LiteLLMGatewayProviderAdapter
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.providers.openrouter import OpenRouterProviderAdapter
from app.adapters.providers.siliconflow import SiliconFlowProviderAdapter
from app.adapters.providers.tei import TEIProviderAdapter
from app.adapters.providers.vllm import VLLMProviderAdapter
from app.core.config import Settings

EXECUTION_PROVIDER_SOURCE_ROLES = frozenset({"execution_source", "dual_source"})
PRODUCTION_LIKE_ENVIRONMENTS = frozenset({"production", "prod", "staging"})


def build_provider_adapters(
    settings: Settings,
    *,
    include_enabled_connections: bool = False,
    connection_source_roles: Iterable[str] | None = EXECUTION_PROVIDER_SOURCE_ROLES,
) -> dict[str, ProviderAdapter]:
    return build_provider_adapters_with_overrides(
        settings,
        include_enabled_connections=include_enabled_connections,
        connection_source_roles=connection_source_roles,
    )


def resolve_live_provider_adapters(
    settings: Settings,
    *,
    base_providers: dict[str, ProviderAdapter] | None = None,
    include_enabled_connections: bool = False,
    connection_source_roles: Iterable[str] | None = EXECUTION_PROVIDER_SOURCE_ROLES,
) -> dict[str, ProviderAdapter]:
    providers = build_provider_adapters(
        settings,
        include_enabled_connections=include_enabled_connections,
        connection_source_roles=connection_source_roles,
    )
    if base_providers:
        providers.update(base_providers)
    return providers


def resolve_execution_provider_adapters(
    settings: Settings,
    *,
    base_providers: dict[str, ProviderAdapter] | None = None,
) -> dict[str, ProviderAdapter]:
    providers = build_provider_adapters(settings)
    if base_providers:
        providers.update(base_providers)
    return providers


def build_provider_adapters_with_overrides(
    settings: Settings,
    *,
    openai_sample_catalog_profile: str | None = None,
    include_enabled_connections: bool = False,
    connection_source_roles: Iterable[str] | None = EXECUTION_PROVIDER_SOURCE_ROLES,
) -> dict[str, ProviderAdapter]:
    providers: dict[str, ProviderAdapter] = {}
    allow_sample_fallback = _allow_sample_provider_fallback(settings)

    if settings.openai_api_key or allow_sample_fallback:
        providers[OpenAIProviderAdapter.provider_id] = OpenAIProviderAdapter(
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            organization=settings.openai_organization,
            timeout_seconds=settings.openai_timeout_seconds,
            sample_catalog_profile=(
                settings.openai_sample_catalog_profile
                if openai_sample_catalog_profile is None
                else openai_sample_catalog_profile
            ),
            app_name=settings.project_name,
            allow_sample_catalog=allow_sample_fallback,
            allow_sample_execution=allow_sample_fallback,
            provider_label=settings.openai_provider_label,
        )

    if settings.anthropic_api_key:
        providers[AnthropicProviderAdapter.provider_id] = AnthropicProviderAdapter(
            base_url=settings.anthropic_base_url,
            api_key=settings.anthropic_api_key,
            api_version=settings.anthropic_version,
            timeout_seconds=settings.anthropic_timeout_seconds,
            app_name=settings.project_name,
            allow_sample_catalog=allow_sample_fallback,
            allow_sample_execution=allow_sample_fallback,
        )

    if settings.litellm_provider_enabled:
        providers[LiteLLMGatewayProviderAdapter.provider_id] = LiteLLMGatewayProviderAdapter(
            base_url=str(settings.litellm_base_url or "").strip(),
            api_key=settings.litellm_api_key,
            timeout_seconds=settings.litellm_timeout_seconds,
            app_name=settings.project_name,
        )

    if settings.vllm_provider_enabled:
        providers[VLLMProviderAdapter.provider_id] = VLLMProviderAdapter(
            base_url=str(settings.vllm_base_url or "").strip(),
            api_key=settings.vllm_api_key,
            timeout_seconds=settings.vllm_timeout_seconds,
            app_name=settings.project_name,
        )

    if settings.tei_provider_enabled:
        tei_model_ids = [
            item.strip()
            for item in str(settings.tei_model_ids or "").split(",")
            if item.strip()
        ]
        providers[TEIProviderAdapter.provider_id] = TEIProviderAdapter(
            base_url=str(settings.tei_base_url or "").strip(),
            api_key=settings.tei_api_key,
            timeout_seconds=settings.tei_timeout_seconds,
            model_ids=tei_model_ids,
            region=settings.tei_region,
            context_window=settings.tei_context_window,
            app_name=settings.project_name,
        )

    if settings.openrouter_provider_enabled:
        providers[OpenRouterProviderAdapter.provider_id] = OpenRouterProviderAdapter(
            base_url=settings.openrouter_base_url,
            api_key=str(settings.openrouter_api_key or "").strip(),
            timeout_seconds=settings.openrouter_timeout_seconds,
            site_url=settings.openrouter_site_url,
            app_name=settings.project_name,
        )

    if settings.siliconflow_provider_enabled:
        providers[SiliconFlowProviderAdapter.provider_id] = SiliconFlowProviderAdapter(
            base_url=settings.siliconflow_base_url,
            api_key=str(settings.siliconflow_api_key or "").strip(),
            timeout_seconds=settings.siliconflow_timeout_seconds,
            app_name=settings.project_name,
        )

    return providers



def _allow_sample_provider_fallback(settings: Settings) -> bool:
    environment = str(settings.environment or "").strip().lower()
    return environment in {"development", "dev", "test"}


def _is_production_like(settings: Settings) -> bool:
    environment = str(settings.environment or "").strip().lower()
    return environment in PRODUCTION_LIKE_ENVIRONMENTS


def _coerce_string(value: object) -> str:
    return str(value or "").strip()


def _coerce_timeout(value: object) -> float:
    try:
        normalized = float(cast(Any, value))
    except (TypeError, ValueError):
        return 30.0
    return max(0.001, normalized)


def _coerce_int(value: object, default: int) -> int:
    try:
        normalized = int(cast(Any, value))
    except (TypeError, ValueError):
        return default
    return max(1, normalized)


def _coerce_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []
