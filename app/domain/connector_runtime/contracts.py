from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

CONNECTOR_RUNTIME_ABILITY = "npcink-cloud/connector-runtime"
CONNECTOR_RUNTIME_ABILITIES = frozenset({CONNECTOR_RUNTIME_ABILITY})
CONNECTOR_RUNTIME_CONTRACT = "cloud_connector_runtime.v1"
CONNECTOR_RUNTIME_RESULT_CONTRACT = "cloud_connector_result.v1"
CONNECTOR_RUNTIME_CHANNEL = "editor"
CONNECTOR_ID = "npcink-cloud-addon"
CONNECTOR_PLATFORM_KIND = "wordpress"

CONNECTOR_RUNTIME_MAX_SITE_URL_CHARS = 2048
CONNECTOR_RUNTIME_MAX_CONNECTOR_VERSION_CHARS = 64
CONNECTOR_RUNTIME_MAX_OBJECT_TYPE_CHARS = 64
CONNECTOR_RUNTIME_MAX_OBJECT_ID_CHARS = 191
CONNECTOR_RUNTIME_MAX_OBJECT_REVISION_CHARS = 191

CONNECTOR_RUNTIME_REQUIRED_FIELDS = frozenset(
    {
        "site_url",
        "platform_kind",
        "connector_id",
        "connector_version",
        "suggestion_only",
        "operation_contract",
    }
)
CONNECTOR_RUNTIME_ALLOWED_FIELDS = CONNECTOR_RUNTIME_REQUIRED_FIELDS | {"object_ref"}
CONNECTOR_OBJECT_REF_FIELDS = frozenset(
    {"object_type", "object_id", "object_revision"}
)


class ConnectorRuntimeContractViolation(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_connector_runtime_envelope(
    *,
    ability_name: str,
    contract_version: str,
    input_payload: dict[str, Any],
) -> dict[str, Any]:
    if ability_name not in CONNECTOR_RUNTIME_ABILITIES:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.unknown_ability",
            "connector runtime ability_name is not supported",
        )
    if contract_version != CONNECTOR_RUNTIME_CONTRACT:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.contract_mismatch",
            "connector runtime contract_version does not match ability_name",
        )
    if not isinstance(input_payload, dict):
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.invalid_input",
            "connector runtime input must be an object",
        )

    fields = set(input_payload)
    missing_fields = CONNECTOR_RUNTIME_REQUIRED_FIELDS - fields
    if missing_fields:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.fields_required",
            "connector runtime input is missing required fields: "
            + ", ".join(sorted(missing_fields)),
        )
    unknown_fields = fields - CONNECTOR_RUNTIME_ALLOWED_FIELDS
    if unknown_fields:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.fields_forbidden",
            "connector runtime input contains unsupported fields: "
            + ", ".join(sorted(unknown_fields)),
        )

    site_url = _bounded_string(
        input_payload.get("site_url"),
        field_name="site_url",
        max_chars=CONNECTOR_RUNTIME_MAX_SITE_URL_CHARS,
    )
    parsed_site_url = urlsplit(site_url)
    if (
        parsed_site_url.scheme not in {"http", "https"}
        or not parsed_site_url.hostname
        or parsed_site_url.username
        or parsed_site_url.password
        or parsed_site_url.query
        or parsed_site_url.fragment
    ):
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.site_url_invalid",
            "connector runtime site_url must be a canonical http(s) site URL",
        )

    if input_payload.get("platform_kind") != CONNECTOR_PLATFORM_KIND:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.platform_kind_invalid",
            "connector runtime currently accepts platform_kind=wordpress only",
        )
    if input_payload.get("connector_id") != CONNECTOR_ID:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.connector_id_invalid",
            f"connector runtime requires connector_id={CONNECTOR_ID}",
        )
    connector_version = _bounded_string(
        input_payload.get("connector_version"),
        field_name="connector_version",
        max_chars=CONNECTOR_RUNTIME_MAX_CONNECTOR_VERSION_CHARS,
    )
    if input_payload.get("suggestion_only") is not True:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.suggestion_only_required",
            "connector runtime requires suggestion_only=true",
        )

    operation_contract = input_payload.get("operation_contract")
    if not isinstance(operation_contract, dict):
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.operation_contract_required",
            "connector runtime requires an operation_contract object",
        )

    normalized: dict[str, Any] = {
        "site_url": site_url,
        "platform_kind": CONNECTOR_PLATFORM_KIND,
        "connector_id": CONNECTOR_ID,
        "connector_version": connector_version,
        "suggestion_only": True,
        "operation_contract": dict(operation_contract),
    }
    if "object_ref" in input_payload:
        normalized["object_ref"] = validate_connector_object_ref(
            input_payload.get("object_ref")
        )
    return normalized


def validate_connector_object_ref(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.object_ref_invalid",
            "connector runtime object_ref must be an object",
        )
    if set(value) != CONNECTOR_OBJECT_REF_FIELDS:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.object_ref_fields_invalid",
            "connector runtime object_ref requires exactly object_type, object_id, "
            "and object_revision",
        )
    return {
        "object_type": _bounded_string(
            value.get("object_type"),
            field_name="object_ref.object_type",
            max_chars=CONNECTOR_RUNTIME_MAX_OBJECT_TYPE_CHARS,
        ),
        "object_id": _bounded_string(
            value.get("object_id"),
            field_name="object_ref.object_id",
            max_chars=CONNECTOR_RUNTIME_MAX_OBJECT_ID_CHARS,
        ),
        "object_revision": _bounded_string(
            value.get("object_revision"),
            field_name="object_ref.object_revision",
            max_chars=CONNECTOR_RUNTIME_MAX_OBJECT_REVISION_CHARS,
        ),
    }


def validate_connector_site_binding(
    envelope: dict[str, Any],
    *,
    site_url: str,
    platform_kind: str,
) -> None:
    if str(envelope.get("site_url") or "") != str(site_url or "").strip():
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.site_url_mismatch",
            "connector runtime site_url does not match the authenticated site",
        )
    if str(envelope.get("platform_kind") or "") != str(platform_kind or "").strip():
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.platform_kind_mismatch",
            "connector runtime platform_kind does not match the authenticated site",
        )


def build_connector_result_envelope(
    *,
    site_id: str,
    connector_envelope: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    operation_contract = connector_envelope.get("operation_contract")
    operation_contract = (
        operation_contract if isinstance(operation_contract, dict) else {}
    )
    result: dict[str, Any] = {
        "contract_version": CONNECTOR_RUNTIME_RESULT_CONTRACT,
        "site_id": site_id,
        "site_url": str(connector_envelope.get("site_url") or ""),
        "platform_kind": str(connector_envelope.get("platform_kind") or ""),
        "connector_id": str(connector_envelope.get("connector_id") or ""),
        "connector_version": str(connector_envelope.get("connector_version") or ""),
        "suggestion_only": True,
        "operation_contract": {
            "contract_version": str(operation_contract.get("contract_version") or ""),
            "task": str(operation_contract.get("task") or ""),
        },
        "output": dict(output),
    }
    object_ref = connector_envelope.get("object_ref")
    if isinstance(object_ref, dict):
        result["object_ref"] = dict(object_ref)
    return result


def _bounded_string(value: Any, *, field_name: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.string_field_invalid",
            f"connector runtime {field_name} must be a string",
        )
    normalized = value.strip()
    if not normalized or len(normalized) > max_chars:
        raise ConnectorRuntimeContractViolation(
            "connector_runtime.string_field_invalid",
            f"connector runtime {field_name} must be nonempty and at most {max_chars} characters",
        )
    return normalized
