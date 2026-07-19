#!/usr/bin/env python3
"""P5-B4 disposable external runtime load/soak proof.

The harness deliberately drives a real Gunicorn API and the real runtime queue
worker over HTTP/Redis/PostgreSQL.  It never creates the application in process.
Quick mode is useful only for harness validation; acceptance needs three fresh,
independent formal records and the ``aggregate`` command.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median, median_low
from typing import cast
from urllib.parse import urlsplit

import httpx
from alembic import command
from alembic.config import Config as AlembicConfig
from redis import Redis
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.adapters.providers.registry import build_enabled_connection_provider_adapters
from app.core.config import Settings
from app.core.db import dispose_engine, get_session
from app.core.models import (
    AccountEntitlementSnapshot,
    MediaArtifact,
    PlanVersion,
    ProviderCallRecord,
    RunRecord,
    UsageMeterEvent,
)
from app.core.security import (
    build_body_digest,
    build_canonical_request,
    build_hmac_signature,
)
from app.domain.catalog.service import CatalogService
from app.domain.commercial.service import CommercialService
from app.domain.provider_connections.service import ProviderConnectionAdminService

CONTRACT_ID = "p5_b4_external_runtime_load_soak_proof.v5"
DISPOSABLE_CONFIRMATION = "I_UNDERSTAND_THIS_DESTROYS_PROOF_DATA"
DATABASE_HOST = "proof-postgres"
DATABASE_NAME = "npcink_p5_b4_proof"
DATABASE_USER = "npcink_p5_b4"
DATABASE_COMMENT = "p5_b4_external_runtime_load_soak_proof_v5"
REDIS_HOST = "proof-redis"
REDIS_DATABASE = 15
REDIS_PREFIX = "p5_b4:external_runtime_proof"
SITE_COUNT = 8
FORMAL_RECORDS = 3
FORMAL_DURATION_SECONDS = 600
FORMAL_WARMUP_SECONDS = 30
FORMAL_CONCURRENCY = 8
FORMAL_REQUEST_RATE = 8.0
FORMAL_QUEUE_BURST = 64
DEFAULT_WORKER_POLL_SECONDS = 5
DEFAULT_WORKER_BATCH_SIZE = 8
FORMAL_WORKER_REPLICAS = 2
FORMAL_PROVIDER_DELAY_MS = 150
FORMAL_RESOURCE_IDLE_RECOVERY_SECONDS = 60
FORMAL_RESOURCE_IDLE_MIN_SAMPLES = 12
FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS = 55.0
FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES = 12
FORMAL_RSS_ENDPOINT_WINDOW_MIN_SPAN_SECONDS = 55.0
FORMAL_RSS_IDLE_BLOCK_COUNT = 4
PROOF_PLAN_ID = "plan_p5_b4_disposable"
PROOF_PLAN_VERSION_ID = "plan_version_p5_b4_disposable_v1"
PROOF_MAX_AI_CREDITS_PER_SITE_PERIOD = 10_000.0
EXPECTED_DATASET_ID = "p5_b4_runtime_8_sites_v5"
EXPECTED_DATASET_CONFIG: dict[str, object] = {
    "commercial": {"max_ai_credits_per_site_period": 10_000.0},
    "contract": "p5_b4_runtime_dataset.v5",
    "formal": {
        "baselines": 3,
        "concurrency": 8,
        "queue_burst": 64,
        "request_rate": 8,
        "resource_idle_minimum_sample_count": 12,
        "resource_idle_minimum_span_seconds": 55,
        "resource_idle_recovery_seconds": 60,
        "resource_process_scope": "pid1_service_trees_aggregate_stable_cohort_v3",
        "rss_endpoint_window_min_span_seconds": 55,
        "rss_endpoint_window_sample_count": 12,
        "rss_growth_method": "steady_endpoint_window_median_v1",
        "rss_growth_percent_max": 10,
        "rss_idle_method": "four_block_budget_confirmation_v1",
        "soak_seconds": 600,
        "warmup_seconds": 30,
    },
    "provider_delay_ms": 150,
    "quick": {
        "baselines": 1,
        "concurrency": 2,
        "queue_burst": 8,
        "request_rate": 2,
        "soak_seconds": 5,
        "warmup_seconds": 3,
    },
    "sites": 8,
    "worker": {"batch_size": 8, "poll_seconds": 5, "replicas": 2},
}
RESOURCE_HEADER = (
    "elapsed_seconds\tapi_rss_bytes\tapi_fd_count\tworker_rss_bytes\t"
    "worker_fd_count\tpostgres_connections\tapi_restart_count\t"
    "worker_restart_count\tapi_running\tworker_running\tapi_process_count\t"
    "worker_process_count\tapi_process_identity_sha256\t"
    "worker_process_identity_sha256"
)
THRESHOLDS = {
    "unexpected_5xx_max": 0,
    "accepted_rate_min": 0.99,
    "completed_rate_min": 0.99,
    "api_p95_ms_max": 500.0,
    "api_p99_ms_max": 1_000.0,
    "queue_wait_poll_multiple_max": 2.0,
    "rss_growth_percent_max": 10.0,
    "achieved_rate_ratio_min": 0.95,
    "scheduler_drift_ms_max": 1_000.0,
    "duplicate_count_max": 0,
    "residue_count_max": 0,
}
RECORD_CHECK_IDS = (
    "unexpected_5xx_zero",
    "transport_http_failures_zero",
    "accepted_rate",
    "completed_rate",
    "provider_excluded_p95",
    "provider_excluded_p99",
    "persistent_provider_latency_complete",
    "queue_requested_accepted_completed_exact",
    "queue_timing_evidence_complete",
    "queue_wait",
    "identifier_set_exact",
    "observation_diagnostics_complete",
    "proof_fixture_rejections_zero",
    "provider_usage_integrity",
    "cross_site_and_result_read_isolation",
    "runtime_queue_residue_zero",
    "artifacts_returned_to_manifest_baseline",
    "rss_growth",
    "process_cohort_stable",
    "api_fd_not_sustained_growth",
    "worker_fd_not_sustained_growth",
    "db_connections_not_sustained_growth",
    "resource_samples_complete",
    "services_survived",
    "service_restarts_zero",
    "formal_clean_revision_requirement_satisfied",
    "achieved_rate",
    "scheduler_drift",
    "real_concurrency_observed",
)
RECORD_BOUNDARY = {
    "cloud_role": "hosted_runtime_and_worker_evidence_only",
    "external_http_gunicorn": True,
    "local_control_plane_unchanged": True,
    "wordpress_write_owner_unchanged": True,
    "new_runtime_infrastructure": False,
}
RECORD_REDACTION = {
    "aggregate_only": True,
    "prompt_fields_emitted": False,
    "result_fields_emitted": False,
    "secret_fields_emitted": False,
    "raw_run_or_site_identifiers_emitted": False,
    "real_provider_credentials_present": False,
}
RECORD_LIMITATIONS = (
    "deterministic_local_provider_excludes_upstream_provider_latency_and_quality",
    "quick_mode_is_never_acceptance_evidence",
    "one_formal_record_cannot_claim_acceptance",
    "engineering_proof_does_not_define_a_production_slo",
)
PROVIDER_CREDENTIAL_ENV_NAMES = (
    "NPCINK_CLOUD_OPENAI_API_KEY",
    "NPCINK_CLOUD_ANTHROPIC_API_KEY",
    "NPCINK_CLOUD_MINIMAX_API_KEY",
    "NPCINK_CLOUD_LITELLM_API_KEY",
    "NPCINK_CLOUD_VLLM_API_KEY",
    "NPCINK_CLOUD_TEI_API_KEY",
    "NPCINK_CLOUD_OPENROUTER_API_KEY",
    "NPCINK_CLOUD_SILICONFLOW_API_KEY",
    "NPCINK_CLOUD_HUGGINGFACE_API_TOKEN",
)
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PROOF_REQUEST_REF_PATTERN = re.compile(r"^[a-p]{64}$")
PROOF_REQUEST_REF_ENCODE = str.maketrans("0123456789abcdef", "abcdefghijklmnop")
PROOF_REQUEST_REF_DECODE = str.maketrans("abcdefghijklmnop", "0123456789abcdef")
SUCCESS_RUNTIME_STATUSES = frozenset({"queued", "running", "succeeded"})
PERSISTED_RUNTIME_STATUSES = SUCCESS_RUNTIME_STATUSES | {"failed"}
DIAGNOSTIC_HTTP_BUCKETS = (
    "200",
    "400",
    "401",
    "403",
    "404",
    "409",
    "422",
    "429",
    "5xx",
    "transport",
    "other",
)
DIAGNOSTIC_ERROR_BUCKETS = (
    "none",
    "auth.invalid_key",
    "auth.invalid_signature",
    "auth.invalid_site",
    "auth.rate_limit_exceeded",
    "auth.replay_blocked",
    "auth.scope_denied",
    "auth.site_mismatch",
    "commercial.entitlement_denied",
    "commercial.quota_exceeded",
    "commercial.subscription_inactive",
    "routing.execution_kind_mismatch",
    "routing.no_candidates",
    "routing.profile_not_found",
    "runtime.contract_profile_mismatch",
    "runtime.contract_task_backend_required",
    "runtime.pii_classification_required",
    "runtime.provider_not_configured",
    "runtime.site_not_active",
    "runtime.site_not_provisioned",
    "transport.timeout",
    "transport.connect_error",
    "transport.read_error",
    "transport.write_error",
    "transport.close_error",
    "transport.protocol_error",
    "transport.proxy_error",
    "transport.unsupported_protocol",
    "transport.too_many_redirects",
    "transport.network_error",
    "transport.request_error",
    "other",
)
DIAGNOSTIC_RUNTIME_BUCKETS = (
    "none",
    "queued",
    "running",
    "succeeded",
    "failed",
    "canceled",
    "cancel_requested",
    "other",
)
DIAGNOSTIC_PHASE_BUCKETS = (
    "cross_site",
    "concurrency_probe",
    "queue",
    "warmup",
    "soak",
    "other",
)
DIAGNOSTIC_SCHEMA = "p5_b4_observation_diagnostics.v2"
PROOF_FIXTURE_REJECTION_BUCKETS = (
    "auth.invalid_key",
    "auth.invalid_signature",
    "auth.invalid_site",
    "auth.rate_limit_exceeded",
    "auth.replay_blocked",
    "auth.scope_denied",
    "commercial.entitlement_denied",
    "commercial.quota_exceeded",
    "commercial.subscription_inactive",
    "routing.execution_kind_mismatch",
    "routing.no_candidates",
    "routing.profile_not_found",
    "runtime.contract_profile_mismatch",
    "runtime.contract_task_backend_required",
    "runtime.pii_classification_required",
    "runtime.provider_not_configured",
    "runtime.site_not_active",
    "runtime.site_not_provisioned",
)


class ProofFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(slots=True)
class Shape:
    mode: str
    duration_seconds: int
    warmup_seconds: int
    concurrency: int
    request_rate: float
    queue_burst: int

    @property
    def formal(self) -> bool:
        return self.mode == "formal"


@dataclass(slots=True)
class Observation:
    request_hash: str
    run_id: str
    http_status: int
    runtime_status: str
    error_code: str
    elapsed_ms: float
    phase: str

    @property
    def success_envelope(self) -> bool:
        return self.http_status == 200 and self.runtime_status in SUCCESS_RUNTIME_STATUSES

    @property
    def accepted(self) -> bool:
        return self.success_envelope and bool(self.run_id) and not self.error_code


@dataclass(frozen=True, slots=True)
class ResourceSample:
    elapsed_seconds: float
    api_rss_bytes: int
    api_fd_count: int
    worker_rss_bytes: int
    worker_fd_count: int
    postgres_connections: int
    api_restart_count: int
    worker_restart_count: int
    api_running: int
    worker_running: int
    api_process_count: int
    worker_process_count: int
    api_process_identity_sha256: str
    worker_process_identity_sha256: str


def _fixed_counts(keys: tuple[str, ...]) -> dict[str, int]:
    return dict.fromkeys(keys, 0)


def _diagnostic_http_bucket(item: Observation) -> str:
    if item.error_code.startswith("transport."):
        return "transport"
    if 500 <= item.http_status <= 599:
        return "5xx"
    value = str(item.http_status)
    return value if value in DIAGNOSTIC_HTTP_BUCKETS else "other"


def _diagnostic_error_bucket(value: str) -> str:
    normalized = value or "none"
    return normalized if normalized in DIAGNOSTIC_ERROR_BUCKETS else "other"


def _diagnostic_runtime_bucket(value: str) -> str:
    normalized = value or "none"
    return normalized if normalized in DIAGNOSTIC_RUNTIME_BUCKETS else "other"


def _diagnostic_phase_bucket(value: str) -> str:
    return value if value in DIAGNOSTIC_PHASE_BUCKETS else "other"


def _response_shape_valid(item: Observation) -> bool:
    if item.http_status == 200:
        if item.runtime_status not in PERSISTED_RUNTIME_STATUSES or not item.run_id:
            return False
        if item.runtime_status in SUCCESS_RUNTIME_STATUSES:
            return not item.error_code
        return item.runtime_status == "failed" and bool(item.error_code)
    return not item.run_id and not item.runtime_status


def _diagnostic_summary(
    observations: list[Observation],
) -> dict[str, object]:
    by_http_status = _fixed_counts(DIAGNOSTIC_HTTP_BUCKETS)
    by_error_code = _fixed_counts(DIAGNOSTIC_ERROR_BUCKETS)
    by_runtime_status = _fixed_counts(DIAGNOSTIC_RUNTIME_BUCKETS)
    by_phase = _fixed_counts(DIAGNOSTIC_PHASE_BUCKETS)
    by_phase_and_error_code = {
        phase: _fixed_counts(DIAGNOSTIC_ERROR_BUCKETS) for phase in DIAGNOSTIC_PHASE_BUCKETS
    }
    response_shape_violation_count = 0
    negative_control_count = 0
    for item in observations:
        error_bucket = _diagnostic_error_bucket(item.error_code)
        phase_bucket = _diagnostic_phase_bucket(item.phase)
        by_http_status[_diagnostic_http_bucket(item)] += 1
        by_error_code[error_bucket] += 1
        by_runtime_status[_diagnostic_runtime_bucket(item.runtime_status)] += 1
        by_phase[phase_bucket] += 1
        by_phase_and_error_code[phase_bucket][error_bucket] += 1
        response_shape_violation_count += int(not _response_shape_valid(item))
        negative_control_count += int(
            item.phase == "cross_site"
            and item.http_status == 400
            and item.error_code == "auth.site_mismatch"
        )
    other_count = (
        by_http_status["other"]
        + by_error_code["other"]
        + by_runtime_status["other"]
        + by_phase["other"]
    )
    negative_control_included = negative_control_count == 1
    return {
        "schema_version": DIAGNOSTIC_SCHEMA,
        "sample_count": len(observations),
        "by_http_status": by_http_status,
        "by_error_code": by_error_code,
        "by_runtime_status": by_runtime_status,
        "by_phase": by_phase,
        "by_phase_and_error_code": by_phase_and_error_code,
        "other_count": other_count,
        "response_shape_violation_count": response_shape_violation_count,
        "negative_control_included": negative_control_included,
        "complete": (
            other_count == 0 and response_shape_violation_count == 0 and negative_control_included
        ),
    }


def _diagnostics_valid(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    expected_keys = {
        "schema_version",
        "sample_count",
        "by_http_status",
        "by_error_code",
        "by_runtime_status",
        "by_phase",
        "by_phase_and_error_code",
        "other_count",
        "response_shape_violation_count",
        "negative_control_included",
        "complete",
    }
    if set(payload) != expected_keys or payload.get("schema_version") != DIAGNOSTIC_SCHEMA:
        return False
    sample_count = payload.get("sample_count")
    other_count = payload.get("other_count")
    violation_count = payload.get("response_shape_violation_count")
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (sample_count, other_count, violation_count)
    ):
        return False
    dimensions = (
        ("by_http_status", DIAGNOSTIC_HTTP_BUCKETS),
        ("by_error_code", DIAGNOSTIC_ERROR_BUCKETS),
        ("by_runtime_status", DIAGNOSTIC_RUNTIME_BUCKETS),
        ("by_phase", DIAGNOSTIC_PHASE_BUCKETS),
    )
    for name, buckets in dimensions:
        counts = payload.get(name)
        if not isinstance(counts, dict) or set(counts) != set(buckets):
            return False
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in counts.values()
        ):
            return False
        if sum(counts.values()) != sample_count:
            return False
    phase_error_counts = payload.get("by_phase_and_error_code")
    if not isinstance(phase_error_counts, dict) or set(phase_error_counts) != set(
        DIAGNOSTIC_PHASE_BUCKETS
    ):
        return False
    for phase in DIAGNOSTIC_PHASE_BUCKETS:
        error_counts = phase_error_counts.get(phase)
        if not isinstance(error_counts, dict) or set(error_counts) != set(DIAGNOSTIC_ERROR_BUCKETS):
            return False
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in error_counts.values()
        ):
            return False
        if sum(error_counts.values()) != cast(dict[str, int], payload["by_phase"])[phase]:
            return False
    for error_code in DIAGNOSTIC_ERROR_BUCKETS:
        phase_total = sum(
            cast(dict[str, int], cast(dict[str, object], phase_error_counts)[phase])[error_code]
            for phase in DIAGNOSTIC_PHASE_BUCKETS
        )
        if phase_total != cast(dict[str, int], payload["by_error_code"])[error_code]:
            return False
    transport_error_total = sum(
        cast(dict[str, int], payload["by_error_code"])[error_code]
        for error_code in DIAGNOSTIC_ERROR_BUCKETS
        if error_code.startswith("transport.")
    )
    if transport_error_total != cast(dict[str, int], payload["by_http_status"])["transport"]:
        return False
    negative_control_count = cast(
        dict[str, int],
        cast(dict[str, object], phase_error_counts)["cross_site"],
    )["auth.site_mismatch"]
    if (
        negative_control_count != 1
        or cast(dict[str, int], payload["by_error_code"])["auth.site_mismatch"] != 1
    ):
        return False
    calculated_other = sum(
        int(cast(dict[str, int], payload[name])["other"])
        for name in ("by_http_status", "by_error_code", "by_runtime_status", "by_phase")
    )
    expected_complete = (
        calculated_other == 0
        and violation_count == 0
        and payload.get("negative_control_included") is True
    )
    return (
        other_count == calculated_other
        and payload.get("negative_control_included") is True
        and payload.get("complete") is expected_complete
    )


def _proof_fixture_rejections_zero(diagnostics: object) -> bool:
    if not _diagnostics_valid(diagnostics):
        return False
    errors = cast(dict[str, int], cast(dict[str, object], diagnostics)["by_error_code"])
    return all(errors[name] == 0 for name in PROOF_FIXTURE_REJECTION_BUCKETS)


def _transport_http_failures_zero(diagnostics: object) -> bool:
    if not _diagnostics_valid(diagnostics):
        return False
    http_statuses = cast(dict[str, int], cast(dict[str, object], diagnostics)["by_http_status"])
    return http_statuses["transport"] == 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-disposable", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve-provider")
    commands.add_parser("probe-api")
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--baseline-index", type=int, required=True)
    run = commands.add_parser("run")
    run.add_argument("--mode", choices=("quick", "formal"), required=True)
    run.add_argument("--baseline-index", type=int, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--resource-file", type=Path, required=True)
    aggregate = commands.add_parser("aggregate")
    aggregate.add_argument("--mode", choices=("quick", "formal"), required=True)
    aggregate.add_argument("--input-dir", type=Path, required=True)
    aggregate.add_argument("--baseline-count", type=int, required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    return parser


def _settings() -> Settings:
    return Settings(_env_file=None)


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProofFailure(f"configuration.{name.lower()}_required")
    return value


def _sha_env(name: str) -> str:
    value = _env(name).lower()
    if not HASH_PATTERN.fullmatch(value):
        raise ProofFailure(f"configuration.{name.lower()}_invalid")
    return value


def _dataset_attribution() -> tuple[dict[str, object], str]:
    raw = _env("P5_B4_DATASET_CONFIG")
    if len(raw) > 4096:
        raise ProofFailure("configuration.dataset_config_too_large")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ProofFailure("configuration.dataset_config_invalid") from error
    if not isinstance(parsed, dict):
        raise ProofFailure("configuration.dataset_config_invalid")
    forbidden = {"secret", "token", "password", "credential", "prompt", "result"}

    def sensitive(value: object) -> bool:
        if isinstance(value, dict):
            return any(
                any(marker in str(key).lower() for marker in forbidden) or sensitive(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(sensitive(item) for item in value)
        return False

    if sensitive(parsed):
        raise ProofFailure("configuration.dataset_config_sensitive")
    if _env("P5_B4_DATASET_ID") != EXPECTED_DATASET_ID:
        raise ProofFailure("configuration.dataset_id_invalid")
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    expected_canonical = json.dumps(
        EXPECTED_DATASET_CONFIG,
        sort_keys=True,
        separators=(",", ":"),
    )
    if canonical != expected_canonical:
        raise ProofFailure("configuration.dataset_contract_invalid")
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    if digest != _sha_env("P5_B4_DATASET_SHA256"):
        raise ProofFailure("configuration.dataset_sha256_mismatch")
    return parsed, digest


def _git_state() -> tuple[bool, int]:
    raw_dirty = _env("P5_B4_GIT_DIRTY").lower()
    if raw_dirty not in {"true", "false"}:
        raise ProofFailure("configuration.git_dirty_invalid")
    try:
        count = int(_env("P5_B4_GIT_DIRTY_COUNT"))
    except ValueError as error:
        raise ProofFailure("configuration.git_dirty_count_invalid") from error
    dirty = raw_dirty == "true"
    if count < 0 or dirty != (count > 0):
        raise ProofFailure("configuration.git_dirty_state_inconsistent")
    return dirty, count


def _confirm(args: argparse.Namespace) -> None:
    if not args.confirm_disposable:
        raise ProofFailure("safety.confirm_disposable_required")
    if os.environ.get("P5_B4_DISPOSABLE_PROOF") != DISPOSABLE_CONFIRMATION:
        raise ProofFailure("safety.disposable_environment_marker_invalid")
    project = os.environ.get("P5_B4_PROOF_PROJECT", "")
    if not re.fullmatch(r"npcink_p5_b4_[a-zA-Z0-9_.-]{6,80}", project):
        raise ProofFailure("safety.compose_project_not_dedicated")
    if any(os.environ.get(name, "").strip() for name in PROVIDER_CREDENTIAL_ENV_NAMES):
        raise ProofFailure("safety.real_provider_credential_present")


def _shape(mode: str) -> Shape:
    if mode == "formal":
        delay_ms = int(os.environ.get("P5_B4_PROVIDER_DELAY_MS", "0"))
        settings = _settings()
        if delay_ms != FORMAL_PROVIDER_DELAY_MS:
            raise ProofFailure("configuration.formal_provider_delay_changed")
        if settings.runtime_worker_poll_seconds != DEFAULT_WORKER_POLL_SECONDS:
            raise ProofFailure("configuration.formal_worker_poll_changed")
        if settings.runtime_worker_batch_size != DEFAULT_WORKER_BATCH_SIZE:
            raise ProofFailure("configuration.formal_worker_batch_changed")
        return Shape(
            mode=mode,
            duration_seconds=FORMAL_DURATION_SECONDS,
            warmup_seconds=FORMAL_WARMUP_SECONDS,
            concurrency=FORMAL_CONCURRENCY,
            request_rate=FORMAL_REQUEST_RATE,
            queue_burst=FORMAL_QUEUE_BURST,
        )
    values = Shape(
        mode=mode,
        duration_seconds=int(os.environ.get("P5_B4_QUICK_DURATION_SECONDS", "5")),
        warmup_seconds=int(os.environ.get("P5_B4_QUICK_WARMUP_SECONDS", "3")),
        concurrency=int(os.environ.get("P5_B4_QUICK_CONCURRENCY", "2")),
        request_rate=float(os.environ.get("P5_B4_QUICK_REQUEST_RATE", "2")),
        queue_burst=int(os.environ.get("P5_B4_QUICK_QUEUE_BURST", "8")),
    )
    if (
        min(values.duration_seconds, values.warmup_seconds, values.concurrency, values.queue_burst)
        < 1
    ):
        raise ProofFailure("configuration.quick_positive_values_required")
    if values.request_rate <= 0:
        raise ProofFailure("configuration.quick_positive_values_required")
    return values


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _validate_targets(settings: Settings, *, fresh: bool) -> tuple[int, int]:
    database = make_url(settings.database_url)
    if (
        not database.drivername.startswith("postgresql")
        or database.host != DATABASE_HOST
        or database.database != DATABASE_NAME
        or database.username != DATABASE_USER
    ):
        raise ProofFailure("safety.database_target_not_dedicated")
    engine = create_engine(settings.database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            identity = connection.execute(
                text(
                    "SELECT current_database(), current_user, current_setting('server_version_num')"
                )
            ).one()
            table_count = int(
                connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
                    )
                ).scalar_one()
            )
            comment = str(
                connection.execute(
                    text(
                        "SELECT coalesce(shobj_description(oid, 'pg_database'), '') "
                        "FROM pg_database WHERE datname=current_database()"
                    )
                ).scalar_one()
            )
    finally:
        engine.dispose()
    pg_major = int(str(identity[2])) // 10_000
    if identity[0] != DATABASE_NAME or identity[1] != DATABASE_USER or pg_major != 16:
        raise ProofFailure("safety.database_identity_mismatch")
    if fresh and (table_count != 0 or comment):
        raise ProofFailure("safety.database_not_fresh")
    if not fresh and comment != DATABASE_COMMENT:
        raise ProofFailure("safety.database_marker_missing")

    redis_url = urlsplit(settings.redis_url)
    redis_db = int(redis_url.path.lstrip("/") or "0")
    if redis_url.hostname != REDIS_HOST or redis_db != REDIS_DATABASE:
        raise ProofFailure("safety.redis_target_not_dedicated")
    client = _redis(settings)
    try:
        if not client.ping():
            raise ProofFailure("safety.redis_unavailable")
        redis_major = int(str(client.info("server")["redis_version"]).split(".", 1)[0])
        if fresh and int(client.dbsize()) != 0:
            raise ProofFailure("safety.redis_not_fresh")
        if not fresh and client.get(f"{REDIS_PREFIX}:marker") != DATABASE_COMMENT:
            raise ProofFailure("safety.redis_marker_missing")
    finally:
        client.close()
    if redis_major != 7:
        raise ProofFailure("safety.redis_version_mismatch")
    return pg_major, redis_major


def _site_credential(index: int) -> tuple[str, str, str]:
    suffix = f"{index + 1:02d}"
    return (
        f"site_p5b4_{suffix}",
        f"key_p5b4_{suffix}",
        f"p5-b4-disposable-signing-secret-{suffix}-32b",
    )


def _proof_request_ref(request_hash: str) -> str:
    if not HASH_PATTERN.fullmatch(request_hash):
        raise ProofFailure("provider.request_hash_invalid")
    return request_hash.translate(PROOF_REQUEST_REF_ENCODE)


def _proof_request_hash(request_ref: str) -> str:
    if not PROOF_REQUEST_REF_PATTERN.fullmatch(request_ref):
        raise ProofFailure("provider.request_ref_invalid")
    request_hash = request_ref.translate(PROOF_REQUEST_REF_DECODE)
    if not HASH_PATTERN.fullmatch(request_hash):
        raise ProofFailure("provider.request_ref_invalid")
    return request_hash


def _proof_concurrency_target(metadata: dict[str, object]) -> int:
    value = metadata.get("proof_concurrency_target", 0)
    if isinstance(value, bool):
        raise ProofFailure("provider.concurrency_target_invalid")
    if isinstance(value, int):
        target = value
    elif isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        target = int(value)
    else:
        raise ProofFailure("provider.concurrency_target_invalid")
    if target < 0 or target > FORMAL_CONCURRENCY:
        raise ProofFailure("provider.concurrency_target_invalid")
    return target


def _wait_for_provider_concurrency(
    client: Redis,
    target: int,
    *,
    timeout_seconds: float = 5.0,
) -> bool:
    if target <= 1:
        return True
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    active_key = f"{REDIS_PREFIX}:provider_active"
    while int(client.get(active_key) or 0) < target:
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.005)
    return True


class _ProviderHandler(BaseHTTPRequestHandler):
    server_version = "P5B4ProofProvider/2"

    def log_message(self, _format: str, *args: object) -> None:
        return

    def _json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok"})
            return
        if self.path in {"/v1/models", "/models"}:
            self._json(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": "gpt-5.5",
                            "object": "model",
                            "owned_by": "proof",
                            "metadata": {
                                "feature": "text",
                                "tier": "balanced",
                                "status": "available",
                            },
                        }
                    ],
                },
            )
            return
        self._json(404, {"error": {"code": "proof.not_found"}})

    def do_POST(self) -> None:  # noqa: N802
        endpoints = {"/v1/responses", "/responses", "/v1/chat/completions", "/chat/completions"}
        if self.path not in endpoints:
            self._json(404, {"error": {"code": "proof.not_found"}})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            if length < 1 or length > 1024 * 1024:
                raise ValueError
            payload = json.loads(self.rfile.read(length))
            metadata = payload.get("metadata") if isinstance(payload, dict) else None
            if not isinstance(metadata, dict):
                raise ValueError
            request_ref = str(metadata.get("proof_request_ref") or "")
            request_hash = _proof_request_hash(request_ref)
            concurrency_target = _proof_concurrency_target(metadata)
        except (TypeError, ValueError, json.JSONDecodeError, ProofFailure):
            self._json(400, {"error": {"code": "proof.metadata_invalid"}})
            return
        settings = _settings()
        client = _redis(settings)
        delay_ms = int(os.environ.get("P5_B4_PROVIDER_DELAY_MS", str(FORMAL_PROVIDER_DELAY_MS)))
        started = time.perf_counter_ns()
        active_incremented = False
        try:
            client.hincrby(f"{REDIS_PREFIX}:provider_invocations", request_hash, 1)
            client.eval(
                "local n=redis.call('incr',KEYS[1]); "
                "local m=tonumber(redis.call('get',KEYS[2]) or '0'); "
                "if n>m then redis.call('set',KEYS[2],n) end; return n",
                2,
                f"{REDIS_PREFIX}:provider_active",
                f"{REDIS_PREFIX}:provider_max_active",
            )
            active_incremented = True
            if not _wait_for_provider_concurrency(client, concurrency_target):
                client.incr(f"{REDIS_PREFIX}:provider_barrier_timeouts")
            time.sleep(max(1, delay_ms) / 1_000)
            duration_us = max(1, (time.perf_counter_ns() - started) // 1_000)
            client.hset(f"{REDIS_PREFIX}:provider_duration_us", request_hash, duration_us)
        finally:
            if active_incremented:
                client.decr(f"{REDIS_PREFIX}:provider_active")
            client.close()
        if self.path.endswith("/responses"):
            self._json(
                200,
                {
                    "id": "proof-response",
                    "model": "gpt-5.5",
                    "output_text": "proof-output",
                    "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                },
            )
            return
        self._json(
            200,
            {
                "id": "proof-completion",
                "model": "gpt-5.5",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "proof-output"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            },
        )


def _serve_provider() -> int:
    server = ThreadingHTTPServer(("0.0.0.0", 8090), _ProviderHandler)
    server.serve_forever()
    return 0


def _probe_api() -> dict[str, object]:
    try:
        response = httpx.get(
            f"{_env('P5_B4_PROOF_API_URL')}/health/ready",
            headers={"X-Npcink-Internal-Token": _env("NPCINK_CLOUD_INTERNAL_AUTH_TOKEN")},
            timeout=5.0,
        )
    except httpx.TimeoutException as error:
        raise ProofFailure("topology.runner_api_preflight_timeout") from error
    except httpx.RequestError as error:
        raise ProofFailure("topology.runner_api_preflight_request_error") from error
    try:
        payload = response.json()
    except ValueError as error:
        raise ProofFailure("topology.runner_api_preflight_non_json") from error
    if (
        response.status_code != 200
        or not isinstance(payload, dict)
        or payload.get("status") != "ok"
    ):
        raise ProofFailure("topology.runner_api_preflight_failed")
    return {
        "contract": CONTRACT_ID,
        "operation": "runner_api_preflight",
        "http_status": response.status_code,
        "ready": True,
        "runner_network_path_verified": True,
    }


def _prepare(baseline_index: int) -> dict[str, object]:
    if baseline_index < 1:
        raise ProofFailure("configuration.baseline_index_invalid")
    settings = _settings()
    pg_major, redis_major = _validate_targets(settings, fresh=True)
    command.upgrade(AlembicConfig("alembic.ini"), "head")
    engine = create_engine(settings.database_url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"COMMENT ON DATABASE {DATABASE_NAME} IS '{DATABASE_COMMENT}'"))
    finally:
        engine.dispose()

    provider_url = _env("P5_B4_PROOF_PROVIDER_URL")
    ProviderConnectionAdminService(settings.database_url, settings).save_connection(
        {
            "connection_id": "p5_b4_proof",
            "provider_id": "p5_b4_proof",
            "provider_type": "openai_compatible",
            "kind": "openai_compatible",
            "display_name": "P5-B4 deterministic proof provider",
            "enabled": True,
            "base_url": provider_url,
            "source_role": "execution_source",
            "secretless": True,
            "runtime_profile_ids": ["text.free-gpt55"],
            "config": {"model_namespace_prefix": "", "timeout_seconds": 30},
            "metadata": {"proof_only": True},
        }
    )
    providers = build_enabled_connection_provider_adapters(settings)
    if set(providers) != {"p5_b4_proof"}:
        raise ProofFailure("prepare.proof_provider_resolution_failed")
    CatalogService(settings.database_url, providers=providers, settings=settings).refresh_catalog()
    commercial = CommercialService(settings.database_url, settings=settings)
    for index in range(SITE_COUNT):
        site_id, key_id, secret = _site_credential(index)
        commercial.provision_runtime_baseline(
            site_id=site_id,
            key_id=key_id,
            secret=secret,
            site_name=f"P5-B4 proof site {index + 1}",
            scopes=["runtime:execute", "runtime:read", "runtime:resolve"],
            plan_id=PROOF_PLAN_ID,
            plan_version_id=PROOF_PLAN_VERSION_ID,
        )
    with get_session(settings.database_url) as session:
        plan_version = session.get(PlanVersion, PROOF_PLAN_VERSION_ID)
        snapshots = list(
            session.scalars(
                select(AccountEntitlementSnapshot).where(
                    AccountEntitlementSnapshot.plan_version_id == PROOF_PLAN_VERSION_ID
                )
            )
        )
        if plan_version is None or len(snapshots) != SITE_COUNT:
            raise ProofFailure("prepare.commercial_baseline_incomplete")
        proof_budgets = {
            "max_ai_credits_per_period": PROOF_MAX_AI_CREDITS_PER_SITE_PERIOD,
            "max_runs_per_period": 0,
            "max_tokens_per_period": 0,
            "max_cost_per_period": 0.0,
        }
        plan_version.budgets_json = dict(proof_budgets)
        for snapshot in snapshots:
            snapshot.budgets_json = dict(proof_budgets)
        artifact_baseline = int(session.query(MediaArtifact).count())
        session.commit()
    client = _redis(settings)
    try:
        client.set(f"{REDIS_PREFIX}:marker", DATABASE_COMMENT)
        client.set(
            f"{REDIS_PREFIX}:manifest",
            json.dumps(
                {
                    "baseline_index": baseline_index,
                    "dataset_fingerprint": _env("P5_B4_DATASET_ID"),
                    "site_count": SITE_COUNT,
                    "artifact_baseline": artifact_baseline,
                    "max_ai_credits_per_site_period": (PROOF_MAX_AI_CREDITS_PER_SITE_PERIOD),
                },
                sort_keys=True,
            ),
        )
    finally:
        client.close()
    dispose_engine(settings.database_url)
    return {
        "contract": CONTRACT_ID,
        "operation": "prepare",
        "baseline_index": baseline_index,
        "postgres_major": pg_major,
        "redis_major": redis_major,
        "database_marked": True,
        "redis_marked": True,
        "site_count": SITE_COUNT,
        "max_ai_credits_per_site_period": PROOF_MAX_AI_CREDITS_PER_SITE_PERIOD,
        "real_provider_credentials_present": False,
    }


def _request_hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _manifest(settings: Settings, baseline_index: int) -> dict[str, object]:
    client = _redis(settings)
    try:
        raw = client.get(f"{REDIS_PREFIX}:manifest")
    finally:
        client.close()
    try:
        manifest = json.loads(raw or "")
    except json.JSONDecodeError as error:
        raise ProofFailure("safety.redis_manifest_invalid") from error
    expected = {
        "baseline_index": baseline_index,
        "dataset_fingerprint": _env("P5_B4_DATASET_ID"),
        "site_count": SITE_COUNT,
        "artifact_baseline": 0,
        "max_ai_credits_per_site_period": PROOF_MAX_AI_CREDITS_PER_SITE_PERIOD,
    }
    if manifest != expected:
        raise ProofFailure("safety.redis_manifest_mismatch")
    return expected


def _auth_headers(
    *,
    method: str,
    path: str,
    credential: tuple[str, str, str],
    label: str,
    body: bytes = b"",
    idempotency_key: str = "",
) -> dict[str, str]:
    site_id, key_id, secret = credential
    trace_id = hashlib.sha256(f"trace:{label}".encode()).hexdigest()[:32]
    traceparent = f"00-{trace_id}-0000000000000000-01"
    timestamp = str(int(datetime.now(UTC).timestamp()))
    nonce = f"nonce-{_request_hash(label)[:24]}" if method == "POST" else ""
    canonical = build_canonical_request(
        method=method,
        path=path,
        query="",
        site_id=site_id,
        key_id=key_id,
        timestamp=timestamp,
        nonce=nonce,
        idempotency_key=idempotency_key,
        traceparent=traceparent,
        body_digest=build_body_digest(body),
    )
    headers = {
        "X-Npcink-Site-Id": site_id,
        "X-Npcink-Key-Id": key_id,
        "X-Npcink-Timestamp": timestamp,
        "X-Npcink-Signature": build_hmac_signature(secret, canonical),
        "traceparent": traceparent,
    }
    if nonce:
        headers["X-Npcink-Nonce"] = nonce
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    if body:
        headers["content-type"] = "application/json"
    return headers


def _payload(
    site_id: str,
    label: str,
    *,
    queued: bool,
    provider_concurrency_target: int = 0,
) -> tuple[bytes, str]:
    request_hash = _request_hash(label)
    idempotency_key = f"idem-{request_hash[:48]}"
    proof_metadata: dict[str, object] = {"proof_request_ref": _proof_request_ref(request_hash)}
    if provider_concurrency_target:
        proof_metadata["proof_concurrency_target"] = str(provider_concurrency_target)
    _proof_concurrency_target(proof_metadata)
    data: dict[str, object] = {
        "site_id": site_id,
        "ability_name": "workflow/media_nightly_image_optimize"
        if queued
        else "p5b4/runtime-load-soak",
        "ability_family": "automation" if queued else "text",
        "workflow_id": "media_nightly_image_optimize" if queued else None,
        "contract_version": "p5_b4_runtime_load_soak.v2",
        "channel": "openapi",
        "execution_kind": "text",
        "execution_tier": "cloud",
        "execution_pattern": "whole_run_offload" if queued else "inline",
        "data_classification": "internal",
        "storage_mode": "result_only",
        "timeout_seconds": 30,
        "retry_max": 0,
        "retention_ttl": 3600,
        "profile_id": "text.free-gpt55",
        "idempotency_key": idempotency_key,
        "trace_id": hashlib.sha256(f"payload:{label}".encode()).hexdigest()[:32],
        "input": {
            "messages": [{"role": "user", "content": "bounded proof input"}],
            "metadata": proof_metadata,
        },
        "policy": {"allow_fallback": False},
    }
    if queued:
        data["task_backend"] = {
            "enabled": True,
            "mode": "polling",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": DEFAULT_WORKER_POLL_SECONDS,
        }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode(), idempotency_key


def _transport_error_code(error: httpx.RequestError) -> str:
    classifications: tuple[tuple[type[httpx.RequestError], str], ...] = (
        (httpx.ConnectError, "transport.connect_error"),
        (httpx.ReadError, "transport.read_error"),
        (httpx.WriteError, "transport.write_error"),
        (httpx.CloseError, "transport.close_error"),
        (httpx.ProtocolError, "transport.protocol_error"),
        (httpx.ProxyError, "transport.proxy_error"),
        (httpx.UnsupportedProtocol, "transport.unsupported_protocol"),
        (httpx.TooManyRedirects, "transport.too_many_redirects"),
        (httpx.NetworkError, "transport.network_error"),
    )
    for error_type, code in classifications:
        if isinstance(error, error_type):
            return code
    return "transport.request_error"


async def _execute(
    client: httpx.AsyncClient,
    *,
    credential: tuple[str, str, str],
    label: str,
    phase: str,
    queued: bool = False,
    payload_site: str | None = None,
    provider_concurrency_target: int = 0,
) -> Observation:
    body, idem = _payload(
        payload_site or credential[0],
        label,
        queued=queued,
        provider_concurrency_target=provider_concurrency_target,
    )
    started = time.perf_counter_ns()
    try:
        response = await client.post(
            "/v1/runtime/execute",
            content=body,
            headers=_auth_headers(
                method="POST",
                path="/v1/runtime/execute",
                credential=credential,
                label=label,
                body=body,
                idempotency_key=idem,
            ),
        )
    except httpx.TimeoutException:
        return Observation(
            request_hash=_request_hash(label),
            run_id="",
            http_status=0,
            runtime_status="",
            error_code="transport.timeout",
            elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
            phase=phase,
        )
    except httpx.RequestError as error:
        return Observation(
            request_hash=_request_hash(label),
            run_id="",
            http_status=0,
            runtime_status="",
            error_code=_transport_error_code(error),
            elapsed_ms=(time.perf_counter_ns() - started) / 1_000_000,
            phase=phase,
        )
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    try:
        envelope = response.json()
    except ValueError:
        envelope = {}
    data = envelope.get("data") if isinstance(envelope, dict) else {}
    data = data if isinstance(data, dict) else {}
    return Observation(
        request_hash=_request_hash(label),
        run_id=str(data.get("run_id") or ""),
        http_status=response.status_code,
        runtime_status=str(data.get("status") or ""),
        error_code=str(envelope.get("error_code") or "") if isinstance(envelope, dict) else "",
        elapsed_ms=elapsed_ms,
        phase=phase,
    )


async def _scheduled_phase(
    client: httpx.AsyncClient,
    credentials: list[tuple[str, str, str]],
    *,
    label_prefix: str,
    phase: str,
    duration_seconds: int,
    rate: float,
    concurrency: int,
) -> tuple[list[Observation], dict[str, object]]:
    count = max(1, round(duration_seconds * rate))
    semaphore = asyncio.Semaphore(concurrency)
    current = 0
    max_in_flight = 0
    drifts: list[float] = []
    semaphore_waits: list[float] = []
    started = time.monotonic()

    async def issue(index: int) -> Observation:
        nonlocal current, max_in_flight
        queued_at = time.monotonic()
        async with semaphore:
            semaphore_waits.append((time.monotonic() - queued_at) * 1_000)
            current += 1
            max_in_flight = max(max_in_flight, current)
            try:
                return await _execute(
                    client,
                    credential=credentials[index % len(credentials)],
                    label=f"{label_prefix}-{index}",
                    phase=phase,
                )
            finally:
                current -= 1

    async def produce() -> list[Observation]:
        completed: list[Observation] = []
        pending: set[asyncio.Task[Observation]] = set()
        for index in range(count):
            target = started + index / rate
            await asyncio.sleep(max(0.0, target - time.monotonic()))
            drifts.append(max(0.0, (time.monotonic() - target) * 1_000))
            pending.add(asyncio.create_task(issue(index)))
            if len(pending) >= concurrency:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                completed.extend(task.result() for task in done)
        if pending:
            completed.extend(await asyncio.gather(*pending))
        return completed

    observations = await asyncio.wait_for(produce(), timeout=duration_seconds + 60)
    wall = time.monotonic() - started
    achieved = len(observations) / wall if wall else 0.0
    return observations, {
        "actual_phase_wall_seconds": round(wall, 3),
        "achieved_requests_per_second": round(achieved, 4),
        "achieved_rate_ratio": round(achieved / rate, 6),
        "scheduler_drift_p95_ms": round(_percentile(drifts, 0.95), 3),
        "scheduler_drift_max_ms": round(max(drifts, default=0.0), 3),
        "semaphore_wait_p95_ms": round(_percentile(semaphore_waits, 0.95), 3),
        "semaphore_wait_max_ms": round(max(semaphore_waits, default=0.0), 3),
        "max_in_flight": max_in_flight,
        "sample_count": len(observations),
    }


async def _queue_burst(
    client: httpx.AsyncClient,
    credentials: list[tuple[str, str, str]],
    *,
    baseline_index: int,
    count: int,
    concurrency: int,
) -> list[Observation]:
    async def issue(index: int) -> Observation:
        return await _execute(
            client,
            credential=credentials[index % SITE_COUNT],
            label=f"baseline-{baseline_index}-queue-{index}",
            phase="queue",
            queued=True,
        )

    completed: list[Observation] = []
    for offset in range(0, count, concurrency):
        completed.extend(
            await asyncio.gather(
                *(issue(index) for index in range(offset, min(count, offset + concurrency)))
            )
        )
    return completed


async def _concurrency_probe(
    client: httpx.AsyncClient,
    credentials: list[tuple[str, str, str]],
    *,
    baseline_index: int,
    concurrency: int,
) -> tuple[list[Observation], int]:
    release = asyncio.Event()
    current = 0
    maximum = 0

    async def issue(index: int) -> Observation:
        nonlocal current, maximum
        await release.wait()
        current += 1
        maximum = max(maximum, current)
        try:
            return await _execute(
                client,
                credential=credentials[index % SITE_COUNT],
                label=f"baseline-{baseline_index}-concurrency-{index}",
                phase="concurrency_probe",
                provider_concurrency_target=concurrency,
            )
        finally:
            current -= 1

    tasks = [asyncio.create_task(issue(index)) for index in range(concurrency)]
    release.set()
    return list(await asyncio.wait_for(asyncio.gather(*tasks), timeout=45)), maximum


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def _timing_distribution(values: list[float]) -> dict[str, int | float]:
    return {
        "sample_count": len(values),
        "p50": round(_percentile(values, 0.50), 4),
        "p90": round(_percentile(values, 0.90), 4),
        "p95": round(_percentile(values, 0.95), 4),
        "p99": round(_percentile(values, 0.99), 4),
        "max": round(max(values, default=0.0), 4),
    }


def _queue_timing_evidence(
    queue_runs: list[object],
    *,
    expected_count: int,
    cohort_size: int,
) -> dict[str, object]:
    def epoch_seconds(value: object) -> float | None:
        if not isinstance(value, datetime):
            return None
        try:
            return value.timestamp()
        except (OSError, OverflowError, ValueError):
            return None

    prepared = [
        (
            epoch_seconds(getattr(run, "started_at", None)),
            epoch_seconds(getattr(run, "processing_started_at", None)),
            str(getattr(run, "run_id", "") or ""),
            index,
        )
        for index, run in enumerate(queue_runs)
    ]
    prepared.sort(
        key=lambda row: (
            row[0] is None,
            row[0] if row[0] is not None else 0.0,
            row[2],
            row[3],
        )
    )

    def aggregate(
        rows: list[tuple[float | None, float | None, str, int]],
        *,
        required_count: int,
    ) -> dict[str, object]:
        submissions = [row[0] for row in rows if row[0] is not None]
        claims = sorted(row[1] for row in rows if row[1] is not None)
        waits = [
            max(0.0, claim - submission)
            for submission, claim, _run_reference, _index in rows
            if submission is not None and claim is not None
        ]
        adjacent_claim_gaps = [
            max(0.0, current - previous)
            for previous, current in zip(claims, claims[1:], strict=False)
        ]
        missing_started_at_count = len(rows) - len(submissions)
        missing_processing_started_count = len(rows) - len(claims)
        timing_sample_count = len(waits)
        complete = (
            required_count > 0
            and len(rows) == required_count
            and missing_started_at_count == 0
            and missing_processing_started_count == 0
            and timing_sample_count == required_count
        )
        return {
            "sample_count": len(rows),
            "processing_started_sample_count": len(claims),
            "missing_started_at_count": missing_started_at_count,
            "missing_processing_started_count": missing_processing_started_count,
            "timing_sample_count": timing_sample_count,
            "complete": complete,
            "wait_seconds": _timing_distribution(waits),
            "first_claim_lag_seconds": round(
                max(0.0, min(claims) - min(submissions)) if claims and submissions else 0.0,
                4,
            ),
            "submission_span_seconds": round(
                max(submissions) - min(submissions) if submissions else 0.0,
                4,
            ),
            "processing_start_span_seconds": round(
                max(claims) - min(claims) if claims else 0.0,
                4,
            ),
            "adjacent_claim_gap_seconds": _timing_distribution(adjacent_claim_gaps),
        }

    valid_cohort_shape = (
        expected_count > 0 and cohort_size > 0 and expected_count % cohort_size == 0
    )
    cohorts = []
    if cohort_size > 0:
        for offset in range(0, len(prepared), cohort_size):
            cohort = aggregate(
                prepared[offset : offset + cohort_size],
                required_count=cohort_size,
            )
            cohorts.append({"cohort_index": len(cohorts) + 1, **cohort})
    overall = aggregate(prepared, required_count=expected_count)
    expected_cohort_count = expected_count // cohort_size if valid_cohort_shape else 0
    complete = (
        bool(overall["complete"])
        and valid_cohort_shape
        and len(cohorts) == expected_cohort_count
        and all(bool(cohort["complete"]) for cohort in cohorts)
    )
    return {
        "expected_sample_count": expected_count,
        **overall,
        "complete": complete,
        "cohort_size": cohort_size,
        "expected_cohort_count": expected_cohort_count,
        "cohort_count": len(cohorts),
        "cohorts": cohorts,
    }


def _exact_identifier_set(observed: list[str], stored: set[str]) -> bool:
    return len(observed) == len(set(observed)) and set(observed) == stored


def _queue_gate(requested: int, accepted: int, completed: int, result_status: int) -> bool:
    return requested == accepted == completed and result_status == 200


def _achieved_rate_passed(achieved: float, target: float) -> bool:
    return target > 0 and achieved / target >= THRESHOLDS["achieved_rate_ratio_min"]


def _side_effect_snapshot(settings: Settings) -> tuple[int, int, int, int]:
    with get_session(settings.database_url) as session:
        counts = (
            int(session.query(RunRecord).count()),
            int(session.query(ProviderCallRecord).count()),
            int(session.query(UsageMeterEvent).count()),
        )
    client = _redis(settings)
    try:
        invocation_count = sum(
            int(value) for value in client.hvals(f"{REDIS_PREFIX}:provider_invocations")
        )
    finally:
        client.close()
    return (*counts, invocation_count)


def _terminal_statuses(settings: Settings, run_ids: set[str]) -> dict[str, str]:
    if not run_ids:
        return {}
    with get_session(settings.database_url) as session:
        rows = session.execute(
            select(RunRecord.run_id, RunRecord.status).where(RunRecord.run_id.in_(run_ids))
        ).all()
    return {str(run_id): str(status) for run_id, status in rows}


async def _wait_terminal(settings: Settings, run_ids: set[str], timeout: float) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        statuses = await asyncio.to_thread(_terminal_statuses, settings, run_ids)
        if len(statuses) == len(run_ids) and all(
            status in {"succeeded", "failed", "canceled"} for status in statuses.values()
        ):
            return statuses
        await asyncio.sleep(0.25)
    raise ProofFailure("queue.terminal_timeout")


async def _signed_get(
    client: httpx.AsyncClient,
    path: str,
    credential: tuple[str, str, str],
    label: str,
) -> tuple[int, str]:
    response = await client.get(
        path,
        headers=_auth_headers(method="GET", path=path, credential=credential, label=label),
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return response.status_code, str(payload.get("error_code") or "")


def _usage_event_valid(event: object, run_ids: set[str], call_runs: dict[int, str]) -> bool:
    meter = str(getattr(event, "meter_key", "") or "")
    run_id = str(getattr(event, "run_id", "") or "")
    call_id = getattr(event, "provider_call_id", None)
    if meter == "runs":
        return run_id in run_ids and call_id is None
    provider_meters = {"provider_calls", "tokens_in", "tokens_out", "tokens_total"}
    if meter == "cost" and float(getattr(event, "quantity", 0) or 0) > 0:
        provider_meters.add("cost")
    if meter not in provider_meters or call_id is None:
        return False
    normalized_call_id = int(call_id)
    return normalized_call_id in call_runs and call_runs[normalized_call_id] == run_id


def _expected_provider_meter_quantities(call: object) -> dict[str, float]:
    tokens_in = float(getattr(call, "tokens_in", 0) or 0)
    tokens_out = float(getattr(call, "tokens_out", 0) or 0)
    candidates = {
        "provider_calls": 1.0,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_in + tokens_out,
        "cost": float(getattr(call, "cost", 0) or 0),
    }
    return {
        meter: quantity
        for meter, quantity in candidates.items()
        if meter == "provider_calls" or quantity > 0
    }


def _integrity(
    settings: Settings,
    observations: list[Observation],
    queue_ids: set[str],
    *,
    expected_queue_count: int,
) -> tuple[dict[str, object], dict[str, int], dict[str, float]]:
    with get_session(settings.database_url) as session:
        runs = list(session.scalars(select(RunRecord)))
        calls = list(session.scalars(select(ProviderCallRecord)))
        usage = list(session.scalars(select(UsageMeterEvent)))
        artifact_count = int(session.query(MediaArtifact).count())
    observed_ids = [item.run_id for item in observations if item.run_id]
    db_set = {run.run_id for run in runs}
    succeeded = {run.run_id for run in runs if run.status == "succeeded"}
    calls_by_run = Counter(call.run_id for call in calls)
    call_latency = {call.run_id: float(call.latency_ms) for call in calls}
    provider_usage = Counter(
        int(event.provider_call_id)
        for event in usage
        if event.provider_call_id is not None and event.meter_key == "provider_calls"
    )
    run_usage = Counter(
        str(event.run_id)
        for event in usage
        if event.run_id and event.provider_call_id is None and event.meter_key == "runs"
    )
    run_usage_quantities: dict[str, float] = {}
    provider_meter_counts: Counter[tuple[int, str]] = Counter()
    provider_meter_quantities: dict[tuple[int, str], float] = {}
    for event in usage:
        if event.provider_call_id is None and event.meter_key == "runs" and event.run_id:
            run_id = str(event.run_id)
            run_usage_quantities[run_id] = run_usage_quantities.get(run_id, 0.0) + float(
                event.quantity or 0
            )
        if event.provider_call_id is not None:
            key = (int(event.provider_call_id), str(event.meter_key or ""))
            provider_meter_counts[key] += 1
            provider_meter_quantities[key] = provider_meter_quantities.get(key, 0.0) + float(
                event.quantity or 0
            )
    provider_client = _redis(settings)
    try:
        invocations = {
            key: int(value)
            for key, value in provider_client.hgetall(
                f"{REDIS_PREFIX}:provider_invocations"
            ).items()
        }
        durations_ms = {
            key: int(value) / 1_000
            for key, value in provider_client.hgetall(
                f"{REDIS_PREFIX}:provider_duration_us"
            ).items()
        }
        queue_residue = int(provider_client.llen(settings.runtime_queue_key))
        provider_active = int(provider_client.get(f"{REDIS_PREFIX}:provider_active") or 0)
        provider_max_active = int(provider_client.get(f"{REDIS_PREFIX}:provider_max_active") or 0)
        provider_barrier_timeouts = int(
            provider_client.get(f"{REDIS_PREFIX}:provider_barrier_timeouts") or 0
        )
    finally:
        provider_client.close()
    hash_by_run = {item.run_id: item.request_hash for item in observations if item.run_id}
    expected_invocation_hashes = {
        hash_by_run[run_id] for run_id in calls_by_run if run_id in hash_by_run
    }
    exact_provider_calls = sum(calls_by_run.get(run_id, 0) != 1 for run_id in succeeded)
    exact_invocations = sum(
        invocations.get(hash_by_run.get(run_id, ""), 0) != 1 for run_id in succeeded
    )
    call_runs = {int(call.id): str(call.run_id) for call in calls}
    provider_call_ids = set(call_runs)
    provider_usage_set_exact = set(provider_usage) == provider_call_ids
    run_usage_set_exact = set(run_usage) == db_set
    expected_provider_meters = {
        (int(call.id), meter): quantity
        for call in calls
        for meter, quantity in _expected_provider_meter_quantities(call).items()
    }
    provider_meter_set_exact = set(provider_meter_counts) == set(expected_provider_meters)
    provider_meter_mismatches = sum(
        provider_meter_counts.get(key, 0) != 1
        or not math.isclose(
            provider_meter_quantities.get(key, 0.0),
            quantity,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        for key, quantity in expected_provider_meters.items()
    ) + (0 if provider_meter_set_exact else 1)
    usage_contract_violations = sum(
        not _usage_event_valid(event, db_set, call_runs) for event in usage
    )
    exact_provider_usage = sum(provider_usage.get(call_id, 0) != 1 for call_id in provider_call_ids)
    exact_run_usage = sum(
        run_usage.get(run_id, 0) != 1
        or not math.isclose(
            run_usage_quantities.get(run_id, 0.0),
            1.0,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
        for run_id in db_set
    )
    duplicate_or_missing = (
        exact_provider_calls
        + exact_invocations
        + exact_provider_usage
        + exact_run_usage
        + sum(count != 1 for count in calls_by_run.values())
        + sum(count != 1 for count in invocations.values())
        + (0 if provider_usage_set_exact else 1)
        + (0 if run_usage_set_exact else 1)
        + provider_meter_mismatches
        + usage_contract_violations
    )
    provider_set_exact = set(invocations) == expected_invocation_hashes
    queue_runs = [run for run in runs if run.run_id in queue_ids]
    queue_timing = _queue_timing_evidence(
        queue_runs,
        expected_count=expected_queue_count,
        cohort_size=DEFAULT_WORKER_BATCH_SIZE,
    )
    queue_wait = cast(dict[str, object], queue_timing["wait_seconds"])
    integrity = {
        "observed_records": len(observed_ids),
        "database_records": len(runs),
        "observed_identifier_set_exact": _exact_identifier_set(observed_ids, db_set),
        "succeeded_records": len(succeeded),
        "provider_call_records": len(calls),
        "provider_invocations": sum(invocations.values()),
        "provider_invocation_set_exact": provider_set_exact,
        "provider_usage_key_set_exact": provider_usage_set_exact,
        "run_usage_key_set_exact": run_usage_set_exact,
        "provider_meter_set_exact": provider_meter_set_exact,
        "provider_meter_mismatches": provider_meter_mismatches,
        "usage_event_contract_violations": usage_contract_violations,
        "duplicates_or_missing": duplicate_or_missing + (0 if provider_set_exact else 1),
        "queued_residue": sum(run.status == "queued" for run in runs),
        "running_residue": sum(run.status == "running" for run in runs),
        "dispatching_residue": sum(run.callback_status == "dispatching" for run in runs),
        "redis_queue_residue": queue_residue,
        "provider_active_residue": provider_active,
        "provider_max_concurrency": provider_max_active,
        "provider_barrier_timeouts": provider_barrier_timeouts,
        "artifact_records": artifact_count,
        "queue_timing_evidence": queue_timing,
        "queue_wait_p95_seconds": queue_wait["p95"],
    }
    return (
        integrity,
        invocations,
        {**durations_ms, **{f"db:{key}": value for key, value in call_latency.items()}},
    )


def _resource_sync_paths(path: Path) -> tuple[Path, Path]:
    return (
        path.with_name(f"{path.name}.sync-request"),
        path.with_name(f"{path.name}.sync-response"),
    )


def _resource_time_origin(path: Path, *, timeout_seconds: float = 30.0) -> float:
    request, response = _resource_sync_paths(path)
    request.unlink(missing_ok=True)
    response.unlink(missing_ok=True)
    descriptor = os.open(request, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("ready\n")
            handle.flush()
            os.fsync(handle.fileno())
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            try:
                origin = float(response.read_text(encoding="utf-8").strip())
            except (FileNotFoundError, ValueError):
                time.sleep(0.05)
                continue
            if origin < 0:
                raise ProofFailure("resources.sampler_origin_invalid")
            return origin
        raise ProofFailure("resources.sampler_origin_timeout")
    finally:
        request.unlink(missing_ok=True)
        response.unlink(missing_ok=True)


def _parse_resource_sample(fields: list[str]) -> ResourceSample:
    if len(fields) != 14:
        raise ProofFailure("resources.row_invalid")
    try:
        elapsed_seconds = float(fields[0])
        integer_values = [int(value) for value in fields[1:12]]
    except ValueError as error:
        raise ProofFailure("resources.row_invalid") from error
    if (
        not math.isfinite(elapsed_seconds)
        or elapsed_seconds < 0
        or any(value < 0 for value in integer_values)
        or integer_values[7] not in {0, 1}
        or integer_values[8] not in range(FORMAL_WORKER_REPLICAS + 1)
        or not HASH_PATTERN.fullmatch(fields[12])
        or not HASH_PATTERN.fullmatch(fields[13])
    ):
        raise ProofFailure("resources.row_invalid")
    return ResourceSample(
        elapsed_seconds=elapsed_seconds,
        api_rss_bytes=integer_values[0],
        api_fd_count=integer_values[1],
        worker_rss_bytes=integer_values[2],
        worker_fd_count=integer_values[3],
        postgres_connections=integer_values[4],
        api_restart_count=integer_values[5],
        worker_restart_count=integer_values[6],
        api_running=integer_values[7],
        worker_running=integer_values[8],
        api_process_count=integer_values[9],
        worker_process_count=integer_values[10],
        api_process_identity_sha256=fields[12],
        worker_process_identity_sha256=fields[13],
    )


def _process_cohort_evidence(samples: list[ResourceSample]) -> dict[str, object]:
    def service_evidence(
        *,
        process_counts: list[int],
        identities: list[str],
        minimum_process_count: int,
    ) -> dict[str, object]:
        distinct_counts = sorted(set(process_counts))
        distinct_identities = sorted(set(identities))
        count_stable = len(distinct_counts) == 1
        identity_unique = len(distinct_identities) == 1
        minimum_met = bool(process_counts) and all(
            count >= minimum_process_count for count in process_counts
        )
        passed = bool(process_counts) and count_stable and identity_unique and minimum_met
        return {
            "sample_count": len(process_counts),
            "minimum_process_count": minimum_process_count,
            "process_counts": distinct_counts,
            "process_count_stable": count_stable,
            "minimum_process_count_met": minimum_met,
            "identity_sha256_values": distinct_identities,
            "identity_sha256_unique": identity_unique,
            "passed": passed,
        }

    api = service_evidence(
        process_counts=[sample.api_process_count for sample in samples],
        identities=[sample.api_process_identity_sha256 for sample in samples],
        minimum_process_count=3,
    )
    worker = service_evidence(
        process_counts=[sample.worker_process_count for sample in samples],
        identities=[sample.worker_process_identity_sha256 for sample in samples],
        minimum_process_count=FORMAL_WORKER_REPLICAS,
    )
    return {
        "scope": "measured_and_idle_samples",
        "evaluated": bool(samples),
        "sample_count": len(samples),
        "api": api,
        "worker": worker,
        "all_valid": bool(api["passed"] and worker["passed"]),
    }


def _rss_growth_evidence(
    measured_samples: list[ResourceSample],
    idle_samples: list[ResourceSample],
    *,
    formal: bool,
    rss_attribute: str,
) -> dict[str, object]:
    threshold_percent = float(THRESHOLDS["rss_growth_percent_max"])

    def empty_window() -> dict[str, object]:
        return {
            "sample_count": 0,
            "sample_span_seconds": None,
            "minimum_sample_count": FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES,
            "minimum_span_seconds": FORMAL_RSS_ENDPOINT_WINDOW_MIN_SPAN_SECONDS,
            "median_rss_bytes": None,
            "complete": False,
        }

    def window_evidence(samples: list[ResourceSample]) -> tuple[dict[str, object], float | None]:
        span_seconds = (
            samples[-1].elapsed_seconds - samples[0].elapsed_seconds if len(samples) >= 2 else 0.0
        )
        rss_values = [float(getattr(sample, rss_attribute)) for sample in samples]
        median_rss = float(median(rss_values)) if rss_values else None
        complete = (
            len(samples) == FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES
            and span_seconds >= FORMAL_RSS_ENDPOINT_WINDOW_MIN_SPAN_SECONDS
            and median_rss is not None
            and median_rss > 0
        )
        return (
            {
                "sample_count": len(samples),
                "sample_span_seconds": round(span_seconds, 3),
                "minimum_sample_count": FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES,
                "minimum_span_seconds": FORMAL_RSS_ENDPOINT_WINDOW_MIN_SPAN_SECONDS,
                "median_rss_bytes": median_rss,
                "complete": complete,
            },
            median_rss,
        )

    idle_span_seconds = (
        idle_samples[-1].elapsed_seconds - idle_samples[0].elapsed_seconds
        if len(idle_samples) >= 2
        else 0.0
    )
    if not formal:
        return {
            "evaluated": False,
            "method": "steady_endpoint_window_median_v1",
            "threshold_percent": threshold_percent,
            "observed_measured_sample_count": len(measured_samples),
            "baseline_window": empty_window(),
            "terminal_window": empty_window(),
            "windows_non_overlapping": False,
            "growth_percent": None,
            "growth_percent_rounded": None,
            "active_within_budget": None,
            "idle_confirmation": {
                "required": False,
                "evaluated": False,
                "method": "four_block_budget_confirmation_v1",
                "sample_count": len(idle_samples),
                "sample_span_seconds": round(idle_span_seconds, 3),
                "minimum_sample_count": FORMAL_RESOURCE_IDLE_MIN_SAMPLES,
                "minimum_span_seconds": FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS,
                "block_sample_counts": [],
                "block_median_rss_bytes": [],
                "baseline_median_rss_bytes": None,
                "budget_ceiling_rss_bytes": None,
                "last_two_block_median_rss_bytes": [],
                "status": "not_evaluated",
                "within_budget": None,
            },
            "within_budget": None,
        }

    baseline_samples = measured_samples[:FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES]
    terminal_samples = measured_samples[-FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES:]
    baseline_window, baseline_median = window_evidence(baseline_samples)
    terminal_window, terminal_median = window_evidence(terminal_samples)
    windows_non_overlapping = bool(
        baseline_samples
        and terminal_samples
        and baseline_samples[-1].elapsed_seconds < terminal_samples[0].elapsed_seconds
    )
    endpoint_evaluated = bool(
        baseline_window["complete"]
        and terminal_window["complete"]
        and windows_non_overlapping
        and baseline_median is not None
        and terminal_median is not None
    )
    growth_percent_unrounded = (
        (terminal_median - baseline_median) / baseline_median * 100.0
        if endpoint_evaluated and baseline_median is not None and terminal_median is not None
        else None
    )
    active_within_budget = bool(
        endpoint_evaluated
        and baseline_median is not None
        and terminal_median is not None
        and terminal_median * 100.0 <= baseline_median * (100.0 + threshold_percent)
    )

    idle_complete = (
        len(idle_samples) >= FORMAL_RESOURCE_IDLE_MIN_SAMPLES
        and idle_span_seconds >= FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS
        and baseline_median is not None
        and baseline_median > 0
    )
    idle_blocks = (
        [
            idle_samples[
                index * len(idle_samples) // FORMAL_RSS_IDLE_BLOCK_COUNT : (index + 1)
                * len(idle_samples)
                // FORMAL_RSS_IDLE_BLOCK_COUNT
            ]
            for index in range(FORMAL_RSS_IDLE_BLOCK_COUNT)
        ]
        if idle_complete
        else []
    )
    idle_levels = (
        [
            float(median([float(getattr(sample, rss_attribute)) for sample in block]))
            for block in idle_blocks
        ]
        if idle_blocks and all(idle_blocks)
        else []
    )
    budget_ceiling = baseline_median * (1.0 + threshold_percent / 100.0) if idle_levels else None
    last_two_idle_levels = idle_levels[-2:] if idle_levels else []
    if budget_ceiling is None or len(last_two_idle_levels) != 2:
        idle_status = "insufficient_samples"
    elif all(
        level * 100.0 <= baseline_median * (100.0 + threshold_percent)
        for level in last_two_idle_levels
    ):
        idle_status = "within_budget"
    elif all(
        level * 100.0 > baseline_median * (100.0 + threshold_percent)
        for level in last_two_idle_levels
    ):
        idle_status = "retained_over_budget"
    else:
        idle_status = "inconclusive"
    idle_within_budget = idle_status == "within_budget"
    within_budget = endpoint_evaluated and active_within_budget and idle_within_budget
    growth_percent_rounded = (
        round(growth_percent_unrounded, 3) if growth_percent_unrounded is not None else None
    )
    return {
        "evaluated": endpoint_evaluated,
        "method": "steady_endpoint_window_median_v1",
        "threshold_percent": threshold_percent,
        "observed_measured_sample_count": len(measured_samples),
        "baseline_window": baseline_window,
        "terminal_window": terminal_window,
        "windows_non_overlapping": windows_non_overlapping,
        "growth_percent": growth_percent_unrounded,
        "growth_percent_rounded": growth_percent_rounded,
        "active_within_budget": active_within_budget if endpoint_evaluated else False,
        "idle_confirmation": {
            "required": True,
            "evaluated": bool(idle_levels),
            "method": "four_block_budget_confirmation_v1",
            "sample_count": len(idle_samples),
            "sample_span_seconds": round(idle_span_seconds, 3),
            "minimum_sample_count": FORMAL_RESOURCE_IDLE_MIN_SAMPLES,
            "minimum_span_seconds": FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS,
            "block_sample_counts": [len(block) for block in idle_blocks],
            "block_median_rss_bytes": idle_levels,
            "baseline_median_rss_bytes": baseline_median,
            "budget_ceiling_rss_bytes": budget_ceiling,
            "last_two_block_median_rss_bytes": last_two_idle_levels,
            "status": idle_status,
            "within_budget": idle_within_budget,
        },
        "within_budget": within_budget,
    }


def _resource_evidence(
    path: Path,
    shape: Shape,
    *,
    warmup_finished_seconds: float,
    load_finished_seconds: float,
    idle_finished_seconds: float,
) -> dict[str, object]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != RESOURCE_HEADER:
        raise ProofFailure("resources.header_invalid")
    rows: list[ResourceSample] = []
    for line in lines[1:]:
        rows.append(_parse_resource_sample(line.split("\t")))
    if not rows:
        raise ProofFailure("resources.samples_missing")
    if any(
        current.elapsed_seconds <= previous.elapsed_seconds
        for previous, current in zip(rows, rows[1:], strict=False)
    ):
        raise ProofFailure("resources.elapsed_not_increasing")
    if load_finished_seconds < warmup_finished_seconds:
        raise ProofFailure("resources.load_boundary_invalid")
    if idle_finished_seconds < load_finished_seconds:
        raise ProofFailure("resources.idle_boundary_invalid")
    measured_rows = [
        row
        for row in rows
        if warmup_finished_seconds <= row.elapsed_seconds <= load_finished_seconds
    ]
    idle_rows = [
        row for row in rows if load_finished_seconds < row.elapsed_seconds <= idle_finished_seconds
    ]
    if shape.formal and not measured_rows:
        raise ProofFailure("resources.measured_samples_missing")
    selected = measured_rows or rows
    minimum_samples = max(1, math.floor(shape.duration_seconds / 5 * 0.9)) if shape.formal else 1
    idle_span_seconds = (
        idle_rows[-1].elapsed_seconds - idle_rows[0].elapsed_seconds if len(idle_rows) >= 2 else 0.0
    )
    idle_samples_complete = not shape.formal or (
        len(idle_rows) >= FORMAL_RESOURCE_IDLE_MIN_SAMPLES
        and idle_span_seconds >= FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS
    )

    def resource_trend(
        samples: list[tuple[float, float]],
        idle_samples: list[tuple[float, float]],
    ) -> dict[str, object]:
        sample_count = len(samples)
        if not shape.formal or sample_count < minimum_samples:
            return {
                "sample_count": sample_count,
                "evaluated": False,
                "method": (
                    "six_block_median_low_with_terminal_subwindows_and_post_load_idle_confirmation"
                ),
                "block_sample_counts": [],
                "block_median_levels": [],
                "new_high_event_blocks": [],
                "new_high_event_count": 0,
                "first_to_last_delta": 0.0,
                "global_candidate_growth": False,
                "global_sustained_growth": False,
                "terminal_window": {
                    "evaluated": False,
                    "block_sample_counts": [],
                    "block_median_levels": [],
                    "new_high_event_blocks": [],
                    "new_high_event_count": 0,
                    "first_to_last_delta": 0.0,
                    "candidate_growth": False,
                    "sustained_growth": False,
                },
                "idle_recovery": {
                    "required": shape.formal,
                    "evaluated": False,
                    "sample_count": len(idle_samples),
                    "sample_span_seconds": round(idle_span_seconds, 3),
                    "minimum_sample_count": FORMAL_RESOURCE_IDLE_MIN_SAMPLES,
                    "minimum_span_seconds": FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS,
                    "samples_complete": idle_samples_complete,
                    "block_sample_counts": [],
                    "block_median_levels": [],
                    "reference_level": None,
                    "retained_growth_threshold": None,
                    "last_two_block_levels": [],
                    "continued_growth_candidate": False,
                    "status": "not_evaluated",
                },
                "least_squares_slope_per_minute": 0.0,
                "candidate_growth": False,
                "confirmed_sustained_growth": False,
                "sustained_growth": False,
            }

        def repeated_new_high(levels: list[float]) -> tuple[list[int], float, bool]:
            running_high = levels[0]
            event_blocks: list[int] = []
            for block_index, level in enumerate(levels[1:], start=1):
                if level >= running_high + 1.0:
                    event_blocks.append(block_index)
                    running_high = level
            delta = levels[-1] - levels[0]
            return event_blocks, delta, len(event_blocks) >= 2 and delta >= 2.0

        blocks = [
            samples[index * sample_count // 6 : (index + 1) * sample_count // 6]
            for index in range(6)
        ]
        block_levels = [float(median_low([sample[1] for sample in block])) for block in blocks]
        new_high_event_blocks, first_to_last_delta, global_candidate = repeated_new_high(
            block_levels
        )
        terminal_samples = blocks[-1]
        terminal_count = len(terminal_samples)
        terminal_blocks = (
            [
                terminal_samples[index * terminal_count // 4 : (index + 1) * terminal_count // 4]
                for index in range(4)
            ]
            if terminal_count >= 4
            else []
        )
        terminal_levels = (
            [float(median_low([sample[1] for sample in block])) for block in terminal_blocks]
            if terminal_blocks
            else []
        )
        if terminal_levels:
            terminal_events, terminal_delta, terminal_candidate = repeated_new_high(terminal_levels)
        else:
            terminal_events, terminal_delta, terminal_candidate = [], 0.0, False

        active_candidate = global_candidate or terminal_candidate
        idle_blocks = (
            [
                idle_samples[index * len(idle_samples) // 4 : (index + 1) * len(idle_samples) // 4]
                for index in range(4)
            ]
            if idle_samples_complete
            else []
        )
        idle_levels = (
            [float(median_low([sample[1] for sample in block])) for block in idle_blocks]
            if idle_blocks
            else []
        )
        reference_level = block_levels[0]
        retained_growth_threshold = reference_level + 2.0
        if idle_levels:
            _, _, idle_continued_growth = repeated_new_high(idle_levels)
            last_two_idle_levels = idle_levels[-2:]
            if idle_continued_growth:
                idle_status = "continued_growth"
            elif all(level < retained_growth_threshold for level in last_two_idle_levels):
                idle_status = "recovered"
            elif all(level >= retained_growth_threshold for level in last_two_idle_levels):
                idle_status = "retained"
            else:
                idle_status = "inconclusive"
        else:
            idle_continued_growth = False
            last_two_idle_levels = []
            idle_status = "insufficient_samples"

        confirmation_failed = idle_status != "recovered"
        global_sustained = global_candidate and confirmation_failed
        terminal_sustained = terminal_candidate and confirmation_failed
        sustained = idle_continued_growth or (active_candidate and confirmation_failed)

        elapsed_minutes = [(sample[0] - samples[0][0]) / 60.0 for sample in samples]
        values = [sample[1] for sample in samples]
        x_mean = sum(elapsed_minutes) / sample_count
        y_mean = sum(values) / sample_count
        denominator = sum((elapsed - x_mean) ** 2 for elapsed in elapsed_minutes)
        slope = (
            sum(
                (elapsed - x_mean) * (value - y_mean)
                for elapsed, value in zip(elapsed_minutes, values, strict=True)
            )
            / denominator
            if denominator > 0
            else 0.0
        )
        return {
            "sample_count": sample_count,
            "evaluated": True,
            "method": (
                "six_block_median_low_with_terminal_subwindows_and_post_load_idle_confirmation"
            ),
            "block_sample_counts": [len(block) for block in blocks],
            "block_median_levels": block_levels,
            "new_high_event_blocks": new_high_event_blocks,
            "new_high_event_count": len(new_high_event_blocks),
            "first_to_last_delta": round(first_to_last_delta, 3),
            "global_candidate_growth": global_candidate,
            "global_sustained_growth": global_sustained,
            "terminal_window": {
                "evaluated": bool(terminal_blocks),
                "block_sample_counts": [len(block) for block in terminal_blocks],
                "block_median_levels": terminal_levels,
                "new_high_event_blocks": terminal_events,
                "new_high_event_count": len(terminal_events),
                "first_to_last_delta": round(terminal_delta, 3),
                "candidate_growth": terminal_candidate,
                "sustained_growth": terminal_sustained,
            },
            "idle_recovery": {
                "required": True,
                "evaluated": bool(idle_blocks),
                "sample_count": len(idle_samples),
                "sample_span_seconds": round(idle_span_seconds, 3),
                "minimum_sample_count": FORMAL_RESOURCE_IDLE_MIN_SAMPLES,
                "minimum_span_seconds": FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS,
                "samples_complete": idle_samples_complete,
                "block_sample_counts": [len(block) for block in idle_blocks],
                "block_median_levels": idle_levels,
                "reference_level": reference_level,
                "retained_growth_threshold": retained_growth_threshold,
                "last_two_block_levels": last_two_idle_levels,
                "continued_growth_candidate": idle_continued_growth,
                "status": idle_status,
            },
            "least_squares_slope_per_minute": round(slope, 6),
            "candidate_growth": active_candidate,
            "confirmed_sustained_growth": sustained,
            "sustained_growth": sustained,
        }

    api_rss_growth = _rss_growth_evidence(
        selected,
        idle_rows,
        formal=shape.formal,
        rss_attribute="api_rss_bytes",
    )
    worker_rss_growth = _rss_growth_evidence(
        selected,
        idle_rows,
        formal=shape.formal,
        rss_attribute="worker_rss_bytes",
    )
    api_fd_trend = resource_trend(
        [(row.elapsed_seconds, row.api_fd_count) for row in selected],
        [(row.elapsed_seconds, row.api_fd_count) for row in idle_rows],
    )
    worker_fd_trend = resource_trend(
        [(row.elapsed_seconds, row.worker_fd_count) for row in selected],
        [(row.elapsed_seconds, row.worker_fd_count) for row in idle_rows],
    )
    postgres_connection_trend = resource_trend(
        [(row.elapsed_seconds, row.postgres_connections) for row in selected],
        [(row.elapsed_seconds, row.postgres_connections) for row in idle_rows],
    )
    cohort_samples = [*selected, *idle_rows]
    process_cohort_evidence = _process_cohort_evidence(cohort_samples)
    survival = all(
        row.api_running == 1 and row.worker_running == FORMAL_WORKER_REPLICAS for row in rows
    )
    restart_free = all(row.api_restart_count == 0 and row.worker_restart_count == 0 for row in rows)
    return {
        "sample_count": len(rows),
        "measured_sample_count": len(selected),
        "minimum_sample_count": minimum_samples,
        "measured_sample_count_passed": len(selected) >= minimum_samples,
        "idle_recovery_required": shape.formal,
        "idle_recovery_sample_count": len(idle_rows),
        "idle_recovery_minimum_sample_count": FORMAL_RESOURCE_IDLE_MIN_SAMPLES,
        "idle_recovery_sample_span_seconds": round(idle_span_seconds, 3),
        "idle_recovery_minimum_span_seconds": FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS,
        "idle_recovery_samples_complete": idle_samples_complete,
        "sample_count_passed": len(selected) >= minimum_samples and idle_samples_complete,
        "warmup_boundary_elapsed_seconds": round(warmup_finished_seconds, 3),
        "load_end_boundary_elapsed_seconds": round(load_finished_seconds, 3),
        "idle_end_boundary_elapsed_seconds": round(idle_finished_seconds, 3),
        "api_peak_rss_bytes": max(row.api_rss_bytes for row in rows),
        "worker_peak_rss_bytes": max(row.worker_rss_bytes for row in rows),
        "api_rss_growth": api_rss_growth,
        "worker_rss_growth": worker_rss_growth,
        "process_cohort_evidence": process_cohort_evidence,
        "api_fd_sustained_growth": bool(api_fd_trend["sustained_growth"]),
        "worker_fd_sustained_growth": bool(worker_fd_trend["sustained_growth"]),
        "postgres_connection_sustained_growth": bool(postgres_connection_trend["sustained_growth"]),
        "api_fd_trend": api_fd_trend,
        "worker_fd_trend": worker_fd_trend,
        "postgres_connection_trend": postgres_connection_trend,
        "services_survived_all_samples": survival,
        "restart_count_zero": restart_free,
    }


def _latency_summary(
    observations: list[Observation],
    invocations: dict[str, int],
    durations: dict[str, float],
) -> dict[str, object]:
    accepted_observations = [item for item in observations if item.accepted and bool(item.run_id)]
    excluded: list[float] = []
    provider_wall: list[float] = []
    db_call: list[float] = []
    for item in accepted_observations:
        wall_ms = durations.get(item.request_hash, 0.0)
        db_ms = durations.get(f"db:{item.run_id}", 0.0)
        if invocations.get(item.request_hash) != 1 or wall_ms <= 0 or db_ms <= 0:
            continue
        provider_wall.append(wall_ms)
        db_call.append(db_ms)
        excluded.append(max(0.0, item.elapsed_ms - max(wall_ms, db_ms)))
    return {
        "attempted_sample_count": len(observations),
        "accepted_sample_count": len(accepted_observations),
        "sample_count": len(excluded),
        "missing_persistent_evidence_count": len(accepted_observations) - len(excluded),
        "provider_excluded_p95_ms": round(_percentile(excluded, 0.95), 3),
        "provider_excluded_p99_ms": round(_percentile(excluded, 0.99), 3),
        "proof_provider_wall_p95_ms": round(_percentile(provider_wall, 0.95), 3),
        "database_provider_call_p95_ms": round(_percentile(db_call, 0.95), 3),
        "exclusion_method": (
            "client_elapsed_minus_max_persistent_provider_wall_and_database_provider_call"
        ),
        "all_accepted_samples_have_persistent_provider_evidence": len(excluded)
        == len(accepted_observations),
    }


def _identity() -> dict[str, object]:
    dataset_config, dataset_sha256 = _dataset_attribution()
    git_dirty, git_dirty_count = _git_state()
    docker_fields = {
        key.removeprefix("P5_B4_DOCKER_").lower(): value
        for key, value in os.environ.items()
        if key.startswith("P5_B4_DOCKER_") and value.strip()
    }
    return {
        "revision": _env("P5_B4_REVISION"),
        "proof_image": _env("P5_B4_PROOF_IMAGE_ID"),
        "context_sha256": _sha_env("P5_B4_CONTEXT_SHA256"),
        "harness_sha256": _sha_env("P5_B4_HARNESS_SHA256"),
        "compose_sha256": _sha_env("P5_B4_COMPOSE_SHA256"),
        "wrapper_sha256": _sha_env("P5_B4_WRAPPER_SHA256"),
        "git_status_sha256": _sha_env("P5_B4_GIT_STATUS_SHA256"),
        "git_dirty": git_dirty,
        "git_dirty_count": git_dirty_count,
        "postgres_image": _env("P5_B4_POSTGRES_IMAGE_ID"),
        "redis_image": _env("P5_B4_REDIS_IMAGE_ID"),
        "migration_manifest_sha256": _sha_env("P5_B4_MIGRATION_MANIFEST_SHA256"),
        "migration_head_sha256": _sha_env("P5_B4_MIGRATION_HEAD_SHA256"),
        "migration_head_source_sha256": _sha_env("P5_B4_MIGRATION_HEAD_SOURCE_SHA256"),
        "environment_fingerprint": _env("P5_B4_ENVIRONMENT_FINGERPRINT"),
        "dataset_fingerprint": _env("P5_B4_DATASET_ID"),
        "dataset_config": dataset_config,
        "dataset_sha256": dataset_sha256,
        "docker": docker_fields,
    }


def _record_configuration(shape: Shape, *, provider_delay_ms: int) -> dict[str, object]:
    return {
        "duration_seconds": shape.duration_seconds,
        "warmup_seconds": shape.warmup_seconds,
        "concurrency_cap": shape.concurrency,
        "request_rate": shape.request_rate,
        "site_count": SITE_COUNT,
        "queue_burst": shape.queue_burst,
        "worker_poll_seconds": DEFAULT_WORKER_POLL_SECONDS,
        "worker_batch_size": DEFAULT_WORKER_BATCH_SIZE,
        "worker_replicas": FORMAL_WORKER_REPLICAS,
        "provider_delay_ms": provider_delay_ms,
        "resource_idle_recovery_seconds": (
            FORMAL_RESOURCE_IDLE_RECOVERY_SECONDS if shape.formal else 0
        ),
        "resource_idle_minimum_sample_count": (
            FORMAL_RESOURCE_IDLE_MIN_SAMPLES if shape.formal else 0
        ),
        "resource_idle_minimum_span_seconds": (
            FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS if shape.formal else 0
        ),
        "resource_process_scope": "pid1_service_trees_aggregate_stable_cohort_v3",
        "rss_endpoint_window_sample_count": (
            FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES if shape.formal else 0
        ),
        "rss_endpoint_window_min_span_seconds": (
            FORMAL_RSS_ENDPOINT_WINDOW_MIN_SPAN_SECONDS if shape.formal else 0
        ),
        "rss_growth_method": "steady_endpoint_window_median_v1" if shape.formal else "unevaluated",
        "rss_growth_percent_max": THRESHOLDS["rss_growth_percent_max"] if shape.formal else 0,
        "rss_idle_method": "four_block_budget_confirmation_v1" if shape.formal else "unevaluated",
    }


def _expected_record_shape(mode: str) -> Shape:
    if mode == "formal":
        return Shape(
            mode="formal",
            duration_seconds=FORMAL_DURATION_SECONDS,
            warmup_seconds=FORMAL_WARMUP_SECONDS,
            concurrency=FORMAL_CONCURRENCY,
            request_rate=FORMAL_REQUEST_RATE,
            queue_burst=FORMAL_QUEUE_BURST,
        )
    return Shape(
        mode="quick",
        duration_seconds=5,
        warmup_seconds=3,
        concurrency=2,
        request_rate=2.0,
        queue_burst=8,
    )


async def _run_record(args: argparse.Namespace) -> tuple[dict[str, object], bool]:
    shape = _shape(args.mode)
    if args.baseline_index < 1:
        raise ProofFailure("configuration.baseline_index_invalid")
    settings = _settings()
    _validate_targets(settings, fresh=False)
    manifest = _manifest(settings, args.baseline_index)
    baseline_environment_receipt = hashlib.sha256(_env("P5_B4_PROOF_PROJECT").encode()).hexdigest()
    credentials = [_site_credential(index) for index in range(SITE_COUNT)]
    observations: list[Observation] = []
    unexpected_5xx = 0
    api_url = _env("P5_B4_PROOF_API_URL")
    resource_time_origin = await asyncio.to_thread(_resource_time_origin, args.resource_file)
    record_started = time.monotonic()
    limits = httpx.Limits(
        max_connections=shape.concurrency,
        max_keepalive_connections=shape.concurrency,
        keepalive_expiry=5.0,
    )
    async with httpx.AsyncClient(base_url=api_url, timeout=45.0, limits=limits) as client:
        before_mismatch = await asyncio.to_thread(_side_effect_snapshot, settings)
        mismatch = await _execute(
            client,
            credential=credentials[0],
            label=f"baseline-{args.baseline_index}-cross-mismatch",
            phase="cross_site",
            payload_site=credentials[1][0],
        )
        after_mismatch = await asyncio.to_thread(_side_effect_snapshot, settings)
        unexpected_5xx += int(mismatch.http_status >= 500)
        mismatch_ok = (
            mismatch.http_status == 400
            and mismatch.error_code == "auth.site_mismatch"
            and before_mismatch == after_mismatch
            and not mismatch.run_id
        )

        sentinel = await _execute(
            client,
            credential=credentials[0],
            label=f"baseline-{args.baseline_index}-cross-valid",
            phase="cross_site",
        )
        observations.append(sentinel)
        run_path = f"/v1/runs/{sentinel.run_id}"
        result_path = f"{run_path}/result"
        wrong_run = await _signed_get(client, run_path, credentials[1], "cross-run-read")
        wrong_result = await _signed_get(client, result_path, credentials[1], "cross-result-read")
        own_result = await _signed_get(client, result_path, credentials[0], "own-result-read")
        unexpected_5xx += sum(status >= 500 for status, _ in (wrong_run, wrong_result, own_result))
        isolation = {
            "payload_mismatch_zero_side_effect": mismatch_ok,
            "cross_site_record_read_rejected": wrong_run == (404, "runtime.run_not_found"),
            "cross_site_result_read_rejected": wrong_result == (404, "runtime.run_not_found"),
            "own_site_result_read_succeeded": own_result[0] == 200,
        }

        probe, probe_client_max = await _concurrency_probe(
            client,
            credentials,
            baseline_index=args.baseline_index,
            concurrency=shape.concurrency,
        )
        observations.extend(probe)
        unexpected_5xx += sum(item.http_status >= 500 for item in probe)

        queue_observations = await _queue_burst(
            client,
            credentials,
            baseline_index=args.baseline_index,
            count=shape.queue_burst,
            concurrency=shape.concurrency,
        )
        observations.extend(queue_observations)
        unexpected_5xx += sum(item.http_status >= 500 for item in queue_observations)
        queue_ids = {
            item.run_id
            for item in queue_observations
            if item.http_status == 200 and item.runtime_status == "queued" and item.run_id
        }
        terminal = await _wait_terminal(
            settings,
            queue_ids,
            timeout=max(60.0, shape.queue_burst * FORMAL_PROVIDER_DELAY_MS / 1_000 * 2),
        )
        queue_completed = sum(status == "succeeded" for status in terminal.values())
        accepted_queue = [
            (item, credentials[index % SITE_COUNT])
            for index, item in enumerate(queue_observations)
            if item.run_id in queue_ids
        ]
        if accepted_queue:
            queued_item, queued_credential = accepted_queue[0]
            queued_result = await _signed_get(
                client,
                f"/v1/runs/{queued_item.run_id}/result",
                queued_credential,
                "queue-result-read",
            )
        else:
            queued_result = (0, "")
        unexpected_5xx += int(queued_result[0] >= 500)

        warmup, warmup_stats = await _scheduled_phase(
            client,
            credentials,
            label_prefix=f"baseline-{args.baseline_index}-warmup",
            phase="warmup",
            duration_seconds=shape.warmup_seconds,
            rate=shape.request_rate,
            concurrency=shape.concurrency,
        )
        observations.extend(warmup)
        unexpected_5xx += sum(item.http_status >= 500 for item in warmup)
        warmup_finished_seconds = resource_time_origin + time.monotonic() - record_started
        soak, soak_stats = await _scheduled_phase(
            client,
            credentials,
            label_prefix=f"baseline-{args.baseline_index}-soak",
            phase="soak",
            duration_seconds=shape.duration_seconds,
            rate=shape.request_rate,
            concurrency=shape.concurrency,
        )
        observations.extend(soak)
        unexpected_5xx += sum(item.http_status >= 500 for item in soak)

    load_finished_seconds = resource_time_origin + time.monotonic() - record_started
    idle_finished_seconds = load_finished_seconds
    if shape.formal:
        await asyncio.to_thread(_resource_time_origin, args.resource_file)
        await asyncio.sleep(FORMAL_RESOURCE_IDLE_RECOVERY_SECONDS)
        idle_finished_seconds = await asyncio.to_thread(_resource_time_origin, args.resource_file)

    integrity, invocations, durations = _integrity(
        settings,
        observations,
        queue_ids,
        expected_queue_count=shape.queue_burst,
    )
    latency = _latency_summary(soak, invocations, durations)
    resources = _resource_evidence(
        args.resource_file,
        shape,
        warmup_finished_seconds=warmup_finished_seconds,
        load_finished_seconds=load_finished_seconds,
        idle_finished_seconds=idle_finished_seconds,
    )
    identity = _identity()
    attempted = len(observations)
    accepted = sum(item.accepted for item in observations)
    completed = int(integrity["succeeded_records"])
    diagnostics = _diagnostic_summary([mismatch, *observations])
    accepted_rate = accepted / attempted if attempted else 0.0
    completed_rate = completed / accepted if accepted else 0.0
    residue = sum(
        int(integrity[key])
        for key in (
            "queued_residue",
            "running_residue",
            "dispatching_residue",
            "redis_queue_residue",
            "provider_active_residue",
        )
    )
    api_rss_growth = cast(dict[str, object], resources["api_rss_growth"])
    worker_rss_growth = cast(dict[str, object], resources["worker_rss_growth"])
    rss_growth_passed = not shape.formal or (
        api_rss_growth["within_budget"] is True and worker_rss_growth["within_budget"] is True
    )
    process_cohort_evidence = cast(dict[str, object], resources["process_cohort_evidence"])
    concurrency_target = shape.concurrency if shape.formal else 1
    queue_exact = _queue_gate(
        shape.queue_burst,
        len(queue_ids) if len(queue_observations) == shape.queue_burst else -1,
        queue_completed,
        queued_result[0],
    )
    queue_timing = cast(dict[str, object], integrity["queue_timing_evidence"])
    checks = {
        "unexpected_5xx_zero": unexpected_5xx == 0,
        "transport_http_failures_zero": _transport_http_failures_zero(diagnostics),
        "accepted_rate": accepted_rate >= THRESHOLDS["accepted_rate_min"],
        "completed_rate": completed_rate >= THRESHOLDS["completed_rate_min"],
        "provider_excluded_p95": float(latency["provider_excluded_p95_ms"]) <= 500,
        "provider_excluded_p99": float(latency["provider_excluded_p99_ms"]) <= 1_000,
        "persistent_provider_latency_complete": bool(
            latency["all_accepted_samples_have_persistent_provider_evidence"]
        ),
        "queue_requested_accepted_completed_exact": queue_exact,
        "queue_timing_evidence_complete": (
            int(queue_timing["sample_count"]) == shape.queue_burst
            and bool(queue_timing["complete"])
        ),
        "queue_wait": float(integrity["queue_wait_p95_seconds"]) <= DEFAULT_WORKER_POLL_SECONDS * 2,
        "identifier_set_exact": bool(integrity["observed_identifier_set_exact"]),
        "observation_diagnostics_complete": bool(
            _diagnostics_valid(diagnostics) and diagnostics["complete"]
        ),
        "proof_fixture_rejections_zero": _proof_fixture_rejections_zero(diagnostics),
        "provider_usage_integrity": _provider_usage_integrity_passed(integrity),
        "cross_site_and_result_read_isolation": all(isolation.values()),
        "runtime_queue_residue_zero": residue == 0,
        "artifacts_returned_to_manifest_baseline": int(integrity["artifact_records"])
        == int(manifest["artifact_baseline"]),
        "rss_growth": rss_growth_passed,
        "process_cohort_stable": process_cohort_evidence["all_valid"] is True,
        "api_fd_not_sustained_growth": not bool(resources["api_fd_sustained_growth"]),
        "worker_fd_not_sustained_growth": not bool(resources["worker_fd_sustained_growth"]),
        "db_connections_not_sustained_growth": not bool(
            resources["postgres_connection_sustained_growth"]
        ),
        "resource_samples_complete": bool(resources["sample_count_passed"]),
        "services_survived": bool(resources["services_survived_all_samples"]),
        "service_restarts_zero": bool(resources["restart_count_zero"]),
        "formal_clean_revision_requirement_satisfied": not shape.formal
        or not bool(identity["git_dirty"]),
        "achieved_rate": _achieved_rate_passed(
            float(soak_stats["achieved_requests_per_second"]), shape.request_rate
        ),
        "scheduler_drift": float(soak_stats["scheduler_drift_max_ms"])
        <= THRESHOLDS["scheduler_drift_ms_max"],
        "real_concurrency_observed": (
            probe_client_max >= concurrency_target
            and int(integrity["provider_max_concurrency"]) >= concurrency_target
            and int(integrity["provider_barrier_timeouts"]) == 0
        ),
    }
    if tuple(checks) != RECORD_CHECK_IDS:
        raise ProofFailure("harness.record_check_contract_drift")
    passed = all(checks.values())
    report = {
        "contract": CONTRACT_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "verdict": "record_passed" if passed else "record_failed",
        "mode": shape.mode,
        "baseline_index": args.baseline_index,
        "baseline_environment_receipt_sha256": baseline_environment_receipt,
        "record_thresholds_passed": passed,
        "formal_record_shape": shape.formal,
        "formal_acceptance": False,
        "production_slo_claim": False,
        "identity": identity,
        "configuration": _record_configuration(
            shape,
            provider_delay_ms=int(os.environ.get("P5_B4_PROVIDER_DELAY_MS", "0")),
        ),
        "scheduler": {
            "warmup": warmup_stats,
            "measured": soak_stats,
            "concurrency_probe_client_max": probe_client_max,
            "concurrency_probe_provider_max": integrity["provider_max_concurrency"],
        },
        "requests": {
            "attempted": attempted,
            "accepted": accepted,
            "completed": completed,
            "accepted_rate": round(accepted_rate, 6),
            "completed_rate": round(completed_rate, 6),
            "unexpected_5xx": unexpected_5xx,
        },
        "observation_diagnostics": diagnostics,
        "queue": {
            "requested": shape.queue_burst,
            "accepted": len(queue_ids),
            "completed": queue_completed,
            "wait_p95_seconds": integrity["queue_wait_p95_seconds"],
            "timing_evidence": queue_timing,
            "result_read_succeeded": queued_result[0] == 200,
        },
        "latency": latency,
        "integrity": integrity,
        "isolation": isolation,
        "resources": resources,
        "checks": checks,
        "boundary": dict(RECORD_BOUNDARY),
        "redaction": dict(RECORD_REDACTION),
        "limitations": list(RECORD_LIMITATIONS),
    }
    dispose_engine(settings.database_url)
    return report, passed


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regression_failed(reference_ms: float, later_ms: float) -> bool:
    delta = later_ms - reference_ms
    percent = (delta / reference_ms * 100.0) if reference_ms > 0 else (100.0 if delta > 0 else 0.0)
    return delta > 100.0 and percent > 20.0


def _canonical_record_mapping(record: dict[str, object], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, dict):
        raise ProofFailure(f"aggregate.{field}_invalid")
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ProofFailure(f"aggregate.{field}_invalid") from error


def _strict_int(value: object, *, minimum: int = 0) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= minimum


def _strict_float(value: object, *, minimum: float = 0.0) -> bool:
    return isinstance(value, float) and math.isfinite(value) and value >= minimum


def _finite_float(value: object) -> bool:
    return isinstance(value, float) and math.isfinite(value)


def _exact_mapping(value: object, keys: set[str]) -> dict[str, object] | None:
    if not isinstance(value, dict) or set(value) != keys:
        return None
    return cast(dict[str, object], value)


def _exact_typed_mapping(value: object, expected: dict[str, object]) -> bool:
    payload = _exact_mapping(value, set(expected))
    return bool(
        payload
        and all(
            type(payload[name]) is type(expected_value) and payload[name] == expected_value
            for name, expected_value in expected.items()
        )
    )


def _timing_distribution_valid(value: object, *, expected_samples: int) -> bool:
    payload = _exact_mapping(value, {"sample_count", "p50", "p90", "p95", "p99", "max"})
    if (
        not payload
        or not _strict_int(payload["sample_count"])
        or payload["sample_count"] != expected_samples
        or any(not _strict_float(payload[name]) for name in ("p50", "p90", "p95", "p99", "max"))
    ):
        return False
    percentiles = [cast(float, payload[name]) for name in ("p50", "p90", "p95", "p99", "max")]
    return percentiles == sorted(percentiles) and (
        expected_samples > 0 or all(value == 0.0 for value in percentiles)
    )


def _queue_timing_section_valid(value: object, *, required_count: int) -> bool:
    keys = {
        "sample_count",
        "processing_started_sample_count",
        "missing_started_at_count",
        "missing_processing_started_count",
        "timing_sample_count",
        "wait_seconds",
        "first_claim_lag_seconds",
        "submission_span_seconds",
        "processing_start_span_seconds",
        "adjacent_claim_gap_seconds",
        "complete",
    }
    payload = _exact_mapping(value, keys)
    if not payload or not _strict_int(required_count, minimum=1):
        return False
    count_fields = (
        "sample_count",
        "processing_started_sample_count",
        "missing_started_at_count",
        "missing_processing_started_count",
        "timing_sample_count",
    )
    if any(not _strict_int(payload[name]) for name in count_fields):
        return False
    sample_count = cast(int, payload["sample_count"])
    processing_started = cast(int, payload["processing_started_sample_count"])
    missing_started = cast(int, payload["missing_started_at_count"])
    missing_processing = cast(int, payload["missing_processing_started_count"])
    timing_samples = cast(int, payload["timing_sample_count"])
    submission_samples = sample_count - missing_started
    if (
        sample_count > required_count
        or missing_started > sample_count
        or missing_processing > sample_count
        or processing_started != sample_count - missing_processing
        or timing_samples > min(submission_samples, processing_started)
        or timing_samples < max(0, submission_samples + processing_started - sample_count)
        or not isinstance(payload["complete"], bool)
        or any(
            not _strict_float(payload[name])
            for name in (
                "first_claim_lag_seconds",
                "submission_span_seconds",
                "processing_start_span_seconds",
            )
        )
        or not _timing_distribution_valid(payload["wait_seconds"], expected_samples=timing_samples)
        or not _timing_distribution_valid(
            payload["adjacent_claim_gap_seconds"],
            expected_samples=max(0, processing_started - 1),
        )
    ):
        return False
    complete = (
        sample_count == required_count
        and missing_started == 0
        and missing_processing == 0
        and timing_samples == required_count
    )
    return payload["complete"] is complete


def _queue_timing_valid(value: object, *, expected_count: int) -> bool:
    keys = {
        "expected_sample_count",
        "sample_count",
        "processing_started_sample_count",
        "missing_started_at_count",
        "missing_processing_started_count",
        "timing_sample_count",
        "wait_seconds",
        "first_claim_lag_seconds",
        "submission_span_seconds",
        "processing_start_span_seconds",
        "adjacent_claim_gap_seconds",
        "complete",
        "cohort_size",
        "expected_cohort_count",
        "cohort_count",
        "cohorts",
    }
    payload = _exact_mapping(value, keys)
    if (
        not payload
        or not _strict_int(expected_count, minimum=1)
        or expected_count % DEFAULT_WORKER_BATCH_SIZE != 0
    ):
        return False
    expected_cohorts = expected_count // DEFAULT_WORKER_BATCH_SIZE
    integer_expectations = {
        "expected_sample_count": expected_count,
        "cohort_size": DEFAULT_WORKER_BATCH_SIZE,
        "expected_cohort_count": expected_cohorts,
    }
    if any(
        not _strict_int(payload[name]) or payload[name] != expected
        for name, expected in integer_expectations.items()
    ):
        return False
    section_keys = keys - {
        "expected_sample_count",
        "cohort_size",
        "expected_cohort_count",
        "cohort_count",
        "cohorts",
    }
    if not _queue_timing_section_valid(
        {name: payload[name] for name in section_keys}, required_count=expected_count
    ):
        return False
    cohorts = payload["cohorts"]
    sample_count = cast(int, payload["sample_count"])
    expected_observed_cohorts = (
        sample_count + DEFAULT_WORKER_BATCH_SIZE - 1
    ) // DEFAULT_WORKER_BATCH_SIZE
    if (
        not _strict_int(payload["cohort_count"])
        or not isinstance(cohorts, list)
        or payload["cohort_count"] != len(cohorts)
        or len(cohorts) != expected_observed_cohorts
    ):
        return False
    cohort_keys = section_keys | {"cohort_index"}
    cohort_totals = dict.fromkeys(
        (
            "sample_count",
            "processing_started_sample_count",
            "missing_started_at_count",
            "missing_processing_started_count",
            "timing_sample_count",
        ),
        0,
    )
    for index, item in enumerate(cohorts, start=1):
        cohort = _exact_mapping(item, cohort_keys)
        if (
            not cohort
            or not _strict_int(cohort["cohort_index"], minimum=1)
            or cohort["cohort_index"] != index
            or not _queue_timing_section_valid(
                {name: cohort[name] for name in section_keys},
                required_count=DEFAULT_WORKER_BATCH_SIZE,
            )
        ):
            return False
        for name in cohort_totals:
            cohort_totals[name] += cast(int, cohort[name])
    if any(cohort_totals[name] != payload[name] for name in cohort_totals):
        return False
    complete = (
        sample_count == expected_count
        and payload["missing_started_at_count"] == 0
        and payload["missing_processing_started_count"] == 0
        and payload["timing_sample_count"] == expected_count
        and len(cohorts) == expected_cohorts
        and all(cast(bool, cast(dict[str, object], cohort)["complete"]) for cohort in cohorts)
    )
    return payload["complete"] is complete


def _phase_stats_valid(value: object, *, expected_samples: int) -> bool:
    payload = _exact_mapping(
        value,
        {
            "actual_phase_wall_seconds",
            "achieved_requests_per_second",
            "achieved_rate_ratio",
            "scheduler_drift_p95_ms",
            "scheduler_drift_max_ms",
            "semaphore_wait_p95_ms",
            "semaphore_wait_max_ms",
            "max_in_flight",
            "sample_count",
        },
    )
    return bool(
        payload
        and _strict_int(payload["sample_count"], minimum=1)
        and payload["sample_count"] == expected_samples
        and _strict_int(payload["max_in_flight"], minimum=1)
        and all(
            _strict_float(payload[name])
            for name in (
                "actual_phase_wall_seconds",
                "achieved_requests_per_second",
                "achieved_rate_ratio",
                "scheduler_drift_p95_ms",
                "scheduler_drift_max_ms",
                "semaphore_wait_p95_ms",
                "semaphore_wait_max_ms",
            )
        )
    )


def _process_service_evidence_valid(
    value: object,
    *,
    expected_sample_count: int,
    minimum_process_count: int,
) -> bool:
    payload = _exact_mapping(
        value,
        {
            "sample_count",
            "minimum_process_count",
            "process_counts",
            "process_count_stable",
            "minimum_process_count_met",
            "identity_sha256_values",
            "identity_sha256_unique",
            "passed",
        },
    )
    if not payload:
        return False
    process_counts = payload["process_counts"]
    identities = payload["identity_sha256_values"]
    if (
        not _strict_int(payload["sample_count"], minimum=1)
        or payload["sample_count"] != expected_sample_count
        or payload["minimum_process_count"] != minimum_process_count
        or not isinstance(process_counts, list)
        or not process_counts
        or any(not _strict_int(count, minimum=1) for count in process_counts)
        or not isinstance(identities, list)
        or not identities
        or any(
            not isinstance(identity, str) or not HASH_PATTERN.fullmatch(identity)
            for identity in identities
        )
    ):
        return False
    count_stable = len(process_counts) == 1
    minimum_met = all(count >= minimum_process_count for count in process_counts)
    identity_unique = len(identities) == 1
    passed = count_stable and minimum_met and identity_unique
    return (
        payload["process_count_stable"] is count_stable
        and payload["minimum_process_count_met"] is minimum_met
        and payload["identity_sha256_unique"] is identity_unique
        and payload["passed"] is passed
    )


def _process_cohort_valid(value: object) -> bool:
    payload = _exact_mapping(
        value,
        {"scope", "evaluated", "sample_count", "api", "worker", "all_valid"},
    )
    if (
        not payload
        or payload["scope"] != "measured_and_idle_samples"
        or payload["evaluated"] is not True
        or not _strict_int(payload["sample_count"], minimum=1)
    ):
        return False
    sample_count = cast(int, payload["sample_count"])
    api_valid = _process_service_evidence_valid(
        payload["api"], expected_sample_count=sample_count, minimum_process_count=3
    )
    worker_valid = _process_service_evidence_valid(
        payload["worker"],
        expected_sample_count=sample_count,
        minimum_process_count=FORMAL_WORKER_REPLICAS,
    )
    if not api_valid or not worker_valid:
        return False
    api = cast(dict[str, object], payload["api"])
    worker = cast(dict[str, object], payload["worker"])
    return payload["all_valid"] is bool(api["passed"] is True and worker["passed"] is True)


def _resource_trend_valid(
    value: object,
    *,
    formal: bool,
    expected_measured_sample_count: int,
    expected_minimum_sample_count: int,
    expected_idle_sample_count: int,
    expected_idle_span_seconds: float,
    expected_idle_samples_complete: bool,
) -> bool:
    payload = _exact_mapping(
        value,
        {
            "sample_count",
            "evaluated",
            "method",
            "block_sample_counts",
            "block_median_levels",
            "new_high_event_blocks",
            "new_high_event_count",
            "first_to_last_delta",
            "global_candidate_growth",
            "global_sustained_growth",
            "terminal_window",
            "idle_recovery",
            "least_squares_slope_per_minute",
            "candidate_growth",
            "confirmed_sustained_growth",
            "sustained_growth",
        },
    )
    terminal = _exact_mapping(
        payload["terminal_window"] if payload else None,
        {
            "evaluated",
            "block_sample_counts",
            "block_median_levels",
            "new_high_event_blocks",
            "new_high_event_count",
            "first_to_last_delta",
            "candidate_growth",
            "sustained_growth",
        },
    )
    idle = _exact_mapping(
        payload["idle_recovery"] if payload else None,
        {
            "required",
            "evaluated",
            "sample_count",
            "sample_span_seconds",
            "minimum_sample_count",
            "minimum_span_seconds",
            "samples_complete",
            "block_sample_counts",
            "block_median_levels",
            "reference_level",
            "retained_growth_threshold",
            "last_two_block_levels",
            "continued_growth_candidate",
            "status",
        },
    )
    if not payload or not terminal or not idle:
        return False

    boolean_fields = (
        "evaluated",
        "global_candidate_growth",
        "global_sustained_growth",
        "candidate_growth",
        "confirmed_sustained_growth",
        "sustained_growth",
    )
    terminal_boolean_fields = ("evaluated", "candidate_growth", "sustained_growth")
    idle_boolean_fields = (
        "required",
        "evaluated",
        "samples_complete",
        "continued_growth_candidate",
    )
    if (
        not _strict_int(payload["sample_count"], minimum=1)
        or payload["sample_count"] != expected_measured_sample_count
        or payload["method"]
        != "six_block_median_low_with_terminal_subwindows_and_post_load_idle_confirmation"
        or not _strict_int(payload["new_high_event_count"])
        or not _finite_float(payload["first_to_last_delta"])
        or not _finite_float(payload["least_squares_slope_per_minute"])
        or any(not isinstance(payload[name], bool) for name in boolean_fields)
        or not _strict_int(terminal["new_high_event_count"])
        or not _finite_float(terminal["first_to_last_delta"])
        or any(not isinstance(terminal[name], bool) for name in terminal_boolean_fields)
        or idle["required"] is not formal
        or any(not isinstance(idle[name], bool) for name in idle_boolean_fields)
        or not _strict_int(idle["sample_count"])
        or idle["sample_count"] != expected_idle_sample_count
        or not _strict_float(idle["sample_span_seconds"])
        or idle["sample_span_seconds"] != expected_idle_span_seconds
        or not _strict_int(idle["minimum_sample_count"])
        or idle["minimum_sample_count"] != FORMAL_RESOURCE_IDLE_MIN_SAMPLES
        or not _strict_float(idle["minimum_span_seconds"])
        or idle["minimum_span_seconds"] != FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS
        or idle["samples_complete"] is not expected_idle_samples_complete
        or not isinstance(idle["status"], str)
    ):
        return False

    def integer_list(item: object, *, minimum: int = 0) -> list[int] | None:
        if not isinstance(item, list) or any(
            not _strict_int(element, minimum=minimum) for element in item
        ):
            return None
        return cast(list[int], item)

    def float_list(item: object) -> list[float] | None:
        if not isinstance(item, list) or any(not _strict_float(element) for element in item):
            return None
        return cast(list[float], item)

    block_counts = integer_list(payload["block_sample_counts"], minimum=1)
    block_levels = float_list(payload["block_median_levels"])
    event_blocks = integer_list(payload["new_high_event_blocks"], minimum=1)
    terminal_counts = integer_list(terminal["block_sample_counts"], minimum=1)
    terminal_levels = float_list(terminal["block_median_levels"])
    terminal_events = integer_list(terminal["new_high_event_blocks"], minimum=1)
    idle_counts = integer_list(idle["block_sample_counts"], minimum=1)
    idle_levels = float_list(idle["block_median_levels"])
    idle_last_two = float_list(idle["last_two_block_levels"])
    if any(
        item is None
        for item in (
            block_counts,
            block_levels,
            event_blocks,
            terminal_counts,
            terminal_levels,
            terminal_events,
            idle_counts,
            idle_levels,
            idle_last_two,
        )
    ):
        return False

    evaluated = formal and expected_measured_sample_count >= expected_minimum_sample_count
    if payload["evaluated"] is not evaluated:
        return False
    if not evaluated:
        return bool(
            block_counts == []
            and block_levels == []
            and event_blocks == []
            and payload["new_high_event_count"] == 0
            and payload["first_to_last_delta"] == 0.0
            and payload["global_candidate_growth"] is False
            and payload["global_sustained_growth"] is False
            and terminal["evaluated"] is False
            and terminal_counts == []
            and terminal_levels == []
            and terminal_events == []
            and terminal["new_high_event_count"] == 0
            and terminal["first_to_last_delta"] == 0.0
            and terminal["candidate_growth"] is False
            and terminal["sustained_growth"] is False
            and idle["evaluated"] is False
            and idle_counts == []
            and idle_levels == []
            and idle["reference_level"] is None
            and idle["retained_growth_threshold"] is None
            and idle_last_two == []
            and idle["continued_growth_candidate"] is False
            and idle["status"] == "not_evaluated"
            and payload["least_squares_slope_per_minute"] == 0.0
            and payload["candidate_growth"] is False
            and payload["confirmed_sustained_growth"] is False
            and payload["sustained_growth"] is False
        )

    def repeated_new_high(levels: list[float]) -> tuple[list[int], float, bool]:
        running_high = levels[0]
        events: list[int] = []
        for index, level in enumerate(levels[1:], start=1):
            if level >= running_high + 1.0:
                events.append(index)
                running_high = level
        delta = levels[-1] - levels[0]
        return events, delta, len(events) >= 2 and delta >= 2.0

    expected_block_counts = [
        (index + 1) * expected_measured_sample_count // 6
        - index * expected_measured_sample_count // 6
        for index in range(6)
    ]
    if block_counts != expected_block_counts or len(cast(list[float], block_levels)) != 6:
        return False
    expected_events, expected_delta, expected_global_candidate = repeated_new_high(
        cast(list[float], block_levels)
    )
    if (
        event_blocks != expected_events
        or payload["new_high_event_count"] != len(expected_events)
        or payload["first_to_last_delta"] != round(expected_delta, 3)
        or payload["global_candidate_growth"] is not expected_global_candidate
    ):
        return False

    terminal_count = expected_block_counts[-1]
    expected_terminal_counts = [
        (index + 1) * terminal_count // 4 - index * terminal_count // 4 for index in range(4)
    ]
    if (
        terminal["evaluated"] is not True
        or terminal_counts != expected_terminal_counts
        or len(cast(list[float], terminal_levels)) != 4
    ):
        return False
    expected_terminal_events, expected_terminal_delta, expected_terminal_candidate = (
        repeated_new_high(cast(list[float], terminal_levels))
    )
    if (
        terminal_events != expected_terminal_events
        or terminal["new_high_event_count"] != len(expected_terminal_events)
        or terminal["first_to_last_delta"] != round(expected_terminal_delta, 3)
        or terminal["candidate_growth"] is not expected_terminal_candidate
    ):
        return False

    reference_level = cast(list[float], block_levels)[0]
    retained_threshold = reference_level + 2.0
    if expected_idle_samples_complete:
        expected_idle_counts = [
            (index + 1) * expected_idle_sample_count // 4 - index * expected_idle_sample_count // 4
            for index in range(4)
        ]
        if (
            idle["evaluated"] is not True
            or idle_counts != expected_idle_counts
            or len(cast(list[float], idle_levels)) != 4
            or idle["reference_level"] != reference_level
            or idle["retained_growth_threshold"] != retained_threshold
            or idle_last_two != cast(list[float], idle_levels)[-2:]
        ):
            return False
        _idle_events, _idle_delta, idle_continued = repeated_new_high(
            cast(list[float], idle_levels)
        )
        if idle_continued:
            idle_status = "continued_growth"
        elif all(level < retained_threshold for level in cast(list[float], idle_last_two)):
            idle_status = "recovered"
        elif all(level >= retained_threshold for level in cast(list[float], idle_last_two)):
            idle_status = "retained"
        else:
            idle_status = "inconclusive"
    else:
        idle_continued = False
        idle_status = "insufficient_samples"
        if (
            idle["evaluated"] is not False
            or idle_counts != []
            or idle_levels != []
            or idle["reference_level"] != reference_level
            or idle["retained_growth_threshold"] != retained_threshold
            or idle_last_two != []
        ):
            return False
    confirmation_failed = idle_status != "recovered"
    active_candidate = expected_global_candidate or expected_terminal_candidate
    expected_sustained = idle_continued or (active_candidate and confirmation_failed)
    return bool(
        idle["continued_growth_candidate"] is idle_continued
        and idle["status"] == idle_status
        and payload["global_sustained_growth"]
        is (expected_global_candidate and confirmation_failed)
        and terminal["sustained_growth"] is (expected_terminal_candidate and confirmation_failed)
        and payload["candidate_growth"] is active_candidate
        and payload["confirmed_sustained_growth"] is expected_sustained
        and payload["sustained_growth"] is expected_sustained
    )


def _rss_growth_valid(
    value: object,
    *,
    formal: bool,
    expected_measured_sample_count: int,
    expected_idle_sample_count: int,
) -> bool:
    payload = _exact_mapping(
        value,
        {
            "evaluated",
            "method",
            "threshold_percent",
            "observed_measured_sample_count",
            "baseline_window",
            "terminal_window",
            "windows_non_overlapping",
            "growth_percent",
            "growth_percent_rounded",
            "active_within_budget",
            "idle_confirmation",
            "within_budget",
        },
    )
    if not payload or payload["method"] != "steady_endpoint_window_median_v1":
        return False
    if (
        not _strict_float(payload["threshold_percent"])
        or payload["threshold_percent"] != THRESHOLDS["rss_growth_percent_max"]
        or not _strict_int(payload["observed_measured_sample_count"])
        or payload["observed_measured_sample_count"] != expected_measured_sample_count
        or not all(
            isinstance(payload[name], bool) for name in ("evaluated", "windows_non_overlapping")
        )
    ):
        return False
    if not formal and (
        payload["evaluated"] is not False
        or payload["windows_non_overlapping"] is not False
        or payload["active_within_budget"] is not None
        or payload["within_budget"] is not None
    ):
        return False
    window_keys = {
        "sample_count",
        "sample_span_seconds",
        "minimum_sample_count",
        "minimum_span_seconds",
        "median_rss_bytes",
        "complete",
    }
    windows: dict[str, dict[str, object]] = {}
    for name in ("baseline_window", "terminal_window"):
        window = _exact_mapping(payload[name], window_keys)
        if (
            not window
            or not _strict_int(window["sample_count"])
            or window["sample_count"] > expected_measured_sample_count
            or not _strict_int(window["minimum_sample_count"])
            or window["minimum_sample_count"] != FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES
            or not _strict_float(window["minimum_span_seconds"])
            or window["minimum_span_seconds"] != FORMAL_RSS_ENDPOINT_WINDOW_MIN_SPAN_SECONDS
            or not isinstance(window["complete"], bool)
        ):
            return False
        for optional_float in ("sample_span_seconds", "median_rss_bytes"):
            if window[optional_float] is not None and not _strict_float(window[optional_float]):
                return False
        if formal:
            if not _strict_float(window["sample_span_seconds"]):
                return False
            complete = (
                window["sample_count"] == FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES
                and cast(float, window["sample_span_seconds"])
                >= FORMAL_RSS_ENDPOINT_WINDOW_MIN_SPAN_SECONDS
                and _strict_float(window["median_rss_bytes"])
                and cast(float, window["median_rss_bytes"]) > 0.0
            )
            if (
                window["sample_count"]
                != min(expected_measured_sample_count, FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES)
                or window["complete"] is not complete
            ):
                return False
        elif (
            window["sample_count"] != 0
            or window["sample_span_seconds"] is not None
            or window["median_rss_bytes"] is not None
            or window["complete"] is not False
        ):
            return False
        windows[name] = window
    idle = _exact_mapping(
        payload["idle_confirmation"],
        {
            "required",
            "evaluated",
            "method",
            "sample_count",
            "sample_span_seconds",
            "minimum_sample_count",
            "minimum_span_seconds",
            "block_sample_counts",
            "block_median_rss_bytes",
            "baseline_median_rss_bytes",
            "budget_ceiling_rss_bytes",
            "last_two_block_median_rss_bytes",
            "status",
            "within_budget",
        },
    )
    if (
        not idle
        or idle["required"] is not formal
        or not isinstance(idle["evaluated"], bool)
        or idle["method"] != "four_block_budget_confirmation_v1"
        or not _strict_int(idle["sample_count"])
        or idle["sample_count"] != expected_idle_sample_count
        or not _strict_float(idle["sample_span_seconds"])
        or not _strict_int(idle["minimum_sample_count"])
        or idle["minimum_sample_count"] != FORMAL_RESOURCE_IDLE_MIN_SAMPLES
        or not _strict_float(idle["minimum_span_seconds"])
        or idle["minimum_span_seconds"] != FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS
        or not isinstance(idle["status"], str)
    ):
        return False
    if not formal and (
        idle["evaluated"] is not False
        or idle["status"] != "not_evaluated"
        or idle["within_budget"] is not None
    ):
        return False
    block_counts = idle["block_sample_counts"]
    block_levels = idle["block_median_rss_bytes"]
    last_two_levels = idle["last_two_block_median_rss_bytes"]
    if (
        not isinstance(block_counts, list)
        or any(not _strict_int(count, minimum=1) for count in block_counts)
        or not isinstance(block_levels, list)
        or any(not _strict_float(level) for level in block_levels)
        or not isinstance(last_two_levels, list)
        or any(not _strict_float(level) for level in last_two_levels)
    ):
        return False
    for optional_float in (
        "baseline_median_rss_bytes",
        "budget_ceiling_rss_bytes",
    ):
        if idle[optional_float] is not None and not _strict_float(idle[optional_float]):
            return False
    for optional_float in (
        "growth_percent",
        "growth_percent_rounded",
    ):
        if payload[optional_float] is not None and not _finite_float(payload[optional_float]):
            return False
    if not formal:
        if (
            block_counts
            or block_levels
            or last_two_levels
            or idle["baseline_median_rss_bytes"] is not None
            or idle["budget_ceiling_rss_bytes"] is not None
        ):
            return False
        return True

    if not isinstance(payload["active_within_budget"], bool) or not isinstance(
        payload["within_budget"], bool
    ):
        return False
    baseline = windows["baseline_window"]
    terminal = windows["terminal_window"]
    endpoint_evaluated = bool(
        baseline["complete"] and terminal["complete"] and payload["windows_non_overlapping"]
    )
    if payload["evaluated"] is not endpoint_evaluated or (
        expected_measured_sample_count < FORMAL_RSS_ENDPOINT_WINDOW_SAMPLES * 2
        and payload["windows_non_overlapping"] is not False
    ):
        return False
    if endpoint_evaluated:
        baseline_median = cast(float, baseline["median_rss_bytes"])
        terminal_median = cast(float, terminal["median_rss_bytes"])
        growth_percent = (terminal_median - baseline_median) / baseline_median * 100.0
        if (
            not _finite_float(payload["growth_percent"])
            or not math.isclose(
                cast(float, payload["growth_percent"]),
                growth_percent,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            or payload["growth_percent_rounded"] != round(growth_percent, 3)
            or payload["active_within_budget"]
            is not (
                terminal_median * 100.0
                <= baseline_median * (100.0 + cast(float, payload["threshold_percent"]))
            )
        ):
            return False
    elif (
        payload["growth_percent"] is not None
        or payload["growth_percent_rounded"] is not None
        or payload["active_within_budget"] is not False
    ):
        return False

    baseline_median = baseline["median_rss_bytes"]
    if idle["baseline_median_rss_bytes"] != baseline_median:
        return False
    idle_evaluated = bool(block_levels)
    if (
        idle["evaluated"] is not idle_evaluated
        or bool(block_counts) is not idle_evaluated
        or (idle_evaluated and len(block_counts) != FORMAL_RSS_IDLE_BLOCK_COUNT)
        or (idle_evaluated and len(block_levels) != FORMAL_RSS_IDLE_BLOCK_COUNT)
        or (idle_evaluated and sum(cast(list[int], block_counts)) != idle["sample_count"])
        or (
            idle_evaluated
            and (
                cast(int, idle["sample_count"]) < FORMAL_RESOURCE_IDLE_MIN_SAMPLES
                or cast(float, idle["sample_span_seconds"]) < FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS
                or not _strict_float(baseline_median)
                or cast(float, baseline_median) <= 0.0
            )
        )
    ):
        return False
    expected_budget_ceiling = (
        cast(float, baseline_median) * (1.0 + cast(float, payload["threshold_percent"]) / 100.0)
        if idle_evaluated
        else None
    )
    if idle["budget_ceiling_rss_bytes"] != expected_budget_ceiling:
        return False
    expected_last_two = cast(list[float], block_levels)[-2:] if idle_evaluated else []
    if last_two_levels != expected_last_two:
        return False
    if expected_budget_ceiling is None or len(expected_last_two) != 2:
        idle_status = "insufficient_samples"
    elif all(
        level * 100.0
        <= cast(float, baseline_median) * (100.0 + cast(float, payload["threshold_percent"]))
        for level in expected_last_two
    ):
        idle_status = "within_budget"
    elif all(
        level * 100.0
        > cast(float, baseline_median) * (100.0 + cast(float, payload["threshold_percent"]))
        for level in expected_last_two
    ):
        idle_status = "retained_over_budget"
    else:
        idle_status = "inconclusive"
    idle_within_budget = idle_status == "within_budget"
    if idle["status"] != idle_status or idle["within_budget"] is not idle_within_budget:
        return False
    within_budget = bool(
        endpoint_evaluated and payload["active_within_budget"] and idle_within_budget
    )
    if payload["within_budget"] is not within_budget:
        return False
    return True


def _provider_usage_integrity_passed(integrity: dict[str, object]) -> bool:
    return bool(
        all(
            integrity[name] is True
            for name in (
                "provider_invocation_set_exact",
                "provider_usage_key_set_exact",
                "run_usage_key_set_exact",
                "provider_meter_set_exact",
            )
        )
        and integrity["provider_meter_mismatches"] == 0
        and integrity["usage_event_contract_violations"] == 0
        and integrity["duplicates_or_missing"] == 0
        and integrity["provider_invocations"] == integrity["provider_call_records"]
    )


def _record_identity_valid(value: object, *, formal: bool) -> bool:
    payload = _exact_mapping(
        value,
        {
            "revision",
            "proof_image",
            "context_sha256",
            "harness_sha256",
            "compose_sha256",
            "wrapper_sha256",
            "git_status_sha256",
            "git_dirty",
            "git_dirty_count",
            "postgres_image",
            "redis_image",
            "migration_manifest_sha256",
            "migration_head_sha256",
            "migration_head_source_sha256",
            "environment_fingerprint",
            "dataset_fingerprint",
            "dataset_config",
            "dataset_sha256",
            "docker",
        },
    )
    if (
        not payload
        or not isinstance(payload["revision"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", payload["revision"])
    ):
        return False
    for name in (
        "context_sha256",
        "harness_sha256",
        "compose_sha256",
        "wrapper_sha256",
        "git_status_sha256",
        "migration_manifest_sha256",
        "migration_head_sha256",
        "migration_head_source_sha256",
        "environment_fingerprint",
        "dataset_sha256",
    ):
        if not isinstance(payload[name], str) or not HASH_PATTERN.fullmatch(payload[name]):
            return False
    if any(
        not isinstance(payload[name], str)
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", payload[name])
        for name in ("proof_image", "postgres_image", "redis_image")
    ):
        return False
    if (
        not isinstance(payload["git_dirty"], bool)
        or not _strict_int(payload["git_dirty_count"])
        or payload["git_dirty"] is not (payload["git_dirty_count"] > 0)
        or (formal and payload["git_dirty"] is not False)
        or payload["dataset_fingerprint"] != EXPECTED_DATASET_ID
    ):
        return False
    try:
        dataset_canonical = json.dumps(
            payload["dataset_config"], sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        expected_canonical = json.dumps(
            EXPECTED_DATASET_CONFIG, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError):
        return False
    if (
        dataset_canonical != expected_canonical
        or hashlib.sha256(dataset_canonical.encode()).hexdigest() != payload["dataset_sha256"]
    ):
        return False
    docker = _exact_mapping(
        payload["docker"],
        {
            "arch",
            "cpu_count",
            "memory_bytes",
            "server_version",
            "compose_version",
            "background_container_count",
        },
    )
    if not docker or any(not isinstance(item, str) or not item for item in docker.values()):
        return False
    return bool(
        re.fullmatch(r"[1-9][0-9]*", cast(str, docker["cpu_count"]))
        and re.fullmatch(r"[1-9][0-9]*", cast(str, docker["memory_bytes"]))
        and re.fullmatch(r"[0-9]+", cast(str, docker["background_container_count"]))
    )


def _record_schema_valid(record: dict[str, object], *, expected_mode: str) -> bool:
    top_level = _exact_mapping(
        record,
        {
            "contract",
            "generated_at",
            "verdict",
            "mode",
            "baseline_index",
            "baseline_environment_receipt_sha256",
            "record_thresholds_passed",
            "formal_record_shape",
            "formal_acceptance",
            "production_slo_claim",
            "identity",
            "configuration",
            "scheduler",
            "requests",
            "observation_diagnostics",
            "queue",
            "latency",
            "integrity",
            "isolation",
            "resources",
            "checks",
            "boundary",
            "redaction",
            "limitations",
        },
    )
    if not top_level or expected_mode not in {"quick", "formal"}:
        return False
    formal = expected_mode == "formal"
    try:
        generated_at = datetime.fromisoformat(cast(str, top_level["generated_at"]))
    except (TypeError, ValueError):
        return False
    if (
        generated_at.tzinfo is None
        or top_level["contract"] != CONTRACT_ID
        or top_level["mode"] != expected_mode
        or not _strict_int(top_level["baseline_index"], minimum=1)
        or not isinstance(top_level["baseline_environment_receipt_sha256"], str)
        or not HASH_PATTERN.fullmatch(top_level["baseline_environment_receipt_sha256"])
        or top_level["formal_record_shape"] is not formal
        or top_level["formal_acceptance"] is not False
        or top_level["production_slo_claim"] is not False
        or not isinstance(top_level["record_thresholds_passed"], bool)
        or not _record_identity_valid(top_level["identity"], formal=formal)
    ):
        return False
    shape = _expected_record_shape(expected_mode)
    expected_configuration = _record_configuration(
        shape, provider_delay_ms=FORMAL_PROVIDER_DELAY_MS
    )
    try:
        configuration = json.dumps(
            top_level["configuration"], sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        expected_configuration_json = json.dumps(
            expected_configuration, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError):
        return False
    if configuration != expected_configuration_json:
        return False

    warmup_samples = max(1, round(shape.warmup_seconds * shape.request_rate))
    soak_samples = max(1, round(shape.duration_seconds * shape.request_rate))
    expected_attempted = 1 + shape.concurrency + shape.queue_burst + warmup_samples + soak_samples
    scheduler = _exact_mapping(
        top_level["scheduler"],
        {"warmup", "measured", "concurrency_probe_client_max", "concurrency_probe_provider_max"},
    )
    if (
        not scheduler
        or not _phase_stats_valid(scheduler["warmup"], expected_samples=warmup_samples)
        or not _phase_stats_valid(scheduler["measured"], expected_samples=soak_samples)
        or not _strict_int(scheduler["concurrency_probe_client_max"], minimum=1)
        or not _strict_int(scheduler["concurrency_probe_provider_max"])
    ):
        return False
    measured = cast(dict[str, object], scheduler["measured"])

    requests = _exact_mapping(
        top_level["requests"],
        {"attempted", "accepted", "completed", "accepted_rate", "completed_rate", "unexpected_5xx"},
    )
    if not requests or any(
        not _strict_int(requests[name])
        for name in ("attempted", "accepted", "completed", "unexpected_5xx")
    ):
        return False
    attempted = cast(int, requests["attempted"])
    accepted = cast(int, requests["accepted"])
    completed = cast(int, requests["completed"])
    expected_completed_rate = round(completed / accepted, 6) if accepted else 0.0
    if (
        attempted != expected_attempted
        or accepted > attempted
        or completed > accepted
        or not _strict_float(requests["accepted_rate"])
        or not _strict_float(requests["completed_rate"])
        or requests["accepted_rate"] != round(accepted / attempted, 6)
        or requests["completed_rate"] != expected_completed_rate
    ):
        return False

    diagnostics = top_level["observation_diagnostics"]
    if (
        not _diagnostics_valid(diagnostics)
        or cast(dict[str, object], diagnostics)["sample_count"] != attempted + 1
    ):
        return False
    diagnostics_payload = cast(dict[str, object], diagnostics)
    diagnostics_http = cast(dict[str, int], diagnostics_payload["by_http_status"])
    diagnostics_runtime = cast(dict[str, int], diagnostics_payload["by_runtime_status"])
    if diagnostics_http["5xx"] > requests["unexpected_5xx"] or accepted != sum(
        diagnostics_runtime[name] for name in ("queued", "running", "succeeded")
    ):
        return False

    queue = _exact_mapping(
        top_level["queue"],
        {
            "requested",
            "accepted",
            "completed",
            "wait_p95_seconds",
            "timing_evidence",
            "result_read_succeeded",
        },
    )
    queue_timing = queue["timing_evidence"] if queue else None
    if (
        not queue
        or any(not _strict_int(queue[name]) for name in ("requested", "accepted", "completed"))
        or queue["requested"] != shape.queue_burst
        or not cast(int, queue["completed"])
        <= cast(int, queue["accepted"])
        <= cast(int, queue["requested"])
        or not _strict_float(queue["wait_p95_seconds"])
        or not isinstance(queue["result_read_succeeded"], bool)
        or not _queue_timing_valid(queue_timing, expected_count=shape.queue_burst)
        or queue["wait_p95_seconds"]
        != cast(dict[str, object], cast(dict[str, object], queue_timing)["wait_seconds"])["p95"]
    ):
        return False

    latency = _exact_mapping(
        top_level["latency"],
        {
            "attempted_sample_count",
            "accepted_sample_count",
            "sample_count",
            "missing_persistent_evidence_count",
            "provider_excluded_p95_ms",
            "provider_excluded_p99_ms",
            "proof_provider_wall_p95_ms",
            "database_provider_call_p95_ms",
            "exclusion_method",
            "all_accepted_samples_have_persistent_provider_evidence",
        },
    )
    latency_complete = (
        latency["all_accepted_samples_have_persistent_provider_evidence"] if latency else None
    )
    if (
        not latency
        or any(
            not _strict_int(latency[name])
            for name in (
                "attempted_sample_count",
                "accepted_sample_count",
                "sample_count",
                "missing_persistent_evidence_count",
            )
        )
        or latency["attempted_sample_count"] != soak_samples
        or not cast(int, latency["sample_count"])
        <= cast(int, latency["accepted_sample_count"])
        <= cast(int, latency["attempted_sample_count"])
        or latency["missing_persistent_evidence_count"]
        != cast(int, latency["accepted_sample_count"]) - cast(int, latency["sample_count"])
        or not all(
            _strict_float(latency[name])
            for name in (
                "provider_excluded_p95_ms",
                "provider_excluded_p99_ms",
                "proof_provider_wall_p95_ms",
                "database_provider_call_p95_ms",
            )
        )
        or latency["exclusion_method"]
        != "client_elapsed_minus_max_persistent_provider_wall_and_database_provider_call"
        or not isinstance(latency_complete, bool)
        or latency_complete is not (cast(int, latency["missing_persistent_evidence_count"]) == 0)
    ):
        return False

    integrity_keys = {
        "observed_records",
        "database_records",
        "observed_identifier_set_exact",
        "succeeded_records",
        "provider_call_records",
        "provider_invocations",
        "provider_invocation_set_exact",
        "provider_usage_key_set_exact",
        "run_usage_key_set_exact",
        "provider_meter_set_exact",
        "provider_meter_mismatches",
        "usage_event_contract_violations",
        "duplicates_or_missing",
        "queued_residue",
        "running_residue",
        "dispatching_residue",
        "redis_queue_residue",
        "provider_active_residue",
        "provider_max_concurrency",
        "provider_barrier_timeouts",
        "artifact_records",
        "queue_timing_evidence",
        "queue_wait_p95_seconds",
    }
    integrity = _exact_mapping(top_level["integrity"], integrity_keys)
    if not integrity:
        return False
    integrity_bool_fields = (
        "observed_identifier_set_exact",
        "provider_invocation_set_exact",
        "provider_usage_key_set_exact",
        "run_usage_key_set_exact",
        "provider_meter_set_exact",
    )
    integrity_int_fields = tuple(
        integrity_keys
        - set(integrity_bool_fields)
        - {"queue_timing_evidence", "queue_wait_p95_seconds"}
    )
    if (
        any(not isinstance(integrity[name], bool) for name in integrity_bool_fields)
        or any(not _strict_int(integrity[name]) for name in integrity_int_fields)
        or not _strict_float(integrity["queue_wait_p95_seconds"])
        or integrity["queue_timing_evidence"] != queue["timing_evidence"]
        or integrity["queue_wait_p95_seconds"] != queue["wait_p95_seconds"]
        or integrity["succeeded_records"] != completed
        or integrity["provider_max_concurrency"] != scheduler["concurrency_probe_provider_max"]
        or not cast(int, integrity["succeeded_records"])
        <= cast(int, integrity["provider_call_records"])
        <= cast(int, integrity["database_records"])
        or (
            integrity["observed_identifier_set_exact"] is True
            and integrity["observed_records"] != integrity["database_records"]
        )
    ):
        return False

    isolation = _exact_mapping(
        top_level["isolation"],
        {
            "payload_mismatch_zero_side_effect",
            "cross_site_record_read_rejected",
            "cross_site_result_read_rejected",
            "own_site_result_read_succeeded",
        },
    )
    if not isolation or any(not isinstance(value, bool) for value in isolation.values()):
        return False

    resource_keys = {
        "sample_count",
        "measured_sample_count",
        "minimum_sample_count",
        "measured_sample_count_passed",
        "idle_recovery_required",
        "idle_recovery_sample_count",
        "idle_recovery_minimum_sample_count",
        "idle_recovery_sample_span_seconds",
        "idle_recovery_minimum_span_seconds",
        "idle_recovery_samples_complete",
        "sample_count_passed",
        "warmup_boundary_elapsed_seconds",
        "load_end_boundary_elapsed_seconds",
        "idle_end_boundary_elapsed_seconds",
        "api_peak_rss_bytes",
        "worker_peak_rss_bytes",
        "api_rss_growth",
        "worker_rss_growth",
        "process_cohort_evidence",
        "api_fd_sustained_growth",
        "worker_fd_sustained_growth",
        "postgres_connection_sustained_growth",
        "api_fd_trend",
        "worker_fd_trend",
        "postgres_connection_trend",
        "services_survived_all_samples",
        "restart_count_zero",
    }
    resources = _exact_mapping(top_level["resources"], resource_keys)
    if not resources:
        return False
    resource_int_fields = (
        "sample_count",
        "measured_sample_count",
        "minimum_sample_count",
        "idle_recovery_sample_count",
        "idle_recovery_minimum_sample_count",
        "api_peak_rss_bytes",
        "worker_peak_rss_bytes",
    )
    resource_bool_fields = (
        "measured_sample_count_passed",
        "idle_recovery_required",
        "idle_recovery_samples_complete",
        "sample_count_passed",
        "api_fd_sustained_growth",
        "worker_fd_sustained_growth",
        "postgres_connection_sustained_growth",
        "services_survived_all_samples",
        "restart_count_zero",
    )
    expected_minimum_sample_count = (
        max(1, math.floor(shape.duration_seconds / 5 * 0.9)) if formal else 1
    )
    if (
        any(not _strict_int(resources[name]) for name in resource_int_fields)
        or any(not isinstance(resources[name], bool) for name in resource_bool_fields)
        or any(
            not _strict_float(resources[name])
            for name in (
                "idle_recovery_sample_span_seconds",
                "idle_recovery_minimum_span_seconds",
                "warmup_boundary_elapsed_seconds",
                "load_end_boundary_elapsed_seconds",
                "idle_end_boundary_elapsed_seconds",
            )
        )
        or resources["idle_recovery_required"] is not formal
        or not _rss_growth_valid(
            resources["api_rss_growth"],
            formal=formal,
            expected_measured_sample_count=cast(int, resources["measured_sample_count"]),
            expected_idle_sample_count=cast(int, resources["idle_recovery_sample_count"]),
        )
        or not _rss_growth_valid(
            resources["worker_rss_growth"],
            formal=formal,
            expected_measured_sample_count=cast(int, resources["measured_sample_count"]),
            expected_idle_sample_count=cast(int, resources["idle_recovery_sample_count"]),
        )
        or not _process_cohort_valid(resources["process_cohort_evidence"])
        or any(
            not _resource_trend_valid(
                resources[trend_name],
                formal=formal,
                expected_measured_sample_count=cast(int, resources["measured_sample_count"]),
                expected_minimum_sample_count=expected_minimum_sample_count,
                expected_idle_sample_count=cast(int, resources["idle_recovery_sample_count"]),
                expected_idle_span_seconds=cast(
                    float, resources["idle_recovery_sample_span_seconds"]
                ),
                expected_idle_samples_complete=cast(
                    bool, resources["idle_recovery_samples_complete"]
                ),
            )
            for trend_name in (
                "api_fd_trend",
                "worker_fd_trend",
                "postgres_connection_trend",
            )
        )
    ):
        return False
    measured_sample_count = cast(int, resources["measured_sample_count"])
    minimum_sample_count = cast(int, resources["minimum_sample_count"])
    idle_sample_count = cast(int, resources["idle_recovery_sample_count"])
    idle_minimum_sample_count = cast(int, resources["idle_recovery_minimum_sample_count"])
    idle_sample_span = cast(float, resources["idle_recovery_sample_span_seconds"])
    idle_minimum_span = cast(float, resources["idle_recovery_minimum_span_seconds"])
    measured_passed = measured_sample_count >= minimum_sample_count
    idle_complete = not formal or (
        idle_sample_count >= idle_minimum_sample_count and idle_sample_span >= idle_minimum_span
    )
    process_cohort_payload = cast(dict[str, object], resources["process_cohort_evidence"])
    if (
        minimum_sample_count != expected_minimum_sample_count
        or idle_minimum_sample_count != FORMAL_RESOURCE_IDLE_MIN_SAMPLES
        or idle_minimum_span != FORMAL_RESOURCE_IDLE_MIN_SPAN_SECONDS
        or resources["measured_sample_count_passed"] is not measured_passed
        or resources["idle_recovery_samples_complete"] is not idle_complete
        or resources["sample_count_passed"] is not (measured_passed and idle_complete)
        or cast(int, resources["sample_count"]) < measured_sample_count + idle_sample_count
        or process_cohort_payload["sample_count"] != measured_sample_count + idle_sample_count
        or not cast(float, resources["warmup_boundary_elapsed_seconds"])
        <= cast(float, resources["load_end_boundary_elapsed_seconds"])
        <= cast(float, resources["idle_end_boundary_elapsed_seconds"])
        or cast(int, resources["api_peak_rss_bytes"]) <= 0
        or cast(int, resources["worker_peak_rss_bytes"]) <= 0
    ):
        return False
    trend_pairs = (
        ("api_fd_sustained_growth", "api_fd_trend"),
        ("worker_fd_sustained_growth", "worker_fd_trend"),
        ("postgres_connection_sustained_growth", "postgres_connection_trend"),
    )
    for summary_name, trend_name in trend_pairs:
        trend = resources[trend_name]
        if (
            not isinstance(trend, dict)
            or not isinstance(trend.get("sustained_growth"), bool)
            or resources[summary_name] is not trend["sustained_growth"]
        ):
            return False

    if not _exact_typed_mapping(top_level["boundary"], RECORD_BOUNDARY) or not _exact_typed_mapping(
        top_level["redaction"], RECORD_REDACTION
    ):
        return False
    if top_level["limitations"] != list(RECORD_LIMITATIONS):
        return False

    process_cohort = cast(dict[str, object], resources["process_cohort_evidence"])
    api_growth = cast(dict[str, object], resources["api_rss_growth"])
    worker_growth = cast(dict[str, object], resources["worker_rss_growth"])
    concurrency_target = shape.concurrency if formal else 1
    recomputed_checks = {
        "unexpected_5xx_zero": requests["unexpected_5xx"] == 0,
        "transport_http_failures_zero": _transport_http_failures_zero(diagnostics),
        "accepted_rate": requests["accepted_rate"] >= THRESHOLDS["accepted_rate_min"],
        "completed_rate": requests["completed_rate"] >= THRESHOLDS["completed_rate_min"],
        "provider_excluded_p95": latency["provider_excluded_p95_ms"]
        <= THRESHOLDS["api_p95_ms_max"],
        "provider_excluded_p99": latency["provider_excluded_p99_ms"]
        <= THRESHOLDS["api_p99_ms_max"],
        "persistent_provider_latency_complete": latency[
            "all_accepted_samples_have_persistent_provider_evidence"
        ],
        "queue_requested_accepted_completed_exact": (
            queue["requested"] == queue["accepted"] == queue["completed"]
            and queue["result_read_succeeded"] is True
        ),
        "queue_timing_evidence_complete": (
            cast(dict[str, object], queue["timing_evidence"])["sample_count"] == shape.queue_burst
            and cast(dict[str, object], queue["timing_evidence"])["complete"] is True
        ),
        "queue_wait": queue["wait_p95_seconds"]
        <= DEFAULT_WORKER_POLL_SECONDS * THRESHOLDS["queue_wait_poll_multiple_max"],
        "identifier_set_exact": integrity["observed_identifier_set_exact"],
        "observation_diagnostics_complete": diagnostics_payload["complete"],
        "proof_fixture_rejections_zero": _proof_fixture_rejections_zero(diagnostics),
        "provider_usage_integrity": _provider_usage_integrity_passed(integrity),
        "cross_site_and_result_read_isolation": all(isolation.values()),
        "runtime_queue_residue_zero": sum(
            cast(int, integrity[name])
            for name in (
                "queued_residue",
                "running_residue",
                "dispatching_residue",
                "redis_queue_residue",
                "provider_active_residue",
            )
        )
        == 0,
        "artifacts_returned_to_manifest_baseline": integrity["artifact_records"] == 0,
        "rss_growth": not formal
        or (api_growth["within_budget"] is True and worker_growth["within_budget"] is True),
        "process_cohort_stable": process_cohort["all_valid"],
        "api_fd_not_sustained_growth": not resources["api_fd_sustained_growth"],
        "worker_fd_not_sustained_growth": not resources["worker_fd_sustained_growth"],
        "db_connections_not_sustained_growth": not resources[
            "postgres_connection_sustained_growth"
        ],
        "resource_samples_complete": resources["sample_count_passed"],
        "services_survived": resources["services_survived_all_samples"],
        "service_restarts_zero": resources["restart_count_zero"],
        "formal_clean_revision_requirement_satisfied": not formal
        or cast(dict[str, object], top_level["identity"])["git_dirty"] is False,
        "achieved_rate": _achieved_rate_passed(
            cast(float, measured["achieved_requests_per_second"]), shape.request_rate
        ),
        "scheduler_drift": measured["scheduler_drift_max_ms"]
        <= THRESHOLDS["scheduler_drift_ms_max"],
        "real_concurrency_observed": (
            scheduler["concurrency_probe_client_max"] >= concurrency_target
            and integrity["provider_max_concurrency"] >= concurrency_target
            and integrity["provider_barrier_timeouts"] == 0
        ),
    }
    checks = _exact_mapping(top_level["checks"], set(RECORD_CHECK_IDS))
    if (
        not checks
        or any(not isinstance(value, bool) for value in checks.values())
        or checks != recomputed_checks
    ):
        return False
    passed = all(recomputed_checks.values())
    return top_level["record_thresholds_passed"] is passed and top_level["verdict"] == (
        "record_passed" if passed else "record_failed"
    )


def _aggregate(args: argparse.Namespace) -> tuple[dict[str, object], bool]:
    if args.baseline_count < 1:
        raise ProofFailure("aggregate.baseline_count_invalid")
    paths = sorted(args.input_dir.glob("baseline-*.json"))
    if len(paths) != args.baseline_count:
        raise ProofFailure("aggregate.baseline_count_mismatch")
    loaded_records = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if any(not isinstance(record, dict) for record in loaded_records):
        raise ProofFailure("aggregate.record_schema_invalid")
    records = cast(list[dict[str, object]], loaded_records)
    if not all(_record_schema_valid(record, expected_mode=args.mode) for record in records):
        raise ProofFailure("aggregate.record_schema_invalid")
    diagnostics_valid_all_records = all(
        _diagnostics_valid(record.get("observation_diagnostics")) for record in records
    )
    if not diagnostics_valid_all_records:
        raise ProofFailure("aggregate.observation_diagnostics_invalid")
    formal_shape = args.mode == "formal" and args.baseline_count == FORMAL_RECORDS
    identity_receipts = [_canonical_record_mapping(record, "identity") for record in records]
    configuration_receipts = [
        _canonical_record_mapping(record, "configuration") for record in records
    ]
    same_identity = bool(records) and len(set(identity_receipts)) == 1
    same_configuration = bool(records) and len(set(configuration_receipts)) == 1
    indices = sorted(int(record.get("baseline_index", 0)) for record in records)
    environment_receipts = {
        str(record.get("baseline_environment_receipt_sha256") or "") for record in records
    }
    independent = (
        indices == list(range(1, args.baseline_count + 1))
        and "" not in environment_receipts
        and len(environment_receipts) == args.baseline_count
    )
    records_passed = all(record.get("record_thresholds_passed") is True for record in records)
    contracts_match = all(record.get("contract") == CONTRACT_ID for record in records)
    modes_match = all(record.get("mode") == args.mode for record in records)
    formal_records_shape = all(record.get("formal_record_shape") is True for record in records)
    first_p95 = float(records[0].get("latency", {}).get("provider_excluded_p95_ms", 0))
    first_p99 = float(records[0].get("latency", {}).get("provider_excluded_p99_ms", 0))
    comparisons = []
    regression_free = True
    for record in records[1:]:
        p95 = float(record.get("latency", {}).get("provider_excluded_p95_ms", 0))
        p99 = float(record.get("latency", {}).get("provider_excluded_p99_ms", 0))
        p95_failed = _regression_failed(first_p95, p95)
        p99_failed = _regression_failed(first_p99, p99)
        regression_free = regression_free and not p95_failed and not p99_failed
        comparisons.append(
            {
                "provider_excluded_p95_ms": p95,
                "provider_excluded_p99_ms": p99,
                "p95_regression_failed": p95_failed,
                "p99_regression_failed": p99_failed,
            }
        )
    topology_verified = os.environ.get("P5_B4_TOPOLOGY_VERIFIED", "").lower() == "true"
    formal_acceptance = all(
        (
            formal_shape,
            same_identity,
            same_configuration,
            independent,
            records_passed,
            contracts_match,
            modes_match,
            formal_records_shape,
            regression_free,
            topology_verified,
            diagnostics_valid_all_records,
        )
    )
    quick_shape = (
        args.mode == "quick"
        and args.baseline_count == 1
        and all(record.get("formal_record_shape") is False for record in records)
    )
    quick_success = all(
        (
            quick_shape,
            independent,
            records_passed,
            contracts_match,
            modes_match,
            topology_verified,
            diagnostics_valid_all_records,
        )
    )
    success = formal_acceptance if args.mode == "formal" else quick_success
    receipt_fields = (
        "baseline_index",
        "baseline_environment_receipt_sha256",
        "verdict",
        "record_thresholds_passed",
        "scheduler",
        "requests",
        "observation_diagnostics",
        "queue",
        "latency",
        "integrity",
        "isolation",
        "resources",
        "checks",
    )
    receipts = [
        {
            "record_sha256": _sha256(path),
            **{field: record.get(field) for field in receipt_fields},
        }
        for path, record in zip(paths, records, strict=True)
    ]
    return (
        {
            "contract": CONTRACT_ID,
            "generated_at": datetime.now(UTC).isoformat(),
            "verdict": "passed"
            if formal_acceptance
            else "non_acceptance_observation"
            if quick_success
            else "failed",
            "mode": args.mode,
            "formal_acceptance": formal_acceptance,
            "production_slo_claim": False,
            "baseline_count": len(records),
            "first_record_sha256": _sha256(paths[0]),
            "comparison_reference": "locked_first_record_sha256",
            "same_revision_environment_dataset": same_identity,
            "same_configuration": same_configuration,
            "independent_baselines": independent,
            "records_passed": records_passed,
            "record_contracts_match": contracts_match,
            "formal_records_shape": formal_records_shape,
            "latency_regression_free": regression_free,
            "topology_verified": topology_verified,
            "diagnostics_valid_all_records": diagnostics_valid_all_records,
            "later_record_comparisons": comparisons,
            "identity": records[0].get("identity", {}),
            "configuration": records[0].get("configuration", {}),
            "baseline_receipts": receipts,
            "boundary": records[0].get("boundary", {}),
            "limitations": records[0].get("limitations", []),
            "acceptance_rule": {
                "required_formal_records": FORMAL_RECORDS,
                "regression_requires_delta_over_100ms_and_percent_over_20": True,
                "one_record_can_claim_formal_pass": False,
            },
            "redaction": {
                "aggregate_only": True,
                "prompt_fields_emitted": False,
                "result_fields_emitted": False,
                "secret_fields_emitted": False,
                "raw_run_or_site_identifiers_emitted": False,
            },
        },
        success,
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _redaction_violations(payload: object, path: str = "$") -> list[str]:
    forbidden = {
        "run_id",
        "run_ids",
        "site_id",
        "site_ids",
        "prompt",
        "prompts",
        "result",
        "results",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "api_key",
        "signing_secret",
        "request_hash",
        "idempotency_key",
        "authorization",
        "message",
        "payload",
        "body",
    }
    violations: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{path}.{key}"
            if str(key).lower() in forbidden:
                violations.append(child)
            violations.extend(_redaction_violations(value, child))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            violations.extend(_redaction_violations(value, f"{path}[{index}]"))
    return violations


def _failure(code: str) -> dict[str, object]:
    return {
        "contract": CONTRACT_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "verdict": "failed",
        "formal_acceptance": False,
        "production_slo_claim": False,
        "failure_code": code,
        "redaction": {
            "aggregate_only": True,
            "prompt_fields_emitted": False,
            "result_fields_emitted": False,
            "secret_fields_emitted": False,
            "raw_run_or_site_identifiers_emitted": False,
        },
    }


def main() -> int:
    logging.getLogger().setLevel(logging.WARNING)
    args = _parser().parse_args()
    output = cast(Path | None, getattr(args, "output", None))
    try:
        _confirm(args)
        if args.command == "serve-provider":
            return _serve_provider()
        if args.command == "probe-api":
            report, success = _probe_api(), True
        elif args.command == "prepare":
            report, success = _prepare(args.baseline_index), True
        elif args.command == "run":
            report, success = asyncio.run(_run_record(args))
        else:
            report, success = _aggregate(args)
    except ProofFailure as error:
        report, success = _failure(error.code), False
    except Exception:
        report, success = _failure("harness.unexpected_error"), False
    if _redaction_violations(report):
        report, success = _failure("redaction.aggregate_output_violation"), False
    if output is not None:
        _write_json(output, report)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
