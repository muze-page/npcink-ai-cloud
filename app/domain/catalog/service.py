from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.adapters.providers.base import ProviderAdapter
from app.adapters.providers.registry import build_provider_adapters
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.models import ProviderCallRecord
from app.domain.health.scoring import assess_instance_health
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_PROFILE_ID,
    AUDIO_NARRATION_QUALITY_MODEL_ID,
    AUDIO_NARRATION_QUALITY_PROFILE_ID,
    FREE_GPT55_TEXT_PROFILE_ID,
    GROK_IMAGINE_IMAGE_MODEL_ID,
    GROK_IMAGINE_IMAGE_PROFILE_ID,
    TEXT_AI_PROFILE_ID,
    VISION_AI_PROFILE_ID,
)
from app.domain.wordpress_ai_connector.routing_profiles import (
    WP_AI_CONNECTOR_PROFILE_SPECS,
)

DEFAULT_RECOMMENDED_PROFILE_IDS = (
    TEXT_AI_PROFILE_ID,
    FREE_GPT55_TEXT_PROFILE_ID,
    "text.economy",
    "text.balanced",
    "text.quality",
    VISION_AI_PROFILE_ID,
    "vision.default",
    AUDIO_NARRATION_PROFILE_ID,
    AUDIO_NARRATION_QUALITY_PROFILE_ID,
    GROK_IMAGINE_IMAGE_PROFILE_ID,
    "embed.default",
)

ALLOWED_MODEL_COST_TIERS = {"budget", "balanced", "premium"}
ALLOWED_MODEL_VISIBILITY = {"default", "advanced", "hidden"}
ALLOWED_ADMIN_MODEL_SORT_FIELDS = {
    "provider_id",
    "model_id",
    "confidence",
    "updated_at",
    "recommended",
    "cost_tier",
    "visibility",
}
ALLOWED_ADMIN_MODEL_SORT_DIRECTIONS = {"asc", "desc"}


