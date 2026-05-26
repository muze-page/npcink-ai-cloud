from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.model_intelligence.publisher.sources.base import PublisherSource
from app.model_intelligence.publisher.sources.huggingface import HuggingFacePublisherSource
from app.model_intelligence.publisher.sources.ollama import OllamaPublisherSource
from app.model_intelligence.publisher.sources.openrouter import OpenRouterPublisherSource
from app.model_intelligence.publisher.sources.siliconflow import SiliconFlowPublisherSource
from app.model_intelligence.publisher.utils import (
    build_checksum,
    merge_models,
    now_iso,
    read_json,
    validate_bundle_shape,
    write_json,
    write_text,
)


@dataclass(slots=True)
class PublisherRunResult:
    bundle_payload: dict[str, Any]
    summary_payload: dict[str, Any]
    bundle_path: str
    summary_path: str


def run_publisher(
    settings: Settings,
    *,
    sources: list[PublisherSource] | None = None,
    now_factory: Callable[[], datetime] | None = None,
) -> PublisherRunResult:
    bundle_path = str(settings.model_intelligence_bundle_path or "").strip()
    summary_path = str(settings.model_intelligence_run_summary_path or "").strip()
    if not bundle_path:
        raise RuntimeError("model_intelligence_bundle_path_not_configured")
    if not summary_path:
        raise RuntimeError("model_intelligence_run_summary_path_not_configured")

    clock = now_factory or (lambda: datetime.now(UTC))
    run_started_at = now_iso(clock())
    previous_bundle = _load_cached_final_bundle(bundle_path)
    price_history = _extract_price_history_from_bundle(previous_bundle)
    source_outputs: list[dict[str, Any]] = []
    source_failures: list[dict[str, Any]] = []
    cached_source_ids: list[str] = []
    enabled_sources = sources or build_enabled_sources(settings, price_history=price_history)

    for source in enabled_sources:
        try:
            bundle = source.fetch_bundle()
            validate_bundle_shape(bundle)
            source_outputs.append({"source": source, "bundle": bundle})
        except Exception as error:
            fallback = _load_cached_source_output(bundle_path, source.id)
            if fallback is not None:
                source_outputs.append({"source": source, "bundle": fallback})
                cached_source_ids.append(source.id)
            source_failures.append(
                {
                    "source_id": source.id,
                    "error": str(error),
                    "fallback_used": bool(fallback),
                }
            )

    if not source_outputs and previous_bundle is None:
        if source_failures:
            joined = "; ".join(
                f"{item['source_id']}:{item['error']}" for item in source_failures
            )
            raise RuntimeError(f"all sources failed: {joined}")
        raise RuntimeError("no sources produced output")

    exchange_rate = float(settings.recognition_price_cny_per_usd or 7.2)
    global_health_signals = _build_global_health_signals(source_outputs, source_failures)
    final_bundle = build_merged_bundle(
        source_outputs,
        clock=clock,
        exchange_rate_usd_cny=exchange_rate,
        global_health_signals=global_health_signals,
    ) if source_outputs else None
    published = choose_published_bundle(final_bundle, previous_bundle, source_failures)
    published_bundle = published["bundle"]
    if not isinstance(published_bundle, dict):
        raise RuntimeError("unable to choose one published bundle")

    output_root = Path(bundle_path).parent
    previous_bundle_path = str(output_root / "model-intelligence.bundle.previous.json")
    if (
        isinstance(previous_bundle, dict)
        and str(previous_bundle.get("checksum") or "").strip()
        and previous_bundle.get("checksum") != published_bundle.get("checksum")
    ):
        write_json(previous_bundle_path, previous_bundle)

    for item in source_outputs:
        write_json(
            output_root / f"{item['source'].id}.models.json",
            {
                "source_id": item["source"].id,
                "generated_at": item["bundle"].get("generated_at"),
                "records_total": len(item["bundle"].get("models") or []),
                "bundle": item["bundle"],
            },
        )

    summary_payload = {
        "status": published["status"],
        "started_at": run_started_at,
        "generated_at": now_iso(clock()),
        "enabled_sources": [source.id for source in enabled_sources],
        "cached_sources_used": cached_source_ids,
        "previous_bundle_used": published["used_previous_bundle"],
        "published_bundle_source": published["bundle_source"],
        "bundle_retained_reason": published["reason"],
        "failed_sources": source_failures,
        "sources": [
            {
                "source_id": item["source"].id,
                "records_total": len(item["bundle"].get("models") or []),
                "checksum": item["bundle"].get("checksum"),
                "cached_fallback_used": item["source"].id in cached_source_ids,
            }
            for item in source_outputs
        ],
        "models_total": len(published_bundle.get("models") or []),
        "bundle_path": bundle_path,
        "previous_bundle_path": previous_bundle_path
        if isinstance(previous_bundle, dict)
        and str(previous_bundle.get("checksum") or "").strip()
        and previous_bundle.get("checksum") != published_bundle.get("checksum")
        else "",
    }

    write_json(bundle_path, published_bundle)
    write_json(summary_path, summary_payload)
    write_text(
        output_root / "LATEST.txt",
        "\n".join(
            [
                f"generated_at={summary_payload['generated_at']}",
                f"models_total={summary_payload['models_total']}",
                f"bundle={Path(bundle_path).name}",
                f"sources={','.join(summary_payload['enabled_sources'])}",
                f"published_bundle_source={published['bundle_source']}",
                f"bundle_retained_reason={published['reason']}",
            ]
        )
        + "\n",
    )
    return PublisherRunResult(
        bundle_payload=published_bundle,
        summary_payload=summary_payload,
        bundle_path=bundle_path,
        summary_path=summary_path,
    )


