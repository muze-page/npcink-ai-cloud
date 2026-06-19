from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings

PROVIDER_IDS = ("unsplash", "pixabay", "pexels")
PROVIDER_MODES = ("disabled", "auto", "unsplash", "pixabay", "pexels")

ENV_KEYS = {
    "provider": "MAGICK_CLOUD_IMAGE_SOURCE_PROVIDER",
    "auto_strategy": "MAGICK_CLOUD_IMAGE_SOURCE_AUTO_STRATEGY",
    "unsplash_base_url": "MAGICK_CLOUD_IMAGE_SOURCE_UNSPLASH_BASE_URL",
    "unsplash_access_key": "MAGICK_CLOUD_IMAGE_SOURCE_UNSPLASH_ACCESS_KEY",
    "pixabay_base_url": "MAGICK_CLOUD_IMAGE_SOURCE_PIXABAY_BASE_URL",
    "pixabay_api_key": "MAGICK_CLOUD_IMAGE_SOURCE_PIXABAY_API_KEY",
    "pexels_base_url": "MAGICK_CLOUD_IMAGE_SOURCE_PEXELS_BASE_URL",
    "pexels_api_key": "MAGICK_CLOUD_IMAGE_SOURCE_PEXELS_API_KEY",
    "timeout_seconds": "MAGICK_CLOUD_IMAGE_SOURCE_TIMEOUT_SECONDS",
    "cost_per_query": "MAGICK_CLOUD_IMAGE_SOURCE_COST_PER_QUERY",
}

SECRET_FIELDS = {
    "unsplash_access_key",
    "pixabay_api_key",
    "pexels_api_key",
}


