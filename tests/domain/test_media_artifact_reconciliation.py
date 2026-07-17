from __future__ import annotations

import ast
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO

import pytest
from sqlalchemy.exc import StatementError

from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_engine, get_session, init_schema
from app.core.models import MediaArtifact
from app.domain.media_artifacts.reconciliation import (
    MediaArtifactReconciliationError,
    MediaArtifactReconciliationService,
)
from app.domain.media_artifacts.store import (
    ArtifactInventoryItem,
    ArtifactInventoryPage,
    ArtifactStorageMetadata,
)
from tests.conftest import seed_site_auth

ROOT = Path(__file__).resolve().parents[2]


class _InventoryStore:
    chunk_size = 4096

    def __init__(
        self,
        items: tuple[ArtifactInventoryItem, ...],
        *,
        present_keys: set[str] | None = None,
        before_list: Callable[[], None] | None = None,
        before_contains: Callable[[], None] | None = None,
    ) -> None:
        self.items = tuple(sorted(items, key=lambda item: item.storage_key))
        self.present_keys = present_keys or {item.storage_key for item in items}
        self.before_list = before_list
        self.before_contains = before_contains
        self.list_calls: list[tuple[str | None, int]] = []
        self.contains_calls: list[str] = []
        self.delete_calls: list[str] = []

    def list_objects(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> ArtifactInventoryPage:
        if self.before_list is not None:
            self.before_list()
        self.list_calls.append((cursor, limit))
        remaining = tuple(
            item for item in self.items if cursor is None or item.storage_key > cursor
        )
        page_items = remaining[:limit]
        next_cursor = (
            page_items[-1].storage_key if len(remaining) > len(page_items) else None
        )
        return ArtifactInventoryPage(items=page_items, next_cursor=next_cursor)

    def contains(self, storage_key: str) -> bool:
        if self.before_contains is not None:
            self.before_contains()
        self.contains_calls.append(storage_key)
        return storage_key in self.present_keys

    def put(
        self,
        stream: BinaryIO,
        *,
        max_bytes: int,
        metadata: Mapping[str, str] | None = None,
    ) -> ArtifactStorageMetadata:
        del stream, max_bytes, metadata
        raise AssertionError("reconciliation must not publish objects")

    def open(self, storage_key: str) -> BinaryIO:
        raise AssertionError(f"reconciliation must not open {storage_key}")

    def delete(self, storage_key: str) -> None:
        self.delete_calls.append(storage_key)
        raise AssertionError("C2a reconciliation must not delete objects")

    def metadata(self, storage_key: str) -> ArtifactStorageMetadata:
        raise AssertionError(f"reconciliation must not hash {storage_key}")


class _FencedInventoryStore(_InventoryStore):
    def acquire_publication_guard(self) -> object:
        raise AssertionError("read-only reconciliation must not acquire a shared guard")

    def try_acquire_reconciliation_guard(self) -> None:
        raise AssertionError("C2a reconciliation must not acquire a deletion fence")


@pytest.fixture
def reconciliation_database(tmp_path: Path) -> Iterator[str]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'artifact-reconciliation.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_reconciliation")
    with get_session(database_url) as session:
        RuntimeRepository(session).create_run(
            run_id="run_artifact_reconciliation",
            site_id="site_reconciliation",
            account_id=None,
            subscription_id=None,
            plan_version_id=None,
            ability_name="npcink-cloud/media-reconciliation-test",
            ability_family="media",
            skill_id=None,
            workflow_id=None,
            contract_version="media_reconciliation_test.v1",
            channel="internal",
            execution_kind="media",
            execution_tier="cloud",
            execution_pattern="inline",
            data_classification="internal",
            profile_id="media.reconciliation.test",
            canonical_run_id=None,
            status="succeeded",
            idempotency_key="idem-artifact-reconciliation",
            request_fingerprint="fingerprint-artifact-reconciliation",
            trace_id="trace-artifact-reconciliation",
            input_json={},
            execution_input_ciphertext=None,
            policy_json={"storage_mode": "result_only"},
        )
        session.commit()
    yield database_url
    dispose_engine(database_url)


def _artifact(storage_key: str, *, status: str, now: datetime) -> MediaArtifact:
    suffix = storage_key.removeprefix("obj_")
    return MediaArtifact(
        artifact_id=f"art_{suffix}",
        run_id="run_artifact_reconciliation",
        site_id="site_reconciliation",
        media_kind="image",
        operation="image.transform.v1",
        content_type="image/png",
        byte_size=7,
        storage_key=storage_key,
        status=status,
        format="png",
        width=1,
        height=1,
        checksum="sha256:" + ("a" * 64),
        expires_at=now + timedelta(days=1),
        created_at=now - timedelta(days=1),
    )


def _item(storage_key: str, *, modified_at: datetime) -> ArtifactInventoryItem:
    return ArtifactInventoryItem(
        storage_key=storage_key,
        byte_size=7,
        last_modified_at=modified_at,
    )


def test_reconciliation_is_bidirectional_paginated_read_only_and_conservative(
    reconciliation_database: str,
) -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    present_available = "obj_00000000000000000000000000000031"
    present_purged = "obj_00000000000000000000000000000032"
    orphan_at_cutoff = "obj_00000000000000000000000000000033"
    orphan_inside_window = "obj_00000000000000000000000000000034"
    missing_available = "obj_00000000000000000000000000000035"
    with get_session(reconciliation_database) as session:
        session.add_all(
            (
                _artifact(present_available, status="available", now=now),
                _artifact(present_purged, status="purged", now=now),
                _artifact(missing_available, status="available", now=now),
            )
        )
        session.commit()

    engine = get_engine(reconciliation_database)

    def assert_no_database_connection_held() -> None:
        assert engine.pool.checkedout() == 0  # type: ignore[attr-defined]

    store = _FencedInventoryStore(
        (
            _item(present_available, modified_at=now - timedelta(days=2)),
            _item(present_purged, modified_at=now - timedelta(days=2)),
            _item(orphan_at_cutoff, modified_at=now - timedelta(days=1)),
            _item(orphan_inside_window, modified_at=now - timedelta(hours=23)),
        ),
        present_keys={
            present_available,
            present_purged,
            orphan_at_cutoff,
            orphan_inside_window,
        },
        before_list=assert_no_database_connection_held,
        before_contains=assert_no_database_connection_held,
    )

    evidence = MediaArtifactReconciliationService(
        reconciliation_database,
        artifact_store=store,
    ).inspect_inventory(now=now, safety_window_seconds=86400, page_size=2)

    assert evidence.as_dict() == {
        "store_examined": 4,
        "referenced_present": 2,
        "orphan_observed": 2,
        "orphan_deferred": 1,
        "orphan_eligible": 1,
        "db_available_examined": 2,
        "referenced_missing": 1,
        "deletion_enabled": False,
        "publication_fence_supported": True,
    }
    assert evidence.store_examined == evidence.referenced_present + evidence.orphan_observed
    assert evidence.orphan_observed == evidence.orphan_deferred + evidence.orphan_eligible
    assert evidence.referenced_missing <= evidence.db_available_examined
    assert len(store.list_calls) == 2
    assert store.contains_calls == [present_available, missing_available]
    assert store.delete_calls == []

    with get_session(reconciliation_database) as session:
        statuses = {
            item.storage_key: item.status
            for item in session.query(MediaArtifact).order_by(MediaArtifact.storage_key)
        }
    assert statuses == {
        present_available: "available",
        present_purged: "purged",
        missing_available: "available",
    }


def test_reconciliation_rejects_unsupported_store_and_malformed_pages(
    reconciliation_database: str,
) -> None:
    class UnsupportedStore:
        chunk_size = 4096

    with pytest.raises(MediaArtifactReconciliationError) as unsupported:
        MediaArtifactReconciliationService(
            reconciliation_database,
            artifact_store=UnsupportedStore(),  # type: ignore[arg-type]
        ).inspect_inventory()
    assert str(unsupported.value) == "media artifact inventory reconciliation failed"

    storage_key = "obj_00000000000000000000000000000041"

    class MalformedStore(_InventoryStore):
        def list_objects(
            self,
            *,
            cursor: str | None = None,
            limit: int = 100,
        ) -> ArtifactInventoryPage:
            del limit
            items = (
                ()
                if cursor is not None
                else (_item(storage_key, modified_at=datetime.now(UTC)),)
            )
            return ArtifactInventoryPage(
                items=items,
                next_cursor=storage_key,
            )

    with pytest.raises(MediaArtifactReconciliationError):
        MediaArtifactReconciliationService(
            reconciliation_database,
            artifact_store=MalformedStore(()),
        ).inspect_inventory(page_size=1)

    class CyclingCursorStore(_InventoryStore):
        def __init__(self) -> None:
            super().__init__(())
            self.calls = 0

        def list_objects(
            self,
            *,
            cursor: str | None = None,
            limit: int = 100,
        ) -> ArtifactInventoryPage:
            del cursor, limit
            keys = (
                "obj_00000000000000000000000000000051",
                "obj_00000000000000000000000000000052",
                "obj_00000000000000000000000000000053",
            )
            tokens = ("opaque-page-one", "opaque-page-two", "opaque-page-one")
            index = self.calls
            self.calls += 1
            return ArtifactInventoryPage(
                items=(_item(keys[index], modified_at=datetime.now(UTC)),),
                next_cursor=tokens[index],
            )

    with pytest.raises(MediaArtifactReconciliationError):
        MediaArtifactReconciliationService(
            reconciliation_database,
            artifact_store=CyclingCursorStore(),
        ).inspect_inventory(page_size=1)


def test_reconciliation_normalizes_private_failures_but_preserves_base_exception(
    reconciliation_database: str,
) -> None:
    private_statement = "SELECT storage_key FROM /private/tenant/media_artifacts"
    private_key = "private/customer/object.png"

    class DatabaseDetailStore(_InventoryStore):
        def list_objects(
            self,
            *,
            cursor: str | None = None,
            limit: int = 100,
        ) -> ArtifactInventoryPage:
            del cursor, limit
            raise StatementError(
                "private database detail",
                private_statement,
                {"storage_key": private_key},
                RuntimeError("private driver detail"),
            )

    with pytest.raises(MediaArtifactReconciliationError) as caught:
        MediaArtifactReconciliationService(
            reconciliation_database,
            artifact_store=DatabaseDetailStore(()),
        ).inspect_inventory()
    observed = str(caught.value)
    assert caught.value.error_code == "media_artifact.inventory_reconciliation_failed"
    assert observed == "media artifact inventory reconciliation failed"
    assert private_statement not in observed
    assert private_key not in observed
    assert caught.value.__cause__ is None

    class FatalInventory(BaseException):
        pass

    failure = FatalInventory("exact fatal inventory failure")

    class FatalStore(_InventoryStore):
        def list_objects(
            self,
            *,
            cursor: str | None = None,
            limit: int = 100,
        ) -> ArtifactInventoryPage:
            del cursor, limit
            raise failure

    with pytest.raises(FatalInventory) as fatal:
        MediaArtifactReconciliationService(
            reconciliation_database,
            artifact_store=FatalStore(()),
        ).inspect_inventory()
    assert fatal.value is failure


def test_reconciliation_validation_rejects_unbounded_requests(
    reconciliation_database: str,
) -> None:
    service = MediaArtifactReconciliationService(
        reconciliation_database,
        artifact_store=_InventoryStore(()),
    )
    for kwargs in (
        {"page_size": 0},
        {"page_size": 501},
        {"safety_window_seconds": 0},
    ):
        with pytest.raises(MediaArtifactReconciliationError):
            service.inspect_inventory(**kwargs)


def test_c2a_reconciliation_source_has_no_delete_or_mutating_database_path() -> None:
    tree = ast.parse(
        (ROOT / "app/domain/media_artifacts/reconciliation.py").read_text(
            encoding="utf-8"
        )
    )
    forbidden_method_calls = {
        "delete",
        "add",
        "add_all",
        "commit",
        "execute",
        "flush",
        "acquire_publication_guard",
        "try_acquire_reconciliation_guard",
    }
    observed = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert observed.isdisjoint(forbidden_method_calls)
