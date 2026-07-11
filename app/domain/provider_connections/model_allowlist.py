from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.adapters.providers.registry import (
    EXECUTION_PROVIDER_SOURCE_ROLES,
    OPENAI_COMPATIBLE_CONNECTION_KINDS,
)
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderConnection


@dataclass(frozen=True, slots=True)
class ProviderModelAllowlist:
    allowed_model_ids_by_provider: dict[str, set[str]]
    fallback_execution_provider_ids: set[str]
    enforced: bool

    def allows(self, *, provider_id: str, model_id: str) -> bool:
        provider_models = self.allowed_model_ids_by_provider.get(provider_id)
        if provider_models is not None:
            return model_id in provider_models
        return provider_id in self.fallback_execution_provider_ids


def build_provider_model_allowlist(
    database_url: str,
    *,
    settings: Settings | None = None,
    execution_provider_ids: set[str] | None = None,
) -> ProviderModelAllowlist:
    fallback_execution_provider_ids = execution_provider_ids or set()
    if not database_url:
        return ProviderModelAllowlist(
            allowed_model_ids_by_provider={},
            fallback_execution_provider_ids=fallback_execution_provider_ids,
            enforced=False,
        )

    with get_session(database_url) as session:
        rows = list(
            session.scalars(
                select(ProviderConnection).where(ProviderConnection.enabled.is_(True))
            )
        )

    allowed_model_ids_by_provider: dict[str, set[str]] = {}
    for row in rows:
        config = _dict(row.config_json)
        metadata = _dict(row.metadata_json)
        provider_id = str(config.get("provider_id") or row.connection_id or "").strip()
        if not provider_id or not _connection_execution_ready(
            row,
            config,
            settings=settings,
            execution_provider_ids=execution_provider_ids or set(),
        ):
            continue
        model_ids = _normalize_id_list(config.get("model_ids"))
        if not model_ids:
            model_ids = _normalize_id_list(metadata.get("model_ids"))
        if not model_ids:
            continue
        model_ids = _effective_connection_model_ids(
            provider_id=provider_id,
            config=config,
            model_ids=model_ids,
        )
        allowed_model_ids_by_provider.setdefault(provider_id, set()).update(model_ids)

    return ProviderModelAllowlist(
        allowed_model_ids_by_provider=allowed_model_ids_by_provider,
        fallback_execution_provider_ids=fallback_execution_provider_ids,
        enforced=bool(allowed_model_ids_by_provider),
    )


def _connection_execution_ready(
    row: ProviderConnection,
    config: dict[str, Any],
    *,
    settings: Settings | None,
    execution_provider_ids: set[str],
) -> bool:
    provider_id = str(config.get("provider_id") or row.connection_id or "").strip()
    if str(row.source_role or "").strip() not in EXECUTION_PROVIDER_SOURCE_ROLES:
        return False
    if provider_id in execution_provider_ids:
        return True
    configured = (
        bool(str(row.secret_ciphertext or "").strip())
        or bool(config.get("secretless"))
        or provider_id == "jina_reader"
    )
    if not configured:
        return False
    return True


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_id_list(value: object) -> list[str]:
    if isinstance(value, str):
        raw_items: tuple[object, ...] = tuple(value.split(","))
    elif isinstance(value, list):
        raw_items = tuple(value)
    else:
        raw_items = ()
    normalized: list[str] = []
    for item in raw_items:
        text = str(item or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _effective_connection_model_ids(
    *,
    provider_id: str,
    config: dict[str, Any],
    model_ids: list[str],
) -> list[str]:
    kind = str(config.get("kind") or "").strip().lower()
    if "model_namespace_prefix" in config:
        prefix = str(config.get("model_namespace_prefix") or "").strip().strip("/")
    elif kind in OPENAI_COMPATIBLE_CONNECTION_KINDS and provider_id != "openai":
        prefix = provider_id
    else:
        prefix = ""
    if not prefix:
        return model_ids
    return [
        model_id if model_id.startswith(f"{prefix}/") else f"{prefix}/{model_id}"
        for model_id in model_ids
    ]
