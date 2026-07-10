from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.core.config import Settings


def _cloud_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _documented_env_value(text: str, key: str) -> str:
    prefix = f"{key}="
    for token in text.replace("`", " ").split():
        if token.startswith(prefix):
            return token.removeprefix(prefix).rstrip(".,;")
    return ""


def _documented_https_host(text: str, key: str) -> str:
    parsed = urlsplit(_documented_env_value(text, key))
    return parsed.netloc if parsed.scheme == "https" else ""


def test_prod_env_files_use_canonical_admin_names_and_do_not_expose_ai_provider_env() -> None:
    cloud_root = _cloud_root()
    compose_text = (cloud_root / "docker-compose.prod.yml").read_text()
    env_example_text = (cloud_root / ".env.example").read_text()
    readme_text = (cloud_root / "README.md").read_text()
    checklist_text = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()
    playbook_text = (cloud_root / "deploy" / "OPS_PLAYBOOK.md").read_text()
    provider_runbook_text = (
        cloud_root / "docs" / "provider-connection-production-runbook-2026-06-30.md"
    ).read_text()

    for text in (compose_text, env_example_text, readme_text, checklist_text):
        assert "NPCINK_CLOUD_ADMIN_SESSION_SECRET" in text
        assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN" in text
        assert "NPCINK_CLOUD_BASE_URL" in text or text is readme_text
        assert "NPCINK_CLOUD_OPS_CADENCE_POLL_SECONDS" in text
        assert "NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS" in text or text is checklist_text
        assert "NPCINK_CLOUD_WORKER_HEARTBEAT_INTERVAL_SECONDS" in text or text is checklist_text
        assert (
            "NPCINK_CLOUD_PROVIDER_HEALTH_SCAN_INTERVAL_SECONDS" in text or text is checklist_text
        )
        assert "NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT" in text or text is checklist_text

    assert "callback-worker:" in compose_text
    assert "otel-collector:" in compose_text
    assert "jaeger:" in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_PRINCIPAL_ID" in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_PRINCIPAL_ID" in env_example_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_PLATFORM_ADMIN_ROLE" in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_PLATFORM_ADMIN_ROLE" in env_example_text

    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in compose_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in env_example_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in readme_text
    assert "NPCINK_CLOUD_OPS_SESSION_SECRET" not in checklist_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_REF" not in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_REF" not in env_example_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_ROLE" not in compose_text
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_ROLE" not in env_example_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in compose_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in env_example_text
    assert "NPCINK_CLOUD_OPENAI_COMPATIBLE_" not in readme_text
    assert "NPCINK_CLOUD_OPENAI_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_OPENAI_BASE_URL=" not in env_example_text
    assert "NPCINK_CLOUD_MINIMAX_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_MINIMAX_BASE_URL=" not in env_example_text
    assert "NPCINK_CLOUD_ANTHROPIC_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_LITELLM_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_VLLM_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_TEI_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_OPENROUTER_API_KEY=" not in env_example_text
    assert "NPCINK_CLOUD_SILICONFLOW_API_KEY=" not in env_example_text
    assert "AI provider channels are managed in Cloud runtime storage" in env_example_text
    assert "NPCINK_CLOUD_FEATURE_FLAGS_JSON" in env_example_text
    assert "NPCINK_CLOUD_FEATURE_FLAGS_JSON" in readme_text
    assert "http://127.0.0.1:8010" in env_example_text
    assert _documented_https_host(checklist_text, "NPCINK_CLOUD_BASE_URL") == "cloud.npc.ink"
    assert (
        _documented_env_value(checklist_text, "NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST")
        == "cloud.npc.ink"
    )
    assert _documented_https_host(playbook_text, "NPCINK_CLOUD_BASE_URL") == "cloud.npc.ink"
    assert "Resource Tuning Baseline" in playbook_text
    assert "NPCINK_CLOUD_API_WORKERS" in playbook_text
    assert "NPCINK_CLOUD_RUNTIME_WORKER_POLL_SECONDS" in playbook_text
    assert "db_managed_provider_connections" in provider_runbook_text
    assert "deploy/remote-provider-matrix-smoke.sh" in provider_runbook_text
    assert "`search_tavily`" in provider_runbook_text
    assert "`search_bocha`" in provider_runbook_text
    assert "`search_apify`" in provider_runbook_text
    assert "`search_zhihu`" in provider_runbook_text
    assert "`search_jina_reader`" in provider_runbook_text
    assert "optional URL reader enhancement" in provider_runbook_text
    assert "`image_unsplash`" in provider_runbook_text
    assert "`siliconflow_env`" in provider_runbook_text
    assert "`tei_env`" in provider_runbook_text
    assert "`embedding_siliconflow`" not in provider_runbook_text
    assert "`vector_zilliz`" in provider_runbook_text
    assert "Do not put provider credentials back into `.env.deploy`" in provider_runbook_text
    assert "NPCINK_CLOUD_WEB_SEARCH_ZHIHU_ACCESS_SECRET=" not in provider_runbook_text
    assert "NPCINK_CLOUD_IMAGE_SOURCE_UNSPLASH_ACCESS_KEY=" not in provider_runbook_text
    assert "NPCINK_CLOUD_SITE_KNOWLEDGE_ZILLIZ_TOKEN=" not in provider_runbook_text
    assert "NPCINK_CLOUD_RUNTIME_CALLBACK_WORKER_POLL_SECONDS" in playbook_text


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
        "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET=": (
            "NPCINK_CLOUD_SERVICE_SETTINGS_SECRET=" + ("s" * 32)
        ),
        "NPCINK_CLOUD_PORTAL_JWT_SECRET=": "NPCINK_CLOUD_PORTAL_JWT_SECRET=" + ("j" * 32),
        "NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST=": (
            "NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST=https://cloud.example.com"
        ),
        "NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST=": (
            "NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST=cloud.example.com"
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


def test_settings_ignore_retired_admin_and_openai_aliases(monkeypatch) -> None:
    monkeypatch.setenv("NPCINK_CLOUD_ENVIRONMENT", "production")
    monkeypatch.setenv("NPCINK_CLOUD_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("NPCINK_CLOUD_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "i" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN", "b" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_SESSION_SECRET", "a" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_OPS_SESSION_SECRET", "z" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_SERVICE_SETTINGS_SECRET", "s" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_PORTAL_JWT_SECRET", "j" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST", "https://cloud.example.com")
    monkeypatch.setenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "cloud.example.com")
    monkeypatch.setenv(
        "NPCINK_CLOUD_OPENAI_COMPATIBLE_BASE_URL",
        "https://retired.example.com/v1",
    )

    settings = Settings(_env_file=None)

    assert settings.admin_session_secret == "a" * 32
    assert settings.openai_api_key in {None, ""}
    assert settings.openai_base_url == "https://api.openai.com/v1"


