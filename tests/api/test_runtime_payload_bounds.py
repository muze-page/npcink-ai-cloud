from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes.runs import RuntimeRepairPayload
from app.api.routes.runtime import MAX_RUNTIME_STRING_CHARS, RuntimePayload


def test_runtime_payload_rejects_oversized_input_string() -> None:
    with pytest.raises(ValidationError):
        RuntimePayload(
            ability_name="npcink-abilities-toolkit/test",
            input={"prompt": "x" * (MAX_RUNTIME_STRING_CHARS + 1)},
        )


def test_runtime_payload_rejects_deep_task_backend() -> None:
    value: object = "leaf"
    for _ in range(9):
        value = {"nested": value}

    with pytest.raises(ValidationError):
        RuntimePayload(
            ability_name="npcink-abilities-toolkit/test",
            task_backend={"root": value},
        )


def test_runtime_payload_accepts_bounded_wordpress_ai_output_schema() -> None:
    RuntimePayload(
        ability_name="npcink-cloud/wp-ai-connector",
        contract_version="wp_ai_connector_runtime.v1",
        channel="wordpress_ai_connector",
        execution_kind="wordpress_ai_connector",
        input={
            "request": {
                "task_contract": {
                    "output_schema": {
                        "type": "object",
                        "properties": {
                            "suggestions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "term": {"type": "string"},
                                        "confidence": {"type": "number"},
                                        "is_new": {"type": "boolean"},
                                    },
                                },
                            }
                        },
                    }
                }
            }
        },
    )


def test_runtime_payload_keeps_non_schema_wordpress_ai_input_depth_bounded() -> None:
    value: object = "leaf"
    for _ in range(9):
        value = {"nested": value}

    with pytest.raises(ValidationError):
        RuntimePayload(
            ability_name="npcink-cloud/wp-ai-connector",
            input={"request": {"scene_gate": value}},
        )


def test_runtime_payload_rejects_unbounded_wordpress_ai_output_schema() -> None:
    schema: object = "leaf"
    for _ in range(10):
        schema = {"nested": schema}

    with pytest.raises(ValidationError):
        RuntimePayload(
            ability_name="npcink-cloud/wp-ai-connector",
            input={"request": {"task_contract": {"output_schema": schema}}},
        )


def test_runtime_repair_payload_rejects_unbounded_operator_evidence() -> None:
    with pytest.raises(ValidationError):
        RuntimeRepairPayload(
            action="redeliver_callback",
            operator_evidence="x" * 4001,
        )
