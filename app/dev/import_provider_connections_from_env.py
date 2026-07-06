from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.domain.provider_connections.service import (
    ProviderConnectionAdminError,
    ProviderConnectionAdminService,
)

DEFAULT_ENV_FILES = (".env", ".env.local", ".env.deploy")


@dataclass(slots=True)
class ProviderConnectionImportSpec:
    connection_id: str
    provider_id: str
    provider_type: str
    display_name: str
    base_url: str
    capability_ids: list[str]
    runtime_profile_ids: list[str]
    credential: str
    config: dict[str, Any]
    secretless: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Import legacy provider .env values into DB-managed provider_connections. "
            "Runs as dry-run unless --apply is provided."
        )
    )
    parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        help="Env file to read. Defaults to .env, .env.local, and .env.deploy when present.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write provider connections. Without this flag, only reports planned imports.",
    )
    parser.add_argument(
        "--remove-env-keys",
        action="store_true",
        help=(
            "Remove imported provider keys from the selected env files after a "
            "successful --apply."
        ),
    )
    return parser.parse_args()


def load_provider_env(env_files: list[str] | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    selected_files = tuple(env_files or DEFAULT_ENV_FILES)
    for env_file in selected_files:
        path = Path(env_file)
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            key, value = _parse_env_line(raw_line)
            if key:
                result[key] = value

    for key, value in os.environ.items():
        if _provider_env_key(key):
            result[key] = value
    return result


def import_provider_connections_from_env(
    *,
    settings: Settings,
    env: dict[str, str],
    apply: bool = False,
) -> dict[str, Any]:
    specs = _build_import_specs(env)
    imported: list[str] = []
    planned: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    service = ProviderConnectionAdminService(settings.database_url, settings)

    for spec in specs:
        planned.append(_public_spec(spec))
        if not apply:
            continue
        try:
            result = service.save_connection(_payload(spec))
        except ProviderConnectionAdminError as error:
            skipped.append(
                {
                    "connection_id": spec.connection_id,
                    "provider_id": spec.provider_id,
                    "reason": error.error_code,
                }
            )
            continue
        imported.append(str(result.get("connection_id") or spec.connection_id))

    return {
        "surface": "provider_connections_env_import",
        "mode": "apply" if apply else "dry_run",
        "planned": planned,
        "imported": imported,
        "skipped": skipped,
        "env_keys_consumed": sorted(_consumed_provider_env_keys(env)),
        "credential_value_exposure": "none",
        "env_fallback": "disabled_after_removal",
    }


def remove_imported_provider_env_keys(
    *,
    env_files: list[str] | None,
    keys: set[str],
) -> dict[str, Any]:
    selected_files = tuple(env_files or DEFAULT_ENV_FILES)
    changed_files: list[str] = []
    removed: dict[str, list[str]] = {}
    for env_file in selected_files:
        path = Path(env_file)
        if not path.exists():
            continue
        original_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        kept_lines: list[str] = []
        removed_keys: list[str] = []
        for line in original_lines:
            key, _value = _parse_any_env_line(line)
            if key in keys:
                removed_keys.append(key)
                continue
            kept_lines.append(line)
        if removed_keys:
            path.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""), encoding="utf-8")
            changed_files.append(str(path))
            removed[str(path)] = removed_keys
    return {"changed_files": changed_files, "removed_keys": removed}


def _build_import_specs(env: dict[str, str]) -> list[ProviderConnectionImportSpec]:
    specs: list[ProviderConnectionImportSpec] = []
    _add_model_provider_specs(specs, env)
    _add_web_search_specs(specs, env)
    _add_image_source_specs(specs, env)
    _add_vector_specs(specs, env)
    return specs