def build_enabled_sources(
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None = None,
    price_history: dict[str, dict[str, float]] | None = None,
) -> list[PublisherSource]:
    sources: list[PublisherSource] = [
        SiliconFlowPublisherSource(
            pricing_url=settings.siliconflow_pricing_url,
            cny_per_usd=settings.recognition_price_cny_per_usd,
            transport=transport,
            price_history=price_history,
        ),
        OpenRouterPublisherSource(
            api_key=settings.openrouter_api_key,
            site_url=str(settings.openrouter_site_url or "https://openrouter.ai"),
            transport=transport,
        ),
        OllamaPublisherSource(
            base_url=str(settings.ollama_base_url or "https://ollama.com"),
            api_key=settings.ollama_api_key,
            catalog_limit=settings.ollama_catalog_limit,
            transport=transport,
        ),
    ]
    huggingface_allowlist = [
        repo_id.strip()
        for repo_id in str(settings.huggingface_model_allowlist or "").split(",")
        if repo_id.strip()
    ]
    if huggingface_allowlist:
        sources.append(
            HuggingFacePublisherSource(
                repo_ids=huggingface_allowlist,
                base_url=settings.huggingface_base_url,
                api_token=settings.huggingface_api_token,
                timeout_seconds=settings.huggingface_timeout_seconds,
                transport=transport,
            )
        )
    return sources


