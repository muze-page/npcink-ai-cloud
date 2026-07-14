from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select

from app.adapters.providers.base import ProviderExecutionError, ProviderExecutionRequest
from app.adapters.providers.siliconflow import SiliconFlowProviderAdapter
from app.core.config import Settings
from app.core.db import get_session
from app.core.models import (
    ProviderConnection,
    SiteKnowledgeChunk,
    SiteKnowledgeDocument,
    SiteKnowledgeSearchMetric,
)
from app.core.secrets import decrypt_provider_connection_secret, encrypt_provider_connection_secret
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)
from app.domain.site_knowledge.backends import (
    SiteKnowledgeBackendError,
    ZillizCloudSiteKnowledgeBackend,
)
from app.domain.site_knowledge.vector_profile_contract import (
    SITE_KNOWLEDGE_VECTOR_BASE_URL,
    SITE_KNOWLEDGE_VECTOR_CONNECTION_ID,
    SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
    SITE_KNOWLEDGE_VECTOR_LOCAL_TEST_BACKEND,
    SITE_KNOWLEDGE_VECTOR_METRIC,
    SITE_KNOWLEDGE_VECTOR_MODEL_ID,
    SITE_KNOWLEDGE_VECTOR_PROBE_REVISION,
    SITE_KNOWLEDGE_VECTOR_PRODUCTION_BACKEND,
    SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
    SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
    SITE_KNOWLEDGE_VECTOR_PROVIDER_NAME,
    SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
    SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
    SITE_KNOWLEDGE_VECTOR_STORE_PROBE_REVISION,
    SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_ID,
    SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_NAME,
)


