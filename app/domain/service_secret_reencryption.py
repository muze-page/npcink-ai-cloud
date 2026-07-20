from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal

from cryptography.fernet import InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import get_session
from app.core.models import ProviderConnection, ServiceSetting
from app.core.secrets import (
    decrypt_provider_connection_secret,
    decrypt_service_setting_secret,
    encrypt_provider_connection_secret,
    encrypt_service_setting_secret,
    service_secret_envelope_key_id,
)
from app.domain.runtime.runtime_data_reencryption import _build_legacy_fernet

MigrationMode = Literal["inventory", "dry-run", "apply", "verify"]

PROVIDER_CONNECTION_SECRET = "provider_connection_secret"
SERVICE_SETTING_SECRET = "service_setting_secret"
SERVICE_SECRET_KINDS = (
    PROVIDER_CONNECTION_SECRET,
    SERVICE_SETTING_SECRET,
)
_ENCRYPTION_KEY_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


class ServiceSecretReencryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServiceSecretCiphertextRecord:
    kind: str
    identifier: str
    purpose: str
    ciphertext: str = field(repr=False, compare=False)
    owner: ProviderConnection | ServiceSetting = field(repr=False, compare=False)
    entry_key: str | None = None

    @property
    def row_identifier(self) -> str:
        suffix = f":{self.entry_key}" if self.entry_key is not None else ""
        return f"{self.kind}:{self.identifier}{suffix}"


@dataclass(frozen=True)
class ServiceSecretReencryptionReport:
    mode: MigrationMode
    total: int
    legacy: int
    current: int
    migrated: int
    would_migrate: int
    counts_by_kind: dict[str, dict[str, int]]
    row_identifiers: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "total": self.total,
            "legacy": self.legacy,
            "current": self.current,
            "migrated": self.migrated,
            "would_migrate": self.would_migrate,
            "counts_by_kind": self.counts_by_kind,
            "row_identifiers": list(self.row_identifiers),
        }


def inventory_service_secret_ciphertexts(
    database_url: str,
    *,
    settings: Settings,
) -> ServiceSecretReencryptionReport:
    with get_session(database_url) as session:
        records = _collect_records(session, lock=False)
        legacy, current = _classify_records(records, settings=settings)
        for record in current:
            _decrypt_current(record, settings=settings)
        return _build_report(
            mode="inventory",
            records=records,
            legacy=legacy,
            current=current,
            migrated=0,
        )


def dry_run_service_secret_reencryption(
    database_url: str,
    *,
    settings: Settings,
    legacy_root_secrets: tuple[str, ...],
) -> ServiceSecretReencryptionReport:
    return _reencrypt_service_secrets(
        database_url,
        settings=settings,
        legacy_root_secrets=legacy_root_secrets,
        apply_changes=False,
    )


def apply_service_secret_reencryption(
    database_url: str,
    *,
    settings: Settings,
    legacy_root_secrets: tuple[str, ...],
    maintenance_confirmed: bool,
) -> ServiceSecretReencryptionReport:
    if not maintenance_confirmed:
        raise ServiceSecretReencryptionError(
            "apply requires an explicitly confirmed maintenance window"
        )
    return _reencrypt_service_secrets(
        database_url,
        settings=settings,
        legacy_root_secrets=legacy_root_secrets,
        apply_changes=True,
    )


def verify_service_secret_ciphertexts(
    database_url: str,
    *,
    settings: Settings,
) -> ServiceSecretReencryptionReport:
    with get_session(database_url) as session:
        records = _collect_records(session, lock=False)
        legacy, current = _classify_records(records, settings=settings)
        if legacy:
            identifiers = ", ".join(record.row_identifier for record in legacy)
            raise ServiceSecretReencryptionError(
                f"legacy service secret ciphertext remains for {identifiers}"
            )
        for record in current:
            _decrypt_current(record, settings=settings)
        return _build_report(
            mode="verify",
            records=records,
            legacy=(),
            current=current,
            migrated=0,
        )


