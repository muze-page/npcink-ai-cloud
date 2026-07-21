from __future__ import annotations

import inspect
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import StatementError

from app.adapters.repositories.runtime_repository import RuntimeRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import MediaArtifact, MediaArtifactDelivery
from app.domain.media_artifacts import ArtifactStoreError
from app.domain.media_artifacts.lifecycle import (
    MEDIA_ARTIFACT_PURGE_ERROR_CODE,
    MEDIA_ARTIFACT_PURGE_LEASE_SECONDS,
    MediaArtifactLifecycleError,
    MediaArtifactLifecycleService,
)
from tests.conftest import seed_site_auth


class RecordingDeleteStore:
    chunk_size = 64 * 1024

    def __init__(self, callback: Callable[[str, int], None] | None = None) -> None:
        self._callback = callback
        self.deleted: list[str] = []

    def delete(self, storage_key: str) -> None:
        self.deleted.append(storage_key)
        if self._callback is not None:
            self._callback(storage_key, len(self.deleted))

    def put(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("put must not be called by lifecycle cleanup")

    def open(self, storage_key: str) -> object:
        raise AssertionError(f"open must not be called for {storage_key}")

    def metadata(self, storage_key: str) -> object:
        raise AssertionError(f"metadata must not be called for {storage_key}")


@pytest.fixture
def lifecycle_database(tmp_path: Path) -> Iterator[str]:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'artifact-lifecycle.sqlite3'}"
    init_schema(database_url)
    seed_site_auth(database_url, site_id="site_alpha")
    with get_session(database_url) as session:
        RuntimeRepository(session).create_run(
            run_id="run_artifact_lifecycle",
            site_id="site_alpha",
            account_id=None,
            subscription_id=None,
            plan_version_id=None,
            ability_name="npcink-cloud/media-lifecycle-test",
            ability_family="media",
            skill_id=None,
            workflow_id=None,
            contract_version="media_lifecycle_test.v1",
            channel="internal",
            execution_kind="media",
            execution_tier="cloud",
            execution_pattern="inline",
            data_classification="internal",
            profile_id="media.lifecycle.test",
            canonical_run_id=None,
            status="succeeded",
            idempotency_key="idem-artifact-lifecycle",
            request_fingerprint="fingerprint-artifact-lifecycle",
            trace_id="trace-artifact-lifecycle",
            input_json={},
            execution_input_ciphertext=None,
            policy_json={"storage_mode": "result_only"},
        )
        session.commit()
    yield database_url
    dispose_engine(database_url)


def _artifact(
    artifact_id: str,
    *,
    now: datetime,
    expires_delta: timedelta = timedelta(minutes=-1),
    attempt_count: int = 0,
    next_attempt_at: datetime | None = None,
    claim_id: str | None = None,
    claim_expires_at: datetime | None = None,
) -> MediaArtifact:
    suffix = artifact_id.removeprefix("art_").ljust(32, "0")[:32]
    return MediaArtifact(
        artifact_id=artifact_id,
        run_id="run_artifact_lifecycle",
        site_id="site_alpha",
        media_kind="image",
        operation="image.transform.v1",
        content_type="image/png",
        byte_size=3,
        checksum="sha256:" + ("a" * 64),
        storage_key=f"obj_{suffix}",
        status="available",
        format="png",
        width=1,
        height=1,
        expires_at=now + expires_delta,
        purge_attempt_count=attempt_count,
        purge_next_attempt_at=next_attempt_at,
        purge_claim_id=claim_id,
        purge_claim_expires_at=claim_expires_at,
        created_at=now - timedelta(hours=1),
    )


def _delivery(
    delivery_id: str,
    artifact_id: str,
    *,
    now: datetime,
    completed: bool = False,
    acked: bool = False,
) -> MediaArtifactDelivery:
    completed_at = now - timedelta(seconds=2) if completed or acked else None
    return MediaArtifactDelivery(
        delivery_id=delivery_id,
        artifact_id=artifact_id,
        site_id="site_alpha",
        expected_byte_size=3,
        expected_checksum="sha256:" + ("a" * 64),
        pull_trace_id=f"trace-{delivery_id}",
        started_at=now - timedelta(seconds=4),
        completed_at=completed_at,
        completed_byte_size=3 if completed_at is not None else None,
        completed_checksum="sha256:" + ("a" * 64) if completed_at is not None else None,
        ack_deadline_at=now + timedelta(minutes=10),
        acked_at=now - timedelta(seconds=1) if acked else None,
    )


