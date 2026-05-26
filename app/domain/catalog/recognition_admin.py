from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable

from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.db import get_session

ALLOWED_RECOGNITION_REVIEW_STATUSES = {
    "pending",
    "reviewed",
    "candidate",
    "suppressed",
}
ALLOWED_RECOGNITION_VISIBILITY = {"default", "advanced", "hidden"}
ALLOWED_RECOGNITION_COST_TIERS = {"", "budget", "balanced", "premium"}
ALLOWED_ADMIN_RECOGNITION_SORT_FIELDS = {
    "provider_id",
    "model_id",
    "confidence",
    "updated_at",
    "review_status",
    "in_hosted_catalog",
}
ALLOWED_ADMIN_RECOGNITION_SORT_DIRECTIONS = {"asc", "desc"}
ALLOWED_RECOGNITION_QUICK_FILTERS = {
    "candidate_not_in_hosted",
    "conflicts",
    "capability_conflicts",
    "low_confidence",
    "new_models",
    "not_in_hosted_catalog",
    "price_conflicts",
}
LOW_CONFIDENCE_THRESHOLD = 0.9
MANUAL_TAG_SUGGESTIONS = [
    "candidate",
    "vision",
    "image",
    "embedding",
    "oss",
    "needs_followup",
]


class RecognitionAdminService:
    def __init__(
        self,
        *,
        database_url: str,
        bundle_loader: Callable[[], dict[str, Any]],
        recognition_price_cny_per_usd: float = 7.2,
    ) -> None:
        self.database_url = database_url
        self.bundle_loader = bundle_loader
        self.recognition_price_cny_per_usd = max(float(recognition_price_cny_per_usd), 0.0001)

    def list_models(
        self,
        *,
        provider_id: str | None = None,
        search: str | None = None,
        review_status: str | None = None,
        in_hosted_catalog: bool | None = None,
        source: str | None = None,
        quick_filter: str | None = None,
        page: int = 1,
        per_page: int = 50,
        sort_by: str = "provider_id",
        sort_dir: str = "asc",
    ) -> dict[str, Any]:
        bundle = self.bundle_loader()
        bundle_models = list(bundle["models"])

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            hosted_models = repository.list_all_models()
            recent_source_runs = repository.list_recent_recognition_source_runs(limit=12)
            recent_publications = repository.list_recent_recognition_snapshot_publications(limit=2)
            annotations = {
                (item.provider_id, item.model_id): item
                for item in repository.list_recognition_annotations(
                    [
                        (str(model.get("provider", "")), str(model.get("model_id", "")))
                        for model in bundle_models
                    ]
                )
            }
            hosted_annotations = {
                item.model_id: item
                for item in repository.list_model_annotations(
                    [item.model_id for item in hosted_models]
                )
            }

        hosted_keys = {(item.provider_id, item.model_id) for item in hosted_models}
        hosted_index = {(item.provider_id, item.model_id): item for item in hosted_models}
        conflict_index = self._build_match_conflicts(bundle_models)
        delta_meta = self._build_snapshot_delta_meta(
            bundle_models=bundle_models,
            recent_publications=recent_publications,
        )
        source_trends = self._build_source_trends(
            current_source_counts={
                source_name: sum(
                    1
                    for item in bundle_models
                    if str(item.get("evidence_source", "")).strip() == source_name
                )
                for source_name in sorted(
                    {
                        str(item.get("evidence_source", "")).strip()
                        for item in bundle_models
                        if str(item.get("evidence_source", "")).strip()
                    }
                )
            },
            recent_publications=recent_publications,
        )

        items: list[dict[str, Any]] = []
        for recognition in bundle_models:
            provider_key = str(recognition.get("provider", ""))
            model_key = str(recognition.get("model_id", ""))
            hosted_model = hosted_index.get((provider_key, model_key))
            item = self._serialize_list_item(
                recognition,
                annotation=annotations.get((provider_key, model_key)),
                in_hosted_catalog=(provider_key, model_key) in hosted_keys,
                hosted_model=hosted_model,
                hosted_annotation=hosted_annotations.get(model_key),
                conflict_keys=conflict_index.get((provider_key, model_key), []),
                is_new_since_previous_snapshot=(provider_key, model_key) in delta_meta["new_keys"],
            )
            if provider_id and item["provider_id"] != provider_id:
                continue
            if search:
                search_term = search.lower()
                haystacks = [
                    item["provider_id"].lower(),
                    item["model_id"].lower(),
                    item["source"].lower(),
                    item["why_not_in_hosted_catalog"].lower(),
                    *[alias.lower() for alias in item["aliases"]],
                    *[source_item.lower() for source_item in item["evidence_sources"]],
                    *[tag.lower() for tag in item["annotation"]["manual_tags"]],
                ]
                if not any(search_term in value for value in haystacks):
                    continue
            if review_status and item["annotation"]["review_status"] != review_status:
                continue
            if in_hosted_catalog is not None and item["in_hosted_catalog"] is not in_hosted_catalog:
                continue
            if source and item["source"] != source:
                continue
            if quick_filter and not self._matches_quick_filter(item, quick_filter):
                continue
            items.append(item)

        normalized_sort_by = self._normalize_sort_by(sort_by)
        normalized_sort_dir = self._normalize_sort_dir(sort_dir)
        normalized_quick_filter = self._normalize_quick_filter(quick_filter)
        items = self._sort_items(
            items,
            sort_by=normalized_sort_by,
            sort_dir=normalized_sort_dir,
        )

        total = len(items)
        normalized_page = max(1, int(page))
        normalized_per_page = max(1, int(per_page))
        offset = (normalized_page - 1) * normalized_per_page
        paged_items = items[offset : offset + normalized_per_page]

        review_status_counts = {
            status_name: sum(
                1 for item in items if item["annotation"]["review_status"] == status_name
            )
            for status_name in sorted(ALLOWED_RECOGNITION_REVIEW_STATUSES)
        }
        source_counts = {
            source_name: sum(1 for item in items if item["source"] == source_name)
            for source_name in sorted({item["source"] for item in items if item["source"]})
        }
        admin_source = dict(bundle.get("admin_source", {})) if isinstance(bundle.get("admin_source"), dict) else {}
        source_run_summaries = self._build_source_run_summaries(
            source_counts=source_counts,
            admin_source=admin_source,
            persisted_runs=recent_source_runs,
        )

        return {
            "filters": {
                "provider_id": provider_id or "",
                "search": search or "",
                "review_status": review_status or "",
                "in_hosted_catalog": in_hosted_catalog,
                "source": source or "",
                "quick_filter": normalized_quick_filter or "",
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
                "hosted_catalog_total": sum(1 for item in items if item["in_hosted_catalog"]),
                "not_in_hosted_catalog_total": sum(
                    1 for item in items if not item["in_hosted_catalog"]
                ),
                "platform_models_total": sum(1 for item in items if item["in_hosted_catalog"]),
                "not_in_platform_models_total": sum(
                    1 for item in items if not item["in_hosted_catalog"]
                ),
                "candidate_not_in_hosted_total": sum(
                    1
                    for item in items
                    if item["annotation"]["review_status"] == "candidate"
                    and not item["in_hosted_catalog"]
                ),
                "candidate_not_in_platform_models_total": sum(
                    1
                    for item in items
                    if item["annotation"]["review_status"] == "candidate"
                    and not item["in_hosted_catalog"]
                ),
                "low_confidence_total": sum(
                    1 for item in items if self._is_low_confidence(item)
                ),
                "conflict_total": sum(
                    1 for item in items if item["has_match_conflict"]
                ),
                "price_conflict_total": sum(
                    1 for item in items if item.get("has_price_conflict")
                ),
                "capability_conflict_total": sum(
                    1 for item in items if item.get("has_capability_conflict")
                ),
                "new_models_total": sum(
                    1 for item in items if item.get("is_new_since_previous_snapshot")
                ),
                "disappeared_models_total": int(delta_meta["disappeared_total"]),
                "disappeared_models": list(delta_meta["disappeared_models"]),
                "review_status_counts": review_status_counts,
                "sources": list(source_counts.keys()),
                "source_counts": source_counts,
                "source_trends": source_trends,
                "source_runs": source_run_summaries,
                "source_failures": list(admin_source.get("source_failures") or []),
                "manual_tag_suggestions": list(MANUAL_TAG_SUGGESTIONS),
            },
            "pricing": self._serialize_pricing_config(),
            "recognition_bundle": {
                "revision": bundle["revision"],
                "checksum": bundle["checksum"],
                "published_at": bundle["published_at"],
                "admin_source": admin_source or None,
                "snapshot_delta": {
                    "new_models_total": int(delta_meta["new_total"]),
                    "disappeared_models_total": int(delta_meta["disappeared_total"]),
                    "previous_revision": str(delta_meta["previous_revision"] or ""),
                },
            },
        }

    def get_model(
        self,
        *,
        provider_id: str,
        model_id: str,
    ) -> dict[str, Any] | None:
        bundle = self.bundle_loader()
        recognition = next(
            (
                item
                for item in bundle["models"]
                if item.get("provider") == provider_id and item.get("model_id") == model_id
            ),
            None,
        )
        if recognition is None:
            return None

        conflict_index = self._build_match_conflicts(list(bundle["models"]))

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            annotation = repository.get_recognition_annotation(
                provider_id=provider_id,
                model_id=model_id,
            )
            hosted_model = next(
                (
                    item
                    for item in repository.list_all_models()
                    if item.provider_id == provider_id and item.model_id == model_id
                ),
                None,
            )
            hosted_annotation = (
                repository.get_model_annotation(model_id) if hosted_model is not None else None
            )

        detail = self._serialize_detail_item(
            recognition,
            annotation=annotation,
            in_hosted_catalog=hosted_model is not None,
            hosted_model=hosted_model,
            hosted_annotation=hosted_annotation,
            conflict_keys=conflict_index.get((provider_id, model_id), []),
        )

        return {
            **detail,
            "pricing": self._serialize_pricing_config(),
            "recognition_bundle": {
                "revision": bundle["revision"],
                "checksum": bundle["checksum"],
                "published_at": bundle["published_at"],
                "admin_source": dict(bundle.get("admin_source", {}))
                if isinstance(bundle.get("admin_source"), dict)
                else None,
            },
        }

    def upsert_annotation(
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
        bundle = self.bundle_loader()
        if not any(
            item.get("provider") == provider_id and item.get("model_id") == model_id
            for item in bundle["models"]
        ):
            return None

        normalized_review_status = self._normalize_review_status(review_status)
        normalized_tags = self._normalize_tags(manual_tags)
        normalized_notes = str(operator_notes or "").strip() or None
        normalized_cost_tier_override = self._normalize_cost_tier_override(cost_tier_override)
        normalized_visibility = self._normalize_visibility(visibility)
        normalized_badges = self._normalize_badges(badges)

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            existing = repository.get_recognition_annotation(
                provider_id=provider_id,
                model_id=model_id,
            )
            metadata = (
                dict(existing.metadata_json or {})
                if existing is not None and isinstance(existing.metadata_json, dict)
                else {}
            )
            metadata.update(
                {
                    "source": "admin_recognition_review_console_v1",
                    "recommended": bool(recommended),
                    "cost_tier_override": normalized_cost_tier_override,
                    "visibility": normalized_visibility,
                    "badges": normalized_badges,
                }
            )
            annotation = repository.upsert_recognition_annotation(
                provider_id=provider_id,
                model_id=model_id,
                review_status=normalized_review_status,
                manual_tags_json=normalized_tags,
                operator_notes=normalized_notes,
                metadata_json=metadata,
            )
            session.commit()

        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "annotation": self._serialize_annotation(annotation),
        }

    def _serialize_detail_item(
        self,
        recognition: dict[str, Any],
        *,
        annotation: Any | None,
        in_hosted_catalog: bool,
        hosted_model: Any | None = None,
        hosted_annotation: Any | None = None,
        conflict_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        evidence = [
            {
                "source": str(item.get("source", "")),
                "confidence": float(item.get("confidence", 0.0) or 0.0),
            }
            for item in recognition.get("evidence", [])
        ]
        sorted_evidence = sorted(
            evidence,
            key=lambda item: (
                float(item.get("confidence", 0.0) or 0.0),
                str(item.get("source", "")).lower(),
            ),
            reverse=True,
        )
        primary_evidence = sorted_evidence[0] if sorted_evidence else None
        secondary_evidence = sorted_evidence[1:] if len(sorted_evidence) > 1 else []
        conflict_list = list(conflict_keys or [])

        item = {
            "provider_id": str(recognition.get("provider", "")),
            "model_id": str(recognition.get("model_id", "")),
            "model_type": str(recognition.get("model_type", "")),
            "preview_type": str(recognition.get("preview_type", "")),
            "confidence": float(recognition.get("confidence", 0.0) or 0.0),
            "price_input": self._normalize_price(recognition.get("price_input")),
            "price_output": self._normalize_price(recognition.get("price_output")),
            "price_source": str(recognition.get("price_source", "")),
            "price_updated_at": str(recognition.get("price_updated_at", "")),
            "price_confidence": float(recognition.get("price_confidence", 0.0) or 0.0),
            "has_price_conflict": bool(recognition.get("has_price_conflict", False)),
            "price_sources": self._serialize_price_sources(recognition.get("price_sources")),
            "source": str(recognition.get("source", "")),
            "source_coverage_count": int(recognition.get("source_coverage_count", 0) or 0),
            "source_coverage_sources": [
                str(entry)
                for entry in recognition.get("source_coverage_sources", [])
                if str(entry).strip()
            ],
            "aliases": [str(entry) for entry in recognition.get("aliases", [])],
            "short_description": str(recognition.get("short_description", "")),
            "best_for": str(recognition.get("best_for", "")),
            "supports": [str(entry) for entry in recognition.get("supports", [])],
            "price_summary": str(recognition.get("price_summary", "")),
            "why_recommended": str(recognition.get("why_recommended", "")),
            "match_keys": [str(entry) for entry in recognition.get("match_keys", [])],
            "input_modalities": [
                str(entry) for entry in recognition.get("input_modalities", [])
            ],
            "output_modalities": [
                str(entry) for entry in recognition.get("output_modalities", [])
            ],
            "capabilities": {
                str(key): bool(value)
                for key, value in (recognition.get("capabilities", {}) or {}).items()
            },
            "evidence": sorted_evidence,
            "primary_evidence": primary_evidence,
            "secondary_evidence": secondary_evidence,
            "evidence_source_count": len(sorted_evidence),
            "evidence_sources": [
                str(entry.get("source", ""))
                for entry in sorted_evidence
                if str(entry.get("source", "")).strip()
            ],
            "updated_at": str(recognition.get("updated_at", "")),
            "deprecated": bool(recognition.get("deprecated", False)),
            "has_capability_conflict": bool(
                recognition.get("has_capability_conflict", False)
            ),
            "capability_sources": self._serialize_capability_sources(
                recognition.get("capability_sources")
            ),
            "in_hosted_catalog": in_hosted_catalog,
            "in_platform_models": in_hosted_catalog,
            "hosted_catalog": {
                "provider_id": getattr(hosted_model, "provider_id", "") or "",
                "model_id": getattr(hosted_model, "model_id", "") or "",
                "feature": getattr(hosted_model, "feature", "") or "",
                "status": getattr(hosted_model, "status", "") or "",
            },
            "platform_models": {
                "provider_id": getattr(hosted_model, "provider_id", "") or "",
                "model_id": getattr(hosted_model, "model_id", "") or "",
                "feature": getattr(hosted_model, "feature", "") or "",
                "status": getattr(hosted_model, "status", "") or "",
            },
            "hosted_metadata": self._serialize_public_hosted_metadata(hosted_annotation),
            "platform_model_metadata": self._serialize_public_hosted_metadata(
                hosted_annotation
            ),
            "annotation": self._serialize_annotation(annotation),
            "has_match_conflict": bool(conflict_list),
            "match_conflict_keys": conflict_list,
        }
        item["why_not_in_hosted_catalog"] = self._why_not_in_hosted_catalog(item)
        item["why_not_in_platform_models"] = self._map_why_not_in_platform_models(
            item["why_not_in_hosted_catalog"]
        )
        return item

    def _serialize_list_item(
        self,
        recognition: dict[str, Any],
        *,
        annotation: Any | None,
        in_hosted_catalog: bool,
        hosted_model: Any | None = None,
        hosted_annotation: Any | None = None,
        conflict_keys: list[str] | None = None,
        is_new_since_previous_snapshot: bool = False,
    ) -> dict[str, Any]:
        detail = self._serialize_detail_item(
            recognition,
            annotation=annotation,
            in_hosted_catalog=in_hosted_catalog,
            hosted_model=hosted_model,
            hosted_annotation=hosted_annotation,
            conflict_keys=conflict_keys,
        )
        return {
            "provider_id": detail["provider_id"],
            "model_id": detail["model_id"],
            "model_type": detail["model_type"],
            "preview_type": detail["preview_type"],
            "confidence": detail["confidence"],
            "price_input": detail["price_input"],
            "price_output": detail["price_output"],
            "price_source": detail["price_source"],
            "price_updated_at": detail["price_updated_at"],
            "price_confidence": detail["price_confidence"],
            "has_price_conflict": detail["has_price_conflict"],
            "source": detail["source"],
            "source_coverage_count": detail["source_coverage_count"],
            "source_coverage_sources": detail["source_coverage_sources"],
            "aliases": detail["aliases"],
            "short_description": detail["short_description"],
            "best_for": detail["best_for"],
            "supports": detail["supports"],
            "price_summary": detail["price_summary"],
            "evidence_sources": detail["evidence_sources"],
            "primary_evidence": detail["primary_evidence"],
            "evidence_source_count": detail["evidence_source_count"],
            "updated_at": detail["updated_at"],
            "in_hosted_catalog": detail["in_hosted_catalog"],
            "in_platform_models": detail["in_platform_models"],
            "annotation": detail["annotation"],
            "has_match_conflict": detail["has_match_conflict"],
            "has_capability_conflict": detail["has_capability_conflict"],
            "is_new_since_previous_snapshot": bool(is_new_since_previous_snapshot),
            "match_conflict_keys": detail["match_conflict_keys"],
            "why_not_in_hosted_catalog": detail["why_not_in_hosted_catalog"],
            "why_not_in_platform_models": detail["why_not_in_platform_models"],
        }

    def _serialize_annotation(self, annotation: Any | None) -> dict[str, Any]:
        if annotation is None:
            return {
                "review_status": "pending",
                "manual_tags": [],
                "operator_notes": "",
                "recommended": False,
                "cost_tier_override": "",
                "visibility": "default",
                "badges": [],
                "updated_at": "",
            }
        metadata = dict(annotation.metadata_json or {}) if isinstance(annotation.metadata_json, dict) else {}
        return {
            "review_status": str(annotation.review_status or "pending"),
            "manual_tags": list(annotation.manual_tags_json or []),
            "operator_notes": str(annotation.operator_notes or ""),
            "recommended": bool(metadata.get("recommended", False)),
            "cost_tier_override": str(metadata.get("cost_tier_override", "") or ""),
            "visibility": str(metadata.get("visibility", "default") or "default"),
            "badges": [
                str(item).strip()
                for item in metadata.get("badges", [])
                if str(item).strip()
            ]
            if isinstance(metadata.get("badges"), list)
            else [],
            "updated_at": self._serialize_timestamp(getattr(annotation, "updated_at", None)),
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

    def _serialize_pricing_config(self) -> dict[str, Any]:
        return {
            "base_currency": "USD",
            "supported_currencies": ["USD", "CNY"],
            "cny_per_usd": round(self.recognition_price_cny_per_usd, 6),
            "unit": "per_1m_tokens",
        }

    def _normalize_price(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        if normalized < 0:
            return None
        return round(normalized, 6)

    def _serialize_price_sources(self, sources: Any) -> list[dict[str, Any]]:
        if not isinstance(sources, list):
            return []
        serialized: list[dict[str, Any]] = []
        for item in sources:
            if not isinstance(item, dict):
                continue
            serialized.append(
                {
                    "source": str(item.get("source", "")),
                    "price_source": str(item.get("price_source", "")),
                    "price_input": self._normalize_price(item.get("price_input")),
                    "price_output": self._normalize_price(item.get("price_output")),
                    "price_updated_at": str(item.get("price_updated_at", "")),
                    "price_confidence": float(item.get("price_confidence", 0.0) or 0.0),
                }
            )
        return serialized

    def _serialize_capability_sources(self, sources: Any) -> list[dict[str, Any]]:
        if not isinstance(sources, list):
            return []
        serialized: list[dict[str, Any]] = []
        for item in sources:
            if not isinstance(item, dict):
                continue
            serialized.append(
                {
                    "source": str(item.get("source", "")),
                    "model_type": str(item.get("model_type", "")),
                    "preview_type": str(item.get("preview_type", "")),
                    "capabilities": {
                        str(key): bool(value)
                        for key, value in dict(item.get("capabilities", {})).items()
                        if str(key).strip()
                    }
                    if isinstance(item.get("capabilities"), dict)
                    else {},
                    "confidence": float(item.get("confidence", 0.0) or 0.0),
                }
            )
        return serialized

    def _build_match_conflicts(
        self,
        bundle_models: list[dict[str, Any]],
    ) -> dict[tuple[str, str], list[str]]:
        match_index: dict[str, set[tuple[str, str]]] = {}
        for model in bundle_models:
            provider_id = str(model.get("provider", ""))
            model_id = str(model.get("model_id", ""))
            for key in model.get("match_keys", []) or []:
                normalized = str(key or "").strip().lower()
                if not normalized:
                    continue
                match_index.setdefault(normalized, set()).add((provider_id, model_id))

        conflicts: dict[tuple[str, str], list[str]] = {}
        for match_key, targets in match_index.items():
            if len(targets) < 2:
                continue
            for target in targets:
                conflicts.setdefault(target, []).append(match_key)

        return {
            key: sorted(values)
            for key, values in conflicts.items()
        }

    def _why_not_in_hosted_catalog(self, item: dict[str, Any]) -> str:
        if item.get("in_hosted_catalog"):
            return ""
        annotation = item.get("annotation", {})
        review_status = str(annotation.get("review_status", "") or "pending")
        if item.get("has_match_conflict"):
            return "match_conflict"
        if review_status == "suppressed":
            return "suppressed"
        if review_status == "pending":
            return "not_reviewed"
        if self._is_low_confidence(item):
            return "low_confidence"
        if review_status != "candidate":
            return "not_marked_candidate"
        return "not_curated_into_hosted_catalog"

    def _matches_quick_filter(self, item: dict[str, Any], quick_filter: str) -> bool:
        normalized = self._normalize_quick_filter(quick_filter)
        if not normalized:
            return True
        if normalized == "candidate_not_in_hosted":
            return (
                item["annotation"]["review_status"] == "candidate"
                and not item["in_hosted_catalog"]
            )
        if normalized == "conflicts":
            return bool(item.get("has_match_conflict"))
        if normalized == "capability_conflicts":
            return bool(item.get("has_capability_conflict"))
        if normalized == "low_confidence":
            return self._is_low_confidence(item)
        if normalized == "not_in_hosted_catalog":
            return not item["in_hosted_catalog"]
        if normalized == "new_models":
            return bool(item.get("is_new_since_previous_snapshot"))
        if normalized == "price_conflicts":
            return bool(item.get("has_price_conflict"))
        return True

    def _build_snapshot_delta_meta(
        self,
        *,
        bundle_models: list[dict[str, Any]],
        recent_publications: list[Any],
    ) -> dict[str, Any]:
        current_keys = {
            (str(item.get("provider", "")), str(item.get("model_id", "")))
            for item in bundle_models
        }
        previous_keys: set[tuple[str, str]] = set()
        previous_revision = ""
        if len(recent_publications) >= 2:
            previous = recent_publications[1]
            previous_revision = str(getattr(previous, "revision", "") or "")
            for raw_key in list(getattr(previous, "record_keys_json", []) or []):
                normalized = str(raw_key).strip()
                if "::" not in normalized:
                    continue
                provider_id, model_id = normalized.split("::", 1)
                previous_keys.add((provider_id, model_id))
        new_keys = current_keys - previous_keys if previous_keys else set()
        disappeared_total = len(previous_keys - current_keys) if previous_keys else 0
        disappeared_models = [
            {
                "provider_id": provider_id,
                "model_id": model_id,
            }
            for provider_id, model_id in sorted(previous_keys - current_keys)
        ]
        return {
            "new_keys": new_keys,
            "new_total": len(new_keys),
            "disappeared_total": disappeared_total,
            "disappeared_models": disappeared_models[:20],
            "previous_revision": previous_revision,
        }

    def _build_source_trends(
        self,
        *,
        current_source_counts: dict[str, int],
        recent_publications: list[Any],
    ) -> list[dict[str, Any]]:
        previous_counts: dict[str, int] = {}
        previous_revision = ""
        if len(recent_publications) >= 2:
            previous = recent_publications[1]
            previous_revision = str(getattr(previous, "revision", "") or "")
            metadata = dict(getattr(previous, "metadata_json", None) or {})
            raw_counts = metadata.get("source_counts")
            if isinstance(raw_counts, dict):
                previous_counts = {
                    str(key): int(value)
                    for key, value in raw_counts.items()
                    if str(key).strip()
                }
        source_names = sorted(set(current_source_counts.keys()) | set(previous_counts.keys()))
        return [
            {
                "source": source_name,
                "current_total": int(current_source_counts.get(source_name, 0)),
                "previous_total": int(previous_counts.get(source_name, 0)),
                "delta": int(current_source_counts.get(source_name, 0) - previous_counts.get(source_name, 0)),
                "previous_revision": previous_revision,
            }
            for source_name in source_names
        ]

    def _is_low_confidence(self, item: dict[str, Any]) -> bool:
        return float(item.get("confidence", 0.0) or 0.0) < LOW_CONFIDENCE_THRESHOLD

    def _map_why_not_in_platform_models(self, reason: str) -> str:
        if reason == "not_curated_into_hosted_catalog":
            return "not_curated_into_platform_models"
        return reason

    def _normalize_quick_filter(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return ""
        if normalized not in ALLOWED_RECOGNITION_QUICK_FILTERS:
            raise ValueError(f"unsupported quick_filter: {normalized}")
        return normalized

    def _normalize_review_status(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "pending"
        if normalized not in ALLOWED_RECOGNITION_REVIEW_STATUSES:
            raise ValueError(f"unsupported review_status: {normalized}")
        return normalized

    def _normalize_tags(self, values: list[str] | None) -> list[str]:
        deduped: list[str] = []
        for raw in values or []:
            tag = str(raw or "").strip().lower()
            if not tag:
                continue
            if tag not in deduped:
                deduped.append(tag)
        return deduped[:8]

    def _normalize_badges(self, values: list[str] | None) -> list[str]:
        deduped: list[str] = []
        for raw in values or []:
            badge = str(raw or "").strip()
            if not badge:
                continue
            if badge not in deduped:
                deduped.append(badge)
        return deduped[:8]

    def _normalize_cost_tier_override(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in ALLOWED_RECOGNITION_COST_TIERS:
            raise ValueError(f"unsupported cost_tier_override: {normalized}")
        return normalized

    def _normalize_visibility(self, value: str | None) -> str:
        normalized = str(value or "default").strip().lower() or "default"
        if normalized not in ALLOWED_RECOGNITION_VISIBILITY:
            raise ValueError(f"unsupported visibility: {normalized}")
        return normalized

    def _normalize_sort_by(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "provider_id"
        if normalized not in ALLOWED_ADMIN_RECOGNITION_SORT_FIELDS:
            raise ValueError(f"unsupported sort_by: {normalized}")
        return normalized

    def _normalize_sort_dir(self, value: str | None) -> str:
        normalized = str(value or "").strip().lower() or "asc"
        if normalized not in ALLOWED_ADMIN_RECOGNITION_SORT_DIRECTIONS:
            raise ValueError(f"unsupported sort_dir: {normalized}")
        return normalized

    def _build_source_run_summaries(
        self,
        *,
        source_counts: dict[str, int],
        admin_source: dict[str, Any],
        persisted_runs: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        if persisted_runs:
            return [
                {
                    "source": str(item.source_name),
                    "run_id": str(item.run_id),
                    "status": str(item.status),
                    "generated_at": self._serialize_datetime(item.snapshot_generated_at),
                    "started_at": self._serialize_datetime(item.started_at),
                    "finished_at": self._serialize_datetime(item.finished_at),
                    "duration_ms": int(item.duration_ms or 0),
                    "records_fetched": int(item.records_fetched or 0),
                    "records_accepted": int(item.records_accepted or 0),
                    "error": str(item.error_message or ""),
                }
                for item in persisted_runs
            ]
        persisted_runs = admin_source.get("source_runs")
        if isinstance(persisted_runs, list) and persisted_runs:
            return [dict(item) for item in persisted_runs if isinstance(item, dict)]
        generated_at = str(admin_source.get("generated_at") or "")
        source_keys = [
            str(source_key).strip()
            for source_key in admin_source.get("source_keys", []) or []
            if str(source_key).strip()
        ]
        source_key_to_count = {
            "openrouter_snapshot": source_counts.get("openrouter_model_info", 0),
            "hf_snapshot": source_counts.get("huggingface_model_info", 0),
            "litellm_revision": source_counts.get("litellm_model_info", 0),
            "ollama_snapshot": source_counts.get("ollama_catalog_show", 0)
            + source_counts.get("ollama_show", 0),
        }
        return [
            {
                "source_key": source_key,
                "records_total": int(source_key_to_count.get(source_key, 0)),
                "status": "configured",
                "generated_at": generated_at,
            }
            for source_key in source_keys
        ]

    def _serialize_datetime(self, value: datetime | None) -> str:
        if value is None:
            return ""
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")

    def _sort_items(
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

    def _serialize_timestamp(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
