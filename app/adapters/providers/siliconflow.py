from __future__ import annotations

import httpx

from app.adapters.providers.openai import OpenAIProviderAdapter


class SiliconFlowProviderAdapter(OpenAIProviderAdapter):
    provider_id = "siliconflow"
    display_name = "SiliconFlow"
    adapter_type = "siliconflow"

    def __init__(
        self,
        *,
        base_url: str = "https://api.siliconflow.cn/v1",
        api_key: str,
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
            allow_sample_catalog=False,
            allow_sample_execution=False,
            provider_label=self.display_name,
            model_namespace_prefix=self.provider_id,
            transport=transport,
        )