def _empty_evidence() -> dict[str, int]:
    return {
        "claimed": 0,
        "purged": 0,
        "retry_scheduled": 0,
        "stale_claims_reclaimed": 0,
        "superseded_finalizations": 0,
    }


def test_success_claim_is_committed_and_unacked_deliveries_revoked_before_delete(
    lifecycle_database: str,
) -> None:
    now = datetime(2026, 7, 15, 8, 0, tzinfo=UTC)
    artifact_id = "art_success"
    with get_session(lifecycle_database) as session:
        session.add(_artifact(artifact_id, now=now))
        session.add_all(
            [
                _delivery("mdl_01_incomplete", artifact_id, now=now),
                _delivery("mdl_02_completed", artifact_id, now=now, completed=True),
                _delivery("mdl_03_acked", artifact_id, now=now, acked=True),
            ]
        )
        session.commit()

    observed: dict[str, object] = {}

    def observe_committed_claim(_storage_key: str, _attempt: int) -> None:
        with get_session(lifecycle_database) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            deliveries = list(
                session.scalars(
                    select(MediaArtifactDelivery)
                    .where(MediaArtifactDelivery.artifact_id == artifact_id)
                    .order_by(MediaArtifactDelivery.delivery_id)
                )
            )
            assert artifact is not None
            observed["status"] = artifact.status
            observed["claim_id"] = artifact.purge_claim_id
            observed["claim_expires_at"] = artifact.purge_claim_expires_at
            observed["revoked"] = [delivery.revoked_at is not None for delivery in deliveries]

    store = RecordingDeleteStore(observe_committed_claim)
    service = MediaArtifactLifecycleService(lifecycle_database, artifact_store=store)  # type: ignore[arg-type]

    result = service.cleanup_expired_artifacts(now=now)

    assert result == {
        "claimed": 1,
        "purged": 1,
        "retry_scheduled": 0,
        "stale_claims_reclaimed": 0,
        "superseded_finalizations": 0,
    }
    assert set(result) == set(_empty_evidence())
    assert observed["status"] == "purge_pending"
    assert str(observed["claim_id"]).startswith("pcl_")
    assert observed["claim_expires_at"] is not None
    assert observed["revoked"] == [True, True, False]
    assert "session" not in inspect.signature(MediaArtifactLifecycleService).parameters
    assert "session" not in inspect.signature(service.cleanup_expired_artifacts).parameters

    with get_session(lifecycle_database) as session:
        artifact = session.get(MediaArtifact, artifact_id)
        deliveries = list(
            session.scalars(
                select(MediaArtifactDelivery)
                .where(MediaArtifactDelivery.artifact_id == artifact_id)
                .order_by(MediaArtifactDelivery.delivery_id)
            )
        )
        assert artifact is not None
        assert artifact.status == "purged"
        assert (
            now.replace(tzinfo=None)
            <= artifact.purged_at
            < (now + timedelta(seconds=1)).replace(tzinfo=None)
        )
        assert artifact.purge_attempt_count == 1
        assert artifact.purge_last_attempt_at == now.replace(tzinfo=None)
        assert artifact.purge_next_attempt_at is None
        assert artifact.purge_last_error_code is None
        assert artifact.purge_claim_id is None
        assert artifact.purge_claim_expires_at is None
        assert [delivery.revoked_at is not None for delivery in deliveries] == [True, True, False]
        assert deliveries[1].completed_at <= deliveries[1].revoked_at


