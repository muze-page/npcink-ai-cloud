from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderConnection
from app.core.secrets import decrypt_provider_connection_secret
from app.domain.site_knowledge.vector_profile_contract import (
    SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
    SITE_KNOWLEDGE_VECTOR_METRIC,
    SITE_KNOWLEDGE_VECTOR_MODEL_ID,
    SITE_KNOWLEDGE_VECTOR_PROBE_REVISION,
    SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
    SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
    SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
    SITE_KNOWLEDGE_VECTOR_STORE_PROBE_REVISION,
    SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_ID,
)


@dataclass(slots=True)
class RuntimeProviderSettingsProjection:
    applied_count: int = 0
    web_search_count: int = 0
    image_source_count: int = 0
    embedding_count: int = 0
    rerank_count: int = 0
    vector_store_count: int = 0


def apply_provider_connection_runtime_settings(
    settings: Settings,
) -> RuntimeProviderSettingsProjection:
    """Project DB-managed provider connections onto legacy Settings fields.

    Runtime modules still consume Settings. This bridge lets DB-managed provider
    connections become the primary source without turning Cloud into a second
    ability/workflow/router control plane.
    """

    projection = RuntimeProviderSettingsProjection()
    database_url = str(getattr(settings, "database_url", "") or "").strip()
    if not database_url:
        return projection

    try:
        with get_session(database_url) as session:
            all_rows = list(
                session.scalars(
                    select(ProviderConnection)
                    .order_by(ProviderConnection.connection_id.asc())
                )
            )
    except SQLAlchemyError:
        return projection

    if not all_rows:
        return projection

    rows = [row for row in all_rows if row.enabled]
    _reset_managed_runtime_selections(settings)
    web_search_primary_seen = False
    image_source_seen = False
    embedding_seen = False
    rerank_seen = False
    vector_store_seen = False
    applied_provider_channels: set[tuple[str, str]] = set()
    for row in rows:
        config = _dict(row.config_json)
        kind = _string(config.get("kind") or row.provider_type).lower()
        provider_id = _string(config.get("provider_id") or row.connection_id).lower()
        provider_channel_key = (kind, provider_id)
        if provider_channel_key in applied_provider_channels:
            continue
        capability_ids = _string_list(config.get("capability_ids"))
        runtime_profile_ids = _string_list(config.get("runtime_profile_ids"))
        credential = _decrypt_connection_credential(settings, row)
        if not _connection_configured(row, config, provider_id, credential):
            continue
        if kind == "web_search_provider":
            applied = _apply_web_search_connection(
                settings,
                row=row,
                provider_id=provider_id,
                credential=credential,
                config=config,
                primary_seen=web_search_primary_seen,
            )
            if applied:
                projection.web_search_count += 1
                projection.applied_count += 1
                applied_provider_channels.add(provider_channel_key)
                if provider_id in {"tavily", "bocha", "apify", "zhihu"}:
                    web_search_primary_seen = True
            continue
        if kind == "image_source_provider":
            applied = _apply_image_source_connection(
                settings,
                row=row,
                provider_id=provider_id,
                credential=credential,
                config=config,
                provider_seen=image_source_seen,
            )
            if applied:
                projection.image_source_count += 1
                projection.applied_count += 1
                applied_provider_channels.add(provider_channel_key)
                image_source_seen = True
            continue
        if kind == "embedding_provider" or (
            provider_id in {"siliconflow", "openai", "tei"}
            and "embedding" in capability_ids
            and "embed.default" in runtime_profile_ids
        ):
            if embedding_seen:
                continue
            if _apply_embedding_connection(
                settings,
                row=row,
                provider_id=provider_id,
                credential=credential,
                config=config,
            ):
                projection.embedding_count += 1
                projection.applied_count += 1
                applied_provider_channels.add(provider_channel_key)
                embedding_seen = True
            continue
        if kind == "rerank_provider":
            if rerank_seen:
                continue
            if _apply_rerank_connection(
                settings,
                row=row,
                provider_id=provider_id,
                credential=credential,
                config=config,
            ):
                projection.rerank_count += 1
                projection.applied_count += 1
                applied_provider_channels.add(provider_channel_key)
                rerank_seen = True
            continue
        if kind == "vector_store_provider":
            if vector_store_seen:
                continue
            if _apply_vector_store_connection(
                settings,
                row=row,
                provider_id=provider_id,
                credential=credential,
                config=config,
            ):
                projection.vector_store_count += 1
                projection.applied_count += 1
                applied_provider_channels.add(provider_channel_key)
                vector_store_seen = True
    return projection


