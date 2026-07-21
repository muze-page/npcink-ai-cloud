from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence

from pydantic import ValidationError

from app.core.config import Settings
from app.domain.runtime.runtime_data_reencryption import (
    LegacyRuntimeDataKey,
    RuntimeDataReencryptionError,
    RuntimeDataReencryptionReport,
    apply_runtime_data_reencryption,
    dry_run_runtime_data_reencryption,
    inventory_runtime_data_ciphertexts,
    verify_runtime_data_ciphertexts,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory and one-time re-encrypt persisted runtime data ciphertexts."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory_parser = subparsers.add_parser(
        "inventory",
        help="List counts and row identifiers without decrypting.",
    )
    _add_old_key_id_argument(
        inventory_parser,
        help_text=(
            "Explicitly classify one historical rde.v1 key id as expected legacy data. "
            "No old root is read by inventory."
        ),
    )

    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Decrypt every ciphertext in memory without writing changes.",
    )
    _add_old_root_arguments(dry_run_parser)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Re-encrypt every legacy ciphertext in one database transaction.",
    )
    _add_old_root_arguments(apply_parser)
    apply_parser.add_argument(
        "--confirm-maintenance-window",
        action="store_true",
        help="Confirm that all runtime-data writers have been stopped.",
    )

    subparsers.add_parser(
        "verify",
        help="Require every non-empty ciphertext to use and decrypt with the active envelope.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        report = _run_command(args, settings=settings)
    except ValidationError:
        parser.exit(
            status=1,
            message="runtime data re-encryption configuration is invalid\n",
        )
    except RuntimeDataReencryptionError as error:
        parser.exit(status=1, message=f"runtime data re-encryption failed: {error}\n")
    print(json.dumps(report.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0


def _run_command(
    args: argparse.Namespace,
    *,
    settings: Settings,
) -> RuntimeDataReencryptionReport:
    if args.command == "inventory":
        return inventory_runtime_data_ciphertexts(
            settings.database_url,
            settings=settings,
            allowed_legacy_envelope_key_ids=frozenset(args.old_key_id),
        )
    if args.command == "dry-run":
        old_roots = _resolve_old_roots(args.old_root_env)
        return dry_run_runtime_data_reencryption(
            settings.database_url,
            settings=settings,
            legacy_root_secrets=old_roots,
            legacy_envelope_keys=_resolve_legacy_envelope_keys(
                args.old_key_id,
                old_roots,
            ),
        )
    if args.command == "apply":
        old_roots = _resolve_old_roots(args.old_root_env)
        return apply_runtime_data_reencryption(
            settings.database_url,
            settings=settings,
            legacy_root_secrets=old_roots,
            legacy_envelope_keys=_resolve_legacy_envelope_keys(
                args.old_key_id,
                old_roots,
            ),
            maintenance_confirmed=bool(args.confirm_maintenance_window),
        )
    if args.command == "verify":
        return verify_runtime_data_ciphertexts(
            settings.database_url,
            settings=settings,
        )
    raise RuntimeDataReencryptionError(f"unsupported command: {args.command}")


def _add_old_root_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--old-root-env",
        action="append",
        required=True,
        help=(
            "Name of an environment variable containing one historical root secret. "
            "Repeat only when preflight identifies multiple historical roots."
        ),
    )
    _add_old_key_id_argument(
        parser,
        help_text=(
            "Explicitly allow one historical rde.v1 key id, paired by position with "
            "--old-root-env. Repeat both options together for multiple old envelopes."
        ),
    )


def _add_old_key_id_argument(
    parser: argparse.ArgumentParser,
    *,
    help_text: str,
) -> None:
    parser.add_argument(
        "--old-key-id",
        action="append",
        default=[],
        help=help_text,
    )


def _resolve_old_roots(environment_names: Sequence[str]) -> tuple[str, ...]:
    roots: list[str] = []
    for raw_name in environment_names:
        name = str(raw_name or "").strip()
        if not name:
            raise RuntimeDataReencryptionError("old root environment variable name is empty")
        value = str(os.environ.get(name, "")).strip()
        if not value:
            raise RuntimeDataReencryptionError(
                f"old root environment variable is missing or empty: {name}"
            )
        roots.append(value)
    return tuple(roots)


def _resolve_legacy_envelope_keys(
    key_ids: Sequence[str],
    roots: tuple[str, ...],
) -> tuple[LegacyRuntimeDataKey, ...]:
    if not key_ids:
        return ()
    if len(key_ids) != len(roots):
        raise RuntimeDataReencryptionError(
            "each old key id must have one matching old root environment variable"
        )
    return tuple(
        LegacyRuntimeDataKey(key_id=str(key_id or "").strip(), root_secret=root_secret)
        for key_id, root_secret in zip(key_ids, roots, strict=True)
    )


if __name__ == "__main__":
    raise SystemExit(main())
