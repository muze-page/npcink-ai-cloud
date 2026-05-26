from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ReplayReceipt, RuntimeGuardEvent
from app.core.security import REPLAY_SCOPE_PUBLIC_POST_SITE
from app.domain.catalog.service import CatalogService
from app.domain.runtime.service import RuntimeService


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'runtime-abuse-guard.sqlite3'}"


def test_abuse_guard_diagnostics_exposes_watchlist_and_event_breakdown(tmp_path: Path) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()

    with get_session(database_url) as session:
        for index in range(5):
            session.add(
                ReplayReceipt(
                    scope_kind=REPLAY_SCOPE_PUBLIC_POST_SITE,
                    scope_id="site_watch",
                    replay_key=f"watch-burst-{index}",
                    method="POST",
                    path="/v1/runtime/execute",
                    trace_id=f"trace-watch-burst-{index}",
                    created_at=datetime.now(UTC) - timedelta(minutes=1),
                    expires_at=datetime.now(UTC) + timedelta(minutes=9),
                )
            )
        for index in range(3):
            session.add(
                RuntimeGuardEvent(
                    auth_surface="public_runtime",
                    scope_kind=REPLAY_SCOPE_PUBLIC_POST_SITE,
                    scope_id="site_watch",
                    site_id="site_watch",
                    key_id="key_watch",
                    client_ref="127.0.0.1",
                    event_code="auth.rate_limit_exceeded" if index < 2 else "auth.replay_blocked",
                    status_code=429 if index < 2 else 409,
                    method="POST",
                    path="/v1/runtime/execute",
                    trace_id=f"trace-watch-guard-{index}",
                    payload_json={"source": "domain_test"},
                    created_at=datetime.now(UTC) - timedelta(minutes=2),
                )
            )
        session.commit()

    payload = RuntimeService(database_url).get_abuse_guard_diagnostics(
        window_seconds=600,
        cooldown_window_seconds=1800,
        limit_per_scope=5,
        public_post_site_limit=4,
        public_post_key_limit=10,
        public_post_ip_limit=10,
        public_guard_site_cooldown_limit=2,
        public_guard_key_cooldown_limit=10,
        public_guard_ip_cooldown_limit=10,
        internal_post_token_limit=10,
        internal_post_ip_limit=10,
        internal_guard_token_cooldown_limit=10,
        internal_guard_ip_cooldown_limit=10,
    )

    assert payload["watchlist_summary"]["highest_severity"] == "critical"
    assert payload["watchlist_summary"]["critical_count"] >= 2
    site_scope = payload["scopes"][REPLAY_SCOPE_PUBLIC_POST_SITE]
    assert site_scope["request_pressure"]["highest_severity"] == "critical"
    assert site_scope["cooldown_pressure"]["highest_severity"] == "critical"
    request_item = site_scope["items"][0]
    assert request_item["scope_id"] == "site_watch"
    assert request_item["severity"] == "critical"
    assert "request_burst_limit_exceeded" in request_item["reason_codes"]
    cooldown_item = site_scope["cooldown_items"][0]
    assert cooldown_item["scope_id"] == "site_watch"
    assert cooldown_item["severity"] == "critical"
    assert "rejects_include_rate_limits" in cooldown_item["reason_codes"]
    assert any(
        item["event_code"] == "auth.replay_blocked"
        for item in cooldown_item["event_code_breakdown"]
    )
    assert any(
        item["scope_kind"] == REPLAY_SCOPE_PUBLIC_POST_SITE
        and item["scope_id"] == "site_watch"
        and item["signal_kind"] == "request_burst"
        for item in payload["watchlist"]
    )

    dispose_engine(database_url)
