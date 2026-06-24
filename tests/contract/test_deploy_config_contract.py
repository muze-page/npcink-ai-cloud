from __future__ import annotations

import os
from pathlib import Path

import pytest

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
        assert "NPCINK_CLOUD_ADMIN_SESSION_SECRET" in text
        assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN" in text
        assert "NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS" in text
        assert "NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS" in text or text is checklist_text
        assert "NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS" in text or text is checklist_text
        assert (
            "NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS" in text or text is checklist_text
        )
        assert "NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT" in text or text is checklist_text
        assert "NPCINK_CLOUD_OPENAI_BASE_URL" in text or text is checklist_text

    assert "callback-worker:" in compose_text
    assert "otel-collector:" in compose_text
    assert "jaeger:" in compose_text

    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in compose_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in env_example_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in readme_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in checklist_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in compose_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in env_example_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in readme_text
    assert "NPCINK_CLOUD_FEATURE_FLAGS_JSON" in env_example_text
    assert "NPCINK_CLOUD_FEATURE_FLAGS_JSON" in readme_text


def test_env_example_production_payload_validates_with_canonical_names(
    tmp_path: Path,
    monkeypatch,
) -> None:
    for key in list(os.environ):
        if key.startswith("NPCINK_CLOUD_"):
            monkeypatch.delenv(key, raising=False)

    env_text = (_cloud_root() / ".env.example").read_text()
    env_text = env_text.replace(
        "NPCINK_CLOUD_ENVIRONMENT=development",
        "NPCINK_CLOUD_ENVIRONMENT=production",
    )
    replacements = {
        "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=": "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN=" + ("i" * 32),
        "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN=": "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN=" + ("b" * 32),
        "NPCINK_CLOUD_ADMIN_SESSION_SECRET=": "NPCINK_CLOUD_ADMIN_SESSION_SECRET=" + ("a" * 32),
        "NPCINK_CLOUD_PORTAL_JWT_SECRET=": "NPCINK_CLOUD_PORTAL_JWT_SECRET=" + ("j" * 32),
        "NPCINK_CLOUD_PORTAL_PUBLIC_BASE_URL=": (
            "NPCINK_CLOUD_PORTAL_PUBLIC_BASE_URL=https://cloud.example.com"
        ),
        "NPCINK_CLOUD_PORTAL_EMAIL_SMTP_HOST=": (
            "NPCINK_CLOUD_PORTAL_EMAIL_SMTP_HOST=smtp.example.com"
        ),
        "NPCINK_CLOUD_PORTAL_EMAIL_FROM_EMAIL=": (
            "NPCINK_CLOUD_PORTAL_EMAIL_FROM_EMAIL=noreply@example.com"
        ),
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
    assert settings.openai_base_url == "https://api.openai.com/v1"


def test_settings_accept_legacy_admin_and_openai_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("NPCINK_CLOUD_ENVIRONMENT", "production")
    monkeypatch.setenv("NPCINK_CLOUD_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("NPCINK_CLOUD_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "i" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN", "b" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_SESSION_SECRET", "a" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_OPS_SESSION_SECRET", "a" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_PORTAL_JWT_SECRET", "j" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_PORTAL_PUBLIC_BASE_URL", "https://cloud.example.com")
    monkeypatch.setenv("NPCINK_CLOUD_PORTAL_EMAIL_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("NPCINK_CLOUD_PORTAL_EMAIL_FROM_EMAIL", "noreply@example.com")
    monkeypatch.setenv("NPCINK_CLOUD_OPENAI_API_KEY", "sk-current")
    monkeypatch.setenv("NPCINK_CLOUD_OPENAI_BASE_URL", "https://current.example.com/v1")

    settings = Settings(_env_file=None)

    assert settings.admin_session_secret == "a" * 32
    assert settings.openai_api_key == "sk-current"
    assert settings.openai_base_url == "https://current.example.com/v1"


def test_preview_and_baseline_scripts_lock_migration_and_schema_checks() -> None:
    repo_root = _cloud_root().parent
    dev_compose_text = (_cloud_root() / "docker-compose.dev.yml").read_text()
    preview_script_path = repo_root / "scripts" / "remote-preview-mini.sh"
    if not preview_script_path.exists():
        pytest.skip("root preview script is not mounted in this standalone Cloud test environment")
    preview_script = preview_script_path.read_text()
    baseline_script = (_cloud_root() / "deploy" / "remote-baseline-status.sh").read_text()
    nginx_dev_conf = (_cloud_root() / "deploy" / "nginx.dev.conf").read_text()
    release_smoke_script = (_cloud_root() / "deploy" / "release-smoke.sh").read_text()
    remote_smoke_script = (_cloud_root() / "deploy" / "remote-smoke.sh").read_text()
    secret_rotation_script = (_cloud_root() / "deploy" / "validate-secret-rotation.sh").read_text()
    env_push_script = (_cloud_root() / "deploy" / "env-to-ssh-host.sh").read_text()
    remote_env_script = (_cloud_root() / "deploy" / "remote-env-upsert.sh").read_text()
    remote_migrate_script = (_cloud_root() / "deploy" / "remote-migrate.sh").read_text()
    deploy_to_ssh_script = (_cloud_root() / "deploy" / "deploy-to-ssh-host.sh").read_text()
    common_script = (_cloud_root() / "deploy" / "common.sh").read_text()
    remote_load_script = (_cloud_root() / "deploy" / "remote-load-and-up.sh").read_text()

    assert "alembic upgrade head" in preview_script
    assert "python -m app.dev.baseline_status" in preview_script
    assert (
        'SERVICES="${SERVICES:-api worker callback-worker ops-worker frontend}"' in preview_script
    )
    assert "for service in ${SERVICES}; do" in preview_script
    assert "fatal startup log detected" in preview_script
    assert "NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST" in preview_script
    assert "NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST" in preview_script
    assert "NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT" in preview_script
    assert "NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT" in preview_script
    assert "NPCINK_CLOUD_OTEL_TRACE_QUERY_URL" in preview_script
    assert "ensure_remote_trace_sink" in preview_script
    assert "verify_remote_trace_sink" in preview_script
    assert "reload_remote_proxy" in preview_script
    assert ".cache/npcink-ai-cloud-mini" in preview_script
    assert "PREVIEW_STACK_SERVICES" in preview_script
    assert "DEPENDENCY_IMAGES=(" in preview_script
    assert (
        "keychain cannot be accessed because the current session does not allow user interaction"
    ) in preview_script
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
    assert "npcink-ai-cloud-ops-worker:dev" in dev_compose_text
    assert "/health/operational-ready" in preview_script
    assert "python -m app.dev.baseline_status" in baseline_script
    assert "/internal/service/observability/summary" in release_smoke_script
    assert "/health/operational-ready" in release_smoke_script
    assert "build_hmac_signature(secret, canonical_request)" in release_smoke_script
    assert "/internal/service/observability/summary" in remote_smoke_script
    assert "/health/operational-ready" in remote_smoke_script
    assert '"policy":{"allow_fallback":true}}' in remote_smoke_script
    assert 'openssl dgst -sha256 -hmac "${SECRET}"' in remote_smoke_script
    assert 'openssl dgst -sha256 -hmac "${secret_hash}"' not in remote_smoke_script
    assert "max_retries" not in remote_smoke_script
    assert "/internal/service/observability/summary" in secret_rotation_script
    assert 'RESTART_SERVICES="proxy,api,worker,callback-worker,ops-worker"' in env_push_script
    assert 'RESTART_SERVICES="proxy,api,worker,callback-worker,ops-worker"' in remote_env_script
    assert "up -d worker callback-worker ops-worker" in remote_migrate_script
    assert "SSH identity file not found" in deploy_to_ssh_script
    assert "BatchMode=yes" in deploy_to_ssh_script
    assert "ConnectTimeout" in deploy_to_ssh_script
    assert "SSH target is not reachable" in deploy_to_ssh_script
    assert "NPCINK_CLOUD_HEALTH_HOST_HEADER" in common_script
    assert "NPCINK_CLOUD_HEALTH_FORWARDED_PROTO" in common_script
    assert "NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST" in remote_load_script
    assert "configure_ready_origin_headers" in remote_load_script


def test_deploy_bundle_smoke_uses_sample_provider_and_skip_frontend_contract() -> None:
    cloud_root = _cloud_root()
    ci_workflow = (cloud_root / ".github" / "workflows" / "ci.yml").read_text()
    compose_text = (cloud_root / "docker-compose.prod.yml").read_text()
    runtime_compose_text = (cloud_root / "docker-compose.runtime.yml").read_text()
    package_json = (cloud_root / "package.json").read_text()
    frontend_dockerfile = (cloud_root / "frontend" / "Dockerfile").read_text()
    bundle_script = (cloud_root / "deploy" / "bundle-images.sh").read_text()
    static_terms_deploy_script = (
        cloud_root / "deploy" / "deploy-static-terms-to-ssh-host.sh"
    ).read_text()
    deploy_bundle_smoke = (cloud_root / "scripts" / "cloud-deploy-bundle-smoke-flow.sh").read_text()
    remote_smoke_script = (cloud_root / "deploy" / "remote-smoke.sh").read_text()
    nginx_prod_conf = (cloud_root / "deploy" / "nginx.prod.conf").read_text()
    caddy_prod_conf = (cloud_root / "deploy" / "Caddyfile.prod").read_text()

    assert "packageManager" in package_json
    assert "pnpm@10.33.0" in package_json
    assert "context: ." in compose_text
    assert "dockerfile: frontend/Dockerfile" in compose_text
    assert "COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./" in frontend_dockerfile
    assert "corepack prepare pnpm@10.33.0 --activate" in frontend_dockerfile
    assert "pnpm install --frozen-lockfile --filter frontend..." in frontend_dockerfile

    assert 'export NPCINK_CLOUD_ENVIRONMENT="${NPCINK_CLOUD_ENVIRONMENT:-test}"' in (
        deploy_bundle_smoke
    )
    assert "NPCINK_CLOUD_ENVIRONMENT" in deploy_bundle_smoke
    assert "NPCINK_CLOUD_SKIP_FRONTEND_IMAGE" in deploy_bundle_smoke

    assert 'if [ "${NPCINK_CLOUD_SKIP_FRONTEND_IMAGE:-0}" = "1" ]; then' in (
        remote_smoke_script
    )
    assert "Skipping frontend page checks" in remote_smoke_script
    assert "buyer-facing home page should succeed" in remote_smoke_script

    assert "upstream npcink_ai_cloud_frontend" not in nginx_prod_conf
    assert "resolver 127.0.0.11" in nginx_prod_conf
    assert 'set $npcink_ai_cloud_frontend "frontend:3000";' in nginx_prod_conf
    assert "map $http_x_forwarded_proto $npcink_forwarded_proto" in nginx_prod_conf
    assert "map $http_x_forwarded_host $npcink_forwarded_host" in nginx_prod_conf
    assert "proxy_set_header X-Forwarded-Host $host;" in nginx_prod_conf
    assert "proxy_set_header X-Forwarded-Proto $npcink_forwarded_proto;" in nginx_prod_conf
    assert "location = /admin/auth/bootstrap" in nginx_prod_conf
    assert "proxy_set_header Host $npcink_forwarded_host;" in nginx_prod_conf
    assert "proxy_set_header X-Forwarded-Host $npcink_forwarded_host;" in nginx_prod_conf
    assert "proxy_pass http://npcink_ai_cloud_api;" in nginx_prod_conf
    assert "header_up Host {host}" in caddy_prod_conf
    assert "header_up X-Forwarded-Host {host}" in caddy_prod_conf
    assert "header_up X-Forwarded-Proto {scheme}" in caddy_prod_conf
    assert "./site:/usr/share/nginx/html/npcink-site:ro" in runtime_compose_text
    assert "-C \"${CLOUD_DIR}\" site" in bundle_script
    assert "location = /terms" in nginx_prod_conf
    assert "try_files /terms/index.html =404;" in nginx_prod_conf
    assert "location /terms/" in nginx_prod_conf
    assert "root /usr/share/nginx/html/npcink-site;" in nginx_prod_conf
    assert "\"${BASE_URL%/}/terms\"" in remote_smoke_script
    assert "/terms/en/terms.html" in remote_smoke_script
    assert "/terms/zh/terms.html" in remote_smoke_script
    assert "/terms/styles.css" in remote_smoke_script
    assert "static_terms_only" in ci_workflow
    assert "site/terms/*" in ci_workflow
    assert "needs: [classify, backend, frontend, static-terms]" in ci_workflow
    assert "bash deploy/deploy-static-terms-to-ssh-host.sh" in ci_workflow
    assert "deploy:static-terms:ssh" in package_json
    assert "CURRENT_LINK=\"${REMOTE_DIR}/current\"" in static_terms_deploy_script
    assert "tar czf \"${TERMS_BUNDLE}\" -C \"${ROOT_DIR}/site\" terms" in (
        static_terms_deploy_script
    )
    assert "assert_public_static_page \"/terms\"" in static_terms_deploy_script
    assert "Static terms deploy completed" in static_terms_deploy_script


def test_static_terms_pages_are_in_release_tree() -> None:
    cloud_root = _cloud_root()

    expected_files = (
        "site/terms/index.html",
        "site/terms/styles.css",
        "site/terms/assets/icon-128x128.png",
        "site/terms/assets/icon-256x256.png",
        "site/terms/en/index.html",
        "site/terms/en/terms.html",
        "site/terms/en/privacy.html",
        "site/terms/en/data-retention.html",
        "site/terms/zh/index.html",
        "site/terms/zh/terms.html",
        "site/terms/zh/privacy.html",
        "site/terms/zh/data-retention.html",
    )
    for relative_path in expected_files:
        assert (cloud_root / relative_path).is_file()

    assert not (cloud_root / "site" / ".DS_Store").exists()
    assert "Npcink Cloud Terms of Service" in (
        cloud_root / "site" / "terms" / "en" / "terms.html"
    ).read_text()
    assert "Npcink Cloud 服务条款" in (
        cloud_root / "site" / "terms" / "zh" / "terms.html"
    ).read_text()


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

    assert (
        "`repo ready` is the only category currently closed by repository evidence"
        in checklist_text
    )
    assert "Cloud must not be treated as GA-ready" in checklist_text
    assert "deploy/release-smoke.sh" in checklist_text
    assert "deploy/RELEASE_CHECKLIST.md" in playbook_text
    assert "the release is blocked" in playbook_text
    assert "Do not replace it with a second release entry point" in playbook_text


def test_lightweight_release_policy_gate_is_documented() -> None:
    cloud_root = _cloud_root()
    agents_text = (cloud_root / "AGENTS.md").read_text()
    policy_text = (cloud_root / "docs" / "cloud-production-release-policy-v1.md").read_text()
    deploy_text = (cloud_root / "deploy" / "PRODUCTION_GITHUB_DEPLOY.md").read_text()
    pr_template_text = (cloud_root / ".github" / "pull_request_template.md").read_text()
    package_text = (cloud_root / "package.json").read_text()
    script_text = (cloud_root / "scripts" / "check-release-policy.sh").read_text()

    for marker in (
        "`master` is the development integration branch",
        "`production` is the production release source",
        "Do not directly edit production application code on the server.",
        "Approved for production validation by operator.",
        "Cloud is not becoming a WordPress write owner",
    ):
        assert marker in policy_text

    assert "docs/cloud-production-release-policy-v1.md" in deploy_text
    assert "pnpm run check:release-policy" in deploy_text
    assert "/terms/en/terms.html" in deploy_text
    assert "static terms fast path" in deploy_text
    assert "Focused module:" in pr_template_text
    assert "Cloud boundary impact:" in pr_template_text
    assert "does not commit production secrets" in pr_template_text
    assert "check:release-policy" in package_text
    assert "Lightweight release policy gate passed" in script_text
    assert "/terms/en/terms.html" in script_text
    assert "deploy-static-terms-to-ssh-host.sh" in script_text

    for marker in (
        "AI Production Operation Rules",
        "Production source branch is `production`",
        "Do not directly edit production application code on the server.",
        "Any emergency server fix must be backported to Git before the next deploy.",
        "Do not commit SMTP passwords",
        "Do not push or deploy to Gitee unless the user explicitly asks.",
        "pnpm run check:release-policy",
    ):
        assert marker in agents_text