def _add_model_provider_specs(
    specs: list[ProviderConnectionImportSpec],
    env: dict[str, str],
) -> None:
    openai_key = _env_first(env, "OPENAI_API_KEY", "OPENAI_COMPATIBLE_API_KEY")
    if openai_key:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="openai_env",
                provider_id="openai",
                provider_type="openai_compatible",
                display_name=_env_first(
                    env,
                    "OPENAI_PROVIDER_LABEL",
                    "OPENAI_COMPATIBLE_PROVIDER_LABEL",
                )
                or "OpenAI compatible",
                base_url=_env_first(env, "OPENAI_BASE_URL", "OPENAI_COMPATIBLE_BASE_URL")
                or "https://api.openai.com/v1",
                capability_ids=["text_generation", "image_generation", "embedding"],
                runtime_profile_ids=[
                    "text.ai",
                    "text.free-gpt55",
                    "grok-imagine-image-quality",
                    "embed.default",
                ],
                credential=openai_key,
                config={
                    "organization": _env_first(
                        env,
                        "OPENAI_ORGANIZATION",
                        "OPENAI_COMPATIBLE_ORGANIZATION",
                    ),
                    "timeout_seconds": _env_first(
                        env,
                        "OPENAI_TIMEOUT_SECONDS",
                        "OPENAI_COMPATIBLE_TIMEOUT_SECONDS",
                    ),
                    "sample_catalog_profile": _env_first(
                        env,
                        "OPENAI_SAMPLE_CATALOG_PROFILE",
                        "OPENAI_COMPATIBLE_SAMPLE_CATALOG_PROFILE",
                    ),
                },
            )
        )

    siliconflow_key = _env_value(env, "SILICONFLOW_API_KEY")
    if siliconflow_key:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="siliconflow_env",
                provider_id="siliconflow",
                provider_type="siliconflow",
                display_name="SiliconFlow",
                base_url=_env_value(env, "SILICONFLOW_BASE_URL")
                or "https://api.siliconflow.cn/v1",
                capability_ids=["text_generation", "embedding"],
                runtime_profile_ids=["text.ai", "embed.default"],
                credential=siliconflow_key,
                config={
                    "model_id": _env_value(env, "SITE_KNOWLEDGE_EMBEDDING_MODEL"),
                    "dimensions": _env_value(env, "SITE_KNOWLEDGE_EMBEDDING_DIMENSIONS"),
                    "timeout_seconds": _env_value(env, "SILICONFLOW_TIMEOUT_SECONDS"),
                    "pricing_url": _env_value(env, "SILICONFLOW_PRICING_URL"),
                },
            )
        )

    tei_base_url = _env_value(env, "TEI_BASE_URL")
    if tei_base_url:
        tei_key = _env_value(env, "TEI_API_KEY")
        embedding_model = _env_value(env, "SITE_KNOWLEDGE_EMBEDDING_MODEL") or "BAAI/bge-m3"
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="tei_env",
                provider_id="tei",
                provider_type="tei",
                display_name="TEI",
                base_url=tei_base_url,
                capability_ids=["embedding"],
                runtime_profile_ids=["embed.default"],
                credential=tei_key,
                secretless=not bool(tei_key),
                config={
                    "model_id": embedding_model,
                    "model_ids": _env_value(env, "TEI_MODEL_IDS") or embedding_model,
                    "dimensions": _env_value(env, "SITE_KNOWLEDGE_EMBEDDING_DIMENSIONS") or "1024",
                    "timeout_seconds": _env_value(env, "TEI_TIMEOUT_SECONDS"),
                    "region": _env_value(env, "TEI_REGION"),
                    "context_window": _env_value(env, "TEI_CONTEXT_WINDOW"),
                },
            )
        )

    minimax_key = _env_value(env, "MINIMAX_API_KEY")
    if minimax_key:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="minimax_env",
                provider_id="minimax",
                provider_type="minimax",
                display_name="MiniMax",
                base_url=_env_value(env, "MINIMAX_BASE_URL") or "https://api.minimaxi.com",
                capability_ids=["audio_generation"],
                runtime_profile_ids=["audio.narration.default", "audio.narration.quality"],
                credential=minimax_key,
                config={
                    "group_id": _env_value(env, "MINIMAX_GROUP_ID"),
                    "timeout_seconds": _env_value(env, "MINIMAX_TIMEOUT_SECONDS"),
                    "default_voice_id": _env_value(env, "MINIMAX_DEFAULT_VOICE_ID"),
                },
            )
        )

    anthropic_key = _env_value(env, "ANTHROPIC_API_KEY")
    if anthropic_key:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="anthropic_env",
                provider_id="anthropic",
                provider_type="anthropic",
                display_name="Anthropic",
                base_url=_env_value(env, "ANTHROPIC_BASE_URL") or "https://api.anthropic.com",
                capability_ids=["text_generation"],
                runtime_profile_ids=["text.ai"],
                credential=anthropic_key,
                config={
                    "api_version": _env_value(env, "ANTHROPIC_VERSION"),
                    "timeout_seconds": _env_value(env, "ANTHROPIC_TIMEOUT_SECONDS"),
                },
            )
        )

    openrouter_key = _env_value(env, "OPENROUTER_API_KEY")
    if openrouter_key:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="openrouter_env",
                provider_id="openrouter",
                provider_type="openrouter",
                display_name="OpenRouter",
                base_url=_env_value(env, "OPENROUTER_BASE_URL")
                or "https://openrouter.ai/api/v1",
                capability_ids=["text_generation"],
                runtime_profile_ids=["text.ai"],
                credential=openrouter_key,
                config={
                    "site_url": _env_value(env, "OPENROUTER_SITE_URL"),
                    "timeout_seconds": _env_value(env, "OPENROUTER_TIMEOUT_SECONDS"),
                },
            )
        )


