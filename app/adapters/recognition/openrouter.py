from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx


class OpenRouterRecognitionEvidenceImporter:
    def __init__(
        self,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        site_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self.site_url = str(site_url or "").strip()
        self.transport = transport

    def fetch_upstream_evidence_payload(self) -> dict[str, Any]:
        try:
            with self._build_client() as client:
                response = client.get("/models")
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise RuntimeError("openrouter recognition evidence refresh timed out") from error
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                "openrouter recognition evidence refresh failed with "
                f"{error.response.status_code}: {self._extract_http_error_message(error.response)}"
            ) from error
        except httpx.RequestError as error:
            raise RuntimeError(
                f"openrouter recognition evidence refresh network error: {error}"
            ) from error

        payload = response.json()
        raw_models = payload.get("data")
        if not isinstance(raw_models, list):
            raise ValueError("openrouter /models response missing data list")

        generated_at = _serialize_timestamp(datetime.now(UTC))
        revision = str(
            response.headers.get("etag")
            or response.headers.get("last-modified")
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
                "openrouter_snapshot": revision,
            },
            "records": records,
        }

    def _build_record(self, payload: Any) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(payload, dict):
            return None

        raw_model_id = str(payload.get("id") or "").strip()
        if not raw_model_id:
            return None

        architecture = payload.get("architecture")
        pricing = payload.get("pricing")
        supported_parameters = payload.get("supported_parameters")
        shape = _derive_shape_from_openrouter_metadata(
            raw_model_id=raw_model_id,
            architecture=architecture if isinstance(architecture, dict) else {},
            pricing=pricing if isinstance(pricing, dict) else {},
            supported_parameters=supported_parameters if isinstance(supported_parameters, list) else [],
        )

        aliases = _unique_strings(
            [
                raw_model_id,
                str(payload.get("canonical_slug") or ""),
                str(payload.get("name") or ""),
            ]
        )
        return (
            f"openrouter::{raw_model_id}",
            {
                "provider": "openrouter",
                "model_id": raw_model_id,
                "aliases": aliases,
                "match_keys": _unique_strings(
                    aliases + [f"openrouter/{raw_model_id}", f"openrouter:{raw_model_id}"]
                ),
                "evidence_source": "openrouter_model_info",
                "model_type": shape["model_type"],
                "preview_type": shape["preview_type"],
                "input_modalities": shape["input_modalities"],
                "output_modalities": shape["output_modalities"],
                "capabilities": shape["capabilities"],
                "confidence": shape["confidence"],
                "deprecated": bool(payload.get("expiration_date")),
                "price_input": _normalize_openrouter_price_per_million(pricing, "prompt"),
                "price_output": _normalize_openrouter_price_per_million(pricing, "completion"),
            },
        )

    def _build_client(self) -> httpx.Client:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.app_name,
            "X-Title": self.app_name,
        }
        if self.site_url:
            headers["HTTP-Referer"] = self.site_url
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
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


def _derive_shape_from_openrouter_metadata(
    *,
    raw_model_id: str,
    architecture: dict[str, Any],
    pricing: dict[str, Any],
    supported_parameters: list[Any],
) -> dict[str, Any]:
    modality = str(architecture.get("modality") or "").strip().lower()
    input_modalities = _unique_strings(
        [str(item).strip().lower() for item in architecture.get("input_modalities", [])]
        if isinstance(architecture.get("input_modalities"), list)
        else []
    )
    output_modalities = _unique_strings(
        [str(item).strip().lower() for item in architecture.get("output_modalities", [])]
        if isinstance(architecture.get("output_modalities"), list)
        else []
    )
    supported = {
        str(item).strip().lower()
        for item in supported_parameters
        if str(item).strip()
    }
    normalized_id = raw_model_id.lower()

    has_embedding_output = "embedding" in output_modalities or "embedding" in modality
    has_image_output = "image" in output_modalities
    has_image_input = "image" in input_modalities
    has_video_input = "video" in input_modalities
    has_tools = "tools" in supported or "tool_choice" in supported
    has_structured_output = "response_format" in supported

    if has_embedding_output:
        return {
            "model_type": "embedding",
            "preview_type": "embedding",
            "input_modalities": input_modalities or ["text"],
            "output_modalities": output_modalities or ["embedding"],
            "capabilities": {
                "text_input": "text" in (input_modalities or ["text"]),
                "image_input": has_image_input,
                "image_output": False,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.95,
        }

    if has_image_output or any(
        token in normalized_id for token in ("flux", "sdxl", "stable-diffusion", "imagen")
    ):
        return {
            "model_type": "image_generation",
            "preview_type": "image",
            "input_modalities": input_modalities or ["text", "image"],
            "output_modalities": output_modalities or ["image"],
            "capabilities": {
                "text_input": "text" in (input_modalities or ["text"]),
                "image_input": has_image_input,
                "image_output": True,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.95,
        }

    if has_image_input or has_video_input or "vision" in normalized_id or "vl" in normalized_id:
        return {
            "model_type": "vision",
            "preview_type": "text",
            "input_modalities": input_modalities or ["text", "image"],
            "output_modalities": output_modalities or ["text"],
            "capabilities": {
                "text_input": True,
                "image_input": has_image_input or has_video_input,
                "image_output": False,
                "vision": True,
                "tools": has_tools,
                "structured_output": has_structured_output,
            },
            "confidence": 0.94,
        }

    prompt_price = str(pricing.get("prompt") or "").strip()
    completion_price = str(pricing.get("completion") or "").strip()
    confidence = 0.92 if prompt_price or completion_price else 0.9
    return {
        "model_type": "chat",
        "preview_type": "text",
        "input_modalities": input_modalities or ["text"],
        "output_modalities": output_modalities or ["text"],
        "capabilities": {
            "text_input": True,
            "image_input": False,
            "image_output": False,
            "vision": False,
            "tools": has_tools,
            "structured_output": has_structured_output,
        },
        "confidence": confidence,
    }


def _normalize_openrouter_price_per_million(
    pricing: dict[str, Any] | None,
    key: str,
) -> float | None:
    if not isinstance(pricing, dict):
        return None
    raw_value = str(pricing.get(key) or "").strip()
    if not raw_value:
        return None
    try:
        unit_price = float(raw_value)
    except (TypeError, ValueError):
        return None
    if unit_price < 0:
        return None
    return round(unit_price * 1_000_000, 6)


def _serialize_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result
