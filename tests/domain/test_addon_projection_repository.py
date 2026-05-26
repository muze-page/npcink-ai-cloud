from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.adapters.repositories.addon_projection_repository import AddonProjectionRepository
from app.core.db import dispose_engine, get_session, init_schema


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'addon-projection-repository.sqlite3'}"


def test_addon_projection_repository_upserts_and_overwrites_latest_projection(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    first_now = datetime(2026, 4, 15, 8, 0, tzinfo=UTC)

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        repository.upsert_projection(
            site_id="site_alpha",
            projection_kind="addon_overview",
            payload_json={"site": {"site_id": "site_alpha"}, "version": 1},
            generated_at=first_now,
            fresh_until=first_now + timedelta(seconds=120),
            source_revision="addon_projection_v1",
            generation_ms=42,
        )
        session.commit()

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        stored = repository.get_projection(site_id="site_alpha", projection_kind="addon_overview")
        assert stored is not None
        assert stored.payload_json["version"] == 1
        assert stored.generation_ms == 42

        repository.upsert_projection(
            site_id="site_alpha",
            projection_kind="addon_overview",
            payload_json={"site": {"site_id": "site_alpha"}, "version": 2},
            generated_at=first_now + timedelta(minutes=5),
            fresh_until=first_now + timedelta(minutes=5, seconds=120),
            source_revision="addon_projection_v1",
            generation_ms=18,
        )
        session.commit()

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        stored = repository.get_projection(site_id="site_alpha", projection_kind="addon_overview")
        assert stored is not None
        assert stored.payload_json["version"] == 2
        assert stored.generation_ms == 18

    dispose_engine(database_url)


def test_addon_projection_repository_reads_missing_and_error_metadata(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    error_at = datetime(2026, 4, 15, 9, 0, tzinfo=UTC)

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        assert (
            repository.get_projection(
                site_id="site_missing",
                projection_kind="provider_release_summary",
            )
            is None
        )
        repository.record_projection_error(
            site_id="site_alpha",
            projection_kind="provider_release_summary",
            message="simulated projection failure",
            error_at=error_at,
            source_revision="addon_projection_v1",
        )
        session.commit()

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        stored = repository.get_projection(
            site_id="site_alpha",
            projection_kind="provider_release_summary",
        )
        assert stored is not None
        assert stored.last_error == "simulated projection failure"
        assert stored.last_error_at is not None
        assert stored.last_error_at.replace(tzinfo=UTC) == error_at

    dispose_engine(database_url)