@dataclass(slots=True)
class ImageSourceAdminConfigService:
    settings: Settings

    def get_config(self) -> dict[str, Any]:
        provider_mode = str(self.settings.image_source_provider or "disabled")
        auto_strategy = str(self.settings.image_source_auto_strategy or "first_available")
        return {
            "provider_mode": provider_mode,
            "auto_strategy": auto_strategy,
            "env_path": str(self.settings.image_source_admin_env_path or ".env.local"),
            "requires_worker_restart_after_save": True,
            "providers": {
                "unsplash": self._provider_state(
                    provider_id="unsplash",
                    display_name="Unsplash",
                    enabled=provider_mode in {"unsplash", "auto"},
                    configured=bool(
                        str(self.settings.image_source_unsplash_access_key or "").strip()
                    ),
                    base_url=self.settings.image_source_unsplash_base_url,
                ),
                "pixabay": self._provider_state(
                    provider_id="pixabay",
                    display_name="Pixabay",
                    enabled=provider_mode in {"pixabay", "auto"},
                    configured=bool(str(self.settings.image_source_pixabay_api_key or "").strip()),
                    base_url=self.settings.image_source_pixabay_base_url,
                ),
                "pexels": self._provider_state(
                    provider_id="pexels",
                    display_name="Pexels",
                    enabled=provider_mode in {"pexels", "auto"},
                    configured=bool(str(self.settings.image_source_pexels_api_key or "").strip()),
                    base_url=self.settings.image_source_pexels_base_url,
                ),
            },
            "runtime": {
                "timeout_seconds": float(self.settings.image_source_timeout_seconds),
                "cost_per_query": float(self.settings.image_source_cost_per_query),
                "auto_strategy": auto_strategy,
            },
            "boundary": {
                "owner": "cloud_runtime",
                "wordpress_users_configure_provider_keys": False,
                "secret_exposure": "masked_status_only",
                "final_writes": "core_proposal_required",
            },
        }

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_payload(payload)
        current_env = _read_env_file(self._env_path())
        merged = dict(current_env)
        for field, env_key in ENV_KEYS.items():
            if field in SECRET_FIELDS:
                secret_value = str(normalized.get(field) or "").strip()
                clear_secret = bool(normalized.get(f"clear_{field}"))
                if clear_secret:
                    merged[env_key] = ""
                elif secret_value:
                    merged[env_key] = secret_value
                elif env_key not in merged:
                    merged[env_key] = ""
                continue
            merged[env_key] = str(normalized.get(field, "")).strip()

        _write_env_values(self._env_path(), merged)
        self._apply_to_settings(merged)
        return self.get_config()

    def _env_path(self) -> Path:
        return Path(str(self.settings.image_source_admin_env_path or ".env.local"))

    def _provider_state(
        self,
        *,
        provider_id: str,
        display_name: str,
        enabled: bool,
        configured: bool,
        base_url: str | None,
    ) -> dict[str, Any]:
        return {
            "provider_id": provider_id,
            "display_name": display_name,
            "enabled": enabled,
            "configured": configured,
            "status": "ready"
            if enabled and configured
            else ("configured" if configured else "missing_secret"),
            "base_url": str(base_url or ""),
            "secret": {
                "configured": configured,
                "display": "configured" if configured else "missing",
            },
        }

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = (
            str(payload.get("provider_mode") or self.settings.image_source_provider).strip().lower()
        )
        if provider not in PROVIDER_MODES:
            provider = "disabled"
        providers = _dict(payload.get("providers"))
        unsplash = _dict(providers.get("unsplash"))
        pixabay = _dict(providers.get("pixabay"))
        pexels = _dict(providers.get("pexels"))
        runtime = _dict(payload.get("runtime"))
        auto_strategy = (
            str(
                payload.get("auto_strategy")
                or runtime.get("auto_strategy")
                or self.settings.image_source_auto_strategy
                or "first_available"
            )
            .strip()
            .lower()
        )
        if auto_strategy not in {"first_available", "random", "parallel", "fast_first"}:
            auto_strategy = "first_available"
        return {
            "provider": provider,
            "auto_strategy": auto_strategy,
            "unsplash_base_url": _value(
                unsplash,
                "base_url",
                self.settings.image_source_unsplash_base_url,
            ),
            "unsplash_access_key": _value(unsplash, "secret", ""),
            "clear_unsplash_access_key": bool(unsplash.get("clear_secret")),
            "pixabay_base_url": _value(
                pixabay,
                "base_url",
                self.settings.image_source_pixabay_base_url,
            ),
            "pixabay_api_key": _value(pixabay, "secret", ""),
            "clear_pixabay_api_key": bool(pixabay.get("clear_secret")),
            "pexels_base_url": _value(
                pexels,
                "base_url",
                self.settings.image_source_pexels_base_url,
            ),
            "pexels_api_key": _value(pexels, "secret", ""),
            "clear_pexels_api_key": bool(pexels.get("clear_secret")),
            "timeout_seconds": _positive_float(
                runtime.get("timeout_seconds"),
                self.settings.image_source_timeout_seconds,
            ),
            "cost_per_query": _nonnegative_float(
                runtime.get("cost_per_query"),
                self.settings.image_source_cost_per_query,
            ),
        }

    def _apply_to_settings(self, env: dict[str, str]) -> None:
        self.settings.image_source_provider = env.get(ENV_KEYS["provider"], "disabled")
        self.settings.image_source_auto_strategy = env.get(
            ENV_KEYS["auto_strategy"],
            "first_available",
        )
        self.settings.image_source_unsplash_base_url = env.get(
            ENV_KEYS["unsplash_base_url"],
            "",
        )
        self.settings.image_source_unsplash_access_key = env.get(
            ENV_KEYS["unsplash_access_key"],
            "",
        )
        self.settings.image_source_pixabay_base_url = env.get(
            ENV_KEYS["pixabay_base_url"],
            "",
        )
        self.settings.image_source_pixabay_api_key = env.get(
            ENV_KEYS["pixabay_api_key"],
            "",
        )
        self.settings.image_source_pexels_base_url = env.get(
            ENV_KEYS["pexels_base_url"],
            "",
        )
        self.settings.image_source_pexels_api_key = env.get(
            ENV_KEYS["pexels_api_key"],
            "",
        )
        self.settings.image_source_timeout_seconds = _positive_float(
            env.get(ENV_KEYS["timeout_seconds"]),
            15,
        )
        self.settings.image_source_cost_per_query = _nonnegative_float(
            env.get(ENV_KEYS["cost_per_query"]),
            0,
        )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_values(path: Path, values: dict[str, str]) -> None:
    existing_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated_keys = set(ENV_KEYS.values())
    output: list[str] = []
    seen: set[str] = set()
    for line in existing_lines:
        if "=" not in line or line.lstrip().startswith("#"):
            output.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updated_keys:
            output.append(f"{key}={values.get(key, '')}")
            seen.add(key)
        else:
            output.append(line)
    missing = [key for key in ENV_KEYS.values() if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Cloud-managed Image Sources. WordPress users never provide provider keys.")
        for key in missing:
            output.append(f"{key}={values.get(key, '')}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _value(payload: dict[str, Any], key: str, default: Any) -> str:
    return str(payload.get(key) if key in payload else default).strip()


def _positive_float(value: Any, default: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default or 0)
    return max(0.001, number)


def _nonnegative_float(value: Any, default: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default or 0)
    return max(0.0, number)
