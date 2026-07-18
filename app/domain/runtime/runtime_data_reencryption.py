from __future__ import annotations

import base64
import hashlib
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.db import get_session
from app.core.models import (
    PortalMutationIdempotencyReceipt,
    PortalOAuthState,
    RunRecord,
    Site,
    SiteApiKey,
)
from app.core.secrets import (
    decrypt_runtime_data_plaintext,
    encrypt_runtime_data_plaintext,
    runtime_data_envelope_key_id,
)

MigrationMode = Literal["inventory", "dry-run", "apply", "verify"]

SITE_API_KEY_PURPOSE = "site_api_key_signing_secret"
RUNTIME_CALLBACK_PURPOSE = "runtime_terminal_callback_secret"
ADDON_PAYLOAD_PURPOSE = "wordpress_addon_connection_payload"
PORTAL_IDEMPOTENCY_PURPOSE = "portal_idempotency_response"
RUN_INPUT_PURPOSE = "runtime_execution_input"
RUNTIME_DATA_KINDS = (
    "site_api_key",
    "site_runtime_callback",
    "addon_connection_payload",
    "portal_idempotency_response",
    "runtime_execution_input",
)


class RuntimeDataReencryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeDataCiphertextRecord:
    kind: str
    identifier: str
    purpose: str
    ciphertext: str
    owner: object = field(repr=False, compare=False)

    @property
    def row_identifier(self) -> str:
        return f"{self.kind}:{self.identifier}"


@dataclass(frozen=True)
class LegacyRuntimeDataKey:
    key_id: str
    root_secret: str = field(repr=False, compare=False)


@dataclass(frozen=True)
class RuntimeDataReencryptionReport:
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


def inventory_runtime_data_ciphertexts(
    database_url: str,
    *,
    settings: Settings,
    allowed_legacy_envelope_key_ids: frozenset[str] = frozenset(),
) -> RuntimeDataReencryptionReport:
    with get_session(database_url) as session:
        records = _collect_records(session, lock=False)
        legacy, current = _classify_records(
            records,
            settings=settings,
            allowed_legacy_envelope_key_ids=_normalize_allowed_legacy_envelope_key_ids(
                allowed_legacy_envelope_key_ids,
                current_key_id=str(settings.runtime_data_encryption_key_id or "").strip(),
            ),
        )
        return _build_report(
            mode="inventory",
            records=records,
            legacy=legacy,
            current=current,
            migrated=0,
        )


def dry_run_runtime_data_reencryption(
    database_url: str,
    *,
    settings: Settings,
    legacy_root_secrets: tuple[str, ...],
    legacy_envelope_keys: tuple[LegacyRuntimeDataKey, ...] = (),
) -> RuntimeDataReencryptionReport:
    return _reencrypt_runtime_data(
        database_url,
        settings=settings,
        legacy_root_secrets=legacy_root_secrets,
        legacy_envelope_keys=legacy_envelope_keys,
        apply_changes=False,
        maintenance_confirmed=False,
    )


def apply_runtime_data_reencryption(
    database_url: str,
    *,
    settings: Settings,
    legacy_root_secrets: tuple[str, ...],
    maintenance_confirmed: bool,
    legacy_envelope_keys: tuple[LegacyRuntimeDataKey, ...] = (),
) -> RuntimeDataReencryptionReport:
    if not maintenance_confirmed:
        raise RuntimeDataReencryptionError(
            "apply requires an explicitly confirmed maintenance window"
        )
    return _reencrypt_runtime_data(
        database_url,
        settings=settings,
        legacy_root_secrets=legacy_root_secrets,
        legacy_envelope_keys=legacy_envelope_keys,
        apply_changes=True,
        maintenance_confirmed=True,
    )


