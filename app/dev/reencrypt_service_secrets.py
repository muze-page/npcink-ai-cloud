from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Sequence

from pydantic import ValidationError

from app.core.config import Settings
from app.domain.service_secret_reencryption import (
    ServiceSecretReencryptionError,
    ServiceSecretReencryptionReport,
    apply_service_secret_reencryption,
    dry_run_service_secret_reencryption,
    inventory_service_secret_ciphertexts,
    verify_service_secret_ciphertexts,
)

_ENVIRONMENT_VARIABLE_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory and one-time re-encrypt persisted service secrets."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "inventory",
        help="Classify every non-empty service secret without writing changes.",
    )

    dry_run_parser = subparsers.add_parser(
        "dry-run",
        help="Decrypt and round-trip every service secret in memory without writing.",
    )
    _add_old_root_arguments(dry_run_parser)

    apply_parser = subparsers.add_parser(
        "apply",
        help="Re-encrypt every legacy service secret in one database transaction.",
    )
    _add_old_root_arguments(apply_parser)
    apply_parser.add_argument(
        "--confirm-maintenance-window",
        action="store_true",
        help="Confirm that all service-secret writers have been stopped.",
    )

    subparsers.add_parser(
        "verify",
        help="Require every service secret to decrypt with the active envelope.",
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
            message="service secret re-encryption configuration is invalid\n",
        )
    except ServiceSecretReencryptionError as error:
        parser.exit(status=1, message=f"service secret re-encryption failed: {error}\n")
    print(json.dumps(report.as_dict(), ensure_ascii=True, sort_keys=True))
    return 0


def _run_command(
    args: argparse.Namespace,
    *,
    settings: Settings,
) -> ServiceSecretReencryptionReport:
    if args.command == "inventory":
        return inventory_service_secret_ciphertexts(
            settings.database_url,
            settings=settings,
        )
    if args.command == "dry-run":
        return dry_run_service_secret_reencryption(
            settings.database_url,
            settings=settings,
            legacy_root_secrets=_resolve_old_roots(args.old_root_env),
        )
    if args.command == "apply":
        return apply_service_secret_reencryption(
            settings.database_url,
            settings=settings,
            legacy_root_secrets=_resolve_old_roots(args.old_root_env),
            maintenance_confirmed=bool(args.confirm_maintenance_window),
        )
    if args.command == "verify":
        return verify_service_secret_ciphertexts(
            settings.database_url,
            settings=settings,
        )
    raise ServiceSecretReencryptionError(f"unsupported command: {args.command}")


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


def _resolve_old_roots(environment_names: Sequence[str]) -> tuple[str, ...]:
    roots: list[str] = []
    for raw_name in environment_names:
        name = str(raw_name or "").strip()
        if not name:
            raise ServiceSecretReencryptionError(
                "old root environment variable name is empty"
            )
        if _ENVIRONMENT_VARIABLE_NAME_PATTERN.fullmatch(name) is None:
            raise ServiceSecretReencryptionError(
                "old root environment variable name is invalid"
            )
        value = str(os.environ.get(name, "")).strip()
        if not value:
            raise ServiceSecretReencryptionError(
                f"old root environment variable is missing or empty: {name}"
            )
        roots.append(value)
    return tuple(roots)


if __name__ == "__main__":
    raise SystemExit(main())
