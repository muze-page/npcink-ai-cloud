from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.adapters.providers.anthropic import AnthropicProviderAdapter
from app.adapters.providers.base import ProviderAdapter
from app.adapters.providers.litellm_gateway import LiteLLMGatewayProviderAdapter
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.providers.openrouter import OpenRouterProviderAdapter
from app.adapters.providers.tei import TEIProviderAdapter
from app.adapters.providers.vllm import VLLMProviderAdapter
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings
from app.core.db import get_session
from app.core.secrets import decrypt_provider_connection_secret

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
    providers = build_enabled_provider_connection_adapters(
        settings,
        source_roles=EXECUTION_PROVIDER_SOURCE_ROLES,
    )
    if not _is_production_like(settings):
        providers.update(
            build_provider_adapters(
                settings,
                include_enabled_connections=False,
            )
        )
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

    if include_enabled_connections:
        providers.update(
            build_enabled_provider_connection_adapters(
                settings,
                source_roles=connection_source_roles,
            )
        )

    return providers


def build_enabled_provider_connection_adapters(
    settings: Settings,
    *,
    source_roles: Iterable[str] | None = EXECUTION_PROVIDER_SOURCE_ROLES,
) -> dict[str, ProviderAdapter]:
    normalized_roles = _normalize_source_roles(source_roles)
    with get_session(settings.database_url) as session:
        repository = CatalogRepository(session)
        connections = repository.list_enabled_provider_connections(
            source_roles=normalized_roles,
        )

    providers: dict[str, ProviderAdapter] = {}
    for connection in connections:
        metadata = getattr(connection, "metadata_json", None) or {}
        credential_origin = str(metadata.get("credential_origin") or "").strip().lower()
        if _is_production_like(settings) and credential_origin != "cloud_local":
            continue
        if _is_production_like(settings):
            active_execution_revision = str(
                metadata.get("active_execution_revision") or ""
            ).strip()
            last_sync_revision = str(metadata.get("last_sync_revision") or "").strip()
            if not active_execution_revision or active_execution_revision != last_sync_revision:
                continue
        providers[str(connection.connection_id)] = build_provider_adapter_from_connection(
            connection,
            settings,
        )
    return providers


def build_provider_adapter_from_connection(
    connection: Any,
    settings: Settings,
) -> ProviderAdapter:
    config = dict(getattr(connection, "config_json", None) or {})
    provider_type = str(getattr(connection, "provider_type", "") or "").strip().lower()
    allow_sample_fallback = _allow_sample_provider_fallback(settings)
    api_key = decrypt_provider_connection_secret(
        getattr(connection, "secret_ciphertext", None),
        settings=settings,
    )
    timeout_seconds = _coerce_timeout(config.get("timeout_seconds"))
    base_url = str(getattr(connection, "base_url", "") or "").strip()

    if provider_type == "openai":
        adapter: ProviderAdapter = OpenAIProviderAdapter(
            base_url=base_url,
            api_key=api_key or None,
            organization=_coerce_string(config.get("organization")) or None,
            timeout_seconds=timeout_seconds,
            sample_catalog_profile="",
            app_name=settings.project_name,
            allow_sample_catalog=allow_sample_fallback,
            allow_sample_execution=allow_sample_fallback,
            model_namespace_prefix=str(getattr(connection, "connection_id", "") or ""),
        )
    elif provider_type == "anthropic":
        adapter = AnthropicProviderAdapter(
            base_url=base_url,
            api_key=api_key or None,
            api_version=_coerce_string(config.get("api_version")) or "2023-06-01",
            timeout_seconds=timeout_seconds,
            app_name=settings.project_name,
            allow_sample_catalog=allow_sample_fallback,
            allow_sample_execution=allow_sample_fallback,
        )
    elif provider_type == "litellm":
        adapter = LiteLLMGatewayProviderAdapter(
            base_url=base_url,
            api_key=api_key or None,
            timeout_seconds=timeout_seconds,
            app_name=settings.project_name,
        )
    elif provider_type == "vllm":
        adapter = VLLMProviderAdapter(
            base_url=base_url,
            api_key=api_key or None,
            timeout_seconds=timeout_seconds,
            app_name=settings.project_name,
        )
    elif provider_type == "tei":
        adapter = TEIProviderAdapter(
            base_url=base_url,
            api_key=api_key or None,
            timeout_seconds=timeout_seconds,
            model_ids=_coerce_string_list(config.get("model_ids")),
            region=_coerce_string(config.get("region")) or "self-hosted",
            context_window=_coerce_int(config.get("context_window"), 8192),
            app_name=settings.project_name,
        )
    elif provider_type == "openrouter":
        adapter = OpenRouterProviderAdapter(
            base_url=base_url,
            api_key=api_key or "",
            timeout_seconds=timeout_seconds,
            site_url=_coerce_string(config.get("site_url")) or None,
            app_name=settings.project_name,
        )
    else:
        raise ValueError(f"unsupported provider_type: {provider_type}")

    connection_id = str(getattr(connection, "connection_id", "") or "").strip()
    adapter.provider_id = connection_id
    adapter.display_name = str(getattr(connection, "display_name", "") or "")
    if hasattr(adapter, "model_namespace_prefix"):
        adapter.model_namespace_prefix = connection_id
    return adapter


def build_recognition_review_provider_adapters(
    settings: Settings,
) -> dict[str, ProviderAdapter]:
    profile = str(settings.openai_recognition_review_sample_catalog_profile or "").strip()
    if not profile:
        return {}
    return build_provider_adapters_with_overrides(
        settings,
        openai_sample_catalog_profile=profile,
    )


def _normalize_source_roles(source_roles: Iterable[str] | None) -> list[str] | None:
    if source_roles is None:
        return None
    return [
        str(role).strip().lower()
        for role in source_roles
        if str(role).strip()
    ]


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
        normalized = float(value)
    except (TypeError, ValueError):
        return 30.0
    return max(0.001, normalized)


def _coerce_int(value: object, default: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, normalized)


def _coerce_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []
