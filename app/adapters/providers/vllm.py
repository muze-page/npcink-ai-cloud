from __future__ import annotations

import httpx

from app.adapters.providers.openai import OpenAIProviderAdapter


class VLLMProviderAdapter(OpenAIProviderAdapter):
    provider_id = "vllm"
    display_name = "Self-hosted vLLM"
    adapter_type = "vllm"

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
