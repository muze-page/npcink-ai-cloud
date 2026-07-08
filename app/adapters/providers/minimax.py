from __future__ import annotations

import base64
import time
from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
    ProviderExecutionError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
)
from app.adapters.providers.openai import OpenAIProviderAdapter
from app.domain.audio_generation.contracts import (
    AUDIO_GENERATION_RESULT_CONTRACT,
    resolve_audio_generation_text,
)
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_QUALITY_MODEL_ID,
)


@dataclass(frozen=True, slots=True)
class _MiniMaxSchemaSource:
    name: str
    url: str
    feature: str
    surface: str


@dataclass(slots=True)
class _MiniMaxSchemaModelEvidence:
    model_id: str
    feature: str
    surface: str
    source_names: list[str]
    source_urls: list[str]


MINIMAX_OFFICIAL_SCHEMA_SOURCES: tuple[_MiniMaxSchemaSource, ...] = (
    _MiniMaxSchemaSource(
        name="speech_t2a_asyncapi",
        url="https://platform.minimax.io/docs/api-reference/speech/t2a/api/asyncapi.json",
        feature="audio_generation",
        surface="audio_generation",
    ),
    _MiniMaxSchemaSource(
        name="image_text_to_image_openapi",
        url="https://platform.minimax.io/docs/api-reference/image/generation/api/text-to-image.json",
        feature="image_generation",
        surface="image_generation",
    ),
    _MiniMaxSchemaSource(
        name="image_image_to_image_openapi",
        url="https://platform.minimax.io/docs/api-reference/image/generation/api/image-to-image.json",
        feature="image_generation",
        surface="image_generation",
    ),
    _MiniMaxSchemaSource(
        name="video_text_to_video_openapi",
        url="https://platform.minimax.io/docs/api-reference/video/generation/api/text-to-video.json",
        feature="video_generation",
        surface="video_generation",
    ),
    _MiniMaxSchemaSource(
        name="video_image_to_video_openapi",
        url="https://platform.minimax.io/docs/api-reference/video/generation/api/image-to-video.json",
        feature="video_generation",
        surface="video_generation",
    ),
    _MiniMaxSchemaSource(
        name="video_subject_reference_to_video_openapi",
        url=(
            "https://platform.minimax.io/docs/api-reference/video/generation/api/"
            "subject-reference-to-video.json"
        ),
        feature="video_generation",
        surface="video_generation",
    ),
    _MiniMaxSchemaSource(
        name="video_start_end_to_video_openapi",
        url=(
            "https://platform.minimax.io/docs/api-reference/video/generation/api/"
            "start-end-to-video.json"
        ),
        feature="video_generation",
        surface="video_generation",
    ),
)

MINIMAX_TEXT_MODEL_IDS = (
    "MiniMax-M2",
    "MiniMax-M2.1",
    "MiniMax-M2.1-highspeed",
    "MiniMax-M2.5",
    "MiniMax-M2.5-highspeed",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "MiniMax-M3",
)

MINIMAX_VERIFIED_AUDIO_MODELS: dict[str, dict[str, object]] = {
    AUDIO_NARRATION_MODEL_ID: {
        "instance_id": "minimax-global-speech-28-turbo",
        "family": "speech-2.8",
        "tier": "balanced",
        "is_default": True,
        "weight": 100,
        "capability_tags": [
            "audio_generation",
            "narration",
            "summary",
            "default",
            "balanced",
        ],
    },
    AUDIO_NARRATION_QUALITY_MODEL_ID: {
        "instance_id": "minimax-global-speech-28-hd",
        "family": "speech-2.8",
        "tier": "quality",
        "is_default": False,
        "weight": 120,
        "capability_tags": [
            "audio_generation",
            "narration",
            "summary",
            "quality",
        ],
    },
}


