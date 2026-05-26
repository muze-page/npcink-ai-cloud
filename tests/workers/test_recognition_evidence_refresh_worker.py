from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.adapters.recognition.huggingface import HuggingFaceRecognitionEvidenceImporter
from app.adapters.recognition.litellm import LiteLLMRecognitionEvidenceImporter
from app.adapters.recognition.openrouter import OpenRouterRecognitionEvidenceImporter
from app.adapters.recognition.ollama import OllamaRecognitionEvidenceImporter
from app.adapters.recognition.siliconflow import SiliconFlowRecognitionEvidenceImporter
from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.config import Settings
from app.core.db import get_session, init_schema
from app.workers.recognition_evidence_refresh import run_once


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'recognition-worker.sqlite3'}"


def test_recognition_evidence_refresh_worker_writes_normalized_snapshot(
    tmp_path: Path,
) -> None:
    init_schema(_sqlite_url(tmp_path))
    source_path = tmp_path / "recognition-source.json"
    snapshot_path = tmp_path / "runtime" / "recognition-snapshot.json"
    source_path.write_text(
        """
{
  "version": "recognition_upstream_custom_v1",
  "sources": {
    "litellm_revision": "custom-litellm-123",
    "hf_snapshot": "custom-hf-456"
  },
  "records": {
    "custom_provider::fixture-model": {
      "evidence_source": "litellm_custom",
      "model_type": "vision",
      "preview_type": "text",
      "input_modalities": ["text", "image", "text"],
      "output_modalities": ["text"],
      "capabilities": {
        "text_input": true,
        "image_input": 1,
        "vision": true
      },
      "confidence": 0.91
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    summary = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            openrouter_recognition_enabled=False,
            recognition_evidence_source_path=str(source_path),
            recognition_evidence_snapshot_path=str(snapshot_path),
        ),
        now_factory=lambda: datetime(2026, 3, 29, 9, 30, tzinfo=UTC),
    )

    assert summary["source"] == "cloud_recognition_evidence_refresh_worker"
    assert summary["status"] == "ok"
    assert summary["snapshot_path"] == str(snapshot_path)
    assert summary["version"] == "recognition_upstream_custom_v1"
    assert summary["records_total"] == 1
    assert summary["source_keys"] == ["hf_snapshot", "litellm_revision", "ollama_snapshot", "openrouter_snapshot", "siliconflow_snapshot"]
    assert summary["source_runs"][0]["source"] == "json_source_path"
    assert summary["source_run_ids"] == ["json_source_path:2026-03-29T09:30:00Z"]
    assert summary["source_failures"] == []

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    record = payload["records"]["custom_provider::fixture-model"]

    assert payload["generated_at"] == "2026-03-29T09:30:00Z"
    assert payload["source_runs"][0]["source"] == "json_source_path"
    assert payload["source_run_ids"] == ["json_source_path:2026-03-29T09:30:00Z"]
    assert payload["source_failures"] == []
    assert record["input_modalities"] == ["text", "image"]
    assert record["capabilities"]["image_input"] is True
    assert record["confidence"] == 0.91
    with get_session(_sqlite_url(tmp_path)) as session:
        repository = CatalogRepository(session)
        rows = repository.list_recent_recognition_source_runs(limit=5)
        publications = repository.list_recent_recognition_snapshot_publications(limit=5)
    assert len(rows) == 1
    assert rows[0].source_name == "json_source_path"
    assert rows[0].run_id == "json_source_path:2026-03-29T09:30:00Z"
    assert len(publications) == 1
    assert publications[0].records_total == 1
    assert publications[0].record_keys_json == ["custom_provider::fixture-model"]


def test_recognition_evidence_refresh_worker_uses_litellm_importer_when_configured(
    tmp_path: Path,
) -> None:
    init_schema(_sqlite_url(tmp_path))
    snapshot_path = tmp_path / "runtime" / "recognition-snapshot.json"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/model/info")
        return httpx.Response(
            200,
            headers={"etag": "litellm-worker-rev-001"},
            json={
                "data": [
                    {
                        "model_name": "openai/gpt-4.1",
                        "litellm_params": {
                            "model": "openai/gpt-4.1",
                            "custom_llm_provider": "openai",
                        },
                        "model_info": {
                            "litellm_provider": "openai",
                            "mode": "chat",
                            "supports_vision": True,
                            "supports_function_calling": True,
                            "input_cost_per_token": 0.0000004,
                            "output_cost_per_token": 0.0000016,
                        },
                    }
                ]
            },
        )

    importer = LiteLLMRecognitionEvidenceImporter(
        base_url="https://litellm.example.test",
        api_key="worker-key",
        transport=httpx.MockTransport(handler),
    )

    summary = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            openrouter_recognition_enabled=False,
            recognition_evidence_snapshot_path=str(snapshot_path),
            huggingface_model_allowlist="",
        ),
        now_factory=lambda: datetime(2026, 3, 29, 10, 0, tzinfo=UTC),
        importer=importer,
    )

    assert summary["status"] == "ok"
    assert summary["source_kind"] == "litellm_importer"
    assert summary["records_total"] == 1
    assert summary["source_runs"][0]["source"] == "litellm"
    assert summary["source_runs"][0]["status"] == "ok"
    assert summary["source_run_ids"] == ["litellm:2026-03-29T10:00:00Z"]

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    record = payload["records"]["openai::gpt-4.1"]

    assert payload["sources"]["litellm_revision"] == "litellm-worker-rev-001"
    assert payload["sources"]["hf_snapshot"] == "unconfigured"
    assert payload["sources"]["ollama_snapshot"] == "unconfigured"
    assert payload["source_runs"][0]["source"] == "litellm"
    assert payload["source_run_ids"] == ["litellm:2026-03-29T10:00:00Z"]
    assert payload["source_failures"] == []
    assert record["evidence_source"] == "litellm_model_info"
    assert record["model_type"] == "vision"
    assert record["capabilities"]["vision"] is True
    assert record["price_input"] == 0.4
    assert record["price_output"] == 1.6


def test_recognition_evidence_refresh_worker_merges_litellm_and_huggingface_importers(
    tmp_path: Path,
) -> None:
    init_schema(_sqlite_url(tmp_path))
    snapshot_path = tmp_path / "runtime" / "recognition-snapshot.json"

    def litellm_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/model/info")
        return httpx.Response(
            200,
            headers={"etag": "litellm-worker-rev-merge"},
            json={
                "data": [
                    {
                        "model_name": "openai/gpt-4.1",
                        "litellm_params": {
                            "model": "openai/gpt-4.1",
                            "custom_llm_provider": "openai",
                        },
                        "model_info": {
                            "litellm_provider": "openai",
                            "mode": "chat",
                            "supports_vision": True,
                            "input_cost_per_token": 0.0000004,
                            "output_cost_per_token": 0.0000016,
                        },
                    }
                ]
            },
        )

    def hf_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/models/black-forest-labs/FLUX.1-dev")
        return httpx.Response(
            200,
            json={
                "id": "black-forest-labs/FLUX.1-dev",
                "pipeline_tag": "text-to-image",
                "tags": ["diffusers", "text-to-image"],
            },
        )

    summary = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            openrouter_recognition_enabled=False,
            recognition_evidence_snapshot_path=str(snapshot_path),
        ),
        now_factory=lambda: datetime(2026, 3, 29, 10, 30, tzinfo=UTC),
        importer=LiteLLMRecognitionEvidenceImporter(
            base_url="https://litellm.example.test",
            transport=httpx.MockTransport(litellm_handler),
        ),
        hf_importer=HuggingFaceRecognitionEvidenceImporter(
            repo_ids=["black-forest-labs/FLUX.1-dev"],
            transport=httpx.MockTransport(hf_handler),
        ),
    )

    assert summary["status"] == "ok"
    assert summary["source_kind"] == "litellm_and_huggingface_importers"
    assert summary["records_total"] == 2
    assert summary["source_keys"] == ["hf_snapshot", "litellm_revision", "ollama_snapshot", "openrouter_snapshot", "siliconflow_snapshot"]
    assert sorted(summary["source_run_ids"]) == [
        "huggingface:2026-03-29T10:30:00Z",
        "litellm:2026-03-29T10:30:00Z",
    ]

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert "openai::gpt-4.1" in payload["records"]
    assert "huggingface::black-forest-labs/FLUX.1-dev" in payload["records"]
    assert len(payload["source_runs"]) == 2
    assert payload["source_failures"] == []


def test_recognition_evidence_refresh_worker_uses_openrouter_importer_when_enabled(
    tmp_path: Path,
) -> None:
    init_schema(_sqlite_url(tmp_path))
    snapshot_path = tmp_path / "runtime" / "recognition-snapshot.json"

    def openrouter_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            headers={"etag": "openrouter-snapshot-001"},
            json={
                "data": [
                    {
                        "id": "openai/gpt-4.1-mini",
                        "architecture": {
                            "modality": "text->text",
                            "input_modalities": ["text"],
                            "output_modalities": ["text"],
                        },
                        "pricing": {"prompt": "0.0000004", "completion": "0.0000016"},
                        "supported_parameters": ["tools", "response_format"],
                    }
                ]
            },
        )

    summary = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            openrouter_recognition_enabled=False,
            recognition_evidence_snapshot_path=str(snapshot_path),
        ),
        now_factory=lambda: datetime(2026, 3, 29, 10, 45, tzinfo=UTC),
        openrouter_importer=OpenRouterRecognitionEvidenceImporter(
            transport=httpx.MockTransport(openrouter_handler),
        ),
    )

    assert summary["status"] == "ok"
    assert summary["source_kind"] == "openrouter_importer"
    assert summary["records_total"] == 1

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    record = payload["records"]["openrouter::openai/gpt-4.1-mini"]

    assert payload["sources"]["openrouter_snapshot"] == "openrouter-snapshot-001"
    assert record["evidence_source"] == "openrouter_model_info"
    assert record["model_type"] == "chat"
    assert record["capabilities"]["structured_output"] is True


def test_recognition_evidence_refresh_worker_uses_siliconflow_importer_when_enabled(
    tmp_path: Path,
) -> None:
    init_schema(_sqlite_url(tmp_path))
    snapshot_path = tmp_path / "runtime" / "recognition-snapshot.json"

    html = """
<!DOCTYPE html>
<html><body>
<div class="h-[43px] px-[12px] flex items-center"><div class="flex-1"><a href="https://cloud.siliconflow.cn/models?target=Qwen/Qwen3.5-4B">Qwen/Qwen3.5-4B</a></div><div class="flex-1">0.72</div><div class="flex-1">2.16</div></div>
<script>
self.__next_f.push([1,"\\\"DisplayName\\\":\\\"Qwen3.5-4B\\\",\\\"type\\\":\\\"text\\\",\\\"subType\\\":\\\"chat\\\",\\\"jsonModeSupport\\\":true,\\\"functionCallSupport\\\":true,\\\"vlm\\\":false,\\\"targetModelName\\\":\\\"Qwen/Qwen3.5-4B\\\""])
</script>
</body></html>
""".strip()

    def siliconflow_handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://www2.siliconflow.cn/pricing"
        return httpx.Response(
            200,
            headers={"etag": "siliconflow-pricing-snapshot-001"},
            text=html,
        )

    summary = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            recognition_evidence_snapshot_path=str(snapshot_path),
        ),
        now_factory=lambda: datetime(2026, 4, 3, 10, 45, tzinfo=UTC),
        siliconflow_importer=SiliconFlowRecognitionEvidenceImporter(
            pricing_url="https://www2.siliconflow.cn/pricing",
            cny_per_usd=7.2,
            transport=httpx.MockTransport(siliconflow_handler),
        ),
    )

    assert summary["status"] == "ok"
    assert summary["source_kind"] == "siliconflow_importer"
    assert summary["records_total"] == 1

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    record = payload["records"]["siliconflow::Qwen/Qwen3.5-4B"]

    assert payload["sources"]["siliconflow_snapshot"] == "siliconflow-pricing-snapshot-001"
    assert record["evidence_source"] == "siliconflow_pricing_page"
    assert record["price_input"] == 0.1
    assert record["price_output"] == 0.3
    assert record["capabilities"]["tools"] is True


def test_recognition_evidence_refresh_worker_continues_when_one_importer_fails(
    tmp_path: Path,
) -> None:
    init_schema(_sqlite_url(tmp_path))
    snapshot_path = tmp_path / "runtime" / "recognition-snapshot.json"

    def openrouter_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "z-ai/glm-5v-turbo",
                        "architecture": {
                            "modality": "text+image->text",
                            "input_modalities": ["text", "image"],
                            "output_modalities": ["text"],
                        },
                        "pricing": {"prompt": "0.0000012", "completion": "0.000004"},
                        "supported_parameters": ["tools"],
                    }
                ]
            },
        )

    summary = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            openrouter_recognition_enabled=False,
            recognition_evidence_snapshot_path=str(snapshot_path),
        ),
        now_factory=lambda: datetime(2026, 3, 29, 11, 0, tzinfo=UTC),
        openrouter_importer=OpenRouterRecognitionEvidenceImporter(
            transport=httpx.MockTransport(openrouter_handler),
        ),
        hf_importer=HuggingFaceRecognitionEvidenceImporter(
            repo_ids=["BAAI/bge-m3"],
            transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.TimeoutException("hf timeout"))),
        ),
    )

    assert summary["status"] == "ok"
    assert summary["records_total"] == 1
    assert summary["source_kind"] == "openrouter_and_huggingface_importers"
    assert summary["source_failures"] == [
        {
            "source": "huggingface",
            "error": "huggingface recognition evidence refresh timed out",
        }
    ]

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert "openrouter::z-ai/glm-5v-turbo" in payload["records"]


def test_recognition_evidence_refresh_worker_merges_all_importers(
    tmp_path: Path,
) -> None:
    init_schema(_sqlite_url(tmp_path))
    snapshot_path = tmp_path / "runtime" / "recognition-snapshot.json"

    def litellm_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/model/info")
        return httpx.Response(
            200,
            headers={"etag": "litellm-worker-rev-all"},
            json={
                "data": [
                    {
                        "model_name": "openai/gpt-4.1",
                        "litellm_params": {
                            "model": "openai/gpt-4.1",
                            "custom_llm_provider": "openai",
                        },
                        "model_info": {
                            "litellm_provider": "openai",
                            "mode": "chat",
                            "supports_vision": True,
                        },
                    }
                ]
            },
        )

    def hf_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/models/black-forest-labs/FLUX.1-dev")
        return httpx.Response(
            200,
            json={
                "id": "black-forest-labs/FLUX.1-dev",
                "pipeline_tag": "text-to-image",
                "tags": ["diffusers"],
            },
        )

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/show")
        return httpx.Response(
            200,
            json={
                "details": {"family": "llava", "families": ["llava"]},
                "capabilities": ["completion", "vision"],
                "model_info": {"general.architecture": "llava"},
                "modelfile": "FROM llava:13b\n",
            },
        )

    summary = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            openrouter_recognition_enabled=False,
            recognition_evidence_snapshot_path=str(snapshot_path),
        ),
        now_factory=lambda: datetime(2026, 3, 29, 11, 0, tzinfo=UTC),
        importer=LiteLLMRecognitionEvidenceImporter(
            base_url="https://litellm.example.test",
            transport=httpx.MockTransport(litellm_handler),
        ),
        hf_importer=HuggingFaceRecognitionEvidenceImporter(
            repo_ids=["black-forest-labs/FLUX.1-dev"],
            transport=httpx.MockTransport(hf_handler),
        ),
        ollama_importer=OllamaRecognitionEvidenceImporter(
            model_names=["llava:13b"],
            transport=httpx.MockTransport(ollama_handler),
        ),
    )

    assert summary["status"] == "ok"
    assert summary["source_kind"] == "litellm_and_huggingface_and_ollama_importers"
    assert summary["records_total"] == 3
    assert summary["source_keys"] == ["hf_snapshot", "litellm_revision", "ollama_snapshot", "openrouter_snapshot", "siliconflow_snapshot"]

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert "openai::gpt-4.1" in payload["records"]
    assert "huggingface::black-forest-labs/FLUX.1-dev" in payload["records"]
    assert "ollama::llava:13b" in payload["records"]


def test_recognition_evidence_refresh_worker_reuses_fresh_snapshot(
    tmp_path: Path,
) -> None:
    init_schema(_sqlite_url(tmp_path))
    snapshot_path = tmp_path / "runtime" / "recognition-snapshot.json"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "version": "recognition_upstream_v1",
                "generated_at": "2026-03-29T10:55:00Z",
                "sources": {
                    "litellm_revision": "cached-litellm-001",
                    "hf_snapshot": "cached-hf-001",
                    "ollama_snapshot": "unconfigured",
                },
                "records": {
                    "openai::gpt-4.1": {
                        "evidence_source": "litellm_model_info",
                        "model_type": "vision",
                        "preview_type": "text",
                        "input_modalities": ["text", "image"],
                        "output_modalities": ["text"],
                        "capabilities": {
                            "text_input": True,
                            "image_input": True,
                            "image_output": False,
                            "vision": True,
                        },
                        "confidence": 0.95,
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    importer_called = False

    class FailingImporter:
        def fetch_upstream_evidence_payload(self) -> dict[str, object]:
            nonlocal importer_called
            importer_called = True
            raise AssertionError("importer should not run when snapshot is fresh")

    summary = run_once(
        Settings(
            _env_file=None,
            project_name="Magick AI Cloud Test",
            environment="test",
            database_url=_sqlite_url(tmp_path),
            redis_url="redis://localhost:6379/0",
            openrouter_recognition_enabled=False,
            recognition_evidence_snapshot_path=str(snapshot_path),
            recognition_evidence_min_refresh_seconds=900,
        ),
        now_factory=lambda: datetime(2026, 3, 29, 11, 0, tzinfo=UTC),
        importer=FailingImporter(),  # type: ignore[arg-type]
    )

    assert importer_called is False
    assert summary["status"] == "skipped"
    assert summary["source_kind"] == "cached_snapshot"
    assert summary["records_total"] == 1
    assert summary["cached_age_seconds"] == 300
