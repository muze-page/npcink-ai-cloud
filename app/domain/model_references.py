from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, or_, select

from app.core.db import get_session
from app.core.models import (
    ModelReferenceModel,
    ModelReferenceOverride,
    ModelReferenceSource,
)

MODELS_DEV_SOURCE_ID = "models.dev"
MODELS_DEV_API_URL = "https://models.dev/api.json"
MODEL_REFERENCE_PRICE_UNIT = "usd_per_1m_tokens"


class ModelReferenceError(ValueError):
    def __init__(self, error_code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class ModelReferenceService:
    database_url: str

    def list_references(
        self,
        *,
        provider_id: str = "",
        model_ids: list[str] | None = None,
        feature: str = "",
        include_deprecated: bool = True,
        search: str = "",
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        normalized_provider_id = _string(provider_id).lower()
        normalized_model_ids = [
            _string(model_id)
            for model_id in model_ids or []
            if _string(model_id)
        ]
        normalized_search = _string(search).lower()
        normalized_limit = min(500, max(1, int(limit)))
        normalized_offset = max(0, int(offset))

        with get_session(self.database_url) as session:
            statement = select(ModelReferenceModel).order_by(
                ModelReferenceModel.provider_id.asc(),
                ModelReferenceModel.model_id.asc(),
            )
            if normalized_provider_id:
                statement = statement.where(
                    ModelReferenceModel.provider_id == normalized_provider_id
                )
            if normalized_model_ids:
                statement = statement.where(ModelReferenceModel.model_id.in_(normalized_model_ids))
            normalized_feature = _string(feature).lower()
            if normalized_feature and normalized_feature != "all":
                statement = statement.where(ModelReferenceModel.feature == normalized_feature)
            if not include_deprecated:
                statement = statement.where(ModelReferenceModel.is_deprecated.is_(False))
            if normalized_search:
                like = f"%{normalized_search}%"
                statement = statement.where(
                    or_(
                        func.lower(ModelReferenceModel.model_id).like(like),
                        func.lower(ModelReferenceModel.display_name).like(like),
                        func.lower(ModelReferenceModel.family).like(like),
                        func.lower(ModelReferenceModel.provider_id).like(like),
                    )
                )

            total = int(session.scalar(select(func.count()).select_from(statement.subquery())) or 0)
            rows = list(
                session.scalars(statement.limit(normalized_limit).offset(normalized_offset))
            )
            overrides = {
                (row.provider_id, row.model_id): row
                for row in session.scalars(select(ModelReferenceOverride))
            }
            sources = {
                row.source_id: row
                for row in session.scalars(select(ModelReferenceSource))
            }

        items = [
            _serialize_model_reference(
                row,
                override=overrides.get((row.provider_id, row.model_id)),
                source=sources.get(row.source_id),
            )
            for row in rows
        ]
        return {
            "surface": "admin_model_references",
            "items": items,
            "total": total,
            "limit": normalized_limit,
            "offset": normalized_offset,
            "source_summary": _source_summary(sources),
            "boundary": _boundary(),
        }

    def sync_models_dev(
        self,
        *,
        payload: dict[str, Any] | None = None,
        source_url: str = MODELS_DEV_API_URL,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        source_id = MODELS_DEV_SOURCE_ID
        normalized_url = _string(source_url) or MODELS_DEV_API_URL
        try:
            catalog_payload = payload if payload is not None else _fetch_json(normalized_url)
            provider_entries = _extract_provider_entries(catalog_payload)
            if not provider_entries:
                raise ModelReferenceError(
                    "model_references.source_empty",
                    "model reference source did not include provider models",
                    status_code=502,
                )
            rows = _normalize_models_dev_provider_entries(provider_entries)
        except ModelReferenceError as error:
            self._record_source_error(
                source_id=source_id,
                source_url=normalized_url,
                error_code=error.error_code,
                message=error.message,
                now=now,
            )
            raise
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._record_source_error(
                source_id=source_id,
                source_url=normalized_url,
                error_code="model_references.sync_failed",
                message=message,
                now=now,
            )
            raise ModelReferenceError(
                "model_references.sync_failed",
                message,
                status_code=502,
            ) from error

        with get_session(self.database_url) as session:
            source = session.get(ModelReferenceSource, source_id)
            if source is None:
                source = ModelReferenceSource(
                    source_id=source_id,
                    display_name="models.dev",
                    source_url=normalized_url,
                    status="active",
                    last_synced_at=now,
                    last_error_code=None,
                    last_error_message=None,
                    metadata_json={"price_unit": MODEL_REFERENCE_PRICE_UNIT},
                )
                session.add(source)
            else:
                source.display_name = "models.dev"
                source.source_url = normalized_url
                source.status = "active"
                source.last_synced_at = now
                source.last_error_code = None
                source.last_error_message = None
                source.metadata_json = {"price_unit": MODEL_REFERENCE_PRICE_UNIT}

            session.flush()

            for row in rows:
                existing = session.scalar(
                    select(ModelReferenceModel).where(
                        ModelReferenceModel.source_id == source_id,
                        ModelReferenceModel.provider_id == row["provider_id"],
                        ModelReferenceModel.model_id == row["model_id"],
                    )
                )
                if existing is None:
                    existing = ModelReferenceModel(
                        source_id=source_id,
                        provider_id=row["provider_id"],
                        model_id=row["model_id"],
                    )
                    session.add(existing)
                existing.display_name = row["display_name"]
                existing.family = row["family"]
                existing.feature = row["feature"]
                existing.modalities_json = row["modalities"]
                existing.capability_flags_json = row["capability_flags"]
                existing.context_window = row["context_window"]
                existing.output_limit = row["output_limit"]
                existing.price_input = row["price_input"]
                existing.price_output = row["price_output"]
                existing.price_cache_read = row["price_cache_read"]
                existing.price_cache_write = row["price_cache_write"]
                existing.price_unit = MODEL_REFERENCE_PRICE_UNIT
                existing.release_date = row["release_date"]
                existing.source_updated_at = row["source_updated_at"]
                existing.is_deprecated = row["is_deprecated"]
                existing.raw_json = row["raw_json"]
                existing.synced_at = now
            session.commit()

        return {
            "surface": "admin_model_reference_sync",
            "source_id": source_id,
            "source_url": normalized_url,
            "synced_at": now.isoformat(),
            "provider_count": len(provider_entries),
            "model_count": len(rows),
            "price_unit": MODEL_REFERENCE_PRICE_UNIT,
            "billing_truth": False,
            "boundary": _boundary(),
        }

    def _record_source_error(
        self,
        *,
        source_id: str,
        source_url: str,
        error_code: str,
        message: str,
        now: datetime,
    ) -> None:
        with get_session(self.database_url) as session:
            source = session.get(ModelReferenceSource, source_id)
            if source is None:
                source = ModelReferenceSource(
                    source_id=source_id,
                    display_name="models.dev",
                    source_url=source_url,
                    status="error",
                    last_synced_at=None,
                    last_error_code=error_code,
                    last_error_message=message[:500],
                    metadata_json={"price_unit": MODEL_REFERENCE_PRICE_UNIT},
                )
                session.add(source)
            else:
                source.status = "error"
                source.source_url = source_url
                source.last_error_code = error_code
                source.last_error_message = message[:500]
                source.metadata_json = {"price_unit": MODEL_REFERENCE_PRICE_UNIT}
            source.updated_at = now
            session.commit()


def _fetch_json(source_url: str) -> dict[str, Any]:
    with httpx.Client(timeout=20.0, headers={"User-Agent": "Npcink-AI-Cloud/1.0"}) as client:
        response = client.get(source_url)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise ModelReferenceError(
            "model_references.source_invalid",
            "model reference source returned a non-object payload",
            status_code=502,
        )
    return payload


def _extract_provider_entries(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    providers = payload.get("providers")
    if isinstance(providers, dict):
        return {
            _string(provider_id).lower(): value
            for provider_id, value in providers.items()
            if isinstance(value, dict) and isinstance(value.get("models"), dict)
        }
    return {
        _string(provider_id).lower(): value
        for provider_id, value in payload.items()
        if isinstance(value, dict) and isinstance(value.get("models"), dict)
    }


def _normalize_models_dev_provider_entries(
    provider_entries: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for provider_key, provider in provider_entries.items():
        provider_id = _string(provider.get("id") or provider_key).lower()
        models = provider.get("models")
        if not isinstance(models, dict):
            continue
        for model_key, model in models.items():
            if not isinstance(model, dict):
                continue
            model_id = _string(model.get("id") or model_key)
            if not provider_id or not model_id:
                continue
            limit = _dict(model.get("limit"))
            cost = _dict(model.get("cost"))
            modalities = _dict(model.get("modalities"))
            rows.append(
                {
                    "provider_id": provider_id[:64],
                    "model_id": model_id[:191],
                    "display_name": _string(model.get("name") or model_id)[:191],
                    "family": _string(model.get("family") or model_id.split("-", 1)[0])[:96],
                    "feature": _feature_from_modalities(modalities),
                    "modalities": modalities,
                    "capability_flags": {
                        "attachment": bool(model.get("attachment")),
                        "reasoning": bool(model.get("reasoning")),
                        "tool_call": bool(model.get("tool_call")),
                        "structured_output": bool(model.get("structured_output")),
                        "temperature": bool(model.get("temperature")),
                        "open_weights": bool(model.get("open_weights")),
                    },
                    "context_window": _optional_int(limit.get("context")),
                    "output_limit": _optional_int(limit.get("output")),
                    "price_input": _optional_float(cost.get("input")),
                    "price_output": _optional_float(cost.get("output")),
                    "price_cache_read": _optional_float(cost.get("cache_read")),
                    "price_cache_write": _optional_float(cost.get("cache_write")),
                    "release_date": _string(model.get("release_date"))[:32],
                    "source_updated_at": _string(model.get("last_updated"))[:32],
                    "is_deprecated": bool(model.get("deprecated") or model.get("is_deprecated")),
                    "raw_json": {
                        "provider": {
                            "id": provider_id,
                            "name": _string(provider.get("name")),
                            "doc": _string(provider.get("doc")),
                        },
                        "model": model,
                    },
                }
            )
    return rows


def _serialize_model_reference(
    row: ModelReferenceModel,
    *,
    override: ModelReferenceOverride | None,
    source: ModelReferenceSource | None,
) -> dict[str, Any]:
    raw = _dict(row.raw_json)
    provider = _dict(raw.get("provider"))
    override_present = override is not None
    price_input = row.price_input
    price_output = row.price_output
    price_cache_read = row.price_cache_read
    price_cache_write = row.price_cache_write
    feature = row.feature
    status = "reference"
    if override is not None:
        feature = override.feature_override or feature
        status = override.status_override or status
        price_input = _override_float(override.price_input_override, price_input)
        price_output = _override_float(override.price_output_override, price_output)
        price_cache_read = _override_float(
            override.price_cache_read_override,
            price_cache_read,
        )
        price_cache_write = _override_float(
            override.price_cache_write_override,
            price_cache_write,
        )
    return {
        "source_id": row.source_id,
        "source_label": source.display_name if source else row.source_id,
        "provider_id": row.provider_id,
        "provider_label": _string(provider.get("name") or row.provider_id),
        "model_id": row.model_id,
        "display_name": row.display_name,
        "family": row.family,
        "feature": feature,
        "status": status,
        "modalities": row.modalities_json or {},
        "capability_flags": row.capability_flags_json or {},
        "context_window": row.context_window,
        "output_limit": row.output_limit,
        "price": {
            "input": price_input,
            "output": price_output,
            "cache_read": price_cache_read,
            "cache_write": price_cache_write,
            "unit": row.price_unit or MODEL_REFERENCE_PRICE_UNIT,
            "billing_truth": False,
        },
        "release_date": row.release_date,
        "source_updated_at": row.source_updated_at,
        "synced_at": row.synced_at.isoformat() if row.synced_at else "",
        "is_deprecated": bool(row.is_deprecated),
        "override_present": override_present,
        "boundary": {
            "reference_only": True,
            "billing_truth": False,
            "routing_truth": False,
        },
    }


def _source_summary(sources: dict[str, ModelReferenceSource]) -> list[dict[str, Any]]:
    return [
        {
            "source_id": source.source_id,
            "display_name": source.display_name,
            "source_url": source.source_url,
            "status": source.status,
            "last_synced_at": source.last_synced_at.isoformat()
            if source.last_synced_at
            else "",
            "last_error_code": source.last_error_code or "",
            "last_error_message": source.last_error_message or "",
        }
        for source in sorted(sources.values(), key=lambda item: item.source_id)
    ]


def _boundary() -> dict[str, Any]:
    return {
        "owner": "cloud_hosted_metadata",
        "reference_only": True,
        "billing_truth": False,
        "routing_truth": False,
        "direct_wordpress_write": False,
        "not_a_control_plane": True,
        "does_not_own": [
            "wordpress_writes",
            "approval_truth",
            "ability_registry",
            "workflow_registry",
            "prompt_router_preset_truth",
            "usage_meter_truth",
        ],
    }


def _feature_from_modalities(modalities: dict[str, Any]) -> str:
    outputs = {str(item).lower() for item in _list(modalities.get("output"))}
    inputs = {str(item).lower() for item in _list(modalities.get("input"))}
    if "audio" in outputs:
        return "audio"
    if "image" in outputs:
        return "image"
    if "video" in outputs:
        return "video"
    if "embedding" in outputs or "embedding" in inputs:
        return "embedding"
    return "text"


def _override_float(value: float | None, fallback: float | None) -> float | None:
    return fallback if value is None else value


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _string(value: object) -> str:
    return str(value or "").strip()
