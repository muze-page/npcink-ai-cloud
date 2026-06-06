from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.domain.agent_feedback.contracts import (
    AGENT_FEEDBACK_CONTRACT_VERSION,
    ALLOWED_AGENT_FEEDBACK_LABELS,
    ALLOWED_AGENT_FEEDBACK_OUTCOMES,
    find_forbidden_agent_feedback_field,
)
from app.domain.agent_feedback.service import AgentFeedbackService

router = APIRouter(prefix="/v1/agent-feedback", tags=["agent-feedback"])


class AgentFeedbackPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["cloud_agent_feedback.v1"] = AGENT_FEEDBACK_CONTRACT_VERSION
    site_id: str | None = Field(default=None, max_length=191)
    agent_id: str = Field(min_length=1, max_length=96)
    agent_version: str = Field(default="", max_length=64)
    source_runtime: str = Field(min_length=1, max_length=64)
    source_run_id: str = Field(default="", max_length=191)
    handoff_id: str = Field(default="", max_length=191)
    handoff_type: str = Field(min_length=1, max_length=64)
    local_surface: str = Field(min_length=1, max_length=96)
    local_outcome: str = Field(min_length=1, max_length=64)
    feedback_labels: list[str] = Field(default_factory=list, max_length=12)
    operator_note: str = Field(default="", max_length=500)
    local_proposal_id: str = Field(default="", max_length=191)
    evidence_ref_ids: list[str] = Field(default_factory=list, max_length=24)
    redaction_status: str = Field(default="", max_length=64)
    retention_class: str = Field(default="", max_length=64)
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def reject_feedback_write_authority(cls, value: Any) -> Any:
        forbidden_path = find_forbidden_agent_feedback_field(value)
        if forbidden_path:
            raise ValueError(
                "agent feedback may not carry approval, preflight, or write authority: "
                + forbidden_path
            )
        return value

    @field_validator("local_outcome")
    @classmethod
    def validate_outcome(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in ALLOWED_AGENT_FEEDBACK_OUTCOMES:
            raise ValueError("local_outcome is not supported")
        return normalized

    @field_validator("feedback_labels")
    @classmethod
    def validate_feedback_labels(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            label = str(item or "").strip()
            if not label:
                continue
            if label not in ALLOWED_AGENT_FEEDBACK_LABELS:
                raise ValueError(f"feedback label is not supported: {label}")
            if label not in normalized:
                normalized.append(label)
        return normalized

    @field_validator("evidence_ref_ids")
    @classmethod
    def normalize_evidence_ref_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            ref_id = str(item or "").strip()
            if ref_id and ref_id not in normalized:
                normalized.append(ref_id[:191])
        return normalized


def _get_feedback_service(request: Request) -> AgentFeedbackService:
    services = get_cloud_services(request)
    return AgentFeedbackService(services.settings.database_url)


@router.post("/events")
async def record_agent_feedback(
    request: Request,
    payload: AgentFeedbackPayload,
) -> Any:
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth

    payload_data = payload.model_dump(mode="json", exclude_none=True)
    payload_data["site_id"] = auth.site_id
    result = await run_in_threadpool(
        _get_feedback_service(request).record_event,
        site_id=auth.site_id,
        idempotency_key=auth.idempotency_key,
        trace_id=auth.trace_id,
        payload=payload_data,
    )

    return build_envelope(
        status="ok",
        message="agent feedback accepted for eval",
        data=result,
        trace_id=auth.trace_id,
        revision="m1",
    )
