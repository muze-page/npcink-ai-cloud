from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import MediaArtifact, RunRecord, Site
from app.core.secrets import encrypt_runtime_terminal_callback_secret
from app.domain.media_artifacts.projection import (
    MEDIA_ARTIFACT_PROJECTION_MAX_IDS,
    project_media_artifact_lifecycle,
)
from app.domain.media_derivatives.artifacts import (
    MEDIA_DERIVATIVE_ARTIFACT_TYPE,
    MEDIA_DERIVATIVE_RESULT_CONTRACT,
    MEDIA_UPLOAD_ARTIFACT_TYPE,
    MEDIA_UPLOAD_RESULT_CONTRACT,
    build_artifact_result_json,
    build_upload_artifact_result_json,
)
from app.domain.runtime.callback_delivery import RuntimeCallbackDeliveryService
from app.domain.runtime.result_normalization import set_transient_runtime_result
from app.domain.runtime.run_lifecycle import RuntimeRunLifecycleService
from app.domain.runtime.run_projection import RuntimeRunProjector
from app.domain.runtime.service import RuntimeService

PAST = datetime(2000, 1, 1, tzinfo=UTC)
FUTURE = datetime(2100, 1, 1, tzinfo=UTC)


class NonCopyableSentinel:
    def __deepcopy__(self, memo: dict[int, object]) -> object:
        del memo
        raise AssertionError("unrelated results must not be deep-copied")


@pytest.fixture
def database_url(tmp_path: Path) -> Iterator[str]:
    url = f"sqlite+pysqlite:///{tmp_path / 'media-artifact-projection.sqlite3'}"
    init_schema(url)
    with get_session(url) as session:
        session.add_all(
            [
                Site(site_id="site_alpha", name="Site Alpha", status="active"),
                Site(site_id="site_beta", name="Site Beta", status="active"),
            ]
        )
        repository = RuntimeRepository(session)
        _create_run(repository, run_id="run_main", site_id="site_alpha")
        _create_run(repository, run_id="run_other", site_id="site_alpha")
        _create_run(repository, run_id="run_cross_site", site_id="site_beta")
        session.commit()
    yield url
    dispose_engine(url)


def _create_run(
    repository: RuntimeRepository,
    *,
    run_id: str,
    site_id: str,
) -> RunRecord:
    return repository.create_run(
        run_id=run_id,
        site_id=site_id,
        account_id=None,
        subscription_id=None,
        plan_version_id=None,
        ability_name="npcink/test-media-projection",
        ability_family="text",
        skill_id="",
        workflow_id="",
        contract_version="v1",
        channel="openapi",
        execution_kind="media_derivative",
        execution_tier="cloud",
        execution_pattern="inline",
        data_classification="internal",
        profile_id="media.test",
        canonical_run_id=f"local_{run_id}",
        status="succeeded",
        idempotency_key=f"idem_{run_id}",
        request_fingerprint=f"fingerprint_{run_id}",
        trace_id=f"trace_{run_id}",
        input_json={},
        execution_input_ciphertext=None,
        policy_json={},
    )


def _artifact(
    artifact_id: str,
    *,
    run_id: str = "run_main",
    site_id: str = "site_alpha",
    status: str = "available",
    expires_at: datetime = FUTURE,
    purged_at: datetime | None = None,
) -> MediaArtifact:
    return MediaArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        site_id=site_id,
        media_kind="image",
        operation="image.transform.v1",
        content_type="image/png",
        byte_size=3,
        storage_key=f"private/{artifact_id}",
        status=status,
        format="png",
        width=1,
        height=1,
        checksum=f"sha256:{artifact_id}",
        expires_at=expires_at,
        purged_at=purged_at,
    )


