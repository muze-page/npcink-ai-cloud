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


def test_runtime_repair_payload_rejects_unbounded_operator_evidence() -> None:
    with pytest.raises(ValidationError):
        RuntimeRepairPayload(
            action="redeliver_callback",
            operator_evidence="x" * 4001,
        )
