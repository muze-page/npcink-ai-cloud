from __future__ import annotations

import os
from pathlib import Path

from app.core.config import Settings


def _cloud_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_prod_env_files_use_canonical_admin_and_openai_names() -> None:
    cloud_root = _cloud_root()
    compose_text = (cloud_root / "docker-compose.prod.yml").read_text()
    env_example_text = (cloud_root / ".env.example").read_text()
    readme_text = (cloud_root / "README.md").read_text()
    checklist_text = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()

    for text in (compose_text, env_example_text, readme_text, checklist_text):
        assert "MAGICK_CLOUD_ADMIN_SESSION_SECRET" in text
        assert "MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN" in text
        assert "MAGICK_CLOUD_OPS_CADENCE_POLL_SECONDS" in text
        assert "MAGICK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS" in text or text is checklist_text
        assert "MAGICK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS" in text or text is checklist_text
        assert "MAGICK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS" in text or text is checklist_text
        assert "MAGICK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT" in text or text is checklist_text
        assert "MAGICK_CLOUD_PROVIDER_CONNECTION_SECRET" in text
        assert "MAGICK_CLOUD_OPENAI_BASE_URL" in text or text is checklist_text

    assert "callback-worker:" in compose_text
    assert "otel-collector:" in compose_text
    assert "jaeger:" in compose_text

    assert "MAGICK_CLOUD_OPS_SESSION_SECRET" not in compose_text
    assert "MAGICK_CLOUD_OPS_SESSION_SECRET" not in env_example_text
    assert "MAGICK_CLOUD_OPS_SESSION_SECRET" not in readme_text
    assert "MAGICK_CLOUD_OPS_SESSION_SECRET" not in checklist_text
    assert "MAGICK_CLOUD_OPENAI_COMPATIBLE_" not in compose_text
    assert "MAGICK_CLOUD_OPENAI_COMPATIBLE_" not in env_example_text
    assert "MAGICK_CLOUD_OPENAI_COMPATIBLE_" not in readme_text
    assert "MAGICK_CLOUD_FEATURE_FLAGS_JSON" in env_example_text
    assert "MAGICK_CLOUD_FEATURE_FLAGS_JSON" in readme_text


