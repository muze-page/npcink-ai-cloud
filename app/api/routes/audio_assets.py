from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.api.auth import authorize_public_request, get_cloud_services
from app.api.envelope import build_envelope
from app.core.db import get_session
from app.domain.audio_generation.assets import (
    AudioAssetError,
    build_audio_asset_playback_url,
    build_audio_asset_projection,
    promote_audio_asset_from_artifact,
    require_active_audio_asset,
    validate_audio_asset_playback_token,
)

router = APIRouter(prefix="/v1/runtime/audio-assets", tags=["audio-assets"])


class PromoteAudioAssetRequest(BaseModel):
    artifact_id: str = Field(min_length=1, max_length=191)
    source_content_hash: str = Field(default="", max_length=128)
    metadata: dict[str, Any] = Field(default_factory=dict)
    playback_ttl_seconds: int | None = Field(default=None, ge=60, le=24 * 60 * 60)


def _audio_asset_error_response(error: AudioAssetError, *, trace_id: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content=build_envelope(
            status="error",
            error_code=error.error_code,
            message=error.message,
            data={},
            trace_id=trace_id,
            revision="aa1",
        ),
    )


def _stream_audio_asset(asset: Any, *, cache_control: str) -> StreamingResponse:
    extension = str(asset.format or "mp3").lower()
    if extension == "mpeg":
        extension = "mp3"
    return StreamingResponse(
        iter([asset.blob_data or b""]),
        media_type=asset.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{asset.asset_id}.{extension}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": cache_control,
        },
    )


@router.post("")
async def promote_audio_asset(request: Request) -> Any:
    services = get_cloud_services(request)
    auth = await authorize_public_request(
        request,
        require_idempotency=True,
        required_scope="runtime:execute",
    )
    if isinstance(auth, JSONResponse):
        return auth

    body = await request.json()
    try:
        payload = PromoteAudioAssetRequest.model_validate(body)
    except ValueError as error:
        return JSONResponse(
            status_code=422,
            content=build_envelope(
                status="error",
                error_code="audio_asset.validation_error",
                message=str(error),
                data={},
                trace_id=auth.trace_id,
                revision="aa1",
            ),
        )

    try:
        with get_session(services.settings.database_url) as session:
            asset = promote_audio_asset_from_artifact(
                session=session,
                site_id=auth.site_id,
                artifact_id=payload.artifact_id,
                source_content_hash=payload.source_content_hash,
                metadata=payload.metadata,
            )
            playback_url = build_audio_asset_playback_url(
                asset,
                settings=services.settings,
                ttl_seconds=payload.playback_ttl_seconds,
            )
            data = build_audio_asset_projection(asset, playback_url=playback_url)
            session.commit()
    except AudioAssetError as error:
        return _audio_asset_error_response(error, trace_id=auth.trace_id)

    return build_envelope(
        status="ok",
        message="audio asset promoted",
        data=data,
        trace_id=auth.trace_id,
        revision="aa1",
    )


@router.get("/{asset_id}/playback-url")
async def get_audio_asset_playback_url(
    request: Request,
    asset_id: str,
    ttl_seconds: int | None = Query(default=None, ge=60, le=24 * 60 * 60),
) -> Any:
    services = get_cloud_services(request)
    auth = await authorize_public_request(
        request,
        require_idempotency=False,
        required_scope="runtime:read",
    )
    if isinstance(auth, JSONResponse):
        return auth

    try:
        with get_session(services.settings.database_url) as session:
            asset = require_active_audio_asset(session, asset_id, site_id=auth.site_id)
            playback_url = build_audio_asset_playback_url(
                asset,
                settings=services.settings,
                ttl_seconds=ttl_seconds,
            )
            data = build_audio_asset_projection(asset, playback_url=playback_url)
            session.commit()
    except AudioAssetError as error:
        return _audio_asset_error_response(error, trace_id=auth.trace_id)

    return build_envelope(
        status="ok",
        message="audio asset playback URL created",
        data=data,
        trace_id=auth.trace_id,
        revision="aa1",
    )


@router.get("/{asset_id}/playback")
async def play_audio_asset(
    request: Request,
    asset_id: str,
    expires: int = Query(default=0),
    token: str = Query(default=""),
) -> Any:
    services = get_cloud_services(request)
    try:
        with get_session(services.settings.database_url) as session:
            asset = require_active_audio_asset(session, asset_id)
            validate_audio_asset_playback_token(
                asset,
                settings=services.settings,
                expires=expires,
                token=token,
            )
            expires_at = datetime.fromtimestamp(expires, tz=UTC)
            remaining_seconds = max(0, int((expires_at - datetime.now(UTC)).total_seconds()))
            session.commit()
    except AudioAssetError as error:
        return _audio_asset_error_response(error)

    return _stream_audio_asset(
        asset,
        cache_control=f"private, max-age={remaining_seconds}",
    )
