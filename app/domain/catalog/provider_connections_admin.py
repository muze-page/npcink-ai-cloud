from __future__ import annotations

from datetime import UTC, datetime
import re
from typing import Any, Callable

from app.adapters.providers.anthropic import AnthropicProviderAdapter
from app.adapters.providers.base import ProviderAdapter
from app.adapters.providers.base import CatalogInstanceSeed, CatalogModelSeed, ProviderCatalogSnapshot
from app.adapters.providers.litellm_gateway import LiteLLMGatewayProviderAdapter
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.adapters.providers.openrouter import OpenRouterProviderAdapter
from app.adapters.providers.registry import build_provider_adapter_from_connection
from app.adapters.providers.tei import TEIProviderAdapter
from app.adapters.providers.vllm import VLLMProviderAdapter
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings
from app.core.db import get_session
from app.core.secrets import (
    decrypt_provider_connection_secret,
    encrypt_provider_connection_secret,
)
from app.dev.model_ops_release_preflight import evaluate_model_admin_release_preflight

ALLOWED_PROVIDER_CONNECTION_TYPES = {
    "openai",
    "anthropic",
    "litellm",
    "vllm",
    "tei",
    "openrouter",
}
ALLOWED_PROVIDER_SOURCE_ROLES = {
    "intelligence_source",
    "execution_source",
    "dual_source",
}
PROVIDER_CONNECTION_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