def test_env_example_production_payload_validates_with_canonical_names(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("MAGICK_CLOUD_"):
            monkeypatch.delenv(key, raising=False)

    env_text = (_cloud_root() / ".env.example").read_text()
    env_text = env_text.replace(
        "MAGICK_CLOUD_ENVIRONMENT=development",
        "MAGICK_CLOUD_ENVIRONMENT=production",
    )
    replacements = {
        "MAGICK_CLOUD_INTERNAL_AUTH_TOKEN=": "MAGICK_CLOUD_INTERNAL_AUTH_TOKEN="
        + ("i" * 32),
        "MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN=": "MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN="
        + ("b" * 32),
        "MAGICK_CLOUD_ADMIN_SESSION_SECRET=": "MAGICK_CLOUD_ADMIN_SESSION_SECRET="
        + ("a" * 32),
        "MAGICK_CLOUD_PROVIDER_CONNECTION_SECRET=": "MAGICK_CLOUD_PROVIDER_CONNECTION_SECRET="
        + ("p" * 32),
        "MAGICK_CLOUD_PORTAL_JWT_SECRET=": "MAGICK_CLOUD_PORTAL_JWT_SECRET=" + ("j" * 32),
        "MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL=": "MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL=https://cloud.example.com",
        "MAGICK_CLOUD_PORTAL_EMAIL_SMTP_HOST=": "MAGICK_CLOUD_PORTAL_EMAIL_SMTP_HOST=smtp.example.com",
        "MAGICK_CLOUD_PORTAL_EMAIL_FROM_EMAIL=": "MAGICK_CLOUD_PORTAL_EMAIL_FROM_EMAIL=noreply@example.com",
    }
    for original, updated in replacements.items():
        env_text = env_text.replace(original, updated)

    env_file = tmp_path / ".env.production"
    env_file.write_text(env_text)

    settings = Settings(_env_file=env_file)

    assert settings.environment == "production"
    assert settings.admin_bootstrap_token == "b" * 32
    assert settings.admin_session_secret == "a" * 32
    assert settings.ops_cadence_poll_seconds == 30
    assert settings.worker_heartbeat_interval_seconds == 60
    assert settings.provider_health_scan_interval_seconds == 900
    assert settings.otel_trace_sink_otlp_endpoint == "jaeger:4317"
    assert settings.provider_connection_secret == "p" * 32
    assert settings.openai_base_url == "https://api.openai.com/v1"


def test_settings_accept_legacy_admin_and_openai_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("MAGICK_CLOUD_ENVIRONMENT", "production")
    monkeypatch.setenv("MAGICK_CLOUD_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("MAGICK_CLOUD_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("MAGICK_CLOUD_INTERNAL_AUTH_TOKEN", "i" * 32)
    monkeypatch.setenv("MAGICK_CLOUD_ADMIN_BOOTSTRAP_TOKEN", "b" * 32)
    monkeypatch.setenv("MAGICK_CLOUD_OPS_SESSION_SECRET", "a" * 32)
    monkeypatch.setenv("MAGICK_CLOUD_PROVIDER_CONNECTION_SECRET", "p" * 32)
    monkeypatch.setenv("MAGICK_CLOUD_PORTAL_JWT_SECRET", "j" * 32)
    monkeypatch.setenv("MAGICK_CLOUD_PORTAL_PUBLIC_BASE_URL", "https://cloud.example.com")
    monkeypatch.setenv("MAGICK_CLOUD_PORTAL_EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("MAGICK_CLOUD_PORTAL_EMAIL_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("MAGICK_CLOUD_OPENAI_COMPATIBLE_API_KEY", "sk-legacy")
    monkeypatch.setenv("MAGICK_CLOUD_OPENAI_COMPATIBLE_BASE_URL", "https://legacy.example.com/v1")

    settings = Settings(_env_file=None)

    assert settings.admin_session_secret == "a" * 32
    assert settings.openai_api_key == "sk-legacy"
    assert settings.openai_base_url == "https://legacy.example.com/v1"


def test_preview_and_baseline_scripts_lock_migration_and_schema_checks() -> None:
    repo_root = _cloud_root().parent
    dev_compose_text = (_cloud_root() / "docker-compose.dev.yml").read_text()
    preview_script = (repo_root / "scripts" / "remote-preview-mini.sh").read_text()
    baseline_script = (_cloud_root() / "deploy" / "remote-baseline-status.sh").read_text()
    nginx_dev_conf = (_cloud_root() / "deploy" / "nginx.dev.conf").read_text()
    release_smoke_script = (_cloud_root() / "deploy" / "release-smoke.sh").read_text()
    remote_smoke_script = (_cloud_root() / "deploy" / "remote-smoke.sh").read_text()
    secret_rotation_script = (_cloud_root() / "deploy" / "validate-secret-rotation.sh").read_text()
    env_push_script = (_cloud_root() / "deploy" / "env-to-ssh-host.sh").read_text()
    remote_env_script = (_cloud_root() / "deploy" / "remote-env-upsert.sh").read_text()
    remote_migrate_script = (_cloud_root() / "deploy" / "remote-migrate.sh").read_text()

    assert "alembic upgrade head" in preview_script
    assert "python -m app.dev.baseline_status" in preview_script
    assert 'SERVICES="${SERVICES:-api worker callback-worker ops-worker recognition-worker frontend}"' in preview_script
    assert "for service in ${SERVICES}; do" in preview_script
    assert 'fatal startup log detected' in preview_script
    assert "MAGICK_CLOUD_TRUSTED_HOST_ALLOWLIST" in preview_script
    assert "MAGICK_CLOUD_BROWSER_ORIGIN_ALLOWLIST" in preview_script
    assert "MAGICK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT" in preview_script
    assert "MAGICK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT" in preview_script
    assert "MAGICK_CLOUD_OTEL_TRACE_QUERY_URL" in preview_script
    assert "ensure_remote_trace_sink" in preview_script
    assert "verify_remote_trace_sink" in preview_script
    assert "reload_remote_proxy" in preview_script
    assert ".cache/magick-ai-cloud-mini" in preview_script
    assert "PREVIEW_STACK_SERVICES" in preview_script
    assert "DEPENDENCY_IMAGES=(" in preview_script
    assert "keychain cannot be accessed because the current session does not allow user interaction" in preview_script
    assert "falling back to local dependency image transfer" in preview_script
    assert "falling back to local build + image transfer" in preview_script
    assert "--pull never" in preview_script
    assert "http://host.docker.internal:4318/v1/traces" in preview_script
    assert "host.docker.internal:4318" in preview_script
    assert "http://${REMOTE_IP}:16686" in preview_script
    assert "--set=receivers.otlp.protocols.grpc.endpoint=0.0.0.0:4317" in preview_script
    assert "--set=receivers.otlp.protocols.http.endpoint=0.0.0.0:4318" in preview_script
    assert "mini-preview-smoke-span" in preview_script
    assert "force_flush()" in preview_script
    assert "api:8000" in preview_script
    assert "proxy:8080" in preview_script
    assert "proxy_set_header Host $host;" in nginx_dev_conf
    assert "proxy_set_header X-Forwarded-Host $host;" in nginx_dev_conf
    assert "location = /health/operational-ready" in nginx_dev_conf
    assert "callback-worker:" in preview_script
    assert "ops-worker:" in preview_script
    assert "ops-worker:" in dev_compose_text
    assert "python -m app.workers.ops_cadence" in dev_compose_text
    assert "magick-ai-cloud-ops-worker:dev" in dev_compose_text
    assert "/health/operational-ready" in preview_script
    assert "python -m app.dev.baseline_status" in baseline_script
    assert "/internal/service/observability/summary" in release_smoke_script
    assert "/health/operational-ready" in release_smoke_script
    assert "--addon-site-id" in release_smoke_script
    assert "--addon-key-id" in release_smoke_script
    assert "--addon-secret" in release_smoke_script
    assert "/v1/addon/dashboard" in release_smoke_script
    assert "/v1/addon/providers/release-summary" in release_smoke_script
    assert "data.generated_at" in release_smoke_script
    assert "data.fresh_until" in release_smoke_script
    assert "data.fallback_reason" in release_smoke_script
    assert "release smoke requires addon credentials" in release_smoke_script
    assert "Skipping addon projection freshness smoke" not in release_smoke_script
    assert "/internal/service/observability/summary" in remote_smoke_script
    assert "/health/operational-ready" in remote_smoke_script
    assert '"policy":{"allow_fallback":true}}' in remote_smoke_script
    assert "max_retries" not in remote_smoke_script
    assert "/internal/service/observability/summary" in secret_rotation_script
    assert 'RESTART_SERVICES="proxy,api,worker,callback-worker,ops-worker"' in env_push_script
    assert 'RESTART_SERVICES="proxy,api,worker,callback-worker,ops-worker"' in remote_env_script
    assert "up -d worker callback-worker ops-worker" in remote_migrate_script


def test_release_gate_documents_cloud_hardening_blockers() -> None:
    cloud_root = _cloud_root()
    checklist_text = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()
    playbook_text = (cloud_root / "deploy" / "OPS_PLAYBOOK.md").read_text()

    for marker in (
        "repo ready",
        "env required",
        "operator required",
        "smoke required",
        "production secrets",
        "TLS / trusted hosts",
        "SMTP real mailbox",
        "worker heartbeat",
        "OTLP sink",
        "DB backup/rollback",
        "real signed runtime request",
    ):
        assert marker in checklist_text

    assert "`repo ready` is the only category currently closed by repository evidence" in checklist_text
    assert "Cloud must not be treated as GA-ready" in checklist_text
    assert "deploy/release-smoke.sh" in checklist_text
    assert "deploy/RELEASE_CHECKLIST.md" in playbook_text
    assert "the release is blocked" in playbook_text
    assert "Do not replace it with a second release entry point" in playbook_text
