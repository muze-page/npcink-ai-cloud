from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.providers.anthropic import AnthropicProviderAdapter
from app.adapters.providers.base import ProviderAdapter
from app.adapters.providers.litellm_gateway import LiteLLMGatewayProviderAdapter
from app.adapters.providers.minimax import MiniMaxProviderAdapter
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.providers.openrouter import OpenRouterProviderAdapter
from app.adapters.providers.siliconflow import SiliconFlowProviderAdapter
from app.adapters.providers.tei import TEIProviderAdapter
from app.adapters.providers.vllm import VLLMProviderAdapter
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderConnection
from app.core.secrets import decrypt_provider_connection_secret

EXECUTION_PROVIDER_SOURCE_ROLES = frozenset({"execution_source", "dual_source"})
PRODUCTION_LIKE_ENVIRONMENTS = frozenset({"production", "prod", "staging"})
OPENAI_COMPATIBLE_CONNECTION_KINDS = frozenset(
    {
        "openai",
        "openai_compatible",
        "openai-compatible",
        "text_provider",
        "image_generation_provider",
    }
)


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
        include_enabled_connections=False,
        connection_source_roles=connection_source_roles,
    )
    if base_providers:
        providers.update(base_providers)
    if include_enabled_connections:
        providers.update(
            build_enabled_connection_provider_adapters(
                settings,
                connection_source_roles=connection_source_roles,
            )
        )
    return providers