class ProviderConnectionsAdminService:
    def __init__(
        self,
        *,
        database_url: str,
        settings: Settings | None,
        sync_default_routing: Callable[[CatalogRepository, str], None],
    ) -> None:
        self.database_url = database_url
        self.settings = settings
        self.sync_default_routing = sync_default_routing

    def list_connections(self) -> dict[str, Any]:
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            connections = repository.list_provider_connections()

        items = [self._serialize_connection(item) for item in connections]
        return {
            "items": items,
            "total": len(items),
            "summary": {
                "enabled_total": sum(1 for item in items if item["enabled"]),
                "healthy_total": sum(1 for item in items if item["status"] == "ok"),
                "error_total": sum(1 for item in items if item["status"] == "error"),
                "provider_types": sorted({item["provider_type"] for item in items}),
                "source_role_counts": {
                    "execution_source": sum(
                        1 for item in items if item["source_role"] == "execution_source"
                    ),
                    "intelligence_source": sum(
                        1 for item in items if item["source_role"] == "intelligence_source"
                    ),
                    "dual_source": sum(
                        1 for item in items if item["source_role"] == "dual_source"
                    ),
                },
            },
            "provider_types": self.supported_provider_types(),
        }

    def get_connection(self, connection_id: str) -> dict[str, Any] | None:
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            connection = repository.get_provider_connection(connection_id)
        if connection is None:
            return None
        return self._serialize_connection(connection)

    def upsert_connection(
        self,
        *,
        connection_id: str,
        provider_type: str,
        source_role: str | None,
        display_name: str,
        enabled: bool,
        base_url: str,
        config: dict[str, Any] | None,
        api_key: str | None,
    ) -> dict[str, Any]:
        normalized_connection_id = self._normalize_connection_id(connection_id)
        normalized_provider_type = self._normalize_provider_type(provider_type)
        normalized_source_role = self._normalize_source_role(
            source_role,
            provider_type=normalized_provider_type,
        )
        normalized_display_name = self._normalize_display_name(
            display_name,
            provider_type=normalized_provider_type,
            connection_id=normalized_connection_id,
        )
        normalized_base_url = self._normalize_base_url(base_url)
        normalized_config = self._normalize_config(normalized_provider_type, config)
        normalized_secret = str(api_key or "").strip()
        status = "configured" if enabled else "inactive"

        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            existing = repository.get_provider_connection(normalized_connection_id)
            secret_ciphertext = None
            if normalized_secret:
                secret_ciphertext = encrypt_provider_connection_secret(
                    normalized_secret,
                    settings=self._require_settings(),
                )
            metadata = dict(getattr(existing, "metadata_json", None) or {})
            metadata["source"] = "admin_provider_connections_console_v1"
            metadata["credential_origin"] = "cloud_local"
            metadata["credential_scope"] = "cloud_only"
            metadata["execution_release_state"] = str(
                metadata.get("execution_release_state") or "draft"
            )
            connection = repository.upsert_provider_connection(
                connection_id=normalized_connection_id,
                provider_type=normalized_provider_type,
                source_role=normalized_source_role,
                display_name=normalized_display_name,
                enabled=enabled,
                base_url=normalized_base_url,
                config_json=normalized_config,
                secret_ciphertext=secret_ciphertext,
                status=status,
                metadata_json=metadata,
            )
            session.commit()

        return self._serialize_connection(connection)

    def test_connection(self, connection_id: str) -> dict[str, Any] | None:
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            connection = repository.get_provider_connection(connection_id)
            if connection is None:
                return None
            tested_at = datetime.now(UTC)
            try:
                snapshot = self._normalize_connection_snapshot(
                    self._build_provider_adapter(connection).fetch_catalog(),
                    connection_id=connection.connection_id,
                )
                repository.update_provider_connection_status(
                    connection_id=connection_id,
                    status="ok",
                    last_tested_at=tested_at,
                    last_error_code=None,
                    last_error_message=None,
                    metadata_json={
                        **dict(connection.metadata_json or {}),
                        "last_test_models_total": len(snapshot.models),
                        "last_test_provider_id": snapshot.provider_id,
                        "last_tested_ok_at": self._serialize_timestamp(tested_at),
                        "execution_release_test_state": "passed",
                    },
                )
                session.commit()
                return {
                    "connection": self._serialize_connection(
                        repository.get_provider_connection(connection_id)
                    ),
                    "test_result": {
                        "ok": True,
                        "tested_at": self._serialize_timestamp(tested_at),
                        "models_total": len(snapshot.models),
                        "inspected_models": [
                            {
                                "model_id": item.model_id,
                                "feature": item.feature,
                                "status": item.status,
                            }
                            for item in snapshot.models[:10]
                        ],
                    },
                }
            except Exception as error:
                metadata = dict(connection.metadata_json or {})
                metadata["execution_release_test_state"] = "failed"
                repository.update_provider_connection_status(
                    connection_id=connection_id,
                    status="error",
                    last_tested_at=tested_at,
                    last_error_code="provider.connection_test_failed",
                    last_error_message=str(error),
                    metadata_json=metadata,
                )
                session.commit()
                raise

    def sync_connection_catalog(self, connection_id: str) -> dict[str, Any] | None:
        revision = datetime.now(UTC).strftime("catalog-%Y%m%d%H%M%S%f")
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            connection = repository.get_provider_connection(connection_id)
            if connection is None:
                return None
            synced_at = datetime.now(UTC)
            try:
                existing_model_ids = {
                    item.model_id
                    for item in repository.list_all_models()
                    if item.provider_id == connection.connection_id
                }
                snapshot = self._normalize_connection_snapshot(
                    self._build_provider_adapter(connection).fetch_catalog(),
                    connection_id=connection.connection_id,
                )
                incoming_model_ids = {item.model_id for item in snapshot.models}
                added_model_ids = sorted(incoming_model_ids - existing_model_ids)
                removed_model_ids = sorted(existing_model_ids - incoming_model_ids)
                updated_model_ids = sorted(incoming_model_ids & existing_model_ids)
                repository.upsert_provider_snapshot(snapshot, revision)
                repository.create_revision(
                    revision,
                    snapshot.provider_id,
                    source="admin_provider_connection_sync",
                    notes=connection.connection_id,
                )
                self.sync_default_routing(repository, revision)
                repository.update_provider_connection_status(
                    connection_id=connection_id,
                    status="ok",
                    last_sync_at=synced_at,
                    last_error_code=None,
                    last_error_message=None,
                    metadata_json={
                        **dict(connection.metadata_json or {}),
                        "last_sync_models_total": len(snapshot.models),
                        "last_sync_revision": revision,
                        "candidate_execution_revision": revision,
                        "last_release_smoke_revision": revision,
                        "last_release_smoked_at": self._serialize_timestamp(synced_at),
                        "execution_release_smoke_state": "passed",
                        "execution_release_state": "synced",
                    },
                )
                session.commit()
                return {
                    "connection": self._serialize_connection(
                        repository.get_provider_connection(connection_id)
                    ),
                    "sync_result": {
                        "ok": True,
                        "synced_at": self._serialize_timestamp(synced_at),
                        "revision": revision,
                        "models_total": len(snapshot.models),
                        "provider_id": snapshot.provider_id,
                        "added_total": len(added_model_ids),
                        "updated_total": len(updated_model_ids),
                        "removed_total": len(removed_model_ids),
                        "inspected_models": [
                            {
                                "model_id": item.model_id,
                                "feature": item.feature,
                                "status": item.status,
                            }
                            for item in snapshot.models[:10]
                        ],
                    },
                }
            except Exception as error:
                repository.update_provider_connection_status(
                    connection_id=connection_id,
                    status="error",
                    last_error_code="provider.catalog_sync_failed",
                    last_error_message=str(error),
                )
                session.commit()
                raise

    def promote_connection_execution_revision(
        self,
        connection_id: str,
    ) -> dict[str, Any] | None:
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            connection = repository.get_provider_connection(connection_id)
            if connection is None:
                return None
            metadata = dict(getattr(connection, "metadata_json", None) or {})
            last_sync_revision = str(metadata.get("last_sync_revision") or "").strip()
            if not last_sync_revision:
                raise ValueError("provider connection must be synced before promote")
            preflight_report = evaluate_model_admin_release_preflight(self._require_settings())
            if not bool(preflight_report.get("ok")):
                blocker_codes = [
                    str(item.get("code") or "").strip()
                    for item in list(preflight_report.get("checks") or [])
                    if str(item.get("status") or "").strip() == "blocker"
                ]
                details = ", ".join(code for code in blocker_codes if code)
                raise ValueError(
                    "provider connection promote blocked by release preflight"
                    + (f": {details}" if details else "")
                )
            if not str(metadata.get("last_tested_ok_at") or "").strip():
                raise ValueError("provider connection must pass test before promote")
            if (
                str(metadata.get("execution_release_test_state") or "").strip().lower()
                != "passed"
            ):
                raise ValueError("provider connection test evidence is not green")
            if (
                str(metadata.get("execution_release_smoke_state") or "").strip().lower()
                != "passed"
            ):
                raise ValueError("provider connection must pass smoke before promote")
            if (
                str(metadata.get("last_release_smoke_revision") or "").strip()
                != last_sync_revision
            ):
                raise ValueError(
                    "provider connection smoke evidence must match the candidate execution revision before promote"
                )
            metadata["active_execution_revision"] = last_sync_revision
            metadata["execution_release_state"] = "active"
            metadata["execution_promoted_at"] = self._serialize_timestamp(datetime.now(UTC))
            metadata["last_release_preflight_ok_at"] = self._serialize_timestamp(datetime.now(UTC))
            repository.update_provider_connection_status(
                connection_id=connection_id,
                status=str(getattr(connection, "status", "") or "configured"),
                metadata_json=metadata,
            )
            session.commit()
            return {
                "connection": self._serialize_connection(
                    repository.get_provider_connection(connection_id)
                ),
                "promote_result": {
                    "ok": True,
                    "active_execution_revision": last_sync_revision,
                },
            }

    def supported_provider_types(self) -> list[dict[str, str]]:
        return [
            {
                "provider_type": "openai",
                "label": "OpenAI compatible",
                "default_source_role": self._default_source_role_for_provider("openai"),
            },
            {
                "provider_type": "anthropic",
                "label": "Anthropic",
                "default_source_role": self._default_source_role_for_provider("anthropic"),
            },
            {
                "provider_type": "litellm",
                "label": "LiteLLM",
                "default_source_role": self._default_source_role_for_provider("litellm"),
            },
            {
                "provider_type": "vllm",
                "label": "vLLM",
                "default_source_role": self._default_source_role_for_provider("vllm"),
            },
            {
                "provider_type": "tei",
                "label": "TEI",
                "default_source_role": self._default_source_role_for_provider("tei"),
            },
            {
                "provider_type": "openrouter",
                "label": "OpenRouter",
                "default_source_role": self._default_source_role_for_provider("openrouter"),
            },
        ]

    def _build_provider_adapter(self, connection: Any) -> ProviderAdapter:
        return build_provider_adapter_from_connection(
            connection,
            self._require_settings(),
        )

    def _normalize_connection_snapshot(
        self,
        snapshot: ProviderCatalogSnapshot,
        *,
        connection_id: str,
    ) -> ProviderCatalogSnapshot:
        normalized_provider_id = str(connection_id).strip()
        normalized_models: list[CatalogModelSeed] = []
        for model_seed in snapshot.models:
            raw_model_id = str(model_seed.model_id or "").strip()
            model_id = raw_model_id
            prefix = f"{normalized_provider_id}/"
            if raw_model_id and not raw_model_id.lower().startswith(prefix.lower()):
                model_id = f"{normalized_provider_id}/{raw_model_id}"

            normalized_instances: list[CatalogInstanceSeed] = []
            for instance_seed in model_seed.instances:
                raw_instance_id = str(instance_seed.instance_id or "").strip()
                instance_id = raw_instance_id
                if raw_instance_id and not raw_instance_id.lower().startswith(prefix.lower()):
                    instance_id = f"{normalized_provider_id}/{raw_instance_id}"
                normalized_instances.append(
                    CatalogInstanceSeed(
                        instance_id=instance_id,
                        endpoint_variant=instance_seed.endpoint_variant,
                        region=instance_seed.region,
                        capability_tags=list(instance_seed.capability_tags),
                        health_status=instance_seed.health_status,
                        is_default=instance_seed.is_default,
                        weight=instance_seed.weight,
                    )
                )

            normalized_models.append(
                CatalogModelSeed(
                    model_id=model_id,
                    family=model_seed.family,
                    feature=model_seed.feature,
                    status=model_seed.status,
                    context_window=model_seed.context_window,
                    price_input=model_seed.price_input,
                    price_output=model_seed.price_output,
                    is_deprecated=model_seed.is_deprecated,
                    fallback_candidate=model_seed.fallback_candidate,
                    raw_json=dict(model_seed.raw_json or {}),
                    instances=normalized_instances,
                )
            )

        return ProviderCatalogSnapshot(
            provider_id=normalized_provider_id,
            display_name=snapshot.display_name,
            adapter_type=snapshot.adapter_type,
            models=normalized_models,
        )

    def _serialize_connection(self, connection: Any | None) -> dict[str, Any]:
        if connection is None:
            return {}
        config = dict(getattr(connection, "config_json", None) or {})
        metadata = dict(getattr(connection, "metadata_json", None) or {})
        return {
            "connection_id": str(getattr(connection, "connection_id", "") or ""),
            "provider_type": str(getattr(connection, "provider_type", "") or ""),
            "source_role": self._normalize_source_role(
                getattr(connection, "source_role", None),
                provider_type=str(getattr(connection, "provider_type", "") or ""),
            ),
            "display_name": str(getattr(connection, "display_name", "") or ""),
            "enabled": bool(getattr(connection, "enabled", False)),
            "base_url": str(getattr(connection, "base_url", "") or ""),
            "status": str(getattr(connection, "status", "") or "configured"),
            "config": {
                "organization": self._coerce_string(config.get("organization")),
                "api_version": self._coerce_string(config.get("api_version")),
                "timeout_seconds": self._coerce_timeout(config.get("timeout_seconds")),
                "model_ids": self._coerce_string_list(config.get("model_ids")),
                "region": self._coerce_string(config.get("region")),
                "context_window": self._coerce_int(config.get("context_window"), 0),
                "site_url": self._coerce_string(config.get("site_url")),
            },
            "has_secret": bool(str(getattr(connection, "secret_ciphertext", "") or "").strip()),
            "last_tested_at": self._serialize_timestamp(
                getattr(connection, "last_tested_at", None)
            ),
            "last_sync_at": self._serialize_timestamp(
                getattr(connection, "last_sync_at", None)
            ),
            "last_error_code": str(getattr(connection, "last_error_code", "") or ""),
            "last_error_message": str(getattr(connection, "last_error_message", "") or ""),
            "last_test_models_total": self._coerce_int(metadata.get("last_test_models_total"), 0),
            "last_test_provider_id": self._coerce_string(metadata.get("last_test_provider_id")),
            "last_sync_models_total": self._coerce_int(metadata.get("last_sync_models_total"), 0),
            "last_sync_revision": self._coerce_string(metadata.get("last_sync_revision")),
            "candidate_execution_revision": self._coerce_string(
                metadata.get("candidate_execution_revision")
            ),
            "active_execution_revision": self._coerce_string(
                metadata.get("active_execution_revision")
            ),
            "execution_release_state": self._coerce_string(
                metadata.get("execution_release_state")
            ),
            "execution_release_test_state": self._coerce_string(
                metadata.get("execution_release_test_state")
            ),
            "execution_release_smoke_state": self._coerce_string(
                metadata.get("execution_release_smoke_state")
            ),
            "last_release_smoke_revision": self._coerce_string(
                metadata.get("last_release_smoke_revision")
            ),
            "last_release_smoked_at": self._coerce_string(
                metadata.get("last_release_smoked_at")
            ),
            "last_release_preflight_ok_at": self._coerce_string(
                metadata.get("last_release_preflight_ok_at")
            ),
            "credential_origin": self._coerce_string(metadata.get("credential_origin")),
            "credential_scope": self._coerce_string(metadata.get("credential_scope")),
            "updated_at": self._serialize_timestamp(getattr(connection, "updated_at", None)),
            "created_at": self._serialize_timestamp(getattr(connection, "created_at", None)),
        }

    def _normalize_connection_id(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not PROVIDER_CONNECTION_ID_PATTERN.fullmatch(normalized):
            raise ValueError("connection_id must use lowercase letters, digits, dot, dash, or underscore")
        return normalized

    def _normalize_provider_type(self, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in ALLOWED_PROVIDER_CONNECTION_TYPES:
            raise ValueError(f"unsupported provider_type: {normalized}")
        return normalized

    def _normalize_source_role(
        self,
        value: str | None,
        *,
        provider_type: str,
    ) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return self._default_source_role_for_provider(provider_type)
        if normalized not in ALLOWED_PROVIDER_SOURCE_ROLES:
            raise ValueError(f"unsupported source_role: {normalized}")
        return normalized

    def _default_source_role_for_provider(self, provider_type: str) -> str:
        normalized = str(provider_type or "").strip().lower()
        if normalized == "openrouter":
            return "dual_source"
        if normalized == "litellm":
            return "dual_source"
        return "execution_source"

    def _normalize_display_name(
        self,
        value: str,
        *,
        provider_type: str,
        connection_id: str,
    ) -> str:
        normalized = str(value or "").strip()
        if normalized:
            return normalized
        return f"{provider_type.replace('_', ' ').title()} · {connection_id}"

    def _normalize_base_url(self, value: str) -> str:
        normalized = str(value or "").strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url is required")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return normalized

    def _normalize_config(
        self,
        provider_type: str,
        config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        raw = dict(config or {})
        normalized: dict[str, Any] = {
            "timeout_seconds": self._coerce_timeout(raw.get("timeout_seconds")),
        }
        if provider_type == "openai":
            normalized["organization"] = self._coerce_string(raw.get("organization"))
        elif provider_type == "anthropic":
            normalized["api_version"] = self._coerce_string(raw.get("api_version")) or "2023-06-01"
        elif provider_type == "tei":
            model_ids = self._coerce_string_list(raw.get("model_ids"))
            if not model_ids:
                raise ValueError("tei connections require at least one model id")
            normalized["model_ids"] = model_ids
            normalized["region"] = self._coerce_string(raw.get("region")) or "self-hosted"
            normalized["context_window"] = self._coerce_int(raw.get("context_window"), 8192)
        elif provider_type == "openrouter":
            normalized["site_url"] = self._coerce_string(raw.get("site_url"))
        return normalized

    def _coerce_timeout(self, value: Any) -> float:
        try:
            timeout_seconds = float(value if value not in (None, "") else DEFAULT_CONNECTION_TIMEOUT_SECONDS)
        except (TypeError, ValueError) as error:
            raise ValueError("timeout_seconds must be numeric") from error
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        return timeout_seconds

    def _coerce_int(self, value: Any, default: int) -> int:
        try:
            normalized = int(value if value not in (None, "") else default)
        except (TypeError, ValueError):
            return default
        return normalized if normalized > 0 else default

    def _coerce_string(self, value: Any) -> str:
        return str(value or "").strip()

    def _coerce_string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            candidates = value
        else:
            candidates = str(value or "").split(",")
        deduped: list[str] = []
        for item in candidates:
            normalized = str(item or "").strip()
            if normalized and normalized not in deduped:
                deduped.append(normalized)
        return deduped

    def _serialize_timestamp(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return ""

    def _require_settings(self) -> Settings:
        if self.settings is None:
            raise RuntimeError("provider connections require cloud settings")
        return self.settings
