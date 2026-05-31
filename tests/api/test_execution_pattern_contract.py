from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.services import CloudServices
from app.domain.catalog.service import CatalogService
from tests.conftest import (
    TEST_INTERNAL_AUTH_TOKEN,
    build_auth_headers,
    merge_json_headers,
    seed_site_auth,
)


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'pattern-contract.sqlite3'}"


def _build_client(tmp_path: Path) -> tuple[str, TestClient]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    CatalogService(database_url).refresh_catalog()
    seed_site_auth(
        database_url,
        site_id="site_pattern",
        key_id="key_pattern",
        secret="pattern-secret-32-chars-long-enough!!",
        scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
    )
    settings = Settings(
        project_name="Magick AI Cloud Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
    )
    return database_url, TestClient(
        create_app(CloudServices(settings=settings, providers={}))
    )


def test_orchestrated_execution_pattern_rejected_by_schema(tmp_path: Path):
    database_url, client = _build_client(tmp_path)
    try:
        body = b'{"ability_name":"test.ability","execution_kind":"text","profile_id":"text.balanced","execution_pattern":"orchestrated","input":{"text":"hello"}}'
        headers = merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_pattern",
                key_id="key_pattern",
                secret="pattern-secret-32-chars-long-enough!!",
                idempotency_key="idem-orch-schema-001",
                nonce="nonce-orch-schema-001",
                body=body,
            )
        )
        response = client.post(
            "/v1/runtime/execute",
            content=body,
            headers=headers,
        )
        assert response.status_code == 422
    finally:
        dispose_engine(database_url)


def test_inline_execution_pattern_accepted(tmp_path: Path):
    database_url, client = _build_client(tmp_path)
    try:
        body = b'{"ability_name":"test.ability","execution_kind":"text","profile_id":"text.balanced","execution_pattern":"inline","input":{"text":"hello"}}'
        headers = merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_pattern",
                key_id="key_pattern",
                secret="pattern-secret-32-chars-long-enough!!",
                idempotency_key="idem-inline-accept-001",
                nonce="nonce-inline-accept-001",
                body=body,
            )
        )
        response = client.post(
            "/v1/runtime/execute",
            content=body,
            headers=headers,
        )
        assert response.status_code in {200, 201}
    finally:
        dispose_engine(database_url)


def test_whole_run_offload_accepted_with_task_backend(tmp_path: Path):
    database_url, client = _build_client(tmp_path)
    try:
        body = b'{"ability_name":"test.ability","execution_kind":"text","profile_id":"text.balanced","execution_pattern":"whole_run_offload","task_backend":{"enabled":true},"input":{"text":"hello"}}'
        headers = merge_json_headers(
            build_auth_headers(
                "POST",
                "/v1/runtime/execute",
                site_id="site_pattern",
                key_id="key_pattern",
                secret="pattern-secret-32-chars-long-enough!!",
                idempotency_key="idem-offload-accept-001",
                nonce="nonce-offload-accept-001",
                body=body,
            )
        )
        response = client.post(
            "/v1/runtime/execute",
            content=body,
            headers=headers,
        )
        assert response.status_code in {200, 201, 202}
    finally:
        dispose_engine(database_url)


def test_openapi_schema_execution_pattern_excludes_orchestrated(tmp_path: Path):
    database_url, client = _build_client(tmp_path)
    try:
        schema = client.get("/openapi.json").json()
        runtime_payload = schema.get("components", {}).get("schemas", {}).get("RuntimePayload", {})
        pattern_prop = runtime_payload.get("properties", {}).get("execution_pattern", {})
        enum_values = pattern_prop.get("enum", [])
        assert "orchestrated" not in enum_values
        assert set(enum_values) == {"inline", "whole_run_offload"}
    finally:
        dispose_engine(database_url)
