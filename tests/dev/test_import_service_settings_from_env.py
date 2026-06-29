from __future__ import annotations

from app.core.config import Settings
from app.core.db import dispose_engine, get_session, init_schema
from app.core.models import ServiceSetting
from app.core.secrets import decrypt_service_setting_secret
from app.dev.import_service_settings_from_env import import_service_settings_from_env


def _sqlite_url(tmp_path) -> str:
    return f"sqlite+pysqlite:///{tmp_path / 'service-settings-env-import.sqlite3'}"


def _settings(database_url: str) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url=database_url,
        redis_url="redis://localhost:6379/0",
        internal_auth_token="npcink-cloud-internal-test-token-32b",
        admin_session_secret="npcink-cloud-admin-session-secret-32b",
        portal_jwt_secret="npcink-cloud-portal-jwt-secret-32b",
    )


def test_import_service_settings_from_env_stores_values_without_secret_output(
    tmp_path,
) -> None:
    database_url = _sqlite_url(tmp_path)
    init_schema(database_url)
    settings = _settings(database_url)

    result = import_service_settings_from_env(
        settings=settings,
        env={
            "NPCINK_CLOUD_PORTAL_PUBLIC_BASE_URL": "https://cloud.example.com",
            "NPCINK_CLOUD_PORTAL_QQ_CLIENT_ID": "qq-client",
            "NPCINK_CLOUD_PORTAL_QQ_CLIENT_SECRET": "qq-secret",
            "NPCINK_CLOUD_PORTAL_EMAIL_SMTP_HOST": "smtp.example.com",
            "NPCINK_CLOUD_PORTAL_EMAIL_SMTP_PORT": "465",
            "NPCINK_CLOUD_PORTAL_EMAIL_SMTP_USERNAME": "smtp-user",
            "NPCINK_CLOUD_PORTAL_EMAIL_SMTP_PASSWORD": "smtp-secret",
            "NPCINK_CLOUD_PORTAL_EMAIL_FROM_EMAIL": "noreply@example.com",
            "NPCINK_CLOUD_PORTAL_EMAIL_FROM_NAME": "Npcink AI Cloud",
        },
    )

    assert result["imported"] == ["portal_public", "portal_qq_login", "portal_email"]
    assert result["credential_value_exposure"] == "none"
    assert "qq-secret" not in str(result)
    assert "smtp-secret" not in str(result)

    with get_session(database_url) as session:
        public = session.get(ServiceSetting, "portal_public")
        qq = session.get(ServiceSetting, "portal_qq_login")
        email = session.get(ServiceSetting, "portal_email")
        assert public is not None
        assert qq is not None
        assert email is not None
        assert public.config_json["public_base_url"] == "https://cloud.example.com"
        assert qq.config_json["client_id"] == "qq-client"
        assert email.config_json["smtp_host"] == "smtp.example.com"
        assert (
            decrypt_service_setting_secret(
                qq.secret_ciphertext_json["client_secret"],
                settings=settings,
            )
            == "qq-secret"
        )
        assert (
            decrypt_service_setting_secret(
                email.secret_ciphertext_json["smtp_password"],
                settings=settings,
            )
            == "smtp-secret"
        )

    dispose_engine(database_url)