def test_delete_failure_schedules_redacted_backoff_and_preserves_first_revocation(
    lifecycle_database: str,
) -> None:
    now = datetime(2026, 7, 15, 9, 0, tzinfo=UTC)
    artifact_id = "art_retry"
    delivery_id = "mdl_retry"
    with get_session(lifecycle_database) as session:
        session.add(_artifact(artifact_id, now=now))
        session.add(_delivery(delivery_id, artifact_id, now=now, completed=True))
        session.commit()

    def fail_with_private_detail(storage_key: str, _attempt: int) -> None:
        raise ArtifactStoreError(f"private delete detail for {storage_key}")

    failing_store = RecordingDeleteStore(fail_with_private_detail)
    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=failing_store,  # type: ignore[arg-type]
    )
    assert service.cleanup_expired_artifacts(now=now) == {
        "claimed": 1,
        "purged": 0,
        "retry_scheduled": 1,
        "stale_claims_reclaimed": 0,
        "superseded_finalizations": 0,
    }
    with get_session(lifecycle_database) as session:
        artifact = session.get(MediaArtifact, artifact_id)
        delivery = session.get(MediaArtifactDelivery, delivery_id)
        assert artifact is not None and delivery is not None
        first_revoked_at = delivery.revoked_at
        assert artifact.status == "purge_pending"
        assert artifact.purge_last_error_code == MEDIA_ARTIFACT_PURGE_ERROR_CODE
        assert "private" not in artifact.purge_last_error_code
        assert (
            (now + timedelta(seconds=30)).replace(tzinfo=None)
            <= artifact.purge_next_attempt_at
            < (now + timedelta(seconds=31)).replace(tzinfo=None)
        )
        retry_at = artifact.purge_next_attempt_at.replace(tzinfo=UTC)
        assert artifact.purge_claim_id is None
        assert artifact.purge_claim_expires_at is None

    assert service.cleanup_expired_artifacts(now=retry_at - timedelta(microseconds=1)) == (
        _empty_evidence()
    )
    success_store = RecordingDeleteStore()
    retried = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=success_store,  # type: ignore[arg-type]
    ).cleanup_expired_artifacts(now=retry_at)
    assert retried["claimed"] == 1
    assert retried["purged"] == 1
    with get_session(lifecycle_database) as session:
        artifact = session.get(MediaArtifact, artifact_id)
        delivery = session.get(MediaArtifactDelivery, delivery_id)
        assert artifact is not None and delivery is not None
        assert artifact.purge_attempt_count == 2
        assert delivery.revoked_at == first_revoked_at


def test_active_lease_is_skipped_and_stale_claim_finalize_is_fenced(
    lifecycle_database: str,
) -> None:
    now = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    active_id = "art_active"
    stale_id = "art_stale"
    with get_session(lifecycle_database) as session:
        session.add_all(
            [
                _artifact(
                    active_id,
                    now=now,
                    claim_id="pcl_active",
                    claim_expires_at=now + timedelta(seconds=1),
                ),
                _artifact(
                    stale_id,
                    now=now,
                    claim_id="pcl_stale",
                    claim_expires_at=now,
                ),
            ]
        )
        session.commit()

    replacement_claim = "pcl_replacement"

    def supersede_claim(_storage_key: str, _attempt: int) -> None:
        with get_session(lifecycle_database) as session:
            artifact = session.get(MediaArtifact, stale_id)
            assert artifact is not None
            artifact.purge_claim_id = replacement_claim
            artifact.purge_claim_expires_at = now + timedelta(minutes=10)
            session.commit()

    store = RecordingDeleteStore(supersede_claim)
    result = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=store,  # type: ignore[arg-type]
    ).cleanup_expired_artifacts(now=now)

    assert result == {
        "claimed": 1,
        "purged": 0,
        "retry_scheduled": 0,
        "stale_claims_reclaimed": 1,
        "superseded_finalizations": 1,
    }
    with get_session(lifecycle_database) as session:
        active = session.get(MediaArtifact, active_id)
        stale = session.get(MediaArtifact, stale_id)
        assert active is not None and stale is not None
        assert active.purge_claim_id == "pcl_active"
        assert active.purge_attempt_count == 0
        assert stale.status == "purge_pending"
        assert stale.purged_at is None
        assert stale.purge_claim_id == replacement_claim


