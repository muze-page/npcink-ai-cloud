from __future__ import annotations

import hashlib
import hmac
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.runtime_config import (
    FRONTEND_INTERNAL_TOKEN_FILE,
    canonical_json_bytes,
    load_runtime_settings_values,
    runtime_config_digest,
)
from app.setup.database import DatabaseValidationResult, PostgreSQL18Validator
from app.setup.errors import SetupError
from app.setup.models import DatabaseInput, InstallInput
from app.setup.security import (
    SetupAttemptLimiter,
    build_setup_session_token,
    generate_prefixed_secret,
    generate_root_secret,
    sha256_text,
    verify_setup_code,
    verify_setup_session_token,
)
from app.setup.state import (
    InstallationInProgressError,
    InstallationState,
    SetupConfigStore,
    SetupStateError,
    new_attempt_id,
)

if TYPE_CHECKING:
    from app.core.config import Settings

_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _validate_runtime_activation(settings: Settings) -> None:
    from app.core.services import create_default_services

    create_default_services(settings)


class SetupService:
    def __init__(
        self,
        store: SetupConfigStore,
        *,
        database_validator: PostgreSQL18Validator | None = None,
        public_origin_allowlist: set[str] | None = None,
        runtime_activation_validator: Callable[[Settings], object] | None = None,
    ) -> None:
        self.store = store
        self.database_validator = database_validator or PostgreSQL18Validator()
        self.public_origin_allowlist = public_origin_allowlist
        self.runtime_activation_validator = (
            runtime_activation_validator or _validate_runtime_activation
        )
        self.attempt_limiter = SetupAttemptLimiter()

    def state(self, *, recover_interrupted: bool = True) -> InstallationState:
        try:
            state = self.store.read_state()
        except SetupStateError as error:
            raise SetupError(
                503,
                "setup.config_write_failed",
                "installation state is unavailable",
            ) from error
        if recover_interrupted and state.installation_state == "initializing":
            try:
                with self.store.install_lock():
                    current = self.store.read_state()
                    if current.installation_state == "initializing":
                        self.store.delete_partial_runtime()
                        return self.store.mark_pending(
                            attempt_id=current.attempt_id,
                            idempotency_key_sha256=current.idempotency_key_sha256,
                            install_request_hmac_sha256=(
                                current.install_request_hmac_sha256
                            ),
                        )
                    return current
            except InstallationInProgressError:
                return state
            except (OSError, SetupStateError) as error:
                raise SetupError(
                    503,
                    "setup.config_write_failed",
                    "installation state is unavailable",
                ) from error
        return state

    def create_session(self, *, setup_code: str, source_ip: str) -> str:
        state = self.state()
        self._ensure_setup_open(state)
        self.attempt_limiter.ensure_allowed(source_ip)
        try:
            auth = self.store.read_setup_auth()
        except SetupStateError as error:
            raise SetupError(
                503,
                "setup.config_write_failed",
                "setup authentication is unavailable",
            ) from error
        if not verify_setup_code(auth, setup_code):
            self.attempt_limiter.record_failure(source_ip)
            raise SetupError(401, "setup.code_invalid", "setup code is invalid")
        self.attempt_limiter.clear(source_ip)
        return build_setup_session_token(auth)

    def require_session(self, token: str) -> None:
        state = self.state()
        self._ensure_setup_open(state)
        try:
            auth = self.store.read_setup_auth()
        except SetupStateError as error:
            raise SetupError(
                503,
                "setup.config_write_failed",
                "setup authentication is unavailable",
            ) from error
        verify_setup_session_token(auth, token)

    def test_database(self, database: DatabaseInput) -> DatabaseValidationResult:
        state = self.state()
        self._ensure_setup_open(state)
        try:
            with self._temporary_ca(database.ca_pem) as ca_path:
                return self.database_validator.validate(
                    database,
                    ca_path=ca_path,
                    interrupted_attempt_id=state.attempt_id,
                )
        except SetupError:
            raise
        except Exception as error:
            raise SetupError(
                422,
                "setup.database_unreachable",
                "database validation failed",
            ) from error

    def install(self, request: InstallInput, *, idempotency_key: str) -> dict[str, str]:
        if _IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key) is None:
            raise SetupError(
                400,
                "setup.idempotency_key_invalid",
                "Idempotency-Key is invalid",
            )
        idempotency_key_sha256 = sha256_text(idempotency_key)
        try:
            setup_auth = self.store.read_setup_auth()
        except SetupStateError as error:
            raise SetupError(
                503,
                "setup.config_write_failed",
                "setup authentication is unavailable",
            ) from error
        request_fingerprint = hmac.new(
            setup_auth.session_secret.encode("utf-8"),
            canonical_json_bytes(
                {
                    "cloud_name": request.cloud_name,
                    "public_base_url": request.public_base_url,
                    "database": {
                        **request.database.connection_components(),
                        "ca_pem": request.database.ca_pem,
                    },
                }
            ),
            hashlib.sha256,
        ).hexdigest()
        try:
            with self.store.install_lock():
                state = self.state(recover_interrupted=False)
                self._ensure_setup_open(state, allow_interrupted=True)
                if (
                    state.idempotency_key_sha256
                    and state.idempotency_key_sha256 != idempotency_key_sha256
                ):
                    raise SetupError(
                        409,
                        "setup.idempotency_key_conflict",
                        "installation retry must reuse its Idempotency-Key",
                    )
                if (
                    state.install_request_hmac_sha256
                    and not hmac.compare_digest(
                        state.install_request_hmac_sha256,
                        request_fingerprint,
                    )
                ):
                    raise SetupError(
                        409,
                        "setup.idempotency_key_conflict",
                        "installation retry payload does not match",
                    )
                attempt_id = state.attempt_id or new_attempt_id()
                self.store.mark_initializing(
                    attempt_id=attempt_id,
                    idempotency_key_sha256=idempotency_key_sha256,
                    install_request_hmac_sha256=request_fingerprint,
                )
                try:
                    return self._install_locked(request, attempt_id=attempt_id)
                except SetupError:
                    self.store.delete_partial_runtime()
                    self.store.mark_pending(
                        attempt_id=attempt_id,
                        idempotency_key_sha256=idempotency_key_sha256,
                        install_request_hmac_sha256=request_fingerprint,
                    )
                    raise
                except Exception as error:
                    self.store.delete_partial_runtime()
                    self.store.mark_pending(
                        attempt_id=attempt_id,
                        idempotency_key_sha256=idempotency_key_sha256,
                        install_request_hmac_sha256=request_fingerprint,
                    )
                    raise SetupError(
                        500,
                        "setup.config_write_failed",
                        "installation could not be completed",
                    ) from error
        except InstallationInProgressError as error:
            raise SetupError(
                409,
                "setup.installation_in_progress",
                "installation is already in progress",
            ) from error

    def _install_locked(self, request: InstallInput, *, attempt_id: str) -> dict[str, str]:
        if self.public_origin_allowlist is not None:
            if not self.public_origin_allowlist:
                raise SetupError(
                    503,
                    "setup.public_origin_unavailable",
                    "setup public origin is unavailable",
                )
            if request.public_base_url not in self.public_origin_allowlist:
                raise SetupError(
                    422,
                    "setup.public_base_url_mismatch",
                    "public base URL does not match this deployment",
                )
        with self._temporary_ca(request.database.ca_pem) as temporary_ca_path:
            validation = self.database_validator.validate(
                request.database,
                ca_path=temporary_ca_path,
                interrupted_attempt_id=attempt_id,
            )
            self.database_validator.ensure_attempt_marker(
                validation.database_url,
                attempt_id=attempt_id,
            )
            self.database_validator.run_migrations(validation.database_url)

        admin_key = generate_prefixed_secret("nca_admin_")
        internal_auth_token = generate_prefixed_secret("nca_internal_")
        runtime_config = self._build_runtime_config(
            request,
            admin_key=admin_key,
        )
        self.store.write_ca(request.database.ca_pem)
        self.store.write_internal_auth_token(internal_auth_token)
        self.store.write_runtime_config(runtime_config)

        from app.core.config import Settings

        settings = Settings(
            **load_runtime_settings_values(
                self.store.config_dir,
                require_complete=False,
            )
        )
        self.runtime_activation_validator(settings)
        digest = runtime_config_digest(runtime_config)
        self.store.delete_setup_auth()
        self.store.mark_complete(config_digest=digest)
        try:
            completed_database_url = load_runtime_settings_values(self.store.config_dir)[
                "database_url"
            ]
            self.database_validator.remove_attempt_marker(str(completed_database_url))
        except Exception:
            # The marker is bounded bootstrap evidence. Runtime activation is safe once
            # migrations, configuration validation, and the complete state are durable.
            pass
        return {"admin_key": admin_key, "next_url": "/admin/login"}

    @staticmethod
    def _build_runtime_config(request: InstallInput, *, admin_key: str) -> dict[str, Any]:
        key_suffix = os.urandom(8).hex()
        database_config = request.database.connection_components()
        database_config["ca_sha256"] = hashlib.sha256(
            request.database.ca_pem.encode("utf-8")
        ).hexdigest()
        return {
            "config_version": "runtime-config-v1",
            "cloud": {
                "name": request.cloud_name,
                "public_base_url": request.public_base_url,
            },
            "database": database_config,
            "security": {
                "internal_auth_token_file": FRONTEND_INTERNAL_TOKEN_FILE,
                "admin_key_sha256": sha256_text(admin_key),
                "admin_session_secret": generate_prefixed_secret("nca_session_"),
                "service_settings_secret": generate_root_secret(),
                "service_settings_encryption_key_id": f"install-service-{key_suffix}",
                "runtime_data_encryption_secret": generate_root_secret(),
                "runtime_data_encryption_key_id": f"install-runtime-{key_suffix}",
                "portal_jwt_secret": generate_prefixed_secret("nca_portal_"),
            },
        }

    @staticmethod
    def _ensure_setup_open(
        state: InstallationState,
        *,
        allow_interrupted: bool = False,
    ) -> None:
        if state.installation_state == "complete":
            raise SetupError(404, "setup.already_complete", "setup is no longer available")
        if (
            state.installation_state == "initializing"
            and not state.retry_allowed
            and not allow_interrupted
        ):
            raise SetupError(
                409,
                "setup.installation_in_progress",
                "installation is already in progress",
            )

    def _temporary_ca(self, ca_pem: str):  # type: ignore[no-untyped-def]
        return _TemporaryCA(self.store.config_dir, ca_pem)


class _TemporaryCA:
    def __init__(self, directory: Path, ca_pem: str) -> None:
        self.directory = directory
        self.ca_pem = ca_pem
        self.path: Path | None = None

    def __enter__(self) -> Path:
        descriptor, raw_path = tempfile.mkstemp(prefix=".rds-ca-probe.", dir=self.directory)
        self.path = Path(raw_path)
        try:
            os.fchmod(descriptor, 0o600)
            content = self.ca_pem.encode("utf-8")
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return self.path

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.path is not None:
            self.path.unlink(missing_ok=True)
