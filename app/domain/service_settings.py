from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select

from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ServiceSetting
from app.core.secrets import (
    decrypt_service_setting_secret,
    encrypt_service_setting_secret,
)

SERVICE_SETTING_PORTAL_PUBLIC = "portal_public"
SERVICE_SETTING_QQ_LOGIN = "portal_qq_login"
SERVICE_SETTING_PORTAL_EMAIL = "portal_email"
SERVICE_SETTING_PAYMENT_ALIPAY = "payment_alipay"

SERVICE_SETTING_KIND_PORTAL = "portal"
SERVICE_SETTING_QQ_OPEN_CALLBACK_PATH = "/open/auth/qq/callback"
SERVICE_SETTING_ALIPAY_NOTIFY_PATH = "/open/payments/alipay/notify"
SERVICE_SETTING_ALIPAY_RETURN_PATH = "/open/payments/alipay/return"

STATUS_READY = "ready"
STATUS_DISABLED = "disabled"
STATUS_MISSING_CONFIG = "missing_config"
STATUS_ERROR = "error"


class ServiceSettingsAdminError(ValueError):
    def __init__(self, error_code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class ServiceSettingsAdminService:
    database_url: str
    settings: Settings

    def get_settings(self) -> dict[str, Any]:
        with get_session(self.database_url) as session:
            rows = {
                row.setting_id: row
                for row in session.scalars(
                    select(ServiceSetting).where(
                        ServiceSetting.setting_id.in_(
                            [
                                SERVICE_SETTING_PORTAL_PUBLIC,
                                SERVICE_SETTING_QQ_LOGIN,
                                SERVICE_SETTING_PORTAL_EMAIL,
                                SERVICE_SETTING_PAYMENT_ALIPAY,
                            ]
                        )
                    )
                )
            }
        return {
            "surface": "admin_service_settings",
            "settings": {
                "portal_public": self._serialize(
                    rows.get(SERVICE_SETTING_PORTAL_PUBLIC),
                    setting_id=SERVICE_SETTING_PORTAL_PUBLIC,
                ),
                "qq_login": self._serialize(
                    rows.get(SERVICE_SETTING_QQ_LOGIN),
                    setting_id=SERVICE_SETTING_QQ_LOGIN,
                ),
                "portal_email": self._serialize(
                    rows.get(SERVICE_SETTING_PORTAL_EMAIL),
                    setting_id=SERVICE_SETTING_PORTAL_EMAIL,
                ),
                "alipay_payment": self._serialize(
                    rows.get(SERVICE_SETTING_PAYMENT_ALIPAY),
                    setting_id=SERVICE_SETTING_PAYMENT_ALIPAY,
                ),
            },
            "env_fallback": "disabled",
            "boundary": _boundary(),
        }

    def save_portal_public(self, payload: dict[str, Any]) -> dict[str, Any]:
        public_base_url = _normalize_public_base_url(_string(payload.get("public_base_url")))
        if not public_base_url:
            raise ServiceSettingsAdminError(
                "service_settings.portal_public_base_url_invalid",
                "portal public base URL is invalid",
            )
        row = self._save(
            setting_id=SERVICE_SETTING_PORTAL_PUBLIC,
            config={"public_base_url": public_base_url},
            secrets={},
            enabled=bool(payload.get("enabled", True)),
            required_secret_keys=[],
        )
        return self._serialize(row)

    def save_qq_login(self, payload: dict[str, Any]) -> dict[str, Any]:
        client_id = _string(payload.get("client_id"))
        if not client_id:
            raise ServiceSettingsAdminError(
                "service_settings.qq_client_id_required",
                "QQ client id is required",
            )
        public_base_url = resolve_portal_public_base_url(self.database_url, self.settings)
        redirect_uri = _string(payload.get("redirect_uri"))
        if not redirect_uri:
            redirect_uri = _default_qq_redirect_uri(public_base_url)
        if not _qq_redirect_uri_allowed(
            redirect_uri,
            public_base_url=public_base_url,
            environment=self.settings.environment,
        ):
            raise ServiceSettingsAdminError(
                "service_settings.qq_redirect_uri_invalid",
                "QQ redirect URI must match the configured portal public base URL",
            )
        timeout_seconds = _positive_float(payload.get("timeout_seconds"), default=10.0)
        row = self._save(
            setting_id=SERVICE_SETTING_QQ_LOGIN,
            config={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": _string(payload.get("scope")) or "get_user_info",
                "timeout_seconds": timeout_seconds,
            },
            secrets={"client_secret": payload.get("client_secret")},
            enabled=bool(payload.get("enabled", True)),
            required_secret_keys=["client_secret"],
        )
        return self._serialize(row)

    def save_email(self, payload: dict[str, Any]) -> dict[str, Any]:
        host = _string(payload.get("smtp_host"))
        from_email = _string(payload.get("from_email")).lower()
        if not host:
            raise ServiceSettingsAdminError(
                "service_settings.email_smtp_host_required",
                "SMTP host is required",
            )
        if not from_email or "@" not in from_email:
            raise ServiceSettingsAdminError(
                "service_settings.email_from_email_invalid",
                "a valid from email is required",
            )
        use_ssl = _bool(payload.get("smtp_use_ssl"), default=True)
        use_starttls = _bool(payload.get("smtp_use_starttls"), default=False)
        if use_ssl and use_starttls:
            raise ServiceSettingsAdminError(
                "service_settings.email_tls_mode_invalid",
                "SMTP cannot enable both SSL and STARTTLS",
            )
        username = _string(payload.get("smtp_username"))
        password_value = payload.get("smtp_password")
        enabled = bool(payload.get("enabled", True))
        if username and password_value is None and enabled:
            existing = _load_service_setting(self.database_url, SERVICE_SETTING_PORTAL_EMAIL)
            try:
                existing_password = _decrypt_secret(
                    existing,
                    "smtp_password",
                    settings=self.settings,
                )
            except RuntimeError as error:
                raise ServiceSettingsAdminError(
                    "service_settings.email_password_required",
                    (
                        "Saved SMTP password cannot be read. "
                        "Re-enter the SMTP password and save again."
                    ),
                ) from error
            if not existing_password:
                raise ServiceSettingsAdminError(
                    "service_settings.email_password_required",
                    "SMTP password is required when username is configured",
                )
            password_value = existing_password
        if not username and (password_value is not None and _string(password_value)):
            raise ServiceSettingsAdminError(
                "service_settings.email_username_required",
                "SMTP username is required when password is configured",
            )
        if not username and password_value is None:
            password_value = ""
        row = self._save(
            setting_id=SERVICE_SETTING_PORTAL_EMAIL,
            config={
                "smtp_host": host,
                "smtp_port": _positive_int(payload.get("smtp_port"), default=465),
                "smtp_username": username,
                "smtp_use_ssl": use_ssl,
                "smtp_use_starttls": use_starttls,
                "smtp_timeout_seconds": _positive_float(
                    payload.get("smtp_timeout_seconds"),
                    default=20.0,
                ),
                "from_email": from_email,
                "from_name": _string(payload.get("from_name")),
                "reply_to": _string(payload.get("reply_to")).lower(),
            },
            secrets={"smtp_password": password_value},
            enabled=enabled,
            required_secret_keys=["smtp_password"] if username else [],
        )
        return self._serialize(row)

    def save_alipay_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        enabled = bool(payload.get("enabled", True))
        public_base_url = resolve_portal_public_base_url(self.database_url, self.settings)
        app_id = _string(payload.get("app_id"))
        gateway_url = _normalize_url(
            _string(payload.get("gateway_url")) or "https://openapi.alipay.com/gateway.do"
        )
        notify_url = _string(payload.get("notify_url")) or _default_alipay_notify_url(
            public_base_url
        )
        return_url = _string(payload.get("return_url")) or _default_alipay_return_url(
            public_base_url
        )
        if enabled:
            if not app_id:
                raise ServiceSettingsAdminError(
                    "service_settings.alipay_app_id_required",
                    "Alipay app id is required",
                )
            if not gateway_url:
                raise ServiceSettingsAdminError(
                    "service_settings.alipay_gateway_url_invalid",
                    "Alipay gateway URL is invalid",
                )
            if not _callback_url_allowed(
                notify_url,
                public_base_url=public_base_url,
                expected_path=SERVICE_SETTING_ALIPAY_NOTIFY_PATH,
                environment=self.settings.environment,
            ):
                raise ServiceSettingsAdminError(
                    "service_settings.alipay_notify_url_invalid",
                    "Alipay notify URL must match the configured portal public base URL",
                )
            if not _callback_url_allowed(
                return_url,
                public_base_url=public_base_url,
                expected_path=SERVICE_SETTING_ALIPAY_RETURN_PATH,
                environment=self.settings.environment,
            ):
                raise ServiceSettingsAdminError(
                    "service_settings.alipay_return_url_invalid",
                    "Alipay return URL must match the configured portal public base URL",
                )
        existing = _load_service_setting(self.database_url, SERVICE_SETTING_PAYMENT_ALIPAY)
        existing_private_key = _decrypt_secret(existing, "private_key", settings=self.settings)
        existing_public_key = _decrypt_secret(existing, "public_key", settings=self.settings)
        private_key_value = payload.get("private_key")
        public_key_value = payload.get("public_key")
        if enabled and private_key_value is None and not existing_private_key:
            raise ServiceSettingsAdminError(
                "service_settings.alipay_private_key_required",
                "Alipay application private key is required",
            )
        if enabled and public_key_value is None and not existing_public_key:
            raise ServiceSettingsAdminError(
                "service_settings.alipay_public_key_required",
                "Alipay public key is required",
            )
        if private_key_value is None and existing_private_key:
            private_key_value = existing_private_key
        if public_key_value is None and existing_public_key:
            public_key_value = existing_public_key
        row = self._save(
            setting_id=SERVICE_SETTING_PAYMENT_ALIPAY,
            config={
                "app_id": app_id,
                "gateway_url": gateway_url,
                "notify_url": notify_url,
                "return_url": return_url,
                "sign_type": "RSA2",
                "payment_product_code": "FAST_INSTANT_TRADE_PAY",
            },
            secrets={
                "private_key": private_key_value,
                "public_key": public_key_value,
            },
            enabled=enabled,
            required_secret_keys=["private_key", "public_key"] if enabled else [],
        )
        return self._serialize(row)

    def test_qq_login(self) -> dict[str, Any]:
        row = _load_service_setting(self.database_url, SERVICE_SETTING_QQ_LOGIN)
        config = resolve_portal_qq_runtime_config(self.database_url, self.settings)
        status = STATUS_READY if config.get("configured") else STATUS_MISSING_CONFIG
        message = (
            "QQ login configuration is ready"
            if status == STATUS_READY
            else "QQ login configuration is incomplete"
        )
        self._record_test_result(
            row,
            status=status,
            error_code="",
            message="" if status == STATUS_READY else message,
        )
        return {
            "surface": "admin_service_settings_test",
            "setting_id": SERVICE_SETTING_QQ_LOGIN,
            "status": status,
            "message": message,
            "redirect_uri": _string(config.get("redirect_uri")),
            "credential_value_exposure": "none",
        }

    def test_alipay_payment(self) -> dict[str, Any]:
        row = _load_service_setting(self.database_url, SERVICE_SETTING_PAYMENT_ALIPAY)
        config = resolve_alipay_payment_runtime_config(self.database_url, self.settings)
        if not config.get("configured"):
            message = "Alipay payment configuration is incomplete"
            self._record_test_result(
                row,
                status=STATUS_MISSING_CONFIG,
                error_code="service_settings.alipay_not_configured",
                message=message,
            )
            return {
                "surface": "admin_service_settings_test",
                "setting_id": SERVICE_SETTING_PAYMENT_ALIPAY,
                "status": STATUS_MISSING_CONFIG,
                "message": message,
                "notify_url": _string(config.get("notify_url")),
                "return_url": _string(config.get("return_url")),
                "credential_value_exposure": "none",
            }
        try:
            from app.domain.commercial.payment_gateways import validate_alipay_gateway_config

            validate_alipay_gateway_config(config)
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._record_test_result(
                row,
                status=STATUS_ERROR,
                error_code="service_settings.alipay_config_invalid",
                message=message,
            )
            raise ServiceSettingsAdminError(
                "service_settings.alipay_config_invalid",
                message,
                status_code=400,
            ) from error
        self._record_test_result(row, status=STATUS_READY, error_code="", message="")
        return {
            "surface": "admin_service_settings_test",
            "setting_id": SERVICE_SETTING_PAYMENT_ALIPAY,
            "status": STATUS_READY,
            "message": "Alipay payment configuration is ready",
            "notify_url": _string(config.get("notify_url")),
            "return_url": _string(config.get("return_url")),
            "credential_value_exposure": "none",
        }

    def test_email(self, *, recipient_email: str, project_name: str) -> dict[str, Any]:
        normalized_email = _string(recipient_email).lower()
        if not normalized_email or "@" not in normalized_email:
            raise ServiceSettingsAdminError(
                "service_settings.test_email_invalid",
                "a valid recipient email is required",
            )
        row = _load_service_setting(self.database_url, SERVICE_SETTING_PORTAL_EMAIL)
        config = resolve_portal_email_runtime_config(self.database_url, self.settings)
        if not config.get("configured"):
            self._record_test_result(
                row,
                status=STATUS_MISSING_CONFIG,
                error_code="service_settings.email_not_configured",
                message="portal email delivery is not configured",
            )
            raise ServiceSettingsAdminError(
                "service_settings.email_not_configured",
                "portal email delivery is not configured",
                status_code=503,
            )
        try:
            from app.adapters.notifications.smtp import build_portal_email_sender_from_config

            sender = build_portal_email_sender_from_config(config)
            if sender is None:
                raise RuntimeError("portal email delivery is not configured")
            public_base_url = resolve_portal_public_base_url(self.database_url, self.settings)
            sender.send_test_email(
                recipient_email=normalized_email,
                project_name=project_name,
                portal_url=f"{public_base_url.rstrip('/')}/portal/login"
                if public_base_url
                else "/portal/login",
            )
        except Exception as error:
            message = str(error) or error.__class__.__name__
            self._record_test_result(
                row,
                status=STATUS_ERROR,
                error_code="service_settings.email_delivery_failed",
                message=message,
            )
            raise ServiceSettingsAdminError(
                "service_settings.email_delivery_failed",
                message,
                status_code=502,
            ) from error

        self._record_test_result(row, status=STATUS_READY, error_code="", message="")
        return {
            "surface": "admin_service_settings_test",
            "setting_id": SERVICE_SETTING_PORTAL_EMAIL,
            "status": STATUS_READY,
            "recipient_email": normalized_email,
            "credential_value_exposure": "none",
        }

    def preview_email(
        self,
        *,
        preview_type: str,
        project_name: str,
        locale: str,
        from_name: str = "",
        from_email: str = "",
    ) -> dict[str, Any]:
        from app.adapters.notifications.smtp import build_portal_email_preview

        row = _load_service_setting(self.database_url, SERVICE_SETTING_PORTAL_EMAIL)
        config = _dict(row.config_json) if row is not None else {}
        public_base_url = resolve_portal_public_base_url(self.database_url, self.settings)
        preview = build_portal_email_preview(
            preview_type=preview_type,
            project_name=project_name,
            locale=locale,
            portal_url=f"{public_base_url.rstrip('/')}/portal/login"
            if public_base_url
            else "/portal/login",
        )
        recommended_from_name = "Npcink AI Cloud"
        resolved_from_name = _string(from_name) or _string(config.get("from_name"))
        resolved_from_email = _string(from_email) or _string(config.get("from_email"))
        return {
            "surface": "admin_service_settings_email_preview",
            "setting_id": SERVICE_SETTING_PORTAL_EMAIL,
            "preview_type": preview["preview_type"],
            "subject": preview["subject"],
            "text": preview["text"],
            "html": preview["html"],
            "from_name": resolved_from_name or recommended_from_name,
            "from_email": resolved_from_email or "auth@npc.ink",
            "recommended_from_name": recommended_from_name,
            "credential_value_exposure": "none",
        }

    def _save(
        self,
        *,
        setting_id: str,
        config: dict[str, Any],
        secrets: dict[str, Any],
        enabled: bool,
        required_secret_keys: list[str],
    ) -> ServiceSetting:
        now = datetime.now(UTC)
        with get_session(self.database_url) as session:
            row = session.get(ServiceSetting, setting_id)
            if row is None:
                row = ServiceSetting(
                    setting_id=setting_id,
                    setting_kind=SERVICE_SETTING_KIND_PORTAL,
                    enabled=enabled,
                    config_json={},
                    secret_ciphertext_json={},
                    status=STATUS_MISSING_CONFIG,
                    last_tested_at=None,
                    last_error_code=None,
                    last_error_message=None,
                    metadata_json={},
                )
                session.add(row)
            secret_ciphertexts = dict(_dict(row.secret_ciphertext_json))
            for key, raw_value in secrets.items():
                if raw_value is None:
                    continue
                value = _string(raw_value)
                if value:
                    secret_ciphertexts[key] = encrypt_service_setting_secret(
                        value,
                        settings=self.settings,
                    )
                else:
                    secret_ciphertexts.pop(key, None)
            row.setting_kind = SERVICE_SETTING_KIND_PORTAL
            row.enabled = enabled
            row.config_json = config
            row.secret_ciphertext_json = secret_ciphertexts
            row.status = _setting_status(
                enabled=enabled,
                config=config,
                secret_ciphertexts=secret_ciphertexts,
                required_secret_keys=required_secret_keys,
            )
            row.last_error_code = None
            row.last_error_message = None
            row.updated_at = now
            session.commit()
            session.refresh(row)
            return row

    def _record_test_result(
        self,
        row: ServiceSetting | None,
        *,
        status: str,
        error_code: str,
        message: str,
    ) -> None:
        if row is None:
            return
        with get_session(self.database_url) as session:
            current = session.get(ServiceSetting, row.setting_id)
            if current is None:
                return
            current.last_tested_at = datetime.now(UTC)
            current.status = status
            current.last_error_code = error_code or None
            current.last_error_message = message or None
            session.commit()

    def _serialize(self, row: ServiceSetting | None, *, setting_id: str = "") -> dict[str, Any]:
        if row is None:
            return {
                "setting_id": setting_id,
                "setting_kind": SERVICE_SETTING_KIND_PORTAL,
                "enabled": False,
                "configured": False,
                "status": STATUS_MISSING_CONFIG,
                "config": {},
                "secrets": {},
                "last_tested_at": "",
                "last_error_code": "",
                "last_error_message": "",
                "credential_value_exposure": "none",
            }
        secrets = _dict(row.secret_ciphertext_json)
        secret_status = {
            key: {
                "configured": bool(_string(value)),
                "display": "configured" if value else "missing",
            }
            for key, value in secrets.items()
        }
        return {
            "setting_id": row.setting_id,
            "setting_kind": row.setting_kind,
            "enabled": bool(row.enabled),
            "configured": row.status == STATUS_READY,
            "status": row.status,
            "config": _public_config(_dict(row.config_json)),
            "secrets": secret_status,
            "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else "",
            "last_error_code": row.last_error_code or "",
            "last_error_message": row.last_error_message or "",
            "credential_value_exposure": "none",
        }


def resolve_portal_public_base_url(database_url: str, settings: Settings) -> str:
    row = _load_service_setting(database_url, SERVICE_SETTING_PORTAL_PUBLIC)
    if row is None or not bool(row.enabled):
        return ""
    return _normalize_public_base_url(_string(_dict(row.config_json).get("public_base_url")))


def resolve_portal_qq_runtime_config(database_url: str, settings: Settings) -> dict[str, Any]:
    row = _load_service_setting(database_url, SERVICE_SETTING_QQ_LOGIN)
    if row is None or not bool(row.enabled):
        return {"configured": False}
    config = _dict(row.config_json)
    public_base_url = resolve_portal_public_base_url(database_url, settings)
    client_secret = _decrypt_secret(row, "client_secret", settings=settings)
    redirect_uri = _string(config.get("redirect_uri")) or _default_qq_redirect_uri(public_base_url)
    configured = bool(
        _string(config.get("client_id"))
        and client_secret
        and _qq_redirect_uri_allowed(
            redirect_uri,
            public_base_url=public_base_url,
            environment=settings.environment,
        )
    )
    return {
        "configured": configured,
        "client_id": _string(config.get("client_id")),
        "client_secret": client_secret,
        "redirect_uri": redirect_uri if configured else "",
        "scope": _string(config.get("scope")) or "get_user_info",
        "timeout_seconds": _positive_float(config.get("timeout_seconds"), default=10.0),
    }


def resolve_portal_email_runtime_config(database_url: str, settings: Settings) -> dict[str, Any]:
    row = _load_service_setting(database_url, SERVICE_SETTING_PORTAL_EMAIL)
    if row is None or not bool(row.enabled):
        return {"configured": False}
    config = _dict(row.config_json)
    password = _decrypt_secret(row, "smtp_password", settings=settings)
    username = _string(config.get("smtp_username"))
    configured = bool(
        _string(config.get("smtp_host"))
        and _string(config.get("from_email"))
        and (not username or password)
    )
    return {
        "configured": configured,
        "smtp_host": _string(config.get("smtp_host")),
        "smtp_port": _positive_int(config.get("smtp_port"), default=465),
        "smtp_username": username,
        "smtp_password": password,
        "smtp_use_ssl": _bool(config.get("smtp_use_ssl"), default=True),
        "smtp_use_starttls": _bool(config.get("smtp_use_starttls"), default=False),
        "smtp_timeout_seconds": _positive_float(
            config.get("smtp_timeout_seconds"),
            default=20.0,
        ),
        "from_email": _string(config.get("from_email")),
        "from_name": _string(config.get("from_name")),
        "reply_to": _string(config.get("reply_to")),
    }


def resolve_alipay_payment_runtime_config(database_url: str, settings: Settings) -> dict[str, Any]:
    row = _load_service_setting(database_url, SERVICE_SETTING_PAYMENT_ALIPAY)
    if row is None or not bool(row.enabled):
        return {"configured": False, "enabled": False}
    config = _dict(row.config_json)
    private_key = _decrypt_secret(row, "private_key", settings=settings)
    public_key = _decrypt_secret(row, "public_key", settings=settings)
    configured = bool(
        _string(config.get("app_id"))
        and _string(config.get("gateway_url"))
        and _string(config.get("notify_url"))
        and _string(config.get("return_url"))
        and private_key
        and public_key
    )
    return {
        "configured": configured,
        "enabled": bool(row.enabled),
        "app_id": _string(config.get("app_id")),
        "gateway_url": _string(config.get("gateway_url")),
        "notify_url": _string(config.get("notify_url")),
        "return_url": _string(config.get("return_url")),
        "private_key": private_key,
        "public_key": public_key,
        "sign_type": _string(config.get("sign_type")) or "RSA2",
        "payment_product_code": _string(config.get("payment_product_code"))
        or "FAST_INSTANT_TRADE_PAY",
    }


def _load_service_setting(database_url: str, setting_id: str) -> ServiceSetting | None:
    with get_session(database_url) as session:
        return session.get(ServiceSetting, setting_id)


def _decrypt_secret(row: ServiceSetting | None, key: str, *, settings: Settings) -> str:
    if row is None:
        return ""
    ciphertext = _string(_dict(row.secret_ciphertext_json).get(key))
    if not ciphertext:
        return ""
    return decrypt_service_setting_secret(ciphertext, settings=settings)


def _setting_status(
    *,
    enabled: bool,
    config: dict[str, Any],
    secret_ciphertexts: dict[str, Any],
    required_secret_keys: list[str],
) -> str:
    if not enabled:
        return STATUS_DISABLED
    if not config:
        return STATUS_MISSING_CONFIG
    if any(not _string(secret_ciphertexts.get(key)) for key in required_secret_keys):
        return STATUS_MISSING_CONFIG
    return STATUS_READY


def _public_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in config.items()
        if "password" not in key and "secret" not in key and "token" not in key
    }


