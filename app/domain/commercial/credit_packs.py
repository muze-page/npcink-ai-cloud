"""AI credit pack catalog for customer self-serve purchases."""

from __future__ import annotations

from dataclasses import dataclass

CREDIT_PACK_CATALOG_VERSION = "ai-credit-packs-v1"


@dataclass(frozen=True)
class CreditPack:
    pack_id: str
    label: str
    ai_credits: int
    amount: float
    currency: str
    recommended_for_tiers: tuple[str, ...]
    active: bool = True


CREDIT_PACKS: tuple[CreditPack, ...] = (
    CreditPack(
        pack_id="pack_small",
        label="Small credit pack",
        ai_credits=10_000,
        amount=99.0,
        currency="CNY",
        recommended_for_tiers=("free", "pro"),
    ),
    CreditPack(
        pack_id="pack_medium",
        label="Medium credit pack",
        ai_credits=35_000,
        amount=349.0,
        currency="CNY",
        recommended_for_tiers=("pro", "agency"),
    ),
    CreditPack(
        pack_id="pack_large",
        label="Large credit pack",
        ai_credits=150_000,
        amount=1499.0,
        currency="CNY",
        recommended_for_tiers=("agency",),
    ),
)


def get_credit_pack(pack_id: str) -> CreditPack | None:
    normalized_pack_id = str(pack_id or "").strip()
    for pack in CREDIT_PACKS:
        if pack.pack_id == normalized_pack_id:
            return pack
    return None


def serialize_credit_pack(pack: CreditPack) -> dict[str, object]:
    return {
        "pack_id": pack.pack_id,
        "label": pack.label,
        "ai_credits": pack.ai_credits,
        "amount": round(float(pack.amount), 6),
        "currency": pack.currency,
        "recommended_for_tiers": list(pack.recommended_for_tiers),
        "active": pack.active,
        "period_policy": "current_subscription_period",
        "grant_event_type": "grant",
        "catalog_version": CREDIT_PACK_CATALOG_VERSION,
    }


def list_credit_packs(*, include_inactive: bool = False) -> list[dict[str, object]]:
    return [
        serialize_credit_pack(pack)
        for pack in CREDIT_PACKS
        if include_inactive or pack.active
    ]