def _add_web_search_specs(
    specs: list[ProviderConnectionImportSpec],
    env: dict[str, str],
) -> None:
    provider_mode = _env_value(env, "WEB_SEARCH_PROVIDER") or "auto"
    tavily_keys = _env_first(env, "WEB_SEARCH_TAVILY_API_KEYS", "WEB_SEARCH_TAVILY_API_KEY")
    if tavily_keys:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="search_tavily",
                provider_id="tavily",
                provider_type="web_search_provider",
                display_name="Tavily",
                base_url=_env_value(env, "WEB_SEARCH_TAVILY_BASE_URL")
                or "https://api.tavily.com",
                capability_ids=["web_search"],
                runtime_profile_ids=["web-search.managed"],
                credential=tavily_keys,
                config={
                    "provider_mode": provider_mode,
                    "api_key_labels": _env_value(env, "WEB_SEARCH_TAVILY_API_KEY_LABELS"),
                    "timeout_seconds": _env_value(env, "WEB_SEARCH_TAVILY_TIMEOUT_SECONDS"),
                    "cost_per_query": _env_value(env, "WEB_SEARCH_TAVILY_COST_PER_QUERY"),
                },
            )
        )

    bocha_key = _env_value(env, "WEB_SEARCH_BOCHA_API_KEY")
    if bocha_key:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="search_bocha",
                provider_id="bocha",
                provider_type="web_search_provider",
                display_name="Bocha",
                base_url=_env_value(env, "WEB_SEARCH_BOCHA_BASE_URL")
                or "https://api.bochaai.com/v1",
                capability_ids=["web_search"],
                runtime_profile_ids=["web-search.managed"],
                credential=bocha_key,
                config={
                    "provider_mode": provider_mode,
                    "timeout_seconds": _env_value(env, "WEB_SEARCH_BOCHA_TIMEOUT_SECONDS"),
                    "cost_per_query": _env_value(env, "WEB_SEARCH_BOCHA_COST_PER_QUERY"),
                },
            )
        )

    apify_token = _env_value(env, "WEB_SEARCH_APIFY_API_TOKEN")
    if apify_token:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="search_apify",
                provider_id="apify",
                provider_type="web_search_provider",
                display_name="Apify",
                base_url=_env_value(env, "WEB_SEARCH_APIFY_BASE_URL")
                or "https://api.apify.com/v2",
                capability_ids=["web_search"],
                runtime_profile_ids=["web-search.managed"],
                credential=apify_token,
                config={
                    "provider_mode": provider_mode,
                    "actor_id": _env_value(env, "WEB_SEARCH_APIFY_ACTOR_ID")
                    or "apify/google-search-scraper",
                    "timeout_seconds": _env_value(env, "WEB_SEARCH_APIFY_TIMEOUT_SECONDS"),
                    "cost_per_query": _env_value(env, "WEB_SEARCH_APIFY_COST_PER_QUERY"),
                },
            )
        )

    jina_reader_key = _env_value(env, "WEB_SEARCH_JINA_READER_API_KEY")
    if jina_reader_key or _bool_env(_env_value(env, "WEB_SEARCH_JINA_READER_ENABLED")):
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="search_jina_reader",
                provider_id="jina_reader",
                provider_type="web_search_provider",
                display_name="Jina Reader",
                base_url=_env_value(env, "WEB_SEARCH_JINA_READER_BASE_URL")
                or "https://r.jina.ai",
                capability_ids=["web_search"],
                runtime_profile_ids=["web-search.reader"],
                credential=jina_reader_key,
                secretless=not bool(jina_reader_key),
                config={
                    "timeout_seconds": _env_value(env, "WEB_SEARCH_JINA_READER_TIMEOUT_SECONDS"),
                    "max_pages": _env_value(env, "WEB_SEARCH_JINA_READER_MAX_PAGES"),
                    "cost_per_page": _env_value(env, "WEB_SEARCH_JINA_READER_COST_PER_PAGE"),
                },
            )
        )

    zhihu_secret = _env_value(env, "WEB_SEARCH_ZHIHU_ACCESS_SECRET")
    if zhihu_secret:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="search_zhihu",
                provider_id="zhihu",
                provider_type="web_search_provider",
                display_name="Zhihu Search",
                base_url=_env_value(env, "WEB_SEARCH_ZHIHU_BASE_URL")
                or "https://developer.zhihu.com",
                capability_ids=["web_search"],
                runtime_profile_ids=["web-search.managed"],
                credential=zhihu_secret,
                config={
                    "provider_mode": provider_mode,
                    "search_path": _env_value(env, "WEB_SEARCH_ZHIHU_SEARCH_PATH"),
                    "global_search_path": _env_value(env, "WEB_SEARCH_ZHIHU_GLOBAL_SEARCH_PATH"),
                    "hot_list_path": _env_value(env, "WEB_SEARCH_ZHIHU_HOT_LIST_PATH"),
                    "direct_answer_path": _env_value(env, "WEB_SEARCH_ZHIHU_DIRECT_ANSWER_PATH"),
                    "timeout_seconds": _env_value(env, "WEB_SEARCH_ZHIHU_TIMEOUT_SECONDS"),
                    "cost_per_query": _env_value(env, "WEB_SEARCH_ZHIHU_COST_PER_QUERY"),
                    "hot_list_cache_ttl_seconds": _env_value(
                        env,
                        "WEB_SEARCH_ZHIHU_HOT_LIST_CACHE_TTL_SECONDS",
                    ),
                },
            )
        )


