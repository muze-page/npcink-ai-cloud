PYTHON ?= python3
SITE_ID ?= site_smoke
KEY_ID ?= key_default
SECRET ?= magick-cloud-test-secret
SCOPES ?= catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read
PYTEST_ARGS ?=
CHANGED_BASE_REF ?= origin/master

.PHONY: baseline bootstrap-dev dev test test-local lint lint-changed perimeter frontend-sync frontend-watch migrate seed-dev rollup recognition-refresh bundle deploy-smoke deploy-ssh provider-status env-ssh secret-rotation-check model-ops-release-check model-ops-ia-check

baseline:
	.venv/bin/pytest --version
	docker compose -f docker-compose.dev.yml run --rm api python -m pytest tests/domain/test_runtime_queue.py -q
	docker compose -f docker-compose.dev.yml run --rm api python -m pytest tests/domain/test_usage_service.py -q
	docker compose -f docker-compose.dev.yml run --rm api python -m pytest tests/api/test_service_routes.py tests/api/test_portal_routes.py -q -k 'keys'
	# Record current static-analysis debt without blocking hardening lanes.
	docker compose -f docker-compose.dev.yml run --rm api python -m ruff check . || true
	docker compose -f docker-compose.dev.yml run --rm api python -m mypy app || true
	$(MAKE) perimeter
	.venv/bin/pytest tests/api/test_runtime_execute.py tests/api/test_addon_routes.py tests/contract/test_runtime_contract.py tests/domain/test_provider_connections_admin.py tests/domain/test_commercial_runtime_defaults.py -q
	cd frontend && pnpm run type-check

bootstrap-dev:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -e '.[dev]'
	cd frontend && pnpm install --lockfile-dir . --frozen-lockfile

dev:
	docker compose -f docker-compose.dev.yml up --build

test:
	docker compose -f docker-compose.dev.yml run --rm api python -m pytest

test-local:
	.venv/bin/pytest $(PYTEST_ARGS)

lint:
	docker compose -f docker-compose.dev.yml run --rm api python -m ruff check . && \
	docker compose -f docker-compose.dev.yml run --rm api python -m mypy app

lint-changed:
	MAGICK_CLOUD_CHANGED_BASE_REF="$(CHANGED_BASE_REF)" bash scripts/check-changed-python-quality.sh

perimeter:
	bash scripts/check-cloud-perimeter.sh

frontend-sync:
	node scripts/watch-cloud-frontend-sync.js --once

frontend-watch:
	node scripts/watch-cloud-frontend-sync.js

migrate:
	docker compose -f docker-compose.dev.yml run --rm api alembic upgrade head

seed-dev:
	docker compose -f docker-compose.dev.yml run --rm api python -m app.dev.seed_runtime \
		--site-id "$(SITE_ID)" \
		--key-id "$(KEY_ID)" \
		--secret "$(SECRET)" \
		--scopes "$(SCOPES)"

rollup:
	docker compose -f docker-compose.dev.yml run --rm api python -m app.workers.usage_rollup

recognition-refresh:
	docker compose -f docker-compose.dev.yml run --rm api python -m app.workers.recognition_evidence_refresh

router-performance:
	docker compose -f docker-compose.dev.yml run --rm api python -m app.workers.router_performance_snapshot

router-diagnostics:
	docker compose -f docker-compose.dev.yml run --rm api python -m app.workers.router_diagnostics_summary

latency-probe:
	docker compose -f docker-compose.dev.yml run --rm api python -m app.workers.latency_probe_summary

alert-provider-degradation:
	docker compose -f docker-compose.dev.yml run --rm api python -m app.workers.alert_provider_degradation

bundle:
	bash deploy/bundle-images.sh

deploy-smoke:
	bash scripts/cloud-deploy-bundle-smoke-flow.sh

deploy-ssh:
	bash deploy/deploy-to-ssh-host.sh

provider-status:
	bash deploy/remote-provider-status.sh

env-ssh:
	bash deploy/env-to-ssh-host.sh

secret-rotation-check:
	bash deploy/validate-secret-rotation.sh

model-ops-release-check:
	docker compose -f docker-compose.dev.yml run --rm api python -m app.dev.model_ops_release_preflight

model-ops-ia-check:
	cd frontend && pnpm run type-check
	cd frontend && pnpm run test:i18n-contract
	cd frontend && pnpm run test:e2e:admin-operator-path
