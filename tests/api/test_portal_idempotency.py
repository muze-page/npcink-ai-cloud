from __future__ import annotations

import asyncio
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select
from starlette.types import Message, Receive, Scope, Send

from app.api.main import create_app
from app.api.portal_idempotency_middleware import PortalIdempotencyMiddleware
from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import (
    ACCOUNT_STATUS_ACTIVE,
    ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
    ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED,
    PRINCIPAL_STATUS_ACTIVE,
    SITE_STATUS_ACTIVE,
    Account,
    AccountUserMembership,
    PortalMutationIdempotencyReceipt,
    Principal,
    Site,
    SupportRequest,
    SupportRequestMessage,
)
from app.core.services import CloudServices
from app.domain.portal_idempotency import (
    PortalIdempotencyClaim,
    PortalIdempotencyError,
    PortalIdempotencyReplay,
    build_portal_business_idempotency_key,
    build_portal_request_fingerprint,
    claim_portal_mutation,
)
from tests.conftest import (
    TEST_ADMIN_SESSION_SECRET,
    TEST_INTERNAL_AUTH_TOKEN,
    TEST_PORTAL_JWT_SECRET,
    build_portal_bearer_headers,
)

PORTAL_PATH = "/portal/v1/support-requests"
PORTAL_ROUTE = "/portal/v1/support-requests"
PORTAL_METHOD = "POST"
PORTAL_KEY = "portal-idempotency-contract-001"
PORTAL_PAYLOAD = {
    "topic": "billing",
    "title": "Idempotent support request",
    "description": "Create this support request exactly once.",
    "site_id": "site_portal_idempotency",
    "source_path": "/portal/billing",
    "context": {"source": "idempotency-contract"},
}


def _sqlite_url(tmp_path: Path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'portal-idempotency.sqlite3'}"


@pytest.fixture
def portal_client(tmp_path: Path) -> Iterator[tuple[str, TestClient]]:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = Settings(
        _env_file=None,
        project_name="Npcink AI Cloud Portal Idempotency Test",
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
        debug_local_origin_allowlist="http://testserver",
    )
    with get_session(database_url) as session:
        session.add(
            Account(
                account_id="acct_portal_idempotency",
                name="Portal Idempotency Account",
                status=ACCOUNT_STATUS_ACTIVE,
                metadata_json={},
            )
        )
        session.add(
            Site(
                site_id="site_portal_idempotency",
                account_id="acct_portal_idempotency",
                name="Portal Idempotency Site",
                status=SITE_STATUS_ACTIVE,
                site_url="https://idempotency.example.com",
                metadata_json={},
            )
        )
        for suffix in ("alpha", "beta"):
            principal_id = f"prn_portal_idempotency_{suffix}"
            session.add(
                Principal(
                    principal_id=principal_id,
                    email=f"portal-idempotency-{suffix}@example.com",
                    status=PRINCIPAL_STATUS_ACTIVE,
                    session_version=1,
                    metadata_json={},
                )
            )
            session.add(
                AccountUserMembership(
                    membership_id=f"mem_portal_idempotency_{suffix}",
                    principal_id=principal_id,
                    account_id="acct_portal_idempotency",
                    role="user",
                    status=ACCOUNT_USER_MEMBERSHIP_STATUS_ACTIVE,
                    allowed_actions_json=[],
                    metadata_json={},
                )
            )
        session.commit()

    try:
        with TestClient(create_app(CloudServices(settings=settings))) as client:
            client.headers.update(
                {
                    "origin": "http://testserver",
                    "referer": "http://testserver/portal",
                }
            )
            yield database_url, client
    finally:
        dispose_engine(database_url)


def _headers(principal: str, *, key: str = "") -> dict[str, str]:
    return build_portal_bearer_headers(
        principal_id=f"prn_portal_idempotency_{principal}",
        session_version=1,
        site_id="site_portal_idempotency",
        idempotency_key=key,
    )


def _support_request_count(database_url: str) -> int:
    with get_session(database_url) as session:
        return int(session.scalar(select(func.count()).select_from(SupportRequest)) or 0)


