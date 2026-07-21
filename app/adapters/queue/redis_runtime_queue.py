from __future__ import annotations

from typing import cast

from redis import Redis
from redis.exceptions import RedisError

from app.adapters.queue.base import RuntimeQueueError


class RedisRuntimeQueue:
    def __init__(
        self,
        redis_url: str,
        queue_key: str,
        *,
        client: Redis | None = None,
    ) -> None:
        self.redis_url = redis_url
        self.queue_key = queue_key
        self._client = client

    def _get_client(self) -> Redis:
        if self._client is None:
            self._client = Redis.from_url(self.redis_url, decode_responses=True)
        return self._client

    def publish(self, run_id: str) -> None:
        client = self._get_client()
        try:
            client.lpush(self.queue_key, run_id)
        except RedisError as error:
            raise RuntimeQueueError(str(error)) from error

    def consume(self, timeout_seconds: int) -> str | None:
        client = self._get_client()
        try:
            if timeout_seconds <= 0:
                return cast(str | None, client.rpop(self.queue_key))
            result = cast(
                tuple[str, str] | None,
                client.brpop([self.queue_key], timeout=timeout_seconds),
            )
            if result is None:
                return None
            _, run_id = result
            return run_id
        except RedisError as error:
            raise RuntimeQueueError(str(error)) from error

    def close(self) -> None:
        if self._client is None:
            return
        self._client.close()
        self._client = None