def _reencrypt_service_secrets(
    database_url: str,
    *,
    settings: Settings,
    legacy_root_secrets: tuple[str, ...],
    apply_changes: bool,
) -> ServiceSecretReencryptionReport:
    normalized_legacy_roots = tuple(
        secret
        for raw_secret in legacy_root_secrets
        if (secret := str(raw_secret or "").strip())
    )
    with get_session(database_url) as session:
        try:
            with session.begin():
                records = _collect_records(session, lock=apply_changes)
                legacy, current = _classify_records(records, settings=settings)
                replacements: dict[str, str] = {}

                for record in current:
                    _decrypt_current(record, settings=settings)
                for record in legacy:
                    plaintext = _decrypt_legacy(
                        record,
                        legacy_root_secrets=normalized_legacy_roots,
                    )
                    replacement = _encrypt_current(
                        record,
                        plaintext=plaintext,
                        settings=settings,
                    )
                    if (
                        service_secret_envelope_key_id(replacement)
                        != _active_key_id(settings)
                        or _decrypt_current_ciphertext(
                            record,
                            ciphertext=replacement,
                            settings=settings,
                        )
                        != plaintext
                    ):
                        raise ServiceSecretReencryptionError(
                            f"round-trip verification failed for {record.row_identifier}"
                        )
                    replacements[record.row_identifier] = replacement

                if apply_changes:
                    for record in legacy:
                        _set_ciphertext(record, replacements[record.row_identifier])
                    session.flush()

                mode: MigrationMode = "apply" if apply_changes else "dry-run"
                return _build_report(
                    mode=mode,
                    records=records,
                    legacy=legacy,
                    current=current,
                    migrated=len(legacy) if apply_changes else 0,
                )
        except ServiceSecretReencryptionError:
            raise
        except Exception:
            raise ServiceSecretReencryptionError(
                "service secret re-encryption failed"
            ) from None


def _collect_records(
    session: Session,
    *,
    lock: bool,
) -> tuple[ServiceSecretCiphertextRecord, ...]:
    records: list[ServiceSecretCiphertextRecord] = []
    provider_query = select(ProviderConnection).order_by(ProviderConnection.connection_id)
    service_query = select(ServiceSetting).order_by(ServiceSetting.setting_id)
    if lock:
        provider_query = provider_query.with_for_update()
        service_query = service_query.with_for_update()

    for provider in session.scalars(provider_query):
        ciphertext = str(provider.secret_ciphertext or "").strip()
        if ciphertext:
            records.append(
                ServiceSecretCiphertextRecord(
                    kind=PROVIDER_CONNECTION_SECRET,
                    identifier=str(provider.connection_id),
                    purpose=PROVIDER_CONNECTION_SECRET,
                    ciphertext=ciphertext,
                    owner=provider,
                )
            )

    for service_setting in session.scalars(service_query):
        secret_map = (
            service_setting.secret_ciphertext_json
            if isinstance(service_setting.secret_ciphertext_json, dict)
            else {}
        )
        for entry_key in sorted(str(key) for key in secret_map):
            ciphertext = str(secret_map.get(entry_key) or "").strip()
            if ciphertext:
                records.append(
                    ServiceSecretCiphertextRecord(
                        kind=SERVICE_SETTING_SECRET,
                        identifier=str(service_setting.setting_id),
                        purpose=SERVICE_SETTING_SECRET,
                        ciphertext=ciphertext,
                        owner=service_setting,
                        entry_key=entry_key,
                    )
                )

    return tuple(sorted(records, key=lambda record: record.row_identifier))


def _classify_records(
    records: tuple[ServiceSecretCiphertextRecord, ...],
    *,
    settings: Settings,
) -> tuple[
    tuple[ServiceSecretCiphertextRecord, ...],
    tuple[ServiceSecretCiphertextRecord, ...],
]:
    active_key_id = _active_key_id(settings)
    legacy: list[ServiceSecretCiphertextRecord] = []
    current: list[ServiceSecretCiphertextRecord] = []
    for record in records:
        envelope_key_id = service_secret_envelope_key_id(record.ciphertext)
        if envelope_key_id == active_key_id:
            current.append(record)
            continue
        if record.ciphertext.startswith("sse."):
            raise ServiceSecretReencryptionError(
                f"unsupported service secret envelope for {record.row_identifier}"
            )
        legacy.append(record)
    return tuple(legacy), tuple(current)


def _active_key_id(settings: Settings) -> str:
    key_id = str(settings.service_settings_encryption_key_id or "")
    if not key_id:
        raise ServiceSecretReencryptionError(
            "service settings encryption key id is not configured"
        )
    if key_id != key_id.strip() or _ENCRYPTION_KEY_ID_PATTERN.fullmatch(key_id) is None:
        raise ServiceSecretReencryptionError(
            "service settings encryption key id is invalid"
        )
    return key_id


def _decrypt_current(
    record: ServiceSecretCiphertextRecord,
    *,
    settings: Settings,
) -> str:
    try:
        return _decrypt_current_ciphertext(
            record,
            ciphertext=record.ciphertext,
            settings=settings,
        )
    except (RuntimeError, UnicodeDecodeError):
        raise ServiceSecretReencryptionError(
            f"current ciphertext could not be decrypted for {record.row_identifier}"
        ) from None


