from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.api.main import create_app
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.core.models import ProviderCallRecord, RunRecord
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'image-context-evidence.sqlite3'}"


class FakeVisionProvider:
    provider_id = "fakevision"
    display_name = "Fake Vision"
    adapter_type = "openai"

    def __init__(self, *, invalid_response: bool = False) -> None:
        self.invalid_response = invalid_response
        self.requests: list[ProviderExecutionRequest] = []

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id="fake-vision-model",
                    family="fake-vision",
                    feature="vision",
                    status="available",
                    price_input=0.1,
                    price_output=0.2,
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="fakevision-global-default",
                            endpoint_variant="responses",
                            region="global",
                            capability_tags=["vision", "default", "quality"],
                            is_default=True,
                            weight=100,
                        )
                    ],
                )
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self.requests.append(request)
        output_text = (
            "not json"
            if self.invalid_response
            else json.dumps(
                {
                    "contract_version": "image_context_evidence.v1",
                    "artifact_type": "image_context_evidence",
                    "items": [
                        {
                            "attachment_id": "101",
                            "visual_summary": "A red notebook beside a coffee mug.",
                            "visible_text": ["NPCINK"],
                            "subject_tags": ["notebook", "coffee mug"],
                            "alt_text_basis": "red notebook and coffee mug on desk",
                            "caption_basis": "workspace detail with branded notebook",
                            "confidence": 0.82,
                            "uncertainty_flags": [],
                        }
                    ],
                    "direct_wordpress_write": False,
                    "requires_human_visual_check": True,
                }
            )
        )
        return ProviderExecutionResult(
            output={
                "output_text": output_text,
                "messages": [{"role": "assistant", "content": output_text}],
                "model_id": request.model_id,
            },
            latency_ms=33,
            tokens_in=123,
            tokens_out=45,
            cost=0.001,
        )


def _build_client(
    tmp_path: Path,
    *,
    provider: FakeVisionProvider | None = None,
) -> tuple[str, TestClient, FakeVisionProvider]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    selected_provider = provider or FakeVisionProvider()
    providers = {selected_provider.provider_id: selected_provider}
    CatalogService(database_url, providers=providers).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_alpha",
        scopes=["runtime:execute", "runtime:read"],
    )
    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Image Context Evidence Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )
    client = TestClient(create_app(CloudServices(settings=settings, providers=providers)))
    return database_url, client, selected_provider


def _payload(input_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    input_payload: dict[str, Any] = {
        "contract_version": "image_context_evidence_request.v1",
        "items": [
            {
                "attachment_id": "101",
                "source_url": "https://example.com/uploads/notebook.jpg",
                "thumbnail_url": "https://example.com/uploads/notebook-300x200.jpg",
                "title": "Notebook product shot",
                "filename": "notebook.jpg",
                "mime_type": "image/jpeg",
                "existing_alt": "",
                "existing_caption": "",
            }
        ],
        "locale": "zh_CN",
    }
    input_payload.update(input_overrides or {})
    return {
        "ability_name": "npcink-cloud/image-context-evidence",
        "contract_version": "image_context_evidence_request.v1",
        "execution_pattern": "inline",
        "data_classification": "public_site_media_metadata",
        "storage_mode": "result_only",
        "timeout_seconds": 20,
        "retry_max": 0,
        "retention_ttl": 3600,
        "input": input_payload,
        "policy": {"allow_fallback": False},
    }


def _execute(
    client: TestClient,
    payload: dict[str, Any],
    *,
    idempotency_key: str = "image-context-evidence-idem",
    nonce: str | None = None,
) -> Any:
    body = json.dumps(payload).encode("utf-8")
    headers = merge_json_headers(
        build_auth_headers(
            "POST",
            "/v1/runtime/execute",
            site_id="site_alpha",
            key_id="key_default",
            idempotency_key=idempotency_key,
            nonce=nonce or f"nonce-{idempotency_key}",
            trace_id="imagecontextevidence0000000000",
            body=body,
        )
    )
    return client.post("/v1/runtime/execute", content=body, headers=headers)


def test_image_context_evidence_runtime_calls_vision_provider(tmp_path: Path) -> None:
    database_url, client, provider = _build_client(tmp_path)

    response = _execute(client, _payload())

    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["status"] == "succeeded"
    assert data["profile_id"] == "vision.ai"
    assert data["provider_id"] == "fakevision"
    assert data["model_id"] == "fake-vision-model"
    assert data["provider_call_count"] == 1
    assert data["execution_context"]["ability_family"] == "vision"
    assert data["execution_context"]["data_classification"] == "public_site_media_metadata"

    result = data["result"]
    assert result["contract_version"] == "image_context_evidence.v1"
    assert result["artifact_type"] == "image_context_evidence"
    assert result["write_posture"] == "suggestion_only"
    assert result["direct_wordpress_write"] is False
    assert result["requires_human_visual_check"] is True
    assert result["items"][0]["attachment_id"] == "101"
    assert result["items"][0]["source_url"] == "https://example.com/uploads/notebook.jpg"
    assert result["items"][0]["alt_text_basis"] == "red notebook and coffee mug on desk"
    assert result["items"][0]["confidence"] == 0.82

    assert len(provider.requests) == 1
    provider_input = provider.requests[0].input_payload
    assert provider_input["input"][0]["content"][2] == {
        "type": "input_image",
        "image_url": "https://example.com/uploads/notebook.jpg",
    }
    assert provider.requests[0].execution_kind == "vision"

    with get_session(database_url) as session:
        run = session.get(RunRecord, data["run_id"])
        assert run is not None
        assert run.execution_kind == "image_context_evidence"
        assert run.input_json == {}
        assert run.policy_json["execution_contract"]["direct_wordpress_write"] is False
        provider_calls = list(
            session.scalars(
                select(ProviderCallRecord)
                .where(ProviderCallRecord.run_id == run.run_id)
                .order_by(ProviderCallRecord.id.asc())
            )
        )
        assert len(provider_calls) == 1
        assert provider_calls[0].provider_id == "fakevision"
        assert provider_calls[0].tokens_in == 123
        assert provider_calls[0].tokens_out == 45


def test_image_context_evidence_rejects_wordpress_write_fields(tmp_path: Path) -> None:
    _, client, _ = _build_client(tmp_path)

    response = _execute(
        client,
        _payload({"wordpress_write_policy": {"update_attachment_metadata": True}}),
        idempotency_key="image-context-evidence-forbidden-write",
    )

    assert response.status_code == 400
    assert response.json()["error_code"] == "image_context_evidence.write_or_secret_field_forbidden"


def test_image_context_evidence_fails_on_unstructured_provider_response(
    tmp_path: Path,
) -> None:
    _, client, _ = _build_client(tmp_path, provider=FakeVisionProvider(invalid_response=True))

    response = _execute(
        client,
        _payload(),
        idempotency_key="image-context-evidence-invalid-provider",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["data"]["status"] == "failed"
    assert payload["data"]["error_code"] == "image_context_evidence.invalid_provider_response"
