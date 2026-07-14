from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.models import ProviderConnection, Site
from app.domain.site_knowledge.contracts import SiteKnowledgeContractViolation
from app.domain.site_knowledge.maintenance import (
    maintenance_request_id,
    project_site_maintenance,
    record_maintenance_batch,
    target_embedding_space_id,
    validate_maintenance_batch,
)


class FakeSession:
    def __init__(self) -> None:
        self.site = SimpleNamespace(site_id="site-1", metadata_json={})
        self.vector_store = SimpleNamespace(
            enabled=True,
            status="ready",
            config_json={"site_knowledge_index_lifecycle": {"status": "awaiting_site_sync"}},
        )
        self.flushed = False

    def get(self, model: object, key: str) -> object | None:
        if model is Site and key == "site-1":
            return self.site
        if model is ProviderConnection:
            return self.vector_store
        return None

    def flush(self) -> None:
        self.flushed = True


def test_status_projects_server_owned_automatic_full_sync_request() -> None:
    session = FakeSession()

    projected = project_site_maintenance(
        session,  # type: ignore[arg-type]
        site_id="site-1",
        indexed_embedding_models=["deterministic:old-model"],
    )

    assert projected == {
        "contract_version": "site_knowledge_maintenance.v1",
        "status": "awaiting_site",
        "action": "full_sync",
        "automatic": True,
        "request_id": maintenance_request_id("site-1"),
        "target_embedding_space_id": target_embedding_space_id(),
        "completed_batches": 0,
        "total_batches": 0,
        "last_error_code": "",
    }


def test_maintenance_batch_rejects_forged_request_id() -> None:
    with pytest.raises(SiteKnowledgeContractViolation) as caught:
        validate_maintenance_batch(
            session=FakeSession(),  # type: ignore[arg-type]
            site_id="site-1",
            sync_mode="rebuild",
            input_payload={
                "maintenance": {
                    "action": "full_sync",
                    "request_id": "skm_forged",
                    "batch_index": 0,
                    "batch_count": 1,
                    "is_final": True,
                }
            },
        )

    assert caught.value.error_code == "site_knowledge.maintenance_request_mismatch"


def test_maintenance_batch_is_rejected_after_lifecycle_is_ready() -> None:
    session = FakeSession()
    session.vector_store.config_json["site_knowledge_index_lifecycle"]["status"] = "ready"

    with pytest.raises(SiteKnowledgeContractViolation) as caught:
        validate_maintenance_batch(
            session=session,  # type: ignore[arg-type]
            site_id="site-1",
            sync_mode="rebuild",
            input_payload={
                "maintenance": {
                    "action": "full_sync",
                    "request_id": maintenance_request_id("site-1"),
                    "batch_index": 0,
                    "batch_count": 1,
                    "is_final": True,
                }
            },
        )

    assert caught.value.error_code == "site_knowledge.maintenance_not_active"


def test_recorded_delivery_progress_remains_visible_after_first_batch() -> None:
    session = FakeSession()
    maintenance = validate_maintenance_batch(
        session=session,  # type: ignore[arg-type]
        site_id="site-1",
        sync_mode="rebuild",
        input_payload={
            "maintenance": {
                "action": "full_sync",
                "request_id": maintenance_request_id("site-1"),
                "batch_index": 0,
                "batch_count": 3,
                "is_final": False,
            }
        },
    )
    assert maintenance is not None

    record_maintenance_batch(
        session,  # type: ignore[arg-type]
        site_id="site-1",
        maintenance=maintenance,
        status="delivering",
    )
    projected = project_site_maintenance(
        session,  # type: ignore[arg-type]
        site_id="site-1",
        indexed_embedding_models=[target_embedding_space_id()],
    )

    assert session.flushed is True
    assert projected["status"] == "delivering"
    assert projected["completed_batches"] == 1
    assert projected["total_batches"] == 3


def test_maintenance_rejects_a_final_batch_before_earlier_batches() -> None:
    with pytest.raises(SiteKnowledgeContractViolation) as caught:
        validate_maintenance_batch(
            session=FakeSession(),  # type: ignore[arg-type]
            site_id="site-1",
            sync_mode="refresh",
            input_payload={
                "maintenance": {
                    "action": "full_sync",
                    "request_id": maintenance_request_id("site-1"),
                    "batch_index": 2,
                    "batch_count": 3,
                    "is_final": True,
                }
            },
        )

    assert caught.value.error_code == "site_knowledge.maintenance_batch_invalid"


def test_maintenance_rejects_skipped_and_recounted_batches() -> None:
    session = FakeSession()
    first_batch = validate_maintenance_batch(
        session=session,  # type: ignore[arg-type]
        site_id="site-1",
        sync_mode="rebuild",
        input_payload={
            "maintenance": {
                "action": "full_sync",
                "request_id": maintenance_request_id("site-1"),
                "batch_index": 0,
                "batch_count": 3,
                "is_final": False,
            }
        },
    )
    assert first_batch is not None
    record_maintenance_batch(
        session,  # type: ignore[arg-type]
        site_id="site-1",
        maintenance=first_batch,
        status="delivering",
    )

    for batch_index, batch_count in ((2, 3), (1, 4)):
        with pytest.raises(SiteKnowledgeContractViolation) as caught:
            validate_maintenance_batch(
                session=session,  # type: ignore[arg-type]
                site_id="site-1",
                sync_mode="refresh",
                input_payload={
                    "maintenance": {
                        "action": "full_sync",
                        "request_id": maintenance_request_id("site-1"),
                        "batch_index": batch_index,
                        "batch_count": batch_count,
                        "is_final": False,
                    }
                },
            )
        assert caught.value.error_code == "site_knowledge.maintenance_batch_invalid"


def test_maintenance_requires_a_json_boolean_for_final_marker() -> None:
    with pytest.raises(SiteKnowledgeContractViolation) as caught:
        validate_maintenance_batch(
            session=FakeSession(),  # type: ignore[arg-type]
            site_id="site-1",
            sync_mode="rebuild",
            input_payload={
                "maintenance": {
                    "action": "full_sync",
                    "request_id": maintenance_request_id("site-1"),
                    "batch_index": 0,
                    "batch_count": 2,
                    "is_final": "false",
                }
            },
        )

    assert caught.value.error_code == "site_knowledge.maintenance_batch_invalid"