def _boundary() -> dict[str, Any]:
    return {
        "surface": "cloud_service_settings",
        "cloud_owns": [
            "portal_login_provider_config",
            "portal_email_delivery_config",
            "payment_gateway_config",
        ],
        "wordpress_control_plane": False,
        "ability_registry_truth": "wordpress_local",
        "workflow_registry_truth": "wordpress_local",
        "credential_value_exposure": "none",
        "env_fallback": "disabled",
    }


def _default_qq_redirect_uri(public_base_url: str) -> str:
    parsed = urlsplit(public_base_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, SERVICE_SETTING_QQ_OPEN_CALLBACK_PATH, "", ""))


def _default_alipay_notify_url(public_base_url: str) -> str:
    parsed = urlsplit(public_base_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, SERVICE_SETTING_ALIPAY_NOTIFY_PATH, "", ""))


def _default_alipay_return_url(public_base_url: str) -> str:
    parsed = urlsplit(public_base_url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, SERVICE_SETTING_ALIPAY_RETURN_PATH, "", ""))


def _qq_redirect_uri_allowed(
    value: str,
    *,
    public_base_url: str,
    environment: str,
) -> bool:
    parsed = urlsplit(_string(value))
    public_parsed = urlsplit(_string(public_base_url))
    if parsed.path != SERVICE_SETTING_QQ_OPEN_CALLBACK_PATH:
        return False
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return False
    if parsed.scheme != "https" and _string(environment).lower() not in {"development", "test"}:
        return False
    return bool(public_parsed.netloc and parsed.netloc.lower() == public_parsed.netloc.lower())


def _callback_url_allowed(
    value: str,
    *,
    public_base_url: str,
    expected_path: str,
    environment: str,
) -> bool:
    parsed = urlsplit(_string(value))
    public_parsed = urlsplit(_string(public_base_url))
    if parsed.path != expected_path:
        return False
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return False
    if parsed.scheme != "https" and _string(environment).lower() not in {"development", "test"}:
        return False
    return bool(public_parsed.netloc and parsed.netloc.lower() == public_parsed.netloc.lower())


def _normalize_public_base_url(value: str) -> str:
    raw = _string(value).rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), "", "", ""))


def _normalize_url(value: str) -> str:
    raw = _string(value)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "", "", ""))


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return str(value or "").strip()


def _bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = _string(value).lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(_string(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: object, *, default: float) -> float:
    try:
        parsed = float(_string(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