def test_projects_only_known_envelopes_and_current_lifecycle(database_url: str) -> None:
    with get_session(database_url) as session:
        session.add_all(
            [
                _artifact("art_available"),
                _artifact("art_expired", expires_at=PAST),
                _artifact("art_pending", status="purge_pending"),
                _artifact("art_purged", status="purged"),
                _artifact("art_purged_at", purged_at=PAST),
                _artifact("art_other_run", run_id="run_other"),
                _artifact("art_cross_site", run_id="run_cross_site", site_id="site_beta"),
            ]
        )
        session.flush()
        snapshot = {
            "artifact_type": "image_generation_artifacts",
            "contract_version": "image_generation_result.v1",
            "artifacts": [
                {"artifact_id": "art_expired", "status": "created"},
                {"artifact_id": "art_pending", "status": "created"},
                {"artifact_id": "art_purged", "status": "created"},
                {"artifact_id": "art_purged_at", "status": "created"},
                {"artifact_id": "art_missing", "status": "created"},
                {"artifact_id": "art_other_run", "status": "created"},
                {"artifact_id": "art_cross_site", "status": "created"},
            ],
            "arbitrary": {"artifact": {"artifact_id": "art_purged", "status": "created"}},
        }
        original = deepcopy(snapshot)

        projected = project_media_artifact_lifecycle(
            snapshot,
            session=session,
            site_id="site_alpha",
            run_id="run_main",
            now=datetime(2026, 7, 15, tzinfo=UTC),
        )
        root_projected = project_media_artifact_lifecycle(
            {
                "artifact_type": MEDIA_UPLOAD_ARTIFACT_TYPE,
                "contract_version": MEDIA_UPLOAD_RESULT_CONTRACT,
                "artifact": {
                    "artifact_id": "art_available",
                    "status": "created",
                    "keep": "root",
                    "storage_key": "must-not-leak",
                    "purge_last_error_code": "must-not-leak",
                    "purge_claim_id": "pcl_must-not-leak",
                    "purge_claim_expires_at": "must-not-leak",
                    "download_url": "/historical/download?token=secret",
                    "b64_json": "historical-base64",
                },
            },
            session=session,
            site_id="site_alpha",
            run_id="run_main",
            now=datetime(2026, 7, 15, tzinfo=UTC),
        )
        session.commit()

    assert snapshot == original
    assert root_projected["artifact"]["status"] == "available"
    assert root_projected["artifact"]["keep"] == "root"
    assert "storage_key" not in root_projected["artifact"]
    assert "purge_last_error_code" not in root_projected["artifact"]
    assert "purge_claim_id" not in root_projected["artifact"]
    assert "purge_claim_expires_at" not in root_projected["artifact"]
    assert "download_url" not in root_projected["artifact"]
    assert "b64_json" not in root_projected["artifact"]
    assert [item["status"] for item in projected["artifacts"]] == [
        "expired",
        "expired",
        "purged",
        "purged",
        "unavailable",
        "unavailable",
        "unavailable",
    ]
    assert projected["arbitrary"]["artifact"]["status"] == "created"
    assert root_projected["artifact"]["expires_at"].endswith("+00:00")
    assert projected["artifacts"][2]["purged_at"] is None

    with get_session(database_url) as session:
        audio_projected = project_media_artifact_lifecycle(
            {
                "artifact_type": "audio_generation_candidates",
                "contract_version": "audio_generation_result.v1",
                "audios": [
                    {
                        "url": "/historical/public-download?token=secret",
                        "subtitle_url": "https://provider.example/subtitle.srt",
                        "b64_json": "historical-base64",
                        "artifact": {
                            "artifact_id": "art_available",
                            "authenticated_download_url": "/historical/download",
                        },
                    }
                ],
                "items": [{"artifact": {"artifact_id": "art_expired"}}],
            },
            session=session,
            site_id="site_alpha",
            run_id="run_main",
            now=datetime(2026, 7, 15, tzinfo=UTC),
        )
        unknown_projected = project_media_artifact_lifecycle(
            {
                "artifact_type": "provider_audio_debug",
                "audios": [{"artifact": {"artifact_id": "art_available", "status": "created"}}],
            },
            session=session,
            site_id="site_alpha",
            run_id="run_main",
        )
        unversioned_audio_projected = project_media_artifact_lifecycle(
            {
                "artifact_type": "audio_generation_candidates",
                "audios": [
                    {"artifact": {"artifact_id": "art_available", "status": "created"}}
                ],
            },
            session=session,
            site_id="site_alpha",
            run_id="run_main",
        )
        wrong_version_image_projected = project_media_artifact_lifecycle(
            {
                "artifact_type": "image_generation_artifacts",
                "contract_version": "unknown.v1",
                "artifacts": [{"artifact_id": "art_available", "status": "created"}],
            },
            session=session,
            site_id="site_alpha",
            run_id="run_main",
        )

    assert audio_projected["audios"][0]["artifact"]["status"] == "available"
    assert "url" not in audio_projected["audios"][0]
    assert "subtitle_url" not in audio_projected["audios"][0]
    assert "b64_json" not in audio_projected["audios"][0]
    assert "authenticated_download_url" not in audio_projected["audios"][0]["artifact"]
    assert audio_projected["items"][0]["artifact"]["status"] == "expired"
    assert unknown_projected["audios"][0]["artifact"]["status"] == "created"
    assert unversioned_audio_projected["audios"][0]["artifact"]["status"] == "created"
    assert wrong_version_image_projected["artifacts"][0]["status"] == "created"


