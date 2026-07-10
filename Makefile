PYTHON ?= python3
SITE_ID ?= site_smoke
KEY_ID ?= key_default
SECRET ?= npcink-cloud-test-secret
SCOPES ?= catalog:read,runtime:resolve,runtime:execute,runtime:read,stats:read
PYTEST_ARGS ?=
CHANGED_BASE_REF ?= origin/master
TEST_PROVIDER_ENV = NPCINK_CLOUD_OPENAI_API_KEY=
DOCKER_TEST_PROVIDER_ENV = -e NPCINK_CLOUD_OPENAI_API_KEY=

.PHONY: baseline bootstrap-dev dev test test-local lint lint-changed mypy-full mypy-targeted mypy-commercial-runtime perimeter frontend-sync frontend-watch frontend-doctor frontend-recover migrate seed-dev rollup bundle deploy-smoke deploy-ssh provider-status env-ssh secret-rotation-check

baseline:
	.venv/bin/pytest --version
	pnpm run test:anti-drift
	docker compose -f docker-compose.dev.yml run --rm $(DOCKER_TEST_PROVIDER_ENV) api python -m pytest tests/domain/test_runtime_queue.py -q
	docker compose -f docker-compose.dev.yml run --rm $(DOCKER_TEST_PROVIDER_ENV) api python -m pytest tests/domain/test_usage_service.py -q
	docker compose -f docker-compose.dev.yml run --rm $(DOCKER_TEST_PROVIDER_ENV) api python -m pytest tests/api/test_service_routes.py tests/api/test_portal_routes.py -q -k 'keys'
	docker compose -f docker-compose.dev.yml run --rm api python -m ruff check .
	docker compose -f docker-compose.dev.yml run --rm api python -m mypy app
	$(MAKE) perimeter
	$(TEST_PROVIDER_ENV) .venv/bin/pytest tests/api/test_runtime_execute.py tests/contract/test_addon_projection_contract.py tests/contract/test_runtime_contract.py tests/domain/test_commercial_runtime_defaults.py -q
	cd frontend && pnpm run type-check
	cd frontend && pnpm run lint

bootstrap-dev:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -e '.[dev]'
	pnpm --dir frontend install --frozen-lockfile

dev:
	docker compose -f docker-compose.dev.yml up --build

test:
	docker compose -f docker-compose.dev.yml run --rm $(DOCKER_TEST_PROVIDER_ENV) api python -m pytest

test-local:
	$(TEST_PROVIDER_ENV) .venv/bin/pytest $(PYTEST_ARGS)

lint:
	docker compose -f docker-compose.dev.yml run --rm api python -m ruff check . && \
	docker compose -f docker-compose.dev.yml run --rm api python -m mypy app

lint-changed:
	NPCINK_CLOUD_CHANGED_BASE_REF="$(CHANGED_BASE_REF)" bash scripts/check-changed-python-quality.sh

mypy-full:
	.venv/bin/mypy app

mypy-targeted:
	bash scripts/mypy-targeted.sh $(MYPY_TARGETS)

mypy-commercial-runtime:
	bash scripts/mypy-targeted.sh --profile commercial-runtime

perimeter:
	bash scripts/check-cloud-perimeter.sh

frontend-sync:
	node scripts/watch-cloud-frontend-sync.js --once

frontend-watch:
	node scripts/watch-cloud-frontend-sync.js

frontend-doctor:
	bash scripts/dev-frontend-doctor.sh

frontend-recover:
	bash scripts/dev-frontend-recover.sh

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
