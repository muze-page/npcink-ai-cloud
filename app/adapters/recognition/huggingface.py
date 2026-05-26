from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx


class HuggingFaceRecognitionEvidenceImporter:
    def __init__(
        self,
        *,
        repo_ids: list[str],
        base_url: str = "https://huggingface.co",
        api_token: str | None = None,
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.repo_ids = [repo_id.strip() for repo_id in repo_ids if repo_id.strip()]
        self.base_url = base_url.rstrip("/")
        self.api_token = str(api_token or "").strip()
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self.transport = transport

    def fetch_upstream_evidence_payload(self) -> dict[str, Any]:
        records: dict[str, dict[str, Any]] = {}
        with self._build_client() as client:
            for repo_id in self.repo_ids:
                try:
                    response = client.get(f"/api/models/{repo_id}")
                    response.raise_for_status()
                except httpx.TimeoutException as error:
                    raise RuntimeError("huggingface recognition evidence refresh timed out") from error
                except httpx.HTTPStatusError as error:
                    raise RuntimeError(
                        "huggingface recognition evidence refresh failed with "
                        f"{error.response.status_code}: {self._extract_http_error_message(error.response)}"
                    ) from error
                except httpx.RequestError as error:
                    raise RuntimeError(
                        f"huggingface recognition evidence refresh network error: {error}"
                    ) from error

                record = self._build_record(repo_id, response.json())
                if record is None:
                    continue
                record_key, payload = record
                records[record_key] = payload

        return {
            "version": "recognition_upstream_v1",
            "generated_at": _serialize_timestamp(datetime.now(UTC)),
            "sources": {
                "hf_snapshot": _serialize_timestamp(datetime.now(UTC)),
            },
            "records": records,
        }

    def _build_record(
        self,
        repo_id: str,
        payload: Any,
    ) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(payload, dict):
            return None

        pipeline_tag = str(payload.get("pipeline_tag") or "").strip().lower()
        tags = [
            str(tag).strip().lower()
            for tag in payload.get("tags", [])
            if str(tag).strip()
        ] if isinstance(payload.get("tags"), list) else []
        shape = _derive_shape_from_hf_metadata(repo_id, pipeline_tag, tags)
        if shape is None:
            return None

        aliases = _unique_strings(
            [repo_id, repo_id.split("/")[-1], str(payload.get("id") or "")]
        )
        return (
            f"huggingface::{repo_id}",
            {
                "provider": "huggingface",
                "model_id": repo_id,
                "aliases": aliases,
                "match_keys": _unique_strings(
                    aliases + [f"huggingface/{repo_id}", f"huggingface:{repo_id}"]
                ),
                "evidence_source": "huggingface_model_info",
                "model_type": shape["model_type"],
                "preview_type": shape["preview_type"],
                "input_modalities": shape["input_modalities"],
                "output_modalities": shape["output_modalities"],
                "capabilities": shape["capabilities"],
                "confidence": shape["confidence"],
            },
        )

    def _build_client(self) -> httpx.Client:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.app_name,
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )

    def _extract_http_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or "unknown error"
        if isinstance(payload, dict):
            error = str(payload.get("error") or "").strip()
            if error:
                return error
        return response.text or "unknown error"


def _derive_shape_from_hf_metadata(
    repo_id: str,
    pipeline_tag: str,
    tags: list[str],
) -> dict[str, Any] | None:
    normalized = f"{repo_id} {' '.join(tags)} {pipeline_tag}".lower()

    if pipeline_tag in {"text-embedding", "feature-extraction", "sentence-similarity"}:
        return {
            "model_type": "embedding",
            "preview_type": "embedding",
            "input_modalities": ["text"],
            "output_modalities": ["embedding"],
            "capabilities": {
                "text_input": True,
                "image_input": False,
                "image_output": False,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.9,
        }

    if pipeline_tag in {"image-text-to-text", "visual-question-answering", "image-classification"}:
        return {
            "model_type": "vision",
            "preview_type": "text",
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "capabilities": {
                "text_input": True,
                "image_input": True,
                "image_output": False,
                "vision": True,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.88,
        }

    if pipeline_tag in {"text-to-image", "image-to-image", "unconditional-image-generation"}:
        return {
            "model_type": "image_generation",
            "preview_type": "image",
            "input_modalities": ["text", "image"],
            "output_modalities": ["image"],
            "capabilities": {
                "text_input": True,
                "image_input": pipeline_tag == "image-to-image",
                "image_output": True,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.9,
        }

    if pipeline_tag in {"text-generation", "text2text-generation", "conversational"}:
        return {
            "model_type": "chat",
            "preview_type": "text",
            "input_modalities": ["text"],
            "output_modalities": ["text"],
            "capabilities": {
                "text_input": True,
                "image_input": False,
                "image_output": False,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.86,
        }

    if any(token in normalized for token in ("llava", "vision", "vlm")):
        return {
            "model_type": "vision",
            "preview_type": "text",
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
            "capabilities": {
                "text_input": True,
                "image_input": True,
                "image_output": False,
                "vision": True,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.8,
        }

    if any(token in normalized for token in ("flux", "sdxl", "stable-diffusion")):
        return {
            "model_type": "image_generation",
            "preview_type": "image",
            "input_modalities": ["text", "image"],
            "output_modalities": ["image"],
            "capabilities": {
                "text_input": True,
                "image_input": "image-to-image" in normalized,
                "image_output": True,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.82,
        }

    return None


def _serialize_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result