def _reset_managed_runtime_selections(settings: Settings) -> None:
    """Reset DB-owned selections so disabling a connection takes effect immediately."""

    settings.web_search_provider = "disabled"
    settings.web_search_jina_reader_enabled = False
    settings.image_source_provider = "disabled"
    settings.site_knowledge_embedding_provider = "deterministic"
    settings.site_knowledge_embedding_model = "BAAI/bge-m3"
    settings.site_knowledge_embedding_dimensions = 1024
    settings.site_knowledge_rerank_provider = "disabled"
    settings.site_knowledge_vector_backend = "postgres_json"


def _apply_web_search_connection(
    settings: Settings,
    *,
    row: ProviderConnection,
    provider_id: str,
    credential: str,
    config: dict[str, Any],
    primary_seen: bool,
) -> bool:
    if provider_id == "tavily":
        settings.web_search_tavily_base_url = row.base_url or settings.web_search_tavily_base_url
        if credential:
            settings.web_search_tavily_api_key = credential
        settings.web_search_tavily_api_key_labels = _string(
            config.get("api_key_labels") or settings.web_search_tavily_api_key_labels
        )
        settings.web_search_tavily_timeout_seconds = _positive_float(
            config.get("timeout_seconds"), settings.web_search_tavily_timeout_seconds
        )
        settings.web_search_tavily_cost_per_query = _nonnegative_float(
            config.get("cost_per_query") or config.get("cost"),
            settings.web_search_tavily_cost_per_query,
        )
    elif provider_id == "bocha":
        settings.web_search_bocha_base_url = row.base_url or settings.web_search_bocha_base_url
        if credential:
            settings.web_search_bocha_api_key = credential
        settings.web_search_bocha_timeout_seconds = _positive_float(
            config.get("timeout_seconds"), settings.web_search_bocha_timeout_seconds
        )
        settings.web_search_bocha_cost_per_query = _nonnegative_float(
            config.get("cost_per_query") or config.get("cost"),
            settings.web_search_bocha_cost_per_query,
        )
    elif provider_id == "jina_reader":
        settings.web_search_jina_reader_enabled = True
        settings.web_search_jina_reader_base_url = (
            row.base_url or settings.web_search_jina_reader_base_url
        )
        if credential:
            settings.web_search_jina_reader_api_key = credential
        settings.web_search_jina_reader_timeout_seconds = _positive_float(
            config.get("timeout_seconds"), settings.web_search_jina_reader_timeout_seconds
        )
        settings.web_search_jina_reader_max_pages = _int(
            config.get("max_pages"), settings.web_search_jina_reader_max_pages
        )
        settings.web_search_jina_reader_cost_per_page = _nonnegative_float(
            config.get("cost_per_page") or config.get("cost"),
            settings.web_search_jina_reader_cost_per_page,
        )
        return True
    elif provider_id == "apify":
        settings.web_search_apify_base_url = row.base_url or settings.web_search_apify_base_url
        if credential:
            settings.web_search_apify_api_token = credential
        settings.web_search_apify_actor_id = _string(
            config.get("actor_id") or settings.web_search_apify_actor_id
        )
        settings.web_search_apify_timeout_seconds = _positive_float(
            config.get("timeout_seconds"), settings.web_search_apify_timeout_seconds
        )
        settings.web_search_apify_cost_per_query = _nonnegative_float(
            config.get("cost_per_query") or config.get("cost"),
            settings.web_search_apify_cost_per_query,
        )
    elif provider_id == "zhihu":
        settings.web_search_zhihu_base_url = row.base_url or settings.web_search_zhihu_base_url
        if credential:
            settings.web_search_zhihu_access_secret = credential
        settings.web_search_zhihu_search_path = _string(
            config.get("search_path") or settings.web_search_zhihu_search_path
        )
        settings.web_search_zhihu_global_search_path = _string(
            config.get("global_search_path") or settings.web_search_zhihu_global_search_path
        )
        settings.web_search_zhihu_hot_list_path = _string(
            config.get("hot_list_path") or settings.web_search_zhihu_hot_list_path
        )
        settings.web_search_zhihu_direct_answer_path = _string(
            config.get("direct_answer_path") or settings.web_search_zhihu_direct_answer_path
        )
        settings.web_search_zhihu_timeout_seconds = _positive_float(
            config.get("timeout_seconds"), settings.web_search_zhihu_timeout_seconds
        )
        settings.web_search_zhihu_cost_per_query = _nonnegative_float(
            config.get("cost_per_query") or config.get("cost"),
            settings.web_search_zhihu_cost_per_query,
        )
        settings.web_search_zhihu_hot_list_cache_ttl_seconds = _int(
            config.get("hot_list_cache_ttl_seconds"),
            settings.web_search_zhihu_hot_list_cache_ttl_seconds,
        )
    else:
        return False

    if not primary_seen and provider_id in {"tavily", "bocha", "apify", "zhihu"}:
        settings.web_search_provider = _string(config.get("provider_mode") or "auto")
    return True


