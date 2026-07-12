from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.models import RunRecord, SiteKnowledgeChunk, SiteKnowledgeDocument


class SiteKnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _rowcount(self, result: object) -> int:
        return int(getattr(result, "rowcount", 0) or 0)

    def delete_site_index(self, site_id: str) -> int:
        chunk_result = self.session.execute(
            delete(SiteKnowledgeChunk).where(SiteKnowledgeChunk.site_id == site_id)
        )
        document_result = self.session.execute(
            delete(SiteKnowledgeDocument).where(SiteKnowledgeDocument.site_id == site_id)
        )
        self.session.flush()
        return self._rowcount(chunk_result) + self._rowcount(document_result)

    def delete_post_indexes(self, site_id: str, post_ids: list[int]) -> int:
        normalized_post_ids = [post_id for post_id in post_ids if post_id > 0]
        if not normalized_post_ids:
            return 0
        chunk_result = self.session.execute(
            delete(SiteKnowledgeChunk).where(
                SiteKnowledgeChunk.site_id == site_id,
                SiteKnowledgeChunk.post_id.in_(normalized_post_ids),
            )
        )
        comment_chunk_result = self.session.execute(
            delete(SiteKnowledgeChunk).where(
                SiteKnowledgeChunk.site_id == site_id,
                SiteKnowledgeChunk.parent_post_id.in_(normalized_post_ids),
            )
        )
        document_result = self.session.execute(
            delete(SiteKnowledgeDocument).where(
                SiteKnowledgeDocument.site_id == site_id,
                SiteKnowledgeDocument.post_id.in_(normalized_post_ids),
            )
        )
        comment_document_result = self.session.execute(
            delete(SiteKnowledgeDocument).where(
                SiteKnowledgeDocument.site_id == site_id,
                SiteKnowledgeDocument.parent_post_id.in_(normalized_post_ids),
            )
        )
        self.session.flush()
        return (
            self._rowcount(chunk_result)
            + self._rowcount(comment_chunk_result)
            + self._rowcount(document_result)
            + self._rowcount(comment_document_result)
        )

    def upsert_document_with_chunks(
        self,
        *,
        site_id: str,
        post_id: int,
        source_type: str,
        source_id: int,
        parent_post_id: int | None,
        post_type: str,
        post_status: str,
        title: str,
        url: str,
        modified_gmt: str,
        content_hash: str,
        run_id: str,
        metadata: dict[str, Any] | None = None,
        chunks: list[dict[str, Any]],
    ) -> None:
        now = datetime.now(UTC)
        document_metadata = metadata if isinstance(metadata, dict) else {}
        document = self.session.scalar(
            select(SiteKnowledgeDocument).where(
                SiteKnowledgeDocument.site_id == site_id,
                SiteKnowledgeDocument.source_type == source_type,
                SiteKnowledgeDocument.source_id == source_id,
            )
        )
        if document is None:
            document = SiteKnowledgeDocument(
                site_id=site_id,
                post_id=post_id,
                source_type=source_type,
                source_id=source_id,
                parent_post_id=parent_post_id,
                post_type=post_type,
                post_status=post_status,
                title=title,
                url=url,
                modified_gmt=modified_gmt,
                content_hash=content_hash,
                last_sync_run_id=run_id,
                metadata_json=document_metadata,
                last_indexed_at=now,
            )
            self.session.add(document)
        else:
            document.post_type = post_type
            document.source_type = source_type
            document.source_id = source_id
            document.parent_post_id = parent_post_id
            document.post_status = post_status
            document.title = title
            document.url = url
            document.modified_gmt = modified_gmt
            document.content_hash = content_hash
            document.last_sync_run_id = run_id
            document.metadata_json = document_metadata
            document.last_indexed_at = now

        self.session.execute(
            delete(SiteKnowledgeChunk).where(
                SiteKnowledgeChunk.site_id == site_id,
                SiteKnowledgeChunk.source_type == source_type,
                SiteKnowledgeChunk.source_id == source_id,
            )
        )
        for chunk in chunks:
            metadata = chunk.get("metadata")
            self.session.add(
                SiteKnowledgeChunk(
                    site_id=site_id,
                    post_id=post_id,
                    source_type=source_type,
                    source_id=source_id,
                    parent_post_id=parent_post_id,
                    chunk_index=int(chunk["chunk_index"]),
                    post_type=post_type,
                    post_status=post_status,
                    title=title,
                    url=url,
                    chunk_text=str(chunk["chunk_text"]),
                    embedding_json=list(chunk["embedding"]),
                    embedding_model=str(chunk["embedding_model"]),
                    content_hash=content_hash,
                    metadata_json=metadata if isinstance(metadata, dict) else {},
                    indexed_at=now,
                )
            )
        self.session.flush()

    def count_documents(self, site_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(SiteKnowledgeDocument)
                .where(SiteKnowledgeDocument.site_id == site_id)
            )
            or 0
        )

    def count_chunks(self, site_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(SiteKnowledgeChunk)
                .where(SiteKnowledgeChunk.site_id == site_id)
            )
            or 0
        )

    def document_exists(self, *, site_id: str, source_type: str, source_id: int) -> bool:
        count = self.session.scalar(
            select(func.count())
            .select_from(SiteKnowledgeDocument)
            .where(
                SiteKnowledgeDocument.site_id == site_id,
                SiteKnowledgeDocument.source_type == source_type,
                SiteKnowledgeDocument.source_id == source_id,
            )
        )
        return int(count or 0) > 0

    def count_chunks_for_source(self, *, site_id: str, source_type: str, source_id: int) -> int:
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(SiteKnowledgeChunk)
                .where(
                    SiteKnowledgeChunk.site_id == site_id,
                    SiteKnowledgeChunk.source_type == source_type,
                    SiteKnowledgeChunk.source_id == source_id,
                )
            )
            or 0
        )

    def count_truncated_documents(self, site_id: str) -> int:
        documents = self.session.scalars(
            select(SiteKnowledgeDocument.metadata_json).where(
                SiteKnowledgeDocument.site_id == site_id
            )
        )
        return sum(
            1
            for metadata in documents
            if isinstance(metadata, dict) and metadata.get("truncated") is True
        )

    def reference_metadata_for_post_ids(
        self,
        *,
        site_id: str,
        post_ids: list[int],
    ) -> dict[int, dict[str, Any]]:
        normalized_ids = list(dict.fromkeys(post_id for post_id in post_ids if post_id > 0))
        if not normalized_ids:
            return {}
        rows = self.session.execute(
            select(
                SiteKnowledgeDocument.post_id,
                SiteKnowledgeDocument.title,
                SiteKnowledgeDocument.metadata_json,
            ).where(
                SiteKnowledgeDocument.site_id == site_id,
                SiteKnowledgeDocument.post_id.in_(normalized_ids),
                SiteKnowledgeDocument.post_status == "publish",
            )
        ).all()
        metadata_by_post_id = {
            int(post_id): {
                "title": str(title or ""),
                **(metadata if isinstance(metadata, dict) else {}),
            }
            for post_id, title, metadata in rows
        }
        return {
            post_id: metadata_by_post_id[post_id]
            for post_id in normalized_ids
            if post_id in metadata_by_post_id
        }

    def last_sync_at(self, site_id: str) -> datetime | None:
        return self.session.scalar(
            select(func.max(SiteKnowledgeDocument.last_indexed_at)).where(
                SiteKnowledgeDocument.site_id == site_id
            )
        )

    def post_type_counts(self, site_id: str) -> dict[str, int]:
        rows = self.session.execute(
            select(SiteKnowledgeDocument.post_type, func.count())
            .where(SiteKnowledgeDocument.site_id == site_id)
            .group_by(SiteKnowledgeDocument.post_type)
        ).all()
        return {str(post_type): int(count or 0) for post_type, count in rows}

    def source_type_counts(self, site_id: str) -> dict[str, int]:
        rows = self.session.execute(
            select(SiteKnowledgeDocument.source_type, func.count())
            .where(SiteKnowledgeDocument.site_id == site_id)
            .group_by(SiteKnowledgeDocument.source_type)
        ).all()
        return {str(source_type): int(count or 0) for source_type, count in rows}

    def has_running_sync(self, site_id: str) -> bool:
        count = self.session.scalar(
            select(func.count())
            .select_from(RunRecord)
            .where(
                RunRecord.site_id == site_id,
                RunRecord.ability_name == "npcink-cloud/site-knowledge-sync",
                RunRecord.status.in_(("queued", "running")),
            )
        )
        return int(count or 0) > 0

    def latest_active_sync(self, site_id: str) -> RunRecord | None:
        return self.session.scalar(
            select(RunRecord)
            .where(
                RunRecord.site_id == site_id,
                RunRecord.ability_name == "npcink-cloud/site-knowledge-sync",
                RunRecord.status.in_(("queued", "running")),
            )
            .order_by(
                RunRecord.processing_started_at.desc(),
                RunRecord.started_at.desc(),
                RunRecord.run_id.desc(),
            )
            .limit(1)
        )

    def latest_failed_sync(self, site_id: str) -> RunRecord | None:
        return self.session.scalar(
            select(RunRecord)
            .where(
                RunRecord.site_id == site_id,
                RunRecord.ability_name == "npcink-cloud/site-knowledge-sync",
                RunRecord.status == "failed",
            )
            .order_by(RunRecord.finished_at.desc(), RunRecord.started_at.desc())
            .limit(1)
        )

    def list_search_chunks(
        self,
        *,
        site_id: str,
        post_types: list[str],
        statuses: list[str],
        source_types: list[str],
        current_post_id: int,
        limit: int,
    ) -> list[SiteKnowledgeChunk]:
        statement = select(SiteKnowledgeChunk).where(SiteKnowledgeChunk.site_id == site_id)
        if post_types:
            statement = statement.where(SiteKnowledgeChunk.post_type.in_(post_types))
        if statuses:
            statement = statement.where(SiteKnowledgeChunk.post_status.in_(statuses))
        if source_types:
            statement = statement.where(SiteKnowledgeChunk.source_type.in_(source_types))
        if current_post_id > 0:
            statement = statement.where(SiteKnowledgeChunk.post_id != current_post_id)
        return list(
            self.session.scalars(
                statement.order_by(SiteKnowledgeChunk.indexed_at.desc()).limit(max(1, limit))
            )
        )
