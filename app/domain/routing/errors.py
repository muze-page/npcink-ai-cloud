from __future__ import annotations


class RoutingError(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class RoutingProfileNotFoundError(RoutingError):
    def __init__(self, profile_id: str) -> None:
        super().__init__(
            "routing.profile_not_found",
            f"routing profile '{profile_id}' is not configured",
        )


class RoutingExecutionKindMismatchError(RoutingError):
    def __init__(self, profile_id: str, expected: str, received: str) -> None:
        super().__init__(
            "routing.execution_kind_mismatch",
            f"profile '{profile_id}' expects '{expected}', received '{received}'",
        )


class RoutingNoCandidatesError(RoutingError):
    def __init__(self, profile_id: str) -> None:
        super().__init__(
            "routing.no_candidates",
            f"routing profile '{profile_id}' has no available candidates",
        )
