from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.core.db import check_database_connection, get_session
from app.core.feature_flags import EnvFeatureFlagProvider
from app.core.models import CatalogModel, CatalogModelAnnotation, CatalogRevision, ProviderConnection


@dataclass(frozen=True)
class PreflightCheck:
    code: str
    status: str
    message: str
    details: str = ""


def _is_truthy(value: str | None) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _configured_env_provider_sources(settings: Settings) -> list[str]:
    configured: list[str] = []

    if str(settings.openai_api_key or "").strip():
        configured.append("openai")
    if str(settings.anthropic_api_key or "").strip():
        configured.append("anthropic")
    if settings.litellm_provider_enabled and str(settings.litellm_base_url or "").strip():
        configured.append("litellm")
    if settings.vllm_provider_enabled and str(settings.vllm_base_url or "").strip():
        configured.append("vllm")
    if settings.tei_provider_enabled and str(settings.tei_base_url or "").strip():
        configured.append("tei")
    if settings.openrouter_provider_enabled and str(settings.openrouter_api_key or "").strip():
        configured.append("openrouter")

    return configured


def evaluate_model_admin_release_preflight(settings: Settings) -> dict[str, Any]:
    checks: list[PreflightCheck] = []
    feature_flags = EnvFeatureFlagProvider(settings)
    ok, db_message = check_database_connection(settings.database_url)
    if not ok:
        checks.append(
            PreflightCheck(
                code="database_reachable",
                status="blocker",
                message="Database is not reachable.",
                details=db_message,
            )
        )
        return _serialize_report(settings, checks, counts={})

    openai_catalog_profile = str(settings.openai_sample_catalog_profile or "").strip()
    recognition_review_profile = str(
        settings.openai_recognition_review_sample_catalog_profile or ""
    ).strip()

    if openai_catalog_profile:
        checks.append(
            PreflightCheck(
                code="openai_sample_catalog_profile_disabled",
                status="blocker",
                message="Hosted Catalog still uses a sample catalog profile.",
                details=f"Unset MAGICK_CLOUD_OPENAI_SAMPLE_CATALOG_PROFILE (current: {openai_catalog_profile}).",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="openai_sample_catalog_profile_disabled",
                status="ok",
                message="Hosted Catalog sample catalog profile is disabled.",
            )
        )

    if recognition_review_profile:
        checks.append(
            PreflightCheck(
                code="recognition_review_sample_profile_disabled",
                status="blocker",
                message="Recognition Review still uses a sample review profile.",
                details=(
                    "Unset MAGICK_CLOUD_OPENAI_RECOGNITION_REVIEW_SAMPLE_CATALOG_PROFILE "
                    f"(current: {recognition_review_profile})."
                ),
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="recognition_review_sample_profile_disabled",
                status="ok",
                message="Recognition Review sample profile is disabled.",
            )
        )

    if feature_flags.is_enabled("admin.dev_internal_token_fallback.enabled"):
        checks.append(
            PreflightCheck(
                code="dev_internal_token_fallback_disabled",
                status="blocker",
                message="Dev internal token fallback is still enabled.",
                details="Set MAGICK_CLOUD_ALLOW_DEV_ADMIN_INTERNAL_TOKEN_FALLBACK=false before launch.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="dev_internal_token_fallback_disabled",
                status="ok",
                message="Dev internal token fallback is disabled.",
            )
        )

    if feature_flags.parse_error:
        checks.append(
            PreflightCheck(
                code="feature_flag_overrides_parseable",
                status="blocker",
                message="Feature flag overrides are not parseable.",
                details=feature_flags.parse_error,
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="feature_flag_overrides_parseable",
                status="ok",
                message="Feature flag overrides are parseable.",
                details=(
                    "overrides="
                    + str(feature_flags.build_summary()["summary"]["overridden_total"])
                ),
            )
        )

    if str(settings.admin_session_secret or "").strip():
        checks.append(
            PreflightCheck(
                code="admin_session_secret_present",
                status="ok",
                message="Admin session secret is configured.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="admin_session_secret_present",
                status="blocker",
                message="Admin session secret is missing.",
                details="Set MAGICK_CLOUD_ADMIN_SESSION_SECRET to a 32+ byte secret.",
            )
        )

    if str(settings.provider_connection_secret or "").strip():
        checks.append(
            PreflightCheck(
                code="provider_connection_secret_present",
                status="ok",
                message="Provider connection secret is configured.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="provider_connection_secret_present",
                status="blocker",
                message="Provider connection secret is missing.",
                details="Set MAGICK_CLOUD_PROVIDER_CONNECTION_SECRET to a 32+ byte secret.",
            )
        )

    configured_env_sources = _configured_env_provider_sources(settings)

    with get_session(settings.database_url) as session:
        enabled_connections = list(
            session.scalars(
                select(ProviderConnection).where(ProviderConnection.enabled.is_(True))
            )
        )
        enabled_connection_ids = [item.connection_id for item in enabled_connections]
        non_cloud_local_connections = []
        for item in enabled_connections:
            metadata = dict(item.metadata_json or {})
            credential_origin = str(metadata.get("credential_origin") or "").strip().lower()
            if credential_origin != "cloud_local":
                non_cloud_local_connections.append(item.connection_id)
        errored_connections = [
            item.connection_id
            for item in enabled_connections
            if str(item.status or "").strip().lower() == "error"
        ]
        hosted_total = int(session.scalar(select(func.count()).select_from(CatalogModel)) or 0)
        recommended_total = int(
            session.scalar(
                select(func.count()).select_from(CatalogModelAnnotation).where(
                    CatalogModelAnnotation.recommended.is_(True)
                )
            )
            or 0
        )
        latest_revision = session.scalar(
            select(CatalogRevision).order_by(CatalogRevision.created_at.desc(), CatalogRevision.id.desc())
        )
        sample_tagged_rows = list(
            session.scalars(select(CatalogModel).where(CatalogModel.raw_json.is_not(None)))
        )

    effective_sources_total = len(configured_env_sources) + len(enabled_connections)
    if effective_sources_total > 0:
        checks.append(
            PreflightCheck(
                code="provider_source_present",
                status="ok",
                message="At least one provider source is configured.",
                details=(
                    f"env_sources={configured_env_sources or ['none']}, "
                    f"enabled_connections={enabled_connection_ids or ['none']}"
                ),
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="provider_source_present",
                status="blocker",
                message="No provider source is configured.",
                details="Configure at least one real upstream provider or provider connection before launch.",
            )
        )

    if errored_connections:
        checks.append(
            PreflightCheck(
                code="enabled_provider_connections_healthy",
                status="blocker",
                message="One or more enabled provider connections are currently failing.",
                details=", ".join(sorted(errored_connections)),
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="enabled_provider_connections_healthy",
                status="ok",
                message="Enabled provider connections are not in error state.",
            )
        )

    if non_cloud_local_connections:
        checks.append(
            PreflightCheck(
                code="provider_connection_credentials_cloud_local",
                status="blocker",
                message="One or more enabled provider connections do not declare cloud-local credential ownership.",
                details=(
                    "Cloud provider connections must be created and credentialed by platform admins in cloud. "
                    "Do not reuse plugin-local or user-local provider secrets. "
                    f"connections={sorted(non_cloud_local_connections)}"
                ),
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="provider_connection_credentials_cloud_local",
                status="ok",
                message="Enabled provider connections declare cloud-local credential ownership.",
            )
        )

    if hosted_total > 0:
        checks.append(
            PreflightCheck(
                code="hosted_catalog_non_empty",
                status="ok",
                message="Hosted Catalog contains models.",
                details=f"hosted_models_total={hosted_total}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="hosted_catalog_non_empty",
                status="blocker",
                message="Hosted Catalog is empty.",
                details="Sync at least one real provider source into Hosted Catalog before launch.",
            )
        )

    sample_profile_models = [
        model.model_id
        for model in sample_tagged_rows
        if str((model.raw_json or {}).get("catalog_profile") or "").strip().startswith("recognition_")
    ]
    if sample_profile_models:
        checks.append(
            PreflightCheck(
                code="hosted_catalog_not_sample_seeded",
                status="blocker",
                message="Hosted Catalog still contains sample-seeded rows.",
                details=f"sample_rows={len(sample_profile_models)}; first={sample_profile_models[:10]}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="hosted_catalog_not_sample_seeded",
                status="ok",
                message="Hosted Catalog has no sample-seeded rows.",
            )
        )

    if recommended_total > 0:
        checks.append(
            PreflightCheck(
                code="hosted_catalog_has_operator_curation",
                status="ok",
                message="Hosted Catalog has operator-curated recommended models.",
                details=f"recommended_total={recommended_total}",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="hosted_catalog_has_operator_curation",
                status="warn",
                message="Hosted Catalog has no recommended models yet.",
                details="This is allowed, but launch UX is usually better with at least one curated recommended model.",
            )
        )

    if latest_revision is None:
        checks.append(
            PreflightCheck(
                code="catalog_revision_present",
                status="blocker",
                message="No catalog revision has been created yet.",
            )
        )
    else:
        checks.append(
            PreflightCheck(
                code="catalog_revision_present",
                status="ok",
                message="Catalog revision is present.",
                details=f"latest_revision={latest_revision.revision}",
            )
        )

    return _serialize_report(
        settings,
        checks,
        counts={
            "configured_env_provider_sources_total": len(configured_env_sources),
            "enabled_provider_connections_total": len(enabled_connections),
            "hosted_models_total": hosted_total,
            "recommended_models_total": recommended_total,
            "sample_seeded_hosted_models_total": len(sample_profile_models),
            "feature_flag_overrides_total": int(
                feature_flags.build_summary()["summary"]["overridden_total"]
            ),
        },
    )


