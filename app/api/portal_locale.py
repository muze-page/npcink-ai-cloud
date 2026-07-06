from __future__ import annotations

from fastapi import Request


def resolve_portal_email_locale(request: Request, explicit_locale: str = "") -> str:
    candidates = [
        explicit_locale,
        str(request.headers.get("x-npcink-locale") or ""),
        str(request.cookies.get("npcink_locale") or ""),
        str(request.query_params.get("lang") or ""),
        str(request.headers.get("accept-language") or "").split(",")[0],
    ]
    for candidate in candidates:
        value = candidate.strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in {"zh", "zh-cn", "zh_hans", "zh-hans", "zh_cn"} or lowered.startswith("zh-cn"):
            return "zh-CN"
        if (
            lowered in {"zh-tw", "zh_hant", "zh-hant", "zh_tw", "zh-hk"}
            or lowered.startswith("zh-tw")
            or lowered.startswith("zh-hk")
        ):
            return "zh-TW"
        if lowered.startswith("en"):
            return "en"
    return "zh-CN"
