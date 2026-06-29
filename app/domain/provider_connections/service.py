from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select

from app.adapters.providers.registry import build_provider_adapter_from_connection
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderConnection
from app.core.secrets import encrypt_provider_connection_secret
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)
from app.domain.web_search.contracts import WEB_SEARCH_ABILITY, WEB_SEARCH_CONTRACT
from app.domain.web_search.service import WebSearchService

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
_ALLOWED_SOURCE_ROLES = frozenset({"execution_source", "runtime_metadata", "diagnostic_source"})
_SECRET_CONFIG_KEY_PARTS = (
    "secret",
    "credential",
    "token",
    "password",
    "api_key",
    "apikey",
)
_RUNTIME_CONFIG_CONNECTION_KINDS = frozenset(
    {
        "web_search_provider",
        "image_source_provider",
        "embedding_provider",
        "rerank_provider",
        "vector_store_provider",
    }
)


class ProviderConnectionAdminError(ValueError):
    def __init__(self, error_code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class ProviderConnectionAdminService:
    database_url: str
    settings: Settings

    def list_connections(self) -> dict[str, Any]:
        with get_session(self.database_url) as session:
            rows = list(
                session.scalars(
                    select(ProviderConnection).order_by(
                        ProviderConnection.enabled.desc(),
                        ProviderConnection.provider_type.asc(),
                        ProviderConnection.connection_id.asc(),
                    )
                )
            )
        return {
            "surface": "admin_provider_connections",
            "connections": [self._serialize(row) for row in rows],
            "boundary": _boundary(),
        }

    def save_connection(
        self,
        payload: dict[str, Any],
        *,
        connection_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = self._normalize_payload(payload, connection_id=connection_id)
        now = datetime.now(UTC)
        with get_session(self.database_url) as session:
            row = session.get(ProviderConnection, normalized["connection_id"])
            if row is None:
                row = ProviderConnection(
                    connection_id=normalized["connection_id"],
                    provider_type=normalized["provider_type"],
                    display_name=normalized["display_name"],
                    enabled=normalized["enabled"],
                    base_url=normalized["base_url"],
                    config_json=normalized["config_json"],
                    secret_ciphertext=None,
                    status="missing_secret",
                    source_role=normalized["source_role"],
                    metadata_json=normalized["metadata_json"],
                    last_tested_at=None,
                    last_sync_at=None,
                    last_error_code=None,
                    last_error_message=None,
                )
                session.add(row)
            else:
                row.provider_type = normalized["provider_type"]
                row.display_name = normalized["display_name"]
                row.enabled = normalized["enabled"]
                row.base_url = normalized["base_url"]
                row.config_json = normalized["config_json"]
                row.source_role = normalized["source_role"]
                row.metadata_json = normalized["metadata_json"]
                row.updated_at = now
                row.last_error_code = None
                row.last_error_message = None

            credential = normalized["credential"]
            if credential is not None:
                row.secret_ciphertext = (
                    encrypt_provider_connection_secret(credential, settings=self.settings)
                    if credential
                    else None
                )

            row.status = _connection_status(
                enabled=row.enabled,
                configured=bool(str(row.secret_ciphertext or "").strip())
                or bool(normalized["config_json"].get("secretless")),
            )
            session.commit()
            session.refresh(row)
            return self._serialize(row)

    def delete_connection(self, connection_id: str) -> dict[str, Any]:
        normalized_id = _normalize_identifier(connection_id, field="connection_id")
        with get_session(self.database_url) as session:
            row = session.get(ProviderConnection, normalized_id)
            if row is None:
                raise ProviderConnectionAdminError(
                    "provider_connection.not_found",
                    "provider connection was not found",
                    status_code=404,
                )
            serialized = self._serialize(row)
            session.delete(row)
            session.commit()
        return {"deleted": True, "connection": serialized}

    def test_connection(self, connection_id: str) -> dict[str, Any]:
        normalized_id = _normalize_identifier(connection_id, field="connection_id")
        now = datetime.now(UTC)
        with get_session(self.database_url) as session:
            row = session.get(ProviderConnection, normalized_id)
            if row is None:
                raise ProviderConnectionAdminError(
                    "provider_connection.not_found",
                    "provider connection was not found",
                    status_code=404,
                )

            serialized = self._serialize(row)
            result = self._build_test_result(row, serialized, now=now)
            row.last_tested_at = now
            if result["status"] == "ready":
                row.status = "ready"
                row.last_sync_at = now
                row.last_error_code = None
                row.last_error_message = None
            else:
                row.status = str(result["status"])
                row.last_error_code = str(result["error_code"] or "")
                row.last_error_message = str(result["message"] or "")
            session.commit()
            session.refresh(row)
            result["connection"] = self._serialize(row)
            return result

    def preview_catalog(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(payload, connection_id=None)
        secret_ciphertext = ""
        if normalized["credential"]:
            secret_ciphertext = encrypt_provider_connection_secret(
                str(normalized["credential"]),
                settings=self.settings,
            )
        elif not bool(normalized["config_json"].get("secretless")):
            with get_session(self.database_url) as session:
                existing = session.get(ProviderConnection, normalized["connection_id"])
                if existing is not None:
                    secret_ciphertext = _string(existing.secret_ciphertext)
        if not secret_ciphertext and not bool(normalized["config_json"].get("secretless")):
            raise ProviderConnectionAdminError(
                "provider_connection.preview_credential_required",
                "provider credential is required to fetch upstream models",
            )
        row = ProviderConnection(
            connection_id=normalized["connection_id"],
            provider_type=normalized["provider_type"],
            display_name=normalized["display_name"],
            enabled=True,
            base_url=normalized["base_url"],
            config_json=normalized["config_json"],
            secret_ciphertext=secret_ciphertext or None,
            status="ready",
            source_role=normalized["source_role"],
            metadata_json=normalized["metadata_json"],
            last_tested_at=None,
            last_sync_at=None,
            last_error_code=None,
            last_error_message=None,
        )
        adapter = build_provider_adapter_from_connection(self.settings, row)
        if adapter is None:
            raise ProviderConnectionAdminError(
                "provider_connection.unsupported_provider_kind",
                "provider kind is not supported by the runtime adapter registry",
            )
        try:
            snapshot = adapter.fetch_catalog()
        except Exception as error:
            raise ProviderConnectionAdminError(
                _map_test_error_code(error),
                _truncate_message(str(error) or error.__class__.__name__),
                status_code=502,
            ) from error

        preview_models = [_catalog_preview_model(model) for model in list(snapshot.models or [])]
        model_ids = [model["model_id"] for model in preview_models if model["model_id"]]
        return {
            "surface": "admin_provider_connection_catalog_preview",
            "provider_id": str(snapshot.provider_id or normalized["provider_id"]),
            "display_name": str(snapshot.display_name or normalized["display_name"]),
            "adapter_type": str(snapshot.adapter_type or ""),
            "model_count": len(model_ids),
            "model_ids": model_ids,
            "models": preview_models,
            "truncated": False,
            "credential_value_exposure": "none",
            "boundary": _boundary(),
        }

    def _build_test_result(
        self,
        row: ProviderConnection,
        serialized: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        if not bool(row.enabled):
            return _test_result(
                connection=serialized,
                status="disabled",
                stage="preflight",
                error_code="provider_connection.disabled",
                message="provider connection is disabled",
                now=now,
            )
        if not bool(serialized.get("configured")):
            return _test_result(
                connection=serialized,
                status="missing_secret",
                stage="preflight",
                error_code="provider_connection.missing_secret",
                message="provider credential is missing",
                now=now,
            )

        if str(serialized.get("kind") or "").strip().lower() == "web_search_provider":
            return self._build_web_search_test_result(row, serialized, now=now)

        if str(serialized.get("kind") or "").strip().lower() in _RUNTIME_CONFIG_CONNECTION_KINDS:
            return _test_result(
                connection=serialized,
                status="ready",
                stage="config_preflight",
                error_code="",
                message="provider runtime configuration is present",
                now=now,
            )

        adapter = build_provider_adapter_from_connection(self.settings, row)
        if adapter is None:
            return _test_result(
                connection=serialized,
                status="unsupported_provider_kind",
                stage="adapter_build",
                error_code="provider_connection.unsupported_provider_kind",
                message="provider kind is not supported by the runtime adapter registry",
                now=now,
            )

        try:
            snapshot = adapter.fetch_catalog()
        except Exception as error:  # provider adapters raise driver-specific exceptions.
            error_code = _map_test_error_code(error)
            return _test_result(
                connection=serialized,
                status=error_code.rsplit(".", 1)[-1],
                stage="catalog_fetch",
                error_code=error_code,
                message=_truncate_message(str(error) or error.__class__.__name__),
                now=now,
            )

        models = list(snapshot.models or [])
        if not models:
            return _test_result(
                connection=serialized,
                status="catalog_empty",
                stage="catalog_fetch",
                error_code="provider_connection.catalog_empty",
                message="provider catalog returned no usable models",
                now=now,
            )

        return _test_result(
            connection=serialized,
            status="ready",
            stage="catalog_fetch",
            error_code="",
            message="provider connection is ready",
            now=now,
            catalog={
                "provider_id": str(snapshot.provider_id or ""),
                "display_name": str(snapshot.display_name or ""),
                "adapter_type": str(snapshot.adapter_type or ""),
                "model_count": len(models),
                "sample_model_ids": [str(model.model_id) for model in models[:5]],
            },
        )

    def _build_web_search_test_result(
        self,
        row: ProviderConnection,
        serialized: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        provider_id = str(serialized.get("provider_id") or "").strip().lower()
        if provider_id == "jina_reader":
            return self._build_jina_reader_test_result(row, serialized, now=now)

        test_settings = self.settings.model_copy(deep=True)
        apply_provider_connection_runtime_settings(test_settings)
        test_settings.web_search_provider = provider_id
        input_payload = {
            "contract_version": WEB_SEARCH_CONTRACT,
            "query": "WordPress AI provider connection smoke test",
            "intent": "general_research",
            "max_results": 1,
            "provider": provider_id,
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }
        try:
            result = WebSearchService(test_settings).execute(
                site_id="admin_provider_connection_test",
                ability_name=WEB_SEARCH_ABILITY,
                contract_version=WEB_SEARCH_CONTRACT,
                input_payload=input_payload,
                run_id=f"provider-connection-test-{row.connection_id}-{int(now.timestamp())}",
            )
        except Exception as error:
            error_code = _map_test_error_code(error)
            return _test_result(
                connection=serialized,
                status=error_code.rsplit(".", 1)[-1],
                stage="web_search_probe",
                error_code=error_code,
                message=_truncate_message(str(error) or error.__class__.__name__),
                now=now,
            )

        result_json = result.result_json
        results = result_json.get("results")
        result_count = int(
            result_json.get("result_count") or (len(results) if isinstance(results, list) else 0)
        )
        return _test_result(
            connection=serialized,
            status="ready",
            stage="web_search_probe",
            error_code="",
            message=f"web search provider returned {result_count} source candidates",
            now=now,
            probe={
                "provider_id": str(result.usage.provider_id or provider_id),
                "result_count": result_count,
                "latency_ms": int(result.usage.latency_ms),
                "write_posture": str(result_json.get("write_posture") or "suggestion_only"),
                "direct_wordpress_write": bool(result_json.get("direct_wordpress_write")),
            },
        )

    def _build_jina_reader_test_result(
        self,
        row: ProviderConnection,
        serialized: dict[str, Any],
        *,
        now: datetime,
    ) -> dict[str, Any]:
        test_settings = self.settings.model_copy(deep=True)
        apply_provider_connection_runtime_settings(test_settings)
        base_url = str(test_settings.web_search_jina_reader_base_url or "").strip().rstrip("/")
        if not base_url:
            return _test_result(
                connection=serialized,
                status="missing_base_url",
                stage="web_search_reader_probe",
                error_code="provider_connection.missing_base_url",
                message="web search reader base URL is missing",
                now=now,
            )

        headers = {"Accept": "text/plain"}
        api_key = str(test_settings.web_search_jina_reader_api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        probe_url = "https://example.com/"
        started = time.monotonic()
        try:
            with httpx.Client(timeout=float(test_settings.web_search_jina_reader_timeout_seconds)) as client:
                response = client.get(f"{base_url}/{probe_url}", headers=headers)
                response.raise_for_status()
                readable_count = 1 if bytes(response.content[:4096]).strip() else 0
        except Exception as error:
            error_code = _map_test_error_code(error)
            return _test_result(
                connection=serialized,
                status=error_code.rsplit(".", 1)[-1],
                stage="web_search_reader_probe",
                error_code=error_code,
                message=_truncate_message(str(error) or error.__class__.__name__),
                now=now,
            )

        if readable_count < 1:
            return _test_result(
                connection=serialized,
                status="reader_empty",
                stage="web_search_reader_probe",
                error_code="provider_connection.reader_empty",
                message="web search reader returned no readable content",
                now=now,
            )

        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        return _test_result(
            connection=serialized,
            status="ready",
            stage="web_search_reader_probe",
            error_code="",
            message="web search reader returned 1 readable source candidates",
            now=now,
            probe={
                "provider_id": "jina_reader",
                "result_count": readable_count,
                "latency_ms": latency_ms,
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            },
        )

    def _normalize_payload(
        self,
        payload: dict[str, Any],
        *,
        connection_id: str | None,
    ) -> dict[str, Any]:
        raw_connection_id = connection_id or _string(payload.get("connection_id"))
        raw_provider_id = _string(payload.get("provider_id"))
        provider_type = _string(
            payload.get("provider_type") or payload.get("kind") or raw_provider_id
        )
        if not raw_connection_id and raw_provider_id:
            raw_connection_id = raw_provider_id
        normalized_connection_id = _normalize_identifier(raw_connection_id, field="connection_id")
        normalized_provider_id = _normalize_identifier(
            raw_provider_id or normalized_connection_id,
            field="provider_id",
        )
        normalized_provider_type = _normalize_identifier(provider_type, field="provider_type")
        display_name = _string(payload.get("display_name")) or normalized_provider_id
        if len(display_name) > 191:
            raise ProviderConnectionAdminError(
                "provider_connection.display_name_invalid",
                "display_name must be 191 characters or less",
            )
        source_role = _string(payload.get("source_role") or "execution_source")
        if source_role not in _ALLOWED_SOURCE_ROLES:
            raise ProviderConnectionAdminError(
                "provider_connection.source_role_invalid",
                "source_role must be execution_source, runtime_metadata, or diagnostic_source",
            )
        base_url = _string(payload.get("base_url"))
        if len(base_url) > 500:
            raise ProviderConnectionAdminError(
                "provider_connection.base_url_invalid",
                "base_url must be 500 characters or less",
            )
        config = _dict(payload.get("config"))
        config = _sanitize_config(config)
        capability_ids = _normalize_id_list(payload.get("capability_ids"))
        runtime_profile_ids = _normalize_id_list(payload.get("runtime_profile_ids"))
        metadata = _dict(payload.get("metadata"))
        secretless = bool(payload.get("secretless") or config.get("secretless"))
        if normalized_provider_type == "web_search_provider" and normalized_provider_id == "jina_reader":
            secretless = True
        config_json = {
            **config,
            "provider_id": normalized_provider_id,
            "kind": _string(payload.get("kind") or normalized_provider_type),
            "capability_ids": capability_ids,
            "runtime_profile_ids": runtime_profile_ids,
            "secretless": secretless,
        }
        credential = payload.get("credential")
        if credential is None:
            credential = payload.get("secret")
        normalized_credential = None if credential is None else str(credential)
        return {
            "connection_id": normalized_connection_id,
            "provider_id": normalized_provider_id,
            "provider_type": normalized_provider_type,
            "display_name": display_name,
            "enabled": bool(payload.get("enabled", True)),
            "base_url": base_url,
            "source_role": source_role,
            "config_json": config_json,
            "metadata_json": _sanitize_config(metadata),
            "credential": normalized_credential,
        }

    def _serialize(self, row: ProviderConnection) -> dict[str, Any]:
        config = _dict(row.config_json)
        capability_ids = _normalize_id_list(config.get("capability_ids"))
        runtime_profile_ids = _normalize_id_list(config.get("runtime_profile_ids"))
        metadata = _dict(row.metadata_json)
        model_ids = _normalize_id_list(config.get("model_ids"))
        if not model_ids:
            model_ids = _normalize_id_list(metadata.get("model_ids"))
        provider_id = _string(config.get("provider_id") or row.connection_id)
        configured = bool(str(row.secret_ciphertext or "").strip()) or bool(
            config.get("secretless")
        ) or provider_id == "jina_reader"
        return {
            "connection_id": row.connection_id,
            "provider_id": provider_id,
            "provider_type": row.provider_type,
            "display_name": row.display_name,
            "kind": _string(config.get("kind") or row.provider_type),
            "enabled": bool(row.enabled),
            "configured": configured,
            "status": _connection_status(enabled=bool(row.enabled), configured=configured),
            "source_role": row.source_role,
            "base_url": row.base_url or "",
            "capability_ids": capability_ids,
            "runtime_profile_ids": runtime_profile_ids,
            "model_ids": model_ids,
            "secrets": {
                "credential": {
                    "configured": configured,
                    "display": "configured" if configured else "missing",
                }
            },
            "config": _public_config(config),
            "metadata": metadata,
            "last_tested_at": _iso(row.last_tested_at),
            "last_sync_at": _iso(row.last_sync_at),
            "last_error_code": row.last_error_code or "",
            "last_error_message": row.last_error_message or "",
            "detail_href": "/admin/ai-resources",
            "managed_by": "cloud_provider_connections",
            "boundary": _boundary(),
        }


def _boundary() -> dict[str, Any]:
    return {
        "owner": "cloud_runtime",
        "secret_exposure": "masked_status_only",
        "direct_wordpress_write": False,
        "final_writes": "core_proposal_required",
        "not_a_control_plane": True,
        "does_not_own": [
            "wordpress_writes",
            "approval_truth",
            "ability_registry",
            "workflow_registry",
            "prompt_router_preset_truth",
        ],
    }


def _catalog_preview_model(model: Any) -> dict[str, Any]:
    instances = list(getattr(model, "instances", []) or [])
    capability_tags = sorted(
        {
            str(tag)
            for instance in instances
            for tag in list(getattr(instance, "capability_tags", []) or [])
            if str(tag)
        }
    )
    runtime_supported = bool(instances)
    return {
        "model_id": str(getattr(model, "model_id", "") or ""),
        "family": str(getattr(model, "family", "") or ""),
        "feature": str(getattr(model, "feature", "") or ""),
        "status": str(getattr(model, "status", "") or ""),
        "is_deprecated": bool(getattr(model, "is_deprecated", False)),
        "runtime_supported": runtime_supported,
        "verified": runtime_supported,
        "capability_tags": capability_tags,
    }


def _connection_status(*, enabled: bool, configured: bool) -> str:
    if not enabled:
        return "disabled"
    return "ready" if configured else "missing_secret"


def _test_result(
    *,
    connection: dict[str, Any],
    status: str,
    stage: str,
    error_code: str,
    message: str,
    now: datetime,
    catalog: dict[str, Any] | None = None,
    probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "surface": "admin_provider_connection_test",
        "connection_id": str(connection.get("connection_id") or ""),
        "provider_id": str(connection.get("provider_id") or ""),
        "kind": str(connection.get("kind") or ""),
        "status": status,
        "stage": stage,
        "ok": status == "ready",
        "error_code": error_code,
        "message": message,
        "tested_at": _iso(now),
        "catalog": catalog or {},
        "probe": probe or {},
        "connection": connection,
        "boundary": _boundary(),
    }


def _map_test_error_code(error: Exception) -> str:
    provider_error_code = str(getattr(error, "error_code", "") or "").strip()
    if provider_error_code:
        return provider_error_code
    message = str(error).lower()
    if "401" in message or "403" in message or "auth" in message or "credential" in message:
        return "provider_connection.auth_failed"
    if "timed out" in message or "timeout" in message:
        return "provider_connection.network_error"
    if "network" in message or "connect" in message or "name resolution" in message:
        return "provider_connection.network_error"
    if "no usable models" in message:
        return "provider_connection.catalog_empty"
    return "provider_connection.test_failed"


def _truncate_message(value: str, limit: int = 360) -> str:
    normalized = _string(value)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def _normalize_identifier(value: str, *, field: str) -> str:
    normalized = _string(value).lower()
    if not _IDENTIFIER_PATTERN.match(normalized):
        raise ProviderConnectionAdminError(
            f"provider_connection.{field}_invalid",
            (
                f"{field} must be 2-64 lowercase characters using letters, numbers, "
                "dot, dash, or underscore"
            ),
        )
    return normalized


def _normalize_id_list(value: object) -> list[str]:
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        values = [_string(item) for item in value]
    else:
        values = []
    normalized: list[str] = []
    for item in values:
        if not item or item in normalized:
            continue
        normalized.append(item[:128])
    return normalized


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    hidden_keys = {
        "provider_id",
        "kind",
        "capability_ids",
        "runtime_profile_ids",
        "group_id",
    }
    return {
        key: value
        for key, value in _sanitize_config(config).items()
        if key not in hidden_keys and key != "secretless"
    }


def _sanitize_config(config: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in config.items():
        normalized_key = str(key)
        if _is_secret_key(normalized_key):
            continue
        if isinstance(value, dict):
            sanitized[normalized_key] = _sanitize_config(value)
        elif isinstance(value, list):
            sanitized[normalized_key] = [
                _sanitize_config(item) if isinstance(item, dict) else item for item in value
            ]
        else:
            sanitized[normalized_key] = value
    return sanitized


def _is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    if normalized in {"api_key_label", "api_key_labels", "key_label", "key_labels"}:
        return False
    return any(part in normalized for part in _SECRET_CONFIG_KEY_PARTS)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return str(value or "").strip()


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""
