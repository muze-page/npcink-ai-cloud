from __future__ import annotations

import os
import socket
from datetime import UTC, datetime

import jwt
import pytest
from sqlalchemy import select

os.environ["NPCINK_CLOUD_INTERNAL_AUTH_TOKEN"] = "npcink-cloud-internal-test-token-32b"
os.environ["NPCINK_CLOUD_ADMIN_SESSION_SECRET"] = "npcink-cloud-ops-session-secret-32b"
os.environ["NPCINK_CLOUD_PORTAL_JWT_SECRET"] = "npcink-cloud-portal-jwt-secret-32b"
for _provider_env_name in (
    "NPCINK_CLOUD_OPENAI_API_KEY",
    "NPCINK_CLOUD_OPENAI_COMPATIBLE_API_KEY",
    "NPCINK_CLOUD_ANTHROPIC_API_KEY",
    "NPCINK_CLOUD_LITELLM_API_KEY",
    "NPCINK_CLOUD_VLLM_API_KEY",
    "NPCINK_CLOUD_TEI_API_KEY",
    "NPCINK_CLOUD_OPENROUTER_API_KEY",
    "NPCINK_CLOUD_SILICONFLOW_API_KEY",
    "NPCINK_CLOUD_WEB_SEARCH_TAVILY_API_KEY",
    "NPCINK_CLOUD_WEB_SEARCH_TAVILY_API_KEYS",
    "NPCINK_CLOUD_WEB_SEARCH_TAVILY_API_KEY_LABELS",
    "NPCINK_CLOUD_WEB_SEARCH_BOCHA_API_KEY",
    "NPCINK_CLOUD_WEB_SEARCH_JINA_READER_API_KEY",
    "NPCINK_CLOUD_WEB_SEARCH_APIFY_API_TOKEN",
):
    os.environ[_provider_env_name] = ""
os.environ["NPCINK_CLOUD_WEB_SEARCH_PROVIDER"] = "disabled"
os.environ["NPCINK_CLOUD_WEB_SEARCH_JINA_READER_ENABLED"] = "false"
for _provider_flag_name in (
    "NPCINK_CLOUD_LITELLM_PROVIDER_ENABLED",
    "NPCINK_CLOUD_VLLM_PROVIDER_ENABLED",
    "NPCINK_CLOUD_TEI_PROVIDER_ENABLED",
    "NPCINK_CLOUD_OPENROUTER_PROVIDER_ENABLED",
    "NPCINK_CLOUD_SILICONFLOW_PROVIDER_ENABLED",
):
    os.environ[_provider_flag_name] = "false"
os.environ["NPCINK_CLOUD_OPENAI_SAMPLE_CATALOG_PROFILE"] = ""
os.environ["NPCINK_CLOUD_OPENAI_COMPATIBLE_SAMPLE_CATALOG_PROFILE"] = ""
os.environ["NPCINK_CLOUD_SITE_KNOWLEDGE_EMBEDDING_PROVIDER"] = "deterministic"
os.environ["NPCINK_CLOUD_SITE_KNOWLEDGE_VECTOR_BACKEND"] = "postgres_json"
os.environ["NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT"] = ""

from app.core.config import Settings
from app.core.db import get_session
from app.core.models import (
    SITE_API_KEY_STATUS_ACTIVE,
    SITE_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_ACTIVE,
    AccountEntitlementSnapshot,
    AccountSubscription,
    PlanVersion,
    ProviderConnection,
    Site,
    SiteApiKey,
)
from app.core.secrets import encrypt_site_api_signing_secret
from app.core.security import (
    build_body_digest,
    build_canonical_request,
    build_hmac_signature,
    build_secret_hash,
)
from app.domain.commercial.service import CommercialService

TEST_SECRET = "npcink-cloud-test-secret-for-hmac-sha256-32b"
TEST_KEY_ID = "key_default"
TEST_INTERNAL_AUTH_TOKEN = "npcink-cloud-internal-test-token-32b"
TEST_ADMIN_SESSION_SECRET = "npcink-cloud-ops-session-secret-32b"
TEST_PORTAL_JWT_SECRET = "npcink-cloud-portal-jwt-secret-32b"


