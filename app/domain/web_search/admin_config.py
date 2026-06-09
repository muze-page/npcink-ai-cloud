from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from app.core.config import Settings

PROVIDER_IDS = ("tavily", "bocha", "jina_reader", "apify")
PROVIDER_MODES = ("disabled", "auto", "tavily", "bocha", "apify")

ENV_KEYS = {
    "provider": "MAGICK_CLOUD_WEB_SEARCH_PROVIDER",
    "tavily_base_url": "MAGICK_CLOUD_WEB_SEARCH_TAVILY_BASE_URL",
    "tavily_api_key": "MAGICK_CLOUD_WEB_SEARCH_TAVILY_API_KEY",
    "tavily_api_keys": "MAGICK_CLOUD_WEB_SEARCH_TAVILY_API_KEYS",
    "tavily_timeout_seconds": "MAGICK_CLOUD_WEB_SEARCH_TAVILY_TIMEOUT_SECONDS",
    "tavily_cost_per_query": "MAGICK_CLOUD_WEB_SEARCH_TAVILY_COST_PER_QUERY",
    "bocha_base_url": "MAGICK_CLOUD_WEB_SEARCH_BOCHA_BASE_URL",
    "bocha_api_key": "MAGICK_CLOUD_WEB_SEARCH_BOCHA_API_KEY",
    "bocha_timeout_seconds": "MAGICK_CLOUD_WEB_SEARCH_BOCHA_TIMEOUT_SECONDS",
    "bocha_cost_per_query": "MAGICK_CLOUD_WEB_SEARCH_BOCHA_COST_PER_QUERY",
    "jina_reader_enabled": "MAGICK_CLOUD_WEB_SEARCH_JINA_READER_ENABLED",
    "jina_reader_base_url": "MAGICK_CLOUD_WEB_SEARCH_JINA_READER_BASE_URL",
    "jina_reader_api_key": "MAGICK_CLOUD_WEB_SEARCH_JINA_READER_API_KEY",
    "jina_reader_timeout_seconds": "MAGICK_CLOUD_WEB_SEARCH_JINA_READER_TIMEOUT_SECONDS",
    "jina_reader_max_pages": "MAGICK_CLOUD_WEB_SEARCH_JINA_READER_MAX_PAGES",
    "jina_reader_cost_per_page": "MAGICK_CLOUD_WEB_SEARCH_JINA_READER_COST_PER_PAGE",
    "apify_base_url": "MAGICK_CLOUD_WEB_SEARCH_APIFY_BASE_URL",
    "apify_api_token": "MAGICK_CLOUD_WEB_SEARCH_APIFY_API_TOKEN",
    "apify_actor_id": "MAGICK_CLOUD_WEB_SEARCH_APIFY_ACTOR_ID",
    "apify_timeout_seconds": "MAGICK_CLOUD_WEB_SEARCH_APIFY_TIMEOUT_SECONDS",
    "apify_cost_per_query": "MAGICK_CLOUD_WEB_SEARCH_APIFY_COST_PER_QUERY",
}

SECRET_FIELDS = {
    "tavily_api_key",
    "tavily_api_keys",
    "bocha_api_key",
    "jina_reader_api_key",
    "apify_api_token",
}