def build_merged_bundle(
    source_outputs: list[dict[str, Any]],
    *,
    clock: Callable[[], datetime],
    exchange_rate_usd_cny: float = 7.2,
    global_health_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_models: dict[str, dict[str, Any]] = {}
    for item in source_outputs:
        bundle = item["bundle"]
        for model in bundle.get("models") or []:
            key = (
                f"{str(model.get('provider') or '').strip().lower()}::"
                f"{str(model.get('model_id') or '').strip().lower()}"
            )
            if key == "::":
                continue
            merged_models[key] = merge_models(merged_models.get(key), model)

    generated_at = now_iso(clock())
    bundle_core = {
        "bundle_kind": "model_intelligence_bundle_v1",
        "schema_version": "model_intelligence_bundle_v1",
        "generated_at": generated_at,
        "exchange_rate_usd_cny": exchange_rate_usd_cny,
        "global_health_signals": global_health_signals or {},
        "sources": [source for item in source_outputs for source in item["bundle"].get("sources") or []],
        "models": sorted(
            merged_models.values(),
            key=lambda row: f"{row.get('provider')}/{row.get('model_id')}",
        ),
    }
    final_bundle = {**bundle_core, "checksum": build_checksum(bundle_core)}
    validate_bundle_shape(final_bundle)
    return final_bundle


def choose_published_bundle(
    final_bundle: dict[str, Any] | None,
    previous_bundle: dict[str, Any] | None,
    source_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    has_failures = bool(source_failures)
    if final_bundle is None and previous_bundle is not None:
        return {
            "bundle": previous_bundle,
            "status": "degraded" if has_failures else "success",
            "used_previous_bundle": True,
            "bundle_source": "previous_bundle",
            "reason": "all_sources_failed_keep_previous",
        }
    if final_bundle is None:
        return {
            "bundle": None,
            "status": "error",
            "used_previous_bundle": False,
            "bundle_source": "",
            "reason": "no_bundle_available",
        }
    if (
        has_failures
        and isinstance(previous_bundle, dict)
        and isinstance(previous_bundle.get("models"), list)
        and isinstance(final_bundle.get("models"), list)
        and len(previous_bundle["models"]) > len(final_bundle["models"])
    ):
        return {
            "bundle": previous_bundle,
            "status": "degraded",
            "used_previous_bundle": True,
            "bundle_source": "previous_bundle",
            "reason": "partial_failure_keep_larger_previous_bundle",
        }
    return {
        "bundle": final_bundle,
        "status": "degraded" if has_failures else "success",
        "used_previous_bundle": False,
        "bundle_source": "current_run",
        "reason": "partial_failure_publish_current_bundle" if has_failures else "current_run_publish",
    }


def _load_cached_source_output(bundle_path: str, source_id: str) -> dict[str, Any] | None:
    try:
        cached = read_json(Path(bundle_path).parent / f"{source_id}.models.json")
        bundle = cached.get("bundle") if isinstance(cached, dict) else None
        if not isinstance(bundle, dict):
            return None
        validate_bundle_shape(bundle)
        return bundle
    except Exception:
        return None


def _load_cached_final_bundle(bundle_path: str) -> dict[str, Any] | None:
    try:
        cached = read_json(bundle_path)
        if not isinstance(cached, dict):
            return None
        validate_bundle_shape(cached)
        return cached
    except Exception:
        return None


def _extract_price_history_from_bundle(
    bundle: dict[str, Any] | None,
) -> dict[str, dict[str, float]]:
    if not isinstance(bundle, dict):
        return {}
    history: dict[str, dict[str, float]] = {}
    for model in bundle.get("models") or []:
        model_id = str(model.get("model_id") or "").strip()
        if not model_id:
            continue
        history[model_id] = {
            "price_input": float(model.get("price_input") or 0.0),
            "price_output": float(model.get("price_output") or 0.0),
        }
    return history


def _build_global_health_signals(
    source_outputs: list[dict[str, Any]],
    source_failures: list[dict[str, Any]],
) -> dict[str, Any]:
    signals: dict[str, Any] = {}
    failure_map = {item["source_id"]: item for item in source_failures}
    for item in source_outputs:
        source = item["source"]
        bundle = item["bundle"]
        source_id = source.id
        failure = failure_map.get(source_id)
        total_models = len(bundle.get("models") or [])
        signals[source_id] = {
            "status": "degraded" if failure else "healthy",
            "models_total": total_models,
            "fallback_used": failure.get("fallback_used", False) if failure else False,
            "error": failure.get("error", "") if failure else "",
        }
    for failure in source_failures:
        source_id = failure["source_id"]
        if source_id not in signals:
            signals[source_id] = {
                "status": "failed",
                "models_total": 0,
                "fallback_used": failure.get("fallback_used", False),
                "error": failure.get("error", ""),
            }
    return signals