def _support_message_count(database_url: str) -> int:
    with get_session(database_url) as session:
        return int(session.scalar(select(func.count()).select_from(SupportRequestMessage)) or 0)


def _idempotency_settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
        admin_session_secret=TEST_ADMIN_SESSION_SECRET,
        portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
    )


@pytest.mark.parametrize(
    ("key", "status_code", "error_code"),
    [
        (None, 401, "auth.idempotency_required"),
        ("contains spaces", 400, "auth.invalid_idempotency_key"),
        ("x" * 129, 400, "auth.invalid_idempotency_key"),
    ],
)
def test_required_portal_mutation_rejects_missing_or_invalid_key_without_business_side_effect(
    portal_client: tuple[str, TestClient],
    key: str | None,
    status_code: int,
    error_code: str,
) -> None:
    database_url, client = portal_client
    headers = _headers("alpha")
    if key is not None:
        headers["Idempotency-Key"] = key

    response = client.post(PORTAL_PATH, json=PORTAL_PAYLOAD, headers=headers)

    assert response.status_code == status_code, response.text
    assert response.json()["error_code"] == error_code
    assert _support_request_count(database_url) == 0


def test_same_principal_key_and_request_replays_exact_response_once(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, client = portal_client
    headers = _headers("alpha", key=PORTAL_KEY)

    first = client.post(PORTAL_PATH, json=PORTAL_PAYLOAD, headers=headers)
    replay = client.post(PORTAL_PATH, json=PORTAL_PAYLOAD, headers=headers)

    assert first.status_code == 200, first.text
    assert replay.status_code == first.status_code
    assert replay.content == first.content
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert _support_request_count(database_url) == 1
    with get_session(database_url) as session:
        receipt = session.scalar(select(PortalMutationIdempotencyReceipt))
        assert receipt is not None
        assert receipt.response_body_ciphertext
        assert "Idempotent support request" not in receipt.response_body_ciphertext


def test_completed_replay_rechecks_current_site_membership(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, client = portal_client
    headers = _headers("alpha", key="portal-replay-after-membership-revocation")
    first = client.post(PORTAL_PATH, json=PORTAL_PAYLOAD, headers=headers)
    assert first.status_code == 200, first.text

    with get_session(database_url) as session:
        membership = session.scalar(
            select(AccountUserMembership).where(
                AccountUserMembership.principal_id == "prn_portal_idempotency_alpha",
                AccountUserMembership.account_id == "acct_portal_idempotency",
            )
        )
        assert membership is not None
        membership.status = ACCOUNT_USER_MEMBERSHIP_STATUS_REVOKED
        session.commit()

    replay = client.post(PORTAL_PATH, json=PORTAL_PAYLOAD, headers=headers)

    assert replay.status_code == 403, replay.text
    assert replay.json()["error_code"] == "service.principal_access_required"
    assert replay.headers.get("Idempotency-Replayed") is None
    assert replay.content != first.content
    assert _support_request_count(database_url) == 1


def test_same_principal_and_key_rejects_changed_body_or_route_without_second_side_effect(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, client = portal_client
    headers = _headers("alpha", key=PORTAL_KEY)
    first = client.post(PORTAL_PATH, json=PORTAL_PAYLOAD, headers=headers)
    assert first.status_code == 200, first.text
    request_id = first.json()["data"]["request"]["request_id"]
    initial_message_count = _support_message_count(database_url)

    changed_body = client.post(
        PORTAL_PATH,
        json={**PORTAL_PAYLOAD, "description": "This is a different request."},
        headers=headers,
    )
    changed_route = client.post(
        f"{PORTAL_PATH}/{request_id}/messages",
        json={"body": "This route must not share the create-request receipt."},
        headers=headers,
    )

    for response in (changed_body, changed_route):
        assert response.status_code == 409, response.text
        assert response.json()["error_code"] == "portal.idempotency_conflict"
    assert _support_request_count(database_url) == 1
    assert _support_message_count(database_url) == initial_message_count


def test_different_principals_may_reuse_the_same_key(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, client = portal_client

    alpha = client.post(
        PORTAL_PATH,
        json=PORTAL_PAYLOAD,
        headers=_headers("alpha", key=PORTAL_KEY),
    )
    beta = client.post(
        PORTAL_PATH,
        json=PORTAL_PAYLOAD,
        headers=_headers("beta", key=PORTAL_KEY),
    )

    assert alpha.status_code == 200, alpha.text
    assert beta.status_code == 200, beta.text
    assert _support_request_count(database_url) == 2


def test_non_idempotent_portal_route_ignores_an_unrelated_invalid_key(
    portal_client: tuple[str, TestClient],
) -> None:
    _, client = portal_client

    baseline = client.get(
        PORTAL_PATH,
        headers=_headers("alpha"),
    )
    with_unrelated_key = client.get(
        PORTAL_PATH,
        headers={**_headers("alpha"), "Idempotency-Key": "contains spaces"},
    )

    assert baseline.status_code == 200, baseline.text
    assert with_unrelated_key.status_code == baseline.status_code
    assert with_unrelated_key.content == baseline.content


def test_non_participating_portal_mutation_streams_large_response_without_truncation(
    tmp_path: Path,
) -> None:
    response_body = b"x" * 2048
    sent_messages: list[Message] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        del scope, receive
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/octet-stream")],
            }
        )
        await send(
            {"type": "http.response.body", "body": response_body}
        )

    async def run() -> None:
        middleware = PortalIdempotencyMiddleware(
            app,
            settings=Settings(
                _env_file=None,
                environment="test",
                database_url=_sqlite_url(tmp_path),
                internal_auth_token=TEST_INTERNAL_AUTH_TOKEN,
                admin_session_secret=TEST_ADMIN_SESSION_SECRET,
                portal_jwt_secret=TEST_PORTAL_JWT_SECRET,
                portal_idempotency_max_response_bytes=1024,
            ),
        )

        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            sent_messages.append(message)

        scope: Scope = {
            "type": "http",
            "method": "POST",
            "path": "/portal/v1/non-participating",
            "state": {},
            "headers": [],
        }
        await middleware(scope, receive, send)

    asyncio.run(run())

    bodies = [
        bytes(message.get("body", b""))
        for message in sent_messages
        if message.get("type") == "http.response.body"
    ]
    assert b"".join(bodies) == response_body


def _domain_claim(
    database_url: str,
    *,
    now: datetime,
    key: str = PORTAL_KEY,
) -> PortalIdempotencyClaim | PortalIdempotencyReplay:
    return claim_portal_mutation(
        database_url=database_url,
        principal_id="prn_portal_idempotency_alpha",
        idempotency_key=key,
        method=PORTAL_METHOD,
        route=PORTAL_ROUTE,
        request_fingerprint=build_portal_request_fingerprint(
            method=PORTAL_METHOD,
            route=PORTAL_ROUTE,
            body=PORTAL_PAYLOAD,
        ),
        now=now,
        lease_seconds=30,
        ttl_seconds=3600,
        settings=_idempotency_settings(database_url),
    )


def test_processing_receipt_returns_conflict_until_lease_expires(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, _ = portal_client
    now = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)
    claim = _domain_claim(database_url, now=now)
    assert isinstance(claim, PortalIdempotencyClaim)

    with pytest.raises(PortalIdempotencyError) as caught:
        _domain_claim(database_url, now=now + timedelta(seconds=10))

    assert caught.value.status_code == 409
    assert caught.value.error_code == "portal.idempotency_in_progress"


def test_selected_site_context_participates_in_the_request_fingerprint(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, _ = portal_client
    now = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)
    fingerprint_a = build_portal_request_fingerprint(
        method="POST",
        route="/portal/v1/account/free-downgrade",
        body={},
        site_id="site_account_alpha",
    )
    fingerprint_b = build_portal_request_fingerprint(
        method="POST",
        route="/portal/v1/account/free-downgrade",
        body={},
        site_id="site_account_beta",
    )
    assert fingerprint_a != fingerprint_b

    first = claim_portal_mutation(
        database_url=database_url,
        principal_id="prn_portal_idempotency_alpha",
        idempotency_key="portal-selected-site-scope",
        method="POST",
        route="/portal/v1/account/free-downgrade",
        request_fingerprint=fingerprint_a,
        now=now,
        lease_seconds=30,
        ttl_seconds=3600,
        settings=_idempotency_settings(database_url),
    )
    assert isinstance(first, PortalIdempotencyClaim)

    with pytest.raises(PortalIdempotencyError) as caught:
        claim_portal_mutation(
            database_url=database_url,
            principal_id="prn_portal_idempotency_alpha",
            idempotency_key="portal-selected-site-scope",
            method="POST",
            route="/portal/v1/account/free-downgrade",
            request_fingerprint=fingerprint_b,
            now=now + timedelta(seconds=1),
            lease_seconds=30,
            ttl_seconds=3600,
            settings=_idempotency_settings(database_url),
        )

    assert caught.value.status_code == 409
    assert caught.value.error_code == "portal.idempotency_conflict"


def test_business_idempotency_key_is_stable_principal_scoped_and_opaque() -> None:
    raw_key = "portal-payment-order-contract-001"
    principal_a = "prn_portal_idempotency_alpha"
    principal_b = "prn_portal_idempotency_beta"

    first = build_portal_business_idempotency_key(
        principal_id=principal_a,
        idempotency_key=raw_key,
    )
    same_scope = build_portal_business_idempotency_key(
        principal_id=principal_a,
        idempotency_key=raw_key,
    )
    other_principal = build_portal_business_idempotency_key(
        principal_id=principal_b,
        idempotency_key=raw_key,
    )

    assert first == same_scope
    assert first != other_principal
    assert raw_key not in first
    assert principal_a not in first
    assert principal_b not in other_principal
    assert 1 <= len(first) <= 191


def test_expired_lease_fails_closed_when_original_result_is_indeterminate(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, _ = portal_client
    now = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)
    first = _domain_claim(database_url, now=now)
    assert isinstance(first, PortalIdempotencyClaim)

    with pytest.raises(PortalIdempotencyError) as caught:
        _domain_claim(database_url, now=now + timedelta(seconds=31))

    assert caught.value.status_code == 409
    assert caught.value.error_code == "portal.idempotency_indeterminate"

    with pytest.raises(PortalIdempotencyError) as after_ttl:
        _domain_claim(database_url, now=now + timedelta(seconds=3601))
    assert after_ttl.value.error_code == "portal.idempotency_indeterminate"


def test_concurrent_claims_allow_at_most_one_owner_on_sqlite(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, _ = portal_client
    now = datetime(2026, 7, 17, 4, 0, tzinfo=UTC)
    barrier = Barrier(2)

    def claim_once() -> PortalIdempotencyClaim | PortalIdempotencyReplay | PortalIdempotencyError:
        barrier.wait(timeout=5)
        try:
            return _domain_claim(database_url, now=now)
        except PortalIdempotencyError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim_once(), range(2)))

    claims = [item for item in outcomes if isinstance(item, PortalIdempotencyClaim)]
    errors = [item for item in outcomes if isinstance(item, PortalIdempotencyError)]
    assert len(claims) == 1
    assert len(errors) == 1
    assert errors[0].error_code == "portal.idempotency_in_progress"


def test_concurrent_http_duplicates_create_one_business_side_effect(
    portal_client: tuple[str, TestClient],
) -> None:
    database_url, client = portal_client
    barrier = Barrier(2)

    def submit_once() -> Response:
        barrier.wait(timeout=5)
        return client.post(
            PORTAL_PATH,
            json=PORTAL_PAYLOAD,
            headers=_headers("alpha", key="portal-concurrent-http-contract"),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit_once(), range(2)))

    successes = [response for response in responses if response.status_code == 200]
    conflicts = [response for response in responses if response.status_code == 409]
    assert successes
    assert len(successes) + len(conflicts) == 2, [
        (response.status_code, str(response.request.url), response.text)
        for response in responses
    ]
    assert _support_request_count(database_url) == 1
    for response in conflicts:
        assert response.json()["error_code"] == "portal.idempotency_in_progress"
    if len(successes) == 2:
        assert successes[0].content == successes[1].content
        assert sorted(
            response.headers.get("Idempotency-Replayed", "") for response in successes
        ) == ["", "true"]