def resolve_execution_provider_adapters(
    settings: Settings,
    *,
    base_providers: dict[str, ProviderAdapter] | None = None,
) -> dict[str, ProviderAdapter]:
    providers = build_provider_adapters(settings, include_enabled_connections=False)
    if base_providers:
        providers.update(base_providers)
    providers.update(
        build_enabled_connection_provider_adapters(
            settings,
            connection_source_roles=EXECUTION_PROVIDER_SOURCE_ROLES,
        )
    )
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

    if settings.minimax_provider_enabled or settings.minimax_api_key:
        providers[MiniMaxProviderAdapter.provider_id] = MiniMaxProviderAdapter(
            base_url=settings.minimax_base_url,
            api_key=settings.minimax_api_key,
            group_id=settings.minimax_group_id,
            timeout_seconds=settings.minimax_timeout_seconds,
            default_voice_id=settings.minimax_default_voice_id,
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
            item.strip() for item in str(settings.tei_model_ids or "").split(",") if item.strip()
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

    if include_enabled_connections:
        providers.update(
            build_enabled_connection_provider_adapters(
                settings,
                connection_source_roles=connection_source_roles,
            )
        )

    return providers


def build_enabled_connection_provider_adapters(
    settings: Settings,
    *,
    connection_source_roles: Iterable[str] | None = EXECUTION_PROVIDER_SOURCE_ROLES,
) -> dict[str, ProviderAdapter]:
    providers: dict[str, ProviderAdapter] = {}
    for connection in _load_enabled_provider_connections(
        settings,
        connection_source_roles=connection_source_roles,
    ):
        adapter = _build_provider_adapter_from_connection(settings, connection)
        if adapter is not None:
            providers[adapter.provider_id] = adapter
    return providers


def build_provider_adapter_from_connection(
    settings: Settings,
    connection: ProviderConnection,
) -> ProviderAdapter | None:
    return _build_provider_adapter_from_connection(settings, connection)


def _allow_sample_provider_fallback(settings: Settings) -> bool:
    environment = str(settings.environment or "").strip().lower()
    return environment in {"development", "dev", "test"}


def _load_enabled_provider_connections(
    settings: Settings,
    *,
    connection_source_roles: Iterable[str] | None,
) -> list[ProviderConnection]:
    database_url = _coerce_string(getattr(settings, "database_url", ""))
    if not database_url:
        return []

    try:
        with get_session(database_url) as session:
            statement = select(ProviderConnection).where(ProviderConnection.enabled.is_(True))
            source_roles = {_coerce_string(role) for role in connection_source_roles or []}
            source_roles.discard("")
            if source_roles:
                statement = statement.where(ProviderConnection.source_role.in_(source_roles))
            return list(session.scalars(statement.order_by(ProviderConnection.connection_id.asc())))
    except SQLAlchemyError:
        return []


def _build_provider_adapter_from_connection(
    settings: Settings,
    connection: ProviderConnection,
) -> ProviderAdapter | None:
    config = connection.config_json if isinstance(connection.config_json, dict) else {}
    provider_id = _coerce_string(config.get("provider_id") or connection.connection_id)
    if not provider_id:
        return None

    kind = _coerce_string(config.get("kind") or connection.provider_type).lower()
    base_url = _coerce_string(connection.base_url)
    secretless = bool(config.get("secretless"))
    credential = _decrypt_connection_credential(settings, connection)
    if not credential and not _connection_kind_allows_secretless(kind, secretless=secretless):
        return None

    adapter = _instantiate_connection_adapter(
        settings,
        provider_id=provider_id,
        display_name=_coerce_string(connection.display_name) or provider_id,
        kind=kind,
        base_url=base_url,
        credential=credential,
        secretless=secretless,
        config=config,
    )
    return adapter


def _decrypt_connection_credential(
    settings: Settings,
    connection: ProviderConnection,
) -> str:
    ciphertext = _coerce_string(connection.secret_ciphertext)
    if not ciphertext:
        return ""
    try:
        return decrypt_provider_connection_secret(ciphertext, settings=settings)
    except RuntimeError:
        return ""


def _instantiate_connection_adapter(
    settings: Settings,
    *,
    provider_id: str,
    display_name: str,
    kind: str,
    base_url: str,
    credential: str,
    secretless: bool,
    config: dict[str, Any],
) -> ProviderAdapter | None:
    timeout_seconds = _coerce_timeout(
        config.get("timeout_seconds")
        or config.get("timeout")
        or _default_timeout_seconds(settings, kind)
    )
    allow_sample_fallback = _allow_sample_provider_fallback(settings)

    if kind in OPENAI_COMPATIBLE_CONNECTION_KINDS:
        return _with_connection_identity(
            OpenAIProviderAdapter(
                base_url=base_url or settings.openai_base_url,
                api_key=credential or None,
                organization=_coerce_string(config.get("organization")) or None,
                timeout_seconds=timeout_seconds,
                sample_catalog_profile=_coerce_string(config.get("sample_catalog_profile")),
                app_name=settings.project_name,
                allow_http_without_api_key=secretless,
                allow_sample_catalog=allow_sample_fallback,
                allow_sample_execution=allow_sample_fallback,
                model_namespace_prefix=_connection_model_namespace_prefix(
                    provider_id,
                    config,
                    default_provider_id="openai",
                ),
                provider_label=display_name,
            ),
            provider_id=provider_id,
            display_name=display_name,
        )

    if kind in {"minimax", "audio_provider", "minimax_audio"}:
        return _with_connection_identity(
            MiniMaxProviderAdapter(
                base_url=base_url or settings.minimax_base_url,
                api_key=credential or None,
                group_id=_coerce_string(config.get("group_id")) or settings.minimax_group_id,
                timeout_seconds=timeout_seconds,
                default_voice_id=(
                    _coerce_string(config.get("default_voice_id"))
                    or settings.minimax_default_voice_id
                ),
                allow_sample_catalog=allow_sample_fallback,
                allow_sample_execution=allow_sample_fallback,
            ),
            provider_id=provider_id,
            display_name=display_name,
        )

    if kind == "anthropic":
        return _with_connection_identity(
            AnthropicProviderAdapter(
                base_url=base_url or settings.anthropic_base_url,
                api_key=credential or None,
                api_version=_coerce_string(config.get("api_version"))
                or settings.anthropic_version,
                timeout_seconds=timeout_seconds,
                app_name=settings.project_name,
                allow_sample_catalog=allow_sample_fallback,
                allow_sample_execution=allow_sample_fallback,
            ),
            provider_id=provider_id,
            display_name=display_name,
        )

    if kind in {"litellm", "litellm_gateway"} and base_url:
        return _with_connection_identity(
            LiteLLMGatewayProviderAdapter(
                base_url=base_url,
                api_key=credential or None,
                timeout_seconds=timeout_seconds,
                app_name=settings.project_name,
            ),
            provider_id=provider_id,
            display_name=display_name,
        )

    if kind == "vllm" and base_url:
        return _with_connection_identity(
            VLLMProviderAdapter(
                base_url=base_url,
                api_key=credential or None,
                timeout_seconds=timeout_seconds,
                app_name=settings.project_name,
            ),
            provider_id=provider_id,
            display_name=display_name,
        )

    if kind == "tei" and base_url:
        model_ids = _coerce_string_list(config.get("model_ids") or config.get("models"))
        if not model_ids:
            return None
        return _with_connection_identity(
            TEIProviderAdapter(
                base_url=base_url,
                api_key=credential or None,
                timeout_seconds=timeout_seconds,
                model_ids=model_ids,
                region=_coerce_string(config.get("region")) or settings.tei_region,
                context_window=_coerce_int(
                    config.get("context_window"),
                    settings.tei_context_window,
                ),
                app_name=settings.project_name,
            ),
            provider_id=provider_id,
            display_name=display_name,
        )

    if kind == "openrouter":
        return _with_connection_identity(
            OpenRouterProviderAdapter(
                base_url=base_url or settings.openrouter_base_url,
                api_key=credential,
                timeout_seconds=timeout_seconds,
                site_url=_coerce_string(config.get("site_url")) or settings.openrouter_site_url,
                app_name=settings.project_name,
            ),
            provider_id=provider_id,
            display_name=display_name,
        )

    if kind == "siliconflow":
        return _with_connection_identity(
            SiliconFlowProviderAdapter(
                base_url=base_url or settings.siliconflow_base_url,
                api_key=credential,
                timeout_seconds=timeout_seconds,
                app_name=settings.project_name,
            ),
            provider_id=provider_id,
            display_name=display_name,
        )

    return None


def _connection_kind_allows_secretless(kind: str, *, secretless: bool) -> bool:
    if not secretless:
        return False
    return kind in OPENAI_COMPATIBLE_CONNECTION_KINDS or kind in {
        "litellm",
        "litellm_gateway",
        "vllm",
        "tei",
    }


def _with_connection_identity(
    adapter: ProviderAdapter,
    *,
    provider_id: str,
    display_name: str,
) -> ProviderAdapter:
    writable_adapter = cast(Any, adapter)
    writable_adapter.provider_id = provider_id
    writable_adapter.display_name = display_name
    return adapter


def _connection_model_namespace_prefix(
    provider_id: str,
    config: dict[str, Any],
    *,
    default_provider_id: str,
) -> str:
    if "model_namespace_prefix" in config:
        return _coerce_string(config.get("model_namespace_prefix"))
    normalized_provider_id = _coerce_string(provider_id)
    if normalized_provider_id == default_provider_id:
        return ""
    return normalized_provider_id


def _default_timeout_seconds(settings: Settings, kind: str) -> float:
    if kind in OPENAI_COMPATIBLE_CONNECTION_KINDS:
        return settings.openai_timeout_seconds
    if kind in {"minimax", "audio_provider", "minimax_audio"}:
        return settings.minimax_timeout_seconds
    if kind == "anthropic":
        return settings.anthropic_timeout_seconds
    if kind in {"litellm", "litellm_gateway"}:
        return settings.litellm_timeout_seconds
    if kind == "vllm":
        return settings.vllm_timeout_seconds
    if kind == "tei":
        return settings.tei_timeout_seconds
    if kind == "openrouter":
        return settings.openrouter_timeout_seconds
    if kind == "siliconflow":
        return settings.siliconflow_timeout_seconds
    return 30.0


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
