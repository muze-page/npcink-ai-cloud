from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.domain.service_settings import ServiceSettingsAdminError, ServiceSettingsAdminService

DEFAULT_ENV_FILES = (".env", ".env.local", ".env.deploy")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import Portal service .env values into service_settings."
    )
    parser.add_argument(
        "--env-file",
        action="append",
        default=[],
        help="Env file to read. Defaults to .env, .env.local, and .env.deploy when present.",
    )
    return parser.parse_args()


def load_service_settings_env(env_files: list[str] | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    selected_files = tuple(env_files or DEFAULT_ENV_FILES)
    for env_file in selected_files:
        path = Path(env_file)
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            key, value = _parse_env_line(raw_line)
            if key:
                result[key] = value

    for key, value in os.environ.items():
        if _service_setting_env_key(key):
            result[key] = value
    return result


def import_service_settings_from_env(
    *,
    settings: Settings,
    env: dict[str, str],
) -> dict[str, Any]:
    service = ServiceSettingsAdminService(settings.database_url, settings)
    imported: list[str] = []
    skipped: list[dict[str, str]] = []

    public_base_url = _env_value(env, "PORTAL_PUBLIC_BASE_URL")
    if public_base_url:
        _save(
            service.save_portal_public,
            {"enabled": True, "public_base_url": public_base_url},
            imported=imported,
            skipped=skipped,
            setting_id="portal_public",
        )
    else:
        skipped.append({"setting_id": "portal_public", "reason": "missing_env_value"})

    qq_client_id = _env_value(env, "PORTAL_QQ_CLIENT_ID")
    qq_client_secret = _env_value(env, "PORTAL_QQ_CLIENT_SECRET")
    qq_redirect_uri = _env_value(env, "PORTAL_QQ_REDIRECT_URI")
    if qq_client_id or qq_client_secret or qq_redirect_uri:
        _save(
            service.save_qq_login,
            {
                "enabled": True,
                "client_id": qq_client_id,
                "client_secret": qq_client_secret,
                "redirect_uri": qq_redirect_uri,
                "scope": _env_value(env, "PORTAL_QQ_SCOPE") or "get_user_info",
                "timeout_seconds": _env_value(env, "PORTAL_QQ_TIMEOUT_SECONDS") or "10",
            },
            imported=imported,
            skipped=skipped,
            setting_id="portal_qq_login",
        )
    else:
        skipped.append({"setting_id": "portal_qq_login", "reason": "missing_env_value"})

    email_host = _env_value(env, "PORTAL_EMAIL_SMTP_HOST")
    email_from = _env_value(env, "PORTAL_EMAIL_FROM_EMAIL")
    if email_host or email_from:
        _save(
            service.save_email,
            {
                "enabled": True,
                "smtp_host": email_host,
                "smtp_port": _env_value(env, "PORTAL_EMAIL_SMTP_PORT") or "465",
                "smtp_username": _env_value(env, "PORTAL_EMAIL_SMTP_USERNAME"),
                "smtp_password": _env_value(env, "PORTAL_EMAIL_SMTP_PASSWORD"),
                "smtp_use_ssl": _bool_env(
                    _env_value(env, "PORTAL_EMAIL_SMTP_USE_SSL"),
                    default=True,
                ),
                "smtp_use_starttls": _bool_env(
                    _env_value(env, "PORTAL_EMAIL_SMTP_USE_STARTTLS"),
                    default=False,
                ),
                "smtp_timeout_seconds": _env_value(env, "PORTAL_EMAIL_SMTP_TIMEOUT_SECONDS")
                or "20",
                "from_email": email_from,
                "from_name": _env_value(env, "PORTAL_EMAIL_FROM_NAME"),
                "reply_to": _env_value(env, "PORTAL_EMAIL_REPLY_TO"),
            },
            imported=imported,
            skipped=skipped,
            setting_id="portal_email",
        )
    else:
        skipped.append({"setting_id": "portal_email", "reason": "missing_env_value"})

    return {
        "surface": "service_settings_env_import",
        "imported": imported,
        "skipped": skipped,
        "credential_value_exposure": "none",
        "env_fallback": "disabled",
    }


def _save(
    save_fn: Any,
    payload: dict[str, Any],
    *,
    imported: list[str],
    skipped: list[dict[str, str]],
    setting_id: str,
) -> None:
    try:
        result = save_fn(payload)
    except ServiceSettingsAdminError as error:
        skipped.append({"setting_id": setting_id, "reason": error.error_code})
        return
    imported.append(str(result.get("setting_id") or setting_id))


def _parse_env_line(raw_line: str) -> tuple[str, str]:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return "", ""
    if line.startswith("export "):
        line = line.removeprefix("export ").strip()
    key, value = line.split("=", 1)
    key = key.strip()
    if not _service_setting_env_key(key):
        return "", ""
    return key, _strip_env_value(value)


def _service_setting_env_key(key: str) -> bool:
    return (
        key == "NPCINK_CLOUD_PORTAL_PUBLIC_BASE_URL"
        or key.startswith("NPCINK_CLOUD_PORTAL_QQ_")
        or key.startswith("NPCINK_CLOUD_PORTAL_EMAIL_")
    )


def _env_value(env: dict[str, str], suffix: str) -> str:
    return _string(env.get(f"NPCINK_CLOUD_{suffix}"))


def _strip_env_value(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _string(value: object) -> str:
    return str(value or "").strip()


def _bool_env(value: object, *, default: bool) -> bool:
    normalized = _string(value).lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def main() -> None:
    args = parse_args()
    settings = Settings()
    result = import_service_settings_from_env(
        settings=settings,
        env=load_service_settings_env(args.env_file),
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))


if __name__ == "__main__":
    main()