class SiteKnowledgeVectorProfileAdminError(ValueError):
    def __init__(self, error_code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class SiteKnowledgeVectorProfileAdminService:
    database_url: str
    settings: Settings

    def get_profile(self) -> dict[str, Any]:
        with get_session(self.database_url) as session:
            connection = session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_CONNECTION_ID)
            vector_store_connection = session.get(
                ProviderConnection,
                SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
            )
            document_count = int(
                session.scalar(select(func.count()).select_from(SiteKnowledgeDocument)) or 0
            )
            chunk_count = int(
                session.scalar(select(func.count()).select_from(SiteKnowledgeChunk)) or 0
            )
            latest_search = session.scalar(
                select(SiteKnowledgeSearchMetric)
                .where(
                    SiteKnowledgeSearchMetric.vector_backend
                    == SITE_KNOWLEDGE_VECTOR_PRODUCTION_BACKEND
                )
                .order_by(SiteKnowledgeSearchMetric.created_at.desc())
                .limit(1)
            )

        provider = self._provider_state(connection)
        vector_store = self._vector_store_state(vector_store_connection)
        environment = str(self.settings.environment or "development").strip().lower()
        local_or_test = environment in {"development", "dev", "test"}
        validation = self._validation_state(
            vector_store_connection,
            provider=provider,
            vector_store=vector_store,
            document_count=document_count,
            chunk_count=chunk_count,
            latest_search=latest_search,
        )
        active_backend = (
            SITE_KNOWLEDGE_VECTOR_PRODUCTION_BACKEND
            if vector_store["verified"]
            and validation["index"]["status"] in {"ready", "empty"}
            else SITE_KNOWLEDGE_VECTOR_LOCAL_TEST_BACKEND
        )
        if not provider["configured"]:
            status = "not_configured"
        elif not provider["verified"]:
            status = "probe_required"
        elif not local_or_test and not vector_store["verified"]:
            status = "vector_store_pending"
        elif validation["index"]["status"] in {
            "reindex_required",
            "rebuilding",
            "failed",
        }:
            status = validation["index"]["status"]
        else:
            status = "ready"

        return {
            "surface": "admin_site_knowledge_vector_profile",
            "profile_id": SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
            "model_id": SITE_KNOWLEDGE_VECTOR_MODEL_ID,
            "dimensions": SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
            "metric": SITE_KNOWLEDGE_VECTOR_METRIC,
            "production_backend": SITE_KNOWLEDGE_VECTOR_PRODUCTION_BACKEND,
            "local_test_backend": SITE_KNOWLEDGE_VECTOR_LOCAL_TEST_BACKEND,
            "active_backend": active_backend,
            "status": status,
            "provider": provider,
            "vector_store": vector_store,
            "validation": validation,
            "editable_fields": ["credential", "zilliz_endpoint", "zilliz_token"],
            "reindex_policy": "profile_change_requires_reindex",
            "boundary": {
                "owner": "cloud_runtime",
                "credential_value_exposure": "presence_only",
                "direct_wordpress_write": False,
                "suggestion_only": True,
                "not_a_control_plane": True,
            },
        }

    def save_and_verify(self, credential: str | None) -> dict[str, Any]:
        current = self._load_connection()
        resolved_credential = str(credential or "").strip()
        if not resolved_credential and current is not None:
            resolved_credential = self._decrypt_credential(current)
        if not resolved_credential:
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.credential_required",
                "SiliconFlow API key is required",
            )

        probe = self._probe_embedding(resolved_credential)
        now = datetime.now(UTC)
        fixed_config = {
            "provider_id": SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
            "kind": SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
            "capability_ids": ["embedding"],
            "runtime_profile_ids": ["embed.default"],
            "model_id": SITE_KNOWLEDGE_VECTOR_MODEL_ID,
            "model_ids": [SITE_KNOWLEDGE_VECTOR_MODEL_ID],
            "site_knowledge_model_id": SITE_KNOWLEDGE_VECTOR_MODEL_ID,
            "dimensions": SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
            "metric": SITE_KNOWLEDGE_VECTOR_METRIC,
            "site_knowledge_profile_id": SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
            "site_knowledge_probe_revision": SITE_KNOWLEDGE_VECTOR_PROBE_REVISION,
            "site_knowledge_probe_dimensions": SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
            "site_knowledge_probe_metric": SITE_KNOWLEDGE_VECTOR_METRIC,
        }
        with get_session(self.database_url) as session:
            row = session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_CONNECTION_ID)
            if row is None:
                row = ProviderConnection(
                    connection_id=SITE_KNOWLEDGE_VECTOR_CONNECTION_ID,
                    provider_type=SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
                    display_name=f"{SITE_KNOWLEDGE_VECTOR_PROVIDER_NAME} Site Knowledge",
                    enabled=True,
                    base_url=SITE_KNOWLEDGE_VECTOR_BASE_URL,
                    config_json=fixed_config,
                    secret_ciphertext=None,
                    status="ready",
                    source_role="execution_source",
                    metadata_json={"managed_surface": "site_knowledge_vector_profile"},
                    last_tested_at=now,
                    last_sync_at=now,
                    last_error_code=None,
                    last_error_message=None,
                )
                session.add(row)
            else:
                row.provider_type = SITE_KNOWLEDGE_VECTOR_PROVIDER_ID
                row.display_name = f"{SITE_KNOWLEDGE_VECTOR_PROVIDER_NAME} Site Knowledge"
                row.enabled = True
                row.base_url = SITE_KNOWLEDGE_VECTOR_BASE_URL
                row.config_json = fixed_config
                row.status = "ready"
                row.source_role = "execution_source"
                row.metadata_json = {"managed_surface": "site_knowledge_vector_profile"}
                row.last_tested_at = now
                row.last_sync_at = now
                row.last_error_code = None
                row.last_error_message = None
                row.updated_at = now
            if credential is not None and str(credential).strip():
                row.secret_ciphertext = encrypt_provider_connection_secret(
                    resolved_credential,
                    settings=self.settings,
                )
            elif not row.secret_ciphertext:
                row.secret_ciphertext = encrypt_provider_connection_secret(
                    resolved_credential,
                    settings=self.settings,
                )

            self._disable_legacy_embedding_slots(session)
            if credential is not None and str(credential).strip():
                self._mark_reindex_required(
                    session,
                    reason="embedding_provider_changed",
                )
            session.commit()

        apply_provider_connection_runtime_settings(self.settings)
        result = self.get_profile()
        result["probe"] = probe
        return result

    def save_and_verify_vector_store(
        self,
        endpoint: str | None,
        token: str | None,
    ) -> dict[str, Any]:
        current = self._load_vector_store_connection()
        resolved_endpoint = _normalized_zilliz_endpoint(
            endpoint or (current.base_url if current is not None else "")
        )
        resolved_token = str(token or "").strip()
        if not resolved_token and current is not None:
            resolved_token = self._decrypt_credential(current)
        if not resolved_endpoint:
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.zilliz_endpoint_required",
                "Zilliz endpoint is required",
            )
        if not resolved_token:
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.zilliz_token_required",
                "Zilliz token is required",
            )

        probe = self._probe_vector_store(resolved_endpoint, resolved_token)
        now = datetime.now(UTC)
        lifecycle = self._next_vector_store_lifecycle(current, resolved_endpoint)
        fixed_config = {
            "provider_id": SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_ID,
            "kind": "vector_store_provider",
            "capability_ids": ["vector_store"],
            "runtime_profile_ids": ["site-knowledge.vector-store"],
            "uri": resolved_endpoint,
            "collection": SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
            "dimensions": SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
            "metric": SITE_KNOWLEDGE_VECTOR_METRIC,
            "site_knowledge_vector_store_profile_id": SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
            "site_knowledge_vector_store_probe_revision": (
                SITE_KNOWLEDGE_VECTOR_STORE_PROBE_REVISION
            ),
            "site_knowledge_vector_store_dimensions": SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
            "site_knowledge_vector_store_metric": SITE_KNOWLEDGE_VECTOR_METRIC,
            "site_knowledge_index_lifecycle": lifecycle,
        }
        with get_session(self.database_url) as session:
            row = session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID)
            if row is None:
                row = ProviderConnection(
                    connection_id=SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
                    provider_type="vector_store_provider",
                    display_name=f"{SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_NAME} Site Knowledge",
                    enabled=True,
                    base_url=resolved_endpoint,
                    config_json=fixed_config,
                    secret_ciphertext=None,
                    status="ready",
                    source_role="execution_source",
                    metadata_json={"managed_surface": "site_knowledge_vector_profile"},
                    last_tested_at=now,
                    last_sync_at=now,
                    last_error_code=None,
                    last_error_message=None,
                )
                session.add(row)
            else:
                row.provider_type = "vector_store_provider"
                row.display_name = (
                    f"{SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_NAME} Site Knowledge"
                )
                row.enabled = True
                row.base_url = resolved_endpoint
                row.config_json = fixed_config
                row.status = "ready"
                row.source_role = "execution_source"
                row.metadata_json = {"managed_surface": "site_knowledge_vector_profile"}
                row.last_tested_at = now
                row.last_sync_at = now
                row.last_error_code = None
                row.last_error_message = None
                row.updated_at = now
            if token is not None and str(token).strip():
                row.secret_ciphertext = encrypt_provider_connection_secret(
                    resolved_token,
                    settings=self.settings,
                )
            elif not row.secret_ciphertext:
                row.secret_ciphertext = encrypt_provider_connection_secret(
                    resolved_token,
                    settings=self.settings,
                )

            self._disable_legacy_vector_store_slots(session)
            session.commit()

        apply_provider_connection_runtime_settings(self.settings)
        result = self.get_profile()
        result["vector_store_probe"] = probe
        return result

    def rebuild_index(self) -> dict[str, Any]:
        """Copy the Cloud-owned compatible index into the verified fixed Zilliz space."""
        provider_connection = self._load_connection()
        vector_store_connection = self._load_vector_store_connection()
        provider = self._provider_state(provider_connection)
        vector_store = self._vector_store_state(vector_store_connection)
        if not provider["verified"] or not vector_store["verified"]:
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.rebuild_not_ready",
                "Embedding provider and Zilliz must be verified before rebuilding",
                status_code=409,
            )

        expected_space = self._embedding_space_id()
        with get_session(self.database_url) as session:
            chunk_count = int(
                session.scalar(select(func.count()).select_from(SiteKnowledgeChunk)) or 0
            )
            document_count = int(
                session.scalar(select(func.count()).select_from(SiteKnowledgeDocument)) or 0
            )
            site_ids = list(
                session.scalars(
                    select(SiteKnowledgeChunk.site_id)
                    .distinct()
                    .order_by(SiteKnowledgeChunk.site_id.asc())
                )
            )
            chunks = session.scalars(
                select(SiteKnowledgeChunk).order_by(
                    SiteKnowledgeChunk.site_id.asc(),
                    SiteKnowledgeChunk.id.asc(),
                )
            ).yield_per(500)

            for chunk in chunks:
                if str(chunk.embedding_model or "") != expected_space:
                    self._persist_lifecycle(
                        status="reindex_required",
                        reason="embedding_space_mismatch",
                        source_document_count=document_count,
                        source_chunk_count=chunk_count,
                        indexed_chunk_count=0,
                        last_error_code=(
                            "site_knowledge_vector_profile.embedding_space_mismatch"
                        ),
                    )
                    apply_provider_connection_runtime_settings(self.settings)
                    raise SiteKnowledgeVectorProfileAdminError(
                        "site_knowledge_vector_profile.embedding_space_mismatch",
                        "Stored chunks do not belong to the active embedding space",
                        status_code=409,
                    )
                try:
                    _validated_embedding(chunk.embedding_json)
                except SiteKnowledgeVectorProfileAdminError as error:
                    self._persist_lifecycle(
                        status="reindex_required",
                        reason="stored_embedding_invalid",
                        source_document_count=document_count,
                        source_chunk_count=chunk_count,
                        indexed_chunk_count=0,
                        last_error_code=error.error_code,
                    )
                    apply_provider_connection_runtime_settings(self.settings)
                    raise SiteKnowledgeVectorProfileAdminError(
                        error.error_code,
                        "Stored chunks are incompatible with the fixed vector profile",
                        status_code=409,
                    ) from error

        self._persist_lifecycle(
            status="rebuilding",
            reason="operator_requested",
            source_document_count=document_count,
            source_chunk_count=chunk_count,
            indexed_chunk_count=0,
        )
        try:
            backend_settings = self.settings.model_copy(deep=True)
            self._apply_verified_vector_store(backend_settings, vector_store_connection)
            backend = ZillizCloudSiteKnowledgeBackend(backend_settings)
            indexed = 0
            first_site_id = ""
            first_embedding: list[float] = []
            for site_id in site_ids:
                backend.delete_site_index(site_id)
                with get_session(self.database_url) as session:
                    site_chunks = session.scalars(
                        select(SiteKnowledgeChunk)
                        .where(SiteKnowledgeChunk.site_id == site_id)
                        .order_by(SiteKnowledgeChunk.id.asc())
                    ).yield_per(500)
                    batch: list[dict[str, Any]] = []
                    for chunk in site_chunks:
                        embedding = _validated_embedding(chunk.embedding_json)
                        if not first_embedding:
                            first_site_id = site_id
                            first_embedding = embedding
                        batch.append(self._zilliz_chunk_payload(chunk, embedding))
                        if len(batch) == 500:
                            backend.upsert_chunks(site_id=site_id, chunks=batch)
                            indexed += len(batch)
                            batch = []
                    if batch:
                        backend.upsert_chunks(site_id=site_id, chunks=batch)
                        indexed += len(batch)
            roundtrip_status = "not_applicable"
            if first_embedding:
                hits = backend.search(
                    site_id=first_site_id,
                    query_embedding=first_embedding,
                    post_types=[],
                    statuses=[],
                    source_types=[],
                    current_post_id=0,
                    limit=1,
                )
                if not hits:
                    raise SiteKnowledgeBackendError(
                        "site_knowledge.zilliz_roundtrip_failed",
                        "Zilliz round-trip validation returned no indexed chunk",
                    )
                roundtrip_status = "passed"
        except (SiteKnowledgeBackendError, SiteKnowledgeVectorProfileAdminError) as error:
            self._persist_lifecycle(
                status="failed",
                reason="zilliz_rebuild_failed",
                source_document_count=document_count,
                source_chunk_count=chunk_count,
                indexed_chunk_count=0,
                last_error_code=error.error_code,
            )
            apply_provider_connection_runtime_settings(self.settings)
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.rebuild_failed",
                "Zilliz index rebuild failed",
                status_code=502,
            ) from error

        self._persist_lifecycle(
            status="ready" if chunk_count else "empty",
            reason="rebuild_completed" if chunk_count else "no_source_chunks",
            source_document_count=document_count,
            source_chunk_count=chunk_count,
            indexed_chunk_count=indexed,
            roundtrip_status=roundtrip_status,
            last_reindexed_at=datetime.now(UTC),
        )
        apply_provider_connection_runtime_settings(self.settings)
        return self.get_profile()

    def _load_connection(self) -> ProviderConnection | None:
        with get_session(self.database_url) as session:
            return session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_CONNECTION_ID)

    def _load_vector_store_connection(self) -> ProviderConnection | None:
        with get_session(self.database_url) as session:
            return session.get(
                ProviderConnection,
                SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
            )

    def _probe_embedding(self, credential: str) -> dict[str, Any]:
        adapter = SiliconFlowProviderAdapter(
            base_url=SITE_KNOWLEDGE_VECTOR_BASE_URL,
            api_key=credential,
            timeout_seconds=float(self.settings.siliconflow_timeout_seconds),
            app_name=self.settings.project_name,
        )
        request = ProviderExecutionRequest(
            run_id="site-knowledge-vector-profile-probe",
            site_id="admin_site_knowledge_vector_profile",
            ability_name="npcink-cloud/site-knowledge-vector-profile-probe",
            profile_id=SITE_KNOWLEDGE_VECTOR_PROFILE_ID,
            execution_kind="embedding",
            model_id=SITE_KNOWLEDGE_VECTOR_MODEL_ID,
            instance_id="siliconflow-site-knowledge-vector-profile",
            endpoint_variant="embeddings",
            trace_id="site-knowledge-vector-profile-probe",
            input_payload={"text": "站点知识向量配置验证"},
            policy={"storage_mode": "no_store"},
            timeout_ms=max(1, int(float(self.settings.siliconflow_timeout_seconds) * 1000)),
        )
        try:
            result = adapter.execute(request)
        except ProviderExecutionError as error:
            raise SiteKnowledgeVectorProfileAdminError(
                error.error_code or "site_knowledge_vector_profile.probe_failed",
                "SiliconFlow embedding probe failed",
                status_code=502,
            ) from error
        except Exception as error:
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.probe_failed",
                "SiliconFlow embedding probe failed",
                status_code=502,
            ) from error

        reported_model_id = str(result.output.get("model_id") or "").strip()
        if reported_model_id != SITE_KNOWLEDGE_VECTOR_MODEL_ID:
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.model_mismatch",
                "Embedding probe returned an unexpected model",
                status_code=502,
            )
        vector = _validated_embedding(result.output.get("embedding"))
        return {
            "status": "ready",
            "provider_id": SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
            "model_id": SITE_KNOWLEDGE_VECTOR_MODEL_ID,
            "dimensions": len(vector),
            "metric": SITE_KNOWLEDGE_VECTOR_METRIC,
            "latency_ms": max(0, int(result.latency_ms)),
            "credential_value_exposure": "none",
        }

    def _probe_vector_store(self, endpoint: str, token: str) -> dict[str, Any]:
        probe_settings = self.settings.model_copy(deep=True)
        probe_settings.site_knowledge_vector_backend = SITE_KNOWLEDGE_VECTOR_PRODUCTION_BACKEND
        probe_settings.site_knowledge_zilliz_uri = endpoint
        probe_settings.site_knowledge_zilliz_token = token
        probe_settings.site_knowledge_zilliz_database = None
        probe_settings.site_knowledge_zilliz_collection = (
            SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION
        )
        probe_settings.site_knowledge_embedding_dimensions = (
            SITE_KNOWLEDGE_VECTOR_DIMENSIONS
        )
        probe_settings.site_knowledge_vector_metric_type = SITE_KNOWLEDGE_VECTOR_METRIC
        try:
            ZillizCloudSiteKnowledgeBackend(probe_settings)
        except SiteKnowledgeBackendError as error:
            if error.error_code == "site_knowledge.zilliz_sdk_missing":
                raise SiteKnowledgeVectorProfileAdminError(
                    "site_knowledge_vector_profile.zilliz_sdk_unavailable",
                    "Zilliz runtime SDK is unavailable on this Cloud instance",
                    status_code=503,
                ) from error
            if error.error_code == "site_knowledge.zilliz_schema_incompatible":
                raise SiteKnowledgeVectorProfileAdminError(
                    "site_knowledge_vector_profile.zilliz_schema_incompatible",
                    "Zilliz collection is incompatible with the fixed vector profile",
                    status_code=409,
                ) from error
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.zilliz_probe_failed",
                "Zilliz connection or collection initialization failed",
                status_code=502,
            ) from error
        except Exception as error:
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.zilliz_probe_failed",
                "Zilliz connection or collection initialization failed",
                status_code=502,
            ) from error
        return {
            "status": "ready",
            "provider_id": SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_ID,
            "collection": SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
            "dimensions": SITE_KNOWLEDGE_VECTOR_DIMENSIONS,
            "metric": SITE_KNOWLEDGE_VECTOR_METRIC,
            "credential_value_exposure": "none",
        }

    def _provider_state(self, row: ProviderConnection | None) -> dict[str, Any]:
        if row is None:
            return {
                "provider_id": SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
                "display_name": SITE_KNOWLEDGE_VECTOR_PROVIDER_NAME,
                "connection_id": SITE_KNOWLEDGE_VECTOR_CONNECTION_ID,
                "configured": False,
                "verified": False,
                "status": "not_configured",
                "last_tested_at": "",
            }
        config = row.config_json if isinstance(row.config_json, dict) else {}
        configured = bool(self._decrypt_credential(row))
        verified = bool(
            configured
            and row.enabled
            and row.status == "ready"
            and config.get("site_knowledge_profile_id") == SITE_KNOWLEDGE_VECTOR_PROFILE_ID
            and config.get("site_knowledge_probe_revision")
            == SITE_KNOWLEDGE_VECTOR_PROBE_REVISION
            and config.get("site_knowledge_model_id") == SITE_KNOWLEDGE_VECTOR_MODEL_ID
            and int(config.get("dimensions") or 0) == SITE_KNOWLEDGE_VECTOR_DIMENSIONS
            and str(config.get("metric") or "").upper() == SITE_KNOWLEDGE_VECTOR_METRIC
        )
        return {
            "provider_id": SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
            "display_name": SITE_KNOWLEDGE_VECTOR_PROVIDER_NAME,
            "connection_id": SITE_KNOWLEDGE_VECTOR_CONNECTION_ID,
            "configured": configured,
            "verified": verified,
            "status": (
                "ready" if verified else ("probe_required" if configured else "not_configured")
            ),
            "last_tested_at": _iso(row.last_tested_at),
        }

    def _vector_store_state(self, row: ProviderConnection | None) -> dict[str, Any]:
        config = row.config_json if row is not None and isinstance(row.config_json, dict) else {}
        endpoint = str(config.get("uri") or (row.base_url if row is not None else "") or "")
        token_configured = bool(row is not None and self._decrypt_credential(row))
        verified = bool(
            row is not None
            and row.enabled
            and row.status == "ready"
            and token_configured
            and endpoint
            and config.get("site_knowledge_vector_store_profile_id")
            == SITE_KNOWLEDGE_VECTOR_PROFILE_ID
            and config.get("site_knowledge_vector_store_probe_revision")
            == SITE_KNOWLEDGE_VECTOR_STORE_PROBE_REVISION
            and int(config.get("site_knowledge_vector_store_dimensions") or 0)
            == SITE_KNOWLEDGE_VECTOR_DIMENSIONS
            and str(config.get("site_knowledge_vector_store_metric") or "").upper()
            == SITE_KNOWLEDGE_VECTOR_METRIC
            and config.get("collection") == SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION
        )
        return {
            "provider_id": SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_ID,
            "display_name": SITE_KNOWLEDGE_VECTOR_STORE_PROVIDER_NAME,
            "connection_id": SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
            "configured": bool(endpoint and token_configured),
            "verified": verified,
            "status": "ready" if verified else "not_configured",
            "settings_owner": "cloud_admin",
            "endpoint": endpoint,
            "token_configured": token_configured,
            "collection": SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION,
            "last_tested_at": _iso(row.last_tested_at if row is not None else None),
        }

    def _validation_state(
        self,
        row: ProviderConnection | None,
        *,
        provider: dict[str, Any],
        vector_store: dict[str, Any],
        document_count: int,
        chunk_count: int,
        latest_search: SiteKnowledgeSearchMetric | None,
    ) -> dict[str, Any]:
        config = row.config_json if row is not None and isinstance(row.config_json, dict) else {}
        lifecycle_value = config.get("site_knowledge_index_lifecycle")
        lifecycle = lifecycle_value if isinstance(lifecycle_value, dict) else {}
        index_status = str(lifecycle.get("status") or "")
        if not index_status:
            if not vector_store["verified"]:
                index_status = "not_ready"
            elif chunk_count:
                index_status = "reindex_required"
            else:
                index_status = "empty"

        last_reindexed_at = str(lifecycle.get("last_reindexed_at") or "")
        retrieval_status = "pending"
        if latest_search is not None and last_reindexed_at:
            reindexed_at = _parse_iso(last_reindexed_at)
            searched_at = latest_search.finished_at or latest_search.created_at
            if reindexed_at is not None and searched_at is not None:
                if searched_at.tzinfo is None:
                    searched_at = searched_at.replace(tzinfo=UTC)
                if searched_at >= reindexed_at:
                    if latest_search.status != "succeeded":
                        retrieval_status = "failed"
                    elif latest_search.no_hit or latest_search.result_count <= 0:
                        retrieval_status = "no_hit"
                    else:
                        retrieval_status = "passed"

        return {
            "connection": {
                "status": (
                    "ready"
                    if provider["verified"] and vector_store["verified"]
                    else "not_ready"
                ),
                "provider_verified": bool(provider["verified"]),
                "vector_store_verified": bool(vector_store["verified"]),
            },
            "index": {
                "status": index_status,
                "reason": str(lifecycle.get("reason") or ""),
                "embedding_space_id": self._embedding_space_id(),
                "source_document_count": document_count,
                "source_chunk_count": chunk_count,
                "indexed_chunk_count": int(lifecycle.get("indexed_chunk_count") or 0),
                "roundtrip_status": str(lifecycle.get("roundtrip_status") or "pending"),
                "last_reindexed_at": last_reindexed_at,
                "last_error_code": str(lifecycle.get("last_error_code") or ""),
            },
            "retrieval": {
                "status": retrieval_status,
                "last_verified_at": (
                    _iso(latest_search.finished_at or latest_search.created_at)
                    if latest_search is not None and retrieval_status != "pending"
                    else ""
                ),
                "result_count": (
                    int(latest_search.result_count)
                    if latest_search is not None and retrieval_status != "pending"
                    else 0
                ),
                "top1_score": (
                    float(latest_search.top1_score)
                    if latest_search is not None and retrieval_status != "pending"
                    else 0.0
                ),
                "evidence_source": "site_knowledge_search_metric",
            },
        }

    def _next_vector_store_lifecycle(
        self,
        current: ProviderConnection | None,
        resolved_endpoint: str,
    ) -> dict[str, Any]:
        with get_session(self.database_url) as session:
            document_count = int(
                session.scalar(select(func.count()).select_from(SiteKnowledgeDocument)) or 0
            )
            chunk_count = int(
                session.scalar(select(func.count()).select_from(SiteKnowledgeChunk)) or 0
            )
        current_config = (
            current.config_json
            if current is not None and isinstance(current.config_json, dict)
            else {}
        )
        existing_value = current_config.get("site_knowledge_index_lifecycle")
        existing = existing_value if isinstance(existing_value, dict) else {}
        endpoint_changed = bool(current is not None and current.base_url != resolved_endpoint)
        if existing and not endpoint_changed:
            return existing
        return {
            "status": "reindex_required" if chunk_count else "empty",
            "reason": "vector_store_changed" if chunk_count else "no_source_chunks",
            "embedding_space_id": self._embedding_space_id(),
            "source_document_count": document_count,
            "source_chunk_count": chunk_count,
            "indexed_chunk_count": 0,
            "roundtrip_status": "pending",
            "last_reindexed_at": "",
            "last_error_code": "",
        }

    def _mark_reindex_required(self, session: Any, *, reason: str) -> None:
        row = session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID)
        if row is None:
            return
        chunk_count = int(
            session.scalar(select(func.count()).select_from(SiteKnowledgeChunk)) or 0
        )
        if not chunk_count:
            return
        document_count = int(
            session.scalar(select(func.count()).select_from(SiteKnowledgeDocument)) or 0
        )
        config = dict(row.config_json) if isinstance(row.config_json, dict) else {}
        config["site_knowledge_index_lifecycle"] = {
            "status": "reindex_required",
            "reason": reason,
            "embedding_space_id": self._embedding_space_id(),
            "source_document_count": document_count,
            "source_chunk_count": chunk_count,
            "indexed_chunk_count": 0,
            "roundtrip_status": "pending",
            "last_reindexed_at": "",
            "last_error_code": "",
        }
        row.config_json = config
        row.updated_at = datetime.now(UTC)

    def _persist_lifecycle(
        self,
        *,
        status: str,
        reason: str,
        source_document_count: int,
        source_chunk_count: int,
        indexed_chunk_count: int,
        roundtrip_status: str = "pending",
        last_reindexed_at: datetime | None = None,
        last_error_code: str = "",
    ) -> None:
        with get_session(self.database_url) as session:
            row = session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID)
            if row is None:
                raise SiteKnowledgeVectorProfileAdminError(
                    "site_knowledge_vector_profile.vector_store_not_configured",
                    "Zilliz is not configured",
                    status_code=409,
                )
            config = dict(row.config_json) if isinstance(row.config_json, dict) else {}
            config["site_knowledge_index_lifecycle"] = {
                "status": status,
                "reason": reason,
                "embedding_space_id": self._embedding_space_id(),
                "source_document_count": source_document_count,
                "source_chunk_count": source_chunk_count,
                "indexed_chunk_count": indexed_chunk_count,
                "roundtrip_status": roundtrip_status,
                "last_reindexed_at": _iso(last_reindexed_at),
                "last_error_code": last_error_code,
            }
            row.config_json = config
            row.updated_at = datetime.now(UTC)
            session.commit()

    @staticmethod
    def _embedding_space_id() -> str:
        return f"{SITE_KNOWLEDGE_VECTOR_PROVIDER_ID}:{SITE_KNOWLEDGE_VECTOR_MODEL_ID}"

    def _apply_verified_vector_store(
        self,
        settings: Settings,
        row: ProviderConnection | None,
    ) -> None:
        if row is None:
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.vector_store_not_configured",
                "Zilliz is not configured",
                status_code=409,
            )
        config = row.config_json if isinstance(row.config_json, dict) else {}
        settings.site_knowledge_vector_backend = SITE_KNOWLEDGE_VECTOR_PRODUCTION_BACKEND
        settings.site_knowledge_zilliz_uri = str(config.get("uri") or row.base_url or "")
        settings.site_knowledge_zilliz_token = self._decrypt_credential(row)
        settings.site_knowledge_zilliz_database = None
        settings.site_knowledge_zilliz_collection = SITE_KNOWLEDGE_VECTOR_STORE_COLLECTION
        settings.site_knowledge_embedding_dimensions = SITE_KNOWLEDGE_VECTOR_DIMENSIONS
        settings.site_knowledge_vector_metric_type = SITE_KNOWLEDGE_VECTOR_METRIC

    @staticmethod
    def _zilliz_chunk_payload(
        chunk: SiteKnowledgeChunk,
        embedding: list[float],
    ) -> dict[str, Any]:
        return {
            "post_id": chunk.post_id,
            "source_type": chunk.source_type,
            "source_id": chunk.source_id,
            "parent_post_id": chunk.parent_post_id,
            "chunk_index": chunk.chunk_index,
            "post_type": chunk.post_type,
            "post_status": chunk.post_status,
            "title": chunk.title,
            "url": chunk.url,
            "chunk_text": chunk.chunk_text,
            "embedding": embedding,
            "content_hash": chunk.content_hash,
            "indexed_at": _iso(chunk.indexed_at),
        }

    def _decrypt_credential(self, row: ProviderConnection) -> str:
        ciphertext = str(row.secret_ciphertext or "").strip()
        if not ciphertext:
            return ""
        try:
            return decrypt_provider_connection_secret(ciphertext, settings=self.settings)
        except RuntimeError:
            return ""

    @staticmethod
    def _disable_legacy_embedding_slots(session: Any) -> None:
        rows = list(
            session.scalars(
                select(ProviderConnection).where(
                    ProviderConnection.enabled.is_(True),
                    ProviderConnection.connection_id != SITE_KNOWLEDGE_VECTOR_CONNECTION_ID,
                )
            )
        )
        for row in rows:
            config = row.config_json if isinstance(row.config_json, dict) else {}
            kind = str(config.get("kind") or row.provider_type).strip().lower()
            if kind != "embedding_provider":
                continue
            row.enabled = False
            row.status = "disabled"

    @staticmethod
    def _disable_legacy_vector_store_slots(session: Any) -> None:
        rows = list(
            session.scalars(
                select(ProviderConnection).where(
                    ProviderConnection.enabled.is_(True),
                    ProviderConnection.connection_id
                    != SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
                )
            )
        )
        for row in rows:
            config = row.config_json if isinstance(row.config_json, dict) else {}
            kind = str(config.get("kind") or row.provider_type).strip().lower()
            if kind != "vector_store_provider":
                continue
            row.enabled = False
            row.status = "disabled"


