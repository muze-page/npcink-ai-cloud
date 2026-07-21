from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings


class SiteKnowledgeBackendError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(slots=True)
class VectorSearchHit:
    post_id: int
    source_type: str
    source_id: int
    parent_post_id: int
    chunk_index: int
    post_type: str
    post_status: str
    title: str
    url: str
    chunk_text: str
    score: float


class SiteKnowledgeVectorBackend(Protocol):
    def delete_site_index(self, site_id: str) -> None: ...

    def delete_post_indexes(self, site_id: str, post_ids: list[int]) -> None: ...

    def upsert_chunks(
        self,
        *,
        site_id: str,
        chunks: list[dict[str, Any]],
    ) -> None: ...

    def search(
        self,
        *,
        site_id: str,
        query_embedding: list[float],
        post_types: list[str],
        statuses: list[str],
        source_types: list[str],
        current_post_id: int,
        limit: int,
    ) -> list[VectorSearchHit]: ...


def build_vector_backend(settings: Settings) -> SiteKnowledgeVectorBackend | None:
    backend = str(settings.site_knowledge_vector_backend or "postgres_json").strip()
    if backend == "postgres_json":
        return None
    if backend == "zilliz_cloud":
        return ZillizCloudSiteKnowledgeBackend(settings)
    raise SiteKnowledgeBackendError(
        "site_knowledge.vector_backend_unsupported",
        f"site knowledge vector backend '{backend}' is not supported",
    )


