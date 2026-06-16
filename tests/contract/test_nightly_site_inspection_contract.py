from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_nightly_site_inspection_contract_freezes_local_schedule_boundary() -> None:
    contract = _read("docs/nightly-site-inspection-morning-brief-v1.md")
    readme = _read("README.md")

    for required in (
        "Nightly Site Inspection / Morning Brief v1",
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
