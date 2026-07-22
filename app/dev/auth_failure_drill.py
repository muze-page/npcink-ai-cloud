from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.core.config import Settings
from app.core.db import dispose_engine, init_schema
from app.core.security import (
    build_body_digest,
    build_canonical_request,
    build_hmac_signature,
)
from app.core.services import CloudServices
from app.dev.seed_runtime import seed_site_auth
from app.domain.runtime.service import RuntimeService

DRILL_SITE_ID = "site_auth_failure_drill"
DRILL_KEY_ID = "key_auth_failure_drill"
DRILL_SECRET = "auth-failure-drill-secret-32b"
DRILL_WRONG_SECRET = "wrong-secret-for-auth-failure-drill-32b"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an isolated auth/signature-failure drill and print non-secret operator evidence."
        )
    )
    parser.add_argument("--site-id", default=DRILL_SITE_ID)
    parser.add_argument("--key-id", default=DRILL_KEY_ID)
    parser.add_argument("--secret", default=DRILL_SECRET)
    parser.add_argument("--wrong-secret", default=DRILL_WRONG_SECRET)
    parser.add_argument("--recent-minutes", type=int, default=60)
    return parser.parse_args()


def _settings(database_url: str) -> Settings:
    settings_kwargs: dict[str, Any] = {
        "_env_file": None,
        "environment": "test",
        "database_url": database_url,
        "redis_url": "redis://localhost:6379/0",
        "internal_auth_token": "auth-failure-drill-internal-token-32b",
        "dev_admin_key": "auth-failure-drill-admin-key-32-bytes",
        "admin_session_secret": "auth-failure-drill-admin-session-secret-32b",
        "portal_jwt_secret": "auth-failure-drill-portal-jwt-secret-32b",
        "openai_api_key": None,
    }
    return Settings(**settings_kwargs)


def _build_traceparent(trace_id: str) -> str:
    normalized = trace_id.lower().replace("-", "")
    if len(normalized) != 32:
        normalized = normalized.ljust(32, "0")[:32]
    return f"00-{normalized}-0000000000000000-01"


def _build_auth_headers(
    method: str,
    path: str,
    *,
    site_id: str,
    key_id: str,
    secret: str,
    body: bytes,
    trace_id: str,
    timestamp: str | None = None,
) -> dict[str, str]:
    resolved_timestamp = timestamp or str(int(datetime.now(UTC).timestamp()))
    traceparent = _build_traceparent(trace_id)
    nonce = f"nonce-{trace_id[:24]}"
    idempotency_key = f"auth-failure-drill-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
    canonical_request = build_canonical_request(
        method=method,
        path=path,
        query="",
        site_id=site_id,
        key_id=key_id,
        timestamp=resolved_timestamp,
        nonce=nonce,
        idempotency_key=idempotency_key,
        traceparent=traceparent,
        body_digest=build_body_digest(body),
    )
    signature = build_hmac_signature(secret, canonical_request)
    return {
        "X-Npcink-Site-Id": site_id,
        "X-Npcink-Key-Id": key_id,
        "X-Npcink-Timestamp": resolved_timestamp,
        "X-Npcink-Signature": signature,
        "X-Npcink-Nonce": nonce,
        "Idempotency-Key": idempotency_key,
        "traceparent": traceparent,
    }


def run_drill(
    *,
    site_id: str,
    key_id: str,
    secret: str,
    wrong_secret: str,
    recent_minutes: int,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="magick-auth-failure-drill-") as tmp_dir:
        database_url = f"sqlite+pysqlite:///{Path(tmp_dir) / 'drill.sqlite3'}"
        settings = _settings(database_url)
        init_schema(database_url)
        seed_site_auth(
            settings=settings,
            site_id=site_id,
            key_id=key_id,
            secret=secret,
            site_name="Auth failure drill",
            scopes=["runtime:execute", "runtime:read", "runtime:resolve", "stats:read"],
        )

        client = TestClient(
            create_app(
                CloudServices(
                    settings=settings,
                    providers={},
                )
            )
        )

        body_bytes = json.dumps(
            {
                "ability_name": "npcink-abilities-toolkit/build-article-block-plan",
                "ability_family": "workflow",
                "channel": "openapi",
                "execution_kind": "text",
                "profile_id": "text.balanced",
                "input_payload": {
                    "messages": [{"role": "user", "content": "force auth failure drill"}]
                },
            }
        ).encode("utf-8")

        trace_id = "authfailuredrill0000000000000000"
        wrong_headers = _build_auth_headers(
            method="POST",
            path="/v1/runtime/execute",
            site_id=site_id,
            key_id=key_id,
            secret=wrong_secret,
            body=body_bytes,
            trace_id=trace_id,
        )
        wrong_headers["content-type"] = "application/json"

        response = client.post("/v1/runtime/execute", content=body_bytes, headers=wrong_headers)

        runtime_service = RuntimeService(database_url, settings=settings)
        diagnostics = runtime_service.get_runtime_diagnostics_summary(
            site_id=site_id,
            recent_minutes=recent_minutes,
        )
        guard_value = diagnostics.get("guard")
        guard = guard_value if isinstance(guard_value, dict) else {}

        evidence = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "site_id": site_id,
            "auth_request": {
                "trace_id": trace_id,
                "method": "POST",
                "path": "/v1/runtime/execute",
                "signature_used_wrong_secret": True,
            },
            "auth_response": {
                "status_code": response.status_code,
                "error_code": (
                    response.json().get("error_code") if response.status_code == 401 else None
                ),
                "error_message": (
                    response.json().get("message") if response.status_code == 401 else None
                ),
            },
            "diagnostics": {
                "operator_guidance": diagnostics.get("operator_guidance"),
                "guard_summary": {
                    "recent_events": guard.get("recent_events"),
                    "event_codes": guard.get("event_codes"),
                },
            },
        }
        dispose_engine(database_url)
        return evidence


def main() -> None:
    args = parse_args()
    evidence = run_drill(
        site_id=args.site_id,
        key_id=args.key_id,
        secret=args.secret,
        wrong_secret=args.wrong_secret,
        recent_minutes=max(1, int(args.recent_minutes)),
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
