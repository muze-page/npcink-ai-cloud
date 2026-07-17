from __future__ import annotations

import inspect
from pathlib import Path

from app.api.routes import media_derivatives as media_routes
from app.domain.media_artifacts import delivery
from app.domain.media_artifacts.lifecycle import MediaArtifactLifecycleService

ROOT = Path(__file__).resolve().parents[2]


def _locked_artifact_precedes_locked_delivery(function: object) -> None:
    source = inspect.getsource(function)
    artifact_position = source.index("select(MediaArtifact)")
    delivery_position = source.index("select(MediaArtifactDelivery)", artifact_position)
    assert artifact_position < delivery_position
    assert ".with_for_update()" in source[artifact_position:delivery_position]
    assert ".with_for_update()" in source[delivery_position:]


def test_prepare_completion_and_ack_use_one_artifact_first_lock_order() -> None:
    prepare_source = inspect.getsource(delivery.prepare_media_artifact_delivery)
    assert prepare_source.index("select(MediaArtifact)") < prepare_source.index(
        "delivery = MediaArtifactDelivery("
    )
    assert (
        ".with_for_update()"
        in prepare_source[
            prepare_source.index("select(MediaArtifact)") : prepare_source.index(
                "delivery = MediaArtifactDelivery("
            )
        ]
    )
    initial_time_position = prepare_source.index("initial_time = _delivery_time(now)")
    store_open_position = prepare_source.index("stream = artifact_store.open")
    final_time_position = prepare_source.index("final_time = _delivery_time(now)")
    delivery_create_position = prepare_source.index("delivery = MediaArtifactDelivery(")
    first_flush_position = prepare_source.index("session.flush()")
    precommit_time_position = prepare_source.index("precommit_time = _delivery_time(now)")
    assert (
        prepare_source.index("select(MediaArtifact)")
        < initial_time_position
        < store_open_position
        < final_time_position
        < delivery_create_position
        < first_flush_position
        < precommit_time_position
    )
    assert "started_at=final_time" in prepare_source
    assert "final_time + timedelta" in prepare_source
    assert "delivery.started_at = precommit_time" in prepare_source
    assert "precommit_time + timedelta" in prepare_source
    assert "_rollback_session_best_effort(session)" in prepare_source
    _locked_artifact_precedes_locked_delivery(
        delivery._load_committed_media_artifact_delivery_snapshot
    )
    _locked_artifact_precedes_locked_delivery(
        delivery.discard_pristine_media_artifact_delivery_best_effort
    )
    _locked_artifact_precedes_locked_delivery(delivery._complete_media_artifact_delivery)
    _locked_artifact_precedes_locked_delivery(delivery.acknowledge_media_artifact_delivery)

    ack_source = inspect.getsource(delivery.acknowledge_media_artifact_delivery)
    assert ack_source.index("delivery_scope = session.execute(") < ack_source.index(
        "artifact = session.scalar("
    )
    assert (
        ".with_for_update()"
        not in ack_source[
            ack_source.index("delivery_scope = session.execute(") : ack_source.index(
                "artifact = session.scalar("
            )
        ]
    )
    assert ack_source.index("if delivery.acked_at is not None:") < ack_source.index(
        'artifact.status != "available"'
    )