@pytest.fixture
def allow_example_callback_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    original_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(
        host: object,
        port: object,
        *args: object,
        **kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, object]]]:
        if str(host).lower().rstrip(".") == "example.com":
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", port or 443),
                )
            ]
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def seed_site_auth(
    database_url: str,
    *,
    site_id: str,
    key_id: str = TEST_KEY_ID,
    secret: str = TEST_SECRET,
    scopes: list[str] | None = None,
    site_status: str = SITE_STATUS_ACTIVE,
    key_status: str = SITE_API_KEY_STATUS_ACTIVE,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    subscription_status: str = SUBSCRIPTION_STATUS_ACTIVE,
    entitlements: dict[str, object] | None = None,
    budgets: dict[str, object] | None = None,
    concurrency: dict[str, object] | None = None,
    policy: dict[str, object] | None = None,
    site_metadata: dict[str, object] | None = None,
) -> None:
    CommercialService(
        database_url,
        settings=Settings(
            _env_file=None,
            environment="test",
            database_url=database_url,
            redis_url="redis://localhost:6379/0",
            internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
            admin_session_secret=TEST_ADMIN_SESSION_SECRET,
            portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        ),
    ).provision_runtime_baseline(
        site_id=site_id,
        key_id=key_id,
        secret=secret,
        site_name=site_id,
        scopes=scopes or [],
    )
    with get_session(database_url) as session:
        site = session.get(Site, site_id)
        assert site is not None
        site.name = site.name or site_id
        site.status = site_status
        if site_metadata is not None:
            site.metadata_json = site_metadata

        api_key = session.get(SiteApiKey, key_id)
        assert api_key is not None
        api_key.site_id = site_id
        api_key.secret_hash = build_secret_hash(secret)
        api_key.signing_secret_ciphertext = encrypt_site_api_signing_secret(
            secret,
            settings=Settings(
                _env_file=None,
                environment="test",
                database_url=database_url,
                redis_url="redis://localhost:6379/0",
                internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
                admin_session_secret=TEST_ADMIN_SESSION_SECRET,
                portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
            ),
        )
        api_key.scopes_json = scopes or []
        api_key.status = key_status
        api_key.expires_at = expires_at
        api_key.revoked_at = revoked_at

        subscription = session.scalar(
            select(AccountSubscription)
            .where(AccountSubscription.account_id == site.account_id)
            .order_by(AccountSubscription.created_at.desc())
        )
        if subscription is not None:
            subscription.status = subscription_status
            plan_version = session.get(PlanVersion, subscription.plan_version_id)
            if plan_version is not None and policy is not None:
                plan_version.policy_json = policy

        snapshot = session.scalar(
            select(AccountEntitlementSnapshot)
            .where(AccountEntitlementSnapshot.account_id == site.account_id)
            .order_by(
                AccountEntitlementSnapshot.generated_at.desc(),
                AccountEntitlementSnapshot.id.desc(),
            )
        )
        if snapshot is not None:
            if entitlements is not None:
                snapshot.entitlements_json = entitlements
            if budgets is not None:
                snapshot.budgets_json = budgets
            if concurrency is not None:
                snapshot.concurrency_json = concurrency
            if policy is not None:
                snapshot.policy_json = policy

        session.commit()


def seed_openai_model_allowlist(
    database_url: str,
    *,
    model_ids: list[str] | None = None,
    connection_id: str = "openai",
) -> None:
    seed_provider_model_allowlist(
        database_url,
        provider_id="openai",
        kind="openai_compatible",
        model_ids=model_ids or ["gpt-4.1-mini"],
        connection_id=connection_id,
        display_name="OpenAI",
        capability_ids=["text_generation"],
        runtime_profile_ids=["text.balanced"],
        base_url="https://api.openai.test/v1",
    )


def seed_provider_model_allowlist(
    database_url: str,
    *,
    provider_id: str,
    kind: str,
    model_ids: list[str],
    connection_id: str | None = None,
    display_name: str | None = None,
    capability_ids: list[str] | None = None,
    runtime_profile_ids: list[str] | None = None,
    base_url: str = "https://api.provider.test",
) -> None:
    effective_connection_id = connection_id or provider_id
    with get_session(database_url) as session:
        row = session.get(ProviderConnection, effective_connection_id)
        config_json = {
            "provider_id": provider_id,
            "kind": kind,
            "capability_ids": capability_ids or [],
            "runtime_profile_ids": runtime_profile_ids or [],
            "model_ids": model_ids,
        }
        if row is None:
            row = ProviderConnection(
                connection_id=effective_connection_id,
                provider_type=kind,
                display_name=display_name or provider_id,
                enabled=True,
                base_url=base_url,
                config_json=config_json,
                secret_ciphertext="configured-in-test",
                status="ready",
                source_role="execution_source",
                metadata_json={},
            )
            session.add(row)
        else:
            row.provider_type = kind
            row.display_name = row.display_name or display_name or provider_id
            row.enabled = True
            row.base_url = row.base_url or base_url
            row.config_json = config_json
            row.secret_ciphertext = row.secret_ciphertext or "configured-in-test"
            row.status = "ready"
            row.source_role = row.source_role or "execution_source"
            row.metadata_json = row.metadata_json or {}
        session.commit()


