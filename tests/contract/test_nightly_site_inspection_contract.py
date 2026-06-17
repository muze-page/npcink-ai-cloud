from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_nightly_site_inspection_contract_freezes_local_schedule_boundary() -> None:
    contract = _read("docs/nightly-site-inspection-morning-brief-v1.md")
    readme = _read("README.md")

    for required in (
        "Nightly Intelligence / Morning Brief v1",
        "Nightly Intelligence = off-hours site inspection and morning editorial readiness",
        "nightly site inspection + morning writing preparation + content quality scoring",
        "`WP-Cron` as the default trigger",
        "Do not introduce Action Scheduler",
        "capped local dry-run/preview path",
        "manual run button",
        "Server cron is a production recommendation",
        "must not replace local schedule ownership",
        "WordPress/plugin side owns",
        "local site enumeration",
        "Morning Brief storage and dashboard display",
        "user-facing review, approval, apply, rollback, and final WordPress writes",
    ):
        assert required in contract

    assert "docs/nightly-site-inspection-morning-brief-v1.md" in readme


def test_nightly_site_inspection_contract_keeps_cloud_runtime_only() -> None:
    contract = _read("docs/nightly-site-inspection-morning-brief-v1.md")

    for required in (
        "Nightly Intelligence is for checking, analysis, scoring, and issue discovery.",
        "`review_items`",
        "`blocked_items`",
        "`retry_guidance`",
        "`core_handoff_suggestion`",
        "nightly_site_inspection_core_intake_package.v1",
        "select_review_item_in_morning_brief",
        "morning_brief_review_queue",
        "core:/proposals/from-plan",
        "core_proposal_id",
        "cloud_receipt_storage",
        "not_canonical",
        "nightly_intelligence_detail.v1",
        "This detail object is not a Cloud control plane.",
        "This package is not a Core proposal and does not create one.",
        "Do not build a Cloud orchestration platform",
        "Cloud may execute\nbounded runtime tasks",
        "Cloud must use the existing stack and seams",
        "FastAPI public runtime routes",
        "PostgreSQL canonical Cloud run/usage evidence",
        "Redis only for queue assist and worker wake-up",
        "existing runtime worker/callback worker patterns",
        "`whole_run_offload` or bounded `inline` analysis",
        "`storage_mode`: default `result_only`",
        "Cloud does not introduce a second scheduler or workflow engine",
    ):
        assert required in contract

    for forbidden in (
        "Temporal, Celery, RabbitMQ, Kafka, NATS, Airflow, Dagster",
        "a second workflow engine",
        "a second scheduler truth",
        "a task-pack product surface",
        "a Cloud ability registry",
        "direct WordPress publishing or content mutation APIs",
    ):
        assert forbidden in contract


def test_nightly_site_inspection_contract_blocks_cloud_article_factory() -> None:
    contract = _read("docs/nightly-site-inspection-morning-brief-v1.md")

    for required in (
        "Cloud must not perform nightly article writing generation",
        "full article drafts",
        "batch article plans",
        "article bodies, sections, paragraphs, or final FAQ copy",
        "SEO title, excerpt, or meta-description copy as unattended nightly output",
        "Cloud-produced `article_write_plan` candidates",
        "direct draft creation, scheduling, publishing, or content updates",
        "source evidence",
        "nightly_site_inspection_core_review_plan.v1",
        "npcink-toolbox/build-nightly-inspection-review-plan",
        "proposal_ready=false",
        "content gap classification",
        "refresh opportunity",
        "review tasks",
        "internal-link follow-up",
        "media follow-up",
        "compliance/risk labels",
        "must run through local Ability/Core review flows",
    ):
        assert required in contract


def test_nightly_cloud_core_handoff_contract_defines_core_intake_package() -> None:
    handoff = _read("docs/nightly-inspection-cloud-core-handoff-v1.md")
    batch_runtime = _read("docs/pro-cloud-batch-runtime-v1.md")

    for required in (
        "nightly_site_inspection_core_intake_package",
        "nightly_site_inspection_core_intake_package.v1",
        "select_review_item_in_morning_brief",
        "wordpress_toolbox_local",
        "morning_brief_review_queue",
        "core:/proposals/from-plan",
        "proposal_created",
        "proposal_state_owner",
        "core_proposal_id",
        "cloud_receipt_storage",
        "not_canonical",
        "not a Cloud proposal record",
        "Cloud proposal truth",
    ):
        assert required in handoff

    for required in (
        "core_intake_package_available",
        "core_intake_package",
        "nightly_site_inspection_core_intake_package.v1",
        "The `core_intake_package` is the Morning Brief selection envelope",
        "canonical receipt remains the local Core `core_proposal_id`",
    ):
        assert required in batch_runtime