def _add_image_source_specs(
    specs: list[ProviderConnectionImportSpec],
    env: dict[str, str],
) -> None:
    provider_mode = _env_value(env, "IMAGE_SOURCE_PROVIDER") or "auto"
    image_specs = (
        (
            "image_unsplash",
            "unsplash",
            "Unsplash",
            "IMAGE_SOURCE_UNSPLASH_ACCESS_KEY",
            "IMAGE_SOURCE_UNSPLASH_BASE_URL",
            "https://api.unsplash.com",
        ),
        (
            "image_pixabay",
            "pixabay",
            "Pixabay",
            "IMAGE_SOURCE_PIXABAY_API_KEY",
            "IMAGE_SOURCE_PIXABAY_BASE_URL",
            "https://pixabay.com/api/",
        ),
        (
            "image_pexels",
            "pexels",
            "Pexels",
            "IMAGE_SOURCE_PEXELS_API_KEY",
            "IMAGE_SOURCE_PEXELS_BASE_URL",
            "https://api.pexels.com/v1",
        ),
    )
    for connection_id, provider_id, label, key_suffix, base_suffix, default_base in image_specs:
        credential = _env_value(env, key_suffix)
        if not credential:
            continue
        specs.append(
            ProviderConnectionImportSpec(
                connection_id=connection_id,
                provider_id=provider_id,
                provider_type="image_source_provider",
                display_name=label,
                base_url=_env_value(env, base_suffix) or default_base,
                capability_ids=["image_source"],
                runtime_profile_ids=["image-source.managed"],
                credential=credential,
                config={
                    "provider_mode": provider_mode,
                    "timeout_seconds": _env_value(env, "IMAGE_SOURCE_TIMEOUT_SECONDS"),
                    "cost_per_query": _env_value(env, "IMAGE_SOURCE_COST_PER_QUERY"),
                },
            )
        )


