FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN set -eux; \
    for attempt in 1 2 3; do \
        apt-get -o Acquire::Retries=5 update; \
        if DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=5 install -y --fix-missing --no-install-recommends build-essential; then \
            break; \
        fi; \
        if [ "${attempt}" = "3" ]; then \
            exit 1; \
        fi; \
        rm -rf /var/lib/apt/lists/*; \
        sleep "$((attempt * 5))"; \
    done; \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY deploy ./deploy

ARG PACKAGE_EXTRAS=
ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_TRUSTED_HOST=

RUN if [ -n "${PIP_INDEX_URL}" ]; then export PIP_INDEX_URL="${PIP_INDEX_URL}"; fi \
    && if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL}"; fi \
    && if [ -n "${PIP_TRUSTED_HOST}" ]; then export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}"; fi \
    && pip install --no-cache-dir --retries 10 --timeout 60 --upgrade pip \
    && pip install --no-cache-dir --retries 10 --timeout 60 "setuptools>=69" wheel \
    && pip wheel --no-cache-dir --retries 10 --timeout 60 --no-build-isolation --wheel-dir /tmp/wheels ".${PACKAGE_EXTRAS}"

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app \
    && mkdir -p /app/.runtime \
    && chown -R app:app /app /home/app

COPY --from=builder /tmp/wheels /tmp/wheels
COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY deploy ./deploy

ARG PACKAGE_EXTRAS=
ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_TRUSTED_HOST=

RUN if [ -n "${PIP_INDEX_URL}" ]; then export PIP_INDEX_URL="${PIP_INDEX_URL}"; fi \
    && if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL}"; fi \
    && if [ -n "${PIP_TRUSTED_HOST}" ]; then export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}"; fi \
    && pip install --no-cache-dir --retries 10 --timeout 60 --upgrade pip \
    && pip install --no-cache-dir --retries 10 --timeout 60 --no-index --find-links /tmp/wheels "npcink-ai-cloud${PACKAGE_EXTRAS}" \
    && rm -rf /tmp/wheels

USER app

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