class CatalogService:
    def __init__(
        self,
        database_url: str,
        providers: dict[str, ProviderAdapter] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.database_url = database_url
        self.settings = settings or get_settings()
        self.providers = (
            providers if providers is not None else build_provider_adapters(self.settings)
        )

    def get_revision(self) -> dict[str, str]:
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            latest = repository.get_latest_revision()

        if latest is None:
            return {"revision": "bootstrap", "source": "bootstrap"}

        return {
            "revision": latest.revision,
            "source": latest.source,
        }

    def list_models(
        self,
        *,
        provider_id: str | None = None,
        feature: str | None = None,
        status: str | None = None,
        search: str | None = None,
        fallback_candidate: bool | None = None,
        recommended_for: str | None = None,
        deprecated_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            recommended_sets = self._build_recommended_sets(repository)
            recommended_index = self._build_recommended_index(recommended_sets)
            revision = repository.get_latest_revision()

            if recommended_for:
                recommended_profile = recommended_sets.get(
                    recommended_for,
                    {
                        "profile_id": recommended_for,
                        "model_ids": [],
                        "instance_ids": [],
                    },
                )
                models = self._filter_models(
                    repository.list_models_by_ids(recommended_profile["model_ids"]),
                    provider_id=provider_id,
                    feature=feature,
                    status=status,
                    search=search,
                    fallback_candidate=fallback_candidate,
                    deprecated_only=deprecated_only,
                )
                total = len(models)
                models = models[offset : offset + limit]
            else:
                models, total = repository.list_models(
                    provider_id=provider_id,
                    feature=feature,
                    status=status,
                    search=search,
                    fallback_candidate=fallback_candidate,
                    deprecated_only=deprecated_only,
                    limit=limit,
                    offset=offset,
                )

            items = []
            for model in models:
                serialized = self._serialize_model(
                    model,
                    recommended_index,
                    selected_profile_id=recommended_for,
                )
                items.append(
                    {
                        **serialized,
                        "platform_model": {
                            "surface": "platform_models",
                            "provider_id": serialized["provider_id"],
                            "model_id": serialized["model_id"],
                        },
                    }
                )

        return {
            "items": items,
            "total": total,
            "revision": revision.revision if revision is not None else "bootstrap",
            "recommended_sets": recommended_sets,
            "recommended_for": recommended_for,
            "platform_models": {
                "surface": "platform_models",
                "total": total,
                "recommended_for": recommended_for,
            },
        }

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            model = repository.get_model(model_id)

            if model is None:
                return None

            instances = repository.list_instances_for_model(model_id)
            recommended_sets = self._build_recommended_sets(repository)
            recommended_index = self._build_recommended_index(recommended_sets)

        serialized = self._serialize_model(model, recommended_index)

        return {
            **serialized,
            "instances": [
                {
                    "instance_id": instance.instance_id,
                    "provider_id": instance.provider_id,
                    "endpoint_variant": instance.endpoint_variant,
                    "region": instance.region,
                    "capability_tags": instance.capability_tags,
                    "health_status": instance.health_status,
                    "is_default": instance.is_default,
                    "weight": instance.weight,
                }
                for instance in instances
            ],
            "recommended_sets": recommended_sets,
            "platform_model": {
                "surface": "platform_models",
                "provider_id": serialized["provider_id"],
                "model_id": serialized["model_id"],
            },
        }

    def refresh_catalog(self, provider_ids: list[str] | None = None) -> dict[str, Any]:
        selected_ids = provider_ids or list(self.providers.keys())
        refreshed: list[str] = []
        revision = self._build_catalog_revision()

        unknown_providers = sorted(set(selected_ids) - set(self.providers.keys()))
        if unknown_providers:
            raise ValueError(f"unknown providers: {', '.join(unknown_providers)}")

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)

            for provider_id in selected_ids:
                adapter = self.providers[provider_id]
                snapshot = adapter.fetch_catalog()
                repository.upsert_provider_snapshot(snapshot, revision)
                refreshed.append(provider_id)

            repository.create_revision(
                revision,
                None,
                source="provider_refresh",
                notes="providers=" + ",".join(refreshed),
            )
            self._sync_default_routing(repository, revision)
            session.commit()

        return {
            "revision": revision,
            "providers": refreshed,
            "refreshed_count": len(refreshed),
        }

    def _build_catalog_revision(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        return f"catalog-{timestamp}-{uuid4().hex[:8]}"

    def scan_provider_health(self, provider_ids: list[str] | None = None) -> dict[str, Any]:
        requested_ids = set(provider_ids or [])
        unknown_providers = sorted(requested_ids - set(self.providers.keys()))
        if unknown_providers:
            raise ValueError(f"unknown providers: {', '.join(unknown_providers)}")

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            instances = repository.list_instances_for_provider()
            now = datetime.now(UTC)

            selected_ids = requested_ids or {instance.provider_id for instance in instances}
            scanned_count = 0
            status_counts = {
                "healthy": 0,
                "degraded": 0,
                "unhealthy": 0,
            }
            selected_instances = [
                instance for instance in instances if instance.provider_id in selected_ids
            ]
            provider_calls = repository.list_provider_calls_for_instances(
                [instance.instance_id for instance in selected_instances]
            )
            provider_calls_by_instance: dict[str, list[ProviderCallRecord]] = {}
            for provider_call in provider_calls:
                provider_calls_by_instance.setdefault(provider_call.instance_id, []).append(
                    provider_call
                )

            for instance in selected_instances:
                assessment = assess_instance_health(
                    provider_calls_by_instance.get(instance.instance_id, []),
                    now=now,
                )
                repository.update_instance_health_status(
                    instance.instance_id,
                    assessment.status,
                )

                repository.record_health_snapshot(
                    provider_id=instance.provider_id,
                    instance_id=instance.instance_id,
                    status=assessment.status,
                    reason=assessment.reason,
                )
                scanned_count += 1
                status_counts[assessment.status] += 1

            session.commit()

        return {
            "providers": sorted(selected_ids),
            "scanned_count": scanned_count,
            "status_counts": status_counts,
        }

    def _serialize_model(
        self,
        model: Any,
        recommended_index: dict[str, dict[str, Any]],
        *,
        selected_profile_id: str | None = None,
    ) -> dict[str, Any]:
        recommended_data = recommended_index.get(
            model.model_id,
            {"profiles": [], "ranks": {}},
        )
        item = {
            "model_id": model.model_id,
            "provider_id": model.provider_id,
            "family": model.family,
            "feature": model.feature,
            "status": model.status,
            "context_window": model.context_window,
            "price_input": model.price_input,
            "price_output": model.price_output,
            "is_deprecated": model.is_deprecated,
            "fallback_candidate": model.fallback_candidate,
            "revision": model.revision,
            "recommended_profiles": recommended_data["profiles"],
        }
        if selected_profile_id is not None:
            item["recommended_rank"] = recommended_data["ranks"].get(selected_profile_id)
        return item

    def _serialize_timestamp(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")

    def _build_recommended_sets(
        self,
        repository: CatalogRepository,
    ) -> dict[str, dict[str, Any]]:
        recommended_sets: dict[str, dict[str, Any]] = {}

        for profile_id in DEFAULT_RECOMMENDED_PROFILE_IDS:
            binding = repository.get_routing_binding(profile_id)
            instance_ids = binding.candidate_instance_ids if binding is not None else []
            instances = repository.list_instances_by_ids(instance_ids)
            model_ids: list[str] = []
            for instance in instances:
                if instance.model_id not in model_ids:
                    model_ids.append(instance.model_id)

            recommended_sets[profile_id] = {
                "profile_id": profile_id,
                "model_ids": model_ids,
                "instance_ids": instance_ids,
            }

        return recommended_sets

    def _build_recommended_index(
        self,
        recommended_sets: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for profile_id, recommended_set in recommended_sets.items():
            for rank, model_id in enumerate(recommended_set["model_ids"], start=1):
                entry = index.setdefault(model_id, {"profiles": [], "ranks": {}})
                if profile_id not in entry["profiles"]:
                    entry["profiles"].append(profile_id)
                entry["ranks"][profile_id] = rank
        return index

    def _filter_models(
        self,
        models: list[Any],
        *,
        provider_id: str | None,
        feature: str | None,
        status: str | None,
        search: str | None,
        fallback_candidate: bool | None,
        deprecated_only: bool,
    ) -> list[Any]:
        filtered = models
        if provider_id:
            filtered = [model for model in filtered if model.provider_id == provider_id]
        if feature:
            filtered = [model for model in filtered if model.feature == feature]
        if status:
            filtered = [model for model in filtered if model.status == status]
        if search:
            search_term = search.lower()
            filtered = [model for model in filtered if search_term in model.model_id.lower()]
        if fallback_candidate is not None:
            filtered = [
                model for model in filtered if model.fallback_candidate == fallback_candidate
            ]
        if deprecated_only:
            filtered = [model for model in filtered if model.is_deprecated]
        return filtered

    def _normalize_admin_model_sort_by(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "provider_id"
        if normalized not in ALLOWED_ADMIN_MODEL_SORT_FIELDS:
            raise ValueError(f"unsupported sort_by: {normalized}")
        return normalized

    def _normalize_admin_model_sort_dir(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "asc"
        if normalized not in ALLOWED_ADMIN_MODEL_SORT_DIRECTIONS:
            raise ValueError(f"unsupported sort_dir: {normalized}")
        return normalized

    def _sort_admin_models(
        self,
        items: list[dict[str, Any]],
        *,
        sort_by: str,
        sort_dir: str,
    ) -> list[dict[str, Any]]:
        reverse = sort_dir == "desc"

        def key(item: dict[str, Any]) -> Any:
            if sort_by == "model_id":
                return str(item.get("model_id", "")).lower()
            if sort_by == "updated_at":
                return str(item.get("updated_at", "") or "")
            return str(item.get("provider_id", "")).lower()

        sorted_items = sorted(
            items,
            key=lambda item: (
                key(item),
                str(item.get("provider_id", "")).lower(),
                str(item.get("model_id", "")).lower(),
            ),
            reverse=reverse,
        )
        return sorted_items

    def _sync_default_routing(
        self,
        repository: CatalogRepository,
        revision: str,
    ) -> None:
        repository.session.flush()
        instances = repository.list_instances_for_provider()

        def select_candidates(
            execution_kind: str,
            ordered_tiers: list[str],
            *,
            exact_model_id: str | None = None,
        ) -> list[str]:
            scored: list[tuple[int, int, str]] = []
            instances_by_id = {instance.instance_id: instance for instance in instances}

            for instance in instances:
                tags = set(instance.capability_tags)
                if execution_kind not in tags:
                    continue

                tier_rank = next(
                    (rank for rank, tier in enumerate(ordered_tiers) if tier in tags),
                    None,
                )
                if tier_rank is None:
                    continue

                scored.append((tier_rank, -instance.weight, instance.instance_id))

            if exact_model_id:
                exact_scored = [
                    item for item in scored if instances_by_id[item[2]].model_id == exact_model_id
                ]
                if exact_scored:
                    exact_scored.sort()
                    return [instance_id for _, _, instance_id in exact_scored]

            scored.sort()
            return [instance_id for _, _, instance_id in scored]

        profile_specs: dict[str, tuple[str, list[str]]] = {
            TEXT_AI_PROFILE_ID: ("text", ["hosted-free", "free-gpt55"]),
            FREE_GPT55_TEXT_PROFILE_ID: ("text", ["free-gpt55"]),
            "text.economy": ("text", ["economy", "balanced"]),
            "text.balanced": ("text", ["balanced", "economy", "quality"]),
            "text.quality": ("text", ["quality", "balanced"]),
            VISION_AI_PROFILE_ID: ("vision", ["default", "quality"]),
            "vision.default": ("vision", ["default", "quality"]),
            AUDIO_NARRATION_PROFILE_ID: (
                "audio_generation",
                ["default", "balanced", "narration"],
            ),
            AUDIO_NARRATION_QUALITY_PROFILE_ID: (
                "audio_generation",
                ["quality", "narration"],
            ),
            GROK_IMAGINE_IMAGE_PROFILE_ID: (
                "image_generation",
                ["z-image", "quality", "default"],
            ),
            "embed.default": ("embedding", ["default", "embedding"]),
        }
        profile_specs.update(
            {
                spec.profile_id: ("text", list(spec.ordered_tiers))
                for spec in WP_AI_CONNECTOR_PROFILE_SPECS
            }
        )

        for profile_id, (execution_kind, ordered_tiers) in profile_specs.items():
            wp_ai_spec = next(
                (
                    spec
                    for spec in WP_AI_CONNECTOR_PROFILE_SPECS
                    if spec.profile_id == profile_id
                ),
                None,
            )
            candidate_instance_ids = select_candidates(
                execution_kind,
                ordered_tiers,
                exact_model_id=(
                    GROK_IMAGINE_IMAGE_MODEL_ID
                    if profile_id == GROK_IMAGINE_IMAGE_PROFILE_ID
                    else AUDIO_NARRATION_MODEL_ID
                    if profile_id == AUDIO_NARRATION_PROFILE_ID
                    else AUDIO_NARRATION_QUALITY_MODEL_ID
                    if profile_id == AUDIO_NARRATION_QUALITY_PROFILE_ID
                    else None
                ),
            )
            default_policy_json = {
                "allow_fallback": True,
                "max_retries": 0,
                "timeout_ms": 30000,
            }
            if wp_ai_spec is not None:
                default_policy_json = {
                    "allow_fallback": wp_ai_spec.allow_fallback,
                    "max_retries": wp_ai_spec.max_retries,
                    "timeout_ms": wp_ai_spec.timeout_ms,
                    "managed_surface": "wordpress_ai_connector",
                    "task_group": wp_ai_spec.group_id,
                    "tasks": list(wp_ai_spec.tasks),
                }
            repository.upsert_routing_profile(
                profile_id=profile_id,
                execution_kind=execution_kind,
                default_policy_json=default_policy_json,
            )
            repository.upsert_routing_binding(
                profile_id=profile_id,
                candidate_instance_ids=candidate_instance_ids,
                selection_policy_json={
                    "strategy": "ordered",
                    "ordered_tiers": ordered_tiers,
                    **(
                        {
                            "managed_surface": "wordpress_ai_connector",
                            "task_group": wp_ai_spec.group_id,
                        }
                        if wp_ai_spec is not None
                        else {}
                    ),
                },
                revision=revision,
            )
