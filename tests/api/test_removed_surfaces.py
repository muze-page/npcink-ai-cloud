from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.services import CloudServices


def _client(tmp_path) -> TestClient:
    settings = Settings(
        project_name="Npcink AI Cloud Test",
        environment="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'removed-surfaces.sqlite3'}",
        redis_url="redis://localhost:6379/0",
    )
    return TestClient(create_app(CloudServices(settings=settings)))


def test_removed_public_control_plane_surfaces_are_absent_from_openapi(tmp_path) -> None:
    client = _client(tmp_path)
    openapi_paths = client.get("/openapi.json").json()["paths"]
    paths = set(openapi_paths)

    removed_prefixes = (
        "/v1/orchestration",
        "/v1/task-packs",
        "/v1/addon",
        "/v1/prompt/advisor/recommendation",
        "/v1/prompt/eval/recommendation",
        "/v1/prompt/canary/recommendation",
        "/v1/prompt/upgrade/recommendation",
        "/v1/preset/advisor/recommendation",
        "/portal/v1/notifications",
        "/portal/v1/topup-packs",
        "/portal/v1/auth/qq/callback",
        "/internal/service/sites/{site_id}/user-grants",
        "/internal/service/admin/topup-packs",
        "/internal/service/admin/portal-action-requests",
        "/internal/service/admin/impersonations",
        "/internal/service/admin/commercial-shadow-pricing/summary",
        "/v1/catalog/recognition",
        "/v1/catalog/recognition-intelligence",
        "/internal/catalog/recognition/evidence",
        "/internal/catalog/intelligence/publisher",
        "/internal/service/admin/providers",
        "/internal/service/admin/models",
        "/internal/service/admin/recognition",
        "/internal/service/admin/wordpress-ai-routing",
        "/v1/runtime/audio-assets",
        "/v1/runtime/artifacts",
    )

    for path in paths:
        assert not path.startswith(removed_prefixes), path

    assert {
        "/portal/v1/sites",
        "/portal/v1/sites/{site_id}/activate",
        "/portal/v1/sites/{site_id}/deactivate",
        "/portal/v1/sites/{site_id}/api-keys",
        "/portal/v1/sites/{site_id}/api-keys/{key_id}/rotate",
        "/portal/v1/sites/{site_id}/api-keys/{key_id}/revoke",
    }.isdisjoint(paths)


def test_removed_urls_return_404(tmp_path) -> None:
    client = _client(tmp_path)

    removed_urls = (
        "/v1/orchestration/runs",
        "/v1/task-packs/woocommerce-growth/analyze",
        "/v1/addon/dashboard",
        "/v1/prompt/advisor/recommendation",
        "/v1/prompt/eval/recommendation",
        "/v1/prompt/canary/recommendation",
        "/v1/prompt/upgrade/recommendation",
        "/v1/preset/advisor/recommendation",
        "/portal/v1/notifications",
        "/portal/v1/auth/qq/callback",
        "/portal/v1/sites/site_alpha/analytics/overview",
        "/portal/v1/sites/site_alpha/compliance/posture",
        "/portal/v1/sites/site_alpha/package-change-requests",
        "/portal/v1/sites/site_alpha/topup-pack-requests",
        "/portal/v1/sites/site_alpha/delete-requests",
        "/portal/v1/sites/site_alpha/usage-alert-settings",
        "/portal/v1/sites/site_alpha/api-keys",
        "/internal/service/admin/topup-packs",
        "/internal/service/admin/portal-action-requests",
        "/internal/service/admin/impersonations",
        "/internal/service/admin/commercial-shadow-pricing/summary",
        "/v1/catalog/recognition/revision",
        "/v1/catalog/recognition-intelligence/revision",
        "/v1/catalog/recognition/bundle",
        "/v1/catalog/recognition-intelligence/bundle",
        "/internal/catalog/recognition/evidence",
        "/internal/catalog/recognition/evidence/refresh",
        "/internal/catalog/intelligence/publisher",
        "/internal/catalog/intelligence/publisher/refresh",
        "/internal/service/admin/providers",
        "/internal/service/admin/models",
        "/internal/service/admin/recognition",
        "/internal/service/admin/wordpress-ai-routing",
        "/internal/service/sites/site_alpha/user-grants",
        "/v1/runtime/artifacts/art_00000000000000000000000000000000/download",
        (
            "/v1/runtime/artifacts/art_00000000000000000000000000000000/"
            "public-download?token=removed"
        ),
        "/v1/runtime/audio-assets/aud_removed/playback-url?ttl_seconds=180",
        "/v1/runtime/audio-assets/aud_removed/playback?expires=1&token=removed",
    )

    for url in removed_urls:
        assert client.get(url).status_code == 404, url

    assert (
        client.post(
            "/v1/runtime/audio-assets",
            json={"artifact_id": "art_removed"},
        ).status_code
        == 404
    )
    assert client.post("/portal/v1/sites", json={}).status_code == 404
    for url in (
        "/portal/v1/sites/site_alpha/activate",
        "/portal/v1/sites/site_alpha/deactivate",
        "/portal/v1/sites/site_alpha/api-keys",
        "/portal/v1/sites/site_alpha/api-keys/key_alpha/rotate",
        "/portal/v1/sites/site_alpha/api-keys/key_alpha/revoke",
    ):
        assert client.post(url, json={}).status_code == 404, url


def test_minimal_surfaces_remain_in_openapi(tmp_path) -> None:
    client = _client(tmp_path)
    paths = set(client.get("/openapi.json").json()["paths"])

    expected = {
        "/health/live",
        "/v1/catalog/models",
        "/v1/runtime/resolve",
        "/v1/runtime/execute",
        "/v1/runtime/media/artifacts/{artifact_id}/download",
        "/v1/runtime/media/artifacts/{artifact_id}/delivery-ack",
        "/v1/runs/{run_id}",
        "/v1/router/recommendation",
        "/portal/v1/session",
        "/portal/v1/sites/{site_id}/summary",
        "/portal/v1/sites/{site_id}/usage-summary",
        "/portal/v1/sites/{site_id}/entitlements",
        "/portal/v1/sites/{site_id}/billing-snapshots",
        "/portal/v1/sites/{site_id}/audit-events",
        "/internal/service/admin/overview",
        "/internal/service/admin/accounts",
        "/internal/service/admin/sites",
        "/internal/service/admin/plans",
        "/internal/service/runtime/diagnostics/summary",
    }

    missing = expected.difference(paths)
    assert missing == set()
