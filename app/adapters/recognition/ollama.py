from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import httpx


class OllamaRecognitionEvidenceImporter:
    def __init__(
        self,
        *,
        model_names: list[str] | None = None,
        base_url: str = "http://127.0.0.1:11434",
        api_key: str | None = None,
        catalog_enabled: bool = False,
        catalog_limit: int = 250,
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model_names = [
            model_name.strip()
            for model_name in (model_names or [])
            if model_name.strip()
        ]
        self.base_url = base_url.rstrip("/")
        self.api_key = str(api_key or "").strip() or None
        self.catalog_enabled = bool(catalog_enabled)
        self.catalog_limit = max(int(catalog_limit), 1)
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self.transport = transport

    def fetch_upstream_evidence_payload(self) -> dict[str, Any]:
        records: dict[str, dict[str, Any]] = {}
        generated_at = _serialize_timestamp(datetime.now(UTC))
        model_names = self._resolve_model_names()
        with self._build_client() as client:
            for model_name in model_names:
                try:
                    response = client.post("/api/show", json={"model": model_name})
                    response.raise_for_status()
                except httpx.TimeoutException as error:
                    raise RuntimeError("ollama recognition evidence refresh timed out") from error
                except httpx.HTTPStatusError as error:
                    raise RuntimeError(
                        "ollama recognition evidence refresh failed with "
                        f"{error.response.status_code}: {self._extract_http_error_message(error.response)}"
                    ) from error
                except httpx.RequestError as error:
                    raise RuntimeError(
                        f"ollama recognition evidence refresh network error: {error}"
                    ) from error

                record = self._build_record(model_name, response.json())
                if record is None:
                    continue
                record_key, payload = record
                records[record_key] = payload

        return {
            "version": "recognition_upstream_v1",
            "generated_at": generated_at,
            "sources": {
                "ollama_snapshot": generated_at,
            },
            "records": records,
        }

    def _resolve_model_names(self) -> list[str]:
        if self.model_names:
            return self.model_names
        if not self.catalog_enabled:
            return []

        try:
            with self._build_client() as client:
                response = client.get("/api/tags")
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise RuntimeError("ollama catalog recognition refresh timed out") from error
        except httpx.HTTPStatusError as error:
            raise RuntimeError(
                "ollama catalog recognition refresh failed with "
                f"{error.response.status_code}: {self._extract_http_error_message(error.response)}"
            ) from error
        except httpx.RequestError as error:
            raise RuntimeError(f"ollama catalog recognition refresh network error: {error}") from error

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("ollama catalog recognition refresh returned a non-object payload")
        models = payload.get("models")
        if not isinstance(models, list):
            raise RuntimeError("ollama catalog recognition refresh returned an invalid models payload")

        names: list[str] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            model_name = str(item.get("name") or item.get("model") or "").strip()
            if model_name and model_name not in names:
                names.append(model_name)
            if len(names) >= self.catalog_limit:
                break
        return names

    def _build_record(
        self,
        model_name: str,
        payload: Any,
    ) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(payload, dict):
            return None

        requested_name = model_name.strip()
        details = payload.get("details")
        details_map = details if isinstance(details, dict) else {}
        capabilities = payload.get("capabilities")
        capabilities_list = [
            str(item).strip().lower()
            for item in capabilities
            if str(item).strip()
        ] if isinstance(capabilities, list) else []
        families = [
            str(item).strip().lower()
            for item in details_map.get("families", [])
            if str(item).strip()
        ] if isinstance(details_map.get("families"), list) else []
        family = str(details_map.get("family") or "").strip().lower()
        model_info = payload.get("model_info")
        info = model_info if isinstance(model_info, dict) else {}

        shape = _derive_shape(requested_name, capabilities_list, family, families, info)
        aliases = _unique_strings(
            [
                requested_name,
                str(payload.get("model") or ""),
                str(payload.get("modelfile") or "").split("FROM ", 1)[-1].splitlines()[0].strip()
                if str(payload.get("modelfile") or "").strip()
                else "",
            ]
        )
        return (
            f"ollama::{requested_name}",
            {
                "provider": "ollama",
                "model_id": requested_name,
                "aliases": aliases,
                "match_keys": _unique_strings(
                    aliases + [f"ollama/{requested_name}", f"ollama:{requested_name}"]
                ),
                "evidence_source": "ollama_catalog_show" if self.catalog_enabled else "ollama_show",
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


def _derive_shape(
    model_name: str,
    capabilities: list[str],
    family: str,
    families: list[str],
    model_info: dict[str, Any],
) -> dict[str, Any]:
    capability_set = {str(item).strip().lower() for item in capabilities if str(item).strip()}
    info_keys = [str(key).strip().lower() for key in model_info.keys() if str(key).strip()]
    searchable_values = [
        model_name.lower(),
        family,
        *families,
        str(model_info.get("general.architecture") or "").strip().lower(),
    ]
    token_set = _tokenize_strings(searchable_values)
    family_terms = {family, *families}

    has_image_generation = "image" in capability_set or bool(
        token_set & {"flux", "sdxl", "zimagepipeline", "diffusion"}
    )
    if not has_image_generation and any(term in family_terms for term in ("stable-diffusion", "diffusion")):
        has_image_generation = True

    has_vision = "vision" in capability_set or bool(token_set & {"llava", "vision", "vl"}) or any(
        ".vision." in key for key in info_keys
    )
    has_embedding = "embedding" in capability_set or (
        not capability_set.intersection({"completion", "vision", "audio", "tools", "thinking", "image"})
        and (
            bool(token_set & {"embedding", "embed", "bge", "gte", "e5"})
            or bool(family_terms & {"bert", "sentence-transformers"})
        )
    )
    supports_tools = "tools" in capability_set

    if has_embedding:
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
            "confidence": 0.92,
        }

    if has_image_generation:
        return {
            "model_type": "image_generation",
            "preview_type": "image",
            "input_modalities": ["text", "image"],
            "output_modalities": ["image"],
            "capabilities": {
                "text_input": True,
                "image_input": "image" in capability_set,
                "image_output": True,
                "vision": False,
                "tools": False,
                "structured_output": False,
            },
            "confidence": 0.84,
        }

    if has_vision:
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
                "tools": supports_tools,
                "structured_output": False,
            },
            "confidence": 0.9,
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
            "tools": supports_tools,
            "structured_output": False,
        },
        "confidence": 0.82,
    }


def _serialize_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def _tokenize_strings(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in re.split(r"[^a-z0-9]+", str(value or "").strip().lower()):
            if token:
                tokens.add(token)
    return tokens
