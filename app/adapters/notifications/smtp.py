from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from app.adapters.notifications.base import PortalEmailDeliveryError, PortalEmailSender
from app.core.config import Settings


class SmtpPortalEmailSender(PortalEmailSender):
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str = "",
        password: str = "",
        use_ssl: bool,
        use_starttls: bool,
        timeout_seconds: float,
        from_email: str,
        from_name: str = "",
        reply_to: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_ssl = use_ssl
        self.use_starttls = use_starttls
        self.timeout_seconds = timeout_seconds
        self.from_email = from_email
        self.from_name = from_name
        self.reply_to = reply_to

    def send_test_email(
        self,
        *,
        recipient_email: str,
        project_name: str,
        portal_url: str,
    ) -> None:
        message = EmailMessage()
        message["Subject"] = f"{project_name} portal email test"
        message["From"] = self._format_from_header()
        message["To"] = recipient_email
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        message.set_content(
            "\n".join(
                [
                    f"{project_name} SMTP test",
                    "",
                    "This is a test email from the Npcink AI Cloud portal mailer.",
                    f"Portal URL: {portal_url}",
                    "",
                    "If you received this email, the current SMTP configuration is working.",
                ]
            )
        )

        try:
            self._deliver(message)
        except Exception as error:
            raise PortalEmailDeliveryError(
                f"failed to deliver portal test email to '{recipient_email}': {error}"
            ) from error

    def send_login_code(
        self,
        *,
        recipient_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        message = EmailMessage()
        message["Subject"] = self._build_login_code_subject(
            project_name=project_name, locale=locale
        )
        message["From"] = self._format_from_header()
        message["To"] = recipient_email
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        message.set_content(
            self._build_login_code_text_body(
                recipient_email=recipient_email,
                principal_id=principal_id,
                code=code,
                expires_in_seconds=expires_in_seconds,
                project_name=project_name,
                locale=locale,
            )
        )

        try:
            self._deliver(message)
        except Exception as error:
            raise PortalEmailDeliveryError(
                f"failed to deliver portal login code to '{recipient_email}': {error}"
            ) from error

    def _deliver(self, message: EmailMessage) -> None:
        ssl_context = ssl.create_default_context()
        if self.use_ssl:
            with smtplib.SMTP_SSL(
                self.host,
                self.port,
                timeout=self.timeout_seconds,
                context=ssl_context,
            ) as client:
                self._login_if_configured(client)
                client.send_message(message)
            return

        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as client:
            client.ehlo()
            if self.use_starttls:
                client.starttls(context=ssl_context)
                client.ehlo()
            self._login_if_configured(client)
            client.send_message(message)

    def _login_if_configured(self, client: smtplib.SMTP) -> None:
        if self.username and self.password:
            client.login(self.username, self.password)

    def _format_from_header(self) -> str:
        if self.from_name:
            return f"{self.from_name} <{self.from_email}>"
        return self.from_email

    def _build_login_code_text_body(
        self,
        *,
        recipient_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str,
    ) -> str:
        normalized_locale = self._normalize_locale(locale)
        expires_minutes = max(1, expires_in_seconds // 60)
        if normalized_locale == "zh-CN":
            return "\n".join(
                [
                    f"{project_name} 登录验证码",
                    "",
                    f"邮箱：{recipient_email}",
                    "",
                    f"验证码：{code}",
                    "",
                    f"该验证码将在 {expires_minutes} 分钟后失效。",
                    "如果这不是你的操作，可以忽略这封邮件。",
                ]
            )
        if normalized_locale == "zh-TW":
            return "\n".join(
                [
                    f"{project_name} 登入驗證碼",
                    "",
                    f"電子郵件：{recipient_email}",
                    "",
                    f"驗證碼：{code}",
                    "",
                    f"此驗證碼將在 {expires_minutes} 分鐘後失效。",
                    "如果這不是你的操作，可以忽略這封郵件。",
                ]
            )
        return "\n".join(
            [
                f"{project_name} portal sign-in code",
                "",
                f"Email: {recipient_email}",
                "",
                f"Verification code: {code}",
                "",
                f"This code expires in {expires_minutes} minutes.",
                "If you did not request this code, you can ignore this email.",
            ]
        )

    def _build_login_code_subject(self, *, project_name: str, locale: str) -> str:
        normalized_locale = self._normalize_locale(locale)
        if normalized_locale == "zh-CN":
            return f"{project_name} 登录验证码"
        if normalized_locale == "zh-TW":
            return f"{project_name} 登入驗證碼"
        return f"{project_name} portal sign-in code"

    def _normalize_locale(self, locale: str) -> str:
        value = (locale or "").strip().lower()
        if value in {"zh", "zh-cn", "zh_hans", "zh-hans", "zh_cn"}:
            return "zh-CN"
        if value in {"zh-tw", "zh_hant", "zh-hant", "zh_tw", "zh-hk"}:
            return "zh-TW"
        return "en" if value == "en" else "zh-CN"


def build_portal_email_sender_from_config(config: dict[str, object]) -> PortalEmailSender | None:
    host = str(config.get("smtp_host") or "").strip()
    from_email = str(config.get("from_email") or "").strip()
    if not host:
        return None
    if not from_email:
        raise ValueError("portal email from_email is required when SMTP is set.")
    use_ssl = bool(config.get("smtp_use_ssl", True))
    use_starttls = bool(config.get("smtp_use_starttls", False))
    if use_ssl and use_starttls:
        raise ValueError("Portal SMTP cannot enable both SSL and STARTTLS.")
    username = str(config.get("smtp_username") or "").strip()
    password = str(config.get("smtp_password") or "")
    if bool(username) != bool(password):
        raise ValueError("Portal SMTP username and password must be configured together.")

    return SmtpPortalEmailSender(
        host=host,
        port=int(str(config.get("smtp_port") or 465)),
        username=username,
        password=password,
        use_ssl=use_ssl,
        use_starttls=use_starttls,
        timeout_seconds=float(str(config.get("smtp_timeout_seconds") or 20.0)),
        from_email=from_email,
        from_name=str(config.get("from_name") or "").strip(),
        reply_to=str(config.get("reply_to") or "").strip(),
    )


def build_portal_email_sender(
    settings: Settings,
    *,
    database_url: str | None = None,
) -> PortalEmailSender | None:
    resolved_database_url = str(database_url or settings.database_url or "").strip()
    if not resolved_database_url:
        return None
    from app.domain.service_settings import resolve_portal_email_runtime_config

    config = resolve_portal_email_runtime_config(resolved_database_url, settings)
    if not config.get("configured"):
        return None
    return build_portal_email_sender_from_config(config)
