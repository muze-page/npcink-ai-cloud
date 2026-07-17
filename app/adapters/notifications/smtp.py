from __future__ import annotations

import smtplib
import ssl
from email.header import Header
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html import escape

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
        message["Subject"] = self._build_test_email_subject(project_name=project_name)
        message["From"] = self._format_from_header()
        message["To"] = recipient_email
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        self._set_message_body(
            message,
            text_body=self._build_test_email_text_body(
                project_name=project_name,
                portal_url=portal_url,
            ),
            html_body=self._build_test_email_html_body(
                project_name=project_name,
                portal_url=portal_url,
            ),
        )

        try:
            self._ensure_delivery_headers(message)
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
        self._set_message_body(
            message,
            text_body=self._build_login_code_text_body(
                recipient_email=recipient_email,
                principal_id=principal_id,
                code=code,
                expires_in_seconds=expires_in_seconds,
                project_name=project_name,
                locale=locale,
            ),
            html_body=self._build_login_code_html_body(
                recipient_email=recipient_email,
                code=code,
                expires_in_seconds=expires_in_seconds,
                project_name=project_name,
                locale=locale,
            ),
        )

        try:
            self._ensure_delivery_headers(message)
            self._deliver(message)
        except Exception as error:
            raise PortalEmailDeliveryError(
                f"failed to deliver portal login code to '{recipient_email}': {error}"
            ) from error

    def send_registration_code(
        self,
        *,
        recipient_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        site_name: str = "",
        site_url: str = "",
        locale: str = "zh-CN",
    ) -> None:
        message = EmailMessage()
        message["Subject"] = self._build_registration_code_subject(
            project_name=project_name, locale=locale
        )
        message["From"] = self._format_from_header()
        message["To"] = recipient_email
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        self._set_message_body(
            message,
            text_body=self._build_registration_code_text_body(
                recipient_email=recipient_email,
                principal_id=principal_id,
                code=code,
                expires_in_seconds=expires_in_seconds,
                project_name=project_name,
                site_name=site_name,
                site_url=site_url,
                locale=locale,
            ),
            html_body=self._build_registration_code_html_body(
                recipient_email=recipient_email,
                code=code,
                expires_in_seconds=expires_in_seconds,
                project_name=project_name,
                site_name=site_name,
                site_url=site_url,
                locale=locale,
            ),
        )

        try:
            self._ensure_delivery_headers(message)
            self._deliver(message)
        except Exception as error:
            raise PortalEmailDeliveryError(
                f"failed to deliver portal registration code to '{recipient_email}': {error}"
            ) from error

    def send_email_change_code(
        self,
        *,
        recipient_email: str,
        old_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        message = EmailMessage()
        message["Subject"] = self._build_email_change_code_subject(
            project_name=project_name, locale=locale
        )
        message["From"] = self._format_from_header()
        message["To"] = recipient_email
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        self._set_message_body(
            message,
            text_body=self._build_email_change_code_text_body(
                recipient_email=recipient_email,
                old_email=old_email,
                principal_id=principal_id,
                code=code,
                expires_in_seconds=expires_in_seconds,
                project_name=project_name,
                locale=locale,
            ),
            html_body=self._build_email_change_code_html_body(
                recipient_email=recipient_email,
                old_email=old_email,
                code=code,
                expires_in_seconds=expires_in_seconds,
                project_name=project_name,
                locale=locale,
            ),
        )

        try:
            self._ensure_delivery_headers(message)
            self._deliver(message)
        except Exception as error:
            raise PortalEmailDeliveryError(
                f"failed to deliver portal email change code to '{recipient_email}': {error}"
            ) from error

    def send_email_changed_notice(
        self,
        *,
        recipient_email: str,
        new_email: str,
        principal_id: str,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        message = EmailMessage()
        message["Subject"] = self._build_email_changed_notice_subject(
            project_name=project_name, locale=locale
        )
        message["From"] = self._format_from_header()
        message["To"] = recipient_email
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        self._set_message_body(
            message,
            text_body=self._build_email_changed_notice_text_body(
                recipient_email=recipient_email,
                new_email=new_email,
                principal_id=principal_id,
                project_name=project_name,
                locale=locale,
            ),
            html_body=self._build_email_changed_notice_html_body(
                recipient_email=recipient_email,
                new_email=new_email,
                project_name=project_name,
                locale=locale,
            ),
        )

        try:
            self._ensure_delivery_headers(message)
            self._deliver(message)
        except Exception as error:
            raise PortalEmailDeliveryError(
                f"failed to deliver portal email change notice to '{recipient_email}': {error}"
            ) from error

    def send_support_request_update(
        self,
        *,
        recipient_email: str,
        request_id: str,
        title: str,
        status: str,
        message_body: str,
        project_name: str,
        portal_url: str,
        locale: str = "zh-CN",
    ) -> None:
        message = EmailMessage()
        message["Subject"] = self._build_support_request_update_subject(
            project_name=project_name,
            title=title,
            locale=locale,
        )
        message["From"] = self._format_from_header()
        message["To"] = recipient_email
        if self.reply_to:
            message["Reply-To"] = self.reply_to
        self._set_message_body(
            message,
            text_body=self._build_support_request_update_text_body(
                request_id=request_id,
                title=title,
                status=status,
                message_body=message_body,
                project_name=project_name,
                portal_url=portal_url,
                locale=locale,
            ),
            html_body=self._build_support_request_update_html_body(
                request_id=request_id,
                title=title,
                status=status,
                message_body=message_body,
                project_name=project_name,
                portal_url=portal_url,
                locale=locale,
            ),
        )

        try:
            self._ensure_delivery_headers(message)
            self._deliver(message)
        except Exception as error:
            raise PortalEmailDeliveryError(
                f"failed to deliver support request update to '{recipient_email}': {error}"
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

    def _ensure_delivery_headers(self, message: EmailMessage) -> None:
        if not message.get("Date"):
            message["Date"] = formatdate(localtime=True)
        if not message.get("Message-ID"):
            message["Message-ID"] = make_msgid(domain=self._message_id_domain())

    def _message_id_domain(self) -> str | None:
        if "@" not in self.from_email:
            return None
        domain = self.from_email.rsplit("@", 1)[1].strip()
        return domain or None

    def _format_from_header(self) -> str:
        if self.from_name:
            return formataddr((str(Header(self.from_name, "utf-8")), self.from_email))
        return self.from_email

    def _set_message_body(
        self,
        message: EmailMessage,
        *,
        text_body: str,
        html_body: str,
    ) -> None:
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

    def _build_test_email_subject(self, *, project_name: str) -> str:
        return f"{self._display_project_name(project_name)} 邮件服务测试成功"

    def _build_test_email_text_body(self, *, project_name: str, portal_url: str) -> str:
        display_name = self._display_project_name(project_name)
        return "\n".join(
            [
                f"{display_name} 邮件服务测试成功",
                "",
                "如果你收到这封邮件，说明当前 SMTP 配置可以正常发送 Portal 邮件。",
                f"Portal 地址：{portal_url}",
                "",
                "这只是一次测试，不需要进行任何操作。",
            ]
        )

    def _build_test_email_html_body(self, *, project_name: str, portal_url: str) -> str:
        display_name = self._display_project_name(project_name)
        return self._build_html_email(
            project_name=display_name,
            eyebrow="邮件服务测试",
            title="邮件服务测试成功",
            intro="如果你收到这封邮件，说明当前 SMTP 配置可以正常发送 Portal 邮件。",
            details=[("Portal 地址", portal_url)],
            note="这只是一次测试，不需要进行任何操作。",
        )

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
        expires_minutes = self._expires_minutes(expires_in_seconds)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-CN":
            return "\n".join(
                [
                    f"{display_name} 登录验证码",
                    "",
                    "你正在登录 Npcink 服务中心。",
                    "",
                    f"验证码：{code}",
                    f"登录邮箱：{recipient_email}",
                    "",
                    f"该验证码将在 {expires_minutes} 分钟后失效。",
                    "如果这不是你的操作，可以忽略这封邮件。",
                ]
            )
        if normalized_locale == "zh-TW":
            return "\n".join(
                [
                    f"{display_name} 登入驗證碼",
                    "",
                    "你正在登入 Npcink 服務中心。",
                    "",
                    f"驗證碼：{code}",
                    f"登入電子郵件：{recipient_email}",
                    "",
                    f"此驗證碼將在 {expires_minutes} 分鐘後失效。",
                    "如果這不是你的操作，可以忽略這封郵件。",
                ]
            )
        return "\n".join(
            [
                f"{display_name} sign-in code",
                "",
                "You are signing in to the Npcink service center.",
                "",
                f"Verification code: {code}",
                f"Email: {recipient_email}",
                "",
                f"This code expires in {expires_minutes} minutes.",
                "If you did not request this code, you can ignore this email.",
            ]
        )

    def _build_login_code_html_body(
        self,
        *,
        recipient_email: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str,
    ) -> str:
        normalized_locale = self._normalize_locale(locale)
        expires_minutes = self._expires_minutes(expires_in_seconds)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-TW":
            return self._build_html_email(
                project_name=display_name,
                eyebrow="登入驗證",
                title="你的登入驗證碼",
                intro="你正在登入 Npcink 服務中心，請在登入頁輸入下方驗證碼。",
                code=code,
                details=[
                    ("登入電子郵件", recipient_email),
                    ("有效時間", f"{expires_minutes} 分鐘"),
                ],
                note="如果這不是你的操作，可以忽略這封郵件。",
            )
        if normalized_locale == "en":
            return self._build_html_email(
                project_name=display_name,
                eyebrow="Sign-in verification",
                title="Your sign-in code",
                intro=(
                    "You are signing in to the Npcink service center. "
                    "Enter this code on the sign-in page."
                ),
                code=code,
                details=[("Email", recipient_email), ("Expires in", f"{expires_minutes} minutes")],
                note="If you did not request this code, you can ignore this email.",
            )
        return self._build_html_email(
            project_name=display_name,
            eyebrow="登录验证",
            title="你的登录验证码",
            intro="你正在登录 Npcink 服务中心，请在登录页输入下方验证码。",
            code=code,
            details=[("登录邮箱", recipient_email), ("有效时间", f"{expires_minutes} 分钟")],
            note="如果这不是你的操作，可以忽略这封邮件。",
        )

    def _build_login_code_subject(self, *, project_name: str, locale: str) -> str:
        normalized_locale = self._normalize_locale(locale)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-CN":
            return f"{display_name} 登录验证码"
        if normalized_locale == "zh-TW":
            return f"{display_name} 登入驗證碼"
        return f"{display_name} sign-in code"

    def _build_registration_code_text_body(
        self,
        *,
        recipient_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        site_name: str,
        site_url: str,
        locale: str,
    ) -> str:
        normalized_locale = self._normalize_locale(locale)
        expires_minutes = self._expires_minutes(expires_in_seconds)
        display_name = self._display_project_name(project_name)
        site_label = site_name or site_url
        if normalized_locale == "zh-CN":
            lines = [
                f"完成 {display_name} 注册",
                "",
                "你正在创建 Npcink 服务中心账号。验证成功后，可进入服务中心查看站点、用量和账单。",
                "",
                f"验证码：{code}",
                f"注册邮箱：{recipient_email}",
            ]
            if site_label:
                lines.append(f"站点：{site_label}")
            lines.extend(
                [
                    "",
                    f"该验证码将在 {expires_minutes} 分钟后失效。",
                    "如果这不是你的操作，可以忽略这封邮件。",
                ]
            )
            return "\n".join(lines)
        if normalized_locale == "zh-TW":
            lines = [
                f"完成 {display_name} 註冊",
                "",
                "你正在建立 Npcink 服務中心帳號。驗證成功後，可進入服務中心查看站點、用量和帳單。",
                "",
                f"驗證碼：{code}",
                f"註冊電子郵件：{recipient_email}",
            ]
            if site_label:
                lines.append(f"站點：{site_label}")
            lines.extend(
                [
                    "",
                    f"此驗證碼將在 {expires_minutes} 分鐘後失效。",
                    "如果這不是你的操作，可以忽略這封郵件。",
                ]
            )
            return "\n".join(lines)
        lines = [
            f"Complete your {display_name} registration",
            "",
            (
                "You are creating a Npcink service center account. After verification, "
                "you can view connected sites, usage, and billing details."
            ),
            "",
            f"Verification code: {code}",
            f"Registration email: {recipient_email}",
        ]
        if site_label:
            lines.append(f"Site: {site_label}")
        lines.extend(
            [
                "",
                f"This code expires in {expires_minutes} minutes.",
                "If you did not request this registration, you can ignore this email.",
            ]
        )
        return "\n".join(lines)

    def _build_registration_code_html_body(
        self,
        *,
        recipient_email: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        site_name: str,
        site_url: str,
        locale: str,
    ) -> str:
        normalized_locale = self._normalize_locale(locale)
        expires_minutes = self._expires_minutes(expires_in_seconds)
        display_name = self._display_project_name(project_name)
        site_label = site_name or site_url
        if normalized_locale == "zh-TW":
            details = [("註冊電子郵件", recipient_email), ("有效時間", f"{expires_minutes} 分鐘")]
            if site_label:
                details.append(("站點", site_label))
            return self._build_html_email(
                project_name=display_name,
                eyebrow="帳號註冊",
                title="完成服務中心註冊",
                intro="你正在建立 Npcink 服務中心帳號。驗證成功後，可查看站點、用量和帳單。",
                code=code,
                details=details,
                note="如果這不是你的操作，可以忽略這封郵件。",
            )
        if normalized_locale == "en":
            details = [
                ("Registration email", recipient_email),
                ("Expires in", f"{expires_minutes} minutes"),
            ]
            if site_label:
                details.append(("Site", site_label))
            return self._build_html_email(
                project_name=display_name,
                eyebrow="Account registration",
                title="Complete your service center registration",
                intro=(
                    "You are creating a Npcink service center account. "
                    "After verification, you can view connected sites, usage, "
                    "and billing details."
                ),
                code=code,
                details=details,
                note="If you did not request this registration, you can ignore this email.",
            )
        details = [("注册邮箱", recipient_email), ("有效时间", f"{expires_minutes} 分钟")]
        if site_label:
            details.append(("站点", site_label))
        return self._build_html_email(
            project_name=display_name,
            eyebrow="账号注册",
            title="完成服务中心注册",
            intro="你正在创建 Npcink 服务中心账号。验证成功后，可查看站点、用量和账单。",
            code=code,
            details=details,
            note="如果这不是你的操作，可以忽略这封邮件。",
        )

    def _build_registration_code_subject(self, *, project_name: str, locale: str) -> str:
        normalized_locale = self._normalize_locale(locale)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-CN":
            return f"完成 {display_name} 注册"
        if normalized_locale == "zh-TW":
            return f"完成 {display_name} 註冊"
        return f"Complete your {display_name} registration"

    def _build_email_change_code_text_body(
        self,
        *,
        recipient_email: str,
        old_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str,
    ) -> str:
        normalized_locale = self._normalize_locale(locale)
        expires_minutes = self._expires_minutes(expires_in_seconds)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-CN":
            return "\n".join(
                [
                    f"{display_name} 更换登录邮箱验证",
                    "",
                    f"新邮箱：{recipient_email}",
                    f"当前邮箱：{old_email}",
                    "",
                    f"验证码：{code}",
                    "",
                    (
                        f"该验证码将在 {expires_minutes} 分钟后失效。"
                        "验证通过后，新邮箱会成为 Portal 登录邮箱。"
                    ),
                    "如果这不是你的操作，可以忽略这封邮件。",
                ]
            )
        if normalized_locale == "zh-TW":
            return "\n".join(
                [
                    f"{display_name} 更換登入電子郵件驗證",
                    "",
                    f"新電子郵件：{recipient_email}",
                    f"目前電子郵件：{old_email}",
                    "",
                    f"驗證碼：{code}",
                    "",
                    (
                        f"此驗證碼將在 {expires_minutes} 分鐘後失效。"
                        "驗證通過後，新電子郵件會成為 Portal 登入電子郵件。"
                    ),
                    "如果這不是你的操作，可以忽略這封郵件。",
                ]
            )
        return "\n".join(
            [
                f"{display_name} email change verification",
                "",
                f"New email: {recipient_email}",
                f"Current email: {old_email}",
                "",
                f"Verification code: {code}",
                "",
                (
                    f"This code expires in {expires_minutes} minutes. "
                    "After verification, the new email will become your Portal sign-in email."
                ),
                "If you did not request this change, you can ignore this email.",
            ]
        )

    def _build_email_change_code_html_body(
        self,
        *,
        recipient_email: str,
        old_email: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        locale: str,
    ) -> str:
        normalized_locale = self._normalize_locale(locale)
        expires_minutes = self._expires_minutes(expires_in_seconds)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-TW":
            return self._build_html_email(
                project_name=display_name,
                eyebrow="電子郵件安全驗證",
                title="確認更換登入電子郵件",
                intro="你正在更換服務中心登入電子郵件。驗證成功前，目前電子郵件仍然有效。",
                code=code,
                details=[
                    ("目前電子郵件", old_email),
                    ("新電子郵件", recipient_email),
                    ("有效時間", f"{expires_minutes} 分鐘"),
                ],
                note="如果這不是你的操作，可以忽略這封郵件；目前電子郵件不會被更換。",
            )
        if normalized_locale == "en":
            return self._build_html_email(
                project_name=display_name,
                eyebrow="Email security verification",
                title="Confirm your sign-in email change",
                intro=(
                    "You are changing your service center sign-in email. "
                    "Your current email remains active until verification succeeds."
                ),
                code=code,
                details=[
                    ("Current email", old_email),
                    ("New email", recipient_email),
                    ("Expires in", f"{expires_minutes} minutes"),
                ],
                note=(
                    "If you did not request this change, you can ignore this email. "
                    "Your current email will not be changed."
                ),
            )
        return self._build_html_email(
            project_name=display_name,
            eyebrow="邮箱安全验证",
            title="确认更换登录邮箱",
            intro="你正在更换服务中心登录邮箱。验证成功前，当前邮箱仍然有效。",
            code=code,
            details=[
                ("当前邮箱", old_email),
                ("新邮箱", recipient_email),
                ("有效时间", f"{expires_minutes} 分钟"),
            ],
            note="如果这不是你的操作，可以忽略这封邮件；当前邮箱不会被更换。",
        )

    def _build_email_changed_notice_text_body(
        self,
        *,
        recipient_email: str,
        new_email: str,
        principal_id: str,
        project_name: str,
        locale: str,
    ) -> str:
        normalized_locale = self._normalize_locale(locale)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-CN":
            return "\n".join(
                [
                    f"{display_name} 登录邮箱已更换",
                    "",
                    f"旧邮箱：{recipient_email}",
                    f"新邮箱：{new_email}",
                    "",
                    "如果这不是你的操作，请尽快联系运营支持。",
                ]
            )
        if normalized_locale == "zh-TW":
            return "\n".join(
                [
                    f"{display_name} 登入電子郵件已更換",
                    "",
                    f"舊電子郵件：{recipient_email}",
                    f"新電子郵件：{new_email}",
                    "",
                    "如果這不是你的操作，請盡快聯絡營運支援。",
                ]
            )
        return "\n".join(
            [
                f"{display_name} email changed",
                "",
                f"Previous email: {recipient_email}",
                f"New email: {new_email}",
                "",
                "If you did not make this change, contact support as soon as possible.",
            ]
        )

    def _build_email_changed_notice_html_body(
        self,
        *,
        recipient_email: str,
        new_email: str,
        project_name: str,
        locale: str,
    ) -> str:
        normalized_locale = self._normalize_locale(locale)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-TW":
            return self._build_html_email(
                project_name=display_name,
                eyebrow="帳號安全通知",
                title="登入電子郵件已更換",
                intro="你的服務中心登入電子郵件已完成更換。",
                details=[("舊電子郵件", recipient_email), ("新電子郵件", new_email)],
                note="如果這不是你的操作，請盡快聯絡營運支援。",
            )
        if normalized_locale == "en":
            return self._build_html_email(
                project_name=display_name,
                eyebrow="Account security notice",
                title="Your sign-in email was changed",
                intro="Your service center sign-in email has been changed.",
                details=[("Previous email", recipient_email), ("New email", new_email)],
                note="If you did not make this change, contact support as soon as possible.",
            )
        return self._build_html_email(
            project_name=display_name,
            eyebrow="账号安全通知",
            title="登录邮箱已更换",
            intro="你的服务中心登录邮箱已完成更换。",
            details=[("旧邮箱", recipient_email), ("新邮箱", new_email)],
            note="如果这不是你的操作，请尽快联系运营支持。",
        )

    def _build_email_change_code_subject(self, *, project_name: str, locale: str) -> str:
        normalized_locale = self._normalize_locale(locale)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-CN":
            return f"{display_name} 更换登录邮箱验证码"
        if normalized_locale == "zh-TW":
            return f"{display_name} 更換登入電子郵件驗證碼"
        return f"{display_name} email change code"

    def _build_email_changed_notice_subject(self, *, project_name: str, locale: str) -> str:
        normalized_locale = self._normalize_locale(locale)
        display_name = self._display_project_name(project_name)
        if normalized_locale == "zh-CN":
            return f"{display_name} 登录邮箱已更换"
        if normalized_locale == "zh-TW":
            return f"{display_name} 登入電子郵件已更換"
        return f"{display_name} email changed"

    def _build_support_request_update_subject(
        self,
        *,
        project_name: str,
        title: str,
        locale: str,
    ) -> str:
        display_name = self._display_project_name(project_name)
        display_title = " ".join(str(title or "工单更新").split())[:80]
        if self._normalize_locale(locale) == "en":
            return f"{display_name} ticket update: {display_title}"
        return f"{display_name} 工单更新：{display_title}"

    def _build_support_request_update_text_body(
        self,
        *,
        request_id: str,
        title: str,
        status: str,
        message_body: str,
        project_name: str,
        portal_url: str,
        locale: str,
    ) -> str:
        display_name = self._display_project_name(project_name)
        if self._normalize_locale(locale) == "en":
            return "\n".join(
                [
                    f"{display_name} ticket update",
                    "",
                    f"Ticket: {title}",
                    f"Request ID: {request_id}",
                    f"Status: {status}",
                    "",
                    "Latest reply:",
                    str(message_body or "").strip(),
                    "",
                    f"Open ticket: {portal_url}",
                    "",
                    "Please sign in to the Portal to reply or provide more information.",
                ]
            )
        return "\n".join(
            [
                f"{display_name} 工单更新",
                "",
                f"工单：{title}",
                f"工单 ID：{request_id}",
                f"状态：{status}",
                "",
                "最新回复：",
                str(message_body or "").strip(),
                "",
                f"查看工单：{portal_url}",
                "",
                "请登录 Portal 回复或补充信息。",
            ]
        )

    def _build_support_request_update_html_body(
        self,
        *,
        request_id: str,
        title: str,
        status: str,
        message_body: str,
        project_name: str,
        portal_url: str,
        locale: str,
    ) -> str:
        display_name = self._display_project_name(project_name)
        normalized_locale = self._normalize_locale(locale)
        if normalized_locale == "en":
            return self._build_html_email(
                project_name=display_name,
                eyebrow="Ticket update",
                title="Support replied to your ticket",
                intro=str(message_body or "").strip(),
                details=[("Ticket", title), ("Request ID", request_id), ("Status", status)],
                note=(
                    "Open the ticket in Portal to reply or provide more information: "
                    f"{portal_url}"
                ),
            )
        return self._build_html_email(
            project_name=display_name,
            eyebrow="工单更新",
            title="客服已回复你的工单",
            intro=str(message_body or "").strip(),
            details=[("工单", title), ("工单 ID", request_id), ("状态", status)],
            note=f"请在 Portal 查看工单并回复或补充信息：{portal_url}",
        )

    def _build_html_email(
        self,
        *,
        project_name: str,
        eyebrow: str,
        title: str,
        intro: str,
        details: list[tuple[str, str]],
        note: str,
        code: str = "",
    ) -> str:
        safe_project_name = escape(project_name)
        safe_eyebrow = escape(eyebrow)
        safe_title = escape(title)
        safe_intro = escape(intro)
        safe_note = escape(note)
        body_style = (
            "margin:0;padding:0;background:#f6f8fb;"
            "font-family:Arial,'PingFang SC','Microsoft YaHei',sans-serif;"
            "color:#0f172a;"
        )
        page_table_style = "background:#f6f8fb;padding:28px 12px;"
        card_style = (
            "max-width:560px;background:#ffffff;border:1px solid #e2e8f0;"
            "border-radius:18px;overflow:hidden;"
        )
        header_style = "padding:28px 30px 18px;border-bottom:1px solid #e2e8f0;"
        brand_style = "font-size:18px;font-weight:800;color:#0f172a;"
        eyebrow_style = (
            "margin-top:10px;font-size:12px;font-weight:700;letter-spacing:0.08em;"
            "text-transform:uppercase;color:#2563eb;"
        )
        title_style = "margin:0 0 12px;font-size:24px;line-height:1.35;color:#0f172a;"
        intro_style = "margin:0;font-size:15px;line-height:1.8;color:#334155;"
        table_attrs = 'role="presentation" width="100%" cellspacing="0" cellpadding="0"'
        detail_table_style = (
            "margin:18px 0;border-top:1px solid #e2e8f0;"
            "border-bottom:1px solid #e2e8f0;"
        )
        label_style = "padding:8px 0;color:#64748b;font-size:13px;"
        value_style = (
            "padding:8px 0;color:#0f172a;font-size:13px;"
            "text-align:right;font-weight:600;"
        )
        note_style = "margin:18px 0 0;font-size:14px;line-height:1.8;color:#475569;"
        footer_style = (
            "padding:18px 30px;background:#f8fafc;color:#64748b;"
            "font-size:12px;line-height:1.7;"
        )
        detail_rows = "\n".join(
            [
                (
                    '<tr>'
                    f'<td style="{label_style}">'
                    f"{escape(label)}"
                    "</td>"
                    f'<td style="{value_style}">'
                    f"{escape(value)}"
                    "</td>"
                    "</tr>"
                )
                for label, value in details
                if str(value or "").strip()
            ]
        )
        code_block = ""
        if code:
            code_block = (
                '<div style="margin:24px 0;padding:20px;border-radius:14px;'
                'background:#f8fafc;border:1px solid #e2e8f0;text-align:center;">'
                '<div style="font-size:12px;color:#64748b;margin-bottom:8px;">验证码</div>'
                '<div style="font-size:34px;line-height:1.2;font-weight:800;'
                'letter-spacing:0.18em;color:#0f172a;font-family:Arial,Helvetica,sans-serif;">'
                f"{escape(code)}"
                "</div>"
                "</div>"
            )
        return f"""<!doctype html>
<html>
  <body style="{body_style}">
    <div style="display:none;max-height:0;overflow:hidden;color:transparent;">{safe_title}</div>
    <table {table_attrs} style="{page_table_style}">
      <tr>
        <td align="center">
          <table {table_attrs} style="{card_style}">
            <tr>
              <td style="{header_style}">
                <div style="{brand_style}">{safe_project_name}</div>
                <div style="{eyebrow_style}">{safe_eyebrow}</div>
              </td>
            </tr>
            <tr>
              <td style="padding:30px;">
                <h1 style="{title_style}">{safe_title}</h1>
                <p style="{intro_style}">{safe_intro}</p>
                {code_block}
                <table {table_attrs} style="{detail_table_style}">
                  {detail_rows}
                </table>
                <p style="{note_style}">{safe_note}</p>
              </td>
            </tr>
            <tr>
              <td style="{footer_style}">
                这是一封系统邮件，请勿直接回复。需要帮助时，请联系 Npcink 支持。
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>"""

    def _display_project_name(self, project_name: str) -> str:
        value = " ".join(str(project_name or "Npcink AI Cloud").replace("_", " ").split())
        return value or "Npcink AI Cloud"

    def _expires_minutes(self, expires_in_seconds: int) -> int:
        return max(1, int(expires_in_seconds or 0) // 60)

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


def build_portal_email_preview(
    *,
    preview_type: str,
    project_name: str,
    locale: str = "zh-CN",
    portal_url: str = "/portal/login",
) -> dict[str, str]:
    sender = SmtpPortalEmailSender(
        host="preview.invalid",
        port=465,
        use_ssl=True,
        use_starttls=False,
        timeout_seconds=1,
        from_email="preview@npc.ink",
        from_name="Npcink AI Cloud",
    )
    normalized_type = (preview_type or "").strip().lower().replace("-", "_")
    if normalized_type == "test":
        return {
            "preview_type": "test",
            "subject": sender._build_test_email_subject(project_name=project_name),
            "text": sender._build_test_email_text_body(
                project_name=project_name,
                portal_url=portal_url,
            ),
            "html": sender._build_test_email_html_body(
                project_name=project_name,
                portal_url=portal_url,
            ),
        }
    if normalized_type == "registration":
        return {
            "preview_type": "registration",
            "subject": sender._build_registration_code_subject(
                project_name=project_name,
                locale=locale,
            ),
            "text": sender._build_registration_code_text_body(
                recipient_email="member@example.com",
                principal_id="prn_preview",
                code="654321",
                expires_in_seconds=600,
                project_name=project_name,
                site_name="Npcink Demo Site",
                site_url="https://example.com",
                locale=locale,
            ),
            "html": sender._build_registration_code_html_body(
                recipient_email="member@example.com",
                code="654321",
                expires_in_seconds=600,
                project_name=project_name,
                site_name="Npcink Demo Site",
                site_url="https://example.com",
                locale=locale,
            ),
        }
    if normalized_type == "email_change":
        return {
            "preview_type": "email_change",
            "subject": sender._build_email_change_code_subject(
                project_name=project_name,
                locale=locale,
            ),
            "text": sender._build_email_change_code_text_body(
                recipient_email="new-member@example.com",
                old_email="member@example.com",
                principal_id="prn_preview",
                code="246810",
                expires_in_seconds=600,
                project_name=project_name,
                locale=locale,
            ),
            "html": sender._build_email_change_code_html_body(
                recipient_email="new-member@example.com",
                old_email="member@example.com",
                code="246810",
                expires_in_seconds=600,
                project_name=project_name,
                locale=locale,
            ),
        }
    if normalized_type == "email_changed":
        return {
            "preview_type": "email_changed",
            "subject": sender._build_email_changed_notice_subject(
                project_name=project_name,
                locale=locale,
            ),
            "text": sender._build_email_changed_notice_text_body(
                recipient_email="member@example.com",
                new_email="new-member@example.com",
                principal_id="prn_preview",
                project_name=project_name,
                locale=locale,
            ),
            "html": sender._build_email_changed_notice_html_body(
                recipient_email="member@example.com",
                new_email="new-member@example.com",
                project_name=project_name,
                locale=locale,
            ),
        }
    return {
        "preview_type": "login",
        "subject": sender._build_login_code_subject(
            project_name=project_name,
            locale=locale,
        ),
        "text": sender._build_login_code_text_body(
            recipient_email="member@example.com",
            principal_id="prn_preview",
            code="123456",
            expires_in_seconds=600,
            project_name=project_name,
            locale=locale,
        ),
        "html": sender._build_login_code_html_body(
            recipient_email="member@example.com",
            code="123456",
            expires_in_seconds=600,
            project_name=project_name,
            locale=locale,
        ),
    }


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
