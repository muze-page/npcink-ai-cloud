"""Stable customer-facing subjects for external payment providers."""

from __future__ import annotations

PAYMENT_SUBJECT_BRAND = "Npcink AI Cloud"

_CREDIT_PACK_NAMES_ZH = {
    "pack_small": "小积分包",
    "pack_medium": "中积分包",
    "pack_large": "大积分包",
}

_SUBSCRIPTION_TIER_NAMES = {
    "free": "Free",
    "plus": "Plus",
    "pro": "Pro",
    "agency": "Agency",
}


def build_credit_pack_payment_subject(*, pack_id: str, ai_credits: int) -> str:
    """Return the stable Chinese payment descriptor for a credit-pack snapshot."""
    normalized_pack_id = str(pack_id or "").strip()
    pack_name = _CREDIT_PACK_NAMES_ZH.get(normalized_pack_id, "积分包")
    normalized_credits = max(int(ai_credits), 0)
    return f"{PAYMENT_SUBJECT_BRAND} {pack_name}（{normalized_credits:,} AI 积分）"


def build_subscription_payment_subject(*, tier_id: str) -> str:
    """Return the stable Chinese payment descriptor for a monthly plan order."""
    normalized_tier_id = str(tier_id or "").strip().lower()
    tier_name = _SUBSCRIPTION_TIER_NAMES.get(normalized_tier_id, "")
    if tier_name:
        return f"{PAYMENT_SUBJECT_BRAND} {tier_name} 月度套餐"
    return f"{PAYMENT_SUBJECT_BRAND} 月度套餐"
