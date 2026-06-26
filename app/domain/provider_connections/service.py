from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.adapters.providers.registry import build_provider_adapter_from_connection
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderConnection
from app.core.secrets import encrypt_provider_connection_secret

_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")
_ALLOWED_SOURCE_ROLES = frozenset({"execution_source", "runtime_metadata", "diagnostic_source"})
_SECRET_CONFIG_KEY_PARTS = (
    "secret",
    "credential",
    "token",
    "password",
    "api_key",
    "apikey",
    "group_id",
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

    def import_env_connections(self) -> dict[str, Any]:
        candidates = self._env_import_candidates()
        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for candidate in candidates:
            if not str(candidate.get("credential") or "").strip():
                skipped.append(
                    {
                        "connection_id": str(candidate["connection_id"]),
                        "reason": "missing_env_secret",
                    }
                )
                continue
            imported.append(self.save_connection(candidate))
        return {
            "surface": "admin_provider_connection_env_import",
            "imported": imported,
            "skipped": skipped,
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

    def _env_import_candidates(self) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = [
            {
                "connection_id": "openai_env",
                "provider_id": "openai",
                "provider_type": "openai_compatible",
                "kind": "openai_compatible",
                "display_name": str(self.settings.openai_provider_label or "").strip()
                or "OpenAI-compatible env",
                "enabled": True,
                "base_url": str(self.settings.openai_base_url or ""),
                "source_role": "execution_source",
                "capability_ids": ["text_generation", "image_generation"],
                "runtime_profile_ids": ["text.ai", "text.free-gpt55", "grok-imagine-image-quality"],
                "credential": self.settings.openai_api_key or "",
                "metadata": {"imported_from": "env", "env_prefix": "NPCINK_CLOUD_OPENAI"},
            },
            {
                "connection_id": "minimax_env",
                "provider_id": "minimax",
                "provider_type": "minimax",
                "kind": "minimax",
                "display_name": "MiniMax env",
                "enabled": bool(self.settings.minimax_provider_enabled)
                or bool(str(self.settings.minimax_api_key or "").strip()),
                "base_url": str(self.settings.minimax_base_url or ""),
                "source_role": "execution_source",
                "capability_ids": ["audio_generation"],
                "runtime_profile_ids": [
                    "audio.narration.default",
                    "audio.narration.quality",
                ],
                "credential": self.settings.minimax_api_key or "",
                "config": {
                    "group_id": self.settings.minimax_group_id or "",
                    "default_voice_id": self.settings.minimax_default_voice_id,
                },
                "metadata": {"imported_from": "env", "env_prefix": "NPCINK_CLOUD_MINIMAX"},
            },
        ]
        return candidates

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
        config_json = {
            **config,
            "provider_id": normalized_provider_id,
            "kind": _string(payload.get("kind") or normalized_provider_type),
            "capability_ids": capability_ids,
            "runtime_profile_ids": runtime_profile_ids,
            "secretless": bool(payload.get("secretless") or config.get("secretless")),
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
        provider_id = _string(config.get("provider_id") or row.connection_id)
        configured = bool(str(row.secret_ciphertext or "").strip()) or bool(
            config.get("secretless")
        )
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
            "secrets": {
                "credential": {
                    "configured": configured,
                    "display": "configured" if configured else "missing",
                }
            },
            "config": _public_config(config),
            "metadata": _dict(row.metadata_json),
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
        "connection": connection,
        "boundary": _boundary(),
    }


def _map_test_error_code(error: Exception) -> str:
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
    hidden_keys = {"provider_id", "kind", "capability_ids", "runtime_profile_ids"}
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
    return any(part in normalized for part in _SECRET_CONFIG_KEY_PARTS)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return str(value or "").strip()


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""
