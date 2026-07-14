from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.orm import Session

from app.core.models import ProviderConnection, Site
from app.domain.site_knowledge.contracts import SiteKnowledgeContractViolation
from app.domain.site_knowledge.vector_profile_contract import (
    SITE_KNOWLEDGE_VECTOR_MODEL_ID,
    SITE_KNOWLEDGE_VECTOR_PROVIDER_ID,
    SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID,
)

SITE_KNOWLEDGE_MAINTENANCE_METADATA_KEY = "site_knowledge_maintenance"
SITE_KNOWLEDGE_MAINTENANCE_ACTION = "full_sync"
SITE_KNOWLEDGE_MAINTENANCE_REVISION = "site_knowledge_maintenance.v1"
ACTIVE_MAINTENANCE_LIFECYCLES = frozenset(
    {"reindex_required", "awaiting_site_sync", "rebuilding", "failed"}
)


def target_embedding_space_id() -> str:
    return f"{SITE_KNOWLEDGE_VECTOR_PROVIDER_ID}:{SITE_KNOWLEDGE_VECTOR_MODEL_ID}"


def maintenance_request_id(site_id: str, maintenance_revision: str = "legacy") -> str:
    seed = "|".join(
        (
            str(site_id or "").strip(),
            target_embedding_space_id(),
            str(maintenance_revision or "legacy").strip(),
            SITE_KNOWLEDGE_MAINTENANCE_REVISION,
        )
    )
    return "skm_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def project_site_maintenance(
    session: Session,
    *,
    site_id: str,
    indexed_embedding_models: list[str],
) -> dict[str, Any]:
    target_space = target_embedding_space_id()
    lifecycle = _maintenance_lifecycle(session)
    request_id = maintenance_request_id(
        site_id,
        str(lifecycle.get("maintenance_revision") or "legacy"),
    )
    state = _site_maintenance_state(session, site_id)
    state_matches = (
        str(state.get("request_id") or "") == request_id
        and str(state.get("target_embedding_space_id") or "") == target_space
    )
    state_status = str(state.get("status") or "") if state_matches else ""
    if state_status == "ready":
        return {
            "contract_version": SITE_KNOWLEDGE_MAINTENANCE_REVISION,
            "status": "not_required",
            "action": "none",
            "automatic": True,
            "request_id": "",
            "target_embedding_space_id": target_space,
            "completed_batches": 0,
            "total_batches": 0,
            "last_error_code": "",
        }
    if state_status in {"delivering", "blocked"}:
        return _projection(
            status=state_status,
            request_id=request_id,
            completed_batches=_positive_or_zero(state.get("completed_batches")),
            total_batches=_positive_or_zero(state.get("total_batches")),
            last_error_code=str(state.get("last_error_code") or ""),
        )

    indexed_models = {
        str(model or "").strip() for model in indexed_embedding_models if str(model or "").strip()
    }
    mismatch = any(model != target_space for model in indexed_models)
    if mismatch and str(lifecycle.get("status") or "") in ACTIVE_MAINTENANCE_LIFECYCLES:
        return _projection(
            status="awaiting_site",
            request_id=request_id,
            completed_batches=0,
            total_batches=0,
            last_error_code="",
        )

    return {
        "contract_version": SITE_KNOWLEDGE_MAINTENANCE_REVISION,
        "status": "not_required",
        "action": "none",
        "automatic": True,
        "request_id": "",
        "target_embedding_space_id": target_space,
        "completed_batches": 0,
        "total_batches": 0,
        "last_error_code": "",
    }


