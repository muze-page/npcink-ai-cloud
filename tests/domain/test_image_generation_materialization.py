from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin, features
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.providers.base import ProviderMediaCandidate
from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import MediaArtifact, RunRecord, Site
from app.domain.image_generation.materialization import (
    ImageGenerationArtifactCleanupUncertainError,
    ImageGenerationArtifactMaterializationError,
    ImageGenerationMaterializationConfig,
    materialize_image_generation_candidates,
)
from app.domain.image_generation.provider_fetch import ProviderFetchedImage
from app.domain.media_artifacts import (
    ArtifactStorageMetadata,
    ArtifactStoreError,
    LocalVolumeArtifactStore,
)
from app.domain.media_artifacts.publication import (
    tracked_artifact_storage_keys,
    uncertain_artifact_storage_keys,
)


@pytest.fixture
def artifact_context(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'image-artifacts.sqlite3'}"
    artifact_root = tmp_path / "artifacts"
    init_schema(database_url)
    with get_session(database_url) as session:
        session.add(Site(site_id="site_image", name="Image", status="active"))
        session.commit()
    yield database_url, artifact_root
    dispose_engine(database_url)


def _create_run(session: Session, *, run_id: str) -> RunRecord:
    repository = RuntimeRepository(session)
    return repository.create_run(
        run_id=run_id,
        site_id="site_image",
        account_id=None,
        subscription_id=None,
        plan_version_id=None,
        ability_name="image_generate",
        ability_family="image_generation",
        skill_id="",
        workflow_id="",
        contract_version="image_generation_request.v1",
        channel="wordpress_ai_connector",
        execution_kind="image_generation",
        execution_tier="cloud",
        execution_pattern="request_response",
        data_classification="internal",
        profile_id="image.generate.hosted",
        canonical_run_id=None,
        status="running",
        idempotency_key=f"idem-{run_id}",
        request_fingerprint=f"fingerprint-{run_id}",
        trace_id=f"trace-{run_id}",
        input_json={},
        execution_input_ciphertext=None,
        policy_json={"storage_mode": "result_only"},
    )


def _png_bytes(*, size: tuple[int, int] = (8, 6), text: bool = False) -> bytes:
    image = Image.new("RGBA", size, (30, 80, 120, 180))
    output = io.BytesIO()
    pnginfo = None
    if text:
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("private-note", "must-not-survive")
    image.save(
        output,
        format="PNG",
        pnginfo=pnginfo,
        icc_profile=b"private-icc-profile" if text else None,
    )
    image.close()
    return output.getvalue()


def _oriented_jpeg_bytes() -> bytes:
    image = Image.new("RGB", (9, 5), (120, 40, 10))
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private-description"
    output = io.BytesIO()
    image.save(output, format="JPEG", exif=exif)
    image.close()
    return output.getvalue()