def test_stream_completion_has_explicit_scope_and_owns_short_transaction() -> None:
    parameters = inspect.signature(delivery.iter_verified_delivery_chunks).parameters
    assert {"database_url", "artifact_id", "site_id", "delivery_id"} <= set(parameters)
    completion_source = inspect.getsource(delivery._complete_media_artifact_delivery)
    assert "with get_session(database_url) as session:" in completion_source
    assert "session.commit()" in completion_source
    assert "artifact.expires_at" not in completion_source
    assert "delivery.expected_byte_size != byte_size" in completion_source
    assert "delivery.expected_checksum != checksum" in completion_source

    route_source = inspect.getsource(media_routes._prepare_signed_delivery)
    assert (
        route_source.index("session.commit()")
        < route_source.index("session_context.__exit__(")
        < route_source.index("revalidate_committed_media_artifact_delivery(")
        < route_source.index("return prepared")
    )
    rejection_position = route_source.index("except MediaArtifactDeliveryError as error:")
    close_position = route_source.index("prepared.stream.close()", rejection_position)
    discard_position = route_source.index(
        "discard_pristine_media_artifact_delivery_best_effort(",
        rejection_position,
    )
    assert rejection_position < close_position < discard_position
    assert "except BaseException:" in route_source

    revalidation_source = inspect.getsource(
        delivery.revalidate_committed_media_artifact_delivery
    )
    assert revalidation_source.index(
        "_load_committed_media_artifact_delivery_snapshot("
    ) < revalidation_source.index("final_time = _delivery_time(now)")
    assert revalidation_source.index(
        "_ensure_committed_delivery_can_be_exposed("
    ) < revalidation_source.index("if loaded.exit_error is None:")
    decision_source = inspect.getsource(delivery._ensure_committed_delivery_can_be_exposed)
    assert decision_source.index("snapshot.artifact_status") < decision_source.index(
        "snapshot.delivery_completed_at"
    )
    ack_route_source = inspect.getsource(media_routes._acknowledge_signed_delivery)
    assert "with get_session(database_url) as session:" in ack_route_source
    assert ack_route_source.index("session.commit()") < ack_route_source.index("return data")


def test_lifecycle_claim_and_finalize_are_atomic_cas_with_ordered_revocation() -> None:
    cleanup_source = inspect.getsource(MediaArtifactLifecycleService.cleanup_expired_artifacts)
    claim_call_position = cleanup_source.index(
        "claims, stale_claims_reclaimed = self._claim_batch("
    )
    claim_error_position = cleanup_source.index(
        "raise MediaArtifactLifecycleError() from None",
        claim_call_position,
    )
    assert claim_call_position < claim_error_position
    assert "except Exception:" in cleanup_source[claim_call_position:claim_error_position]

    claim_source = inspect.getsource(MediaArtifactLifecycleService._claim_batch)
    assert "update(MediaArtifact)" in claim_source
    claim_update_position = claim_source.index("update(MediaArtifact)")
    delivery_lock_position = claim_source.index("select(MediaArtifactDelivery)")
    assert claim_update_position < delivery_lock_position
    assert ".order_by(MediaArtifactDelivery.delivery_id.asc())" in claim_source
    assert ".with_for_update()" in claim_source[delivery_lock_position:]
    assert claim_source.index("session.flush()") < claim_source.index(
        "purge_claim_expires_at=refreshed_expiry"
    ) < claim_source.index("session.commit()")
    for predicate in (
        "MediaArtifact.expires_at <= now",
        "MediaArtifact.purged_at.is_(None)",
        'MediaArtifact.status != "purged"',
        "MediaArtifact.purge_next_attempt_at <= now",
        "MediaArtifact.purge_claim_expires_at <= now",
    ):
        assert claim_source.count(predicate) >= 2

    success_source = inspect.getsource(MediaArtifactLifecycleService._finalize_success)
    failure_source = inspect.getsource(MediaArtifactLifecycleService._finalize_failure)
    for source in (success_source, failure_source):
        assert "update(MediaArtifact)" in source
        assert "MediaArtifact.artifact_id == claim.artifact_id" in source
        assert "MediaArtifact.purge_claim_id == claim.claim_id" in source
        assert "MediaArtifact.purged_at.is_(None)" in source
        assert 'MediaArtifact.status == "purge_pending"' in source
        assert "result.rowcount == 1" in source


def test_old_media_derivative_cleanup_implementation_is_completely_removed() -> None:
    old_source = (ROOT / "app/domain/media_derivatives/artifacts.py").read_text(encoding="utf-8")
    assert "cleanup_expired_artifacts" not in old_source
    assert "_PURGE_RETRY_BASE_SECONDS" not in old_source
    assert "_PURGE_RETRY_MAX_SECONDS" not in old_source
