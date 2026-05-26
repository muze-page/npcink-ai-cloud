from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WooCommerceProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None = None
    title: str = ""
    short_description: str = ""
    long_description: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    target_locales: list[str] = Field(default_factory=list)


class ProductTitleSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original: str = ""
    suggestions: list[str] = Field(default_factory=list)
    reasoning: str = ""


class ProductDescriptionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_type: str = ""  # "short" or "long"
    original: str = ""
    draft: str = ""
    reasoning: str = ""


class ProductAttributeSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    existing: dict[str, Any] = Field(default_factory=dict)
    suggested_additions: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""


class ProductLocalizationSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str = ""
    localized_title: str = ""
    localized_short_description: str = ""
    localized_long_description: str = ""
    reasoning: str = ""


class ProductSchemaSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_type: str = "Product"  # e.g. Product, Offer, AggregateOffer
    recommended_fields: dict[str, Any] = Field(default_factory=dict)
    reasoning: str = ""


class WooCommerceGrowthAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str | None = None
    title_suggestion: ProductTitleSuggestion | None = None
    description_drafts: list[ProductDescriptionDraft] = Field(default_factory=list)
    attribute_suggestion: ProductAttributeSuggestion | None = None
    localization_suggestions: list[ProductLocalizationSuggestion] = Field(default_factory=list)
    schema_suggestion: ProductSchemaSuggestion | None = None
    requires_local_approval: bool = True


class BatchPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_reference: str = ""
    suggested_tasks: list[str] = Field(default_factory=list)


class BatchTaskPlanSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BatchPlanItem] = Field(default_factory=list)
    total_products: int = 0
    task_types: list[str] = Field(default_factory=list)
    requires_local_approval: bool = True


# =============================================================================
# GEO Visibility Pack models
# =============================================================================

class GeoPageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str | None = None
    url: str = ""
    title: str = ""
    content_text: str = ""
    schema_markup: dict[str, Any] | None = Field(default=None)
    current_llms_txt: str | None = Field(default=None)
    locale: str = "en"


class LlmsTxtSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    present: bool = False
    suggested_snippet: str = ""
    reasoning: str = ""


class SchemaCheckItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_type: str = ""  # e.g. FAQPage, Article, Product
    check_name: str = ""  # e.g. "required_fields_present", "valid_json_ld"
    passed: bool = False
    details: str = ""


class AiCitationCheckItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_name: str = ""  # e.g. "structured_headings", "entity_markup", "key_points_summary"
    passed: bool = False
    details: str = ""


class ContentRewriteSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str = ""  # e.g. "intro", "faq", "product_description"
    original: str = ""
    suggested: str = ""
    reasoning: str = ""


class GeoVisibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str | None = None
    url: str = ""
    locale: str = "en"
    llms_txt_suggestion: LlmsTxtSuggestion | None = None
    schema_checks: list[SchemaCheckItem] = Field(default_factory=list)
    ai_citation_checks: list[AiCitationCheckItem] = Field(default_factory=list)
    content_rewrite_suggestions: list[ContentRewriteSuggestion] = Field(default_factory=list)
    summary: str = ""
    requires_local_approval: bool = True


class GeoVisibilityBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reports: list[GeoVisibilityReport] = Field(default_factory=list)
    total_pages: int = 0
    requires_local_approval: bool = True


# =============================================================================
# Managed Model Routing Pack models
# =============================================================================

class ManagedRoutingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site_context: dict[str, Any] = Field(default_factory=dict)


class RoutingProfileRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_id: str = ""  # e.g. "deepseek-economy", "openai-quality"
    route_label: str = ""  # e.g. "DeepSeek 低成本路线"
    description: str = ""
    suggested_model_ids: list[str] = Field(default_factory=list)
    estimated_cost_tier: str = ""  # "budget", "balanced", "premium"
    use_case_hint: str = ""  # e.g. "batch_translation", "critical_reasoning"
    reasoning: str = ""


class ProviderHealthItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = ""
    health_status: str = ""  # e.g. "healthy", "degraded", "unhealthy"
    instance_count: int = 0
    healthy_instance_count: int = 0
    reasoning: str = ""


class FallbackOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_model_id: str = ""
    fallback_model_ids: list[str] = Field(default_factory=list)
    reasoning: str = ""


class BudgetAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert_level: str = ""  # "none", "notice", "warning"
    message: str = ""
    reasoning: str = ""


class QualityRegressionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = ""
    regression_type: str = ""  # e.g. "latency", "error_rate", "availability"
    severity: str = ""  # "low", "medium", "high"
    reasoning: str = ""


class ManagedRoutingReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[RoutingProfileRecommendation] = Field(default_factory=list)
    provider_health: list[ProviderHealthItem] = Field(default_factory=list)
    fallback_options: list[FallbackOption] = Field(default_factory=list)
    budget_alerts: list[BudgetAlert] = Field(default_factory=list)
    quality_regressions: list[QualityRegressionItem] = Field(default_factory=list)
    summary: str = ""
    requires_local_approval: bool = True
    cloud_only_recommendation: bool = True
