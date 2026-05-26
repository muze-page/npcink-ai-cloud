from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx


class LiteLLMRecognitionEvidenceImporter:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self.transport = transport

    def fetch_upstream_evidence_payload(self) -> dict[str, Any]:
        try:
            with self._build_client() as client:
                response = client.get("/model/info")
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise RuntimeError("litellm recognition evidence refresh timed out") from error
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                "litellm recognition evidence refresh failed with "
                f"{error.response.status_code}: {self._extract_http_error_message(error.response)}"
            ) from error
        except httpx.RequestError as error:
            raise RuntimeError(
                f"litellm recognition evidence refresh network error: {error}"
            ) from error

        payload = response.json()
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            raise ValueError("litellm /model/info response missing data list")

        generated_at = _serialize_timestamp(datetime.now(UTC))
        revision = str(
            response.headers.get("etag")
            or response.headers.get("x-litellm-revision")
            or generated_at
        )
        records: dict[str, dict[str, Any]] = {}
        for raw_model in raw_models:
            record = self._build_record(raw_model)
            if record is None:
                continue
            record_key, record_payload = record
            records[record_key] = record_payload

        return {
            "version": "recognition_upstream_v1",
            "generated_at": generated_at,
            "sources": {
                "litellm_revision": revision,
                "hf_snapshot": "unconfigured",
            },
            "records": records,
        }

    def _build_record(self, payload: Any) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(payload, dict):
            return None

        model_name = str(payload.get("model_name") or "").strip()
        litellm_params = payload.get("litellm_params")
        params = litellm_params if isinstance(litellm_params, dict) else {}
        model_info = payload.get("model_info")
        info = model_info if isinstance(model_info, dict) else {}

        provider_name = self._resolve_provider_name(model_name, params, info)
        provider_id = self._map_provider_id(provider_name)
        model_id = self._resolve_model_id(model_name, params, info, provider_name)
        if not provider_id or not model_id:
            return None

        shape = self._derive_shape(model_id, info, params)
        return (
            f"{provider_id}::{model_id}",
            {
                "provider": provider_id,
                "model_id": model_id,
                "aliases": self._unique_strings([model_name, str(params.get("model") or "")]),
                "match_keys": self._unique_strings(
                    [
                        model_id,
                        f"{provider_id}/{model_id}",
                        f"{provider_id}:{model_id}",
                        model_name,
                    ]
                ),
                "evidence_source": "litellm_model_info",
                "model_type": shape["model_type"],
                "preview_type": shape["preview_type"],
                "input_modalities": shape["input_modalities"],
                "output_modalities": shape["output_modalities"],
                "capabilities": shape["capabilities"],
                "confidence": shape["confidence"],
                "price_input": self._coerce_price_per_million(
                    info.get("input_cost_per_token")
                ),
                "price_output": self._coerce_price_per_million(
                    info.get("output_cost_per_token")
                ),
            },
        )

    def _derive_shape(
        self,
        model_id: str,
        model_info: dict[str, Any],
        litellm_params: dict[str, Any],
    ) -> dict[str, Any]:
        mode = str(model_info.get("mode") or "").strip().lower()
        supports_vision = bool(
            model_info.get("supports_vision")
            or model_info.get("supports_image_input")
        )
        supports_function_calling = bool(
            model_info.get("supports_function_calling")
            or model_info.get("supports_parallel_function_calling")
        )
        supports_response_schema = bool(
            model_info.get("supports_response_schema")
            or model_info.get("supports_native_streaming")
            and "response_format" in str(model_info)
        )

        if mode == "embedding":
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
                "confidence": 0.95,
            }

        if mode in {"image_generation", "image"} or _looks_like_image_generation(model_id):
            return {
                "model_type": "image_generation",
                "preview_type": "image",
                "input_modalities": ["text", "image"],
                "output_modalities": ["image"],
                "capabilities": {
                    "text_input": True,
                    "image_input": mode == "image" or bool(model_info.get("supports_image_input")),
                    "image_output": True,
                    "vision": False,
                    "tools": False,
                    "structured_output": False,
                },
                "confidence": 0.94,
            }

        if supports_vision or mode == "vision":
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
                    "tools": supports_function_calling,
                    "structured_output": supports_response_schema,
                },
                "confidence": 0.95,
            }

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
                "tools": supports_function_calling,
                "structured_output": supports_response_schema,
            },
            "confidence": 0.92,
        }

    def _resolve_provider_name(
        self,
        model_name: str,
        litellm_params: dict[str, Any],
        model_info: dict[str, Any],
    ) -> str:
        for candidate in (
            model_info.get("litellm_provider"),
            litellm_params.get("custom_llm_provider"),
            litellm_params.get("provider"),
        ):
            normalized = str(candidate or "").strip().lower()
            if normalized:
                return normalized
        if "/" in model_name:
            return model_name.split("/", 1)[0].strip().lower()
        return ""

    def _resolve_model_id(
        self,
        model_name: str,
        litellm_params: dict[str, Any],
        model_info: dict[str, Any],
        provider_name: str,
    ) -> str:
        for candidate in (
            litellm_params.get("model"),
            model_name,
            model_info.get("key"),
        ):
            normalized = str(candidate or "").strip()
            if not normalized:
                continue
            provider_prefix = f"{provider_name}/"
            if provider_name and normalized.lower().startswith(provider_prefix.lower()):
                normalized = normalized[len(provider_prefix) :]
            return normalized
        return ""

    def _map_provider_id(self, provider_name: str) -> str:
        normalized = provider_name.strip().lower()
        provider_map = {
            "openai": "openai",
            "azure": "openai",
            "anthropic": "anthropic",
        }
        return provider_map.get(normalized, normalized)

    def _build_client(self) -> httpx.Client:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.app_name,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )

    def _coerce_price_per_million(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return None
        if normalized < 0:
            return None
        return round(normalized * 1_000_000, 6)

    def _extract_http_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or "unknown error"

        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            if message:
                return message

        message = str(payload.get("message") or "").strip()
        return message or response.text or "unknown error"

    def _unique_strings(self, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result


def _looks_like_image_generation(model_id: str) -> bool:
    normalized = model_id.lower()
    return any(token in normalized for token in ("flux", "sdxl", "stable-diffusion"))


def _serialize_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
