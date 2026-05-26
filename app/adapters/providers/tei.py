from __future__ import annotations

from typing import Iterable

import httpx

from app.adapters.providers.base import (
    CatalogInstanceSeed,
    CatalogModelSeed,
    ProviderCatalogSnapshot,
    ProviderExecutionError,
    ProviderExecutionRequest,
)
from app.adapters.providers.openai import OpenAIProviderAdapter


class TEIProviderAdapter(OpenAIProviderAdapter):
    provider_id = "tei"
    display_name = "Self-hosted TEI"
    adapter_type = "tei"

    def __init__(
        self,
        *,
        base_url: str,
        model_ids: Iterable[str],
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        region: str = "self-hosted",
        context_window: int = 8192,
        app_name: str = "magick-ai-cloud",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            base_url=_normalize_tei_base_url(base_url),
            api_key=api_key,
            organization=None,
            timeout_seconds=timeout_seconds,
            sample_catalog_profile="",
            app_name=app_name,
            allow_http_without_api_key=True,
            model_namespace_prefix=self.provider_id,
            transport=transport,
        )
        self.model_ids = [str(item).strip() for item in model_ids if str(item).strip()]
        self.region = str(region or "self-hosted").strip() or "self-hosted"
        self.context_window = max(1, int(context_window))

    def fetch_catalog(self) -> ProviderCatalogSnapshot:
        if not self.model_ids:
            raise ValueError("tei provider requires at least one configured model id")
        return ProviderCatalogSnapshot(
            provider_id=self.provider_id,
            display_name=self.display_name,
            adapter_type=self.adapter_type,
            models=[
                CatalogModelSeed(
                    model_id=self._namespace_catalog_model_id(model_id),
                    family=self._infer_catalog_family(model_id),
                    feature="embedding",
                    status="available",
                    context_window=self.context_window,
                    price_input=0.0,
                    price_output=0.0,
                    fallback_candidate=False,
                    raw_json={
                        "catalog_source": "tei_config",
                        "tier": "default",
                        "upstream_model_id": model_id,
                    },
                    instances=[
                        CatalogInstanceSeed(
                            instance_id=(
                                f"{self._slugify(self.provider_id)}-"
                                f"{self._slugify(self.region)}-"
                                f"{self._slugify(self._namespace_catalog_model_id(model_id))}"
                            ),
                            endpoint_variant="embeddings",
                            region=self.region,
                            capability_tags=["embedding", "default", "tei"],
                            is_default=True,
                            weight=100,
                        )
                    ],
                )
                for model_id in self.model_ids
            ],
        )

    def execute(self, request: ProviderExecutionRequest):
        if request.execution_kind != "embedding" or request.endpoint_variant != "embeddings":
            raise ProviderExecutionError(
                "provider.unsupported_operation",
                "tei adapter only supports embedding execution via embeddings endpoint",
            )
        return super().execute(request)


def _normalize_tei_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip().rstrip("/")
    if not normalized:
        return normalized
    if normalized.endswith("/v1"):
        return normalized
    return f"{normalized}/v1"
