from __future__ import annotations

from typing import Any

from app.adapters.repositories.catalog_repository import CatalogRepository
from app.core.db import get_session
from app.domain.task_packs.models import (
    AiCitationCheckItem,
    BatchPlanItem,
    BatchTaskPlanSummary,
    BudgetAlert,
    ContentRewriteSuggestion,
    FallbackOption,
    GeoPageInput,
    GeoVisibilityBatchResult,
    GeoVisibilityReport,
    LlmsTxtSuggestion,
    ManagedRoutingInput,
    ManagedRoutingReport,
    ProductAttributeSuggestion,
    ProductDescriptionDraft,
    ProductLocalizationSuggestion,
    ProductSchemaSuggestion,
    ProductTitleSuggestion,
    ProviderHealthItem,
    QualityRegressionItem,
    RoutingProfileRecommendation,
    SchemaCheckItem,
    WooCommerceGrowthAnalysisResult,
    WooCommerceProductInput,
)


class WooCommerceGrowthPackService:
    """Generate suggestions and drafts for WooCommerce product growth.

    This service never writes to WooCommerce directly. All outputs are
    suggestions, drafts, or reports that require local approval before
    any product mutation.
    """

    def analyze_product(
        self,
        product_input: WooCommerceProductInput,
    ) -> WooCommerceGrowthAnalysisResult:
        """Analyze a single product and return growth suggestions."""
        title_suggestion = self._suggest_titles(product_input)
        description_drafts = self._draft_descriptions(product_input)
        attribute_suggestion = self._suggest_attributes(product_input)
        localization_suggestions = self._suggest_localizations(product_input)
        schema_suggestion = self._suggest_schema(product_input)

        return WooCommerceGrowthAnalysisResult(
            product_id=product_input.product_id,
            title_suggestion=title_suggestion,
            description_drafts=description_drafts,
            attribute_suggestion=attribute_suggestion,
            localization_suggestions=localization_suggestions,
            schema_suggestion=schema_suggestion,
            requires_local_approval=True,
        )

    def generate_batch_plan(
        self,
        items: list[WooCommerceProductInput],
    ) -> BatchTaskPlanSummary:
        """Generate a batch task plan summary for multiple products."""
        plan_items: list[BatchPlanItem] = []
        task_type_set: set[str] = set()

        for item in items:
            suggested_tasks: list[str] = []
            if item.title:
                suggested_tasks.append("title_optimization")
                task_type_set.add("title_optimization")
            if item.short_description or item.long_description:
                suggested_tasks.append("description_enhancement")
                task_type_set.add("description_enhancement")
            if item.attributes:
                suggested_tasks.append("attribute_completion")
                task_type_set.add("attribute_completion")
            if item.target_locales:
                suggested_tasks.append("localization")
                task_type_set.add("localization")
            suggested_tasks.append("seo_schema_enhancement")
            task_type_set.add("seo_schema_enhancement")

            plan_items.append(
                BatchPlanItem(
                    product_reference=item.product_id or item.title or "unknown",
                    suggested_tasks=suggested_tasks,
                )
            )

        return BatchTaskPlanSummary(
            items=plan_items,
            total_products=len(items),
            task_types=sorted(task_type_set),
            requires_local_approval=True,
        )

    def _suggest_titles(
        self,
        product_input: WooCommerceProductInput,
    ) -> ProductTitleSuggestion | None:
        if not product_input.title:
            return None

        original = product_input.title
        suggestions: list[str] = []

        # Simple heuristic-based suggestions for the minimal implementation.
        if len(original) < 30:
            suggestions.append(f"{original} — Premium Quality Selection")
        if "sale" not in original.lower():
            suggestions.append(f"{original} (Limited Offer)")
        suggestions.append(original)

        return ProductTitleSuggestion(
            original=original,
            suggestions=suggestions,
            reasoning="Titles are suggestions only; local approval required before update.",
        )

    def _draft_descriptions(
        self,
        product_input: WooCommerceProductInput,
    ) -> list[ProductDescriptionDraft]:
        drafts: list[ProductDescriptionDraft] = []

        if product_input.short_description:
            drafts.append(
                ProductDescriptionDraft(
                    draft_type="short",
                    original=product_input.short_description,
                    draft=(
                        f"{product_input.short_description}"
                        " Discover why customers love this product."
                    ),
                    reasoning="Draft short description for local review and approval.",
                )
            )

        if product_input.long_description:
            drafts.append(
                ProductDescriptionDraft(
                    draft_type="long",
                    original=product_input.long_description,
                    draft=(
                        f"{product_input.long_description}\n\n"
                        "Key Benefits:\n"
                        "- High quality\n"
                        "- Great value\n"
                        "- Fast delivery"
                    ),
                    reasoning="Draft long description for local review and approval.",
                )
            )

        return drafts

    def _suggest_attributes(
        self,
        product_input: WooCommerceProductInput,
    ) -> ProductAttributeSuggestion | None:
        existing = dict(product_input.attributes)
        suggested: dict[str, Any] = {}

        if "brand" not in existing:
            suggested["brand"] = "Suggested brand value (to be filled locally)"
        if "material" not in existing:
            suggested["material"] = "Suggested material value (to be filled locally)"
        if "color" not in existing:
            suggested["color"] = "Suggested color value (to be filled locally)"

        if not suggested:
            return None

        return ProductAttributeSuggestion(
            existing=existing,
            suggested_additions=suggested,
            reasoning="Attribute suggestions are drafts; local approval required before writing.",
        )

    def _suggest_localizations(
        self,
        product_input: WooCommerceProductInput,
    ) -> list[ProductLocalizationSuggestion]:
        suggestions: list[ProductLocalizationSuggestion] = []

        for locale in product_input.target_locales:
            short = product_input.short_description or "Localized short description placeholder"
            long = product_input.long_description or "Localized long description placeholder"
            suggestions.append(
                ProductLocalizationSuggestion(
                    locale=locale,
                    localized_title=(
                        f"[{locale}] {product_input.title or 'Localized title placeholder'}"
                    ),
                    localized_short_description=f"[{locale}] {short}",
                    localized_long_description=f"[{locale}] {long}",
                    reasoning="Localization drafts require local review before publication.",
                )
            )

        return suggestions

    def _suggest_schema(
        self,
        product_input: WooCommerceProductInput,
    ) -> ProductSchemaSuggestion | None:
        recommended_fields: dict[str, Any] = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": product_input.title or "Product name placeholder",
            "description": product_input.short_description or product_input.long_description or "",
            "offers": {
                "@type": "Offer",
                "availability": "https://schema.org/InStock",
            },
        }

        if product_input.categories:
            recommended_fields["category"] = product_input.categories[0]

        return ProductSchemaSuggestion(
            schema_type="Product",
            recommended_fields=recommended_fields,
            reasoning="SEO/GEO-ready Product Schema suggestion; local approval required.",
        )


