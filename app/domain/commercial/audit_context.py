from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ServiceAuditContext:
    trace_id: str
    idempotency_key: str
    method: str
    path: str
    actor_kind: str = "internal_token"
    actor_ref: str = "internal"
