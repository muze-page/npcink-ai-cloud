from __future__ import annotations

from pathlib import Path

from app.core.db import dispose_engine, init_schema
from app.domain.catalog.service import CatalogService
from app.domain.task_packs.models import (
    GeoPageInput,
    GeoVisibilityReport,
    ManagedRoutingInput,
    ManagedRoutingReport,
    WooCommerceGrowthAnalysisResult,
    WooCommerceProductInput,
)
from app.domain.task_packs.service import (
    GeoVisibilityPackService,
    ManagedModelRoutingPackService,
    WooCommerceGrowthPackService,
)


def test_analyze_product_returns_title_suggestions() -> None:
    service = WooCommerceGrowthPackService()
    product_input = WooCommerceProductInput(
        product_id="prod_001",
        title="Wireless Mouse",
        short_description="A great wireless mouse.",
        long_description="This wireless mouse offers precision and comfort.",
        attributes={"color": "black"},
        categories=["Electronics"],
        tags=["wireless", "mouse"],
        target_locales=["zh-CN", "ja-JP"],
    )

    result = service.analyze_product(product_input)

    assert result.product_id == "prod_001"
    assert result.title_suggestion is not None
    assert result.title_suggestion.original == "Wireless Mouse"
    assert len(result.title_suggestion.suggestions) > 0
    assert "requires_local_approval" in result.model_dump()
    assert result.requires_local_approval is True


def test_analyze_product_returns_description_drafts() -> None:
    service = WooCommerceGrowthPackService()
    product_input = WooCommerceProductInput(
        product_id="prod_002",
        title="Mechanical Keyboard",
        short_description="Tactile mechanical keyboard.",
        long_description="Full-size mechanical keyboard with RGB backlight.",
    )

    result = service.analyze_product(product_input)

    assert len(result.description_drafts) == 2
    draft_types = {d.draft_type for d in result.description_drafts}
    assert "short" in draft_types
    assert "long" in draft_types
    for draft in result.description_drafts:
        assert draft.draft
        assert "draft" in draft.reasoning.lower() or "approval" in draft.reasoning.lower()


def test_analyze_product_returns_attribute_suggestions() -> None:
    service = WooCommerceGrowthPackService()
    product_input = WooCommerceProductInput(
        product_id="prod_003",
        title="Leather Wallet",
        attributes={"color": "brown"},
    )

    result = service.analyze_product(product_input)

    assert result.attribute_suggestion is not None
    assert "brand" in result.attribute_suggestion.suggested_additions
    assert result.attribute_suggestion.existing == {"color": "brown"}
    assert "local approval" in result.attribute_suggestion.reasoning.lower()


def test_analyze_product_returns_localization_suggestions() -> None:
    service = WooCommerceGrowthPackService()
    product_input = WooCommerceProductInput(
        product_id="prod_004",
        title="Running Shoes",
        target_locales=["de-DE", "fr-FR"],
    )

    result = service.analyze_product(product_input)

    assert len(result.localization_suggestions) == 2
    locales = {s.locale for s in result.localization_suggestions}
    assert "de-DE" in locales
    assert "fr-FR" in locales
    for loc in result.localization_suggestions:
        assert loc.localized_title
        assert "review" in loc.reasoning.lower() or "approval" in loc.reasoning.lower()


def test_analyze_product_returns_schema_suggestion() -> None:
    service = WooCommerceGrowthPackService()
    product_input = WooCommerceProductInput(
        product_id="prod_005",
        title="Coffee Mug",
        short_description="Ceramic coffee mug.",
        categories=["Kitchen"],
    )

    result = service.analyze_product(product_input)

    assert result.schema_suggestion is not None
    assert result.schema_suggestion.schema_type == "Product"
    assert "@context" in result.schema_suggestion.recommended_fields
    assert "local approval" in result.schema_suggestion.reasoning.lower()


def test_analyze_product_never_claims_write_to_woocommerce() -> None:
    service = WooCommerceGrowthPackService()
    product_input = WooCommerceProductInput(
        product_id="prod_006",
        title="Bluetooth Speaker",
    )

    result = service.analyze_product(product_input)
    result_dict = result.model_dump()
    result_str = str(result_dict)

    assert "已写入 WooCommerce" not in result_str
    assert "written to WooCommerce" not in result_str.lower()
    assert result.requires_local_approval is True


def test_generate_batch_plan_returns_summary() -> None:
    service = WooCommerceGrowthPackService()
    items = [
        WooCommerceProductInput(product_id="prod_001", title="Item A"),
        WooCommerceProductInput(product_id="prod_002", title="Item B"),
    ]

    summary = service.generate_batch_plan(items)

    assert summary.total_products == 2
    assert len(summary.items) == 2
    assert "title_optimization" in summary.task_types
    assert "seo_schema_enhancement" in summary.task_types
    assert summary.requires_local_approval is True


def test_generate_batch_plan_respects_empty_list() -> None:
    service = WooCommerceGrowthPackService()
    summary = service.generate_batch_plan([])

    assert summary.total_products == 0
    assert summary.items == []
    assert summary.requires_local_approval is True


def test_batch_plan_never_claims_write_to_woocommerce() -> None:
    service = WooCommerceGrowthPackService()
    items = [WooCommerceProductInput(product_id="prod_007", title="Gadget")]

    summary = service.generate_batch_plan(items)
    summary_dict = summary.model_dump()
    summary_str = str(summary_dict)

    assert "已写入 WooCommerce" not in summary_str
    assert "written to WooCommerce" not in summary_str.lower()
    assert summary.requires_local_approval is True