def test_crash_after_idempotent_delete_converges_after_stale_lease(
    lifecycle_database: str,
) -> None:
    now = datetime(2026, 7, 15, 11, 0, tzinfo=UTC)
    artifact_id = "art_crash"
    with get_session(lifecycle_database) as session:
        session.add(_artifact(artifact_id, now=now))
        session.commit()

    def crash_after_delete(_storage_key: str, attempt: int) -> None:
        if attempt == 1:
            raise KeyboardInterrupt("simulated worker crash after idempotent delete")

    store = RecordingDeleteStore(crash_after_delete)
    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=store,  # type: ignore[arg-type]
    )
    clock_values = iter(
        (
            now,
            now,
            now + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS - 1),
            now + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS),
            now + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS),
            now + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS),
        )
    )
    service._clock_now = lambda: next(clock_values)  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        service.cleanup_expired_artifacts(now=now)
    with get_session(lifecycle_database) as session:
        artifact = session.get(MediaArtifact, artifact_id)
        assert artifact is not None
        assert artifact.status == "purge_pending"
        assert artifact.purge_claim_id is not None
        assert artifact.purge_claim_expires_at == (
            now + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS)
        ).replace(tzinfo=None)

    before_expiry = service.cleanup_expired_artifacts(
        now=now + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS - 1)
    )
    assert before_expiry == _empty_evidence()
    recovered = service.cleanup_expired_artifacts(
        now=now + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS)
    )
    assert recovered == {
        "claimed": 1,
        "purged": 1,
        "retry_scheduled": 0,
        "stale_claims_reclaimed": 1,
        "superseded_finalizations": 0,
    }
    assert len(store.deleted) == 2


def test_batch_fairness_and_backoff_cap(lifecycle_database: str) -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    with get_session(lifecycle_database) as session:
        session.add_all(
            [
                _artifact(
                    f"art_fail_{index}",
                    now=now,
                    expires_delta=timedelta(minutes=-2, microseconds=index),
                )
                for index in range(3)
            ]
            + [
                _artifact(
                    f"art_success_{index}",
                    now=now,
                    expires_delta=timedelta(minutes=-1, microseconds=index),
                )
                for index in range(3)
            ]
            + [
                _artifact(
                    "art_backoff_cap",
                    now=now,
                    expires_delta=timedelta(minutes=-3),
                    attempt_count=20,
                )
            ]
        )
        session.commit()

    def fail_selected(storage_key: str, _attempt: int) -> None:
        if "fail" in storage_key or "backoff" in storage_key:
            raise ArtifactStoreError("injected")

    store = RecordingDeleteStore(fail_selected)
    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=store,  # type: ignore[arg-type]
    )
    first = service.cleanup_expired_artifacts(now=now, batch_size=2)
    second = service.cleanup_expired_artifacts(now=now, batch_size=2)
    third = service.cleanup_expired_artifacts(now=now, batch_size=2)
    fourth = service.cleanup_expired_artifacts(now=now, batch_size=2)

    assert [result["claimed"] for result in (first, second, third, fourth)] == [2, 2, 2, 1]
    assert sum(result["purged"] for result in (first, second, third, fourth)) == 3
    assert sum(result["retry_scheduled"] for result in (first, second, third, fourth)) == 4
    with get_session(lifecycle_database) as session:
        capped = session.get(MediaArtifact, "art_backoff_cap")
        successes = list(
            session.scalars(
                select(MediaArtifact).where(MediaArtifact.artifact_id.like("art_success_%"))
            )
        )
        assert capped is not None
        assert capped.purge_attempt_count == 21
        assert (
            (now + timedelta(hours=1)).replace(tzinfo=None)
            <= capped.purge_next_attempt_at
            < (now + timedelta(hours=1, seconds=1)).replace(tzinfo=None)
        )
        assert {artifact.status for artifact in successes} == {"purged"}