def _apply_image_source_connection(
    settings: Settings,
    *,
    row: ProviderConnection,
    provider_id: str,
    credential: str,
    config: dict[str, Any],
    provider_seen: bool,
) -> bool:
    if provider_id == "unsplash":
        settings.image_source_unsplash_base_url = (
            row.base_url or settings.image_source_unsplash_base_url
        )
        if credential:
            settings.image_source_unsplash_access_key = credential
    elif provider_id == "pixabay":
        settings.image_source_pixabay_base_url = (
            row.base_url or settings.image_source_pixabay_base_url
        )
        if credential:
            settings.image_source_pixabay_api_key = credential
    elif provider_id == "pexels":
        settings.image_source_pexels_base_url = (
            row.base_url or settings.image_source_pexels_base_url
        )
        if credential:
            settings.image_source_pexels_api_key = credential
    else:
        return False

    settings.image_source_timeout_seconds = _positive_float(
        config.get("timeout_seconds"), settings.image_source_timeout_seconds
    )
    settings.image_source_cost_per_query = _nonnegative_float(
        config.get("cost_per_query") or config.get("cost"), settings.image_source_cost_per_query
    )
    if not provider_seen:
        settings.image_source_provider = _string(config.get("provider_mode") or "auto")
    return True


def _apply_embedding_connection(
    settings: Settings,
    *,
    row: ProviderConnection,
    provider_id: str,
    credential: str,
    config: dict[str, Any],
) -> bool:
    if provider_id != SITE_KNOWLEDGE_VECTOR_PROVIDER_ID:
        return False
    if row.status != "ready":
        return False
    if str(config.get("site_knowledge_profile_id") or "") != SITE_KNOWLEDGE_VECTOR_PROFILE_ID:
        return False
    if str(config.get("site_knowledge_probe_revision") or "") != (
        SITE_KNOWLEDGE_VECTOR_PROBE_REVISION
    ):
        return False
    embedding_model = _site_knowledge_embedding_model(
        config,
        fallback=settings.site_knowledge_embedding_model,
    )
    if embedding_model != SITE_KNOWLEDGE_VECTOR_MODEL_ID:
        return False
    if _int(config.get("dimensions"), 0) != SITE_KNOWLEDGE_VECTOR_DIMENSIONS:
        return False
    if _string(config.get("metric")).upper() != SITE_KNOWLEDGE_VECTOR_METRIC:
        return False
    settings.site_knowledge_embedding_provider = provider_id
    settings.site_knowledge_embedding_model = SITE_KNOWLEDGE_VECTOR_MODEL_ID
    settings.site_knowledge_embedding_dimensions = SITE_KNOWLEDGE_VECTOR_DIMENSIONS
    settings.siliconflow_provider_enabled = True
    settings.siliconflow_base_url = row.base_url or settings.siliconflow_base_url
    if credential:
        settings.siliconflow_api_key = credential
    return True


