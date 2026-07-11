from __future__ import annotations

import pytest

from app.domain.commercial.payment_subjects import (
    build_credit_pack_payment_subject,
    build_subscription_payment_subject,
)


@pytest.mark.parametrize(
    ("pack_id", "ai_credits", "expected"),
    [
        ("pack_small", 10_000, "Npcink AI Cloud 小积分包（10,000 AI 积分）"),
        ("pack_medium", 35_000, "Npcink AI Cloud 中积分包（35,000 AI 积分）"),
        ("pack_large", 150_000, "Npcink AI Cloud 大积分包（150,000 AI 积分）"),
        ("custom_pack", 1_000, "Npcink AI Cloud 积分包（1,000 AI 积分）"),
    ],
)
def test_credit_pack_payment_subjects_are_stable_chinese_descriptors(
    pack_id: str,
    ai_credits: int,
    expected: str,
) -> None:
    subject = build_credit_pack_payment_subject(pack_id=pack_id, ai_credits=ai_credits)

    assert subject == expected
    assert len(subject) <= 256


@pytest.mark.parametrize(
    ("tier_id", "expected"),
    [
        ("plus", "Npcink AI Cloud Plus 月度套餐"),
        ("pro", "Npcink AI Cloud Pro 月度套餐"),
        ("agency", "Npcink AI Cloud Agency 月度套餐"),
        ("unknown", "Npcink AI Cloud 月度套餐"),
    ],
)
def test_subscription_payment_subjects_are_stable_chinese_descriptors(
    tier_id: str,
    expected: str,
) -> None:
    subject = build_subscription_payment_subject(tier_id=tier_id)

    assert subject == expected
    assert len(subject) <= 256