def _validated_embedding(value: object) -> list[float]:
    if not isinstance(value, list) or not value:
        raise SiteKnowledgeVectorProfileAdminError(
            "site_knowledge_vector_profile.embedding_invalid",
            "Embedding probe returned an empty or invalid vector",
            status_code=502,
        )
    vector: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.embedding_invalid",
                "Embedding probe returned a non-numeric vector",
                status_code=502,
            )
        number = float(item)
        if not math.isfinite(number):
            raise SiteKnowledgeVectorProfileAdminError(
                "site_knowledge_vector_profile.embedding_invalid",
                "Embedding probe returned a non-finite vector",
                status_code=502,
            )
        vector.append(number)
    if len(vector) != SITE_KNOWLEDGE_VECTOR_DIMENSIONS:
        raise SiteKnowledgeVectorProfileAdminError(
            "site_knowledge_vector_profile.dimension_mismatch",
            (
                "Embedding probe returned "
                f"{len(vector)} dimensions; {SITE_KNOWLEDGE_VECTOR_DIMENSIONS} required"
            ),
            status_code=502,
        )
    return vector


def _normalized_zilliz_endpoint(value: object) -> str:
    candidate = str(value or "").strip()
    if not candidate:
        return ""
    parsed = urlsplit(candidate)
    hostname = str(parsed.hostname or "").lower()
    china_serverless_hostname = (
        ".serverless." in hostname
        and hostname.endswith(".cloud.zilliz.com.cn")
    )
    supported_hostname = (
        hostname.endswith(".zillizcloud.com")
        or hostname.endswith(".vectordb.zilliz.com.cn")
        or china_serverless_hostname
    )
    if (
        parsed.scheme.lower() != "https"
        or not supported_hostname
        or parsed.username
        or parsed.password
        or parsed.path.rstrip("/")
        or parsed.query
        or parsed.fragment
    ):
        raise SiteKnowledgeVectorProfileAdminError(
            "site_knowledge_vector_profile.zilliz_endpoint_invalid",
            "Zilliz endpoint must be a Zilliz Cloud HTTPS root URL",
        )
    return urlunsplit(("https", parsed.netloc, "", "", ""))


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
