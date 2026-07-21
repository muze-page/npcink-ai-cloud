from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.auth import authorize_internal_request
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import CloudServices
from tests.conftest import TEST_INTERNAL_AUTH_TOKEN


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'internal-auth-replay.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient, dict[str, int]]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Internal Auth Replay Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    app = FastAPI()
    app.state.services = CloudServices(settings=settings)
    calls = {"put": 0, "post": 0, "get": 0, "head": 0}

    @app.put("/internal/test-resource")
    async def update_resource(request: Request) -> Any:
        auth_error = await authorize_internal_request(
            request,
            require_idempotency=True,
        )
        if auth_error is not None:
            return auth_error
        calls["put"] += 1
        return {"status": "updated"}

    @app.post("/internal/test-resource")
    async def create_resource(request: Request) -> Any:
        auth_error = await authorize_internal_request(
            request,
            require_idempotency=True,
        )
        if auth_error is not None:
            return auth_error
        calls["post"] += 1
        return {"status": "created"}

    @app.get("/internal/test-resource")
    async def get_resource(request: Request) -> Any:
        auth_error = await authorize_internal_request(
            request,
            require_idempotency=False,
        )
        if auth_error is not None:
            return auth_error
        calls["get"] += 1
        return {"status": "loaded"}

    @app.head("/internal/test-resource")
    async def head_resource(request: Request) -> Any:
        auth_error = await authorize_internal_request(
            request,
            require_idempotency=False,
        )
        if auth_error is not None:
            return auth_error
        calls["head"] += 1
        return {"status": "loaded"}

    return database_url, TestClient(app), calls


def _headers(*, idempotency_key: str) -> dict[str, str]:
    return {
        "X-Npcink-Internal-Token": TEST_INTERNAL_AUTH_TOKEN,
        "Idempotency-Key": idempotency_key,
    }


def test_internal_put_replay_is_blocked_before_handler_runs_twice(tmp_path: Path) -> None:
    database_url, client, calls = _build_client(tmp_path)
    headers = _headers(idempotency_key="internal-put-replay-001")
    try:
        first = client.put("/internal/test-resource", json={"enabled": True}, headers=headers)
        replay = client.put(
            "/internal/test-resource",
            json={"enabled": True},
            headers=headers,
        )

        assert first.status_code == 200
        assert replay.status_code == 409
        assert replay.json()["error_code"] == "auth.replay_blocked"
        assert calls["put"] == 1
    finally:
        client.close()
        dispose_engine(database_url)


def test_internal_post_replay_remains_blocked(tmp_path: Path) -> None:
    database_url, client, calls = _build_client(tmp_path)
    headers = _headers(idempotency_key="internal-post-replay-001")
    try:
        first = client.post("/internal/test-resource", json={}, headers=headers)
        replay = client.post("/internal/test-resource", json={}, headers=headers)

        assert first.status_code == 200
        assert replay.status_code == 409
        assert replay.json()["error_code"] == "auth.replay_blocked"
        assert calls["post"] == 1
    finally:
        client.close()
        dispose_engine(database_url)


def test_internal_reads_do_not_reserve_write_replay_receipts(tmp_path: Path) -> None:
    database_url, client, calls = _build_client(tmp_path)
    headers = _headers(idempotency_key="internal-read-repeat-001")
    try:
        get_first = client.get("/internal/test-resource", headers=headers)
        get_second = client.get("/internal/test-resource", headers=headers)
        head_first = client.head("/internal/test-resource", headers=headers)
        head_second = client.head("/internal/test-resource", headers=headers)

        assert get_first.status_code == 200
        assert get_second.status_code == 200
        assert head_first.status_code == 200
        assert head_second.status_code == 200
        assert calls["get"] == 2
        assert calls["head"] == 2
    finally:
        client.close()
        dispose_engine(database_url)
