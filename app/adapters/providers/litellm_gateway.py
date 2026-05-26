from __future__ import annotations

from typing import Any

import httpx

from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
)
from app.adapters.providers.openai import OpenAIProviderAdapter


class LiteLLMGatewayProviderAdapter(OpenAIProviderAdapter):
    provider_id = "litellm"
    display_name = "LiteLLM Gateway"
    adapter_type = "litellm_gateway"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        app_name: str = "magick-ai-cloud",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            organization=None,
            timeout_seconds=timeout_seconds,
            sample_catalog_profile="",
            app_name=app_name,
            allow_http_without_api_key=True,
            model_namespace_prefix=self.provider_id,
            transport=transport,
        )

    def _fetch_http_catalog(self) -> ProviderCatalogSnapshot:
        try:
            with self._build_catalog_client() as client:
                response = client.get("/model/info")
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
            model_seed = self._build_litellm_catalog_model_seed(raw_model)
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

    def _build_litellm_catalog_model_seed(
        self,
        payload: Any,
    ) -> CatalogModelSeed | None:
        if not isinstance(payload, dict):
            return None

        model_name = str(payload.get("model_name") or "").strip()
        litellm_params = payload.get("litellm_params")
        params = litellm_params if isinstance(litellm_params, dict) else {}
        model_info = payload.get("model_info")
        info = model_info if isinstance(model_info, dict) else {}

        upstream_model_id = self._resolve_model_id(model_name, params, info)
        if not upstream_model_id:
            return None

        feature = self._derive_feature(upstream_model_id, info, params)
        if feature not in {"text", "vision", "embedding"}:
            return None

        status = "available"
        tier = self._infer_catalog_tier(
            upstream_model_id,
            feature,
            {
                "tier": self._derive_tier(upstream_model_id, feature),
            },
        )
        endpoint_variant = self._select_catalog_endpoint_variant(feature, tier)
        catalog_model_id = self._namespace_catalog_model_id(upstream_model_id)

        return CatalogModelSeed(
            model_id=catalog_model_id,
            family=self._infer_catalog_family(upstream_model_id),
            feature=feature,
            status=status,
            context_window=self._coerce_int(
                info.get("max_input_tokens")
                or info.get("max_tokens")
                or info.get("context_window")
            ),
            price_input=self._coerce_float(
                info.get("input_cost_per_token")
                or info.get("input_cost_per_second")
            ),
            price_output=self._coerce_float(info.get("output_cost_per_token")),
            is_deprecated=False,
            fallback_candidate=(
                feature == "text"
                and tier in {"economy", "balanced"}
                and status == "available"
            ),
            raw_json={
                "catalog_source": "litellm_gateway",
                "tier": tier,
                "upstream_model_id": upstream_model_id,
                "litellm_provider": self._resolve_provider_name(model_name, params, info),
                "mode": str(info.get("mode") or "").strip().lower(),
            },
            instances=[
                CatalogInstanceSeed(
                    instance_id=(
                        f"{self._slugify(self.provider_id)}-gateway-"
                        f"{self._slugify(catalog_model_id)}"
                    ),
                    endpoint_variant=endpoint_variant,
                    region="gateway",
                    capability_tags=self._build_catalog_capability_tags(
                        feature,
                        tier,
                        {"metadata": {"capability_tags": ["litellm", "gateway"]}},
                    ),
                    is_default=True,
                    weight=self._catalog_weight_for_tier(tier),
                )
            ],
        )

    def _derive_feature(
        self,
        model_id: str,
        model_info: dict[str, Any],
        litellm_params: dict[str, Any],
    ) -> str:
        mode = str(model_info.get("mode") or "").strip().lower()
        supports_vision = bool(
            model_info.get("supports_vision")
            or model_info.get("supports_image_input")
            or litellm_params.get("supports_vision")
        )
        if mode == "embedding":
            return "embedding"
        if mode in {"image_generation", "image"}:
            return "unsupported"
        if supports_vision or mode == "vision":
            return "vision"
        if "embedding" in model_id.lower():
            return "embedding"
        return "text"

    def _derive_tier(self, model_id: str, feature: str) -> str:
        if feature == "embedding":
            return "default"
        if feature == "vision":
            return "quality"
        return self._infer_catalog_tier(model_id, feature, {})

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
        return "unknown"

    def _resolve_model_id(
        self,
        model_name: str,
        litellm_params: dict[str, Any],
        model_info: dict[str, Any],
    ) -> str:
        provider_name = self._resolve_provider_name(model_name, litellm_params, model_info)
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
