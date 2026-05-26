from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.adapters.providers.base import ProviderAdapter
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderCallRecord
from app.domain.catalog.provider_connections_admin import (
    ProviderConnectionsAdminService,
)
from app.domain.catalog.recognition_admin import RecognitionAdminService
from app.domain.catalog.recognition import (
    build_recognition_bundle,
    build_recognition_bundle_from_upstream_snapshot,
    inspect_upstream_evidence_snapshot,
    load_active_upstream_evidence_payload,
)
from app.domain.health.scoring import assess_instance_health
from app.workers.model_intelligence_publisher import inspect_publisher_state

DEFAULT_RECOMMENDED_PROFILE_IDS = (
    "text.economy",
    "text.balanced",
    "text.quality",
    "vision.default",
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
        settings: Settings | None = None,
        providers: dict[str, ProviderAdapter] | None = None,
        recognition_review_providers: dict[str, ProviderAdapter] | None = None,
        recognition_evidence_snapshot_path: str | None = None,
    ) -> None:
        self.database_url = database_url
        self.settings = settings
        self.recognition_evidence_snapshot_path = recognition_evidence_snapshot_path
        self.recognition_admin = RecognitionAdminService(
            database_url=database_url,
            bundle_loader=self.get_admin_recognition_bundle,
            recognition_price_cny_per_usd=(
                float(settings.recognition_price_cny_per_usd)
                if settings is not None
                else 7.2
            ),
        )
        self.provider_connections_admin = ProviderConnectionsAdminService(
            database_url=database_url,
            settings=settings,
            sync_default_routing=self._sync_default_routing,
        )
        self.providers = providers or {
            OpenAIProviderAdapter.provider_id: OpenAIProviderAdapter()
        }
        self.recognition_review_providers = recognition_review_providers or {}

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

    def get_recognition_revision(self) -> dict[str, Any]:
        bundle = self.get_recognition_bundle()
        return {
            "revision": bundle["revision"],
            "schema_version": bundle["schema_version"],
            "published_at": bundle["published_at"],
            "checksum": bundle["checksum"],
        }

    def get_recognition_bundle(self) -> dict[str, Any]:
        publisher_bundle = self._build_recognition_bundle_from_publisher_bundle()
        if publisher_bundle is not None:
            return publisher_bundle

        snapshot_bundle = self._build_public_recognition_bundle_from_snapshot()
        if snapshot_bundle is not None:
            return snapshot_bundle

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            latest = repository.get_latest_revision()
            models = repository.list_all_models()

        published_at = self._serialize_timestamp(
            latest.created_at if latest is not None else None
        )
        catalog_revision = latest.revision if latest is not None else "bootstrap"
        return build_recognition_bundle(
            models=models,
            catalog_revision=catalog_revision,
            published_at=published_at,
            evidence_snapshot_path=self.recognition_evidence_snapshot_path,
        )

    def _build_public_recognition_bundle_from_snapshot(self) -> dict[str, Any] | None:
        snapshot_meta = inspect_upstream_evidence_snapshot(
            self.recognition_evidence_snapshot_path
        )
        if not snapshot_meta.get("configured") or not snapshot_meta.get("snapshot_exists"):
            return None

        snapshot_path = str(snapshot_meta.get("snapshot_path") or "").strip()
        if not snapshot_path or not Path(snapshot_path).exists():
            return None

        upstream_payload = load_active_upstream_evidence_payload(snapshot_path)
        raw_records = upstream_payload.get("records", {})
        if not isinstance(raw_records, dict) or not raw_records:
            return None

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            latest = repository.get_latest_revision()

        published_at = str(snapshot_meta.get("generated_at") or "").strip() or self._serialize_timestamp(
            latest.created_at if latest is not None else None
        )
        latest_revision = latest.revision if latest is not None else "bootstrap"
        return build_recognition_bundle_from_upstream_snapshot(
            snapshot_payload=upstream_payload,
            catalog_revision=latest_revision,
            published_at=published_at,
            source_label="cloud_intelligence",
        )

    def get_admin_recognition_bundle(self) -> dict[str, Any]:
        publisher_bundle = self._build_admin_recognition_bundle_from_publisher_bundle()
        if publisher_bundle is not None:
            return publisher_bundle

        if not self.recognition_review_providers:
            snapshot_bundle = self._build_admin_recognition_bundle_from_snapshot()
            if snapshot_bundle is not None:
                return snapshot_bundle
            return self._build_empty_admin_recognition_bundle()

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            latest = repository.get_latest_revision()

        published_at = self._serialize_timestamp(
            latest.created_at if latest is not None else None
        )
        latest_revision = latest.revision if latest is not None else "bootstrap"
        review_models: list[Any] = []
        profile_names: list[str] = []

        for adapter in self.recognition_review_providers.values():
            snapshot = adapter.fetch_catalog()
            profile_name = str(getattr(adapter, "sample_catalog_profile", "") or "").strip()
            if profile_name:
                profile_names.append(profile_name)
            snapshot_updated_at = latest.created_at if latest is not None else datetime.now(UTC)
            for seed in snapshot.models:
                review_models.append(
                    SimpleNamespace(
                        provider_id=snapshot.provider_id,
                        model_id=seed.model_id,
                        family=seed.family,
                        feature=seed.feature,
                        status=seed.status,
                        context_window=seed.context_window,
                        price_input=seed.price_input,
                        price_output=seed.price_output,
                        is_deprecated=False,
                        fallback_candidate=seed.fallback_candidate,
                        revision=latest_revision,
                        raw_json=seed.raw_json or {},
                        updated_at=snapshot_updated_at,
                    )
                )

        review_models.sort(key=lambda item: (str(item.provider_id), str(item.model_id)))
        review_profile_slug = "-".join(sorted({name for name in profile_names if name})) or "review"
        review_revision = f"admin-review-{review_profile_slug}-{latest_revision}"
        return build_recognition_bundle(
            models=review_models,
            catalog_revision=review_revision,
            published_at=published_at,
            evidence_snapshot_path=self.recognition_evidence_snapshot_path,
        )

    def _build_admin_recognition_bundle_from_snapshot(self) -> dict[str, Any] | None:
        snapshot_meta = inspect_upstream_evidence_snapshot(self.recognition_evidence_snapshot_path)
        if not snapshot_meta.get("configured") or not snapshot_meta.get("snapshot_exists"):
            return None

        snapshot_path = str(snapshot_meta.get("snapshot_path") or "").strip()
        if not snapshot_path or not Path(snapshot_path).exists():
            return None

        upstream_payload = load_active_upstream_evidence_payload(snapshot_path)
        raw_records = upstream_payload.get("records", {})
        if not isinstance(raw_records, dict) or not raw_records:
            return None

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            latest = repository.get_latest_revision()

        published_at = str(snapshot_meta.get("generated_at") or "").strip() or self._serialize_timestamp(
            latest.created_at if latest is not None else None
        )
        updated_at = self._parse_timestamp_or_none(published_at) or (
            latest.created_at if latest is not None else datetime.now(UTC)
        )
        latest_revision = latest.revision if latest is not None else "bootstrap"

        review_models: list[Any] = []
        for key, record in raw_records.items():
            if not isinstance(key, str) or not isinstance(record, dict):
                continue
            provider_id, model_id = self._parse_recognition_record_key(key, record)
            if not provider_id or not model_id:
                continue
            review_models.append(
                SimpleNamespace(
                    provider_id=provider_id,
                    model_id=model_id,
                    family="",
                    feature=self._feature_from_recognition_record(record),
                    status="active",
                    context_window=None,
                    price_input=None,
                    price_output=None,
                    is_deprecated=bool(record.get("deprecated", False)),
                    fallback_candidate=False,
                    revision=latest_revision,
                    raw_json={
                        "recognition_source": str(record.get("evidence_source") or "upstream_evidence"),
                        "recognition_admin_bundle": "snapshot_only",
                    },
                    updated_at=updated_at,
                )
            )

        review_models.sort(key=lambda item: (str(item.provider_id), str(item.model_id)))
        bundle = build_recognition_bundle(
            models=review_models,
            catalog_revision=f"admin-intelligence-{latest_revision}",
            published_at=published_at,
            evidence_snapshot_path=self.recognition_evidence_snapshot_path,
        )
        bundle["admin_source"] = {
            "kind": "recognition_evidence_snapshot",
            "configured": True,
            "snapshot_exists": True,
            "snapshot_path": str(snapshot_meta.get("snapshot_path") or ""),
            "version": str(snapshot_meta.get("version") or ""),
            "records_total": len(review_models),
            "generated_at": published_at,
            "source_keys": list(snapshot_meta.get("source_keys") or []),
            "sources": dict(snapshot_meta.get("sources") or {}),
            "source_runs": list(snapshot_meta.get("source_runs") or []),
            "source_run_ids": list(snapshot_meta.get("source_run_ids") or []),
            "source_failures": list(snapshot_meta.get("source_failures") or []),
        }
        return bundle

    def _build_empty_admin_recognition_bundle(self) -> dict[str, Any]:
        snapshot_meta = inspect_upstream_evidence_snapshot(self.recognition_evidence_snapshot_path)
        published_at = self._serialize_timestamp(None)
        bundle = build_recognition_bundle(
            models=[],
            catalog_revision="admin-intelligence-unconfigured",
            published_at=published_at,
            evidence_snapshot_path=self.recognition_evidence_snapshot_path,
        )
        bundle["admin_source"] = {
            "kind": "unconfigured",
            "configured": bool(snapshot_meta.get("configured")),
            "snapshot_exists": bool(snapshot_meta.get("snapshot_exists")),
            "snapshot_path": str(snapshot_meta.get("snapshot_path") or ""),
            "version": str(snapshot_meta.get("version") or ""),
            "records_total": 0,
            "generated_at": str(snapshot_meta.get("generated_at") or ""),
            "source_keys": list(snapshot_meta.get("source_keys") or []),
            "sources": dict(snapshot_meta.get("sources") or {}),
            "source_runs": list(snapshot_meta.get("source_runs") or []),
            "source_run_ids": list(snapshot_meta.get("source_run_ids") or []),
            "source_failures": list(snapshot_meta.get("source_failures") or []),
        }
        return bundle

    def _build_recognition_bundle_from_publisher_bundle(self) -> dict[str, Any] | None:
        payload = self._load_publisher_bundle_payload()
        if payload is None:
            return None
        published_at = str(payload.get("generated_at") or "").strip() or self._serialize_timestamp(None)
        bundle = self._build_publisher_recognition_bundle(
            payload=payload,
            published_at=published_at,
            source_label="publisher_bundle",
        )
        bundle["sources"]["recognition_derivation"] = "publisher_bundle"
        return bundle

    def _build_admin_recognition_bundle_from_publisher_bundle(self) -> dict[str, Any] | None:
        payload = self._load_publisher_bundle_payload()
        if payload is None:
            return None
        published_at = str(payload.get("generated_at") or "").strip() or self._serialize_timestamp(None)
        bundle = self._build_publisher_recognition_bundle(
            payload=payload,
            published_at=published_at,
            source_label="publisher_bundle",
        )
        source_rows = self._normalize_publisher_sources(payload.get("sources"))
        summary_payload = self._load_publisher_run_summary_payload()
        publisher_state = self._get_publisher_state()
        bundle["admin_source"] = {
            "kind": "publisher_bundle",
            "configured": True,
            "snapshot_exists": True,
            "snapshot_path": str(self._publisher_bundle_path() or ""),
            "version": str(payload.get("schema_version") or ""),
            "records_total": len(bundle["models"]),
            "generated_at": published_at,
            "hours_old": publisher_state.get("hours_old"),
            "freshness_status": publisher_state.get("freshness_status") or "missing",
            "source_keys": [item["source_id"] for item in source_rows],
            "sources": {
                item["source_id"]: str(item.get("status") or "")
                for item in source_rows
                if str(item.get("source_id") or "").strip()
            },
            "failed_sources": list(publisher_state.get("failed_sources") or []),
            "health_status": str(publisher_state.get("health_status") or "error"),
            "health_issues": list(publisher_state.get("health_issues") or []),
            "operator_alerts": list(publisher_state.get("operator_alerts") or []),
            "bundle_exists": bool(publisher_state.get("bundle_exists")),
            "fallback": dict(publisher_state.get("fallback") or {}),
            "latest_publication": dict(publisher_state.get("latest_publication") or {}),
            "recent_publications": list(publisher_state.get("recent_publications") or []),
            "source_runs": [
                {
                    "source": item["source_id"],
                    "run_id": f"publisher:{published_at}:{item['source_id']}",
                    "status": str(item.get("status") or "ok"),
                    "generated_at": str(item.get("fetched_at") or published_at),
                    "records_fetched": int(item.get("records_total") or 0),
                    "records_accepted": int(item.get("records_total") or 0),
                    "duration_ms": 0,
                }
                for item in source_rows
            ],
            "source_run_ids": [
                f"publisher:{published_at}:{item['source_id']}"
                for item in source_rows
            ],
            "source_failures": list(publisher_state.get("failed_sources") or summary_payload.get("failed_sources") or []),
        }
        return bundle

    def _build_publisher_recognition_bundle(
        self,
        *,
        payload: dict[str, Any],
        published_at: str,
        source_label: str,
    ) -> dict[str, Any]:
        latest_revision = "bootstrap"
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            latest = repository.get_latest_revision()
            if latest is not None:
                latest_revision = latest.revision

        snapshot_payload = self._convert_publisher_bundle_to_snapshot_payload(payload)
        bundle = build_recognition_bundle_from_upstream_snapshot(
            snapshot_payload=snapshot_payload,
            catalog_revision=f"{source_label}-{latest_revision}",
            published_at=published_at,
            source_label=source_label,
        )
        publisher_index = {
            (
                str(item.get("provider") or "").strip(),
                str(item.get("model_id") or "").strip(),
            ): item
            for item in payload.get("models", [])
            if isinstance(item, dict)
        }
        for record in bundle["models"]:
            key = (str(record.get("provider") or "").strip(), str(record.get("model_id") or "").strip())
            publisher_record = publisher_index.get(key)
            if publisher_record is None:
                continue
            source_ids = [
                str(entry).strip()
                for entry in publisher_record.get("source_ids", [])
                if str(entry).strip()
            ]
            if not source_ids:
                source_ids = [str(item["source_id"]) for item in self._normalize_publisher_sources(payload.get("sources"))]
            price_reference_kind = str(publisher_record.get("price_reference_kind") or "unavailable").strip().lower()
            price_confidence = 0.95 if price_reference_kind == "exact" else (0.7 if price_reference_kind == "estimated" else 0.0)
            record.update(
                {
                    "source": source_label,
                    "aliases": [
                        str(entry).strip()
                        for entry in publisher_record.get("aliases", [])
                        if str(entry).strip()
                    ],
                    "source_coverage_sources": source_ids,
                    "source_coverage_count": len(source_ids),
                    "short_description": str(publisher_record.get("short_description") or record.get("short_description") or ""),
                    "best_for": str(publisher_record.get("best_for") or record.get("best_for") or ""),
                    "supports": [
                        str(entry).strip()
                        for entry in publisher_record.get("supports", [])
                        if str(entry).strip()
                    ],
                    "price_summary": str(publisher_record.get("price_summary") or record.get("price_summary") or ""),
                    "why_recommended": str(publisher_record.get("why_recommended") or record.get("why_recommended") or ""),
                    "updated_at": str(publisher_record.get("updated_at") or record.get("updated_at") or published_at),
                    "price_source": source_ids[0] if source_ids else source_label,
                    "price_updated_at": str(publisher_record.get("updated_at") or published_at),
                    "price_confidence": price_confidence,
                    "has_price_conflict": False,
                    "price_sources": [
                        {
                            "source": source_id,
                            "price_source": source_id,
                            "price_input": publisher_record.get("price_input"),
                            "price_output": publisher_record.get("price_output"),
                            "price_updated_at": str(publisher_record.get("updated_at") or published_at),
                            "price_confidence": price_confidence,
                        }
                        for source_id in source_ids
                    ],
                }
            )
        return bundle

    def _convert_publisher_bundle_to_snapshot_payload(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        source_rows = self._normalize_publisher_sources(payload.get("sources"))
        generated_at = str(payload.get("generated_at") or "").strip() or self._serialize_timestamp(None)
        records: dict[str, dict[str, Any]] = {}
        for item in payload.get("models", []):
            if not isinstance(item, dict):
                continue
            provider_id = str(item.get("provider") or "").strip()
            model_id = str(item.get("model_id") or "").strip()
            if not provider_id or not model_id:
                continue
            supports = [
                str(entry).strip().lower()
                for entry in item.get("supports", [])
                if str(entry).strip()
            ]
            model_type = str(item.get("model_type") or "").strip().lower()
            preview_type = str(item.get("preview_type") or "").strip().lower()
            capabilities = {
                "text_input": "text" in supports or model_type not in {"embedding", "image_generation"},
                "image_input": "vision" in supports or model_type == "vision",
                "image_output": "image_generation" in supports or model_type == "image_generation",
                "vision": "vision" in supports or model_type == "vision",
                "tools": "tools" in supports,
                "structured_output": "structured" in supports or "structured_output" in supports,
            }
            price_reference_kind = str(item.get("price_reference_kind") or "unavailable").strip().lower()
            confidence = 0.95 if price_reference_kind == "exact" else (0.85 if price_reference_kind == "estimated" else 0.75)
            source_ids = [
                str(entry).strip()
                for entry in item.get("source_ids", [])
                if str(entry).strip()
            ]
            records[f"{provider_id}::{model_id}"] = {
                "provider": provider_id,
                "model_id": model_id,
                "aliases": list(item.get("aliases") or []),
                "evidence_source": "publisher_bundle",
                "model_type": model_type or "chat",
                "preview_type": preview_type or ("embedding" if model_type == "embedding" else "text"),
                "input_modalities": self._publisher_input_modalities(supports, model_type),
                "output_modalities": self._publisher_output_modalities(supports, model_type),
                "capabilities": capabilities,
                "confidence": confidence,
                "deprecated": bool(item.get("deprecated", False)),
                "price_input": item.get("price_input"),
                "price_output": item.get("price_output"),
                "source_details": {
                    source_id: {
                        "price_input": item.get("price_input"),
                        "price_output": item.get("price_output"),
                        "price_source": source_id,
                        "price_updated_at": str(item.get("updated_at") or generated_at),
                        "price_confidence": confidence,
                        "model_type": model_type or "chat",
                        "preview_type": preview_type or ("embedding" if model_type == "embedding" else "text"),
                        "capabilities": capabilities,
                        "confidence": confidence,
                    }
                    for source_id in source_ids
                },
            }
        return {
            "version": str(payload.get("schema_version") or "model_intelligence_bundle_v1"),
            "generated_at": generated_at,
            "sources": {
                item["source_id"]: str(item.get("fetched_at") or item.get("status") or generated_at)
                for item in source_rows
            },
            "records": records,
        }

    def _publisher_input_modalities(self, supports: list[str], model_type: str) -> list[str]:
        if model_type == "embedding":
            return ["text"]
        if "vision" in supports or model_type == "vision":
            return ["text", "image"]
        return ["text"]

    def _publisher_output_modalities(self, supports: list[str], model_type: str) -> list[str]:
        if model_type == "embedding":
            return ["embedding"]
        if "image_generation" in supports or model_type == "image_generation":
            return ["image"]
        return ["text"]

    def _load_publisher_bundle_payload(self) -> dict[str, Any] | None:
        bundle_path = self._publisher_bundle_path()
        if not bundle_path or not bundle_path.exists():
            return None
        payload = json.loads(bundle_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        models = payload.get("models")
        if not isinstance(models, list) or not models:
            return None
        return payload

    def _load_publisher_run_summary_payload(self) -> dict[str, Any]:
        if self.settings is None:
            return {}
        summary_path = str(self.settings.model_intelligence_run_summary_path or "").strip()
        if not summary_path:
            return {}
        path = Path(summary_path)
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def _publisher_bundle_path(self) -> Path | None:
        if self.settings is None:
            return None
        bundle_path = str(self.settings.model_intelligence_bundle_path or "").strip()
        if not bundle_path:
            return None
        return Path(bundle_path)

    def _get_publisher_state(self) -> dict[str, Any]:
        if self.settings is None:
            return {}
        return inspect_publisher_state(self.settings)

    def _normalize_publisher_sources(self, payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, list):
            return []
        normalized: list[dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "").strip()
            if not source_id:
                continue
            normalized.append(
                {
                    "source_id": source_id,
                    "status": str(item.get("status") or "").strip() or "ok",
                    "fetched_at": str(item.get("fetched_at") or "").strip(),
                    "records_total": int(item.get("records_total") or 0),
                }
            )
        return normalized

    def _parse_recognition_record_key(
        self,
        key: str,
        record: dict[str, Any],
    ) -> tuple[str, str]:
        if "::" in key:
            provider_id, model_id = key.split("::", 1)
            return str(provider_id).strip(), str(model_id).strip()
        return str(record.get("provider") or "").strip(), str(record.get("model_id") or "").strip()

    def _feature_from_recognition_record(self, record: dict[str, Any]) -> str:
        model_type = str(record.get("model_type") or "").strip().lower()
        if model_type == "vision":
            return "vision"
        if model_type == "embedding":
            return "embedding"
        if model_type == "image_generation":
            return "image"
        return "text"

    def _parse_timestamp_or_none(self, value: str | None) -> datetime | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(normalized).astimezone(UTC)
        except ValueError:
            return None

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
            annotations = {
                item.model_id: item for item in repository.list_model_annotations()
            }
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
                    annotation=annotations.get(model.model_id),
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
            annotation = repository.get_model_annotation(model_id)

        serialized = self._serialize_model(model, recommended_index, annotation=annotation)

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

    def list_admin_models(
        self,
        *,
        provider_id: str | None = None,
        feature: str | None = None,
        status: str | None = None,
        search: str | None = None,
        recommended: bool | None = None,
        cost_tier: str | None = None,
        visibility: str | None = None,
        deprecated_only: bool = False,
        page: int = 1,
        per_page: int = 50,
        sort_by: str = "provider_id",
        sort_dir: str = "asc",
    ) -> dict[str, Any]:
        bundle = self.get_recognition_bundle()
        recognition_index = {
            (item["provider"], item["model_id"]): item for item in bundle["models"]
        }

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            recommended_sets = self._build_recommended_sets(repository)
            recommended_index = self._build_recommended_index(recommended_sets)
            models = self._filter_models(
                repository.list_all_models(),
                provider_id=provider_id,
                feature=feature,
                status=status,
                search=search,
                fallback_candidate=None,
                deprecated_only=deprecated_only,
            )
            annotations = {
                item.model_id: item
                for item in repository.list_model_annotations(
                    [model.model_id for model in models]
                )
            }
            recognition_annotations = {
                (item.provider_id, item.model_id): item
                for item in repository.list_recognition_annotations(
                    [(model.provider_id, model.model_id) for model in models]
                )
            }

        items = []
        for model in models:
            serialized = self._serialize_model(model, recommended_index)
            annotation = self._serialize_model_annotation(annotations.get(model.model_id))
            recognition = self._serialize_recognition_summary(
                recognition_index.get((model.provider_id, model.model_id))
            )
            recognition_review = self._serialize_recognition_annotation(
                recognition_annotations.get((model.provider_id, model.model_id))
            )
            item = {
                **serialized,
                "annotation": annotation,
                "recognition": recognition,
                "recognition_review": recognition_review,
                "platform_model": {
                    "surface": "platform_models",
                    "provider_id": serialized["provider_id"],
                    "model_id": serialized["model_id"],
                },
            }
            if recommended is not None and annotation["recommended"] is not recommended:
                continue
            if cost_tier and annotation["cost_tier"] != cost_tier:
                continue
            if visibility and annotation["visibility"] != visibility:
                continue
            items.append(item)

        normalized_sort_by = self._normalize_admin_model_sort_by(sort_by)
        normalized_sort_dir = self._normalize_admin_model_sort_dir(sort_dir)
        items = self._sort_admin_models(
            items,
            sort_by=normalized_sort_by,
            sort_dir=normalized_sort_dir,
        )

        total = len(items)
        normalized_page = max(1, int(page))
        normalized_per_page = max(1, int(per_page))
        offset = (normalized_page - 1) * normalized_per_page
        paged_items = items[offset : offset + normalized_per_page]
        recommended_total = sum(1 for item in items if item["annotation"]["recommended"])
        cost_tier_counts = {
            tier: sum(1 for item in items if item["annotation"]["cost_tier"] == tier)
            for tier in sorted(ALLOWED_MODEL_COST_TIERS)
        }
        visibility_counts = {
            level: sum(1 for item in items if item["annotation"]["visibility"] == level)
            for level in sorted(ALLOWED_MODEL_VISIBILITY)
        }

        return {
            "filters": {
                "provider_id": provider_id or "",
                "feature": feature or "",
                "status": status or "",
                "search": search or "",
                "recommended": recommended,
                "cost_tier": cost_tier or "",
                "visibility": visibility or "",
                "deprecated_only": deprecated_only,
                "page": normalized_page,
                "per_page": normalized_per_page,
                "offset": offset,
            },
            "total": total,
            "items": paged_items,
            "pagination": {
                "page": normalized_page,
                "per_page": normalized_per_page,
                "pages_total": max(1, (total + normalized_per_page - 1) // normalized_per_page),
                "offset": offset,
            },
            "sort": {
                "sort_by": normalized_sort_by,
                "sort_dir": normalized_sort_dir,
            },
            "summary": {
                "recommended_total": recommended_total,
                "cost_tier_counts": cost_tier_counts,
                "visibility_counts": visibility_counts,
            },
            "platform_models": {
                "surface": "platform_models",
                "total": total,
                "recommended_total": recommended_total,
            },
            "recognition_bundle": {
                "revision": bundle["revision"],
                "checksum": bundle["checksum"],
                "published_at": bundle["published_at"],
            },
        }

    def get_admin_model(self, model_id: str) -> dict[str, Any] | None:
        bundle = self.get_recognition_bundle()
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            model = repository.get_model(model_id)
            if model is None:
                return None
            annotation = repository.get_model_annotation(model_id)
            recognition_annotation = repository.get_recognition_annotation(
                provider_id=model.provider_id,
                model_id=model.model_id,
            )
            recommended_sets = self._build_recommended_sets(repository)
            recommended_index = self._build_recommended_index(recommended_sets)

        recognition = next(
            (
                item
                for item in bundle["models"]
                if item["provider"] == model.provider_id and item["model_id"] == model.model_id
            ),
            None,
        )

        return {
            **self._serialize_model(model, recommended_index),
            "annotation": self._serialize_model_annotation(annotation),
            "recognition": recognition,
            "recognition_review": self._serialize_recognition_annotation(
                recognition_annotation
            ),
            "platform_model": {
                "surface": "platform_models",
                "provider_id": model.provider_id,
                "model_id": model.model_id,
            },
            "recognition_bundle": {
                "revision": bundle["revision"],
                "checksum": bundle["checksum"],
                "published_at": bundle["published_at"],
            },
        }

    def upsert_admin_model_annotation(
        self,
        *,
        model_id: str,
        recommended: bool,
        cost_tier: str | None,
        visibility: str,
        badges: list[str] | None = None,
        operator_notes: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_cost_tier = self._normalize_model_cost_tier(cost_tier)
        normalized_visibility = self._normalize_model_visibility(visibility)
        normalized_badges = self._normalize_badges(badges)
        normalized_notes = str(operator_notes or "").strip() or None

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            model = repository.get_model(model_id)
            if model is None:
                return None
            annotation = repository.upsert_model_annotation(
                model_id=model.model_id,
                provider_id=model.provider_id,
                recommended=recommended,
                cost_tier=normalized_cost_tier,
                visibility=normalized_visibility,
                badges_json=normalized_badges,
                operator_notes=normalized_notes,
                metadata_json={"source": "admin_model_annotations_console_v1"},
            )
            session.commit()

        return {
            "model_id": model_id,
            "annotation": self._serialize_model_annotation(annotation),
        }

    def list_admin_recognition_models(
        self,
        *,
        provider_id: str | None = None,
        search: str | None = None,
        review_status: str | None = None,
        in_hosted_catalog: bool | None = None,
        source: str | None = None,
        page: int = 1,
        per_page: int = 50,
        sort_by: str = "provider_id",
        sort_dir: str = "asc",
        quick_filter: str | None = None,
    ) -> dict[str, Any]:
        return self.recognition_admin.list_models(
            provider_id=provider_id,
            search=search,
            review_status=review_status,
            in_hosted_catalog=in_hosted_catalog,
            source=source,
            quick_filter=quick_filter,
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )

    def get_admin_recognition_model(
        self,
        *,
        provider_id: str,
        model_id: str,
    ) -> dict[str, Any] | None:
        return self.recognition_admin.get_model(
            provider_id=provider_id,
            model_id=model_id,
        )

    def upsert_admin_recognition_annotation(
        self,
        *,
        provider_id: str,
        model_id: str,
        review_status: str,
        manual_tags: list[str] | None = None,
        operator_notes: str | None = None,
        recommended: bool = False,
        cost_tier_override: str | None = None,
        visibility: str | None = None,
        badges: list[str] | None = None,
    ) -> dict[str, Any] | None:
        return self.recognition_admin.upsert_annotation(
            provider_id=provider_id,
            model_id=model_id,
            review_status=review_status,
            manual_tags=manual_tags,
            operator_notes=operator_notes,
            recommended=recommended,
            cost_tier_override=cost_tier_override,
            visibility=visibility,
            badges=badges,
        )

    def list_admin_provider_connections(self) -> dict[str, Any]:
        return self.provider_connections_admin.list_connections()

    def get_admin_provider_connection(self, connection_id: str) -> dict[str, Any] | None:
        return self.provider_connections_admin.get_connection(connection_id)

    def upsert_admin_provider_connection(
        self,
        *,
        connection_id: str,
        provider_type: str,
        source_role: str | None = None,
        display_name: str,
        enabled: bool,
        base_url: str,
        config: dict[str, Any] | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        return self.provider_connections_admin.upsert_connection(
            connection_id=connection_id,
            provider_type=provider_type,
            source_role=source_role,
            display_name=display_name,
            enabled=enabled,
            base_url=base_url,
            config=config,
            api_key=api_key,
        )

    def test_admin_provider_connection(self, connection_id: str) -> dict[str, Any] | None:
        return self.provider_connections_admin.test_connection(connection_id)

    def sync_admin_provider_connection_catalog(
        self,
        connection_id: str,
    ) -> dict[str, Any] | None:
        return self.provider_connections_admin.sync_connection_catalog(connection_id)

    def promote_admin_provider_connection_execution_revision(
        self,
        connection_id: str,
    ) -> dict[str, Any] | None:
        return self.provider_connections_admin.promote_connection_execution_revision(
            connection_id
        )

    def refresh_catalog(self, provider_ids: list[str] | None = None) -> dict[str, Any]:
        selected_ids = provider_ids or list(self.providers.keys())
        refreshed: list[str] = []
        revision = datetime.now(UTC).strftime("catalog-%Y%m%d%H%M%S")

        unknown_providers = sorted(set(selected_ids) - set(self.providers.keys()))
        if unknown_providers:
            raise ValueError(f"unknown providers: {', '.join(unknown_providers)}")

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)

            for provider_id in selected_ids:
                adapter = self.providers[provider_id]
                snapshot = adapter.fetch_catalog()
                repository.upsert_provider_snapshot(snapshot, revision)
                repository.create_revision(revision, provider_id, source="provider_refresh")
                refreshed.append(provider_id)

            self._sync_default_routing(repository, revision)
            session.commit()

        return {
            "revision": revision,
            "providers": refreshed,
            "refreshed_count": len(refreshed),
        }

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
        annotation: Any | None = None,
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
            "hosted_metadata": self._serialize_public_hosted_metadata(annotation),
        }
        if selected_profile_id is not None:
            item["recommended_rank"] = recommended_data["ranks"].get(selected_profile_id)
        return item

    def _serialize_model_annotation(self, annotation: Any | None) -> dict[str, Any]:
        if annotation is None:
            return {
                "recommended": False,
                "cost_tier": "",
                "visibility": "default",
                "badges": [],
                "operator_notes": "",
                "updated_at": "",
            }
        return {
            "recommended": bool(annotation.recommended),
            "cost_tier": str(annotation.cost_tier or ""),
            "visibility": str(annotation.visibility or "default"),
            "badges": list(annotation.badges_json or []),
            "operator_notes": str(annotation.operator_notes or ""),
            "updated_at": self._serialize_timestamp(getattr(annotation, "updated_at", None)),
        }

    def _serialize_recognition_summary(self, recognition: dict[str, Any] | None) -> dict[str, Any]:
        if recognition is None:
            return {
                "matched": False,
                "model_type": "",
                "preview_type": "",
                "confidence": 0.0,
                "evidence_sources": [],
            }
        return {
            "matched": True,
            "model_type": recognition.get("model_type", ""),
            "preview_type": recognition.get("preview_type", ""),
            "confidence": float(recognition.get("confidence", 0.0) or 0.0),
            "evidence_sources": [
                str(item.get("source", ""))
                for item in recognition.get("evidence", [])
                if str(item.get("source", "")).strip()
            ],
        }

    def _serialize_recognition_annotation(self, annotation: Any | None) -> dict[str, Any]:
        if annotation is None:
            return {
                "review_status": "pending",
                "manual_tags": [],
                "operator_notes": "",
                "updated_at": "",
            }
        return {
            "review_status": str(annotation.review_status or "pending"),
            "manual_tags": list(annotation.manual_tags_json or []),
            "operator_notes": str(annotation.operator_notes or ""),
            "updated_at": self._serialize_timestamp(getattr(annotation, "updated_at", None)),
        }

    def _serialize_admin_recognition_item(
        self,
        recognition: dict[str, Any],
        *,
        annotation: Any | None,
        in_hosted_catalog: bool,
        hosted_model: Any | None = None,
    ) -> dict[str, Any]:
        evidence = recognition.get("evidence", [])
        capabilities = recognition.get("capabilities", {}) or {}
        return {
            "provider_id": str(recognition.get("provider", "")),
            "model_id": str(recognition.get("model_id", "")),
            "model_type": str(recognition.get("model_type", "")),
            "preview_type": str(recognition.get("preview_type", "")),
            "confidence": float(recognition.get("confidence", 0.0) or 0.0),
            "source": str(recognition.get("source", "")),
            "aliases": [str(item) for item in recognition.get("aliases", [])],
            "match_keys": [str(item) for item in recognition.get("match_keys", [])],
            "input_modalities": [str(item) for item in recognition.get("input_modalities", [])],
            "output_modalities": [str(item) for item in recognition.get("output_modalities", [])],
            "capabilities": {
                str(key): bool(value) for key, value in capabilities.items()
            },
            "evidence": [
                {
                    "source": str(item.get("source", "")),
                    "confidence": float(item.get("confidence", 0.0) or 0.0),
                }
                for item in evidence
            ],
            "evidence_sources": [
                str(item.get("source", ""))
                for item in evidence
                if str(item.get("source", "")).strip()
            ],
            "updated_at": str(recognition.get("updated_at", "")),
            "deprecated": bool(recognition.get("deprecated", False)),
            "in_hosted_catalog": in_hosted_catalog,
            "hosted_catalog": {
                "provider_id": getattr(hosted_model, "provider_id", "") or "",
                "model_id": getattr(hosted_model, "model_id", "") or "",
                "feature": getattr(hosted_model, "feature", "") or "",
                "status": getattr(hosted_model, "status", "") or "",
            },
            "annotation": self._serialize_recognition_annotation(annotation),
        }

    def _serialize_admin_recognition_list_item(
        self,
        recognition: dict[str, Any],
        *,
        annotation: Any | None,
        in_hosted_catalog: bool,
        hosted_model: Any | None = None,
    ) -> dict[str, Any]:
        detail = self._serialize_admin_recognition_item(
            recognition,
            annotation=annotation,
            in_hosted_catalog=in_hosted_catalog,
            hosted_model=hosted_model,
        )
        return {
            "provider_id": detail["provider_id"],
            "model_id": detail["model_id"],
            "model_type": detail["model_type"],
            "preview_type": detail["preview_type"],
            "confidence": detail["confidence"],
            "source": detail["source"],
            "aliases": detail["aliases"],
            "evidence_sources": detail["evidence_sources"],
            "updated_at": detail["updated_at"],
            "in_hosted_catalog": detail["in_hosted_catalog"],
            "annotation": detail["annotation"],
        }

    def _serialize_public_hosted_metadata(self, annotation: Any | None) -> dict[str, Any]:
        if annotation is None:
            return {
                "recommended": False,
                "cost_tier": "",
                "visibility": "default",
                "badges": [],
                "updated_at": "",
            }
        return {
            "recommended": bool(annotation.recommended),
            "cost_tier": str(annotation.cost_tier or ""),
            "visibility": str(annotation.visibility or "default"),
            "badges": list(annotation.badges_json or []),
            "updated_at": self._serialize_timestamp(getattr(annotation, "updated_at", None)),
        }

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
            filtered = [
                model
                for model in filtered
                if search_term in model.model_id.lower()
            ]
        if fallback_candidate is not None:
            filtered = [
                model
                for model in filtered
                if model.fallback_candidate == fallback_candidate
            ]
        if deprecated_only:
            filtered = [model for model in filtered if model.is_deprecated]
        return filtered

    def _normalize_model_cost_tier(self, value: str | None) -> str | None:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return None
        if normalized not in ALLOWED_MODEL_COST_TIERS:
            raise ValueError(f"unsupported cost_tier: {normalized}")
        return normalized

    def _normalize_model_visibility(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "default"
        if normalized not in ALLOWED_MODEL_VISIBILITY:
            raise ValueError(f"unsupported visibility: {normalized}")
        return normalized

    def _normalize_badges(self, values: list[str] | None) -> list[str]:
        deduped: list[str] = []
        for raw in values or []:
            badge = str(raw or "").strip().lower()
            if not badge:
                continue
            if badge not in deduped:
                deduped.append(badge)
        return deduped[:8]

    def _normalize_recognition_review_status(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "pending"
        if normalized not in ALLOWED_RECOGNITION_REVIEW_STATUSES:
            raise ValueError(f"unsupported review_status: {normalized}")
        return normalized

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

    def _normalize_admin_recognition_sort_by(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "provider_id"
        if normalized not in ALLOWED_ADMIN_RECOGNITION_SORT_FIELDS:
            raise ValueError(f"unsupported sort_by: {normalized}")
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
            annotation = item.get("annotation", {})
            recognition = item.get("recognition", {})
            if sort_by == "model_id":
                return str(item.get("model_id", "")).lower()
            if sort_by == "confidence":
                return float(recognition.get("confidence", 0.0) or 0.0)
            if sort_by == "updated_at":
                return str(annotation.get("updated_at", "") or "")
            if sort_by == "recommended":
                return 1 if annotation.get("recommended") else 0
            if sort_by == "cost_tier":
                return str(annotation.get("cost_tier", "") or "")
            if sort_by == "visibility":
                return str(annotation.get("visibility", "") or "")
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

    def _sort_admin_recognition_models(
        self,
        items: list[dict[str, Any]],
        *,
        sort_by: str,
        sort_dir: str,
    ) -> list[dict[str, Any]]:
        reverse = sort_dir == "desc"

        def key(item: dict[str, Any]) -> Any:
            annotation = item.get("annotation", {})
            if sort_by == "model_id":
                return str(item.get("model_id", "")).lower()
            if sort_by == "confidence":
                return float(item.get("confidence", 0.0) or 0.0)
            if sort_by == "updated_at":
                return str(annotation.get("updated_at", "") or item.get("updated_at", ""))
            if sort_by == "review_status":
                return str(annotation.get("review_status", "") or "")
            if sort_by == "in_hosted_catalog":
                return 1 if item.get("in_hosted_catalog") else 0
            return str(item.get("provider_id", "")).lower()

        return sorted(
            items,
            key=lambda item: (
                key(item),
                str(item.get("provider_id", "")).lower(),
                str(item.get("model_id", "")).lower(),
            ),
            reverse=reverse,
        )

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
        ) -> list[str]:
            scored: list[tuple[int, int, str]] = []

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

            scored.sort()
            return [instance_id for _, _, instance_id in scored]

        profile_specs: dict[str, tuple[str, list[str]]] = {
            "text.economy": ("text", ["economy", "balanced"]),
            "text.balanced": ("text", ["balanced", "economy", "quality"]),
            "text.quality": ("text", ["quality", "balanced"]),
            "vision.default": ("vision", ["default", "quality"]),
            "embed.default": ("embedding", ["default", "embedding"]),
        }

        for profile_id, (execution_kind, ordered_tiers) in profile_specs.items():
            candidate_instance_ids = select_candidates(execution_kind, ordered_tiers)
            repository.upsert_routing_profile(
                profile_id=profile_id,
                execution_kind=execution_kind,
                default_policy_json={
                    "allow_fallback": True,
                    "max_retries": 0,
                    "timeout_ms": 30000,
                },
            )
            repository.upsert_routing_binding(
                profile_id=profile_id,
                candidate_instance_ids=candidate_instance_ids,
                selection_policy_json={
                    "strategy": "ordered",
                    "ordered_tiers": ordered_tiers,
                },
                revision=revision,
            )
