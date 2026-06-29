from __future__ import annotations

from dataclasses import dataclass, field

from redis.asyncio import Redis

from app.adapters.callbacks.base import RuntimeCallbackDispatcher
from app.adapters.callbacks.http import HttpRuntimeCallbackDispatcher
from app.adapters.notifications.base import PortalEmailSender
from app.adapters.providers.base import ProviderAdapter
from app.adapters.providers.registry import build_provider_adapters
from app.adapters.queue.base import RuntimeQueue
from app.adapters.queue.redis_runtime_queue import RedisRuntimeQueue
from app.core.config import Settings
from app.core.db import check_database_connection
from app.domain.provider_connections.runtime_settings import (
    apply_provider_connection_runtime_settings,
)


@dataclass(slots=True)
class ReadyReport:
    checks: dict[str, bool]
    details: dict[str, str]

    @property
    def ok(self) -> bool:
        return all(self.checks.values())


@dataclass(slots=True)
class CloudServices:
    settings: Settings
    providers: dict[str, ProviderAdapter] = field(default_factory=dict)
    runtime_queue: RuntimeQueue | None = None
    callback_dispatcher: RuntimeCallbackDispatcher | None = None
    portal_email_sender: PortalEmailSender | None = None

    async def get_live_payload(self) -> dict[str, str]:
        return {
            "service": self.settings.project_name,
            "environment": self.settings.environment,
        }

    async def get_ready_report(self) -> ReadyReport:
        database_ok, database_detail = check_database_connection(self.settings.database_url)
        redis_ok, redis_detail = await self._check_redis_connection()

        return ReadyReport(
            checks={
                "database": database_ok,
                "redis": redis_ok,
            },
            details={
                "database": database_detail,
                "redis": redis_detail,
            },
        )

    async def _check_redis_connection(self) -> tuple[bool, str]:
        client = Redis.from_url(self.settings.redis_url)

        try:
            await client.ping()
            return True, "redis is reachable"
        except Exception as error:  # pragma: no cover - redis client errors vary by driver/runtime.
            return False, str(error)
        finally:
            await client.aclose()


def create_default_services(settings: Settings) -> CloudServices:
    apply_provider_connection_runtime_settings(settings)
    return CloudServices(
        settings=settings,
        providers=build_provider_adapters(settings),
        runtime_queue=RedisRuntimeQueue(
            settings.redis_url,
            settings.runtime_queue_key,
        ),
        callback_dispatcher=HttpRuntimeCallbackDispatcher(
            timeout_seconds=settings.runtime_callback_timeout_seconds,
        ),
        portal_email_sender=None,
    )