def test_retry_clock_starts_after_slow_delete_returns(lifecycle_database: str) -> None:
    claim_time = datetime(2026, 7, 15, 14, 0, tzinfo=UTC)
    finalize_time = claim_time + timedelta(seconds=17)
    artifact_id = "art_slow_delete"
    with get_session(lifecycle_database) as session:
        session.add(_artifact(artifact_id, now=claim_time))
        session.commit()

    def fail_delete(_storage_key: str, _attempt: int) -> None:
        raise ArtifactStoreError("injected slow delete failure")

    clock_values = iter((claim_time, claim_time, finalize_time))
    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=RecordingDeleteStore(fail_delete),  # type: ignore[arg-type]
    )
    service._clock_now = lambda: next(clock_values)  # type: ignore[method-assign]

    result = service.cleanup_expired_artifacts(now=claim_time)

    assert result["retry_scheduled"] == 1
    with get_session(lifecycle_database) as session:
        artifact = session.get(MediaArtifact, artifact_id)
        assert artifact is not None
        assert artifact.purge_next_attempt_at == (finalize_time + timedelta(seconds=30)).replace(
            tzinfo=None
        )


def test_claim_lease_is_refreshed_after_slow_revocation_before_delete(
    lifecycle_database: str,
) -> None:
    claim_time = datetime(2026, 7, 15, 15, 0, tzinfo=UTC)
    revocation_finished_at = claim_time + timedelta(
        seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS + 17
    )
    finalize_time = revocation_finished_at + timedelta(seconds=3)
    artifact_id = "art_slow_revocation"
    with get_session(lifecycle_database) as session:
        session.add(_artifact(artifact_id, now=claim_time))
        session.add(_delivery("mdl_slow_revocation", artifact_id, now=claim_time))
        session.commit()

    observed: dict[str, datetime | None] = {}

    def observe_refreshed_lease(_storage_key: str, _attempt: int) -> None:
        with get_session(lifecycle_database) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            observed["claim_expires_at"] = artifact.purge_claim_expires_at

    clock_values = iter((claim_time, revocation_finished_at, finalize_time))
    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=RecordingDeleteStore(observe_refreshed_lease),  # type: ignore[arg-type]
    )
    service._clock_now = lambda: next(clock_values)  # type: ignore[method-assign]

    result = service.cleanup_expired_artifacts(now=claim_time)

    assert result["purged"] == 1
    assert observed["claim_expires_at"] == (
        revocation_finished_at + timedelta(seconds=MEDIA_ARTIFACT_PURGE_LEASE_SECONDS)
    ).replace(tzinfo=None)


def test_unexpected_delete_error_finalizes_safely_then_raises_stable_error(
    lifecycle_database: str,
) -> None:
    now = datetime(2026, 7, 15, 16, 0, tzinfo=UTC)
    artifact_id = "art_unexpected_delete"
    private_detail = "private /srv/media/obj_unexpected_delete"
    with get_session(lifecycle_database) as session:
        session.add(_artifact(artifact_id, now=now))
        session.commit()

    def fail_unexpectedly(_storage_key: str, _attempt: int) -> None:
        raise RuntimeError(private_detail)

    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=RecordingDeleteStore(fail_unexpectedly),  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError) as captured:
        service.cleanup_expired_artifacts(now=now)

    assert str(captured.value) == "media artifact lifecycle cleanup failed"
    assert private_detail not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True
    with get_session(lifecycle_database) as session:
        artifact = session.get(MediaArtifact, artifact_id)
        assert artifact is not None
        assert artifact.status == "purge_pending"
        assert artifact.purge_claim_id is None
        assert artifact.purge_claim_expires_at is None
        assert artifact.purge_last_error_code == MEDIA_ARTIFACT_PURGE_ERROR_CODE
        assert artifact.purge_next_attempt_at is not None


def test_claim_stage_database_error_is_wrapped_without_private_statement_details(
    lifecycle_database: str,
) -> None:
    private_statement = "SELECT * FROM media_artifacts WHERE storage_key=:storage_key"
    private_params = {"storage_key": "private/object/claim-source.png"}
    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=RecordingDeleteStore(),  # type: ignore[arg-type]
    )

    def fail_claim(**_kwargs: object) -> tuple[list[object], int]:
        raise StatementError(
            "private claim-stage database failure",
            private_statement,
            private_params,
            RuntimeError("private driver detail"),
        )

    service._claim_batch = fail_claim  # type: ignore[method-assign]
    with pytest.raises(MediaArtifactLifecycleError) as captured:
        service.cleanup_expired_artifacts(
            now=datetime(2026, 7, 15, 16, 30, tzinfo=UTC)
        )

    assert str(captured.value) == "media artifact lifecycle cleanup failed"
    assert private_statement not in repr(captured.value)
    assert private_params["storage_key"] not in repr(captured.value)
    assert captured.value.__cause__ is None
    assert captured.value.__suppress_context__ is True


