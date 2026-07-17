from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.routes.runs import RuntimeRepairPayload
from app.api.routes.runtime import MAX_RUNTIME_STRING_CHARS, RuntimePayload


def _connector_payload_input(request: dict[str, object]) -> dict[str, object]:
    return {
        "site_url": "https://alpha.example.test",
        "platform_kind": "wordpress",
        "connector_id": "npcink-cloud-addon",
        "connector_version": "1.0.0-test",
        "suggestion_only": True,
        "operation_contract": {
            "contract_version": "wordpress_operation.v1",
            "task": "title_generation",
            "request": request,
        },
    }


def test_runtime_payload_rejects_oversized_input_string() -> None:
    with pytest.raises(ValidationError):
        RuntimePayload(
            ability_name="npcink-abilities-toolkit/test",
            input={"prompt": "x" * (MAX_RUNTIME_STRING_CHARS + 1)},
        )


def test_runtime_payload_rejects_unknown_public_top_level_field() -> None:
    with pytest.raises(ValidationError, match="unexpected_top_level_field"):
        RuntimePayload(
            site_id="site_alpha",
            ability_name="npcink-cloud/connector-runtime",
            contract_version="cloud_connector_runtime.v1",
            channel="editor",
            input=_connector_payload_input(
                {"source_text": "<content>Current article content.</content>"}
            ),
            unexpected_top_level_field=True,  # type: ignore[call-arg]
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
        site_id="site_alpha",
        ability_name="npcink-cloud/connector-runtime",
        contract_version="cloud_connector_runtime.v1",
        channel="editor",
        execution_kind="text",
        input=_connector_payload_input(
            {
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
        ),
    )


def test_runtime_payload_keeps_non_schema_wordpress_ai_input_depth_bounded() -> None:
    value: object = "leaf"
    for _ in range(9):
        value = {"nested": value}

    with pytest.raises(ValidationError):
        RuntimePayload(
            site_id="site_alpha",
            ability_name="npcink-cloud/connector-runtime",
            input=_connector_payload_input({"scene_gate": value}),
        )


def test_runtime_payload_rejects_unbounded_wordpress_ai_output_schema() -> None:
    schema: object = "leaf"
    for _ in range(10):
        schema = {"nested": schema}

    with pytest.raises(ValidationError):
        RuntimePayload(
            site_id="site_alpha",
            ability_name="npcink-cloud/connector-runtime",
            input=_connector_payload_input(
                {"task_contract": {"output_schema": schema}}
            ),
        )


def test_runtime_repair_payload_rejects_unbounded_operator_evidence() -> None:
    with pytest.raises(ValidationError):
        RuntimeRepairPayload(
            action="redeliver_callback",
            operator_evidence="x" * 4001,
        )