def _serialize_report(
    settings: Settings,
    checks: list[PreflightCheck],
    *,
    counts: dict[str, int],
) -> dict[str, Any]:
    blockers = [item for item in checks if item.status == "blocker"]
    warnings = [item for item in checks if item.status == "warn"]
    return {
        "environment": settings.environment,
        "ok": not blockers,
        "blockers_total": len(blockers),
        "warnings_total": len(warnings),
        "checks": [
            {
                "code": item.code,
                "status": item.status,
                "message": item.message,
                "details": item.details,
            }
            for item in checks
        ],
        "counts": counts,
    }


def _print_report(report: dict[str, Any]) -> None:
    print("Cloud model admin release preflight")
    print(f"environment: {report['environment']}")
    print(f"ok: {'yes' if report['ok'] else 'no'}")
    print(f"blockers: {report['blockers_total']}")
    print(f"warnings: {report['warnings_total']}")
    if report["counts"]:
        print("counts:")
        for key in sorted(report["counts"].keys()):
            print(f"  - {key}: {report['counts'][key]}")
    print("checks:")
    for item in report["checks"]:
        line = f"  - [{item['status']}] {item['code']}: {item['message']}"
        if item["details"]:
            line = f"{line} ({item['details']})"
        print(line)


def main() -> int:
    report = evaluate_model_admin_release_preflight(get_settings())
    _print_report(report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
