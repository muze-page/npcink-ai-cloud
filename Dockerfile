FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_TRUSTED_HOST=

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY migrations ./migrations
COPY deploy ./deploy

RUN if [ -n "${PIP_INDEX_URL}" ]; then export PIP_INDEX_URL="${PIP_INDEX_URL}"; fi \
    && if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL}"; fi \
    && if [ -n "${PIP_TRUSTED_HOST}" ]; then export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}"; fi \
    && pip install --no-cache-dir --retries 10 --timeout 60 "setuptools>=69" wheel \
    && pip wheel --no-cache-dir --retries 10 --timeout 60 --no-build-isolation --wheel-dir /tmp/wheels ".[dev]"

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_TRUSTED_HOST=

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

RUN if [ -n "${PIP_INDEX_URL}" ]; then export PIP_INDEX_URL="${PIP_INDEX_URL}"; fi \
    && if [ -n "${PIP_EXTRA_INDEX_URL}" ]; then export PIP_EXTRA_INDEX_URL="${PIP_EXTRA_INDEX_URL}"; fi \
    && if [ -n "${PIP_TRUSTED_HOST}" ]; then export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST}"; fi \
    && pip install --no-cache-dir --retries 10 --timeout 60 --no-index --find-links /tmp/wheels "magick-ai-cloud[dev]" \
    && rm -rf /tmp/wheels

USER app

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