@dataclass(slots=True)
class WebSearchAdminConfigService:
    settings: Settings

    def get_config(self) -> dict[str, Any]:
        return {
            "provider_mode": str(self.settings.web_search_provider or "disabled"),
            "env_path": str(self.settings.web_search_admin_env_path or ".env.local"),
            "requires_worker_restart_after_save": True,
            "providers": {
                "tavily": self._provider_state(
                    provider_id="tavily",
                    display_name="Tavily",
                    enabled=str(self.settings.web_search_provider or "") in {"tavily", "auto"},
                    configured=bool(_secret_pool(self.settings.web_search_tavily_api_keys))
                    or bool(str(self.settings.web_search_tavily_api_key or "").strip()),
                    base_url=self.settings.web_search_tavily_base_url,
                    timeout_seconds=self.settings.web_search_tavily_timeout_seconds,
                    cost=self.settings.web_search_tavily_cost_per_query,
                    extra={
                        "key_pool_count": len(
                            _secret_pool(self.settings.web_search_tavily_api_keys)
                        )
                    },
                ),
                "bocha": self._provider_state(
                    provider_id="bocha",
                    display_name="Bocha",
                    enabled=str(self.settings.web_search_provider or "") in {"bocha", "auto"},
                    configured=bool(str(self.settings.web_search_bocha_api_key or "").strip()),
                    base_url=self.settings.web_search_bocha_base_url,
                    timeout_seconds=self.settings.web_search_bocha_timeout_seconds,
                    cost=self.settings.web_search_bocha_cost_per_query,
                ),
                "jina_reader": self._provider_state(
                    provider_id="jina_reader",
                    display_name="Jina Reader",
                    enabled=bool(self.settings.web_search_jina_reader_enabled),
                    configured=bool(
                        str(self.settings.web_search_jina_reader_api_key or "").strip()
                    ),
                    base_url=self.settings.web_search_jina_reader_base_url,
                    timeout_seconds=self.settings.web_search_jina_reader_timeout_seconds,
                    cost=self.settings.web_search_jina_reader_cost_per_page,
                    extra={"max_pages": int(self.settings.web_search_jina_reader_max_pages or 1)},
                ),
                "apify": self._provider_state(
                    provider_id="apify",
                    display_name="Apify",
                    enabled=str(self.settings.web_search_provider or "") in {"apify", "auto"},
                    configured=bool(str(self.settings.web_search_apify_api_token or "").strip()),
                    base_url=self.settings.web_search_apify_base_url,
                    timeout_seconds=self.settings.web_search_apify_timeout_seconds,
                    cost=self.settings.web_search_apify_cost_per_query,
                    extra={"actor_id": str(self.settings.web_search_apify_actor_id or "")},
                ),
            },
            "boundary": {
                "owner": "cloud_runtime",
                "wordpress_users_configure_provider_keys": False,
                "secret_exposure": "masked_status_only",
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
        return Path(str(self.settings.web_search_admin_env_path or ".env.local"))

    def _provider_state(
        self,
        *,
        provider_id: str,
        display_name: str,
        enabled: bool,
        configured: bool,
        base_url: str | None,
        timeout_seconds: float,
        cost: float,
        extra: dict[str, Any] | None = None,
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
            "timeout_seconds": float(timeout_seconds),
            "cost": float(cost),
            "secret": {
                "configured": configured,
                "display": "configured" if configured else "missing",
            },
            **(extra or {}),
        }

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = (
            str(payload.get("provider_mode") or self.settings.web_search_provider).strip().lower()
        )
        if provider not in PROVIDER_MODES:
            provider = "disabled"
        raw_providers = payload.get("providers")
        providers: dict[str, Any] = raw_providers if isinstance(raw_providers, dict) else {}
        tavily = _dict(providers.get("tavily"))
        bocha = _dict(providers.get("bocha"))
        jina = _dict(providers.get("jina_reader"))
        apify = _dict(providers.get("apify"))
        return {
            "provider": provider,
            "tavily_base_url": _value(tavily, "base_url", self.settings.web_search_tavily_base_url),
            "tavily_api_key": _value(tavily, "secret", ""),
            "clear_tavily_api_key": bool(tavily.get("clear_secret")),
            "tavily_api_keys": _secret_pool_value(tavily, "secret_pool"),
            "clear_tavily_api_keys": bool(tavily.get("clear_secret_pool")),
            "tavily_timeout_seconds": _positive_float(
                tavily.get("timeout_seconds"), self.settings.web_search_tavily_timeout_seconds
            ),
            "tavily_cost_per_query": _nonnegative_float(
                tavily.get("cost"), self.settings.web_search_tavily_cost_per_query
            ),
            "bocha_base_url": _value(bocha, "base_url", self.settings.web_search_bocha_base_url),
            "bocha_api_key": _value(bocha, "secret", ""),
            "clear_bocha_api_key": bool(bocha.get("clear_secret")),
            "bocha_timeout_seconds": _positive_float(
                bocha.get("timeout_seconds"), self.settings.web_search_bocha_timeout_seconds
            ),
            "bocha_cost_per_query": _nonnegative_float(
                bocha.get("cost"), self.settings.web_search_bocha_cost_per_query
            ),
            "jina_reader_enabled": "true" if bool(jina.get("enabled")) else "false",
            "jina_reader_base_url": _value(
                jina, "base_url", self.settings.web_search_jina_reader_base_url
            ),
            "jina_reader_api_key": _value(jina, "secret", ""),
            "clear_jina_reader_api_key": bool(jina.get("clear_secret")),
            "jina_reader_timeout_seconds": _positive_float(
                jina.get("timeout_seconds"), self.settings.web_search_jina_reader_timeout_seconds
            ),
            "jina_reader_max_pages": max(
                1,
                min(5, _int(jina.get("max_pages"), self.settings.web_search_jina_reader_max_pages)),
            ),
            "jina_reader_cost_per_page": _nonnegative_float(
                jina.get("cost"), self.settings.web_search_jina_reader_cost_per_page
            ),
            "apify_base_url": _value(apify, "base_url", self.settings.web_search_apify_base_url),
            "apify_api_token": _value(apify, "secret", ""),
            "clear_apify_api_token": bool(apify.get("clear_secret")),
            "apify_actor_id": _value(apify, "actor_id", self.settings.web_search_apify_actor_id),
            "apify_timeout_seconds": _positive_float(
                apify.get("timeout_seconds"), self.settings.web_search_apify_timeout_seconds
            ),
            "apify_cost_per_query": _nonnegative_float(
                apify.get("cost"), self.settings.web_search_apify_cost_per_query
            ),
        }

    def _apply_to_settings(self, env: dict[str, str]) -> None:
        self.settings.web_search_provider = env.get(ENV_KEYS["provider"], "disabled")
        self.settings.web_search_tavily_base_url = env.get(ENV_KEYS["tavily_base_url"], "")
        self.settings.web_search_tavily_api_key = env.get(ENV_KEYS["tavily_api_key"], "")
        self.settings.web_search_tavily_api_keys = env.get(ENV_KEYS["tavily_api_keys"], "")
        self.settings.web_search_tavily_timeout_seconds = _positive_float(
            env.get(ENV_KEYS["tavily_timeout_seconds"]), 15
        )
        self.settings.web_search_tavily_cost_per_query = _nonnegative_float(
            env.get(ENV_KEYS["tavily_cost_per_query"]), 0
        )
        self.settings.web_search_bocha_base_url = env.get(ENV_KEYS["bocha_base_url"], "")
        self.settings.web_search_bocha_api_key = env.get(ENV_KEYS["bocha_api_key"], "")
        self.settings.web_search_bocha_timeout_seconds = _positive_float(
            env.get(ENV_KEYS["bocha_timeout_seconds"]), 15
        )
        self.settings.web_search_bocha_cost_per_query = _nonnegative_float(
            env.get(ENV_KEYS["bocha_cost_per_query"]), 0
        )
        self.settings.web_search_jina_reader_enabled = _bool(
            env.get(ENV_KEYS["jina_reader_enabled"])
        )
        self.settings.web_search_jina_reader_base_url = env.get(
            ENV_KEYS["jina_reader_base_url"], ""
        )
        self.settings.web_search_jina_reader_api_key = env.get(ENV_KEYS["jina_reader_api_key"], "")
        self.settings.web_search_jina_reader_timeout_seconds = _positive_float(
            env.get(ENV_KEYS["jina_reader_timeout_seconds"]), 15
        )
        self.settings.web_search_jina_reader_max_pages = _int(
            env.get(ENV_KEYS["jina_reader_max_pages"]), 2
        )
        self.settings.web_search_jina_reader_cost_per_page = _nonnegative_float(
            env.get(ENV_KEYS["jina_reader_cost_per_page"]), 0
        )
        self.settings.web_search_apify_base_url = env.get(ENV_KEYS["apify_base_url"], "")
        self.settings.web_search_apify_api_token = env.get(ENV_KEYS["apify_api_token"], "")
        self.settings.web_search_apify_actor_id = env.get(ENV_KEYS["apify_actor_id"], "")
        self.settings.web_search_apify_timeout_seconds = _positive_float(
            env.get(ENV_KEYS["apify_timeout_seconds"]), 30
        )
        self.settings.web_search_apify_cost_per_query = _nonnegative_float(
            env.get(ENV_KEYS["apify_cost_per_query"]), 0
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
        output.append("# Cloud-managed Web Search. WordPress users never provide provider keys.")
        for key in missing:
            output.append(f"{key}={values.get(key, '')}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _value(payload: dict[str, Any], key: str, default: Any) -> str:
    value = str(payload.get(key) if key in payload else default).strip()
    return value


def _secret_pool(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = re.split(r"[\s,;]+", str(value or ""))
    keys: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = str(raw).strip()
        if not item or item in seen:
            continue
        keys.append(item)
        seen.add(item)
    return keys


def _secret_pool_value(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        return ""
    return ",".join(_secret_pool(payload.get(key)))


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


def _int(value: Any, default: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default or 0)


def _bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