def verify_runtime_data_ciphertexts(
    database_url: str,
    *,
    settings: Settings,
) -> RuntimeDataReencryptionReport:
    with get_session(database_url) as session:
        records = _collect_records(session, lock=False)
        legacy, current = _classify_records(records, settings=settings)
        if legacy:
            identifiers = ", ".join(record.row_identifier for record in legacy)
            raise RuntimeDataReencryptionError(
                f"legacy runtime data ciphertext remains for {identifiers}"
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


def _reencrypt_runtime_data(
    database_url: str,
    *,
    settings: Settings,
    legacy_root_secrets: tuple[str, ...],
    legacy_envelope_keys: tuple[LegacyRuntimeDataKey, ...],
    apply_changes: bool,
    maintenance_confirmed: bool,
) -> RuntimeDataReencryptionReport:
    del maintenance_confirmed
    normalized_legacy_roots = tuple(
        secret for raw_secret in legacy_root_secrets if (secret := str(raw_secret or "").strip())
    )
    legacy_envelope_key_map = _normalize_legacy_envelope_keys(
        legacy_envelope_keys,
        current_key_id=str(settings.runtime_data_encryption_key_id or "").strip(),
    )
    with get_session(database_url) as session:
        try:
            with session.begin():
                records = _collect_records(session, lock=apply_changes)
                legacy, current = _classify_records(
                    records,
                    settings=settings,
                    allowed_legacy_envelope_key_ids=frozenset(legacy_envelope_key_map),
                )
                replacement_by_identifier: dict[str, str] = {}

                for record in current:
                    _decrypt_current(record, settings=settings)
                for record in legacy:
                    plaintext = _decrypt_legacy(
                        record,
                        legacy_root_secrets=normalized_legacy_roots,
                        legacy_envelope_key_map=legacy_envelope_key_map,
                    )
                    replacement = encrypt_runtime_data_plaintext(
                        plaintext,
                        purpose=record.purpose,
                        settings=settings,
                    )
                    if (
                        decrypt_runtime_data_plaintext(
                            replacement,
                            purpose=record.purpose,
                            settings=settings,
                        )
                        != plaintext
                    ):
                        raise RuntimeDataReencryptionError(
                            f"round-trip verification failed for {record.row_identifier}"
                        )
                    replacement_by_identifier[record.row_identifier] = replacement

                if apply_changes:
                    for record in legacy:
                        _set_ciphertext(
                            record,
                            replacement_by_identifier[record.row_identifier],
                        )
                    session.flush()

                mode: MigrationMode = "apply" if apply_changes else "dry-run"
                return _build_report(
                    mode=mode,
                    records=records,
                    legacy=legacy,
                    current=current,
                    migrated=len(legacy) if apply_changes else 0,
                )
        except RuntimeDataReencryptionError:
            raise
        except Exception as error:
            raise RuntimeDataReencryptionError("runtime data re-encryption failed") from error


def _collect_records(
    session: Session,
    *,
    lock: bool,
) -> tuple[RuntimeDataCiphertextRecord, ...]:
    records: list[RuntimeDataCiphertextRecord] = []

    site_key_query = select(SiteApiKey).order_by(SiteApiKey.key_id)
    receipt_query = select(PortalMutationIdempotencyReceipt).order_by(
        PortalMutationIdempotencyReceipt.receipt_id
    )
    run_query = select(RunRecord).order_by(RunRecord.run_id)
    site_query = select(Site).order_by(Site.site_id)
    oauth_query = select(PortalOAuthState).order_by(PortalOAuthState.state_id)
    if lock:
        site_key_query = site_key_query.with_for_update()
        receipt_query = receipt_query.with_for_update()
        run_query = run_query.with_for_update()
        site_query = site_query.with_for_update()
        oauth_query = oauth_query.with_for_update()

    for site_api_key in session.scalars(site_key_query):
        ciphertext = str(site_api_key.signing_secret_ciphertext or "").strip()
        if ciphertext:
            records.append(
                RuntimeDataCiphertextRecord(
                    kind="site_api_key",
                    identifier=str(site_api_key.key_id),
                    purpose=SITE_API_KEY_PURPOSE,
                    ciphertext=ciphertext,
                    owner=site_api_key,
                )
            )

    for site in session.scalars(site_query):
        metadata = site.metadata_json if isinstance(site.metadata_json, dict) else {}
        callbacks = metadata.get("runtime_callbacks")
        callbacks = callbacks if isinstance(callbacks, dict) else {}
        terminal = callbacks.get("terminal")
        terminal = terminal if isinstance(terminal, dict) else {}
        ciphertext = str(terminal.get("secret_ciphertext") or "").strip()
        if ciphertext:
            records.append(
                RuntimeDataCiphertextRecord(
                    kind="site_runtime_callback",
                    identifier=str(site.site_id),
                    purpose=RUNTIME_CALLBACK_PURPOSE,
                    ciphertext=ciphertext,
                    owner=site,
                )
            )

    for oauth_state in session.scalars(oauth_query):
        metadata = oauth_state.metadata_json if isinstance(oauth_state.metadata_json, dict) else {}
        ciphertext = str(metadata.get("payload_ciphertext") or "").strip()
        if ciphertext:
            records.append(
                RuntimeDataCiphertextRecord(
                    kind="addon_connection_payload",
                    identifier=str(oauth_state.state_id),
                    purpose=ADDON_PAYLOAD_PURPOSE,
                    ciphertext=ciphertext,
                    owner=oauth_state,
                )
            )

    for receipt in session.scalars(receipt_query):
        ciphertext = str(receipt.response_body_ciphertext or "").strip()
        if ciphertext:
            records.append(
                RuntimeDataCiphertextRecord(
                    kind="portal_idempotency_response",
                    identifier=str(receipt.receipt_id),
                    purpose=PORTAL_IDEMPOTENCY_PURPOSE,
                    ciphertext=ciphertext,
                    owner=receipt,
                )
            )

    for run in session.scalars(run_query):
        ciphertext = str(run.execution_input_ciphertext or "").strip()
        if ciphertext:
            records.append(
                RuntimeDataCiphertextRecord(
                    kind="runtime_execution_input",
                    identifier=str(run.run_id),
                    purpose=RUN_INPUT_PURPOSE,
                    ciphertext=ciphertext,
                    owner=run,
                )
            )

    return tuple(sorted(records, key=lambda record: record.row_identifier))


def _classify_records(
    records: tuple[RuntimeDataCiphertextRecord, ...],
    *,
    settings: Settings,
    allowed_legacy_envelope_key_ids: frozenset[str] = frozenset(),
) -> tuple[tuple[RuntimeDataCiphertextRecord, ...], tuple[RuntimeDataCiphertextRecord, ...]]:
    expected_key_id = str(settings.runtime_data_encryption_key_id or "").strip()
    if not expected_key_id:
        raise RuntimeDataReencryptionError("runtime data encryption key id is not configured")
    legacy: list[RuntimeDataCiphertextRecord] = []
    current: list[RuntimeDataCiphertextRecord] = []
    for record in records:
        envelope_key_id = runtime_data_envelope_key_id(record.ciphertext)
        if envelope_key_id == expected_key_id:
            current.append(record)
            continue
        if envelope_key_id in allowed_legacy_envelope_key_ids:
            legacy.append(record)
            continue
        if record.ciphertext.startswith("rde."):
            raise RuntimeDataReencryptionError(
                f"unsupported runtime data envelope for {record.row_identifier}"
            )
        legacy.append(record)
    return tuple(legacy), tuple(current)


def _decrypt_current(
    record: RuntimeDataCiphertextRecord,
    *,
    settings: Settings,
) -> bytes:
    try:
        return decrypt_runtime_data_plaintext(
            record.ciphertext,
            purpose=record.purpose,
            settings=settings,
        )
    except RuntimeError as error:
        raise RuntimeDataReencryptionError(
            f"current ciphertext could not be decrypted for {record.row_identifier}"
        ) from error


def _decrypt_legacy(
    record: RuntimeDataCiphertextRecord,
    *,
    legacy_root_secrets: tuple[str, ...],
    legacy_envelope_key_map: dict[str, str],
) -> bytes:
    envelope_key_id = runtime_data_envelope_key_id(record.ciphertext)
    if record.ciphertext.startswith("rde."):
        legacy_root_secret = legacy_envelope_key_map.get(str(envelope_key_id or ""))
        if not legacy_root_secret:
            raise RuntimeDataReencryptionError(
                f"unsupported runtime data envelope for {record.row_identifier}"
            )
        _family, _version, _key_id, fernet_token = record.ciphertext.split(".", 3)
        try:
            return _build_legacy_fernet(
                legacy_root_secret,
                purpose=record.purpose,
            ).decrypt(fernet_token.encode("utf-8"))
        except InvalidToken as error:
            raise RuntimeDataReencryptionError(
                f"legacy ciphertext could not be decrypted for {record.row_identifier}"
            ) from error

    for legacy_root_secret in legacy_root_secrets:
        try:
            return _build_legacy_fernet(
                legacy_root_secret,
                purpose=record.purpose,
            ).decrypt(record.ciphertext.encode("utf-8"))
        except InvalidToken:
            continue
    raise RuntimeDataReencryptionError(
        f"legacy ciphertext could not be decrypted for {record.row_identifier}"
    )


def _normalize_legacy_envelope_keys(
    legacy_envelope_keys: tuple[LegacyRuntimeDataKey, ...],
    *,
    current_key_id: str,
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for legacy_key in legacy_envelope_keys:
        key_id = str(legacy_key.key_id or "").strip()
        root_secret = str(legacy_key.root_secret or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key_id):
            raise RuntimeDataReencryptionError("old runtime data key id is invalid")
        if key_id == current_key_id:
            raise RuntimeDataReencryptionError(
                "old runtime data key id must differ from the active key id"
            )
        if not root_secret:
            raise RuntimeDataReencryptionError(
                f"old runtime data root is missing for key id {key_id}"
            )
        if key_id in normalized:
            raise RuntimeDataReencryptionError(f"old runtime data key id is duplicated: {key_id}")
        normalized[key_id] = root_secret
    return normalized


def _normalize_allowed_legacy_envelope_key_ids(
    key_ids: frozenset[str],
    *,
    current_key_id: str,
) -> frozenset[str]:
    normalized: set[str] = set()
    for raw_key_id in key_ids:
        key_id = str(raw_key_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", key_id):
            raise RuntimeDataReencryptionError("old runtime data key id is invalid")
        if key_id == current_key_id:
            raise RuntimeDataReencryptionError(
                "old runtime data key id must differ from the active key id"
            )
        normalized.add(key_id)
    return frozenset(normalized)


def _set_ciphertext(record: RuntimeDataCiphertextRecord, ciphertext: str) -> None:
    if record.kind == "site_api_key":
        assert isinstance(record.owner, SiteApiKey)
        record.owner.signing_secret_ciphertext = ciphertext
        return
    if record.kind == "site_runtime_callback":
        assert isinstance(record.owner, Site)
        metadata = deepcopy(record.owner.metadata_json or {})
        callbacks = dict(metadata.get("runtime_callbacks") or {})
        terminal = dict(callbacks.get("terminal") or {})
        terminal["secret_ciphertext"] = ciphertext
        callbacks["terminal"] = terminal
        metadata["runtime_callbacks"] = callbacks
        record.owner.metadata_json = metadata
        return
    if record.kind == "addon_connection_payload":
        assert isinstance(record.owner, PortalOAuthState)
        metadata = deepcopy(record.owner.metadata_json or {})
        metadata["payload_ciphertext"] = ciphertext
        record.owner.metadata_json = metadata
        return
    if record.kind == "portal_idempotency_response":
        assert isinstance(record.owner, PortalMutationIdempotencyReceipt)
        record.owner.response_body_ciphertext = ciphertext
        return
    if record.kind == "runtime_execution_input":
        assert isinstance(record.owner, RunRecord)
        record.owner.execution_input_ciphertext = ciphertext
        return
    raise RuntimeDataReencryptionError(f"unsupported ciphertext record {record.row_identifier}")


def _build_legacy_fernet(root_secret: str, *, purpose: str) -> Fernet:
    derived_key = hashlib.sha256(f"{purpose}:{root_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived_key))


def _build_report(
    *,
    mode: MigrationMode,
    records: tuple[RuntimeDataCiphertextRecord, ...],
    legacy: tuple[RuntimeDataCiphertextRecord, ...],
    current: tuple[RuntimeDataCiphertextRecord, ...],
    migrated: int,
) -> RuntimeDataReencryptionReport:
    reported_legacy = 0 if mode == "apply" else len(legacy)
    reported_current = len(current) + len(legacy) if mode == "apply" else len(current)
    return RuntimeDataReencryptionReport(
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
    records: tuple[RuntimeDataCiphertextRecord, ...],
    legacy: tuple[RuntimeDataCiphertextRecord, ...],
    current: tuple[RuntimeDataCiphertextRecord, ...],
    migrated: int,
    mode: MigrationMode,
) -> dict[str, dict[str, int]]:
    legacy_counts = {kind: 0 for kind in RUNTIME_DATA_KINDS}
    current_counts = {kind: 0 for kind in RUNTIME_DATA_KINDS}
    total_counts = {kind: 0 for kind in RUNTIME_DATA_KINDS}
    for record in records:
        total_counts[record.kind] += 1
    for record in legacy:
        legacy_counts[record.kind] += 1
    for record in current:
        current_counts[record.kind] += 1
    if mode == "apply":
        for kind in RUNTIME_DATA_KINDS:
            current_counts[kind] += legacy_counts[kind]
    return {
        kind: {
            "total": total_counts[kind],
            "legacy": 0 if mode == "apply" else legacy_counts[kind],
            "current": current_counts[kind],
            "would_migrate": legacy_counts[kind],
            "migrated": legacy_counts[kind] if migrated else 0,
        }
        for kind in RUNTIME_DATA_KINDS
    }
