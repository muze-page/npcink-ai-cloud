from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_cloud_bulk_article_contract_prohibits_cloud_writing_generation() -> None:
    contract = _read("docs/cloud-bulk-article-run-v1.md")
    content_boundary = _read("docs/cloud-content-generation-boundary-v1.md")
    readme = _read("README.md")

    for required in (
        "Status: prohibited and deprecated planning contract",
        "bulk_article_run_v1",
        "Cloud bulk article generation is not a product surface",
        "article title generation",
        "article outline generation",
        "paragraph or body drafting",
        "SEO title, excerpt, or meta-description writing",
        "batch article draft production",
        "Cloud-produced `article_write_plan` candidates",
        "Cloud article artifact import into Toolbox",
        "direct Cloud publishing",
        "local Ability recipe",
        "article_write_plan",
        "magick-ai-toolbox/build-article-write-plan",
        "Core /proposals/from-plan",
        "WordPress Abilities API",
        "must not become article workflow",
        "blocked",
        "contract identifier",
    ):
        assert required in contract

    assert "Cloud article writing generation is not cautiously allowed" in content_boundary
    assert "article writing generation, batch article drafts" in content_boundary
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
        "/v1/articles/bulk-runs",
        "/v1/bulk-article-runs",
        "wp_insert_post",
        "wp_update_post",
    )

    for forbidden in forbidden_fragments:
        assert forbidden not in source_text