def _add_vector_specs(
    specs: list[ProviderConnectionImportSpec],
    env: dict[str, str],
) -> None:
    jina_key = _env_first(env, "SITE_KNOWLEDGE_JINA_API_KEY", "JINA_API_KEY")
    if _env_value(env, "SITE_KNOWLEDGE_RERANK_PROVIDER").lower() == "jina" or jina_key:
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="rerank_jina",
                provider_id="jina",
                provider_type="rerank_provider",
                display_name="Jina Rerank",
                base_url=_env_value(env, "SITE_KNOWLEDGE_JINA_BASE_URL")
                or "https://api.jina.ai",
                capability_ids=["site_knowledge_rerank"],
                runtime_profile_ids=["site-knowledge.rerank"],
                credential=jina_key,
                config={
                    "model_id": _env_value(env, "SITE_KNOWLEDGE_JINA_RERANK_MODEL")
                    or "jina-reranker-v3",
                    "top_k": _env_value(env, "SITE_KNOWLEDGE_RERANK_TOP_K"),
                    "timeout_seconds": _env_value(env, "SITE_KNOWLEDGE_RERANK_TIMEOUT_SECONDS"),
                },
            )
        )

    if _env_value(env, "SITE_KNOWLEDGE_VECTOR_BACKEND").lower() == "zilliz_cloud" or _env_value(
        env,
        "SITE_KNOWLEDGE_ZILLIZ_URI",
    ):
        specs.append(
            ProviderConnectionImportSpec(
                connection_id="vector_zilliz",
                provider_id="zilliz",
                provider_type="vector_store_provider",
                display_name="Zilliz",
                base_url=_env_value(env, "SITE_KNOWLEDGE_ZILLIZ_URI"),
                capability_ids=["vector_store"],
                runtime_profile_ids=["site-knowledge.vector-store"],
                credential=_env_value(env, "SITE_KNOWLEDGE_ZILLIZ_TOKEN"),
                config={
                    "uri": _env_value(env, "SITE_KNOWLEDGE_ZILLIZ_URI"),
                    "database": _env_value(env, "SITE_KNOWLEDGE_ZILLIZ_DATABASE"),
                    "collection": _env_value(env, "SITE_KNOWLEDGE_ZILLIZ_COLLECTION"),
                    "timeout_seconds": _env_value(env, "SITE_KNOWLEDGE_ZILLIZ_TIMEOUT_SECONDS"),
                },
            )
        )


def _payload(spec: ProviderConnectionImportSpec) -> dict[str, Any]:
    return {
        "connection_id": spec.connection_id,
        "provider_id": spec.provider_id,
        "provider_type": spec.provider_type,
        "kind": spec.provider_type,
        "display_name": spec.display_name,
        "enabled": True,
        "base_url": spec.base_url,
        "capability_ids": spec.capability_ids,
        "runtime_profile_ids": spec.runtime_profile_ids,
        "config": _compact_dict(spec.config),
        "credential": spec.credential,
        "secretless": spec.secretless,
    }


def _public_spec(spec: ProviderConnectionImportSpec) -> dict[str, Any]:
    return {
        "connection_id": spec.connection_id,
        "provider_id": spec.provider_id,
        "provider_type": spec.provider_type,
        "display_name": spec.display_name,
        "base_url_set": bool(spec.base_url),
        "capability_ids": spec.capability_ids,
        "runtime_profile_ids": spec.runtime_profile_ids,
        "credential_configured": bool(spec.credential) or spec.secretless,
        "secretless": spec.secretless,
    }


def _consumed_provider_env_keys(env: dict[str, str]) -> set[str]:
    return {key for key in env if _provider_env_key(key)}


