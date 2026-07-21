from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.db import get_session, init_schema
from app.core.models import MediaArtifact
from app.domain.media_artifacts.input_loading import (
    VISION_IMAGE_MAX_BYTES,
    ArtifactInputError,
    admit_artifact_input,
    load_artifact_input,
)
from app.domain.media_artifacts.store import LocalVolumeArtifactStore


def _database_url(tmp_path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'artifact-input.sqlite3'}"
    init_schema(database_url)
    return database_url


def _seed_artifact(
    tmp_path: Path,
    database_url: str,
    *,
    artifact_id: str = "art_0123456789abcdef0123456789abcdef",
    site_id: str = "site_alpha",
    payload: bytes = b"verified-image-bytes",
    **overrides: Any,
) -> LocalVolumeArtifactStore:
    store = LocalVolumeArtifactStore(tmp_path / "artifacts")
    stored = store.put(io.BytesIO(payload), max_bytes=len(payload))
    values: dict[str, Any] = {
        "artifact_id": artifact_id,
        "run_id": f"run_{artifact_id}",
        "site_id": site_id,
        "media_kind": "image",
        "operation": "image.upload.v1",
        "content_type": "image/png",
        "byte_size": stored.byte_size,
        "storage_key": stored.storage_key,
        "status": "available",
        "format": "png",
        "width": 64,
        "height": 48,
        "checksum": stored.checksum,
        "expires_at": datetime.now(UTC) + timedelta(minutes=30),
    }
    values.update(overrides)
    with get_session(database_url) as session:
        session.add(MediaArtifact(**values))
        session.commit()
    return store


def test_load_artifact_input_returns_repr_safe_verified_bytes(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    store = _seed_artifact(tmp_path, database_url)

    with get_session(database_url) as session:
        loaded = load_artifact_input(
            session,
            store,
            site_id="site_alpha",
            artifact_id="art_0123456789abcdef0123456789abcdef",
        )

    assert loaded.content_type == "image/png"
    assert loaded.content_bytes == b"verified-image-bytes"
    assert "verified-image-bytes" not in repr(loaded)


def test_cross_site_artifact_is_indistinguishable_from_not_found(tmp_path: Path) -> None:
    database_url = _database_url(tmp_path)
    _seed_artifact(tmp_path, database_url, site_id="site_beta")

    with get_session(database_url) as session, pytest.raises(ArtifactInputError) as error:
        admit_artifact_input(
            session,
            site_id="site_alpha",
            artifact_id="art_0123456789abcdef0123456789abcdef",
        )

    assert error.value.error_code == (
        "wordpress_operation.alt_text_source_artifact_not_found"
    )


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        (
            {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
            "wordpress_operation.alt_text_source_artifact_expired",
        ),
        (
            {"media_kind": "audio"},
            "wordpress_operation.alt_text_artifact_type_not_allowed",
        ),
        (
            {"content_type": "image/gif", "format": "gif"},
            "wordpress_operation.alt_text_artifact_type_not_allowed",
        ),
        (
            {"format": "webp"},
            "wordpress_operation.alt_text_artifact_type_not_allowed",
        ),
        (
            {"byte_size": VISION_IMAGE_MAX_BYTES + 1},
            "wordpress_operation.alt_text_source_artifact_too_large",
        ),
        (
            {"status": "failed"},
            "wordpress_operation.alt_text_source_artifact_unavailable",
        ),
    ],
)
def test_artifact_metadata_admission_fails_closed(
    tmp_path: Path,
    overrides: dict[str, Any],
    expected_error: str,
) -> None:
    database_url = _database_url(tmp_path)
    _seed_artifact(tmp_path, database_url, **overrides)

    with get_session(database_url) as session, pytest.raises(ArtifactInputError) as error:
        admit_artifact_input(
            session,
            site_id="site_alpha",
            artifact_id="art_0123456789abcdef0123456789abcdef",
        )

    assert error.value.error_code == expected_error


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_artifact_storage_failure_is_stably_unavailable(
    tmp_path: Path,
    failure: str,
) -> None:
    database_url = _database_url(tmp_path)
    overrides: dict[str, Any] = {}
    if failure == "missing":
        overrides["storage_key"] = "obj_00000000000000000000000000000000"
    else:
        overrides["checksum"] = "sha256:" + ("0" * 64)
    store = _seed_artifact(tmp_path, database_url, **overrides)

    with get_session(database_url) as session, pytest.raises(ArtifactInputError) as error:
        load_artifact_input(
            session,
            store,
            site_id="site_alpha",
            artifact_id="art_0123456789abcdef0123456789abcdef",
        )

    assert error.value.error_code == (
        "wordpress_operation.alt_text_source_artifact_unavailable"
    )
