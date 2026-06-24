from __future__ import annotations

import base64
import time
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
from app.domain.audio_generation.contracts import (
    AUDIO_GENERATION_RESULT_CONTRACT,
    resolve_audio_generation_text,
)
from app.domain.hosted_model_defaults import (
    AUDIO_NARRATION_MODEL_ID,
    AUDIO_NARRATION_QUALITY_MODEL_ID,
)


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
        if not self._http_enabled and not self.allow_sample_catalog:
            raise RuntimeError("MiniMax catalog refresh requires configured credentials")

        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id=AUDIO_NARRATION_MODEL_ID,
                    family="speech-2.8",
                    feature="audio_generation",
                    status="available",
                    price_input=None,
                    price_output=None,
                    fallback_candidate=False,
                    raw_json={
                        "tier": "balanced",
                        "surface": "audio_generation",
                        "intents": ["article_narration", "article_audio_summary"],
                    },
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="minimax-global-speech-28-turbo",
                            endpoint_variant="t2a_v2",
                            region="global",
                            capability_tags=[
                                "audio_generation",
                                "narration",
                                "summary",
                                "default",
                                "balanced",
                            ],
                            is_default=True,
                            weight=100,
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id=AUDIO_NARRATION_QUALITY_MODEL_ID,
                    family="speech-2.8",
                    feature="audio_generation",
                    status="available",
                    price_input=None,
                    price_output=None,
                    fallback_candidate=False,
                    raw_json={
                        "tier": "quality",
                        "surface": "audio_generation",
                        "intents": ["article_narration", "article_audio_summary"],
                    },
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="minimax-global-speech-28-hd",
                            endpoint_variant="t2a_v2",
                            region="global",
                            capability_tags=[
                                "audio_generation",
                                "narration",
                                "summary",
                                "quality",
                            ],
                            is_default=False,
                            weight=120,
                        )
                    ],
                ),
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
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

    @property
    def _http_enabled(self) -> bool:
        return bool(self.api_key)

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
