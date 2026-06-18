from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ErrorTaxonomyEntry:
    error_code: str
    error_stage: str
    retryable: bool
    fallback_eligible: bool


_ERROR_TAXONOMY: dict[str, ErrorTaxonomyEntry] = {
    "provider.timeout": ErrorTaxonomyEntry(
        error_code="provider.timeout",
        error_stage="provider",
        retryable=True,
        fallback_eligible=True,
    ),
    "provider.network_error": ErrorTaxonomyEntry(
        error_code="provider.network_error",
        error_stage="provider",
        retryable=True,
        fallback_eligible=True,
    ),
    "provider.rate_limited": ErrorTaxonomyEntry(
        error_code="provider.rate_limited",
        error_stage="provider",
        retryable=True,
        fallback_eligible=True,
    ),
    "provider.upstream_unavailable": ErrorTaxonomyEntry(
        error_code="provider.upstream_unavailable",
        error_stage="provider",
        retryable=True,
        fallback_eligible=True,
    ),
    "provider.upstream_error": ErrorTaxonomyEntry(
        error_code="provider.upstream_error",
        error_stage="provider",
        retryable=True,
        fallback_eligible=True,
    ),
    "provider.quota_exceeded": ErrorTaxonomyEntry(
        error_code="provider.quota_exceeded",
        error_stage="provider",
        retryable=False,
        fallback_eligible=True,
    ),
    "provider.auth_invalid": ErrorTaxonomyEntry(
        error_code="provider.auth_invalid",
        error_stage="provider",
        retryable=False,
        fallback_eligible=True,
    ),
    "provider.access_denied": ErrorTaxonomyEntry(
        error_code="provider.access_denied",
        error_stage="provider",
        retryable=False,
        fallback_eligible=True,
    ),
    "provider.endpoint_not_found": ErrorTaxonomyEntry(
        error_code="provider.endpoint_not_found",
        error_stage="provider",
        retryable=False,
        fallback_eligible=True,
    ),
    "provider.invalid_request": ErrorTaxonomyEntry(
        error_code="provider.invalid_request",
        error_stage="provider",
        retryable=False,
        fallback_eligible=False,
    ),
    "provider.unsupported_operation": ErrorTaxonomyEntry(
        error_code="provider.unsupported_operation",
        error_stage="provider",
        retryable=False,
        fallback_eligible=False,
    ),
    "provider.content_filtered": ErrorTaxonomyEntry(
        error_code="provider.content_filtered",
        error_stage="provider",
        retryable=False,
        fallback_eligible=False,
    ),
    "provider.simulated_error": ErrorTaxonomyEntry(
        error_code="provider.simulated_error",
        error_stage="provider",
        retryable=False,
        fallback_eligible=True,
    ),
    "runtime.provider_not_configured": ErrorTaxonomyEntry(
        error_code="runtime.provider_not_configured",
        error_stage="runtime",
        retryable=False,
        fallback_eligible=True,
    ),
    "runtime.execute_failed": ErrorTaxonomyEntry(
        error_code="runtime.execute_failed",
        error_stage="runtime",
        retryable=False,
        fallback_eligible=False,
    ),
    "cloud_batch_runtime.item_invalid": ErrorTaxonomyEntry(
        error_code="cloud_batch_runtime.item_invalid",
        error_stage="runtime",
        retryable=True,
        fallback_eligible=False,
    ),
    "cloud_batch_runtime.invalid_input": ErrorTaxonomyEntry(
        error_code="cloud_batch_runtime.invalid_input",
        error_stage="contract",
        retryable=False,
        fallback_eligible=False,
    ),
    "cloud_batch_runtime.items_required": ErrorTaxonomyEntry(
        error_code="cloud_batch_runtime.items_required",
        error_stage="contract",
        retryable=False,
        fallback_eligible=False,
    ),
    "cloud_batch_runtime.items_limit_exceeded": ErrorTaxonomyEntry(
        error_code="cloud_batch_runtime.items_limit_exceeded",
        error_stage="contract",
        retryable=False,
        fallback_eligible=False,
    ),
    "cloud_batch_runtime.write_or_secret_field_forbidden": ErrorTaxonomyEntry(
        error_code="cloud_batch_runtime.write_or_secret_field_forbidden",
        error_stage="contract",
        retryable=False,
        fallback_eligible=False,
    ),
    "commercial.batch_limit_exceeded": ErrorTaxonomyEntry(
        error_code="commercial.batch_limit_exceeded",
        error_stage="entitlement",
        retryable=False,
        fallback_eligible=False,
    ),
    "commercial.quota_exceeded": ErrorTaxonomyEntry(
        error_code="commercial.quota_exceeded",
        error_stage="entitlement",
        retryable=False,
        fallback_eligible=False,
    ),
    "routing.profile_not_found": ErrorTaxonomyEntry(
        error_code="routing.profile_not_found",
        error_stage="routing",
        retryable=False,
        fallback_eligible=False,
    ),
    "routing.no_candidates": ErrorTaxonomyEntry(
        error_code="routing.no_candidates",
        error_stage="routing",
        retryable=False,
        fallback_eligible=False,
    ),
}


def get_error_taxonomy(error_code: str | None) -> ErrorTaxonomyEntry:
    if not error_code:
        return ErrorTaxonomyEntry(
            error_code="",
            error_stage="",
            retryable=False,
            fallback_eligible=False,
        )

    if error_code in _ERROR_TAXONOMY:
        return _ERROR_TAXONOMY[error_code]

    if error_code.startswith("provider."):
        return ErrorTaxonomyEntry(
            error_code=error_code,
            error_stage="provider",
            retryable=False,
            fallback_eligible=True,
        )

    if error_code.startswith("routing."):
        return ErrorTaxonomyEntry(
            error_code=error_code,
            error_stage="routing",
            retryable=False,
            fallback_eligible=False,
        )

    if error_code.startswith("auth."):
        return ErrorTaxonomyEntry(
            error_code=error_code,
            error_stage="auth",
            retryable=False,
            fallback_eligible=False,
        )

    if error_code.startswith("commercial."):
        return ErrorTaxonomyEntry(
            error_code=error_code,
            error_stage="entitlement",
            retryable=False,
            fallback_eligible=False,
        )

    if error_code.startswith("cloud_batch_runtime."):
        return ErrorTaxonomyEntry(
            error_code=error_code,
            error_stage="runtime",
            retryable=False,
            fallback_eligible=False,
        )

    if error_code.startswith("stats."):
        return ErrorTaxonomyEntry(
            error_code=error_code,
            error_stage="stats",
            retryable=False,
            fallback_eligible=False,
        )

    if error_code.startswith("health."):
        return ErrorTaxonomyEntry(
            error_code=error_code,
            error_stage="health",
            retryable=False,
            fallback_eligible=False,
        )

    return ErrorTaxonomyEntry(
        error_code=error_code,
        error_stage="runtime",
        retryable=False,
        fallback_eligible=False,
    )
