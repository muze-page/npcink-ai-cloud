from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cloud_bulk_article_contract_keeps_cloud_runtime_only() -> None:
    contract = _read("docs/cloud-bulk-article-run-v1.md")
    content_boundary = _read("docs/cloud-content-generation-boundary-v1.md")
    readme = _read("README.md")

    for required in (
        "Status: active planning contract",
        "bulk_article_run_v1",
        "Cloud bulk article work is runtime preparation",
        "Cloud bulk article work is not publishing",
        "Final WordPress writes remain local",
        "Core-governed, preflighted, audited",
        "approval_policy",
        "wordpress_write_target",
        "post_status=publish",
        "commit=true",
        "ready_for_local_review",
        "partially_ready_for_local_review",
        "article_write_plan",
        "magick-ai-toolbox/build-article-write-plan",
        "POST /wp-json/magick-ai-core/v1/proposals/from-plan",
        "must not mark it",
        "published",
        "bulk spam",
        "doorway pages",
        "Cloud Addon reads run/result detail",
        "WordPress Abilities API",
        "direct Cloud publishing",
        "Cloud WordPress credentials",
        "a second scheduler or workflow truth",
    ):
        assert required in contract

    assert "direct cloud-side publishing to WordPress" in content_boundary
    assert "docs/cloud-bulk-article-run-v1.md" in readme


def test_cloud_bulk_article_contract_does_not_add_public_publish_route() -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "app").rglob("*.py")
    )

    forbidden_fragments = (
        "/v1/articles/bulk-publish",
        "/v1/bulk-publish",
        "wp_insert_post",
        "wp_update_post",
    )

    for forbidden in forbidden_fragments:
        assert forbidden not in source_text