class ZillizCloudSiteKnowledgeBackend:
    def __init__(self, settings: Settings) -> None:
        try:
            from pymilvus import DataType, MilvusClient
        except ImportError as error:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_sdk_missing",
                "pymilvus is required when site_knowledge_vector_backend=zilliz_cloud",
            ) from error

        uri = str(settings.site_knowledge_zilliz_uri or "").strip()
        token = str(settings.site_knowledge_zilliz_token or "").strip()
        collection = str(settings.site_knowledge_zilliz_collection or "").strip()
        if not uri or not token or not collection:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_config_missing",
                "Zilliz uri, token, and collection are required for site knowledge",
            )

        kwargs: dict[str, Any] = {
            "uri": uri,
            "token": token,
            "timeout": float(settings.site_knowledge_zilliz_timeout_seconds),
        }
        database = str(settings.site_knowledge_zilliz_database or "").strip()
        if database:
            kwargs["db_name"] = database

        self.client = MilvusClient(**kwargs)
        self.data_type = DataType
        self.collection = collection
        self.dimension = int(settings.site_knowledge_embedding_dimensions)
        self.metric_type = str(settings.site_knowledge_vector_metric_type or "COSINE").upper()
        self._ensure_collection()

    def delete_site_index(self, site_id: str) -> None:
        self._delete(expr=f'site_id == "{_escape_expr_string(site_id)}"')

    def delete_post_indexes(self, site_id: str, post_ids: list[int]) -> None:
        normalized_post_ids = [post_id for post_id in post_ids if post_id > 0]
        if not normalized_post_ids:
            return
        post_ids_expr = ", ".join(str(post_id) for post_id in normalized_post_ids)
        self._delete(
            expr=(f'site_id == "{_escape_expr_string(site_id)}" and post_id in [{post_ids_expr}]')
        )

    def upsert_chunks(
        self,
        *,
        site_id: str,
        chunks: list[dict[str, Any]],
    ) -> None:
        if not chunks:
            return
        rows = []
        for chunk in chunks:
            post_id = int(chunk["post_id"])
            source_type = str(chunk.get("source_type") or chunk["post_type"])
            source_id = int(chunk.get("source_id") or post_id)
            parent_post_id = int(chunk.get("parent_post_id") or post_id)
            chunk_index = int(chunk["chunk_index"])
            rows.append(
                {
                    "id": f"{site_id}:{source_type}:{source_id}:{chunk_index}",
                    "vector": [float(value) for value in list(chunk["embedding"])],
                    "site_id": site_id,
                    "post_id": post_id,
                    "source_type": source_type,
                    "source_id": source_id,
                    "parent_post_id": parent_post_id,
                    "chunk_index": chunk_index,
                    "post_type": str(chunk["post_type"]),
                    "post_status": str(chunk["post_status"]),
                    "title": str(chunk["title"]),
                    "url": str(chunk["url"]),
                    "chunk_text": str(chunk["chunk_text"]),
                    "content_hash": str(chunk["content_hash"]),
                    "indexed_at": str(chunk.get("indexed_at") or ""),
                }
            )
        try:
            self.client.upsert(collection_name=self.collection, data=rows)
        except Exception as error:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_upsert_failed",
                "Zilliz site knowledge upsert failed",
            ) from error

    def search(
        self,
        *,
        site_id: str,
        query_embedding: list[float],
        post_types: list[str],
        statuses: list[str],
        source_types: list[str],
        current_post_id: int,
        limit: int,
    ) -> list[VectorSearchHit]:
        filters = [f'site_id == "{_escape_expr_string(site_id)}"']
        if post_types:
            filters.append(
                "post_type in ["
                + ", ".join(f'"{_escape_expr_string(item)}"' for item in post_types)
                + "]"
            )
        if statuses:
            filters.append(
                "post_status in ["
                + ", ".join(f'"{_escape_expr_string(item)}"' for item in statuses)
                + "]"
            )
        if source_types:
            filters.append(
                "source_type in ["
                + ", ".join(f'"{_escape_expr_string(item)}"' for item in source_types)
                + "]"
            )
        if current_post_id > 0:
            filters.append(f"post_id != {current_post_id}")

        try:
            result = self.client.search(
                collection_name=self.collection,
                data=[[float(value) for value in query_embedding]],
                filter=" and ".join(filters),
                limit=max(1, limit),
                output_fields=[
                    "post_id",
                    "source_type",
                    "source_id",
                    "parent_post_id",
                    "chunk_index",
                    "post_type",
                    "post_status",
                    "title",
                    "url",
                    "chunk_text",
                ],
            )
        except Exception as error:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_search_failed",
                "Zilliz site knowledge search failed",
            ) from error

        return _parse_zilliz_search_hits(result)

    def _ensure_collection(self) -> None:
        try:
            if self.client.has_collection(self.collection):
                self._validate_collection_schema()
                return
            schema = self.client.create_schema(
                auto_id=False,
                enable_dynamic_field=False,
            )
            schema.add_field("id", self.data_type.VARCHAR, is_primary=True, max_length=512)
            schema.add_field("vector", self.data_type.FLOAT_VECTOR, dim=self.dimension)
            schema.add_field("site_id", self.data_type.VARCHAR, max_length=191)
            schema.add_field("post_id", self.data_type.INT64)
            schema.add_field("source_type", self.data_type.VARCHAR, max_length=32)
            schema.add_field("source_id", self.data_type.INT64)
            schema.add_field("parent_post_id", self.data_type.INT64)
            schema.add_field("chunk_index", self.data_type.INT64)
            schema.add_field("post_type", self.data_type.VARCHAR, max_length=64)
            schema.add_field("post_status", self.data_type.VARCHAR, max_length=64)
            schema.add_field("title", self.data_type.VARCHAR, max_length=1024)
            schema.add_field("url", self.data_type.VARCHAR, max_length=2048)
            schema.add_field("chunk_text", self.data_type.VARCHAR, max_length=4096)
            schema.add_field("content_hash", self.data_type.VARCHAR, max_length=191)
            schema.add_field("indexed_at", self.data_type.VARCHAR, max_length=64)

            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="vector",
                index_type="AUTOINDEX",
                metric_type=self.metric_type,
            )
            self.client.create_collection(
                collection_name=self.collection,
                schema=schema,
                index_params=index_params,
            )
        except Exception as error:
            if isinstance(error, SiteKnowledgeBackendError):
                raise
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_collection_failed",
                "Zilliz site knowledge collection is not ready",
            ) from error

    def _validate_collection_schema(self) -> None:
        description = self.client.describe_collection(self.collection)
        fields_value = description.get("fields") if isinstance(description, dict) else []
        fields = fields_value if isinstance(fields_value, list) else []
        fields_by_name = {
            str(field.get("name") or ""): field for field in fields if isinstance(field, dict)
        }
        id_field = fields_by_name.get("id") or {}
        vector_field = fields_by_name.get("vector") or {}
        required_fields = {
            "id",
            "vector",
            "site_id",
            "post_id",
            "source_type",
            "source_id",
            "parent_post_id",
            "chunk_index",
            "post_type",
            "post_status",
            "title",
            "url",
            "chunk_text",
            "content_hash",
            "indexed_at",
        }
        missing_fields = sorted(field for field in required_fields if field not in fields_by_name)
        if missing_fields:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_schema_incompatible",
                "Zilliz site knowledge collection is missing source fields",
            )
        if id_field.get("type") != self.data_type.VARCHAR:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_schema_incompatible",
                "Zilliz site knowledge collection must use a varchar primary id",
            )
        if vector_field.get("type") != self.data_type.FLOAT_VECTOR:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_schema_incompatible",
                "Zilliz site knowledge collection must include a float vector field",
            )
        params = vector_field.get("params")
        dimension = _coerce_int(
            params.get("dim") if isinstance(params, dict) else None,
            default=0,
        )
        if dimension != self.dimension:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_schema_incompatible",
                "Zilliz site knowledge collection dimensions do not match configuration",
            )
        index_names_value = self.client.list_indexes(
            collection_name=self.collection,
            field_name="vector",
        )
        index_names = index_names_value if isinstance(index_names_value, list) else []
        metrics: list[str] = []
        for index_name in index_names:
            description = self.client.describe_index(
                collection_name=self.collection,
                index_name=str(index_name),
            )
            if not isinstance(description, dict):
                continue
            params = description.get("params")
            metric = description.get("metric_type")
            if not metric and isinstance(params, dict):
                metric = params.get("metric_type")
            if metric:
                metrics.append(str(metric).upper())
        if self.metric_type not in metrics:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_schema_incompatible",
                "Zilliz site knowledge collection metric does not match configuration",
            )

    def _delete(self, *, expr: str) -> None:
        try:
            self.client.delete(collection_name=self.collection, filter=expr)
        except Exception as error:
            raise SiteKnowledgeBackendError(
                "site_knowledge.zilliz_delete_failed",
                "Zilliz site knowledge delete failed",
            ) from error


