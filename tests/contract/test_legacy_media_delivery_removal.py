from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "app"
MEDIA_ROUTES = APP / "api/routes/media_derivatives.py"


def test_b4b2_removes_legacy_audio_asset_and_download_surfaces() -> None:
    assert not (APP / "api/routes/audio_assets.py").exists()
    assert not (APP / "domain/audio_generation/assets.py").exists()

    app_source = "\n".join(
        path.read_text(encoding="utf-8") for path in APP.rglob("*.py")
    )
    assert "AudioAsset" not in app_source
    assert "/audio-assets" not in app_source
    assert "public-download" not in app_source
    assert "playback_token" not in app_source
    assert "audio_asset_playback_" not in app_source
    assert "record_media_derivative_artifact_download" not in app_source
    assert "iter_open_artifact_chunks" not in app_source

    route_source = MEDIA_ROUTES.read_text(encoding="utf-8")
    assert '@router.get("/artifacts/{artifact_id}/download")' not in route_source
    assert '@router.get("/artifacts/{artifact_id}/public-download")' not in route_source
    assert '@router.get("/media/artifacts/{artifact_id}/download")' in route_source
    assert '@router.post("/media/artifacts/{artifact_id}/delivery-ack")' in route_source


def test_b4b2_keeps_audio_generation_and_runtime_evidence() -> None:
    audio_contract_source = (APP / "domain/audio_generation/contracts.py").read_text(
        encoding="utf-8"
    )
    models_source = (APP / "core/models.py").read_text(encoding="utf-8")

    assert "audio_generation_request.v1" in audio_contract_source
    assert "MediaArtifactDelivery" in models_source
    assert "UsageMeterEvent" in models_source