def test_query_cap_fails_excess_references_closed(database_url: str) -> None:
    artifact_ids = [
        f"art_cap_{index}" for index in range(MEDIA_ARTIFACT_PROJECTION_MAX_IDS + 1)
    ]
    with get_session(database_url) as session:
        session.add_all(_artifact(artifact_id) for artifact_id in artifact_ids)
        session.flush()
        projected = project_media_artifact_lifecycle(
            {
                "artifact_type": "image_generation_artifacts",
                "contract_version": "image_generation_result.v1",
                "artifacts": [{"artifact_id": artifact_id} for artifact_id in artifact_ids],
            },
            session=session,
            site_id="site_alpha",
            run_id="run_main",
        )

    assert all(
        item["status"] == "available"
        for item in projected["artifacts"][:MEDIA_ARTIFACT_PROJECTION_MAX_IDS]
    )
    assert projected["artifacts"][MEDIA_ARTIFACT_PROJECTION_MAX_IDS]["status"] == (
        "unavailable"
    )


def test_unrelated_result_returns_without_deepcopy(database_url: str) -> None:
    result = {"provider_debug": NonCopyableSentinel()}
    with get_session(database_url) as session:
        projected = project_media_artifact_lifecycle(
            result,
            session=session,
            site_id="site_alpha",
            run_id="run_main",
        )

    assert projected is result


@pytest.mark.parametrize(
    "result",
    [
        {"artifact": {"artifact_id": "art_available", "status": "created"}},
        {
            "artifact_type": MEDIA_UPLOAD_ARTIFACT_TYPE,
            "artifact": {"artifact_id": "art_available", "status": "created"},
        },
        {
            "artifact_type": MEDIA_UPLOAD_ARTIFACT_TYPE,
            "contract_version": "unknown.v1",
            "artifact": {"artifact_id": "art_available", "status": "created"},
        },
        {
            "artifact_type": "unknown_artifact",
            "contract_version": MEDIA_UPLOAD_RESULT_CONTRACT,
            "artifact": {"artifact_id": "art_available", "status": "created"},
        },
    ],
)
def test_root_artifact_requires_exact_type_and_version(
    database_url: str,
    result: dict[str, object],
) -> None:
    with get_session(database_url) as session:
        projected = project_media_artifact_lifecycle(
            result,
            session=session,
            site_id="site_alpha",
            run_id="run_main",
        )

    assert projected is result
    assert projected["artifact"]["status"] == "created"


def test_media_result_producers_emit_stable_type_and_version_markers() -> None:
    artifact = _artifact("art_producer_contract")

    upload = build_upload_artifact_result_json(artifact)
    derivative = build_artifact_result_json(artifact)

    assert upload["artifact_type"] == MEDIA_UPLOAD_ARTIFACT_TYPE
    assert upload["contract_version"] == MEDIA_UPLOAD_RESULT_CONTRACT
    assert derivative["artifact_type"] == MEDIA_DERIVATIVE_ARTIFACT_TYPE
    assert derivative["contract_version"] == MEDIA_DERIVATIVE_RESULT_CONTRACT


