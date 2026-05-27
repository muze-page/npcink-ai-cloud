from __future__ import annotations

import json
from dataclasses import dataclass

from app.core.config import Settings


@dataclass(frozen=True)
class FeatureFlagDefinition:
    key: str
    enabled: bool
    description: str


@dataclass(frozen=True)
class ResolvedFeatureFlag:
    key: str
    enabled: bool
    source: str
    default_enabled: bool
    description: str


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in {0, 1}:
            return bool(value)
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _default_flag_definitions(settings: Settings) -> tuple[FeatureFlagDefinition, ...]:
    return (
        FeatureFlagDefinition(
            key="admin.commercial_ops.enabled",
            enabled=True,
            description="Bounded admin commercial guidance surfaces remain available.",
        ),
        FeatureFlagDefinition(
            key="portal.billing.readonly.enabled",
            enabled=True,
            description="Portal billing stays read-only and operator-mediated.",
        ),
        FeatureFlagDefinition(
            key="admin.dev_internal_token_fallback.enabled",
            enabled=bool(settings.allow_dev_admin_internal_token_fallback),
            description="Development-only internal admin token fallback is enabled.",
        ),
    )


class EnvFeatureFlagProvider:
    def __init__(self, settings: Settings) -> None:
        self._definitions = {item.key: item for item in _default_flag_definitions(settings)}
        self._overrides, self._parse_error = self._parse_overrides(settings.feature_flags_json)

    @property
    def parse_error(self) -> str:
        return self._parse_error

    def is_enabled(self, key: str, *, default: bool = False) -> bool:
        resolved = self.resolve(key)
        if resolved is not None:
            return resolved.enabled
        return default

    def resolve(self, key: str) -> ResolvedFeatureFlag | None:
        definition = self._definitions.get(key)
        if definition is None:
            if key not in self._overrides:
                return None
            return ResolvedFeatureFlag(
                key=key,
                enabled=bool(self._overrides[key]),
                source="env_override",
                default_enabled=False,
                description="Runtime-only env-backed feature flag override.",
            )

        if key in self._overrides:
            return ResolvedFeatureFlag(
                key=key,
                enabled=bool(self._overrides[key]),
                source="env_override",
                default_enabled=definition.enabled,
                description=definition.description,
            )

        return ResolvedFeatureFlag(
            key=key,
            enabled=definition.enabled,
            source="settings_default",
            default_enabled=definition.enabled,
            description=definition.description,
        )

    def list_flags(self) -> list[ResolvedFeatureFlag]:
        keys = set(self._definitions.keys()) | set(self._overrides.keys())
        items = [self.resolve(key) for key in sorted(keys)]
        return [item for item in items if item is not None]

    def build_summary(self) -> dict[str, object]:
        items = self.list_flags()
        return {
            "source": "settings_defaults+env_overrides",
            "parse_error": self._parse_error,
            "summary": {
                "flags_total": len(items),
                "enabled_total": sum(1 for item in items if item.enabled),
                "disabled_total": sum(1 for item in items if not item.enabled),
                "overridden_total": sum(1 for item in items if item.source == "env_override"),
            },
            "items": [
                {
                    "key": item.key,
                    "enabled": item.enabled,
                    "source": item.source,
                    "default_enabled": item.default_enabled,
                    "description": item.description,
                }
                for item in items
            ],
        }

    def _parse_overrides(self, raw: str) -> tuple[dict[str, bool], str]:
        if not str(raw or "").strip():
            return {}, ""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return {}, f"invalid MAGICK_CLOUD_FEATURE_FLAGS_JSON: {exc.msg}"
        if not isinstance(parsed, dict):
            return {}, "invalid MAGICK_CLOUD_FEATURE_FLAGS_JSON: top-level value must be an object"
        overrides: dict[str, bool] = {}
        invalid_keys: list[str] = []
        for key, value in parsed.items():
            normalized_key = str(key or "").strip()
            coerced = _coerce_bool(value)
            if not normalized_key or coerced is None:
                invalid_keys.append(normalized_key or "<empty>")
                continue
            overrides[normalized_key] = coerced
        if invalid_keys:
            return (
                overrides,
                "invalid MAGICK_CLOUD_FEATURE_FLAGS_JSON entries: "
                + ", ".join(sorted(set(invalid_keys))),
            )
        return overrides, ""