def _decrypt_current_ciphertext(
    record: ServiceSecretCiphertextRecord,
    *,
    ciphertext: str,
    settings: Settings,
) -> str:
    if record.kind == PROVIDER_CONNECTION_SECRET:
        return decrypt_provider_connection_secret(ciphertext, settings=settings)
    if record.kind == SERVICE_SETTING_SECRET:
        return decrypt_service_setting_secret(ciphertext, settings=settings)
    raise ServiceSecretReencryptionError(
        f"unsupported ciphertext record {record.row_identifier}"
    )


def _decrypt_legacy(
    record: ServiceSecretCiphertextRecord,
    *,
    legacy_root_secrets: tuple[str, ...],
) -> str:
    for legacy_root_secret in legacy_root_secrets:
        try:
            plaintext = _build_legacy_fernet(
                legacy_root_secret,
                purpose=record.purpose,
            ).decrypt(record.ciphertext.encode("utf-8"))
        except InvalidToken:
            continue
        try:
            return plaintext.decode("utf-8")
        except UnicodeDecodeError:
            break
    raise ServiceSecretReencryptionError(
        f"legacy ciphertext could not be decrypted for {record.row_identifier}"
    )


def _encrypt_current(
    record: ServiceSecretCiphertextRecord,
    *,
    plaintext: str,
    settings: Settings,
) -> str:
    if record.kind == PROVIDER_CONNECTION_SECRET:
        return encrypt_provider_connection_secret(plaintext, settings=settings)
    if record.kind == SERVICE_SETTING_SECRET:
        return encrypt_service_setting_secret(plaintext, settings=settings)
    raise ServiceSecretReencryptionError(
        f"unsupported ciphertext record {record.row_identifier}"
    )


def _set_ciphertext(record: ServiceSecretCiphertextRecord, ciphertext: str) -> None:
    if record.kind == PROVIDER_CONNECTION_SECRET:
        assert isinstance(record.owner, ProviderConnection)
        record.owner.secret_ciphertext = ciphertext
        return
    if record.kind == SERVICE_SETTING_SECRET:
        assert isinstance(record.owner, ServiceSetting)
        assert record.entry_key is not None
        secret_map = deepcopy(record.owner.secret_ciphertext_json or {})
        secret_map[record.entry_key] = ciphertext
        record.owner.secret_ciphertext_json = secret_map
        return
    raise ServiceSecretReencryptionError(
        f"unsupported ciphertext record {record.row_identifier}"
    )


def _build_report(
    *,
    mode: MigrationMode,
    records: tuple[ServiceSecretCiphertextRecord, ...],
    legacy: tuple[ServiceSecretCiphertextRecord, ...],
    current: tuple[ServiceSecretCiphertextRecord, ...],
    migrated: int,
) -> ServiceSecretReencryptionReport:
    reported_legacy = 0 if mode == "apply" else len(legacy)
    reported_current = len(current) + len(legacy) if mode == "apply" else len(current)
    return ServiceSecretReencryptionReport(
        mode=mode,
        total=len(records),
        legacy=reported_legacy,
        current=reported_current,
        migrated=migrated,
        would_migrate=len(legacy),
        counts_by_kind=_build_counts_by_kind(
            records=records,
            legacy=legacy,
            current=current,
            migrated=migrated,
            mode=mode,
        ),
        row_identifiers=tuple(record.row_identifier for record in records),
    )


def _build_counts_by_kind(
    *,
    records: tuple[ServiceSecretCiphertextRecord, ...],
    legacy: tuple[ServiceSecretCiphertextRecord, ...],
    current: tuple[ServiceSecretCiphertextRecord, ...],
    migrated: int,
    mode: MigrationMode,
) -> dict[str, dict[str, int]]:
    legacy_counts = {kind: 0 for kind in SERVICE_SECRET_KINDS}
    current_counts = {kind: 0 for kind in SERVICE_SECRET_KINDS}
    total_counts = {kind: 0 for kind in SERVICE_SECRET_KINDS}
    for record in records:
        total_counts[record.kind] += 1
    for record in legacy:
        legacy_counts[record.kind] += 1
    for record in current:
        current_counts[record.kind] += 1
    if mode == "apply":
        for kind in SERVICE_SECRET_KINDS:
            current_counts[kind] += legacy_counts[kind]
    return {
        kind: {
            "total": total_counts[kind],
            "legacy": 0 if mode == "apply" else legacy_counts[kind],
            "current": current_counts[kind],
            "would_migrate": legacy_counts[kind],
            "migrated": legacy_counts[kind] if migrated else 0,
        }
        for kind in SERVICE_SECRET_KINDS
    }
