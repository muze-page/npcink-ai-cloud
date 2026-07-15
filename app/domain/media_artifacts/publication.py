from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import BinaryIO

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import SessionTransaction

from app.domain.media_artifacts.store import (
    ArtifactStorageMetadata,
    ArtifactStore,
    ArtifactStoreError,
    ArtifactStorePublicationUncertainError,
)

_LOGGER = logging.getLogger(__name__)
_TRACKER_KEY = "media_artifact_publication_tracker.v1"
_OUTCOME_KEY = "media_artifact_publication_outcome.v1"
_QUARANTINE_KEY = "media_artifact_publication_quarantine.v1"
_LISTENERS_KEY = "media_artifact_publication_listeners.v1"
_CONNECTION_COMMIT_LISTENER_KEY = "media_artifact_publication_connection_commit_listener.v1"

PublicationCleanupErrorFactory = Callable[[tuple[str, ...]], BaseException]


class ArtifactPublicationCleanupUncertainError(ArtifactStoreError):
    error_code = "media_artifact.publication_cleanup_uncertain"

    def __init__(self, storage_keys: Iterable[str]) -> None:
        super().__init__("artifact publication rollback cleanup is uncertain")
        self.storage_keys = tuple(dict.fromkeys(str(key) for key in storage_keys))


def artifact_publication_cleanup_error(
    storage_keys: tuple[str, ...],
) -> BaseException:
    return ArtifactPublicationCleanupUncertainError(storage_keys)


@dataclass(frozen=True, slots=True)
class _TrackedPublication:
    store: ArtifactStore
    storage_key: str
    cleanup_error_factory: PublicationCleanupErrorFactory


def publish_and_track_artifact(
    session: Session,
    *,
    store: ArtifactStore,
    stream: BinaryIO,
    max_bytes: int,
    metadata: Mapping[str, str] | None = None,
    cleanup_error_factory: PublicationCleanupErrorFactory = (
        artifact_publication_cleanup_error
    ),
) -> ArtifactStorageMetadata:
    """Publish an object and bind it to the outer DB transaction outcome.

    A caller that owns a nested savepoint must explicitly clean publications
    when that savepoint rolls back, then forget successful deletes and
    quarantine failed deletes. The generic tracker resolves only the outer
    transaction boundary.
    """

    _ensure_session_transaction(session)
    try:
        stored = store.put(stream, max_bytes=max_bytes, metadata=metadata)
    except ArtifactStorePublicationUncertainError as error:
        track_artifact_publication(
            session,
            store=store,
            storage_key=error.storage_metadata.storage_key,
            cleanup_error_factory=cleanup_error_factory,
        )
        raise
    track_artifact_publication(
        session,
        store=store,
        storage_key=stored.storage_key,
        cleanup_error_factory=cleanup_error_factory,
    )
    return stored


def track_artifact_publication(
    session: Session,
    *,
    store: ArtifactStore,
    storage_key: str,
    cleanup_error_factory: PublicationCleanupErrorFactory = (
        artifact_publication_cleanup_error
    ),
) -> None:
    """Delete a newly published object if the owning DB transaction rolls back.

    Artifact stores publish before the MediaArtifact row can be committed. This
    session-local tracker closes that ordinary rollback window without making
    the store implementation transaction-aware.
    """

    _ensure_session_transaction(session)
    tracker = _tracker(session)
    if not bool(session.info.get(_LISTENERS_KEY)):
        _install_session_listeners(session)
        session.info[_LISTENERS_KEY] = True
    publication = _TrackedPublication(
        store=store,
        storage_key=storage_key,
        cleanup_error_factory=cleanup_error_factory,
    )
    if not _contains_publication(tracker, publication):
        tracker.append(publication)


def forget_artifact_publications(
    session: Session,
    *,
    store: ArtifactStore,
    storage_keys: Iterable[str],
) -> None:
    """Forget matching active publications owned by this exact store instance."""

    forgotten = {str(storage_key) for storage_key in storage_keys}
    if not forgotten:
        return
    _forget_publications(
        session,
        publications=(
            item
            for item in _tracker(session)
            if item.store is store and item.storage_key in forgotten
        ),
    )


def quarantine_artifact_publications(
    session: Session,
    *,
    store: ArtifactStore,
    storage_keys: Iterable[str],
) -> tuple[str, ...]:
    """Quarantine matching publications owned by this exact store instance."""

    quarantined_keys = {str(storage_key) for storage_key in storage_keys}
    if not quarantined_keys:
        return ()
    return _quarantine_publications(
        session,
        publications=(
            item
            for item in _tracker(session)
            if item.store is store and item.storage_key in quarantined_keys
        ),
    )


def _forget_publications(
    session: Session,
    *,
    publications: Iterable[_TrackedPublication],
) -> None:
    forgotten = tuple(publications)
    if not forgotten:
        return
    session.info[_TRACKER_KEY] = [
        item for item in _tracker(session) if not _contains_publication(forgotten, item)
    ]