class MiniMaxProviderAdapter:
    provider_id = "minimax"
    display_name = "MiniMax"
    adapter_type = "minimax"

    def __init__(
        self,
        *,
        base_url: str = "https://api.minimaxi.com",
        api_key: str | None = None,
        group_id: str | None = None,
        timeout_seconds: float = 30.0,
        default_voice_id: str = "male-qn-qingse",
        allow_sample_catalog: bool = False,
        allow_sample_execution: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.group_id = str(group_id or "").strip()
        self.timeout_seconds = timeout_seconds
        self.default_voice_id = str(default_voice_id or "male-qn-qingse").strip()
        self.allow_sample_catalog = allow_sample_catalog
        self.allow_sample_execution = allow_sample_execution
        self.transport = transport

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        if self._http_enabled:
            models = self._fetch_official_catalog_models()
        elif self.allow_sample_catalog:
            models = self._sample_catalog_models()
        else:
            raise RuntimeError("MiniMax catalog refresh requires configured credentials")

        if not models:
            raise ValueError("MiniMax catalog refresh returned no usable models")

        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=models,
        )

    def _fetch_official_catalog_models(self) -> list[CatalogModelSeed]:
        try:
            with self._build_model_catalog_client() as client:
                response = client.get("/models")
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderExecutionError(
                "provider.timeout",
                "MiniMax model catalog request timed out",
            ) from error
        except httpx.HTTPStatusError as error:
            raise ProviderExecutionError(
                self._map_http_status_error(error.response.status_code),
                self._extract_http_error_message(error.response),
                retryable=error.response.status_code >= 500 or error.response.status_code == 429,
            ) from error
        except httpx.RequestError as error:
            raise ProviderExecutionError("provider.network_error", str(error)) from error

        try:
            response_json = response.json()
        except ValueError as error:
            raise ValueError("MiniMax model catalog response was not valid JSON") from error

        raw_models = response_json.get("data") if isinstance(response_json, dict) else None
        if not isinstance(raw_models, list):
            raise ValueError("MiniMax model catalog response did not include a model list")

        models: list[CatalogModelSeed] = []
        seen_model_ids: set[str] = set()
        for raw_model in raw_models:
            model_id = self._official_model_id(raw_model)
            if not model_id or model_id in seen_model_ids:
                continue
            seen_model_ids.add(model_id)
            models.append(self._model_from_official_id(model_id, raw_model))
        for evidence in self._fetch_official_schema_models():
            if evidence.model_id in seen_model_ids:
                continue
            seen_model_ids.add(evidence.model_id)
            models.append(self._model_from_official_schema_evidence(evidence))
        return models

    def _sample_catalog_models(self) -> list[CatalogModelSeed]:
        return [
            self._model_from_official_id(AUDIO_NARRATION_MODEL_ID, {}),
            self._model_from_official_id(AUDIO_NARRATION_QUALITY_MODEL_ID, {}),
            *[self._model_from_official_id(model_id, {}) for model_id in MINIMAX_TEXT_MODEL_IDS],
        ]

    def _fetch_official_schema_models(self) -> list[_MiniMaxSchemaModelEvidence]:
        by_model_id: dict[str, _MiniMaxSchemaModelEvidence] = {}
        with self._build_official_schema_client() as client:
            for source in MINIMAX_OFFICIAL_SCHEMA_SOURCES:
                schema = self._fetch_official_schema(client, source)
                for model_id in self._extract_model_enum_values(schema):
                    evidence = by_model_id.setdefault(
                        model_id,
                        _MiniMaxSchemaModelEvidence(
                            model_id=model_id,
                            feature=source.feature,
                            surface=source.surface,
                            source_names=[],
                            source_urls=[],
                        ),
                    )
                    if source.name not in evidence.source_names:
                        evidence.source_names.append(source.name)
                    if source.url not in evidence.source_urls:
                        evidence.source_urls.append(source.url)

        return list(by_model_id.values())

    def _fetch_official_schema(
        self,
        client: httpx.Client,
        source: _MiniMaxSchemaSource,
    ) -> Any:
        try:
            response = client.get(source.url)
            response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderExecutionError(
                "provider.timeout",
                f"MiniMax official schema request timed out: {source.name}",
            ) from error
        except httpx.HTTPStatusError as error:
            raise ProviderExecutionError(
                self._map_http_status_error(error.response.status_code),
                (
                    "MiniMax official schema request failed "
                    f"for {source.name}: {self._extract_http_error_message(error.response)}"
                ),
                retryable=error.response.status_code >= 500
                or error.response.status_code == 429,
            ) from error
        except httpx.RequestError as error:
            raise ProviderExecutionError(
                "provider.network_error",
                f"MiniMax official schema request failed for {source.name}: {error}",
            ) from error

        try:
            return response.json()
        except ValueError as error:
            raise ValueError(
                f"MiniMax official schema response was not valid JSON: {source.name}"
            ) from error

    def _extract_model_enum_values(self, payload: Any) -> list[str]:
        model_ids: list[str] = []

        def visit(value: Any, path: tuple[str, ...]) -> None:
            if isinstance(value, dict):
                enum_values = value.get("enum")
                if isinstance(enum_values, list) and path and path[-1] == "model":
                    for enum_value in enum_values:
                        if isinstance(enum_value, str) and enum_value.strip():
                            normalized = enum_value.strip()
                            if normalized not in model_ids:
                                model_ids.append(normalized)
                for key, child in value.items():
                    visit(child, (*path, str(key)))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, (*path, str(index)))

        visit(payload, ())
        return model_ids

    def _model_from_official_id(self, model_id: str, raw_model: Any) -> CatalogModelSeed:
        metadata = self._infer_model_metadata(model_id)
        raw_payload = raw_model if isinstance(raw_model, dict) else {}
        raw_json: dict[str, object] = {
            "source": "official_models_endpoint",
            "upstream_model_id": model_id,
            "official_listed": True,
            "surface": metadata["surface"],
            "runtime_support": "verified" if metadata["instances"] else "not_verified",
            "enrichment_source": "minimax_local_rules",
        }
        if metadata["tier"]:
            raw_json["tier"] = metadata["tier"]
        if raw_payload:
            raw_json["upstream"] = raw_payload

        return CatalogModelSeed(
            model_id=model_id,
            family=str(metadata["family"]),
            feature=str(metadata["feature"]),
            status="available",
            context_window=metadata["context_window"],
            price_input=None,
            price_output=None,
            is_deprecated=bool(metadata["deprecated"]),
            fallback_candidate=bool(metadata["fallback_candidate"]),
            raw_json=raw_json,
            instances=metadata["instances"],
        )

    def _model_from_official_schema_evidence(
        self,
        evidence: _MiniMaxSchemaModelEvidence,
    ) -> CatalogModelSeed:
        metadata = self._infer_model_metadata(
            evidence.model_id,
            feature_hint=evidence.feature,
            surface_hint=evidence.surface,
        )
        raw_json: dict[str, object] = {
            "source": "official_schema_model_enum",
            "upstream_model_id": evidence.model_id,
            "official_schema_listed": True,
            "official_schema_source_names": evidence.source_names,
            "official_schema_source_urls": evidence.source_urls,
            "surface": metadata["surface"],
            "runtime_support": "verified" if metadata["instances"] else "not_verified",
            "enrichment_source": "minimax_local_rules",
        }
        if metadata["tier"]:
            raw_json["tier"] = metadata["tier"]

        return CatalogModelSeed(
            model_id=evidence.model_id,
            family=str(metadata["family"]),
            feature=str(metadata["feature"]),
            status="available",
            context_window=metadata["context_window"],
            price_input=None,
            price_output=None,
            is_deprecated=bool(metadata["deprecated"]),
            fallback_candidate=bool(metadata["fallback_candidate"]),
            raw_json=raw_json,
            instances=metadata["instances"],
        )

    def _infer_model_metadata(
        self,
        model_id: str,
        *,
        feature_hint: str | None = None,
        surface_hint: str | None = None,
    ) -> dict[str, Any]:
        normalized = model_id.strip()
        lowered = normalized.lower()
        if normalized in MINIMAX_VERIFIED_AUDIO_MODELS:
            audio = MINIMAX_VERIFIED_AUDIO_MODELS[normalized]
            raw_capability_tags = audio.get("capability_tags", [])
            capability_tags = (
                [str(tag) for tag in raw_capability_tags]
                if isinstance(raw_capability_tags, list)
                else []
            )
            raw_weight = audio.get("weight", 0)
            weight = int(raw_weight) if isinstance(raw_weight, int | float | str) else 0
            return {
                "family": str(audio["family"]),
                "feature": "audio_generation",
                "surface": "audio_generation",
                "tier": str(audio["tier"]),
                "context_window": None,
                "deprecated": False,
                "fallback_candidate": False,
                "instances": [
                    CatalogInstanceSeed(
                        instance_id=str(audio["instance_id"]),
                        endpoint_variant="t2a_v2",
                        region="global",
                        capability_tags=capability_tags,
                        is_default=bool(audio["is_default"]),
                        weight=weight,
                    )
                ],
            }
        if feature_hint == "audio_generation":
            family = ".".join(normalized.split("-")[:2]) if "-" in normalized else "audio"
            return {
                "family": family,
                "feature": "audio_generation",
                "surface": surface_hint or "audio_generation",
                "tier": self._infer_tier(normalized),
                "context_window": None,
                "deprecated": lowered.startswith(("speech-01", "speech-02")),
                "fallback_candidate": False,
                "instances": [],
            }
        if feature_hint == "image_generation":
            return {
                "family": "image",
                "feature": "image_generation",
                "surface": surface_hint or "image_generation",
                "tier": "",
                "context_window": None,
                "deprecated": False,
                "fallback_candidate": False,
                "instances": [],
            }
        if feature_hint == "video_generation":
            return {
                "family": "video",
                "feature": "video_generation",
                "surface": surface_hint or "video_generation",
                "tier": "",
                "context_window": None,
                "deprecated": False,
                "fallback_candidate": False,
                "instances": [],
            }
        if lowered.startswith("speech-"):
            family = ".".join(normalized.split("-")[:2]) if "-" in normalized else "speech"
            return {
                "family": family,
                "feature": "audio_generation",
                "surface": "audio_generation",
                "tier": self._infer_tier(normalized),
                "context_window": None,
                "deprecated": lowered.startswith(("speech-01", "speech-02")),
                "fallback_candidate": False,
                "instances": [],
            }
        if normalized in MINIMAX_TEXT_MODEL_IDS or lowered.startswith(("minimax-m", "abab")):
            tier = "economy" if "highspeed" in lowered else "balanced"
            return {
                "family": (
                    "MiniMax-M" if lowered.startswith("minimax-m") else normalized.split("-")[0]
                ),
                "feature": "text",
                "surface": "text_generation",
                "tier": tier,
                "context_window": 200000,
                "deprecated": False,
                "fallback_candidate": True,
                "instances": [
                    CatalogInstanceSeed(
                        instance_id=f"minimax-global-{self._slugify(normalized)}",
                        endpoint_variant="chat_completions",
                        region="global",
                        capability_tags=["text", tier],
                        is_default=normalized == "MiniMax-M3",
                        weight=90 if tier == "economy" else 100,
                    )
                ],
            }
        if lowered.startswith("image"):
            return {
                "family": "image",
                "feature": "image_generation",
                "surface": "image_generation",
                "tier": "",
                "context_window": None,
                "deprecated": False,
                "fallback_candidate": False,
                "instances": [],
            }
        if (
            "hailuo" in lowered
            or lowered.startswith("video")
            or lowered.startswith(("t2v-", "i2v-", "s2v-"))
        ):
            return {
                "family": "video",
                "feature": "video_generation",
                "surface": "video_generation",
                "tier": "",
                "context_window": None,
                "deprecated": False,
                "fallback_candidate": False,
                "instances": [],
            }
        if lowered.startswith("music"):
            return {
                "family": "music",
                "feature": "audio_generation",
                "surface": "music_generation",
                "tier": "",
                "context_window": None,
                "deprecated": False,
                "fallback_candidate": False,
                "instances": [],
            }
        return {
            "family": normalized.split("-")[0] if "-" in normalized else normalized,
            "feature": "text",
            "surface": "text_generation",
            "tier": "balanced",
            "context_window": None,
            "deprecated": False,
            "fallback_candidate": True,
            "instances": [
                CatalogInstanceSeed(
                    instance_id=f"minimax-global-{self._slugify(normalized)}",
                    endpoint_variant="chat_completions",
                    region="global",
                    capability_tags=["text", "balanced"],
                    is_default=False,
                    weight=100,
                )
            ],
        }

    def _official_model_id(self, raw_model: Any) -> str:
        if isinstance(raw_model, str):
            return raw_model.strip()
        if isinstance(raw_model, dict):
            for key in ("id", "model", "model_id", "name"):
                value = raw_model.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        if request.endpoint_variant == "chat_completions":
            return self._execute_text(request)
        if request.endpoint_variant != "t2a_v2":
            raise ProviderExecutionError(
                "provider.unsupported_operation",
                f"MiniMax endpoint variant is not supported: {request.endpoint_variant}",
                retryable=False,
            )
        if self._http_enabled:
            return self._execute_http(request)
        if not self.allow_sample_execution:
            raise ProviderExecutionError(
                "runtime.provider_not_configured",
                "MiniMax credentials are not configured",
                retryable=False,
            )
        return self._execute_sample(request)

    def _text_catalog_models(self) -> list[CatalogModelSeed]:
        return [
            CatalogModelSeed(
                model_id=model_id,
                family="MiniMax-M",
                feature="text",
                status="available",
                context_window=200000,
                price_input=None,
                price_output=None,
                fallback_candidate=True,
                raw_json={
                    "surface": "text_generation",
                    "protocol": "openai_compatible",
                    "tier": "economy" if "highspeed" in model_id.lower() else "balanced",
                },
                instances=[
                    CatalogInstanceSeed(
                        instance_id=f"minimax-global-{self._slugify(model_id)}",
                        endpoint_variant="chat_completions",
                        region="global",
                        capability_tags=[
                            "text",
                            "economy" if "highspeed" in model_id.lower() else "balanced",
                        ],
                        is_default=model_id == "MiniMax-M3",
                        weight=90 if "highspeed" in model_id.lower() else 100,
                    )
                ],
            )
            for model_id in MINIMAX_TEXT_MODEL_IDS
        ]

    def _execute_text(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        adapter = OpenAIProviderAdapter(
            base_url=self._chat_base_url,
            api_key=self.api_key or None,
            timeout_seconds=self.timeout_seconds,
            app_name="npcink-ai-cloud",
            allow_sample_catalog=self.allow_sample_catalog,
            allow_sample_execution=self.allow_sample_execution,
            provider_label=self.display_name,
            transport=self.transport,
        )
        adapter.provider_id = self.provider_id
        adapter.display_name = self.display_name
        request = self._without_openai_incompatible_chat_metadata(request)
        return adapter.execute(request)

    def _without_openai_incompatible_chat_metadata(
        self,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionRequest:
        if "metadata" not in request.input_payload:
            return request
        input_payload = dict(request.input_payload)
        input_payload.pop("metadata", None)
        return replace(request, input_payload=input_payload)

    @property
    def _http_enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def _chat_base_url(self) -> str:
        if self.base_url.endswith("/v1"):
            return self.base_url
        return f"{self.base_url}/v1"

    def _execute_http(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        started_at = time.monotonic()
        payload = self._build_t2a_payload(request)
        try:
            with self._build_client(request.timeout_ms) as client:
                path = "/v1/t2a_v2"
                if self.group_id:
                    path = f"{path}?GroupId={self.group_id}"
                response = client.post(path, json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderExecutionError(
                "provider.timeout",
                f"MiniMax T2A exceeded timeout budget for {request.instance_id}",
            ) from error
        except httpx.HTTPStatusError as error:
            raise ProviderExecutionError(
                self._map_http_status_error(error.response.status_code),
                self._extract_http_error_message(error.response),
                retryable=error.response.status_code >= 500 or error.response.status_code == 429,
            ) from error
        except httpx.RequestError as error:
            raise ProviderExecutionError("provider.network_error", str(error)) from error

        response_json = response.json()
        base_resp = response_json.get("base_resp")
        if isinstance(base_resp, dict):
            status_code = int(base_resp.get("status_code") or 0)
            if status_code != 0:
                raise ProviderExecutionError(
                    self._map_minimax_status_code(status_code),
                    str(base_resp.get("status_msg") or "MiniMax T2A request failed"),
                    retryable=status_code in {1002, 1008, 2013},
                )

        latency_ms = max(1, int((time.monotonic() - started_at) * 1000))
        return self._build_result(request, response_json, latency_ms)

    def _build_client(self, request_timeout_ms: int) -> httpx.Client:
        timeout_seconds = min(
            max(request_timeout_ms / 1000, 0.001),
            max(self.timeout_seconds, 0.001),
        )
        return httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
            transport=self.transport,
        )

    def _build_model_catalog_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._chat_base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )

    def _build_official_schema_client(self) -> httpx.Client:
        return httpx.Client(
            headers={"Accept": "application/json"},
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )

    def _build_t2a_payload(self, request: ProviderExecutionRequest) -> dict[str, Any]:
        options = request.input_payload
        text = resolve_audio_generation_text(options)
        voice_id = str(options.get("voice_id") or self.default_voice_id).strip()
        audio_format = str(options.get("format") or "mp3").strip().lower()
        payload: dict[str, Any] = {
            "model": request.model_id,
            "text": text,
            "stream": False,
            "output_format": str(options.get("response_format") or "url").strip(),
            "voice_setting": {
                "voice_id": voice_id,
                "speed": self._coerce_int(options.get("speed"), default=1),
                "vol": self._coerce_int(options.get("volume"), default=1),
                "pitch": self._coerce_int(options.get("pitch"), default=0),
            },
            "audio_setting": {
                "sample_rate": self._coerce_int(options.get("sample_rate"), default=32000),
                "bitrate": self._coerce_int(options.get("bitrate"), default=128000),
                "format": audio_format,
                "channel": self._coerce_int(options.get("channel"), default=1),
            },
        }
        if isinstance(options.get("language_boost"), str) and options["language_boost"].strip():
            payload["language_boost"] = options["language_boost"].strip()
        if isinstance(options.get("subtitle_enable"), bool):
            payload["subtitle_enable"] = bool(options["subtitle_enable"])
        return payload

    def _build_result(
        self,
        request: ProviderExecutionRequest,
        response_json: dict[str, Any],
        latency_ms: int,
    ) -> ProviderExecutionResult:
        data = response_json.get("data")
        data_payload = data if isinstance(data, dict) else {}
        extra_info = data_payload.get("extra_info") or response_json.get("extra_info")
        extra = extra_info if isinstance(extra_info, dict) else {}
        text = resolve_audio_generation_text(request.input_payload)
        usage_characters = self._coerce_int(extra.get("usage_characters"), default=len(text))
        duration_ms = self._coerce_int(
            extra.get("audio_length") or data_payload.get("audio_length"),
            default=0,
        )
        audio_format = str(
            extra.get("audio_format") or request.input_payload.get("format") or "mp3"
        ).strip()
        audio_url = str(
            data_payload.get("audio_url")
            or data_payload.get("url")
            or data_payload.get("download_url")
            or (
                data_payload.get("audio")
                if str(data_payload.get("audio") or "").startswith(("http://", "https://"))
                else ""
            )
            or ""
        ).strip()
        audio_b64 = self._audio_b64_from_response(data_payload)
        candidate: dict[str, Any] = {
            "index": 1,
            "url": audio_url,
            "b64_json": audio_b64,
            "mime_type": self._mime_type(audio_format),
            "format": audio_format,
            "duration_seconds": round(duration_ms / 1000, 3) if duration_ms > 0 else 0,
            "transcript": text,
        }
        if data_payload.get("subtitle_file"):
            candidate["subtitle_url"] = str(data_payload.get("subtitle_file") or "")
        output = {
            "artifact_type": "audio_generation_candidates",
            "contract_version": AUDIO_GENERATION_RESULT_CONTRACT,
            "model_id": request.model_id,
            "provider": self.provider_id,
            "audios": [candidate],
            "provider_response_format": "url" if audio_url else "b64_json",
            "direct_wordpress_write": False,
            "usage": {
                "characters": usage_characters,
                "duration_ms": duration_ms,
                "trace_id": str(response_json.get("trace_id") or ""),
            },
        }
        return ProviderExecutionResult(
            output=output,
            latency_ms=latency_ms,
            tokens_in=usage_characters,
            tokens_out=0,
            cost=self._estimate_cost(request, usage_characters),
        )

    def _execute_sample(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        text = resolve_audio_generation_text(request.input_payload) or request.ability_name
        usage_characters = len(text)
        latency_ms = 120 + (request.retry_count * 25)
        output = {
            "artifact_type": "audio_generation_candidates",
            "contract_version": AUDIO_GENERATION_RESULT_CONTRACT,
            "model_id": request.model_id,
            "provider": self.provider_id,
            "audios": [
                {
                    "index": 1,
                    "url": "",
                    "b64_json": base64.b64encode(b"ID3\x04\x00\x00\x00\x00\x00\x00").decode(
                        "ascii"
                    ),
                    "mime_type": "audio/mpeg",
                    "format": "mp3",
                    "duration_seconds": max(1, round(usage_characters / 12, 3)),
                    "transcript": text,
                }
            ],
            "provider_response_format": "b64_json",
            "direct_wordpress_write": False,
            "usage": {"characters": usage_characters, "duration_ms": usage_characters * 80},
        }
        return ProviderExecutionResult(
            output=output,
            latency_ms=latency_ms,
            tokens_in=usage_characters,
            tokens_out=0,
            cost=self._estimate_cost(request, usage_characters),
        )

    def _audio_b64_from_response(self, data_payload: dict[str, Any]) -> str:
        for key in ("audio_b64", "b64_json"):
            value = data_payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        audio_hex = data_payload.get("audio")
        if isinstance(audio_hex, str) and audio_hex.strip():
            if audio_hex.strip().startswith(("http://", "https://")):
                return ""
            try:
                return base64.b64encode(bytes.fromhex(audio_hex.strip())).decode("ascii")
            except ValueError:
                return ""
        return ""

    def _estimate_cost(self, request: ProviderExecutionRequest, usage_characters: int) -> float:
        if request.price_input is None:
            return 0.0
        return round((usage_characters / 1_000_000) * max(0.0, request.price_input), 6)

    def _map_http_status_error(self, status_code: int) -> str:
        if status_code == 401:
            return "provider.auth_invalid"
        if status_code == 403:
            return "provider.access_denied"
        if status_code == 404:
            return "provider.endpoint_not_found"
        if status_code == 429:
            return "provider.rate_limited"
        if status_code >= 500:
            return "provider.upstream_unavailable"
        return "provider.invalid_request"

    def _map_minimax_status_code(self, status_code: int) -> str:
        if status_code in {1004, 1008}:
            return "provider.rate_limited"
        if status_code in {2013, 2037}:
            return "provider.content_filtered"
        if status_code in {1001, 1002}:
            return "provider.upstream_error"
        return "provider.invalid_request"

    def _extract_http_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            base_resp = payload.get("base_resp")
            if isinstance(base_resp, dict):
                message = str(base_resp.get("status_msg") or "").strip()
                if message:
                    return message
            for key in ("message", "error", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return response.text[:4000]

    def _mime_type(self, audio_format: str) -> str:
        normalized = audio_format.strip().lower()
        if normalized == "wav":
            return "audio/wav"
        if normalized == "pcm":
            return "audio/L16"
        return "audio/mpeg"

    def _coerce_int(self, value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _coerce_float(self, value: Any, *, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _infer_tier(self, model_id: str) -> str:
        lowered = model_id.lower()
        if "hd" in lowered:
            return "quality"
        if "turbo" in lowered:
            return "balanced"
        return ""

    def _slugify(self, value: str) -> str:
        normalized = "".join(
            character.lower() if character.isalnum() else "-"
            for character in value.strip()
        )
        while "--" in normalized:
            normalized = normalized.replace("--", "-")
        return normalized.strip("-") or "model"
