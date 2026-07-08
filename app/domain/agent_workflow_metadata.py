from __future__ import annotations

from dataclasses import dataclass

METADATA_PROJECTION_VERSION = "cloud-agent-workflow-metadata.v1"


@dataclass(frozen=True)
class StatusBadge:
    label: str
    status: str

    def to_dict(self) -> dict[str, str]:
        return {
            "label": self.label,
            "status": self.status,
        }


@dataclass(frozen=True)
class AgentHandoffMetadata:
    agent_id: str
    agent_version: str
    agent_role: str
    handoff_type: str
    handoff_owner: str
    requires_operator_review: bool
    direct_wordpress_write: bool
    execution_pattern: str
    storage_mode: str
    allowed_actions: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    fail_closed_behavior: str

    def to_dict(self, *, agent_role: str | None = None) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "agent_role": agent_role or self.agent_role,
            "handoff_type": self.handoff_type,
            "handoff_owner": self.handoff_owner,
            "requires_operator_review": self.requires_operator_review,
            "direct_wordpress_write": self.direct_wordpress_write,
            "execution_pattern": self.execution_pattern,
            "storage_mode": self.storage_mode,
            "allowed_actions": list(self.allowed_actions),
            "stop_conditions": list(self.stop_conditions),
            "forbidden_actions": list(self.forbidden_actions),
            "fail_closed_behavior": self.fail_closed_behavior,
        }


@dataclass(frozen=True)
class WorkflowMetadata:
    workflow_id: str
    workflow_version: str
    title: str
    summary: str
    ability_name: str
    contract: str
    owner: str
    handoff_owner: str
    execution_pattern: str
    storage_mode: str
    badges: tuple[StatusBadge, ...]
    steps: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    direct_wordpress_write: bool
    requires_operator_review: bool
    fail_closed_behavior: str

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_version": self.workflow_version,
            "title": self.title,
            "summary": self.summary,
            "ability_name": self.ability_name,
            "contract": self.contract,
            "owner": self.owner,
            "handoff_owner": self.handoff_owner,
            "execution_pattern": self.execution_pattern,
            "storage_mode": self.storage_mode,
            "badges": [badge.to_dict() for badge in self.badges],
            "steps": list(self.steps),
            "stop_conditions": list(self.stop_conditions),
            "direct_wordpress_write": self.direct_wordpress_write,
            "requires_operator_review": self.requires_operator_review,
            "fail_closed_behavior": self.fail_closed_behavior,
        }


INTERNAL_OPS_ADVISOR_AGENT_ID = "internal_ops_advisor_agent"
SITE_KNOWLEDGE_SUGGESTION_AGENT_ID = "site_knowledge_suggestion_agent"
WEB_SEARCH_EVIDENCE_WORKFLOW_ID = "external_web_evidence_preflight"
MEDIA_DERIVATIVE_WORKFLOW_ID = "media_derivative_artifact_generation"


_AGENTS: dict[str, AgentHandoffMetadata] = {
    INTERNAL_OPS_ADVISOR_AGENT_ID: AgentHandoffMetadata(
        agent_id=INTERNAL_OPS_ADVISOR_AGENT_ID,
        agent_version="internal_ops_advisor_agent.v1",
        agent_role="runtime_operations",
        handoff_type="operator_recommendation",
        handoff_owner="cloud_internal_operator",
        requires_operator_review=True,
        direct_wordpress_write=False,
        execution_pattern="inline",
        storage_mode="result_only",
        allowed_actions=(
            "read_cloud_service_evidence",
            "rank_operator_attention_items",
            "return_evidence_backed_recommendation",
        ),
        stop_conditions=(
            "insufficient_evidence",
            "operator_action_required",
            "forbidden_mutation_detected",
        ),
        forbidden_actions=(
            "direct_wordpress_write",
            "automatic_routing_profile_adoption",
            "automatic_commercial_state_mutation",
            "cloud_prompt_or_preset_truth",
            "cloud_workflow_truth",
        ),
        fail_closed_behavior="return_deterministic_advisory_summary",
    ),
    SITE_KNOWLEDGE_SUGGESTION_AGENT_ID: AgentHandoffMetadata(
        agent_id=SITE_KNOWLEDGE_SUGGESTION_AGENT_ID,
        agent_version="site_knowledge_agent.v1",
        agent_role="site_knowledge_suggestion",
        handoff_type="suggestion_or_proposal_input",
        handoff_owner="wordpress_local",
        requires_operator_review=True,
        direct_wordpress_write=False,
        execution_pattern="inline",
        storage_mode="result_only",
        allowed_actions=(
            "search_site_knowledge_read_model",
            "rank_grounding_evidence",
            "return_suggestion_or_proposal_input",
        ),
        stop_conditions=(
            "evidence_gate_insufficient",
            "no_allowed_next_action",
            "local_approval_required",
        ),
        forbidden_actions=(
            "direct_wordpress_write",
            "cloud_publish",
            "cloud_workflow_truth",
            "cloud_prompt_or_preset_truth",
            "article_body_generation",
            "article_write_plan_generation",
        ),
        fail_closed_behavior="return_suggestion_only_without_wordpress_write",
    ),
}

