from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.adapters.repositories.addon_projection_repository import AddonProjectionRepository
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ServiceAuditEvent
from app.domain.addon_projection.service import (
    ADDON_OVERVIEW_PROJECTION_KIND,
    PROVIDER_RELEASE_SUMMARY_PROJECTION_KIND,
    AddonProjectionService,
)
from app.domain.catalog.service import CatalogService
from app.workers.addon_overview_projection import run_once as run_addon_overview_projection
from app.workers.provider_release_summary_projection import (
    run_once as run_provider_release_summary_projection,
)
from tests.conftest import seed_site_auth


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'addon-projection-worker.sqlite3'}"


def _settings(database_url: str) -> Settings:
    return Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        provider_connection_secret="p" * 32,
    )


def test_addon_projection_service_generates_overview_and_provider_summary(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    service = AddonProjectionService(
        database_url=database_url,
        settings=_settings(database_url),
        now_factory=lambda: datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
    )

    overview_result = service.refresh_addon_overview_projections(site_ids=["site_alpha"])
    provider_result = service.refresh_provider_release_summary_projections(site_ids=["site_alpha"])

    assert overview_result["stored_total"] == 1
    assert provider_result["stored_total"] == 1

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        overview = repository.get_projection(
            site_id="site_alpha",
            projection_kind=ADDON_OVERVIEW_PROJECTION_KIND,
        )
        provider = repository.get_projection(
            site_id="site_alpha",
            projection_kind=PROVIDER_RELEASE_SUMMARY_PROJECTION_KIND,
        )
        assert overview is not None
        assert provider is not None
        assert overview.payload_json["site"]["site_id"] == "site_alpha"
        assert isinstance(provider.payload_json["items"], list)

    dispose_engine(database_url)


def test_addon_projection_service_records_projection_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])

    service = AddonProjectionService(
        database_url=database_url,
        settings=_settings(database_url),
        now_factory=lambda: datetime(2026, 4, 15, 10, 30, tzinfo=UTC),
    )

    def fail(*args, **kwargs):
        raise RuntimeError("projection blew up")

    monkeypatch.setattr(service, "_build_provider_release_summary_payload", fail)

    result = service.refresh_provider_release_summary_projections(site_ids=["site_alpha"])

    assert result["stored_total"] == 0
    assert result["error_total"] == 1

    with get_session(database_url) as session:
        repository = AddonProjectionRepository(session)
        stored = repository.get_projection(
            site_id="site_alpha",
            projection_kind=PROVIDER_RELEASE_SUMMARY_PROJECTION_KIND,
        )
        assert stored is not None
        assert stored.last_error == "projection blew up"
        assert stored.last_error_at is not None
        assert stored.last_error_at.replace(tzinfo=UTC) == datetime(2026, 4, 15, 10, 30, tzinfo=UTC)
        assert stored.fresh_until.replace(tzinfo=UTC) == datetime(2026, 4, 15, 10, 30, tzinfo=UTC)

    dispose_engine(database_url)


def test_addon_projection_service_prioritizes_recently_active_sites(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(database_url, site_id="site_idle", scopes=["stats:read"])
    seed_site_auth(database_url, site_id="site_old", scopes=["stats:read"])
    seed_site_auth(database_url, site_id="site_recent", scopes=["stats:read"])

    with get_session(database_url) as session:
        session.add_all(
            [
                ServiceAuditEvent(
                    site_id="site_old",
                    event_kind="runtime.execute",
                    outcome="succeeded",
                    created_at=datetime(2026, 4, 10, 8, 0, tzinfo=UTC),
                ),
                ServiceAuditEvent(
                    site_id="site_recent",
                    event_kind="runtime.execute",
                    outcome="succeeded",
                    created_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
                ),
            ]
        )
        session.commit()

    service = AddonProjectionService(
        database_url=database_url,
        settings=_settings(database_url),
        now_factory=lambda: datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
    )

    assert service.list_target_site_ids() == ["site_recent", "site_old", "site_idle"]

    dispose_engine(database_url)


def test_projection_workers_expose_dedicated_run_once_entrypoints(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    CatalogService(database_url).scan_provider_health()
    seed_site_auth(database_url, site_id="site_alpha", scopes=["stats:read"])
    settings = _settings(database_url)

    overview_result = run_addon_overview_projection(settings, site_ids=["site_alpha"])
    provider_result = run_provider_release_summary_projection(settings, site_ids=["site_alpha"])

    assert overview_result["stored_total"] == 1
    assert provider_result["stored_total"] == 1

    dispose_engine(database_url)
