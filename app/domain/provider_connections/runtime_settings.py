from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderConnection
from app.core.secrets import decrypt_provider_connection_secret


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
            rows = list(
                session.scalars(
                    select(ProviderConnection)
                    .where(ProviderConnection.enabled.is_(True))
                    .order_by(ProviderConnection.connection_id.asc())
                )
            )
    except SQLAlchemyError:
        return projection

    web_search_primary_seen = False
    image_source_seen = False
    for row in rows:
        config = _dict(row.config_json)
        kind = _string(config.get("kind") or row.provider_type).lower()
        provider_id = _string(config.get("provider_id") or row.connection_id).lower()
        credential = _decrypt_connection_credential(settings, row)
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
                if provider_id in {"tavily", "bocha", "apify"}:
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
                image_source_seen = True
            continue
        if kind == "embedding_provider":
            if _apply_embedding_connection(
                settings,
                row=row,
                provider_id=provider_id,
                credential=credential,
                config=config,
            ):
                projection.embedding_count += 1
                projection.applied_count += 1
            continue
        if kind == "rerank_provider":
            if _apply_rerank_connection(
                settings,
                row=row,
                provider_id=provider_id,
                credential=credential,
                config=config,
            ):
                projection.rerank_count += 1
                projection.applied_count += 1
            continue
        if kind == "vector_store_provider":
            if _apply_vector_store_connection(
                settings,
                row=row,
                provider_id=provider_id,
                credential=credential,
                config=config,
            ):
                projection.vector_store_count += 1
                projection.applied_count += 1
    return projection


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
    if provider_id not in {"siliconflow", "openai", "tei"}:
        return False
    settings.site_knowledge_embedding_provider = provider_id
    settings.site_knowledge_embedding_model = _string(
        config.get("model_id") or config.get("model") or settings.site_knowledge_embedding_model
    )
    settings.site_knowledge_embedding_dimensions = _int(
        config.get("dimensions"), settings.site_knowledge_embedding_dimensions
    )
    if provider_id == "siliconflow":
        settings.siliconflow_provider_enabled = True
        settings.siliconflow_base_url = row.base_url or settings.siliconflow_base_url
        if credential:
            settings.siliconflow_api_key = credential
    elif provider_id == "openai":
        settings.openai_base_url = row.base_url or settings.openai_base_url
        if credential:
            settings.openai_api_key = credential
    elif provider_id == "tei":
        settings.tei_provider_enabled = True
        settings.tei_base_url = row.base_url or settings.tei_base_url
        if credential:
            settings.tei_api_key = credential
        model_ids = _string(config.get("model_ids") or config.get("model_id") or "")
        if model_ids:
            settings.tei_model_ids = model_ids
    return True


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
    if provider_id != "zilliz":
        return False
    settings.site_knowledge_vector_backend = "zilliz_cloud"
    settings.site_knowledge_zilliz_uri = _string(config.get("uri") or row.base_url)
    if credential:
        settings.site_knowledge_zilliz_token = credential
    settings.site_knowledge_zilliz_database = _string(
        config.get("database") or settings.site_knowledge_zilliz_database or ""
    )
    settings.site_knowledge_zilliz_collection = _string(
        config.get("collection") or settings.site_knowledge_zilliz_collection
    )
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


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return str(value or "").strip()


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
