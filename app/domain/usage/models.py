from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class UsageWindowRange:
    start_at: datetime
    end_at: datetime


@dataclass(slots=True)
class HealthRollup:
    providers_total: int
    instances_total: int
    healthy_total: int
    degraded_total: int
    unhealthy_total: int
    unknown_total: int
    last_measured_at: str
