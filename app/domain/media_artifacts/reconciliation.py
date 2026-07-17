from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import get_session
from app.core.models import MediaArtifact
from app.domain.media_artifacts.store import (
    ArtifactInventoryItem,
    ArtifactInventoryPage,
    ArtifactInventoryStore,
    ArtifactPublicationFenceStore,
    ArtifactStore,
)


class MediaArtifactReconciliationError(RuntimeError):
    error_code = "media_artifact.inventory_reconciliation_failed"

    def __init__(self) -> None:
        super().__init__("media artifact inventory reconciliation failed")


@dataclass(frozen=True, slots=True)
class MediaArtifactReconciliationEvidence:
    store_examined: int
    referenced_present: int
    orphan_observed: int
    orphan_deferred: int
    orphan_eligible: int
    db_available_examined: int
    referenced_missing: int
    deletion_enabled: bool
    publication_fence_supported: bool

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "store_examined": self.store_examined,
            "referenced_present": self.referenced_present,
            "orphan_observed": self.orphan_observed,
            "orphan_deferred": self.orphan_deferred,
            "orphan_eligible": self.orphan_eligible,
            "db_available_examined": self.db_available_examined,
            "referenced_missing": self.referenced_missing,
            "deletion_enabled": self.deletion_enabled,
            "publication_fence_supported": self.publication_fence_supported,
        }


class MediaArtifactReconciliationService:
    """Compares byte-store and database inventories without mutating either truth."""

    def __init__(self, database_url: str, *, artifact_store: ArtifactStore) -> None:
        self._database_url = database_url
        self._artifact_store = artifact_store

    def inspect_inventory(
        self,
        *,
        now: datetime | None = None,
        safety_window_seconds: int = 24 * 60 * 60,
        page_size: int = 200,
    ) -> MediaArtifactReconciliationEvidence:
        try:
            if (
                isinstance(page_size, bool)
                or not isinstance(page_size, int)
                or not 1 <= page_size <= 500
                or isinstance(safety_window_seconds, bool)
                or not isinstance(safety_window_seconds, int)
                or safety_window_seconds < 1
            ):
                raise MediaArtifactReconciliationError()
            if not isinstance(self._artifact_store, ArtifactInventoryStore):
                raise MediaArtifactReconciliationError()

            current_time = _as_utc(now or datetime.now(UTC))
            cutoff = current_time - timedelta(seconds=safety_window_seconds)
            store_counts = self._inspect_store_inventory(
                inventory_store=self._artifact_store,
                cutoff=cutoff,
                page_size=page_size,
            )
            database_counts = self._inspect_available_database_inventory(
                inventory_store=self._artifact_store,
                page_size=page_size,
            )
            return MediaArtifactReconciliationEvidence(
                **store_counts,
                **database_counts,
                deletion_enabled=False,
                publication_fence_supported=isinstance(
                    self._artifact_store,
                    ArtifactPublicationFenceStore,
                ),
            )
        except MediaArtifactReconciliationError:
            raise
        except Exception:
            raise MediaArtifactReconciliationError() from None

    def _inspect_store_inventory(
        self,
        *,
        inventory_store: ArtifactInventoryStore,
        cutoff: datetime,
        page_size: int,
    ) -> dict[str, int]:
        store_examined = 0
        referenced_present = 0
        orphan_observed = 0
        orphan_deferred = 0
        orphan_eligible = 0
        cursor: str | None = None
        last_storage_key: str | None = None
        seen_cursors: dict[str, None] = {}

        while True:
            page = inventory_store.list_objects(cursor=cursor, limit=page_size)
            items = _validated_page(
                page,
                cursor=cursor,
                last_storage_key=last_storage_key,
                page_size=page_size,
            )
            storage_keys = tuple(item.storage_key for item in items)
            referenced_keys: set[str] = set()
            if storage_keys:
                with get_session(self._database_url) as session:
                    referenced_keys = set(
                        session.scalars(
                            select(MediaArtifact.storage_key).where(
                                MediaArtifact.storage_key.in_(storage_keys)
                            )
                        )
                    )

            for item in items:
                store_examined += 1
                if item.storage_key in referenced_keys:
                    referenced_present += 1
                    continue
                orphan_observed += 1
                if _as_utc(item.last_modified_at) <= cutoff:
                    orphan_eligible += 1
                else:
                    orphan_deferred += 1

            if items:
                last_storage_key = items[-1].storage_key
            if page.next_cursor is None:
                break
            if (
                not isinstance(page.next_cursor, str)
                or not page.next_cursor
                or page.next_cursor in seen_cursors
            ):
                raise MediaArtifactReconciliationError()
            seen_cursors[page.next_cursor] = None
            cursor = page.next_cursor

        return {
            "store_examined": store_examined,
            "referenced_present": referenced_present,
            "orphan_observed": orphan_observed,
            "orphan_deferred": orphan_deferred,
            "orphan_eligible": orphan_eligible,
        }

    def _inspect_available_database_inventory(
        self,
        *,
        inventory_store: ArtifactInventoryStore,
        page_size: int,
    ) -> dict[str, int]:
        db_available_examined = 0
        referenced_missing = 0
        cursor: str | None = None

        while True:
            with get_session(self._database_url) as session:
                statement = (
                    select(MediaArtifact.storage_key)
                    .where(MediaArtifact.status == "available")
                    .order_by(MediaArtifact.storage_key.asc())
                    .limit(page_size)
                )
                if cursor is not None:
                    statement = statement.where(MediaArtifact.storage_key > cursor)
                storage_keys = tuple(session.scalars(statement))

            for storage_key in storage_keys:
                db_available_examined += 1
                if not inventory_store.contains(storage_key):
                    referenced_missing += 1

            if len(storage_keys) < page_size:
                break
            next_cursor = storage_keys[-1]
            if next_cursor == cursor:
                raise MediaArtifactReconciliationError()
            cursor = next_cursor

        return {
            "db_available_examined": db_available_examined,
            "referenced_missing": referenced_missing,
        }


def _validated_page(
    page: ArtifactInventoryPage,
    *,
    cursor: str | None,
    last_storage_key: str | None,
    page_size: int,
) -> tuple[ArtifactInventoryItem, ...]:
    items = tuple(page.items)
    if len(items) > page_size:
        raise MediaArtifactReconciliationError()
    storage_keys = tuple(item.storage_key for item in items)
    if storage_keys != tuple(sorted(set(storage_keys))):
        raise MediaArtifactReconciliationError()
    if last_storage_key is not None and storage_keys and storage_keys[0] <= last_storage_key:
        raise MediaArtifactReconciliationError()
    if page.next_cursor is not None and (
        not items or page.next_cursor == cursor
    ):
        raise MediaArtifactReconciliationError()
    return items


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