def test_claim_stage_base_exception_is_not_wrapped(lifecycle_database: str) -> None:
    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=RecordingDeleteStore(),  # type: ignore[arg-type]
    )
    primary_error = KeyboardInterrupt("operator interrupt")

    def interrupt_claim(**_kwargs: object) -> tuple[list[object], int]:
        raise primary_error

    service._claim_batch = interrupt_claim  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt) as captured:
        service.cleanup_expired_artifacts(
            now=datetime(2026, 7, 15, 16, 31, tzinfo=UTC)
        )

    assert captured.value is primary_error


def test_superseded_failure_finalize_cannot_overwrite_replacement_claim(
    lifecycle_database: str,
) -> None:
    now = datetime(2026, 7, 15, 17, 0, tzinfo=UTC)
    artifact_id = "art_superseded_failure"
    replacement_claim_id = "pcl_replacement_failure"
    replacement_expiry = now + timedelta(minutes=20)
    replacement_retry = now + timedelta(minutes=7)
    replacement_error = "replacement.error"
    with get_session(lifecycle_database) as session:
        session.add(_artifact(artifact_id, now=now))
        session.commit()

    def replace_then_fail(_storage_key: str, _attempt: int) -> None:
        with get_session(lifecycle_database) as session:
            artifact = session.get(MediaArtifact, artifact_id)
            assert artifact is not None
            artifact.purge_claim_id = replacement_claim_id
            artifact.purge_claim_expires_at = replacement_expiry
            artifact.purge_next_attempt_at = replacement_retry
            artifact.purge_last_error_code = replacement_error
            session.commit()
        raise ArtifactStoreError("expected delete failure")

    result = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=RecordingDeleteStore(replace_then_fail),  # type: ignore[arg-type]
    ).cleanup_expired_artifacts(now=now)

    assert result == {
        "claimed": 1,
        "purged": 0,
        "retry_scheduled": 0,
        "stale_claims_reclaimed": 0,
        "superseded_finalizations": 1,
    }
    with get_session(lifecycle_database) as session:
        artifact = session.get(MediaArtifact, artifact_id)
        assert artifact is not None
        assert artifact.purge_claim_id == replacement_claim_id
        assert artifact.purge_claim_expires_at == replacement_expiry.replace(tzinfo=None)
        assert artifact.purge_next_attempt_at == replacement_retry.replace(tzinfo=None)
        assert artifact.purge_last_error_code == replacement_error


def test_slow_success_records_exact_post_delete_finalize_time(
    lifecycle_database: str,
) -> None:
    claim_time = datetime(2026, 7, 15, 18, 0, tzinfo=UTC)
    lease_refresh_time = claim_time + timedelta(seconds=4)
    finalize_time = claim_time + timedelta(seconds=29)
    artifact_id = "art_slow_success"
    with get_session(lifecycle_database) as session:
        session.add(_artifact(artifact_id, now=claim_time))
        session.commit()

    clock_values = iter((claim_time, lease_refresh_time, finalize_time))
    service = MediaArtifactLifecycleService(
        lifecycle_database,
        artifact_store=RecordingDeleteStore(),  # type: ignore[arg-type]
    )
    service._clock_now = lambda: next(clock_values)  # type: ignore[method-assign]

    result = service.cleanup_expired_artifacts(now=claim_time)

    assert result["purged"] == 1
    with get_session(lifecycle_database) as session:
        artifact = session.get(MediaArtifact, artifact_id)
        assert artifact is not None
        assert artifact.purged_at == finalize_time.replace(tzinfo=None)
