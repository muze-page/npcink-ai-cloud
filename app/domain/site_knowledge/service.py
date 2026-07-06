from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.providers.base import (
    ProviderAdapter,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.core.config import Settings, get_settings
from app.domain.agent_workflow_metadata import (
    SITE_KNOWLEDGE_SUGGESTION_AGENT_ID,
    get_agent_handoff_metadata,
)
from app.domain.site_knowledge.backends import (
    SiteKnowledgeBackendError,
    SiteKnowledgeVectorBackend,
    VectorSearchHit,
    build_vector_backend,
)
from app.domain.site_knowledge.contracts import (
    ALLOWED_SEARCH_INTENTS,
    ALLOWED_SYNC_MODES,
    PUBLIC_COMMENT_STATUSES,
    PUBLIC_POST_STATUSES,
    PUBLIC_POST_TYPES,
    PUBLIC_SOURCE_TYPES,
    SITE_KNOWLEDGE_CONTRACTS,
    SITE_KNOWLEDGE_SEARCH_ABILITY,
    SITE_KNOWLEDGE_STATUS_ABILITY,
    SITE_KNOWLEDGE_SYNC_ABILITY,
    SiteKnowledgeContractViolation,
    coerce_positive_int,
    validate_site_knowledge_runtime_contract,
)
from app.domain.site_knowledge.embedding import (
    cosine_similarity,
    embed_text_deterministic,
)
from app.domain.site_knowledge.repository import SiteKnowledgeRepository
from app.domain.site_knowledge.rerankers import (
    SiteKnowledgeReranker,
    SiteKnowledgeRerankError,
    build_site_knowledge_reranker,
)

MAX_CHUNK_CHARS = 900
CHUNK_OVERLAP_CHARS = 120
MAX_DOCUMENT_CONTENT_CHARS = 50000
MAX_CHUNKS_PER_DOCUMENT = 64
MAX_SEARCH_QUERY_CHARS = 500
MAX_SEARCH_FILTER_ITEMS = 20
MAX_SYNC_POST_IDS = 1000
MAX_FALLBACK_SEARCH_CHUNKS = 5000
DEFAULT_EVIDENCE_MIN_SCORE = 0.45
DEFAULT_REQUIRED_EVIDENCE_SOURCES = 1
ALLOWED_NO_HIT_POLICIES = frozenset({"abstain", "fallback_to_general", "return_empty"})
ProgressCallback = Callable[[dict[str, Any]], None]
EmbeddingUsageCallback = Callable[
    [str, ProviderExecutionRequest, ProviderExecutionResult | None, ProviderExecutionError | None],
    None,
]

STYLE_SCRIPT_BLOCK_PATTERN = re.compile(
    r"<(?:style|script)\b[^>]*>.*?</(?:style|script)>",
    flags=re.IGNORECASE | re.DOTALL,
)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
CSS_RULE_PATTERN = re.compile(
    r"(?:@[a-z][a-z0-9_-]*\s+[^{]{0,160}|[.#]?[a-z_][a-z0-9_-]*)\s*\{[^{}]{0,1200}\}",
    flags=re.IGNORECASE,
)


class SiteKnowledgeService:
    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
        providers: dict[str, ProviderAdapter] | None = None,
        progress_callback: ProgressCallback | None = None,
        embedding_usage_callback: EmbeddingUsageCallback | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.providers = providers or {}
        self.progress_callback = progress_callback
        self.embedding_usage_callback = embedding_usage_callback
        self.repository = SiteKnowledgeRepository(session)
        self.vector_backend = build_vector_backend(self.settings)
        self.reranker = build_site_knowledge_reranker(self.settings)
        self.embedding_provider_id = str(
            self.settings.site_knowledge_embedding_provider or "deterministic"
        )
        self.embedding_model = str(self.settings.site_knowledge_embedding_model or "BAAI/bge-m3")
        self.embedding_dimensions = int(self.settings.site_knowledge_embedding_dimensions)

    def execute(
        self,
        *,
        site_id: str,
        ability_name: str,
        contract_version: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        validate_site_knowledge_runtime_contract(
            ability_name=ability_name,
            contract_version=contract_version,
            input_payload=input_payload,
        )
        if ability_name == SITE_KNOWLEDGE_SYNC_ABILITY:
            return self.sync(site_id=site_id, input_payload=input_payload, run_id=run_id)
        if ability_name == SITE_KNOWLEDGE_STATUS_ABILITY:
            return self.status(site_id=site_id, input_payload=input_payload)
        if ability_name == SITE_KNOWLEDGE_SEARCH_ABILITY:
            return self.search(site_id=site_id, input_payload=input_payload, run_id=run_id)
        raise SiteKnowledgeContractViolation(
            "site_knowledge.unknown_ability",
            "site knowledge ability_name is not supported",
        )

    def sync(
        self,
        *,
        site_id: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        sync_mode = str(input_payload.get("sync_mode") or "refresh").strip().lower()
        if sync_mode not in ALLOWED_SYNC_MODES:
            raise SiteKnowledgeContractViolation(
                "site_knowledge.invalid_sync_mode",
                "site knowledge sync_mode must be refresh, rebuild, or delete",
            )
        post_ids = _coerce_post_ids(input_payload.get("post_ids"))
        documents = input_payload.get("documents")
        documents = documents if isinstance(documents, list) else []
        comments = input_payload.get("comments")
        comments = comments if isinstance(comments, list) else []
        total_documents = len(documents) + len(comments)

        deleted_entries = 0
        self._emit_sync_progress(
            status="running",
            stage="preparing",
            message="Preparing public site content for indexing.",
            sync_mode=sync_mode,
            total_documents=total_documents,
        )
        if sync_mode == "delete":
            self._emit_sync_progress(
                status="running",
                stage="cleaning",
                message="Removing existing Cloud index entries.",
                sync_mode=sync_mode,
                total_documents=total_documents,
            )
            if self.vector_backend is not None:
                if post_ids:
                    self.vector_backend.delete_post_indexes(site_id, post_ids)
                else:
                    self.vector_backend.delete_site_index(site_id)
            deleted_entries = (
                self.repository.delete_post_indexes(site_id, post_ids)
                if post_ids
                else self.repository.delete_site_index(site_id)
            )
            self._emit_sync_progress(
                status="completed",
                stage="completed",
                message="Index cleanup completed.",
                sync_mode=sync_mode,
                total_documents=total_documents,
                deleted_entries=deleted_entries,
                percent=100,
            )
            return self._sync_response(
                status="completed",
                run_id=run_id,
                sync_mode=sync_mode,
                accepted_documents=0,
                indexed_documents=0,
                indexed_chunks=0,
                failed_documents=0,
                deleted_entries=deleted_entries,
                progress=self._sync_progress(
                    status="completed",
                    stage="completed",
                    message="Index cleanup completed.",
                    sync_mode=sync_mode,
                    total_documents=total_documents,
                    deleted_entries=deleted_entries,
                    percent=100,
                ),
            )

        if sync_mode == "rebuild":
            self._emit_sync_progress(
                status="running",
                stage="cleaning",
                message="Clearing old site index before rebuilding.",
                sync_mode=sync_mode,
                total_documents=total_documents,
            )
            if self.vector_backend is not None:
                if post_ids:
                    self.vector_backend.delete_post_indexes(site_id, post_ids)
                else:
                    self.vector_backend.delete_site_index(site_id)
            deleted_entries = (
                self.repository.delete_post_indexes(site_id, post_ids)
                if post_ids
                else self.repository.delete_site_index(site_id)
            )
        elif sync_mode == "refresh" and post_ids:
            self._emit_sync_progress(
                status="running",
                stage="cleaning",
                message="Clearing selected old index entries before refreshing.",
                sync_mode=sync_mode,
                total_documents=total_documents,
            )
            if self.vector_backend is not None:
                self.vector_backend.delete_post_indexes(site_id, post_ids)
            deleted_entries = self.repository.delete_post_indexes(site_id, post_ids)

        accepted_documents = 0
        indexed_documents = 0
        indexed_chunks = 0
        failed_documents = 0
        truncated_documents = 0
        skipped_documents = 0
        skipped_due_to_quota = 0
        processed_documents = 0
        site_document_count = self.repository.count_documents(site_id)
        site_chunk_count = self.repository.count_chunks(site_id)
        remaining_run_documents = int(self.settings.site_knowledge_max_sync_documents_per_run)
        remaining_run_chunks = int(self.settings.site_knowledge_max_sync_chunks_per_run)
        quota_limited = False

        for raw_document in [*documents, *comments]:
            document = raw_document if isinstance(raw_document, dict) else {}
            self._emit_sync_progress(
                status="running",
                stage="embedding",
                message="Chunking content and creating embeddings.",
                sync_mode=sync_mode,
                processed_documents=processed_documents,
                total_documents=total_documents,
                accepted_documents=accepted_documents,
                indexed_documents=indexed_documents,
                indexed_chunks=indexed_chunks,
                failed_documents=failed_documents,
                skipped_documents=skipped_documents,
                skipped_due_to_quota=skipped_due_to_quota,
                deleted_entries=deleted_entries,
            )
            normalized = (
                _normalize_public_comment(document)
                if _looks_like_comment_document(document)
                else _normalize_public_document(document)
            )
            if normalized is None:
                failed_documents += 1
                processed_documents += 1
                continue
            if (
                normalized["source_type"] == "comment"
                and not self.settings.site_knowledge_comments_enabled
            ):
                skipped_documents += 1
                processed_documents += 1
                continue
            source_type = str(normalized["source_type"])
            source_id = _coerce_int(normalized.get("source_id"), default=0)
            existing_document = self.repository.document_exists(
                site_id=site_id,
                source_type=source_type,
                source_id=source_id,
            )
            existing_chunks = self.repository.count_chunks_for_source(
                site_id=site_id,
                source_type=source_type,
                source_id=source_id,
            )
            if remaining_run_documents <= 0:
                skipped_documents += 1
                skipped_due_to_quota += 1
                quota_limited = True
                processed_documents += 1
                continue
            if not existing_document and site_document_count >= int(
                self.settings.site_knowledge_max_indexed_documents_per_site
            ):
                skipped_documents += 1
                skipped_due_to_quota += 1
                quota_limited = True
                processed_documents += 1
                continue
            available_site_chunks = int(
                self.settings.site_knowledge_max_indexed_chunks_per_site
            ) - max(0, site_chunk_count - existing_chunks)
            allowed_chunks = min(
                MAX_CHUNKS_PER_DOCUMENT,
                remaining_run_chunks,
                max(0, available_site_chunks),
            )
            if allowed_chunks <= 0:
                skipped_documents += 1
                skipped_due_to_quota += 1
                quota_limited = True
                processed_documents += 1
                continue
            accepted_documents += 1
            chunks = self._build_chunks(
                normalized,
                site_id=site_id,
                run_id=run_id,
                ability_name=SITE_KNOWLEDGE_SYNC_ABILITY,
                max_chunks=allowed_chunks,
            )
            if not chunks:
                failed_documents += 1
                processed_documents += 1
                continue
            if allowed_chunks < MAX_CHUNKS_PER_DOCUMENT and _chunks_include_limit_truncation(
                chunks
            ):
                quota_limited = True
            document_truncated = bool(
                normalized.get("content_truncated")
            ) or _chunks_include_limit_truncation(chunks)
            if document_truncated:
                truncated_documents += 1
            self._emit_sync_progress(
                status="running",
                stage="writing",
                message="Writing chunks to the Cloud index.",
                sync_mode=sync_mode,
                processed_documents=processed_documents,
                total_documents=total_documents,
                accepted_documents=accepted_documents,
                indexed_documents=indexed_documents,
                indexed_chunks=indexed_chunks,
                failed_documents=failed_documents,
                skipped_documents=skipped_documents,
                skipped_due_to_quota=skipped_due_to_quota,
                deleted_entries=deleted_entries,
            )
            if self.vector_backend is not None:
                self.vector_backend.upsert_chunks(
                    site_id=site_id,
                    chunks=[
                        {
                            **chunk,
                            "post_id": _coerce_int(normalized.get("post_id"), default=0),
                            "source_type": str(normalized["source_type"]),
                            "source_id": _coerce_int(normalized.get("source_id"), default=0),
                            "parent_post_id": _coerce_int(
                                normalized.get("parent_post_id"), default=0
                            ),
                            "post_type": str(normalized["post_type"]),
                            "post_status": str(normalized["post_status"]),
                            "title": str(normalized["title"]),
                            "url": str(normalized["url"]),
                            "content_hash": str(normalized["content_hash"]),
                        }
                        for chunk in chunks
                    ],
                )
            self.repository.upsert_document_with_chunks(
                site_id=site_id,
                post_id=_coerce_int(normalized.get("post_id"), default=0),
                source_type=str(normalized["source_type"]),
                source_id=_coerce_int(normalized.get("source_id"), default=0),
                parent_post_id=(
                    _coerce_int(normalized.get("parent_post_id"), default=0)
                    if normalized.get("parent_post_id") is not None
                    else None
                ),
                post_type=str(normalized["post_type"]),
                post_status=str(normalized["post_status"]),
                title=str(normalized["title"]),
                url=str(normalized["url"]),
                modified_gmt=str(normalized["modified_gmt"]),
                content_hash=str(normalized["content_hash"]),
                run_id=run_id,
                metadata={
                    "content_truncated": bool(normalized.get("content_truncated")),
                    "chunk_limit_truncated": _chunks_include_limit_truncation(chunks),
                    "truncated": document_truncated,
                    "source_content_chars": _coerce_int(
                        normalized.get("source_content_chars"), default=0
                    ),
                    "indexed_content_chars": _coerce_int(
                        normalized.get("indexed_content_chars"), default=0
                    ),
                    "max_content_chars": MAX_DOCUMENT_CONTENT_CHARS,
                    "chunk_count": len(chunks),
                    "max_chunks": MAX_CHUNKS_PER_DOCUMENT,
                    "effective_max_chunks": allowed_chunks,
                    "quota_limited": bool(quota_limited),
                },
                chunks=chunks,
            )
            indexed_documents += 1
            indexed_chunks += len(chunks)
            remaining_run_documents -= 1
            remaining_run_chunks = max(0, remaining_run_chunks - len(chunks))
            if not existing_document:
                site_document_count += 1
            site_chunk_count = max(0, site_chunk_count - existing_chunks) + len(chunks)
            processed_documents += 1
            self._emit_sync_progress(
                status="running",
                stage="embedding",
                message="Indexing is still running.",
                sync_mode=sync_mode,
                processed_documents=processed_documents,
                total_documents=total_documents,
                accepted_documents=accepted_documents,
                indexed_documents=indexed_documents,
                indexed_chunks=indexed_chunks,
                failed_documents=failed_documents,
                skipped_documents=skipped_documents,
                skipped_due_to_quota=skipped_due_to_quota,
                deleted_entries=deleted_entries,
            )

        progress = self._sync_progress(
            status="completed",
            stage="limited" if quota_limited else "completed",
            message=(
                "Indexing completed with quota limits; remaining content will need later batches."
                if quota_limited
                else "Index is ready for search."
            ),
            sync_mode=sync_mode,
            processed_documents=processed_documents,
            total_documents=total_documents,
            accepted_documents=accepted_documents,
            indexed_documents=indexed_documents,
            indexed_chunks=indexed_chunks,
            failed_documents=failed_documents,
            skipped_documents=skipped_documents,
            skipped_due_to_quota=skipped_due_to_quota,
            deleted_entries=deleted_entries,
            percent=100,
        )
        self._emit_sync_progress(**progress)

        return self._sync_response(
            status="completed",
            run_id=run_id,
            sync_mode=sync_mode,
            accepted_documents=accepted_documents,
            indexed_documents=indexed_documents,
            indexed_chunks=indexed_chunks,
            failed_documents=failed_documents,
            truncated_documents=truncated_documents,
            skipped_documents=skipped_documents,
            skipped_due_to_quota=skipped_due_to_quota,
            deleted_entries=deleted_entries,
            progress=progress,
            quota=self._quota_snapshot(
                indexed_posts=self.repository.count_documents(site_id),
                indexed_chunks=self.repository.count_chunks(site_id),
                skipped_documents=skipped_documents,
                skipped_due_to_quota=skipped_due_to_quota,
            ),
        )

    def status(self, *, site_id: str, input_payload: dict[str, Any]) -> dict[str, Any]:
        include_coverage = bool(input_payload.get("include_coverage"))
        indexed_posts = self.repository.count_documents(site_id)
        indexed_chunks = self.repository.count_chunks(site_id)
        last_sync_at = self.repository.last_sync_at(site_id)
        active_run = self.repository.latest_active_sync(site_id)

        status = "ready" if indexed_chunks > 0 else "empty"
        if active_run is not None:
            status = "syncing"
        elif indexed_chunks == 0 and self.repository.latest_failed_sync(site_id) is not None:
            status = "failed"

        coverage = {
            "indexed_posts": indexed_posts,
            "indexed_chunks": indexed_chunks,
            "truncated_documents": self.repository.count_truncated_documents(site_id),
            "last_sync_at": _serialize_datetime(last_sync_at),
            "has_stale_content": False,
            "post_type_coverage": {},
            "source_type_coverage": {},
            "comments_enabled": bool(self.settings.site_knowledge_comments_enabled),
        }
        coverage["quota"] = self._quota_snapshot(
            indexed_posts=indexed_posts,
            indexed_chunks=indexed_chunks,
        )
        if include_coverage:
            coverage["post_type_coverage"] = {
                post_type: 1.0 for post_type in sorted(self.repository.post_type_counts(site_id))
            }
            coverage["source_type_coverage"] = {
                source_type: 1.0
                for source_type in sorted(self.repository.source_type_counts(site_id))
            }

        progress = self._status_progress(
            status=status,
            coverage=coverage,
            active_run=active_run,
        )

        return {
            "artifact_type": "site_knowledge_status",
            "composition_role": "site_knowledge_status",
            "contract_version": SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_STATUS_ABILITY],
            "status": status,
            "coverage": coverage,
            "progress": progress,
            "active_run": _serialize_active_run(active_run) if active_run is not None else {},
            "ownership": _site_knowledge_ownership_contract(),
            "truth_boundaries": _site_knowledge_truth_boundaries(),
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }

    def search(
        self,
        *,
        site_id: str,
        input_payload: dict[str, Any],
        run_id: str,
    ) -> dict[str, Any]:
        query = _normalize_search_query(input_payload.get("query"))
        if not query:
            raise SiteKnowledgeContractViolation(
                "site_knowledge.query_required",
                "site knowledge search query is required",
            )
        intent = str(input_payload.get("intent") or "site_search").strip()
        if intent not in ALLOWED_SEARCH_INTENTS:
            intent = "site_search"
        max_results = coerce_positive_int(
            input_payload.get("max_results"),
            default=8,
            maximum=20,
        )
        evidence_policy = _resolve_evidence_policy(input_payload.get("evidence_policy"))
        filters = input_payload.get("filters")
        filters = filters if isinstance(filters, dict) else {}
        post_types = _filter_string_list(filters.get("post_types"), allowed=PUBLIC_POST_TYPES)
        statuses = _filter_string_list(filters.get("status"), allowed=PUBLIC_POST_STATUSES)
        source_types = _filter_string_list(filters.get("source_types"), allowed=PUBLIC_SOURCE_TYPES)
        if not source_types:
            source_types = ["post", "page"]
        if "comment" in source_types and self.settings.site_knowledge_comments_enabled:
            post_types = [*post_types, "comment"] if "comment" not in post_types else post_types
        else:
            source_types = [source_type for source_type in source_types if source_type != "comment"]
        current_post_id = _coerce_int(input_payload.get("current_post_id"), default=0)

        query_embedding = self._embed_text(
            query,
            site_id=site_id,
            run_id=run_id,
            ability_name=SITE_KNOWLEDGE_SEARCH_ABILITY,
        )
        results = self._search_vector_backend(
            site_id=site_id,
            query_embedding=query_embedding,
            post_types=post_types,
            statuses=statuses or ["publish"],
            source_types=source_types,
            current_post_id=current_post_id,
            max_results=max_results,
            intent=intent,
            query=query,
        )
        if results is not None:
            results, rerank = self._prepare_search_results(
                query=query,
                results=results,
                evidence_policy=evidence_policy,
                max_results=max_results,
            )
            workflow_support = _workflow_support_for_intent(intent)
            evidence_gate = _evidence_gate(results, evidence_policy)
            return {
                "artifact_type": "site_knowledge_results",
                "composition_role": "site_knowledge_context",
                "status": "ready",
                "intent": intent,
                "workflow_support": workflow_support,
                "agent_handoff": _agent_handoff_for_search(
                    intent=intent,
                    workflow_support=workflow_support,
                    evidence_gate=evidence_gate,
                    results=results,
                ),
                "evidence_gate": evidence_gate,
                "rerank": rerank,
                "results": results,
                "write_posture": "suggestion_only",
                "direct_wordpress_write": False,
            }

        scored = []
        for chunk in self.repository.list_search_chunks(
            site_id=site_id,
            post_types=post_types,
            statuses=statuses or ["publish"],
            source_types=source_types,
            current_post_id=current_post_id,
            limit=MAX_FALLBACK_SEARCH_CHUNKS,
        ):
            embedding = chunk.embedding_json if isinstance(chunk.embedding_json, list) else []
            score = cosine_similarity(query_embedding, [float(value) for value in embedding])
            lexical_bonus = _lexical_bonus(query, chunk.chunk_text, chunk.title)
            scored.append((min(1.0, score + lexical_bonus), chunk))

        scored.sort(key=lambda item: (-item[0], item[1].post_id, item[1].chunk_index))
        results = [
            _serialize_search_result(
                post_id=chunk.post_id,
                source_type=chunk.source_type,
                source_id=chunk.source_id,
                parent_post_id=chunk.parent_post_id or 0,
                title=chunk.title,
                url=chunk.url,
                chunk_text=chunk.chunk_text,
                score=score,
                intent=intent,
                query=query,
            )
            for score, chunk in scored
        ]
        results, rerank = self._prepare_search_results(
            query=query,
            results=results,
            evidence_policy=evidence_policy,
            max_results=max_results,
        )
        workflow_support = _workflow_support_for_intent(intent)
        evidence_gate = _evidence_gate(results, evidence_policy)

        return {
            "artifact_type": "site_knowledge_results",
            "composition_role": "site_knowledge_context",
            "status": "ready",
            "intent": intent,
            "workflow_support": workflow_support,
            "agent_handoff": _agent_handoff_for_search(
                intent=intent,
                workflow_support=workflow_support,
                evidence_gate=evidence_gate,
                results=results,
            ),
            "evidence_gate": evidence_gate,
            "rerank": rerank,
            "results": results,
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }

    def _build_chunks(
        self,
        document: dict[str, object],
        *,
        site_id: str,
        run_id: str,
        ability_name: str,
        max_chunks: int | None = None,
    ) -> list[dict[str, object]]:
        source_text = "\n\n".join(
            part
            for part in (
                str(document.get("title") or ""),
                str(document.get("excerpt") or ""),
                str(document.get("content_excerpt") or ""),
            )
            if part.strip()
        )
        source_text = " ".join(source_text.split())
        if not source_text:
            return []

        chunks: list[dict[str, object]] = []
        chunk_limit = MAX_CHUNKS_PER_DOCUMENT
        if max_chunks is not None:
            chunk_limit = max(0, min(MAX_CHUNKS_PER_DOCUMENT, int(max_chunks)))
        if chunk_limit <= 0:
            return []
        start = 0
        while start < len(source_text):
            if len(chunks) >= chunk_limit:
                break
            text = source_text[start : start + MAX_CHUNK_CHARS].strip()
            if text:
                chunks.append(
                    {
                        "chunk_index": len(chunks),
                        "chunk_text": text,
                        "embedding": self._embed_text(
                            text,
                            site_id=site_id,
                            run_id=run_id,
                            ability_name=ability_name,
                        ),
                        "embedding_model": self.embedding_model,
                        "metadata": {
                            "source": "wordpress_public_excerpt",
                            "content_hash": str(document.get("content_hash") or ""),
                            "content_truncated": bool(document.get("content_truncated")),
                            "max_content_chars": MAX_DOCUMENT_CONTENT_CHARS,
                            "max_chunks": MAX_CHUNKS_PER_DOCUMENT,
                            "effective_max_chunks": chunk_limit,
                        },
                    }
                )
            if start + MAX_CHUNK_CHARS >= len(source_text):
                break
            start += MAX_CHUNK_CHARS - CHUNK_OVERLAP_CHARS
        chunk_limit_truncated = start < len(source_text) and len(chunks) >= chunk_limit
        if chunk_limit_truncated:
            for chunk in chunks:
                metadata = chunk.get("metadata")
                if isinstance(metadata, dict):
                    metadata["chunk_limit_truncated"] = True
                    metadata["max_chunks"] = MAX_CHUNKS_PER_DOCUMENT
                    metadata["effective_max_chunks"] = chunk_limit
        return chunks

    def _embed_text(
        self,
        text: str,
        *,
        site_id: str,
        run_id: str,
        ability_name: str,
    ) -> list[float]:
        if self.embedding_provider_id == "deterministic":
            return embed_text_deterministic(text, dimensions=self.embedding_dimensions)
        return self._embed_text_with_provider(
            text,
            site_id=site_id,
            run_id=run_id,
            ability_name=ability_name,
        )

    def _embed_text_with_provider(
        self,
        text: str,
        *,
        site_id: str,
        run_id: str,
        ability_name: str,
    ) -> list[float]:
        provider = self.providers.get(self.embedding_provider_id)
        if provider is None:
            raise SiteKnowledgeBackendError(
                "site_knowledge.embedding_provider_missing",
                "site knowledge embedding provider is not configured",
            )
        model_id = self.embedding_model
        if self.embedding_provider_id == "tei" and not model_id.lower().startswith("tei/"):
            model_id = f"tei/{model_id}"
        provider_request = ProviderExecutionRequest(
            run_id=run_id,
            site_id=site_id,
            ability_name=ability_name,
            profile_id="site-knowledge.managed",
            execution_kind="embedding",
            model_id=model_id,
            instance_id=f"{self.embedding_provider_id}-site-knowledge-embedding",
            endpoint_variant="embeddings",
            trace_id=run_id,
            input_payload={"text": text},
            policy={"storage_mode": "result_only"},
            timeout_ms=max(1, int(self._embedding_timeout_seconds() * 1000)),
        )
        try:
            result = provider.execute(provider_request)
        except ProviderExecutionError as error:
            self._record_embedding_usage(provider_request, provider_error=error)
            raise SiteKnowledgeBackendError(
                error.error_code,
                "site knowledge embedding provider request failed",
            ) from error
        self._record_embedding_usage(provider_request, provider_result=result)

        embedding = result.output.get("embedding")
        if not isinstance(embedding, list):
            raise SiteKnowledgeBackendError(
                "site_knowledge.embedding_invalid",
                "site knowledge embedding provider returned an invalid embedding",
            )
        vector = [float(value) for value in embedding]
        if len(vector) != self.embedding_dimensions:
            raise SiteKnowledgeBackendError(
                "site_knowledge.embedding_dimension_mismatch",
                "site knowledge embedding dimensions do not match configuration",
            )
        return vector

    def _record_embedding_usage(
        self,
        provider_request: ProviderExecutionRequest,
        *,
        provider_result: ProviderExecutionResult | None = None,
        provider_error: ProviderExecutionError | None = None,
    ) -> None:
        if self.embedding_usage_callback is None:
            return
        self.embedding_usage_callback(
            self.embedding_provider_id,
            provider_request,
            provider_result,
            provider_error,
        )

    def _embedding_timeout_seconds(self) -> float:
        if self.embedding_provider_id == "siliconflow":
            return float(self.settings.siliconflow_timeout_seconds)
        if self.embedding_provider_id == "openai":
            return float(self.settings.openai_timeout_seconds)
        return float(self.settings.tei_timeout_seconds)

    def _prepare_search_results(
        self,
        *,
        query: str,
        results: list[dict[str, object]],
        evidence_policy: dict[str, object],
        max_results: int,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        filtered = _apply_evidence_policy(results, evidence_policy)
        ranked = _rank_search_results_for_query(query, filtered)
        reranked, rerank = self._maybe_rerank_results(query=query, results=ranked)
        return reranked[:max_results], rerank

    def _maybe_rerank_results(
        self,
        *,
        query: str,
        results: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        reranker: SiteKnowledgeReranker | None = self.reranker
        if reranker is None:
            return results, {
                "status": "disabled",
                "provider": str(self.settings.site_knowledge_rerank_provider or "disabled"),
                "candidate_count": len(results),
            }

        exact_results = [result for result in results if bool(result.get("exact_query_match"))]
        semantic_results = [
            result for result in results if not bool(result.get("exact_query_match"))
        ]
        try:
            if exact_results:
                exact_outcome = reranker.rerank(query=query, results=exact_results)
                if semantic_results:
                    semantic_outcome = reranker.rerank(query=query, results=semantic_results)
                    metadata = dict(exact_outcome.metadata)
                    metadata["semantic_candidate_count"] = len(semantic_results)
                    metadata["semantic_status"] = semantic_outcome.metadata.get("status")
                    return [*exact_outcome.results, *semantic_outcome.results], metadata
                return exact_outcome.results, exact_outcome.metadata

            outcome = reranker.rerank(query=query, results=results)
            return outcome.results, outcome.metadata
        except SiteKnowledgeRerankError as error:
            return results, {
                "status": "failed",
                "provider": str(self.settings.site_knowledge_rerank_provider or ""),
                "error_code": error.error_code,
                "candidate_count": len(results),
                "fallback": "vector_order",
            }

    def _sync_progress(
        self,
        *,
        status: str,
        stage: str,
        message: str,
        sync_mode: str,
        processed_documents: int = 0,
        total_documents: int = 0,
        accepted_documents: int = 0,
        indexed_documents: int = 0,
        indexed_chunks: int = 0,
        failed_documents: int = 0,
        skipped_documents: int = 0,
        skipped_due_to_quota: int = 0,
        deleted_entries: int = 0,
        percent: int | None = None,
    ) -> dict[str, Any]:
        total = max(0, int(total_documents))
        processed = max(0, int(processed_documents))
        resolved_percent = (
            max(0, min(100, int(percent)))
            if percent is not None
            else (min(99, int(processed / total * 100)) if total > 0 else 0)
        )
        return {
            "status": status,
            "stage": stage,
            "message": message,
            "sync_mode": sync_mode,
            "processed_documents": processed,
            "total_documents": total,
            "accepted_documents": max(0, int(accepted_documents)),
            "indexed_documents": max(0, int(indexed_documents)),
            "indexed_chunks": max(0, int(indexed_chunks)),
            "failed_documents": max(0, int(failed_documents)),
            "skipped_documents": max(0, int(skipped_documents)),
            "skipped_due_to_quota": max(0, int(skipped_due_to_quota)),
            "deleted_entries": max(0, int(deleted_entries)),
            "percent": resolved_percent,
            "updated_at": _serialize_datetime(datetime.now(UTC)),
        }

    def _quota_snapshot(
        self,
        *,
        indexed_posts: int,
        indexed_chunks: int,
        skipped_documents: int = 0,
        skipped_due_to_quota: int = 0,
    ) -> dict[str, Any]:
        max_documents = int(self.settings.site_knowledge_max_indexed_documents_per_site)
        max_chunks = int(self.settings.site_knowledge_max_indexed_chunks_per_site)
        warning_ratio = float(self.settings.site_knowledge_quota_warning_ratio)
        document_utilization = indexed_posts / max_documents if max_documents > 0 else 1.0
        chunk_utilization = indexed_chunks / max_chunks if max_chunks > 0 else 1.0
        status = "ok"
        if skipped_due_to_quota > 0 or document_utilization >= 1.0 or chunk_utilization >= 1.0:
            status = "limited"
        elif document_utilization >= warning_ratio or chunk_utilization >= warning_ratio:
            status = "near_limit"
        elif indexed_posts == 0 and indexed_chunks == 0:
            status = "empty"

        return {
            "status": status,
            "indexed_documents": max(0, int(indexed_posts)),
            "indexed_chunks": max(0, int(indexed_chunks)),
            "max_indexed_documents_per_site": max_documents,
            "max_indexed_chunks_per_site": max_chunks,
            "max_sync_documents_per_run": int(
                self.settings.site_knowledge_max_sync_documents_per_run
            ),
            "max_sync_chunks_per_run": int(self.settings.site_knowledge_max_sync_chunks_per_run),
            "warning_ratio": warning_ratio,
            "document_utilization": round(max(0.0, document_utilization), 4),
            "chunk_utilization": round(max(0.0, chunk_utilization), 4),
            "skipped_documents": max(0, int(skipped_documents)),
            "skipped_due_to_quota": max(0, int(skipped_due_to_quota)),
            "comments_enabled": bool(self.settings.site_knowledge_comments_enabled),
        }

    def _emit_sync_progress(self, **progress: Any) -> None:
        if self.progress_callback is None:
            return
        payload = progress if "updated_at" in progress else self._sync_progress(**progress)
        self.progress_callback(payload)

    def _status_progress(
        self,
        *,
        status: str,
        coverage: dict[str, Any],
        active_run: Any | None,
    ) -> dict[str, Any]:
        if active_run is not None:
            progress = _progress_from_run(active_run)
            if progress:
                return progress
            stage = "queued" if active_run.status == "queued" else "preparing"
            return self._sync_progress(
                status=active_run.status,
                stage=stage,
                message=(
                    "Waiting for Cloud worker to start."
                    if stage == "queued"
                    else "Cloud indexing is running."
                ),
                sync_mode="refresh",
                percent=0,
            )
        if status == "ready":
            return self._sync_progress(
                status="completed",
                stage="completed",
                message="Index is ready for search.",
                sync_mode="refresh",
                processed_documents=int(coverage.get("indexed_posts") or 0),
                total_documents=int(coverage.get("indexed_posts") or 0),
                indexed_documents=int(coverage.get("indexed_posts") or 0),
                indexed_chunks=int(coverage.get("indexed_chunks") or 0),
                percent=100,
            )
        if status == "failed":
            return self._sync_progress(
                status="failed",
                stage="failed",
                message="Indexing failed. Refresh again or check Cloud logs.",
                sync_mode="refresh",
            )
        return self._sync_progress(
            status="empty",
            stage="not_started",
            message="Index has not been started yet.",
            sync_mode="refresh",
        )

    def _search_vector_backend(
        self,
        *,
        site_id: str,
        query_embedding: list[float],
        post_types: list[str],
        statuses: list[str],
        source_types: list[str],
        current_post_id: int,
        max_results: int,
        intent: str,
        query: str,
    ) -> list[dict[str, object]] | None:
        backend: SiteKnowledgeVectorBackend | None = self.vector_backend
        if backend is None:
            return None
        hits = backend.search(
            site_id=site_id,
            query_embedding=query_embedding,
            post_types=post_types,
            statuses=statuses,
            source_types=source_types,
            current_post_id=current_post_id,
            limit=min(max(1, max_results * 4), 80),
        )
        return [_serialize_vector_hit(hit, intent=intent, query=query) for hit in hits]

    def _sync_response(
        self,
        *,
        status: str,
        run_id: str,
        sync_mode: str,
        accepted_documents: int,
        indexed_documents: int,
        indexed_chunks: int,
        failed_documents: int,
        deleted_entries: int,
        truncated_documents: int = 0,
        skipped_documents: int = 0,
        skipped_due_to_quota: int = 0,
        progress: dict[str, Any] | None = None,
        quota: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "artifact_type": "site_knowledge_sync_request",
            "composition_role": "site_knowledge_sync_request",
            "contract_version": SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_SYNC_ABILITY],
            "status": status,
            "run_id": run_id,
            "sync": {
                "sync_mode": sync_mode,
                "accepted_documents": accepted_documents,
                "indexed_documents": indexed_documents,
                "indexed_chunks": indexed_chunks,
                "failed_documents": failed_documents,
                "truncated_documents": truncated_documents,
                "skipped_documents": skipped_documents,
                "skipped_due_to_quota": skipped_due_to_quota,
                "deleted_entries": deleted_entries,
            },
            "quota": quota if isinstance(quota, dict) else {},
            "progress": progress
            if isinstance(progress, dict)
            else self._sync_progress(
                status=status,
                stage="completed" if status == "completed" else status,
                message="Index is ready for search." if status == "completed" else "",
                sync_mode=sync_mode,
                processed_documents=indexed_documents + failed_documents,
                total_documents=accepted_documents + failed_documents,
                accepted_documents=accepted_documents,
                indexed_documents=indexed_documents,
                indexed_chunks=indexed_chunks,
                failed_documents=failed_documents,
                skipped_documents=skipped_documents,
                skipped_due_to_quota=skipped_due_to_quota,
                deleted_entries=deleted_entries,
                percent=100 if status == "completed" else None,
            ),
            "ownership": _site_knowledge_ownership_contract(),
            "truth_boundaries": _site_knowledge_truth_boundaries(),
            "write_posture": "suggestion_only",
            "direct_wordpress_write": False,
        }


def _site_knowledge_ownership_contract() -> dict[str, str]:
    return {
        "source_content_owner": "local_wordpress_host",
        "delivery_bridge_owner": "cloud_addon",
        "index_execution_owner": "cloud_service",
        "index_lifecycle_owner": "cloud_service",
        "freshness_policy_owner": "cloud_service",
        "diagnostics_detail_owner": "cloud_service",
        "vector_storage_owner": "cloud_service",
        "embedding_execution_owner": "cloud_service",
        "approval_owner": "local_wordpress_host",
        "final_write_owner": "local_wordpress_host",
        "wordpress_write_owner": "local_wordpress_host",
    }


def _site_knowledge_truth_boundaries() -> dict[str, bool]:
    return {
        "cloud_is_index_truth": True,
        "cloud_is_freshness_truth": True,
        "cloud_is_diagnostics_truth": True,
        "cloud_is_wordpress_control_plane": False,
        "cloud_creates_wordpress_writes": False,
        "cloud_owns_local_approval": False,
        "cloud_owns_ability_registry": False,
        "cloud_owns_workflow_registry": False,
    }


def _normalize_public_document(document: dict[str, Any]) -> dict[str, object] | None:
    post_id = _coerce_int(document.get("post_id"), default=0)
    post_type = str(document.get("post_type") or "").strip().lower()
    post_status = str(document.get("post_status") or "").strip().lower()
    if (
        post_id <= 0
        or post_type not in PUBLIC_POST_TYPES
        or post_status not in PUBLIC_POST_STATUSES
    ):
        return None

    title = _normalize_site_knowledge_text(document.get("title"), max_chars=500)
    url = str(document.get("url") or "").strip()
    excerpt = _normalize_site_knowledge_text(
        document.get("excerpt"),
        max_chars=2000,
        remove_markup_noise=True,
    )
    content_excerpt = _normalize_site_knowledge_text(
        document.get("content_excerpt"),
        max_chars=MAX_DOCUMENT_CONTENT_CHARS,
        remove_markup_noise=True,
    )
    source_content_chars = _normalized_site_knowledge_text_length(
        document.get("content_excerpt"),
        remove_markup_noise=True,
    )
    indexed_content_chars = len(content_excerpt)
    content_hash = str(document.get("content_hash") or "").strip()
    if not content_hash:
        content_hash = hashlib.sha256(f"{title}|{excerpt}|{content_excerpt}".encode()).hexdigest()

    return {
        "post_id": post_id,
        "source_type": post_type,
        "source_id": post_id,
        "parent_post_id": post_id,
        "post_type": post_type,
        "post_status": post_status,
        "title": title,
        "url": url[:2000],
        "modified_gmt": str(document.get("modified_gmt") or "").strip()[:64],
        "excerpt": excerpt,
        "content_excerpt": content_excerpt,
        "source_content_chars": source_content_chars,
        "indexed_content_chars": indexed_content_chars,
        "content_truncated": source_content_chars > indexed_content_chars,
        "content_hash": content_hash[:128],
    }


def _normalize_public_comment(document: dict[str, Any]) -> dict[str, object] | None:
    comment_id = _coerce_int(document.get("comment_id"), default=0)
    post_id = _coerce_int(document.get("post_id"), default=0)
    comment_status = str(document.get("comment_status") or "").strip().lower()
    if comment_id <= 0 or post_id <= 0 or comment_status not in PUBLIC_COMMENT_STATUSES:
        return None

    content_excerpt = _normalize_site_knowledge_text(
        document.get("content_excerpt"),
        max_chars=4000,
        remove_markup_noise=True,
    )
    content_hash = str(document.get("content_hash") or "").strip()
    if not content_hash:
        content_hash = hashlib.sha256(
            f"{post_id}|{comment_id}|{content_excerpt}".encode()
        ).hexdigest()
    url = str(document.get("url") or "").strip()

    return {
        "post_id": post_id,
        "source_type": "comment",
        "source_id": comment_id,
        "parent_post_id": post_id,
        "post_type": "comment",
        "post_status": "publish",
        "title": f"Comment on post {post_id}",
        "url": url[:2000],
        "modified_gmt": str(document.get("created_gmt") or "").strip()[:64],
        "excerpt": "",
        "content_excerpt": content_excerpt,
        "content_hash": content_hash[:128],
    }


def _normalize_site_knowledge_text(
    value: Any,
    *,
    max_chars: int,
    remove_markup_noise: bool = False,
) -> str:
    text = html.unescape(str(value or ""))
    if remove_markup_noise:
        text = _remove_markup_noise(text)
    return " ".join(text.split())[:max_chars]


def _normalized_site_knowledge_text_length(
    value: Any,
    *,
    remove_markup_noise: bool = False,
) -> int:
    text = html.unescape(str(value or ""))
    if remove_markup_noise:
        text = _remove_markup_noise(text)
    return len(" ".join(text.split()))


def _remove_markup_noise(text: str) -> str:
    cleaned = STYLE_SCRIPT_BLOCK_PATTERN.sub(" ", text)
    cleaned = HTML_TAG_PATTERN.sub(" ", cleaned)
    for _ in range(6):
        next_cleaned = CSS_RULE_PATTERN.sub(" ", cleaned)
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned
    return cleaned


def _looks_like_comment_document(document: dict[str, Any]) -> bool:
    return "comment_id" in document or "comment_status" in document


def _coerce_post_ids(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    post_ids = []
    seen = set()
    for item in value:
        post_id = _coerce_int(item, default=0)
        if post_id <= 0 or post_id in seen:
            continue
        post_ids.append(post_id)
        seen.add(post_id)
        if len(post_ids) >= MAX_SYNC_POST_IDS:
            break
    return post_ids


def _filter_string_list(value: Any, *, allowed: frozenset[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    results = []
    seen = set()
    for item in value:
        normalized = str(item or "").strip().lower()
        if normalized not in allowed or normalized in seen:
            continue
        results.append(normalized)
        seen.add(normalized)
        if len(results) >= MAX_SEARCH_FILTER_ITEMS:
            break
    return results


def _normalize_search_query(value: Any) -> str:
    return " ".join(str(value or "").split())[:MAX_SEARCH_QUERY_CHARS]


def _resolve_evidence_policy(value: Any) -> dict[str, object]:
    policy = value if isinstance(value, dict) else {}
    min_score = _coerce_float(
        policy.get("min_score"),
        default=DEFAULT_EVIDENCE_MIN_SCORE,
    )
    min_score = max(0.0, min(1.0, min_score))
    required_sources = coerce_positive_int(
        policy.get("required_sources"),
        default=DEFAULT_REQUIRED_EVIDENCE_SOURCES,
        maximum=5,
    )
    no_hit_policy = str(policy.get("no_hit_policy") or "abstain").strip().lower()
    if no_hit_policy not in ALLOWED_NO_HIT_POLICIES:
        no_hit_policy = "abstain"
    return {
        "min_score": min_score,
        "required_sources": required_sources,
        "no_hit_policy": no_hit_policy,
    }


def _apply_evidence_policy(
    results: list[dict[str, object]],
    evidence_policy: dict[str, object],
) -> list[dict[str, object]]:
    min_score = _coerce_float(evidence_policy.get("min_score"), default=0.0)
    return [
        result for result in results if _coerce_float(result.get("score"), default=0.0) >= min_score
    ]


def _evidence_gate(
    results: list[dict[str, object]],
    evidence_policy: dict[str, object],
) -> dict[str, object]:
    required_sources = _coerce_int(evidence_policy.get("required_sources"), default=1)
    no_hit_policy = str(evidence_policy.get("no_hit_policy") or "abstain")
    passed = len(results) >= required_sources
    return {
        "status": "passed" if passed else "insufficient_evidence",
        "min_score": round(_coerce_float(evidence_policy.get("min_score"), default=0.0), 4),
        "required_sources": required_sources,
        "source_count": len(results),
        "no_hit_policy": no_hit_policy,
        "allows_site_grounded_assertion": passed,
        "guidance": (
            "Use returned site sources as grounding evidence."
            if passed
            else _insufficient_evidence_guidance(no_hit_policy)
        ),
    }


def _insufficient_evidence_guidance(no_hit_policy: str) -> str:
    if no_hit_policy == "fallback_to_general":
        return (
            "Do not present an unsupported site-specific claim; use general model "
            "knowledge only with an explicit uncertainty disclaimer."
        )
    if no_hit_policy == "return_empty":
        return (
            "Return no grounded answer because the site knowledge index had insufficient evidence."
        )
    return "Abstain or ask for more source material; do not invent site-specific facts."


def _coerce_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _serialize_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


def _progress_from_run(run: Any) -> dict[str, Any]:
    result_json = run.result_json if isinstance(run.result_json, dict) else {}
    progress = result_json.get("progress")
    return progress if isinstance(progress, dict) else {}


def _serialize_active_run(run: Any) -> dict[str, Any]:
    return {
        "run_id": str(run.run_id or ""),
        "status": str(run.status or ""),
        "started_at": _serialize_datetime(run.started_at),
        "processing_started_at": _serialize_datetime(run.processing_started_at),
    }


def _lexical_bonus(query: str, chunk_text: str, title: str) -> float:
    query_terms = {term for term in query.lower().split() if len(term) >= 2}
    if not query_terms:
        return 0.0
    haystack = f"{title} {chunk_text}".lower()
    matches = sum(1 for term in query_terms if term in haystack)
    return min(0.2, matches / max(1, len(query_terms)) * 0.2)


def _query_match_info(query: str, chunk_text: str) -> dict[str, object]:
    normalized_query = " ".join(str(query or "").split())
    text = str(chunk_text or "")
    if not normalized_query or not text:
        return {
            "match_type": "semantic",
            "exact_query_match": False,
            "match_count": 0,
            "match_context": text[:360],
        }

    text_lower = text.lower()
    query_lower = normalized_query.lower()
    positions = _substring_positions(text_lower, query_lower)
    if positions:
        return {
            "match_type": "exact",
            "exact_query_match": True,
            "match_count": len(positions),
            "match_context": _match_context(text, positions[0], len(normalized_query)),
        }

    return {
        "match_type": "semantic",
        "exact_query_match": False,
        "match_count": 0,
        "match_context": text[:360],
    }


def _rank_search_results_for_query(
    query: str,
    results: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not query.strip():
        return results
    return sorted(
        results,
        key=lambda result: (
            0 if bool(result.get("exact_query_match")) else 1,
            -_coerce_int(result.get("match_count"), default=0),
            -_coerce_float(result.get("score"), default=0.0),
            _coerce_int(result.get("post_id"), default=0),
        ),
    )


def _chunks_include_limit_truncation(chunks: list[dict[str, object]]) -> bool:
    for chunk in chunks:
        metadata = chunk.get("metadata")
        if isinstance(metadata, dict) and bool(metadata.get("chunk_limit_truncated")):
            return True
    return False


def _substring_positions(text: str, needle: str) -> list[int]:
    if not text or not needle:
        return []
    positions: list[int] = []
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return positions
        positions.append(index)
        start = index + max(1, len(needle))


def _match_context(text: str, position: int, match_length: int) -> str:
    start = max(0, position - 140)
    end = min(len(text), position + match_length + 180)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


def _reason_for_intent(intent: str) -> str:
    if intent == "site_search":
        return "The indexed passage may answer a site-content question with source context."
    if intent == "faq_candidates":
        return (
            "The indexed passage may reveal a repeated question or answerable site FAQ candidate."
        )
    if intent == "related_content":
        return "The indexed passage is related and may support topic cluster planning."
    if intent == "content_gap_analysis":
        return (
            "The indexed passage is related evidence for deciding whether coverage "
            "is missing or shallow."
        )
    if intent == "duplicate_check":
        return (
            "The indexed passage is similar enough to review before creating or "
            "publishing new content."
        )
    if intent == "internal_links":
        return "The indexed passage is semantically related and may support an internal link."
    if intent == "refresh_suggestions":
        return "The indexed passage is related to the requested refresh context."
    if intent == "writing_context":
        return "The indexed passage can provide site-specific writing context."
    if intent == "writing_support_plan":
        return (
            "The indexed passage can reduce writing preparation work without "
            "becoming an article draft."
        )
    if intent == "image_context":
        return "The indexed passage can inform image context or media planning."
    return "Topic and intent are closely related."


def _suggested_use_for_intent(intent: str) -> str:
    return {
        "site_search": "answer_source",
        "internal_links": "internal_link",
        "related_content": "topic_cluster_candidate",
        "refresh_suggestions": "refresh_candidate",
        "faq_candidates": "faq_candidate",
        "content_gap_analysis": "gap_evidence",
        "duplicate_check": "duplicate_or_conflict_candidate",
        "writing_support_plan": "writing_support_evidence",
    }.get(intent, "reference_snippet")


def _serialize_vector_hit(
    hit: VectorSearchHit,
    *,
    intent: str,
    query: str = "",
) -> dict[str, object]:
    return _serialize_search_result(
        post_id=hit.post_id,
        source_type=hit.source_type,
        source_id=hit.source_id,
        parent_post_id=hit.parent_post_id,
        title=hit.title,
        url=hit.url,
        chunk_text=hit.chunk_text,
        score=hit.score,
        intent=intent,
        query=query,
    )


def _serialize_search_result(
    *,
    post_id: int,
    source_type: str,
    source_id: int,
    parent_post_id: int,
    title: str,
    url: str,
    chunk_text: str,
    score: float,
    intent: str,
    query: str = "",
) -> dict[str, object]:
    match = _query_match_info(query, chunk_text)
    result: dict[str, object] = {
        "post_id": post_id,
        "source_type": source_type,
        "source_id": source_id,
        "parent_post_id": parent_post_id,
        "title": title,
        "url": url,
        "chunk": chunk_text[:1200],
        "score": round(score, 4),
        "match_type": match["match_type"],
        "exact_query_match": match["exact_query_match"],
        "match_count": match["match_count"],
        "match_context": match["match_context"],
        "reason": _reason_for_intent(intent),
        "suggested_use": _suggested_use_for_intent(intent),
    }
    if intent == "internal_links":
        result.update(
            {
                "anchor_text_candidates": _anchor_text_candidates(title, chunk_text),
                "link_target": {
                    "post_id": post_id,
                    "title": title,
                    "url": url,
                },
                "suggested_action": "insert_internal_link_after_editor_confirmation",
                "insert_mode": "wordpress_local_only",
            }
        )
    elif intent == "writing_context":
        result.update(
            {
                "context_role": "site_reference",
                "citation": {
                    "post_id": post_id,
                    "title": title,
                    "url": url,
                },
                "usage_guidance": (
                    "Use as background context for generation; do not copy or publish "
                    "without WordPress-side editor approval."
                ),
            }
        )
    elif intent == "refresh_suggestions":
        result.update(
            {
                "refresh_action": "review_for_update_or_merge",
                "refresh_signals": ["topic_overlap", "semantic_similarity"],
                "suggested_action": "open_wordpress_editor_review",
                "update_mode": "wordpress_local_only",
            }
        )
    elif intent == "site_search":
        result.update(
            {
                "answer_source": {
                    "post_id": post_id,
                    "title": title,
                    "url": url,
                },
                "copilot_action": "answer_with_site_citation",
                "response_mode": "source_grounded_suggestion",
            }
        )
    elif intent == "faq_candidates":
        result.update(
            {
                "faq_candidate": {
                    "question_seed": _faq_question_seed(chunk_text),
                    "answer_source": {
                        "post_id": post_id,
                        "source_type": source_type,
                        "source_id": source_id,
                        "title": title,
                        "url": url,
                    },
                    "source_signal": (
                        "approved_comment_question"
                        if source_type == "comment"
                        else "public_content_question"
                    ),
                },
                "suggested_action": "review_or_add_faq_after_editor_confirmation",
                "faq_mode": "wordpress_local_only",
            }
        )
    elif intent == "related_content":
        result.update(
            {
                "cluster_candidate": {
                    "post_id": post_id,
                    "title": title,
                    "url": url,
                },
                "cluster_role": _cluster_role_for_score(score),
                "planning_action": "review_for_topic_cluster_or_hub_page",
                "planning_mode": "wordpress_local_only",
            }
        )
    elif intent == "content_gap_analysis":
        result.update(
            {
                "gap_signal": {
                    "coverage": _coverage_signal_for_score(score),
                    "evidence_source": {
                        "post_id": post_id,
                        "source_type": source_type,
                        "source_id": source_id,
                        "title": title,
                        "url": url,
                    },
                    "signals": ["semantic_near_match", "coverage_review_needed"],
                },
                "suggested_action": "review_for_new_or_expanded_content",
                "planning_mode": "wordpress_local_only",
            }
        )
    elif intent == "writing_support_plan":
        result.update(
            {
                "writing_support": {
                    "source_role": _writing_support_source_role(score),
                    "evidence_source": {
                        "post_id": post_id,
                        "source_type": source_type,
                        "source_id": source_id,
                        "title": title,
                        "url": url,
                    },
                    "pre_draft_tasks": [
                        "verify_facts_against_source",
                        "decide_expand_existing_or_write_new_coverage",
                        "collect_internal_link_and_media_candidates",
                    ],
                    "writer_next_action": "use_as_preparation_material_before_drafting",
                    "blocked_outputs": [
                        "article_body",
                        "article_title",
                        "seo_copy",
                        "article_write_plan",
                        "full_article_draft",
                        "ready_to_publish_content",
                        "auto_publish_instruction",
                        "direct_wordpress_write",
                    ],
                },
                "planning_mode": "wordpress_local_only",
            }
        )
    if intent in {"refresh_suggestions", "duplicate_check"}:
        result["duplicate_check"] = {
            "risk": _duplicate_risk_for_score(score),
            "signals": ["semantic_similarity", "topic_overlap"],
            "preflight_action": "review_existing_content_before_drafting",
            "conflict_action": "do_not_publish_until_wordpress_editor_review",
            "review_mode": "wordpress_local_only",
        }
    return result


def _workflow_support_for_intent(intent: str) -> dict[str, object]:
    if intent == "site_search":
        return {
            "workflow": "site_content_copilot",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "answer_sources",
        }
    if intent == "faq_candidates":
        return {
            "workflow": "faq_candidate_mining",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "faq_candidates",
        }
    if intent == "related_content":
        return {
            "workflow": "topic_cluster_planning",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "cluster_candidates",
        }
    if intent == "content_gap_analysis":
        return {
            "workflow": "content_gap_analysis",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "gap_evidence",
        }
    if intent == "duplicate_check":
        return {
            "workflow": "publish_preflight_duplicate_check",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "duplicate_or_conflict_candidates",
        }
    if intent == "internal_links":
        return {
            "workflow": "internal_link_recommendation",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "candidate_links",
        }
    if intent == "writing_context":
        return {
            "workflow": "writer_context_enrichment",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "reference_context",
        }
    if intent == "writing_support_plan":
        return {
            "workflow": "writer_preparation_support",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "pre_draft_support_plan",
            "writing_assistance_owner": "wordpress_local_writer",
        }
    if intent == "refresh_suggestions":
        return {
            "workflow": "content_refresh_review",
            "wordpress_write_owner": "wordpress_local",
            "cloud_output": "refresh_candidates",
        }
    return {
        "workflow": "site_knowledge_search",
        "wordpress_write_owner": "wordpress_local",
        "cloud_output": "search_results",
    }


PROPOSAL_HANDOFF_INTENTS = frozenset(
    {
        "content_gap_analysis",
        "duplicate_check",
        "faq_candidates",
        "internal_links",
        "refresh_suggestions",
        "related_content",
        "writing_support_plan",
    }
)


def _agent_handoff_for_search(
    *,
    intent: str,
    workflow_support: dict[str, object],
    evidence_gate: dict[str, object],
    results: list[dict[str, object]],
) -> dict[str, object]:
    handoff_type = "proposal_input" if intent in PROPOSAL_HANDOFF_INTENTS else "suggestion_only"
    evidence_refs = _agent_evidence_refs(results)
    proposal_input: dict[str, object] = {}
    if handoff_type == "proposal_input":
        proposal_input = {
            "source": "site_knowledge",
            "intent": intent,
            "workflow": str(workflow_support.get("workflow") or "site_knowledge_search"),
            "cloud_output": str(workflow_support.get("cloud_output") or "search_results"),
            "local_next_action": _agent_local_next_action_for_intent(intent),
            "evidence_refs": evidence_refs,
            "blocked_outputs": [
                "direct_wordpress_write",
                "cloud_publish",
                "article_body",
                "article_title",
                "seo_copy",
                "article_write_plan",
                "full_article_draft",
                "ready_to_publish_content",
                "auto_publish_instruction",
            ],
        }

    agent_metadata = get_agent_handoff_metadata(SITE_KNOWLEDGE_SUGGESTION_AGENT_ID)
    return {
        "agent_id": str(agent_metadata.get("agent_id") or SITE_KNOWLEDGE_SUGGESTION_AGENT_ID),
        "agent_version": str(agent_metadata.get("agent_version") or ""),
        "agent_role": str(agent_metadata.get("agent_role") or ""),
        "triggering_ability": SITE_KNOWLEDGE_SEARCH_ABILITY,
        "triggering_contract": SITE_KNOWLEDGE_CONTRACTS[SITE_KNOWLEDGE_SEARCH_ABILITY],
        "handoff_type": handoff_type,
        "handoff_owner": str(agent_metadata.get("handoff_owner") or "wordpress_local"),
        "local_handoff_owner": "wordpress_local",
        "requires_local_approval": handoff_type == "proposal_input",
        "write_posture": "suggestion_only",
        "direct_wordpress_write": bool(agent_metadata.get("direct_wordpress_write")),
        "execution_pattern": str(agent_metadata.get("execution_pattern") or "inline"),
        "storage_mode": str(agent_metadata.get("storage_mode") or "result_only"),
        "workflow": str(workflow_support.get("workflow") or "site_knowledge_search"),
        "cloud_output": str(workflow_support.get("cloud_output") or "search_results"),
        "evidence_gate_status": str(evidence_gate.get("status") or "insufficient_evidence"),
        "evidence_count": len(evidence_refs),
        "evidence_requirements": {
            "min_score": evidence_gate.get("min_score", 0),
            "required_sources": evidence_gate.get("required_sources", 1),
            "no_hit_policy": str(evidence_gate.get("no_hit_policy") or "abstain"),
        },
        "allowed_actions": _string_list(agent_metadata.get("allowed_actions")),
        "stop_conditions": _string_list(agent_metadata.get("stop_conditions")),
        "forbidden_actions": _string_list(agent_metadata.get("forbidden_actions")),
        "fail_closed_behavior": str(agent_metadata.get("fail_closed_behavior") or ""),
        "proposal_input": proposal_input,
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _agent_evidence_refs(results: list[dict[str, object]]) -> list[dict[str, object]]:
    evidence_refs: list[dict[str, object]] = []
    for item in results[:5]:
        evidence_refs.append(
            {
                "post_id": _coerce_int(item.get("post_id"), default=0),
                "source_type": str(item.get("source_type") or ""),
                "source_id": _coerce_int(item.get("source_id"), default=0),
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "score": item.get("score") if isinstance(item.get("score"), float) else 0,
                "suggested_use": str(item.get("suggested_use") or ""),
            }
        )
    return evidence_refs


def _agent_local_next_action_for_intent(intent: str) -> str:
    if intent == "content_gap_analysis":
        return "review_content_gap_before_local_plan"
    if intent == "duplicate_check":
        return "review_duplicate_risk_before_drafting"
    if intent == "faq_candidates":
        return "review_faq_candidate_before_local_proposal"
    if intent == "internal_links":
        return "create_internal_link_proposal_after_editor_review"
    if intent == "refresh_suggestions":
        return "review_refresh_candidate_before_local_update"
    if intent == "related_content":
        return "review_topic_cluster_candidate"
    if intent == "writing_support_plan":
        return "use_pre_draft_support_in_local_writer_workflow"
    return "display_suggestion_with_evidence"


def _anchor_text_candidates(title: str, chunk_text: str) -> list[str]:
    candidates = []
    normalized_title = " ".join(str(title or "").split())
    if normalized_title:
        candidates.append(normalized_title[:80])

    words = [word.strip(".,;:!?()[]{}\"'") for word in str(chunk_text or "").split()]
    words = [word for word in words if len(word) >= 2]
    if len(words) >= 4:
        phrase = " ".join(words[: min(8, len(words))])
        if phrase and phrase not in candidates:
            candidates.append(phrase[:80])
    return candidates[:3]


def _duplicate_risk_for_score(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.7:
        return "medium"
    return "low"


def _coverage_signal_for_score(score: float) -> str:
    if score >= 0.85:
        return "covered_or_duplicate_risk"
    if score >= 0.65:
        return "partially_covered"
    return "possible_gap"


def _faq_question_seed(chunk_text: str) -> str:
    text = " ".join(str(chunk_text or "").split())
    if not text:
        return ""
    for marker in ("?", "？"):
        if marker in text:
            return text.split(marker, 1)[0][:180] + marker
    return text[:180]


def _cluster_role_for_score(score: float) -> str:
    if score >= 0.85:
        return "hub_or_core_reference"
    if score >= 0.7:
        return "supporting_reference"
    return "loose_related_reference"


def _writing_support_source_role(score: float) -> str:
    if score >= 0.85:
        return "primary_existing_coverage"
    if score >= 0.7:
        return "supporting_context"
    return "background_or_gap_signal"
