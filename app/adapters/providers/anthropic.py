from __future__ import annotations

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
from app.adapters.providers.openai import OpenAIProviderAdapter


class AnthropicProviderAdapter(OpenAIProviderAdapter):
    provider_id = "anthropic"
    display_name = "Anthropic"
    adapter_type = "anthropic"

    def __init__(
        self,
        *,
        base_url: str = "https://api.anthropic.com",
        api_key: str | None = None,
        api_version: str = "2023-06-01",
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        allow_sample_catalog: bool = True,
        allow_sample_execution: bool = True,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            organization=None,
            timeout_seconds=timeout_seconds,
            app_name=app_name,
            allow_sample_catalog=allow_sample_catalog,
            allow_sample_execution=allow_sample_execution,
            transport=transport,
        )
        self.api_version = api_version

    def _build_sample_catalog(self) -> ProviderCatalogSnapshot:
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id="anthropic-haiku-sample",
                    family="anthropic-haiku",
                    feature="text",
                    status="available",
                    fallback_candidate=True,
                    raw_json={"catalog_source": "sample", "tier": "economy"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="anthropic-global-text-economy",
                            endpoint_variant="messages",
                            region="global",
                            capability_tags=["text", "economy"],
                            is_default=True,
                            weight=80,
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id="anthropic-sonnet-sample",
                    family="anthropic-sonnet",
                    feature="text",
                    status="available",
                    fallback_candidate=True,
                    raw_json={"catalog_source": "sample", "tier": "balanced"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="anthropic-global-text-balanced",
                            endpoint_variant="messages",
                            region="global",
                            capability_tags=["text", "balanced"],
                            is_default=True,
                            weight=100,
                        )
                    ],
                ),
                CatalogModelSeed(
                    model_id="anthropic-opus-sample",
                    family="anthropic-opus",
                    feature="text",
                    status="available",
                    fallback_candidate=False,
                    raw_json={"catalog_source": "sample", "tier": "quality"},
                    instances=[
                        CatalogInstanceSeed(
                            instance_id="anthropic-global-text-quality",
                            endpoint_variant="messages",
                            region="global",
                            capability_tags=["text", "quality"],
                            is_default=True,
                            weight=120,
                        )
                    ],
                ),
            ],
        )

    def execute(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        self._maybe_raise_simulated_error(request)
        if request.execution_kind != "text":
            raise ProviderExecutionError(
                "provider.unsupported_operation",
                f"anthropic adapter only supports text execution, got {request.execution_kind}",
            )
        if request.endpoint_variant != "messages":
            raise ProviderExecutionError(
                "provider.unsupported_operation",
                f"anthropic adapter requires messages endpoint, got {request.endpoint_variant}",
            )
        if not self._http_enabled:
            if not self.allow_sample_execution:
                raise ProviderExecutionError(
                    "provider.auth_invalid",
                    "provider execution requires configured upstream credentials",
                )
            return self._execute_sample(request)

        return self._execute_http(request)

    def _build_catalog_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers=self._build_headers(),
            timeout=max(self.timeout_seconds, 0.001),
            transport=self.transport,
        )

    def _build_client(self, request_timeout_ms: int) -> httpx.Client:
        timeout_seconds = min(
            max(request_timeout_ms / 1000, 0.001),
            max(self.timeout_seconds, 0.001),
        )
        return httpx.Client(
            base_url=self.base_url,
            headers=self._build_headers(),
            timeout=timeout_seconds,
            transport=self.transport,
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": self.api_version,
            "Content-Type": "application/json",
            "User-Agent": self.app_name,
        }
        return headers

    def _fetch_http_catalog(self) -> ProviderCatalogSnapshot:
        try:
            with self._build_catalog_client() as client:
                response = client.get("/v1/models")
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise RuntimeError("provider catalog refresh timed out") from error
        except httpx.HTTPStatusError as error:
            message = self._extract_http_error_message(error.response)
            raise RuntimeError(
                f"provider catalog refresh failed with {error.response.status_code}: {message}"
            ) from error
        except httpx.RequestError as error:
            raise RuntimeError(
                f"provider catalog refresh network error: {error}"
            ) from error

        response_json = response.json()
        raw_models = response_json.get("data")
        if not isinstance(raw_models, list):
            raise ValueError("provider catalog response missing data list")

        catalog_models: list[CatalogModelSeed] = []
        for raw_model in raw_models:
            model_seed = self._build_catalog_model_seed(raw_model)
            if model_seed is None:
                continue
            catalog_models.append(model_seed)

        if not catalog_models:
            raise ValueError("provider catalog refresh returned no usable models")

        catalog_models.sort(key=self._catalog_sort_key)

        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=catalog_models,
        )

    def _execute_http(self, request: ProviderExecutionRequest) -> ProviderExecutionResult:
        payload = self._build_messages_request(request)
        started_at = time.monotonic()

        try:
            with self._build_client(request.timeout_ms) as client:
                response = client.post("/v1/messages", json=payload)
                response.raise_for_status()
        except httpx.TimeoutException as error:
            raise ProviderExecutionError(
                "provider.timeout",
                f"provider call exceeded timeout budget for {request.instance_id}",
            ) from error
        except httpx.HTTPStatusError as error:
            error_code = self._map_anthropic_error(error.response)
            raise ProviderExecutionError(
                error_code,
                self._extract_http_error_message(error.response),
                retryable=error_code
                in {
                    "provider.timeout",
                    "provider.rate_limited",
                    "provider.upstream_unavailable",
                    "provider.upstream_error",
                },
            ) from error
        except httpx.RequestError as error:
            raise ProviderExecutionError(
                "provider.network_error",
                str(error),
            ) from error

        response_json = response.json()
        latency_ms = max(1, int((time.monotonic() - started_at) * 1000))
        return self._build_messages_result(request, response_json, latency_ms)

    def _build_messages_request(
        self,
        request: ProviderExecutionRequest,
    ) -> dict[str, Any]:
        system_text, messages = self._normalize_messages_input(request.input_payload)
        payload: dict[str, Any] = {
            "model": request.model_id,
            "messages": messages,
            "max_tokens": self._resolve_max_tokens(request.input_payload),
        }
        if system_text:
            payload["system"] = system_text
        if isinstance(request.input_payload.get("temperature"), (int, float)):
            payload["temperature"] = request.input_payload["temperature"]
        return payload

    def _build_messages_result(
        self,
        request: ProviderExecutionRequest,
        response_json: dict[str, Any],
        latency_ms: int,
    ) -> ProviderExecutionResult:
        usage = response_json.get("usage", {})
        output_text = self._extract_anthropic_output_text(response_json.get("content"))
        output = {
            "output_text": output_text,
            "messages": [{"role": "assistant", "content": output_text}],
            "model_id": response_json.get("model", request.model_id),
        }
        tokens_in = self._coerce_int(usage.get("input_tokens"))
        tokens_out = self._coerce_int(usage.get("output_tokens"))
        return ProviderExecutionResult(
            output=output,
            latency_ms=latency_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=self._estimate_cost(request, tokens_in, tokens_out),
            finish_reason=self._resolve_finish_reason(response_json),
        )

    def _build_catalog_model_seed(self, payload: Any) -> CatalogModelSeed | None:
        if not isinstance(payload, dict):
            return None

        model_id = payload.get("id")
        if not isinstance(model_id, str) or not model_id:
            return None

        tier = self._infer_catalog_tier(model_id, "text", payload)
        region = self._infer_catalog_region(payload)
        status = self._infer_catalog_status(payload)
        is_deprecated = self._infer_catalog_deprecated(status, payload)

        return CatalogModelSeed(
            model_id=model_id,
            family=self._infer_catalog_family(model_id),
            feature="text",
            status=status,
            context_window=self._coerce_int(
                self._lookup_nested(
                    payload,
                    ("context_window",),
                    ("metadata", "context_window"),
                )
            ),
            price_input=self._coerce_float(
                self._lookup_nested(payload, ("price_input",), ("pricing", "input"))
            ),
            price_output=self._coerce_float(
                self._lookup_nested(payload, ("price_output",), ("pricing", "output"))
            ),
            is_deprecated=is_deprecated,
            fallback_candidate=tier in {"economy", "balanced"}
            and status == "available"
            and not is_deprecated,
            raw_json={
                "catalog_source": "provider_api",
                "display_name": payload.get("display_name"),
                "tier": tier,
                "type": payload.get("type"),
            },
            instances=[
                CatalogInstanceSeed(
                    instance_id=(
                        f"{self._slugify(self.provider_id)}-"
                        f"{self._slugify(region)}-"
                        f"{self._slugify(model_id)}"
                    ),
                    endpoint_variant="messages",
                    region=region,
                    capability_tags=["text", tier],
                    is_default=True,
                    weight=self._catalog_weight_for_tier(tier),
                )
            ],
        )

    def _infer_catalog_tier(
        self,
        model_id: str,
        feature: str,
        payload: dict[str, Any],
    ) -> str:
        del feature
        explicit_tier = self._lookup_nested(
            payload,
            ("tier",),
            ("metadata", "tier"),
            ("raw", "tier"),
        )
        if isinstance(explicit_tier, str):
            normalized_tier = explicit_tier.strip().lower()
            if normalized_tier in {"economy", "balanced", "quality"}:
                return normalized_tier

        model_key = model_id.lower()
        if "haiku" in model_key:
            return "economy"
        if "sonnet" in model_key:
            return "balanced"
        if "opus" in model_key:
            return "quality"
        return "balanced"

    def _infer_catalog_family(self, model_id: str) -> str:
        model_key = model_id.strip().lower()
        if "haiku" in model_key:
            return "claude-haiku"
        if "sonnet" in model_key:
            return "claude-sonnet"
        if "opus" in model_key:
            return "claude-opus"
        return super()._infer_catalog_family(model_id)

    def _extract_http_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or f"http {response.status_code}"

        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        return super()._extract_http_error_message(response)

    def _map_anthropic_error(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return self._map_http_status_error(response.status_code)

        error = payload.get("error")
        error_type = error.get("type") if isinstance(error, dict) else None
        if error_type == "authentication_error":
            return "provider.auth_invalid"
        if error_type == "permission_error":
            return "provider.access_denied"
        if error_type == "not_found_error":
            return "provider.endpoint_not_found"
        if error_type == "rate_limit_error":
            return "provider.rate_limited"
        if error_type == "overloaded_error":
            return "provider.upstream_unavailable"
        if error_type == "invalid_request_error":
            return "provider.invalid_request"

        return self._map_http_status_error(response.status_code)

    def _map_http_status_error(self, status_code: int) -> str:
        if status_code == 400:
            return "provider.invalid_request"
        if status_code == 401:
            return "provider.auth_invalid"
        if status_code == 403:
            return "provider.access_denied"
        if status_code == 404:
            return "provider.endpoint_not_found"
        if status_code in {408, 524}:
            return "provider.timeout"
        if status_code == 429:
            return "provider.rate_limited"
        if status_code in {502, 503, 504, 529}:
            return "provider.upstream_unavailable"
        if status_code >= 500:
            return "provider.upstream_error"
        return "provider.invalid_request"

    def _normalize_messages_input(
        self,
        payload: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]]]:
        messages = payload.get("messages")
        normalized_messages: list[dict[str, Any]] = []
        system_fragments: list[str] = []

        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue

                content = self._normalize_message_content(message.get("content"))
                if content == "" or content == []:
                    continue

                role = message.get("role")
                if role == "system":
                    system_text = self._flatten_message_content(content)
                    if system_text:
                        system_fragments.append(system_text)
                    continue

                normalized_role = role if role in {"user", "assistant"} else "user"
                normalized_messages.append(
                    {"role": normalized_role, "content": content}
                )

        if not normalized_messages:
            source_text = self._collect_source_text(payload) or "empty input"
            normalized_messages = [{"role": "user", "content": source_text}]

        explicit_system = payload.get("system")
        if isinstance(explicit_system, str) and explicit_system.strip():
            system_fragments.insert(0, explicit_system.strip())

        system_text = "\n\n".join(
            fragment for fragment in system_fragments if fragment
        )
        return system_text, normalized_messages

    def _normalize_message_content(self, content: Any) -> str | list[dict[str, str]]:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            blocks: list[dict[str, str]] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                item_type = item.get("type")
                if item_type not in {None, "text"}:
                    continue
                text = item.get("text") or item.get("content")
                if isinstance(text, str) and text.strip():
                    blocks.append({"type": "text", "text": text})
            if blocks:
                return blocks

        return ""

    def _flatten_message_content(self, content: str | list[dict[str, str]]) -> str:
        if isinstance(content, str):
            return content.strip()

        fragments = [
            block["text"].strip()
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        ]
        return " ".join(fragment for fragment in fragments if fragment).strip()

    def _resolve_max_tokens(self, payload: dict[str, Any]) -> int:
        for key in ("max_tokens", "max_output_tokens"):
            value = payload.get(key)
            if isinstance(value, int) and value > 0:
                return value
        return 1024

    def _extract_anthropic_output_text(self, content: Any) -> str:
        if not isinstance(content, list):
            return ""

        fragments: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "text":
                continue
            text = item.get("text")
            if isinstance(text, str) and text:
                fragments.append(text)

        return " ".join(fragment for fragment in fragments if fragment).strip()

    def _resolve_finish_reason(self, payload: dict[str, Any]) -> str:
        stop_reason = payload.get("stop_reason")
        if isinstance(stop_reason, str) and stop_reason:
            return stop_reason
        return "stop"
