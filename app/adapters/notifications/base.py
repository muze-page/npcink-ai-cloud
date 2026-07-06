from __future__ import annotations

from abc import ABC, abstractmethod


class PortalEmailDeliveryError(RuntimeError):
    pass


class PortalEmailSender(ABC):
    @abstractmethod
    def send_test_email(
        self,
        *,
        recipient_email: str,
        project_name: str,
        portal_url: str,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def send_registration_code(
        self,
        *,
        recipient_email: str,
        principal_id: str,
        code: str,
        expires_in_seconds: int,
        project_name: str,
        site_name: str = "",
        wordpress_url: str = "",
        locale: str = "zh-CN",
    ) -> None:
        raise NotImplementedError

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    def send_email_changed_notice(
        self,
        *,
        recipient_email: str,
        new_email: str,
        principal_id: str,
        project_name: str,
        locale: str = "zh-CN",
    ) -> None:
        raise NotImplementedError