def test_public_result_outlets_project_without_mutating_snapshot(database_url: str) -> None:
    snapshot = {
        "artifact_type": MEDIA_DERIVATIVE_ARTIFACT_TYPE,
        "contract_version": MEDIA_DERIVATIVE_RESULT_CONTRACT,
        "artifact": {
            "artifact_id": "art_outlets",
            "artifact_reference": {"artifact_id": "art_outlets"},
            "expires_at": FUTURE.isoformat(),
            "suggested_filename": "media-derivative-png-aabbccdd.png",
            "filename_basis": {
                "owner": "wordpress_write_ability_final",
                "strategy": "format_checksum",
                "final_sanitize_unique_required": True,
            },
            "mime_type": "image/png",
            "format": "png",
            "width": 1,
            "height": 1,
            "filesize_bytes": 3,
            "checksum": f"sha256:{'a' * 64}",
            "processing_warnings": [],
        },
    }
    with get_session(database_url) as session:
        run = session.get(RunRecord, "run_main")
        assert run is not None
        run.result_json = deepcopy(snapshot)
        session.add(_artifact("art_outlets", expires_at=PAST))
        session.commit()

    lifecycle = RuntimeRunLifecycleService(
        database_url=database_url,
        runtime_queue=None,
        run_projector=RuntimeRunProjector(),
        claimed_run_executor=lambda run, repository: None,
        media_derivative_site_running_limit=1,
    )
    lifecycle_artifact = lifecycle.get_run_result("run_main", site_id="site_alpha")[
        "result"
    ]["artifact"]
    assert set(lifecycle_artifact) == {
        "artifact_id",
        "artifact_reference",
        "expires_at",
        "suggested_filename",
        "filename_basis",
        "mime_type",
        "format",
        "width",
        "height",
        "filesize_bytes",
        "checksum",
        "processing_warnings",
    }
    assert lifecycle_artifact == snapshot["artifact"]

    runtime = object.__new__(RuntimeService)
    runtime.run_projector = RuntimeRunProjector()
    with get_session(database_url) as session:
        repository = RuntimeRepository(session)
        run = repository.get_run("run_main")
        assert run is not None
        set_transient_runtime_result(run, deepcopy(snapshot))
        initial = runtime._build_execution_response(
            run,
            repository=repository,
            idempotent_replay=False,
        )
        delattr(run, "_transient_result_json")
        replay = runtime._build_execution_response(
            run,
            repository=repository,
            idempotent_replay=True,
        )

    assert initial.result["artifact"] == snapshot["artifact"]
    assert replay.idempotent_replay is True
    assert replay.result["artifact"] == snapshot["artifact"]
    with get_session(database_url) as session:
        run = session.get(RunRecord, "run_main")
        assert run is not None
        assert run.result_json == snapshot


def test_real_delayed_callback_claim_projects_without_rewriting_snapshot(
    database_url: str,
) -> None:
    settings = Settings(
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        admin_session_secret="a" * 32,
        portal_jwt_secret="p" * 32,
    )
    snapshot = {
        "artifact_type": MEDIA_UPLOAD_ARTIFACT_TYPE,
        "contract_version": MEDIA_UPLOAD_RESULT_CONTRACT,
        "artifact": {"artifact_id": "art_callback_claim", "status": "available"},
    }
    with get_session(database_url) as session:
        run = session.get(RunRecord, "run_main")
        site = session.get(Site, "site_alpha")
        assert run is not None
        assert site is not None
        run.result_json = deepcopy(snapshot)
        run.finished_at = datetime(2026, 7, 15, tzinfo=UTC)
        run.callback_status = "pending"
        run.callback_attempt_count = 0
        run.callback_next_attempt_at = PAST
        run.policy_json = {
            "runtime_callback": {
                "source": "site_registered",
                "callback_url": "https://callback.example.test/runtime",
                "key_id": "callback_key",
                "callback_id": "runtime_terminal_test",
                "registered": True,
            },
            "task_backend": {
                "enabled": False,
                "callback_mode": "polling_preferred",
            },
        }
        site.metadata_json = {
            "runtime_callbacks": {
                "terminal": {
                    "enabled": True,
                    "callback_url": "https://callback.example.test/runtime",
                    "key_id": "callback_key",
                    "secret_ciphertext": encrypt_runtime_terminal_callback_secret(
                        "callback-secret",
                        settings=settings,
                    ),
                    "callback_id": "runtime_terminal_test",
                }
            }
        }
        session.add(_artifact("art_callback_claim", expires_at=PAST))
        session.commit()

    request = RuntimeCallbackDeliveryService(
        database_url=database_url,
        settings=settings,
        dispatcher=None,
    )._claim_next_pending_callback()

    assert request is not None
    assert request.payload["result"]["artifact"]["status"] == "expired"
    with get_session(database_url) as session:
        run = session.get(RunRecord, "run_main")
        assert run is not None
        assert run.result_json == snapshot