def test_analyze_product_with_minimal_input_returns_result() -> None:
    service = WooCommerceGrowthPackService()
    product_input = WooCommerceProductInput()

    result = service.analyze_product(product_input)

    assert isinstance(result, WooCommerceGrowthAnalysisResult)
    assert result.title_suggestion is None
    assert result.description_drafts == []
    # Even with no attributes, common missing attributes are suggested.
    assert result.attribute_suggestion is not None
    assert result.localization_suggestions == []
    assert result.schema_suggestion is not None
    assert result.requires_local_approval is True


# =============================================================================
# GEO Visibility Pack domain tests
# =============================================================================


def test_geo_visibility_analyze_returns_report() -> None:
    service = GeoVisibilityPackService()
    page_input = GeoPageInput(
        page_id="page_001",
        url="https://example.com/product",
        title="Example Product",
        content_text="This is a great product. It has many features.",
        schema_markup={"@type": "Product", "name": "Example Product"},
        locale="zh-CN",
    )

    result = service.analyze_page(page_input)

    assert isinstance(result, GeoVisibilityReport)
    assert result.page_id == "page_001"
    assert result.url == "https://example.com/product"
    assert result.locale == "zh-CN"
    assert result.requires_local_approval is True
    assert result.llms_txt_suggestion is not None
    assert len(result.schema_checks) > 0
    assert len(result.ai_citation_checks) > 0


def test_geo_visibility_llms_txt_detects_missing() -> None:
    service = GeoVisibilityPackService()
    page_input = GeoPageInput(url="https://example.com", title="Test")

    result = service.analyze_page(page_input)

    assert result.llms_txt_suggestion is not None
    assert result.llms_txt_suggestion.present is False
    assert "llms.txt" in result.llms_txt_suggestion.reasoning.lower()


def test_geo_visibility_llms_txt_detects_present() -> None:
    service = GeoVisibilityPackService()
    page_input = GeoPageInput(
        url="https://example.com",
        current_llms_txt="# Example Site\n",
    )

    result = service.analyze_page(page_input)

    assert result.llms_txt_suggestion is not None
    assert result.llms_txt_suggestion.present is True


def test_geo_visibility_schema_checks_detect_missing_json_ld() -> None:
    service = GeoVisibilityPackService()
    page_input = GeoPageInput(schema_markup=None)

    result = service.analyze_page(page_input)

    schema_check_names = {c.check_name for c in result.schema_checks}
    assert "json_ld_present" in schema_check_names
    json_ld_check = next(c for c in result.schema_checks if c.check_name == "json_ld_present")
    assert json_ld_check.passed is False


def test_geo_visibility_never_promises_ranking_or_compliance() -> None:
    service = GeoVisibilityPackService()
    page_input = GeoPageInput(
        title="Test",
        content_text="Some content here.",
    )

    result = service.analyze_page(page_input)
    result_str = str(result.model_dump())

    forbidden_phrases = [
        "自动排名",
        "automatic ranking",
        "自动合规",
        "automatic compliance",
        "自动获得 ai 引用",
        "automatic ai citation",
        "guaranteed",
        "承诺",
    ]
    for phrase in forbidden_phrases:
        assert phrase.lower() not in result_str.lower(), f"found forbidden phrase: {phrase}"
    assert result.requires_local_approval is True


def test_geo_visibility_batch_returns_results() -> None:
    service = GeoVisibilityPackService()
    inputs = [
        GeoPageInput(page_id="p1", url="https://a.com"),
        GeoPageInput(page_id="p2", url="https://b.com"),
    ]

    result = service.analyze_batch(inputs)

    assert result.total_pages == 2
    assert len(result.reports) == 2
    assert result.requires_local_approval is True


# =============================================================================
# Managed Model Routing Pack domain tests
# =============================================================================


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'routing-pack-domain.sqlite3'}"


def test_managed_routing_report_returns_structure(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    service = ManagedModelRoutingPackService(database_url)
    result = service.generate_report(ManagedRoutingInput())

    assert isinstance(result, ManagedRoutingReport)
    assert result.requires_local_approval is True
    assert result.cloud_only_recommendation is True
    assert len(result.provider_health) > 0
    assert len(result.fallback_options) >= 0
    assert len(result.budget_alerts) > 0

    dispose_engine(database_url)


def test_managed_routing_report_includes_recommendations(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    service = ManagedModelRoutingPackService(database_url)
    result = service.generate_report(ManagedRoutingInput())

    route_ids = {r.route_id for r in result.recommendations}
    assert "deepseek-economy" in route_ids or "openai-claude-quality" in route_ids

    for rec in result.recommendations:
        assert rec.route_label
        assert rec.reasoning
        assert rec.estimated_cost_tier in ("budget", "balanced", "premium", "")

    dispose_engine(database_url)


def test_managed_routing_report_never_claims_router_control(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    service = ManagedModelRoutingPackService(database_url)
    result = service.generate_report(ManagedRoutingInput())
    result_str = str(result.model_dump())

    forbidden_phrases = [
        "本地 router 真源",
        "local router truth overridden",
        "cloud controls routing",
        "cloud owns router",
        "cloud 控制",
        "cloud 拥有",
    ]
    for phrase in forbidden_phrases:
        assert phrase.lower() not in result_str.lower(), f"found forbidden phrase: {phrase}"
    assert result.cloud_only_recommendation is True
    assert result.requires_local_approval is True

    dispose_engine(database_url)


def test_managed_routing_report_budget_alert_with_low_cap(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    service = ManagedModelRoutingPackService(database_url)
    result = service.generate_report(
        ManagedRoutingInput(site_context={"budgets": {"monthly_usd": 30}})
    )

    alert_levels = {a.alert_level for a in result.budget_alerts}
    assert "warning" in alert_levels or "notice" in alert_levels or "none" in alert_levels

    dispose_engine(database_url)
