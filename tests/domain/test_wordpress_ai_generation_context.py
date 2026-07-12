from __future__ import annotations

from app.domain.wordpress_ai_connector.generation_context import (
    build_generation_context_pack,
    generation_context_policy,
    render_generation_context,
    select_generation_context_post_ids,
)


def test_generation_context_excludes_current_like_content_and_duplicate_posts() -> None:
    policy = generation_context_policy(
        task="title_generation",
        mode="site_title_style",
    )
    assert policy is not None
    current_content = "这是一篇介绍 WordPress 向量检索与编辑器标题生成能力的文章。" * 4

    post_ids = select_generation_context_post_ids(
        policy=policy,
        prompt=f"请为下面的文章生成标题：{current_content}",
        results=[
            {
                "post_id": 10,
                "title": "Current post",
                "chunk": current_content,
                "score": 0.99,
            },
            {"post_id": 11, "title": "Related title", "chunk": "其他相关内容", "score": 0.8},
            {"post_id": 11, "title": "Duplicate chunk", "chunk": "重复内容", "score": 0.75},
            {"post_id": 12, "title": "Below threshold", "chunk": "无关内容", "score": 0.2},
        ],
    )

    assert post_ids == [11]


def test_generation_context_honors_task_budget_and_never_renders_scores_or_chunks() -> None:
    policy = generation_context_policy(
        task="title_generation",
        mode="site_title_style",
    )
    assert policy is not None
    results = [
        {
            "post_id": post_id,
            "title": f"历史标题 {post_id} " + ("风格" * 80),
            "chunk": f"private chunk {post_id}",
            "score": 0.9 - post_id / 100,
        }
        for post_id in range(1, 9)
    ]
    post_ids = select_generation_context_post_ids(
        policy=policy,
        prompt="为一篇全新的文章生成标题",
        results=results,
    )
    pack = build_generation_context_pack(
        policy=policy,
        post_ids=post_ids,
        results=results,
        reference_metadata={},
    )

    assert pack is not None
    assert pack["reference_count"] <= policy.max_references
    assert pack["context_chars"] <= policy.max_context_chars
    rendered = render_generation_context(pack)
    assert "generation_context.v1" in rendered
    assert "private chunk" not in rendered
    assert "0.89" not in rendered


def test_generation_context_ranks_existing_taxonomies_by_related_post_frequency() -> None:
    policy = generation_context_policy(
        task="content_classification",
        mode="site_taxonomy_history",
    )
    assert policy is not None
    metadata = {
        11: {
            "taxonomies": {
                "category": ["WordPress", "AI"],
                "post_tag": ["向量检索"],
            }
        },
        12: {
            "taxonomies": {
                "category": ["WordPress"],
                "post_tag": ["站点知识", "向量检索"],
            }
        },
    }

    pack = build_generation_context_pack(
        policy=policy,
        post_ids=[11, 12],
        results=[],
        reference_metadata=metadata,
    )

    assert pack is not None
    values = [reference["value"] for reference in pack["references"]]
    assert values[:2] == ["WordPress", "向量检索"]
    rendered = render_generation_context(pack)
    assert "term IDs" in rendered
    assert "current scene input is the only factual source" in rendered