def _parse_zilliz_search_hits(result: Any) -> list[VectorSearchHit]:
    first_result = result[0] if isinstance(result, list) and result else []
    hits = first_result if isinstance(first_result, list) else []
    parsed: list[VectorSearchHit] = []
    for hit in hits:
        entity = _extract_hit_entity(hit)
        parsed.append(
            VectorSearchHit(
                post_id=_coerce_int(entity.get("post_id"), default=0),
                source_type=str(entity.get("source_type") or ""),
                source_id=_coerce_int(entity.get("source_id"), default=0),
                parent_post_id=_coerce_int(entity.get("parent_post_id"), default=0),
                chunk_index=_coerce_int(entity.get("chunk_index"), default=0),
                post_type=str(entity.get("post_type") or ""),
                post_status=str(entity.get("post_status") or ""),
                title=str(entity.get("title") or ""),
                url=str(entity.get("url") or ""),
                chunk_text=str(entity.get("chunk_text") or ""),
                score=_extract_hit_score(hit),
            )
        )
    return [hit for hit in parsed if hit.post_id > 0 and hit.chunk_text]


def _extract_hit_entity(hit: Any) -> dict[str, Any]:
    if isinstance(hit, dict):
        entity = hit.get("entity")
        if isinstance(entity, dict):
            return entity
        return hit
    entity = getattr(hit, "entity", None)
    if isinstance(entity, dict):
        return entity
    if hasattr(hit, "get"):
        maybe_entity = hit.get("entity")
        if isinstance(maybe_entity, dict):
            return maybe_entity
    return {}


def _extract_hit_score(hit: Any) -> float:
    for key in ("score", "distance"):
        if isinstance(hit, dict) and key in hit:
            return _normalize_score(hit[key])
        value = getattr(hit, key, None)
        if value is not None:
            return _normalize_score(value)
        if hasattr(hit, "get"):
            value = hit.get(key)
            if value is not None:
                return _normalize_score(value)
    return 0.0


def _normalize_score(value: Any) -> float:
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, normalized))


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _escape_expr_string(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')