_WORKFLOWS: dict[str, WorkflowMetadata] = {
    WEB_SEARCH_EVIDENCE_WORKFLOW_ID: WorkflowMetadata(
        workflow_id=WEB_SEARCH_EVIDENCE_WORKFLOW_ID,
        workflow_version="web_search_evidence_workflow.v1",
        title="External web evidence preflight",
        summary=(
            "Fixed runtime evidence workflow. It produces source grounding only "
            "and hands control back to the local WordPress path."
        ),
        ability_name="npcink-cloud/web-search",
        contract="web_search_runtime_request.v1",
        owner="cloud_runtime",
        handoff_owner="wordpress_local",
        execution_pattern="step_offload",
        storage_mode="suggestion_only",
        badges=(
            StatusBadge(label="suggestion only", status="read_only"),
            StatusBadge(label="write blocked", status="success"),
        ),
        steps=(
            "Validate runtime contract",
            "Select Cloud-managed search provider",
            "Normalize and score sources",
            "Apply evidence gate",
            "Return suggestion-only evidence",
        ),
        stop_conditions=(
            "Provider not configured",
            "Provider fallback exhausted",
            "Insufficient evidence",
        ),
        direct_wordpress_write=False,
        requires_operator_review=True,
        fail_closed_behavior="return_without_external_evidence",
    ),
    MEDIA_DERIVATIVE_WORKFLOW_ID: WorkflowMetadata(
        workflow_id=MEDIA_DERIVATIVE_WORKFLOW_ID,
        workflow_version="media_derivative_workflow.v1",
        title="Media derivative artifact generation",
        summary=(
            "Fixed worker workflow for temporary image derivatives. Cloud returns "
            "an artifact reference; local WordPress remains the approval and write owner."
        ),
        ability_name="npcink-cloud/media-derivative",
        contract="media_derivative_cloud_request.v1",
        owner="cloud_worker",
        handoff_owner="wordpress_local",
        execution_pattern="whole_run_offload",
        storage_mode="short_ttl_artifact",
        badges=(
            StatusBadge(label="whole run offload", status="active"),
            StatusBadge(label="write blocked", status="success"),
        ),
        steps=(
            "Validate media derivative request",
            "Queue runtime worker job",
            "Process static image derivative",
            "Store short TTL artifact",
            "Return artifact reference for local review",
        ),
        stop_conditions=(
            "Invalid source",
            "Unsupported format",
            "Artifact TTL expired",
            "Local approval required",
        ),
        direct_wordpress_write=False,
        requires_operator_review=True,
        fail_closed_behavior="return_artifact_unavailable",
    ),
}


def get_agent_handoff_metadata(
    agent_id: str,
    *,
    agent_role: str | None = None,
) -> dict[str, object]:
    metadata = _AGENTS.get(agent_id)
    return metadata.to_dict(agent_role=agent_role) if metadata else {}


def list_agent_handoff_metadata() -> list[dict[str, object]]:
    return [metadata.to_dict() for metadata in _AGENTS.values()]


def get_workflow_metadata(workflow_id: str) -> dict[str, object]:
    metadata = _WORKFLOWS.get(workflow_id)
    return metadata.to_dict() if metadata else {}


def list_workflow_metadata() -> list[dict[str, object]]:
    return [metadata.to_dict() for metadata in _WORKFLOWS.values()]


def get_agent_workflow_metadata_projection() -> dict[str, object]:
    return {
        "projection_version": METADATA_PROJECTION_VERSION,
        "projection_kind": "read_only_runtime_metadata",
        "agents": list_agent_handoff_metadata(),
        "workflows": list_workflow_metadata(),
    }


def metadata_projection_tokens(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    tokens: list[str] = []
    for value in values:
        token = _metadata_projection_token(str(value or ""))
        if token:
            tokens.append(token)
    return tokens


def _metadata_projection_token(value: str) -> str:
    parts: list[str] = []
    previous_was_separator = True
    for character in value.strip().lower():
        if character.isalnum():
            parts.append(character)
            previous_was_separator = False
            continue
        if not previous_was_separator:
            parts.append("_")
            previous_was_separator = True
    return "".join(parts).strip("_")
