from pathlib import Path


def test_default_free_plan_is_the_current_bootstrap_posture() -> None:
    root = Path(__file__).resolve().parents[2]
    service_code = (root / "app/domain/commercial/service.py").read_text()
    account_code = (
        root / "app/domain/commercial/mixins/_account_mixin.py"
    ).read_text()
    billing_code = (
        root / "app/domain/commercial/mixins/_billing_mixin.py"
    ).read_text()
    seed_runtime_code = (root / "app/dev/seed_runtime.py").read_text()

    assert "plan_dev_unlimited" not in service_code
    assert "plan_dev_unlimited" not in seed_runtime_code
    assert '"dev_baseline"' not in billing_code
    assert 'DEFAULT_FREE_PLAN_ID = "free"' in service_code
    assert 'DEFAULT_FREE_PLAN_VERSION_ID = "free_v1"' in service_code
    assert 'plan_id: str = "free"' in seed_runtime_code
    assert 'plan_version_id: str = "free_v1"' in seed_runtime_code
    assert "bind_default_free: bool = False" in account_code


def test_plus_plan_tier_is_registered_in_service_and_billing_templates() -> None:
    from app.domain.commercial import service
    from app.domain.commercial.mixins import _billing_mixin

    service_plus = service.PLAN_TIER_REGISTRY["plus"]
    billing_plus = _billing_mixin.PLAN_TIER_REGISTRY["plus"]

    assert service_plus["package_alias"] == "Plus"
    assert billing_plus["package_alias"] == "Plus"
    assert list(service.PLAN_TIER_REGISTRY)[:3] == ["free", "plus", "pro"]
    assert list(_billing_mixin.PLAN_TIER_REGISTRY)[:3] == ["free", "plus", "pro"]
    assert service_plus["monthly_included_points"] == 3_000
    assert billing_plus["budgets_template"]["max_ai_credits_per_period"] == 3_000
    assert billing_plus["site_limit"] == 3
    assert billing_plus["concurrency_template"] == {"max_active_runs": 2}
