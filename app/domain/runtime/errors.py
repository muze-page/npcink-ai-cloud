from __future__ import annotations


class RuntimeErrorBase(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.message = message


class RuntimeIdempotencyConflictError(RuntimeErrorBase):
    def __init__(self, site_id: str, idempotency_key: str) -> None:
        super().__init__(
            409,
            "runtime.idempotency_conflict",
            f"idempotency key '{idempotency_key}' for site '{site_id}' "
            "does not match the original request",
        )


class RuntimeSiteNotProvisionedError(RuntimeErrorBase):
    def __init__(self, site_id: str) -> None:
        super().__init__(
            400,
            "runtime.site_not_provisioned",
            f"site '{site_id}' is not provisioned for cloud runtime",
        )


class RuntimeSiteInactiveError(RuntimeErrorBase):
    def __init__(self, site_id: str, status: str) -> None:
        super().__init__(
            400,
            "runtime.site_not_active",
            f"site '{site_id}' is in status '{status}' and is not active for cloud runtime",
        )


class RuntimeSubscriptionInactiveError(RuntimeErrorBase):
    def __init__(self, site_id: str, status: str) -> None:
        super().__init__(
            403,
            "commercial.subscription_inactive",
            f"site '{site_id}' subscription status '{status}' does not permit cloud runtime",
        )


class RuntimeEntitlementDeniedError(RuntimeErrorBase):
    def __init__(self, site_id: str, ability_family: str, reason: str) -> None:
        super().__init__(
            403,
            "commercial.entitlement_denied",
            f"site '{site_id}' is not entitled for ability family '{ability_family}'"
            f" ({reason})",
        )


class RuntimeExecutionContractError(RuntimeErrorBase):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(400, error_code, message)


class RuntimeCallbackConfigurationError(RuntimeErrorBase):
    def __init__(self, site_id: str, message: str) -> None:
        super().__init__(
            400,
            "runtime.callback_not_registered",
            f"site '{site_id}' callback configuration is invalid: {message}",
        )


class RuntimeQuotaExceededError(RuntimeErrorBase):
    def __init__(self, meter_key: str, limit: float) -> None:
        super().__init__(
            429,
            "commercial.quota_exceeded",
            f"runtime quota '{meter_key}' exhausted at limit '{limit}'",
        )


class RuntimeConcurrencyExceededError(RuntimeErrorBase):
    def __init__(self, site_id: str, limit: int) -> None:
        super().__init__(
            429,
            "commercial.concurrency_exceeded",
            f"site '{site_id}' exceeded max active cloud runs '{limit}'",
        )


class RuntimeBatchLimitExceededError(RuntimeErrorBase):
    def __init__(self, *, feature_id: str, requested_items: int, limit: int) -> None:
        super().__init__(
            429,
            "commercial.batch_limit_exceeded",
            f"feature '{feature_id}' requested '{requested_items}' batch items "
            f"but current plan limit is '{limit}'",
        )


class RuntimeRunNotFoundError(RuntimeErrorBase):
    def __init__(self, run_id: str) -> None:
        super().__init__(404, "runtime.run_not_found", f"run '{run_id}' was not found")


class RuntimeCancelNotAllowedError(RuntimeErrorBase):
    def __init__(self, run_id: str, status: str) -> None:
        super().__init__(
            409,
            "runtime.cancel_not_allowed",
            f"run '{run_id}' in status '{status}' does not permit public cancel",
        )


class RuntimeResultNotReadyError(RuntimeErrorBase):
    def __init__(self, run_id: str, status: str) -> None:
        super().__init__(
            409,
            "runtime.result_not_ready",
            f"run '{run_id}' is in status '{status}' and has no result yet",
        )


class RuntimeResultExpiredError(RuntimeErrorBase):
    def __init__(self, run_id: str) -> None:
        super().__init__(
            410,
            "runtime.result_expired",
            f"run '{run_id}' result has expired and is no longer available",
        )
