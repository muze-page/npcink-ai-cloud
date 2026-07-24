from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.configure_m4_ollama_preview import (
    BASE_URL,
    MODEL_ID,
    PROFILE_IDS,
    _connection_payload,
    _validate_environment,
)


def test_m4_ollama_preview_connection_is_secretless_and_non_reasoning() -> None:
    payload = _connection_payload()

    assert payload["base_url"] == BASE_URL == "http://host.docker.internal:11434/v1"
    assert payload["provider_id"] == "ollama-m4"
    assert payload["secretless"] is True
    assert payload["runtime_profile_ids"] == list(PROFILE_IDS)
    assert payload["config"] == {
        "model_ids": [MODEL_ID],
        "timeout_seconds": 60,
        "default_reasoning_effort": "none",
    }
    assert "credential" not in payload
    assert "secret" not in payload


def test_m4_ollama_preview_configuration_rejects_production() -> None:
    with pytest.raises(RuntimeError, match="development-only"):
        _validate_environment(SimpleNamespace(environment="production"))  # type: ignore[arg-type]


@pytest.mark.parametrize("environment", ["development", "dev", "test"])
def test_m4_ollama_preview_configuration_accepts_development_environments(
    environment: str,
) -> None:
    _validate_environment(SimpleNamespace(environment=environment))  # type: ignore[arg-type]
