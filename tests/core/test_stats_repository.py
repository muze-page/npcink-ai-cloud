from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.adapters.repositories.stats_repository import StatsRepository
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import HealthSnapshot


def test_list_latest_health_snapshots_returns_one_row_per_instance(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'stats-repository.sqlite3'}"
    init_schema(database_url)
    measured_at = datetime(2026, 7, 11, 1, 0, tzinfo=UTC)

    with get_session(database_url) as session:
        session.add_all(
            [
                HealthSnapshot(
                    provider_id="provider-a",
                    instance_id="instance-a",
                    status="healthy",
                    reason="initial",
                    measured_at=measured_at,
                ),
                HealthSnapshot(
                    provider_id="provider-a",
                    instance_id="instance-a",
                    status="degraded",
                    reason="latest first write",
                    measured_at=measured_at + timedelta(minutes=1),
                ),
                HealthSnapshot(
                    provider_id="provider-a",
                    instance_id="instance-a",
                    status="unhealthy",
                    reason="latest tie breaker",
                    measured_at=measured_at + timedelta(minutes=1),
                ),
                HealthSnapshot(
                    provider_id="provider-b",
                    instance_id="instance-b",
                    status="healthy",
                    reason="only snapshot",
                    measured_at=measured_at,
                ),
                HealthSnapshot(
                    provider_id="provider-unknown",
                    instance_id=None,
                    status="unknown",
                    reason="not attached to an instance",
                    measured_at=measured_at + timedelta(minutes=2),
                ),
            ]
        )
        session.commit()

        repository = StatsRepository(session)
        latest = repository.list_latest_health_snapshots()
        filtered = repository.list_latest_health_snapshots(["instance-a"])
        empty = repository.list_latest_health_snapshots([])

    assert [(item.instance_id, item.status) for item in latest] == [
        ("instance-a", "unhealthy"),
        ("instance-b", "healthy"),
    ]
    assert [(item.instance_id, item.status) for item in filtered] == [("instance-a", "unhealthy")]
    assert empty == []

    dispose_engine(database_url)
