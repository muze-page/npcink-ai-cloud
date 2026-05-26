from pathlib import Path


def test_dev_unlimited_plan_is_limited_to_seed_runtime_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    service_code = (root / "app/domain/commercial/service.py").read_text()
    seed_runtime_code = (root / "app/dev/seed_runtime.py").read_text()
    commercial_core_doc = (
        root.parent / "magick-ai/docs/contracts/cloud-commercial-core-v1.md"
    ).read_text()
    free_plan_doc = (
        root.parent / "magick-ai/docs/contracts/cloud-free-plan-v1.md"
    ).read_text()

    assert "plan_dev_unlimited" in service_code
    assert '"source": "seed_runtime"' in service_code
    assert "plan_dev_unlimited" in seed_runtime_code
    assert 'DEFAULT_FREE_PLAN_ID = "plan_free"' in service_code
    assert 'DEFAULT_FREE_PLAN_VERSION_ID = "plan_free_v1"' in service_code
    assert "bind_default_free: bool = False" in service_code
    assert "production/commercial truth 已冻结显式 production free package" in commercial_core_doc
    assert "plan_dev_unlimited / plan_dev_unlimited_v1" in commercial_core_doc
    assert "只属于：" in commercial_core_doc
    assert "plan_id = plan_free" in free_plan_doc
    assert "不是 runtime request-time fallback" in free_plan_doc or "不是 runtime request-time fallback" in commercial_core_doc
