from __future__ import annotations

from typing import Any


def build_envelope(
    *,
    status: str,
    data: dict[str, Any] | None = None,
    message: str = "",
    error_code: str = "",
    trace_id: str = "",
    revision: str = "m0",
) -> dict[str, Any]:
    return {
        "status": status,
        "error_code": error_code,
        "message": message,
        "data": data or {},
        "meta": {
            "trace_id": trace_id,
            "revision": revision,
        },
    }