def build_traceparent(trace_id: str) -> str:
    normalized = trace_id.lower().replace("-", "")
    if len(normalized) != 32:
        normalized = normalized.ljust(32, "0")[:32]
    return f"00-{normalized}-0000000000000000-01"


def build_auth_headers(
    method: str,
    path: str,
    *,
    site_id: str,
    key_id: str = TEST_KEY_ID,
    secret: str = TEST_SECRET,
    body: bytes | None = None,
    idempotency_key: str = "",
    nonce: str = "",
    trace_id: str = "0123456789abcdef0123456789abcdef",
    timestamp: str | None = None,
    query: str = "",
) -> dict[str, str]:
    resolved_timestamp = timestamp or str(int(datetime.now(UTC).timestamp()))
    resolved_nonce = nonce or (f"nonce-{trace_id[:24]}" if method.upper() == "POST" else "")
    traceparent = build_traceparent(trace_id)
    payload = body or b""
    canonical_request = build_canonical_request(
        method=method,
        path=path,
        query=query,
        site_id=site_id,
        key_id=key_id,
        timestamp=resolved_timestamp,
        nonce=resolved_nonce,
        idempotency_key=idempotency_key,
        traceparent=traceparent,
        body_digest=build_body_digest(payload),
    )
    signature = build_hmac_signature(secret, canonical_request)

    headers = {
        "X-Npcink-Site-Id": site_id,
        "X-Npcink-Key-Id": key_id,
        "X-Npcink-Timestamp": resolved_timestamp,
        "X-Npcink-Signature": signature,
        "traceparent": traceparent,
    }
    if resolved_nonce:
        headers["X-Npcink-Nonce"] = resolved_nonce
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def merge_json_headers(
    auth_headers: dict[str, str],
    *,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers: dict[str, str] = {
        "content-type": "application/json",
        **auth_headers,
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers


def build_internal_headers(
    *,
    internal_token: str = TEST_INTERNAL_AUTH_TOKEN,
    idempotency_key: str = "",
    trace_id: str = "fedcba9876543210fedcba9876543210",
) -> dict[str, str]:
    headers = {
        "X-Npcink-Internal-Token": internal_token,
        "traceparent": build_traceparent(trace_id),
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def build_portal_headers(
    *,
    principal_id: str = "principal:portal-admin@example.com",
    session_version: int = 1,
    secret: str = TEST_PORTAL_JWT_SECRET,
    issuer: str | None = None,
    audience: str | None = None,
    expires_at: datetime | None = None,
    idempotency_key: str = "",
    trace_id: str = "00112233445566778899aabbccddeeff",
) -> dict[str, str]:
    headers = build_portal_bearer_headers(
        principal_id=principal_id,
        session_version=session_version,
        secret=secret,
        issuer=issuer,
        audience=audience,
        expires_at=expires_at,
        idempotency_key=idempotency_key,
        trace_id=trace_id,
    )
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers


def build_portal_bearer_headers(
    *,
    principal_id: str = "principal:portal-admin@example.com",
    session_version: int = 1,
    secret: str = TEST_PORTAL_JWT_SECRET,
    issuer: str | None = None,
    audience: str | None = None,
    expires_at: datetime | None = None,
    idempotency_key: str = "",
    trace_id: str = "00112233445566778899aabbccddeeff",
) -> dict[str, str]:
    payload: dict[str, object] = {
        "sub": principal_id,
        "session_version": int(session_version or 1),
    }
    if issuer:
        payload["iss"] = issuer
    if audience:
        payload["aud"] = audience
    if expires_at is not None:
        payload["exp"] = expires_at
    token = jwt.encode(payload, secret, algorithm="HS256")
    headers = {
        "Authorization": f"Bearer {token}",
        "traceparent": build_traceparent(trace_id),
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    return headers