def _animated_webp_bytes() -> bytes:
    first = Image.new("RGB", (8, 6), "red")
    second = Image.new("RGB", (8, 6), "blue")
    output = io.BytesIO()
    first.save(
        output,
        format="WEBP",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    first.close()
    second.close()
    return output.getvalue()


def _stored_paths(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("obj_*") if path.is_file())


def _assert_no_private_fields(value: object) -> None:
    forbidden = {
        "b64_json",
        "source_url",
        "storage_key",
        "provider_url",
        "bearer_token",
        "signed_token",
        "wordpress_write_target",
    }
    if isinstance(value, dict):
        assert forbidden.isdisjoint(value)
        for nested in value.values():
            _assert_no_private_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_private_fields(nested)


def test_materializes_clean_platform_neutral_artifacts_and_commits(
    artifact_context: tuple[str, Path],
) -> None:
    database_url, artifact_root = artifact_context
    store = LocalVolumeArtifactStore(artifact_root)
    candidates = (
        ProviderMediaCandidate(
            index=1,
            content_bytes=_png_bytes(text=True),
            claimed_mime_type="image/png",
            claimed_width=8,
            claimed_height=6,
        ),
        ProviderMediaCandidate(
            index=2,
            content_bytes=_oriented_jpeg_bytes(),
            claimed_mime_type="image/jpeg",
        ),
    )

    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_success")
        result = materialize_image_generation_candidates(
            session=session,
            artifact_store=store,
            run=run,
            media_candidates=candidates,
            provider_output={"model_id": "image-model", "candidate_count": 2},
        )
        artifact_rows = list(
            session.scalars(
                select(MediaArtifact)
                .where(MediaArtifact.run_id == run.run_id)
            )
        )
        assert result["contract_version"] == "image_generation_result.v1"
        assert result["artifact_type"] == "image_generation_artifacts"
        assert result["operation"] == "image.generate.v1"
        assert result["suggestion_only"] is True
        assert result["requires_local_review"] is True
        assert len(result["artifacts"]) == len(artifact_rows) == 2
        _assert_no_private_fields(result)
        artifact_by_id = {artifact.artifact_id: artifact for artifact in artifact_rows}
        for artifact_result in result["artifacts"]:
            artifact = artifact_by_id[artifact_result["artifact_id"]]
            assert artifact.run_id == run.run_id
            assert artifact.site_id == run.site_id
            assert artifact.operation == "image.generate.v1"
            expires_at = artifact_result.pop("expires_at")
            assert str(expires_at).endswith("+00:00")
            assert artifact_result == {
                "artifact_id": artifact.artifact_id,
                "artifact_reference": {"artifact_id": artifact.artifact_id},
                "status": "available",
                "media_kind": "image",
                "operation": "image.generate.v1",
                "content_type": artifact.content_type,
                "format": artifact.format,
                "width": artifact.width,
                "height": artifact.height,
                "filesize_bytes": artifact.byte_size,
                "checksum": artifact.checksum,
            }

        png_artifact = next(artifact for artifact in artifact_rows if artifact.format == "png")
        assert (png_artifact.width, png_artifact.height) == (8, 6)
        with store.open(png_artifact.storage_key) as stream, Image.open(stream) as image:
            image.load()
            assert "private-note" not in image.info
            assert "exif" not in image.info
            assert "icc_profile" not in image.info

        jpeg_artifact = next(artifact for artifact in artifact_rows if artifact.format == "jpeg")
        assert (jpeg_artifact.width, jpeg_artifact.height) == (5, 9)
        with store.open(jpeg_artifact.storage_key) as stream, Image.open(stream) as image:
            image.load()
            assert image.getexif() == {}
            assert "icc_profile" not in image.info
        session.commit()

    assert len(_stored_paths(artifact_root)) == 2


def test_url_candidate_uses_provider_host_claims_and_mime_validation(
    artifact_context: tuple[str, Path],
) -> None:
    database_url, artifact_root = artifact_context
    store = LocalVolumeArtifactStore(artifact_root)
    calls: list[dict[str, object]] = []

    def fake_fetch(source_url: str, **kwargs: object) -> ProviderFetchedImage:
        calls.append({"source_url": source_url, **kwargs})
        payload = _png_bytes()
        return ProviderFetchedImage(io.BytesIO(payload), len(payload), "image/png")

    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_url")
        result = materialize_image_generation_candidates(
            session=session,
            artifact_store=store,
            run=run,
            media_candidates=(
                ProviderMediaCandidate(
                    index=1,
                    source_url="https://images.provider.test/image.png",
                    image_output_hosts=("images.provider.test",),
                    claimed_mime_type="image/png",
                    claimed_width=8,
                    claimed_height=6,
                ),
            ),
            provider_output={"candidate_count": 1},
            url_fetcher=fake_fetch,
        )
        assert len(result["artifacts"]) == 1
        assert calls[0]["source_url"] == "https://images.provider.test/image.png"
        assert calls[0]["allowed_hosts"] == ("images.provider.test",)
        session.commit()


@pytest.mark.parametrize(
    ("provider_output", "candidates"),
    [
        ({"candidate_count": 2}, (ProviderMediaCandidate(index=1, content_bytes=b"x"),)),
        (
            {"candidate_count": 2},
            (
                ProviderMediaCandidate(index=1, content_bytes=b"x"),
                ProviderMediaCandidate(index=3, content_bytes=b"y"),
            ),
        ),
    ],
)
def test_rejects_candidate_count_and_index_mismatch_before_publication(
    artifact_context: tuple[str, Path],
    provider_output: dict[str, object],
    candidates: tuple[ProviderMediaCandidate, ...],
) -> None:
    database_url, artifact_root = artifact_context
    with get_session(database_url) as session:
        run = _create_run(session, run_id=f"run_bad_envelope_{len(candidates)}")
        with pytest.raises(ImageGenerationArtifactMaterializationError):
            materialize_image_generation_candidates(
                session=session,
                artifact_store=LocalVolumeArtifactStore(artifact_root),
                run=run,
                media_candidates=candidates,
                provider_output=provider_output,
            )
    assert _stored_paths(artifact_root) == []


def test_batch_failure_rolls_back_rows_and_deletes_earlier_objects(
    artifact_context: tuple[str, Path],
) -> None:
    database_url, artifact_root = artifact_context
    store = LocalVolumeArtifactStore(artifact_root)
    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_batch_failure")
        with pytest.raises(ImageGenerationArtifactMaterializationError):
            materialize_image_generation_candidates(
                session=session,
                artifact_store=store,
                run=run,
                media_candidates=(
                    ProviderMediaCandidate(
                        index=1,
                        content_bytes=_png_bytes(),
                        claimed_mime_type="image/png",
                    ),
                    ProviderMediaCandidate(
                        index=2,
                        content_bytes=b"<html>not an image</html>",
                        claimed_mime_type="image/png",
                    ),
                ),
                provider_output={"candidate_count": 2},
            )
        assert list(
            session.scalars(select(MediaArtifact).where(MediaArtifact.run_id == run.run_id))
        ) == []
        assert _stored_paths(artifact_root) == []
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == ()
        run.status = "failed"
        session.commit()
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == ()


def test_rejects_mime_mismatch_before_publication(
    artifact_context: tuple[str, Path],
) -> None:
    database_url, artifact_root = artifact_context
    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_mime_mismatch")
        with pytest.raises(ImageGenerationArtifactMaterializationError) as error:
            materialize_image_generation_candidates(
                session=session,
                artifact_store=LocalVolumeArtifactStore(artifact_root),
                run=run,
                media_candidates=(
                    ProviderMediaCandidate(
                        index=1,
                        content_bytes=_png_bytes(),
                        claimed_mime_type="image/jpeg",
                    ),
                ),
                provider_output={"candidate_count": 1},
            )
        assert error.value.message == "generated image MIME type does not match its content"
    assert _stored_paths(artifact_root) == []


def test_rejects_animated_and_oversized_images_before_publication(
    artifact_context: tuple[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, artifact_root = artifact_context
    if features.check("webp"):
        with get_session(database_url) as session:
            run = _create_run(session, run_id="run_image_animated")
            with pytest.raises(ImageGenerationArtifactMaterializationError) as error:
                materialize_image_generation_candidates(
                    session=session,
                    artifact_store=LocalVolumeArtifactStore(artifact_root),
                    run=run,
                    media_candidates=(
                        ProviderMediaCandidate(
                            index=1,
                            content_bytes=_animated_webp_bytes(),
                            claimed_mime_type="image/webp",
                        ),
                    ),
                    provider_output={"candidate_count": 1},
                )
            assert error.value.message == "animated generated images are not supported"

    from app.domain.image_generation import materialization

    monkeypatch.setattr(materialization, "MAX_IMAGE_DIMENSION", 4)
    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_oversized")
        with pytest.raises(ImageGenerationArtifactMaterializationError) as error:
            materialize_image_generation_candidates(
                session=session,
                artifact_store=LocalVolumeArtifactStore(artifact_root),
                run=run,
                media_candidates=(
                    ProviderMediaCandidate(
                        index=1,
                        content_bytes=_png_bytes(),
                        claimed_mime_type="image/png",
                    ),
                ),
                provider_output={"candidate_count": 1},
            )
        assert error.value.message == "generated image exceeds the decode limit"
    assert _stored_paths(artifact_root) == []


def test_outer_transaction_rollback_removes_successfully_published_object(
    artifact_context: tuple[str, Path],
) -> None:
    database_url, artifact_root = artifact_context
    store = LocalVolumeArtifactStore(artifact_root)
    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_outer_rollback")
        result = materialize_image_generation_candidates(
            session=session,
            artifact_store=store,
            run=run,
            media_candidates=(
                ProviderMediaCandidate(
                    index=1,
                    content_bytes=_png_bytes(),
                    claimed_mime_type="image/png",
                ),
            ),
            provider_output={"candidate_count": 1},
        )
        artifact = session.get(MediaArtifact, result["artifacts"][0]["artifact_id"])
        assert artifact is not None
        artifact_id = artifact.artifact_id
        storage_key = artifact.storage_key
        session.rollback()
        assert session.get(MediaArtifact, artifact_id) is None
        with pytest.raises(ArtifactStoreError):
            store.open(storage_key)


def test_run_io_budget_includes_source_and_sanitized_output(
    artifact_context: tuple[str, Path],
) -> None:
    database_url, artifact_root = artifact_context
    payload = _png_bytes()
    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_io_budget")
        with pytest.raises(ImageGenerationArtifactMaterializationError) as error:
            materialize_image_generation_candidates(
                session=session,
                artifact_store=LocalVolumeArtifactStore(artifact_root),
                run=run,
                media_candidates=(
                    ProviderMediaCandidate(
                        index=1,
                        content_bytes=payload,
                        claimed_mime_type="image/png",
                    ),
                ),
                provider_output={"candidate_count": 1},
                config=ImageGenerationMaterializationConfig(
                    max_image_bytes=len(payload) * 2,
                    max_run_bytes=len(payload) + 1,
                ),
            )
        assert error.value.message == "generated artifacts exceed the run byte limit"
    assert _stored_paths(artifact_root) == []


def test_storage_metadata_mismatch_is_cleaned_up(
    artifact_context: tuple[str, Path],
) -> None:
    database_url, artifact_root = artifact_context
    delegate = LocalVolumeArtifactStore(artifact_root)

    class MismatchedStore:
        chunk_size = delegate.chunk_size

        def put(self, *args: object, **kwargs: object) -> ArtifactStorageMetadata:
            stored = delegate.put(*args, **kwargs)  # type: ignore[arg-type]
            return replace(stored, byte_size=stored.byte_size + 1)

        def delete(self, storage_key: str) -> None:
            delegate.delete(storage_key)

    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_bad_store_metadata")
        with pytest.raises(ImageGenerationArtifactMaterializationError) as error:
            materialize_image_generation_candidates(
                session=session,
                artifact_store=MismatchedStore(),  # type: ignore[arg-type]
                run=run,
                media_candidates=(
                    ProviderMediaCandidate(
                        index=1,
                        content_bytes=_png_bytes(),
                        claimed_mime_type="image/png",
                    ),
                ),
                provider_output={"candidate_count": 1},
            )
        assert error.value.message == "generated artifact storage metadata is invalid"
    assert _stored_paths(artifact_root) == []


@pytest.mark.parametrize("persistent_delete_failure", [False, True])
def test_delete_failure_is_quarantined_across_failed_run_commit(
    artifact_context: tuple[str, Path],
    persistent_delete_failure: bool,
) -> None:
    database_url, artifact_root = artifact_context
    delegate = LocalVolumeArtifactStore(artifact_root)

    class FailFirstDeleteStore:
        chunk_size = delegate.chunk_size
        delete_calls = 0

        def put(self, *args: object, **kwargs: object) -> ArtifactStorageMetadata:
            return delegate.put(*args, **kwargs)  # type: ignore[arg-type]

        def delete(self, storage_key: str) -> None:
            self.delete_calls += 1
            if persistent_delete_failure or self.delete_calls == 1:
                raise ArtifactStoreError("injected delete failure")
            delegate.delete(storage_key)

    store = FailFirstDeleteStore()
    with get_session(database_url) as session:
        run = _create_run(session, run_id="run_image_cleanup_uncertain")
        with pytest.raises(ImageGenerationArtifactCleanupUncertainError) as error:
            materialize_image_generation_candidates(
                session=session,
                artifact_store=store,  # type: ignore[arg-type]
                run=run,
                media_candidates=(
                    ProviderMediaCandidate(
                        index=1,
                        content_bytes=_png_bytes(),
                        claimed_mime_type="image/png",
                    ),
                    ProviderMediaCandidate(
                        index=2,
                        content_bytes=b"not-an-image",
                        claimed_mime_type="image/png",
                    ),
                ),
                provider_output={"candidate_count": 2},
            )
        assert error.value.error_code == "image_generation.artifact_cleanup_uncertain"
        assert len(error.value.storage_keys) == 1
        storage_key = error.value.storage_keys[0]
        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == (storage_key,)
        assert list(
            session.scalars(select(MediaArtifact).where(MediaArtifact.run_id == run.run_id))
        ) == []

        run.status = "failed"
        session.commit()

        assert tracked_artifact_storage_keys(session) == ()
        assert uncertain_artifact_storage_keys(session) == (storage_key,)
        assert list(
            session.scalars(select(MediaArtifact).where(MediaArtifact.run_id == run.run_id))
        ) == []
    assert store.delete_calls == 1
    assert len(_stored_paths(artifact_root)) == 1
