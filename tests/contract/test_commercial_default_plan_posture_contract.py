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