class GeoVisibilityPackService:
    """Generate GEO visibility diagnostics, reports, and recommendations.

    This service never modifies site content, schema, or pages directly.
    All outputs are suggestions and reports that require local approval.
    No output promises automatic ranking, compliance, or AI citation.
    """

    def analyze_page(self, page_input: GeoPageInput) -> GeoVisibilityReport:
        """Analyze a single page and return a GEO visibility report."""
        llms_txt = self._check_llms_txt(page_input)
        schema_checks = self._check_schema(page_input)
        ai_citation_checks = self._check_ai_citation_structure(page_input)
        rewrite_suggestions = self._suggest_rewrites(page_input)

        return GeoVisibilityReport(
            page_id=page_input.page_id,
            url=page_input.url,
            locale=page_input.locale,
            llms_txt_suggestion=llms_txt,
            schema_checks=schema_checks,
            ai_citation_checks=ai_citation_checks,
            content_rewrite_suggestions=rewrite_suggestions,
            summary=(
                "GEO visibility diagnostics generated. "
                "This is a recommendation-only report; it does not promise ranking, "
                "compliance, or AI engine citation. Local review and approval are required."
            ),
            requires_local_approval=True,
        )

    def analyze_batch(
        self,
        inputs: list[GeoPageInput],
    ) -> GeoVisibilityBatchResult:
        """Analyze multiple pages and return a batch report."""
        reports = [self.analyze_page(item) for item in inputs]
        return GeoVisibilityBatchResult(
            reports=reports,
            total_pages=len(reports),
            requires_local_approval=True,
        )

    def _check_llms_txt(self, page_input: GeoPageInput) -> LlmsTxtSuggestion | None:
        present = bool(page_input.current_llms_txt and page_input.current_llms_txt.strip())
        if present:
            return LlmsTxtSuggestion(
                present=True,
                suggested_snippet="",
                reasoning="llms.txt is present. Review freshness and coverage periodically.",
            )
        snippet = (
            f"# {page_input.title or 'Site'}\n\n"
            f"- URL: {page_input.url or 'N/A'}\n"
            f"- Locale: {page_input.locale}\n"
        )
        return LlmsTxtSuggestion(
            present=False,
            suggested_snippet=snippet,
            reasoning="llms.txt not detected. Consider adding a concise llms.txt for AI crawlers.",
        )

    def _check_schema(self, page_input: GeoPageInput) -> list[SchemaCheckItem]:
        checks: list[SchemaCheckItem] = []
        schema = page_input.schema_markup or {}

        has_json_ld = bool(schema.get("@context") or schema.get("@type"))
        checks.append(
            SchemaCheckItem(
                schema_type=schema.get("@type", "Unknown"),
                check_name="json_ld_present",
                passed=has_json_ld,
                details="JSON-LD Schema markup is recommended for AI visibility."
                if not has_json_ld
                else "JSON-LD detected. Verify required fields are complete.",
            )
        )

        recommended_types = {"FAQPage", "Article", "Product"}
        detected_type = schema.get("@type", "")
        checks.append(
            SchemaCheckItem(
                schema_type=detected_type or "None",
                check_name="recommended_schema_type",
                passed=detected_type in recommended_types,
                details=(
                    f"Recommended schema types: {', '.join(recommended_types)}. "
                    "These help AI engines understand content structure."
                ),
            )
        )

        checks.append(
            SchemaCheckItem(
                schema_type=detected_type or "None",
                check_name="required_fields_present",
                passed=bool(schema.get("name") or page_input.title),
                details="Ensure 'name' or page title is present in structured data.",
            )
        )

        return checks

    def _check_ai_citation_structure(self, page_input: GeoPageInput) -> list[AiCitationCheckItem]:
        checks: list[AiCitationCheckItem] = []
        text = page_input.content_text

        has_headings = "#" in text or "<h" in text.lower()
        checks.append(
            AiCitationCheckItem(
                check_name="structured_headings",
                passed=has_headings,
                details="Structured headings help AI engines extract key points."
                if not has_headings
                else "Headings detected.",
            )
        )

        has_lists = "- " in text or "* " in text or "<li" in text.lower()
        checks.append(
            AiCitationCheckItem(
                check_name="list_based_summaries",
                passed=has_lists,
                details="Bullet or numbered lists improve AI summarization."
                if not has_lists
                else "Lists detected.",
            )
        )

        checks.append(
            AiCitationCheckItem(
                check_name="key_points_summary",
                passed=len(text) > 200,
                details="Substantial content length supports AI citation coverage."
                if len(text) > 200
                else "Content may be too short for reliable AI summarization.",
            )
        )

        return checks

    def _suggest_rewrites(self, page_input: GeoPageInput) -> list[ContentRewriteSuggestion]:
        suggestions: list[ContentRewriteSuggestion] = []
        text = page_input.content_text

        if text and len(text) < 300:
            suggestions.append(
                ContentRewriteSuggestion(
                    section="intro",
                    original=text[:120] if len(text) > 120 else text,
                    suggested=(
                        f"{text[:120] if len(text) > 120 else text}\n\n"
                        "[Suggested expansion] Add a concise value proposition and key facts."
                    ),
                    reasoning="Expand introductory content to improve AI engine coverage.",
                )
            )

        if text and "?" not in text:
            suggestions.append(
                ContentRewriteSuggestion(
                    section="faq",
                    original="",
                    suggested="Consider adding an FAQ section with 2–3 concise Q&A pairs.",
                    reasoning="FAQ structure improves AI citation and snippet eligibility.",
                )
            )

        return suggestions