def validate_maintenance_batch(
    *,
    session: Session,
    site_id: str,
    input_payload: dict[str, Any],
    sync_mode: str,
) -> dict[str, Any] | None:
    value = input_payload.get("maintenance")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SiteKnowledgeContractViolation(
            "site_knowledge.invalid_maintenance",
            "site knowledge maintenance must be an object",
        )

    lifecycle = _maintenance_lifecycle(session)
    if str(lifecycle.get("status") or "") not in ACTIVE_MAINTENANCE_LIFECYCLES:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.maintenance_not_active",
            "site knowledge maintenance is not active for the fixed profile",
        )
    request_id = str(value.get("request_id") or "").strip()
    expected_request_id = maintenance_request_id(
        site_id,
        str(lifecycle.get("maintenance_revision") or "legacy"),
    )
    if request_id != expected_request_id:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.maintenance_request_mismatch",
            "site knowledge maintenance request does not match the active profile",
        )
    if str(value.get("action") or "") != SITE_KNOWLEDGE_MAINTENANCE_ACTION:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.maintenance_action_invalid",
            "site knowledge maintenance action must be full_sync",
        )

    batch_index = _bounded_int(value.get("batch_index"), minimum=0, maximum=9999)
    batch_count = _bounded_int(value.get("batch_count"), minimum=1, maximum=10000)
    is_final = bool(value.get("is_final"))
    if batch_index >= batch_count or is_final != (batch_index == batch_count - 1):
        raise SiteKnowledgeContractViolation(
            "site_knowledge.maintenance_batch_invalid",
            "site knowledge maintenance batch position is invalid",
        )
    expected_mode = "rebuild" if batch_index == 0 else "refresh"
    if sync_mode != expected_mode:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.maintenance_sync_mode_invalid",
            "site knowledge maintenance batches must start with rebuild and continue with refresh",
        )

    return {
        "request_id": request_id,
        "action": SITE_KNOWLEDGE_MAINTENANCE_ACTION,
        "batch_index": batch_index,
        "batch_count": batch_count,
        "is_final": is_final,
        "target_embedding_space_id": target_embedding_space_id(),
    }


def record_maintenance_batch(
    session: Session,
    *,
    site_id: str,
    maintenance: dict[str, Any],
    status: str,
    last_error_code: str = "",
) -> None:
    site = session.get(Site, site_id)
    if site is None:
        return
    metadata = dict(site.metadata_json) if isinstance(site.metadata_json, dict) else {}
    metadata[SITE_KNOWLEDGE_MAINTENANCE_METADATA_KEY] = {
        "contract_version": SITE_KNOWLEDGE_MAINTENANCE_REVISION,
        "status": status,
        "request_id": str(maintenance["request_id"]),
        "target_embedding_space_id": target_embedding_space_id(),
        "completed_batches": int(maintenance["batch_index"]) + (0 if status == "blocked" else 1),
        "total_batches": int(maintenance["batch_count"]),
        "last_error_code": str(last_error_code or ""),
    }
    site.metadata_json = metadata
    session.flush()


def _projection(
    *,
    status: str,
    request_id: str,
    completed_batches: int,
    total_batches: int,
    last_error_code: str,
) -> dict[str, Any]:
    return {
        "contract_version": SITE_KNOWLEDGE_MAINTENANCE_REVISION,
        "status": status,
        "action": SITE_KNOWLEDGE_MAINTENANCE_ACTION,
        "automatic": True,
        "request_id": request_id,
        "target_embedding_space_id": target_embedding_space_id(),
        "completed_batches": completed_batches,
        "total_batches": total_batches,
        "last_error_code": last_error_code,
    }


def _maintenance_lifecycle(session: Session) -> dict[str, Any]:
    row = session.get(ProviderConnection, SITE_KNOWLEDGE_VECTOR_STORE_CONNECTION_ID)
    if row is None or not row.enabled or row.status != "ready":
        return {}
    config = row.config_json if isinstance(row.config_json, dict) else {}
    lifecycle = config.get("site_knowledge_index_lifecycle")
    return lifecycle if isinstance(lifecycle, dict) else {}


def _site_maintenance_state(session: Session, site_id: str) -> dict[str, Any]:
    site = session.get(Site, site_id)
    metadata = (
        site.metadata_json if site is not None and isinstance(site.metadata_json, dict) else {}
    )
    value = metadata.get(SITE_KNOWLEDGE_MAINTENANCE_METADATA_KEY)
    return value if isinstance(value, dict) else {}


def _bounded_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as error:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.maintenance_batch_invalid",
            "site knowledge maintenance batch position is invalid",
        ) from error
    if normalized < minimum or normalized > maximum:
        raise SiteKnowledgeContractViolation(
            "site_knowledge.maintenance_batch_invalid",
            "site knowledge maintenance batch position is invalid",
        )
    return normalized


def _positive_or_zero(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