def test_retired_ops_secret_does_not_satisfy_production_config(monkeypatch) -> None:
    monkeypatch.setenv("NPCINK_CLOUD_ENVIRONMENT", "production")
    monkeypatch.setenv("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN", "i" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN", "b" * 32)
    monkeypatch.delenv("NPCINK_CLOUD_ADMIN_SESSION_SECRET", raising=False)
    monkeypatch.setenv("NPCINK_CLOUD_OPS_SESSION_SECRET", "z" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_SERVICE_SETTINGS_SECRET", "s" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_PORTAL_JWT_SECRET", "j" * 32)
    monkeypatch.setenv("NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST", "https://cloud.example.com")
    monkeypatch.setenv("NPCINK_CLOUD_TRUSTED_HOST_ALLOWLIST", "cloud.example.com")

    with pytest.raises(ValueError, match="admin_session_secret is required"):
        Settings(_env_file=None)


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
    provider_matrix_smoke = (
        _cloud_root() / "deploy" / "remote-provider-matrix-smoke.sh"
    ).read_text()

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
    assert "location /open/" in nginx_dev_conf
    dev_open_block = nginx_dev_conf.split("location /open/ {", 1)[1].split("\n    }", 1)[0]
    assert "proxy_set_header Connection" not in dev_open_block
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
    assert "Operational readiness gate: enabled" in deploy_to_ssh_script
    assert "Running remote operational readiness gate" in deploy_to_ssh_script
    assert "Remote operational readiness gate passed" in deploy_to_ssh_script
    assert "npcink_ai_cloud_start_timing_summary" in deploy_to_ssh_script
    assert 'remote_run_timed "remote load and up"' in deploy_to_ssh_script
    assert 'remote_run_timed "remote operational readiness"' in deploy_to_ssh_script
    assert "bash deploy/remote-load-and-up.sh </dev/null" in deploy_to_ssh_script
    assert "bash deploy/remote-migrate.sh </dev/null" in deploy_to_ssh_script
    assert "bash deploy/remote-refresh-providers.sh </dev/null" in deploy_to_ssh_script
    assert 'bash deploy/remote-smoke.sh "${SMOKE_ARGS[@]}" </dev/null' in deploy_to_ssh_script
    assert (
        'bash deploy/remote-operational-ready.sh --base-url "${BASE_URL}" </dev/null'
        in deploy_to_ssh_script
    )
    assert "NPCINK_CLOUD_HEALTH_HOST_HEADER" in common_script
    assert "NPCINK_CLOUD_HEALTH_FORWARDED_PROTO" in common_script
    assert "npcink_ai_cloud_run_timed" in common_script
    assert "NPCINK_CLOUD_BROWSER_ORIGIN_ALLOWLIST" in remote_load_script
    assert "configure_ready_origin_headers" in remote_load_script
    assert "compose up services" in remote_load_script
    assert "NPCINK_CLOUD_REQUIRED_PROVIDER_CAPABILITIES" in provider_matrix_smoke
    assert "db_managed_provider_connections" in provider_matrix_smoke
    assert '"direct_wordpress_write": False' in provider_matrix_smoke
    assert '"secret_exposure": "none"' in provider_matrix_smoke


def test_deploy_bundle_smoke_uses_sample_provider_and_skip_frontend_contract() -> None:
    cloud_root = _cloud_root()
    ci_workflow = (cloud_root / ".github" / "workflows" / "ci.yml").read_text()
    deploy_workflow = (
        cloud_root / ".github" / "workflows" / "deploy-production.yml"
    ).read_text()
    maintenance_workflow = (
        cloud_root / ".github" / "workflows" / "production-maintenance.yml"
    ).read_text()
    compose_text = (cloud_root / "docker-compose.prod.yml").read_text()
    runtime_compose_text = (cloud_root / "docker-compose.runtime.yml").read_text()
    package_json = (cloud_root / "package.json").read_text()
    frontend_dockerfile = (cloud_root / "frontend" / "Dockerfile").read_text()
    bundle_script = (cloud_root / "deploy" / "bundle-images.sh").read_text()
    remote_load_script = (cloud_root / "deploy" / "remote-load-and-up.sh").read_text()
    static_terms_deploy_script = (
        cloud_root / "deploy" / "deploy-static-terms-to-ssh-host.sh"
    ).read_text()
    next_config = (cloud_root / "frontend" / "next.config.mjs").read_text()
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

    assert "CLOUD_API_BASE_URL: process.env.CLOUD_API_BASE_URL" not in next_config
    assert "CLOUD_PUBLIC_BASE_URL: process.env.CLOUD_PUBLIC_BASE_URL" not in next_config

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
    assert "location /open/" in nginx_prod_conf
    prod_open_block = nginx_prod_conf.split("location /open/ {", 1)[1].split("\n    }", 1)[0]
    prod_portal_api_block = nginx_prod_conf.split("location /portal/v1/ {", 1)[1].split(
        "\n    }",
        1,
    )[0]
    assert "proxy_set_header Connection" not in prod_open_block
    assert "proxy_set_header Connection" not in prod_portal_api_block
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
    assert "./site:/usr/share/nginx/html/npcink-site:ro" in compose_text
    assert "\"${BASE_URL%/}/terms\"" in remote_smoke_script
    assert "/terms/en/terms.html" in remote_smoke_script
    assert "/terms/zh/terms.html" in remote_smoke_script
    assert "/terms/styles.css" in remote_smoke_script
    assert "--skip-terms-checks" in remote_smoke_script
    assert "Npcink Cloud Legal Documents" in remote_smoke_script
    assert "data.result.images" in remote_smoke_script
    assert 'INCLUDE_EXTERNAL_IMAGES="${NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES:-0}"' in (
        bundle_script
    )
    assert 'if [ "${INCLUDE_EXTERNAL_IMAGES}" = "1" ]; then' in bundle_script
    assert "postgres.tar.gz" in bundle_script
    assert "otel-collector.tar.gz" in bundle_script
    assert "jaeger.tar.gz" in bundle_script
    assert "otel-collector:" in runtime_compose_text
    assert "jaeger:" in runtime_compose_text
    jaeger_localhost_port = (
        "${NPCINK_CLOUD_JAEGER_BIND_HOST:-127.0.0.1}:"
        "${NPCINK_CLOUD_JAEGER_UI_PORT:-16686}:16686"
    )
    assert jaeger_localhost_port in compose_text
    assert jaeger_localhost_port in runtime_compose_text
    otlp_exporter_default = (
        "NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT: "
        "${NPCINK_CLOUD_OTEL_EXPORTER_OTLP_ENDPOINT:-"
        "http://otel-collector:4318/v1/traces}"
    )
    trace_sink_default = (
        "NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT: "
        "${NPCINK_CLOUD_OTEL_TRACE_SINK_OTLP_ENDPOINT:-jaeger:4317}"
    )
    trace_query_default = (
        "NPCINK_CLOUD_OTEL_TRACE_QUERY_URL: "
        "${NPCINK_CLOUD_OTEL_TRACE_QUERY_URL:-http://127.0.0.1:"
        "${NPCINK_CLOUD_JAEGER_UI_PORT:-16686}}"
    )
    assert otlp_exporter_default in runtime_compose_text
    assert trace_sink_default in runtime_compose_text
    assert trace_query_default in runtime_compose_text
    assert 'if service_exists otel-collector; then' in remote_load_script
    assert 'if service_exists jaeger; then' in remote_load_script
    assert '-C "${CLOUD_DIR}" dist/worker.tar.gz' not in bundle_script
    assert '-C "${CLOUD_DIR}" dist/callback-worker.tar.gz' not in bundle_script
    assert '-C "${CLOUD_DIR}" dist/ops-worker.tar.gz' not in bundle_script
    assert "build api worker callback-worker ops-worker" not in bundle_script
    assert 'GZIP_LEVEL="${NPCINK_CLOUD_BUNDLE_GZIP_LEVEL:-1}"' in bundle_script
    build_cache_scope_prefix = (
        'BUILD_CACHE_SCOPE_PREFIX="${NPCINK_CLOUD_BUILD_CACHE_SCOPE_PREFIX:-npcink-ai-cloud}"'
    )
    assert build_cache_scope_prefix in bundle_script
    assert '--cache-from "type=gha,scope=${BUILD_CACHE_SCOPE_PREFIX}-${cache_scope}"' in (
        bundle_script
    )
    build_cache_to = (
        '--cache-to "type=gha,scope=${BUILD_CACHE_SCOPE_PREFIX}-${cache_scope},'
        'mode=max,ignore-error=true"'
    )
    assert build_cache_to in bundle_script
    assert "set_build_cache_args api" in bundle_script
    assert "set_build_cache_args frontend" in bundle_script
    assert 'gzip "-${GZIP_LEVEL}" > "${output}"' in bundle_script
    assert 'gzip "-${GZIP_LEVEL}" > "${DIST_DIR}/deploy-bundle.tgz"' in bundle_script
    assert "actions: write" in ci_workflow
    external_images_default = (
        "NPCINK_CLOUD_INCLUDE_EXTERNAL_IMAGES: "
        "${{ vars.PROD_INCLUDE_EXTERNAL_IMAGES || '0' }}"
    )
    assert external_images_default in ci_workflow
    assert external_images_default in deploy_workflow
    assert "deploy_required:" in ci_workflow
    assert "needs.classify.outputs.deploy_required == 'true'" in ci_workflow
    assert ".github/workflows/ci.yml|.github/workflows/deploy-production.yml" in (
        ci_workflow
    )
    assert "docker-compose*.yml|Dockerfile|deploy/*.sh" in ci_workflow
    assert "docker tag npcink-ai-cloud-api:prod npcink-ai-cloud-worker:prod" in remote_load_script
    assert "otel-collector.tar.gz" in remote_load_script
    assert "jaeger.tar.gz" in remote_load_script
    assert "static_terms_only" in ci_workflow
    assert "site/terms/*" in ci_workflow
    assert "needs: [classify, backend, frontend, static-terms]" in ci_workflow
    assert "backend-scope:" in ci_workflow
    assert "backend-targeted:" in ci_workflow
    assert "backend-static:" in ci_workflow
    assert "backend-pytest:" in ci_workflow
    assert "matrix:" in ci_workflow
    assert "shard: [1, 2, 3]" in ci_workflow
    assert "scripts/select-pytest-shard.py" in ci_workflow
    assert "backend pytest shards did not pass" in ci_workflow
    assert "bash deploy/deploy-static-terms-to-ssh-host.sh" in ci_workflow
    assert "post-production-smoke:" in ci_workflow
    assert "needs['deploy-production'].result == 'success'" in ci_workflow
    assert "bash deploy/small-customer-trial-preflight.sh" in ci_workflow
    assert "--require-alipay-enabled" in ci_workflow
    assert "bash deploy/release-smoke.sh --base-url" in ci_workflow
    assert "ci-observability:" in ci_workflow
    assert "python3 scripts/report-release-timing.py" in ci_workflow
    assert "artifacts/pytest-backend-shard-${{ matrix.shard }}.xml" in ci_workflow
    assert "artifacts/pytest-files-shard-${{ matrix.shard }}.txt" in ci_workflow
    assert "python3 scripts/report-junit-timing.py" in ci_workflow
    assert "actions/checkout@v6" in ci_workflow
    assert "actions/setup-node@v6" in ci_workflow
    assert "actions/setup-python@v6" in ci_workflow
    assert "pnpm/action-setup@v6" in ci_workflow
    assert "docker/setup-buildx-action@v4" in ci_workflow
    assert "gitleaks/gitleaks-action@v3" in ci_workflow
    assert "args: detect --source" not in ci_workflow
    assert "actions/upload-artifact@v7" in ci_workflow
    assert "pytest-backend-timing-shard-${{ matrix.shard }}" in ci_workflow
    assert (cloud_root / "ci" / "pytest-backend-durations.json").is_file()
    assert "deploy:static-terms:ssh" in package_json
    assert "release:junit-timing" in package_json
    assert "CURRENT_LINK=\"${REMOTE_DIR}/current\"" in static_terms_deploy_script
    assert "tar czf \"${TERMS_BUNDLE}\" -C \"${ROOT_DIR}/site\" terms" in (
        static_terms_deploy_script
    )
    assert "assert_public_static_page \"/terms\"" in static_terms_deploy_script
    assert "Static terms deploy completed" in static_terms_deploy_script

    assert "name: Production Maintenance" in maintenance_workflow
    assert "github.ref == 'refs/heads/production'" in maintenance_workflow
    assert "environment: production" in maintenance_workflow
    assert "docker container prune -f" in maintenance_workflow
    assert "docker image prune -af" in maintenance_workflow
    assert "docker builder prune -af" in maintenance_workflow
    assert "docker system prune" not in maintenance_workflow
    assert "--volumes" not in maintenance_workflow
    assert "rm -rf -- \"${release_dir}\"" in maintenance_workflow


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


def test_release_gate_documents_current_cloud_blockers() -> None:
    cloud_root = _cloud_root()
    checklist_text = (cloud_root / "deploy" / "RELEASE_CHECKLIST.md").read_text()
    playbook_text = (cloud_root / "deploy" / "OPS_PLAYBOOK.md").read_text()
    release_smoke_script = (cloud_root / "deploy" / "release-smoke.sh").read_text()
    release_smoke_env_example = (
        cloud_root / "deploy" / "release-smoke.env.example"
    ).read_text()
    release_smoke_workflow = (
        cloud_root / ".github" / "workflows" / "release-smoke.yml"
    ).read_text()

    for marker in (
        "repo ready",
        "env required",
        "operator required",
        "smoke required",
        "real Alipay transaction",
        "real WordPress reconnect",
        "formal release smoke",
        "schema drift baseline",
        "OTLP sink",
        "24-hour observation",
    ):
        assert marker in checklist_text

    assert "the PC launch candidate is deployed to production" in checklist_text
    assert "Cloud must not be treated as GA-ready" in checklist_text
    assert "deploy/release-smoke.sh" in checklist_text
    assert "Release Smoke" in checklist_text
    assert "manually run the `Release Smoke` workflow from the `production` branch" in (
        checklist_text
    )
    assert "deploy/RELEASE_CHECKLIST.md" in playbook_text
    assert "the release is blocked" in playbook_text
    assert "Do not replace it with a second release entry point" in playbook_text
    assert "deploy/remote-smoke.sh" in release_smoke_script
    assert "--runtime-site-id" in release_smoke_script
    assert "Signed hosted runtime smoke." in release_smoke_env_example
    assert "signed `POST /v1/runtime/execute`" in checklist_text
    assert "signed `GET /v1/catalog/models`" in playbook_text

    for removed_marker in (
        "/v1/addon/dashboard",
        "/v1/addon/providers/release-summary",
        "signed addon projection reads",
        "Signed addon projection smoke.",
    ):
        assert removed_marker not in release_smoke_script
        assert removed_marker not in checklist_text
        assert removed_marker not in playbook_text
        assert removed_marker not in release_smoke_env_example

    assert "workflow_dispatch:" in release_smoke_workflow
    assert "github.ref == 'refs/heads/production'" in release_smoke_workflow
    assert "environment: production" in release_smoke_workflow
    assert "NPCINK_CLOUD_INTERNAL_AUTH_TOKEN" in release_smoke_workflow
    assert "NPCINK_CLOUD_ADMIN_BOOTSTRAP_TOKEN" in release_smoke_workflow
    assert "NPCINK_CLOUD_RELEASE_MEMBER_EMAIL" in release_smoke_workflow
    assert "NPCINK_CLOUD_PORTAL_LOGIN_CODE" in release_smoke_workflow
    assert "NPCINK_CLOUD_RELEASE_SITE_ID" in release_smoke_workflow
    assert "NPCINK_CLOUD_RELEASE_KEY_ID" in release_smoke_workflow
    assert "NPCINK_CLOUD_RELEASE_KEY_SECRET" in release_smoke_workflow
    assert "--require-smoke-env" in release_smoke_workflow
    assert "--run-release-smoke" in release_smoke_workflow
    assert "--require-alipay-enabled" in release_smoke_workflow
    assert 'if [ -z "${LOGIN_CODE}" ]; then' in release_smoke_script
    assert "Using pre-issued Portal login code" in release_smoke_script
    assert "skips requesting a replacement code" in release_smoke_env_example
    assert release_smoke_script.count('"Origin: ${BASE_URL%/}"') >= 3
    assert release_smoke_script.count('"data.principal_id"') >= 3
    assert '"data.member_ref"' not in release_smoke_script
    assert '"data.platform_admin_ref"' not in release_smoke_script
    assert '200 | 303' in release_smoke_script


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
        "Do not push or deploy to Gitee. Current project source control is GitHub-only.",
        "pnpm run check:release-policy",
    ):
        assert marker in agents_text