class ManagedModelRoutingPackService:
    """Generate hosted routing profile recommendations and health summaries.

    This service queries the hosted catalog to produce read-only recommendations.
    It does not replace or override the local router truth. The local plugin
    retains final ownership of adopted routing profiles, snapshots, prompts,
    presets, and router configuration.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def generate_report(self, routing_input: ManagedRoutingInput) -> ManagedRoutingReport:
        """Generate a managed model routing report from the hosted catalog."""
        with get_session(self.database_url) as session:
            repository = CatalogRepository(session)
            models = repository.list_models(status="available", limit=200)[0]
            instances = repository.list_instances_for_provider()
            annotations = repository.list_model_annotations()

        recommendations = self._build_recommendations(models, annotations)
        provider_health = self._build_provider_health(instances)
        fallback_options = self._build_fallback_options(models, instances)
        budget_alerts = self._build_budget_alerts(models, routing_input)
        quality_regressions = self._build_quality_regressions(instances)

        return ManagedRoutingReport(
            recommendations=recommendations,
            provider_health=provider_health,
            fallback_options=fallback_options,
            budget_alerts=budget_alerts,
            quality_regressions=quality_regressions,
            summary=(
                "Hosted routing profile recommendations generated from cloud catalog. "
                "Local plugin retains final ownership of adopted profiles, snapshots, "
                "and router configuration. This report is recommendation-only."
            ),
            requires_local_approval=True,
            cloud_only_recommendation=True,
        )

    def _build_recommendations(
        self,
        models: list[Any],
        annotations: list[Any],
    ) -> list[RoutingProfileRecommendation]:
        recommendations: list[RoutingProfileRecommendation] = []

        annotation_map = {a.model_id: a for a in annotations}

        # DeepSeek / budget route
        budget_models = [
            m.model_id
            for m in models
            if m.provider_id in ("deepseek", "openai")
            and (
                getattr(annotation_map.get(m.model_id), "cost_tier", None) == "budget"
                or (m.price_input or 0) < 0.5
            )
        ]
        if budget_models:
            recommendations.append(
                RoutingProfileRecommendation(
                    route_id="deepseek-economy",
                    route_label="DeepSeek 低成本路线",
                    description=(
                        "Prioritize DeepSeek and low-cost OpenAI models "
                        "for high-volume, non-critical tasks."
                    ),
                    suggested_model_ids=budget_models[:3],
                    estimated_cost_tier="budget",
                    use_case_hint="batch_translation,content_draft",
                    reasoning="Low input/output pricing suitable for cost-sensitive workloads.",
                )
            )

        # Chinese / domestic route
        chinese_models = [
            m.model_id
            for m in models
            if m.provider_id in ("tongyi", "kimi", "alibaba", "moonshot")
        ]
        if chinese_models:
            recommendations.append(
                RoutingProfileRecommendation(
                    route_id="chinese-domestic",
                    route_label="通义 / Kimi 中文路线",
                    description=(
                        "Domestic-provider models optimized for "
                        "Chinese-language tasks and compliance."
                    ),
                    suggested_model_ids=chinese_models[:3],
                    estimated_cost_tier="balanced",
                    use_case_hint="chinese_copywriting,local_compliance",
                    reasoning="Tongyi and Kimi offer strong Chinese-language performance.",
                )
            )

        # Quality / upgrade route
        quality_models = [
            m.model_id
            for m in models
            if m.provider_id in ("openai", "anthropic")
            and (
                getattr(annotation_map.get(m.model_id), "cost_tier", None)
                in ("premium", "balanced")
                or (m.price_input or 0) >= 1.0
            )
        ]
        if quality_models:
            recommendations.append(
                RoutingProfileRecommendation(
                    route_id="openai-claude-quality",
                    route_label="OpenAI / Claude 高质量路线",
                    description=(
                        "High-quality models for critical reasoning, "
                        "complex tasks, and final review."
                    ),
                    suggested_model_ids=quality_models[:3],
                    estimated_cost_tier="premium",
                    use_case_hint="critical_reasoning,code_review,final_editing",
                    reasoning=(
                        "OpenAI and Claude models are recommended "
                        "for quality-critical workloads."
                    ),
                )
            )

        return recommendations

    def _build_provider_health(self, instances: list[Any]) -> list[ProviderHealthItem]:
        from collections import defaultdict

        by_provider: dict[str, list[Any]] = defaultdict(list)
        for inst in instances:
            by_provider[inst.provider_id].append(inst)

        health_items: list[ProviderHealthItem] = []
        for provider_id, insts in sorted(by_provider.items()):
            healthy = sum(1 for i in insts if i.health_status == "healthy")
            if healthy == len(insts):
                status = "healthy"
            elif healthy > 0:
                status = "degraded"
            else:
                status = "unhealthy"
            health_items.append(
                ProviderHealthItem(
                    provider_id=provider_id,
                    health_status=status,
                    instance_count=len(insts),
                    healthy_instance_count=healthy,
                    reasoning=(
                        f"{healthy}/{len(insts)} instances report healthy. "
                        "Review before adopting into local routing profile."
                    ),
                )
            )
        return health_items

    def _build_fallback_options(
        self,
        models: list[Any],
        instances: list[Any],
    ) -> list[FallbackOption]:
        fallbacks: list[FallbackOption] = []
        fallback_models = [m for m in models if getattr(m, "fallback_candidate", False)]
        for m in fallback_models:
            related = [
                i.model_id
                for i in instances
                if i.model_id != m.model_id and i.provider_id == m.provider_id
            ]
            fallbacks.append(
                FallbackOption(
                    primary_model_id=m.model_id,
                    fallback_model_ids=related[:2],
                    reasoning=(
                        "Fallback candidates help maintain availability "
                        "during provider degradation."
                    ),
                )
            )
        return fallbacks

    def _build_budget_alerts(
        self,
        models: list[Any],
        routing_input: ManagedRoutingInput,
    ) -> list[BudgetAlert]:
        budgets = routing_input.site_context.get("budgets", {})
        alerts: list[BudgetAlert] = []

        # Simple heuristic: if any premium model exists and no budget cap is set, show notice
        has_premium = any((m.price_input or 0) >= 2.0 for m in models)
        monthly_cap = budgets.get("monthly_usd")
        if has_premium and monthly_cap is None:
            alerts.append(
                BudgetAlert(
                    alert_level="notice",
                    message=(
                        "Premium models are available in catalog; "
                        "consider setting a monthly budget cap locally."
                    ),
                    reasoning="Budget awareness prevents unexpected cost escalation.",
                )
            )
        elif isinstance(monthly_cap, (int, float)) and monthly_cap < 50:
            alerts.append(
                BudgetAlert(
                    alert_level="warning",
                    message="Monthly budget cap is low relative to premium model pricing.",
                    reasoning=(
                        "Low cap may cause frequent throttling "
                        "if quality routes are adopted."
                    ),
                )
            )

        if not alerts:
            alerts.append(
                BudgetAlert(
                    alert_level="none",
                    message="No immediate budget concerns based on current catalog.",
                    reasoning="Continue monitoring usage via local telemetry.",
                )
            )

        return alerts

    def _build_quality_regressions(self, instances: list[Any]) -> list[QualityRegressionItem]:
        regressions: list[QualityRegressionItem] = []
        for inst in instances:
            if inst.health_status == "degraded":
                regressions.append(
                    QualityRegressionItem(
                        model_id=inst.model_id,
                        regression_type="availability",
                        severity="medium",
                        reasoning=(
                            f"Instance {inst.instance_id} is degraded. "
                            "Review before routing traffic."
                        ),
                    )
                )
            elif inst.health_status == "unhealthy":
                regressions.append(
                    QualityRegressionItem(
                        model_id=inst.model_id,
                        regression_type="availability",
                        severity="high",
                        reasoning=(
                            f"Instance {inst.instance_id} is unhealthy. "
                            "Exclude from local routing until recovered."
                        ),
                    )
                )
        return regressions
