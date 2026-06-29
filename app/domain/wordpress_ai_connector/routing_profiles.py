from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID = "wp-ai.short-text"
WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID = "wp-ai.editorial"
WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID = "wp-ai.classification"
WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID = "wp-ai.image-generation"

WP_AI_CONNECTOR_PROFILE_IDS = (
    WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
    WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID,
    WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID,
    WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID,
)


@dataclass(frozen=True, slots=True)
class WordPressAIConnectorProfileSpec:
    profile_id: str
    group_id: str
    routing_intent: str
    label: str
    execution_kind: str
    tasks: tuple[str, ...]
    ordered_tiers: tuple[str, ...]
    timeout_ms: int
    max_timeout_ms: int
    allow_fallback: bool
    max_retries: int
    description: str


WP_AI_CONNECTOR_PROFILE_SPECS: tuple[WordPressAIConnectorProfileSpec, ...] = (
    WordPressAIConnectorProfileSpec(
        profile_id=WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID,
        group_id="short_text",
        routing_intent="content.short_text",
        label="Short text",
        execution_kind="text",
        tasks=(
            "alt_text_suggest",
            "excerpt_generation",
            "meta_description",
            "title_generation",
        ),
        ordered_tiers=("economy", "hosted-free", "balanced", "free-gpt55"),
        timeout_ms=20_000,
        max_timeout_ms=60_000,
        allow_fallback=True,
        max_retries=0,
        description=(
            "Low-latency WordPress AI suggestions for titles, SEO text, excerpts, "
            "and alt text."
        ),
    ),
    WordPressAIConnectorProfileSpec(
        profile_id=WP_AI_CONNECTOR_EDITORIAL_PROFILE_ID,
        group_id="editorial_text",
        routing_intent="content.editorial",
        label="Editorial text",
        execution_kind="text",
        tasks=(
            "comment_reply_suggest",
            "content_rewrite",
            "content_summary",
        ),
        ordered_tiers=("balanced", "economy", "hosted-free", "quality", "free-gpt55"),
        timeout_ms=45_000,
        max_timeout_ms=60_000,
        allow_fallback=True,
        max_retries=0,
        description=(
            "Bounded editorial suggestions for summaries, rewrites, and reviewable "
            "replies."
        ),
    ),
    WordPressAIConnectorProfileSpec(
        profile_id=WP_AI_CONNECTOR_CLASSIFICATION_PROFILE_ID,
        group_id="classification",
        routing_intent="content.classification",
        label="Classification",
        execution_kind="text",
        tasks=(
            "comment_moderation",
            "content_classification",
        ),
        ordered_tiers=("economy", "balanced", "hosted-free", "free-gpt55"),
        timeout_ms=25_000,
        max_timeout_ms=60_000,
        allow_fallback=True,
        max_retries=0,
        description="Structured taxonomy and moderation suggestions for WordPress AI tasks.",
    ),
    WordPressAIConnectorProfileSpec(
        profile_id=WP_AI_CONNECTOR_IMAGE_GENERATION_PROFILE_ID,
        group_id="image_generation",
        routing_intent="media.image_generation",
        label="Image generation",
        execution_kind="image_generation",
        tasks=("image_generation",),
        ordered_tiers=("z-image", "quality", "default"),
        timeout_ms=90_000,
        max_timeout_ms=90_000,
        allow_fallback=False,
        max_retries=0,
        description=(
            "Cloud-managed text-to-image generation for the WordPress AI media "
            "library feature."
        ),
    ),
)

WP_AI_CONNECTOR_PROFILE_SPECS_BY_ID = {
    spec.profile_id: spec for spec in WP_AI_CONNECTOR_PROFILE_SPECS
}

WP_AI_CONNECTOR_PROFILE_SPECS_BY_TASK = {
    task: spec for spec in WP_AI_CONNECTOR_PROFILE_SPECS for task in spec.tasks
}


def resolve_wordpress_ai_connector_profile_id(input_payload: dict[str, Any]) -> str:
    task = str(input_payload.get("task") or "").strip()
    spec = WP_AI_CONNECTOR_PROFILE_SPECS_BY_TASK.get(task)
    if spec is None:
        return WP_AI_CONNECTOR_SHORT_TEXT_PROFILE_ID
    return spec.profile_id