def _site_knowledge_embedding_model(config: dict[str, Any], *, fallback: object) -> str:
    requested = _string(config.get("site_knowledge_model_id"))
    declared_models = _string_list(config.get("model_ids"))
    if requested:
        if declared_models and requested not in declared_models:
            return ""
        return requested
    return _string(config.get("model_id") or config.get("model") or fallback)


def _apply_rerank_connection(
    settings: Settings,
    *,
    row: ProviderConnection,
    provider_id: str,
    credential: str,
    config: dict[str, Any],
) -> bool:
    if provider_id != "jina":
        return False
    settings.site_knowledge_rerank_provider = "jina"
    settings.site_knowledge_jina_base_url = row.base_url or settings.site_knowledge_jina_base_url
    if credential:
        settings.site_knowledge_jina_api_key = credential
    settings.site_knowledge_jina_rerank_model = _string(
        config.get("model_id")
        or config.get("rerank_model")
        or settings.site_knowledge_jina_rerank_model
    )
    settings.site_knowledge_rerank_top_k = _int(
        config.get("top_k"), settings.site_knowledge_rerank_top_k
    )
    settings.site_knowledge_rerank_timeout_seconds = _positive_float(
        config.get("timeout_seconds"), settings.site_knowledge_rerank_timeout_seconds
    )
    return True


def _apply_vector_store_connection(
    settings: Settings,
    *,
    row: ProviderConnection,
    provider_id: str,
    credential: str,
    config: dict[str, Any],
) -> bool:
    if provider_id != SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_ID:
        return False
    if row.status != "ready":
        return False
    if str(config.get("site_knowledge_vector_store_profile_id") or "") != (
        SITE_KNOWLEDGE_VECTOR_PROFILE_ID
    ):
        return False
    if str(config.get("site_knowledge_vector_store_probe_revision") or "") != (
        SITE_KNOWLEDGE_VECTOR_STORE_PROBE_REVISION
    ):
        return False
    if _int(config.get("site_knowledge_vector_store_dimensions"), 0) != (
        SITE_KNOWLEDGE_VECTOR_DIMENSIONS
    ):
        return False
    if _string(config.get("site_knowledge_vector_store_metric")).upper() != (
        SITE_KNOWLEDGE_VECTOR_METRIC
    ):
        return False
    if _string(config.get("collection")) != SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION:
        return False
    lifecycle_value = config.get("site_knowledge_index_lifecycle")
    if isinstance(lifecycle_value, dict):
        lifecycle_status = _string(lifecycle_value.get("status"))
        if lifecycle_status not in {"ready", "empty"}:
            return False
    settings.site_knowledge_vector_backend = "zilliz_cloud"
    settings.site_knowledge_zilliz_uri = _string(config.get("uri") or row.base_url)
    if credential:
        settings.site_knowledge_zilliz_token = credential
    settings.site_knowledge_zilliz_database = None
    settings.site_knowledge_zilliz_collection = SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION
    settings.site_knowledge_zilliz_timeout_seconds = _positive_float(
        config.get("timeout_seconds"), settings.site_knowledge_zilliz_timeout_seconds
    )
    return True


def _decrypt_connection_credential(settings: Settings, row: ProviderConnection) -> str:
    ciphertext = _string(row.secret_ciphertext)
    if not ciphertext:
        return ""
    try:
        return decrypt_provider_connection_secret(ciphertext, settings=settings)
    except RuntimeError:
        return ""


def _connection_configured(
    row: ProviderConnection,
    config: dict[str, Any],
    provider_id: str,
    credential: str,
) -> bool:
    if provider_id == "jina_reader":
        return True
    return bool(_string(credential)) or bool(config.get("secretless"))


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return str(value or "").strip()


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = []
    normalized: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _positive_float(value: object, default: object) -> float:
    raw_value: Any = value
    raw_default: Any = default
    try:
        number = float(raw_value)
    except (TypeError, ValueError):
        number = float(raw_default or 0)
    return max(0.001, number)


def _nonnegative_float(value: object, default: object) -> float:
    raw_value: Any = value
    raw_default: Any = default
    try:
        number = float(raw_value)
    except (TypeError, ValueError):
        number = float(raw_default or 0)
    return max(0.0, number)


def _int(value: object, default: object) -> int:
    raw_value: Any = value
    raw_default: Any = default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return int(raw_default or 0)