def _quarantine_publications(
    session: Session,
    *,
    publications: Iterable[_TrackedPublication],
) -> tuple[str, ...]:
    requested = tuple(publications)
    if not requested:
        return ()
    active = tuple(_tracker(session))
    moving = tuple(
        item for item in active if _contains_publication(requested, item)
    )
    if not moving:
        return ()
    uncertain = list(_quarantined_publications(session))
    for publication in moving:
        if not _contains_publication(uncertain, publication):
            uncertain.append(publication)
    session.info[_QUARANTINE_KEY] = tuple(uncertain)
    session.info[_TRACKER_KEY] = [
        item for item in active if not _contains_publication(moving, item)
    ]
    return tuple(dict.fromkeys(item.storage_key for item in moving))


def tracked_artifact_storage_keys(session: Session) -> tuple[str, ...]:
    return tuple(item.storage_key for item in _tracker(session))


def uncertain_artifact_storage_keys(session: Session) -> tuple[str, ...]:
    """Return opaque keys held by the Session-local no-delete quarantine."""

    return tuple(
        dict.fromkeys(item.storage_key for item in _quarantined_publications(session))
    )


def _tracker(session: Session) -> list[_TrackedPublication]:
    value = session.info.setdefault(_TRACKER_KEY, [])
    assert isinstance(value, list)
    return value


def _quarantined_publications(session: Session) -> tuple[_TrackedPublication, ...]:
    value = session.info.get(_QUARANTINE_KEY, ())
    assert isinstance(value, tuple)
    return value


def _contains_publication(
    publications: Iterable[_TrackedPublication],
    candidate: _TrackedPublication,
) -> bool:
    return any(
        item.store is candidate.store and item.storage_key == candidate.storage_key
        for item in publications
    )


def _ensure_session_transaction(session: Session) -> None:
    if not session.in_transaction():
        session.begin()
    # Acquiring the Connection before publication validates that the current
    # transaction is usable and guarantees rollback/commit events will fire.
    session.connection()


def _install_session_listeners(session: Session) -> None:
    event.listen(session, "before_commit", _before_commit)
    event.listen(session, "after_commit", _after_commit)
    event.listen(session, "after_rollback", _after_rollback)
    event.listen(session, "after_transaction_end", _after_transaction_end)


def _before_commit(session: Session) -> None:
    if session.in_nested_transaction() or not _tracker(session):
        return
    session.info[_OUTCOME_KEY] = "commit_requested"
    _remove_connection_commit_listener(session)
    connection = session.connection()

    def _mark_db_commit_started(commit_connection: Connection) -> None:
        listener_state = session.info.get(_CONNECTION_COMMIT_LISTENER_KEY)
        if (
            isinstance(listener_state, tuple)
            and len(listener_state) == 2
            and listener_state[0] is commit_connection
            and listener_state[1] is _mark_db_commit_started
        ):
            session.info[_OUTCOME_KEY] = "commit_started"

    event.listen(connection, "commit", _mark_db_commit_started, once=True)
    session.info[_CONNECTION_COMMIT_LISTENER_KEY] = (
        connection,
        _mark_db_commit_started,
    )


def _after_commit(session: Session) -> None:
    if not session.in_nested_transaction():
        session.info[_OUTCOME_KEY] = "committed"


def _after_rollback(session: Session) -> None:
    if (
        not session.in_nested_transaction()
        and session.info.get(_OUTCOME_KEY) != "commit_started"
    ):
        session.info[_OUTCOME_KEY] = "rolled_back"


def _after_transaction_end(
    session: Session,
    transaction: SessionTransaction,
) -> None:
    if transaction.parent is not None:
        return

    _remove_connection_commit_listener(session)
    publications = tuple(_tracker(session))
    if not publications:
        session.info.pop(_OUTCOME_KEY, None)
        return
    outcome = str(session.info.pop(_OUTCOME_KEY, ""))
    if outcome == "committed":
        session.info[_TRACKER_KEY] = []
        return
    if outcome == "commit_started":
        # The DBAPI commit call began but SQLAlchemy never observed a definitive
        # outcome. A recovery rollback cannot prove that the database did not
        # commit, so these objects must leave the active cleanup tracker.
        _quarantine_publications(
            session,
            publications=publications,
        )
        _LOGGER.critical(
            "artifact publication commit outcome is uncertain; orphan reconciliation required",
            extra={"artifact_count": len(_quarantined_publications(session))},
        )
        return

    failed: list[_TrackedPublication] = []
    deleted: list[_TrackedPublication] = []
    for publication in publications:
        try:
            publication.store.delete(publication.storage_key)
            deleted.append(publication)
        except Exception:
            failed.append(publication)
    _forget_publications(session, publications=deleted)
    if failed:
        storage_keys = tuple(item.storage_key for item in failed)
        _quarantine_publications(session, publications=failed)
        _LOGGER.critical(
            "artifact rollback cleanup is uncertain",
            extra={"artifact_count": len(failed)},
        )
        raise failed[0].cleanup_error_factory(storage_keys)


def _remove_connection_commit_listener(session: Session) -> None:
    value = session.info.pop(_CONNECTION_COMMIT_LISTENER_KEY, None)
    if not isinstance(value, tuple) or len(value) != 2:
        return
    connection, listener = value
    try:
        if event.contains(connection, "commit", listener):
            event.remove(connection, "commit", listener)
    except Exception:
        # Publication state handling must still finish for an invalidated
        # Connection. The callback's exact-state guard makes a leaked listener
        # a no-op if the Session later enters another transaction.
        _LOGGER.exception("artifact publication commit listener removal failed")
