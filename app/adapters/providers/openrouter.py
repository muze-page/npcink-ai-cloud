from __future__ import annotations

import httpx

from app.adapters.providers.openai import OpenAIProviderAdapter


class OpenRouterProviderAdapter(OpenAIProviderAdapter):
    provider_id = "openrouter"
    display_name = "OpenRouter"
    adapter_type = "openrouter"

    def __init__(
        self,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str,
        timeout_seconds: float = 30.0,
        site_url: str | None = None,
        app_name: str = "Magick AI Cloud",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        extra_headers = {"X-Title": app_name}
        if str(site_url or "").strip():
            extra_headers["HTTP-Referer"] = str(site_url).strip()
        super().__init__(
            base_url=base_url,
            api_key=api_key,
            organization=None,
            timeout_seconds=timeout_seconds,
            sample_catalog_profile="",
            app_name=app_name,
            extra_headers=extra_headers,
            model_namespace_prefix=self.provider_id,
            transport=transport,
        )