def _parse_env_line(raw_line: str) -> tuple[str, str]:
    key, value = _parse_any_env_line(raw_line)
    if key and _provider_env_key(key):
        return key, value
    return "", ""


def _parse_any_env_line(raw_line: str) -> tuple[str, str]:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return "", ""
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return "", ""
    return key, _strip_env_value(value)


def _provider_env_key(key: str) -> bool:
    if not key.startswith("NPCINK_CLOUD_") and key != "JINA_API_KEY":
        return False
    if key == "JINA_API_KEY":
        return True
    suffix = key.removeprefix("NPCINK_CLOUD_")
    return (
        suffix.startswith("OPENAI_")
        or suffix.startswith("OPENAI_COMPATIBLE_")
        or suffix.startswith("MINIMAX_")
        or suffix.startswith("ANTHROPIC_")
        or suffix.startswith("OPENROUTER_")
        or suffix.startswith("WEB_SEARCH_")
        or suffix.startswith("IMAGE_SOURCE_")
        or suffix.startswith("TEI_")
        or suffix.startswith("SILICONFLOW_")
        or suffix
        in {
            "SITE_KNOWLEDGE_EMBEDDING_PROVIDER",
            "SITE_KNOWLEDGE_EMBEDDING_MODEL",
            "SITE_KNOWLEDGE_EMBEDDING_DIMENSIONS",
            "SITE_KNOWLEDGE_RERANK_PROVIDER",
            "SITE_KNOWLEDGE_JINA_BASE_URL",
            "SITE_KNOWLEDGE_JINA_API_KEY",
            "SITE_KNOWLEDGE_JINA_RERANK_MODEL",
            "SITE_KNOWLEDGE_VECTOR_BACKEND",
            "SITE_KNOWLEDGE_ZILLIZ_URI",
            "SITE_KNOWLEDGE_ZILLIZ_TOKEN",
            "SITE_KNOWLEDGE_ZILLIZ_DATABASE",
            "SITE_KNOWLEDGE_ZILLIZ_COLLECTION",
        }
    )


def _env_value(env: dict[str, str], suffix: str) -> str:
    if suffix == "JINA_API_KEY":
        return _string(env.get("JINA_API_KEY"))
    return _string(env.get(f"NPCINK_CLOUD_{suffix}"))


def _env_first(env: dict[str, str], *suffixes: str) -> str:
    for suffix in suffixes:
        value = _env_value(env, suffix)
        if value:
            return value
    return ""


def _strip_env_value(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _string(value: object) -> str:
    return str(value or "").strip()


def _bool_env(value: object) -> bool:
    return _string(value).lower() in {"1", "true", "yes", "on"}


def _compact_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != "" and item != []
    }


def _list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _redact_report(value: object) -> object:
    if isinstance(value, dict):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key).lower().replace("-", "_")
            if any(part in key_text for part in ("secret", "credential", "token", "password")):
                redacted[str(key)] = bool(str(item or ""))
            else:
                redacted[str(key)] = _redact_report(item)
        return redacted
    if isinstance(value, list):
        return [_redact_report(item) for item in value]
    return value


def main() -> None:
    args = parse_args()
    selected_env_files = args.env_file or list(DEFAULT_ENV_FILES)
    settings = Settings()
    env = load_provider_env(selected_env_files)
    result = import_provider_connections_from_env(
        settings=settings,
        env=env,
        apply=bool(args.apply),
    )
    if args.remove_env_keys:
        if not args.apply:
            result["env_removal"] = {
                "skipped": True,
                "reason": "remove-env-keys requires --apply",
            }
        else:
            result["env_removal"] = remove_imported_provider_env_keys(
                env_files=selected_env_files,
                keys=set(result["env_keys_consumed"]),
            )
    summary = {
        "surface": "provider_connections_env_import",
        "mode": "apply" if args.apply else "dry_run",
        "planned_count": _list_count(result.get("planned")),
        "imported_count": _list_count(result.get("imported")),
        "skipped_count": _list_count(result.get("skipped")),
        "env_key_count": _list_count(result.get("env_keys_consumed")),
        "credential_value_exposure": "none",
    }
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
