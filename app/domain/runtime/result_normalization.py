from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.models import RunRecord
from app.domain.connector_runtime.contracts import build_connector_result_envelope
from app.domain.runtime.analysis_result import build_analysis_result_envelope
from app.domain.runtime.models import RUNTIME_STORAGE_MODE_NO_STORE

_TRANSIENT_RESULT_JSON_ATTR = "_transient_result_json"


@dataclass(frozen=True, slots=True)
class RuntimeResultNormalizationCommand:
    site_id: str
    provider_output: dict[str, Any]
    storage_mode: str
    ability_family: str
    ability_name: str
    input_payload: dict[str, Any]
    connector_envelope: dict[str, Any] | None = None
    automatic_web_search: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RuntimeNormalizedResult:
    durable_result: dict[str, Any]
    transient_result: dict[str, Any] | None


class RuntimeResultNormalizationService:
    def normalize(
        self,
        command: RuntimeResultNormalizationCommand,
    ) -> RuntimeNormalizedResult:
        provider_output = command.provider_output
        if command.connector_envelope is not None and isinstance(
            command.automatic_web_search,
            dict,
        ):
            provider_output = dict(provider_output)
            provider_output["automatic_web_search"] = command.automatic_web_search

        response_output = provider_output
        if command.connector_envelope is not None:
            response_output = build_connector_result_envelope(
                site_id=command.site_id,
                connector_envelope=command.connector_envelope,
                output=provider_output,
            )

        if command.connector_envelope is not None:
            prepared_output = self._prepare_result_for_storage(
                provider_output,
                storage_mode=command.storage_mode,
            )
            prepared_result = build_connector_result_envelope(
                site_id=command.site_id,
                connector_envelope=command.connector_envelope,
                output=prepared_output,
            )
        else:
            prepared_result = self._prepare_result_for_storage(
                response_output,
                storage_mode=command.storage_mode,
            )

        transient_result = (
            response_output if command.storage_mode == RUNTIME_STORAGE_MODE_NO_STORE else None
        )
        if command.connector_envelope is None and isinstance(
            command.automatic_web_search,
            dict,
        ):
            prepared_result = dict(prepared_result)
            prepared_result["automatic_web_search"] = command.automatic_web_search

        durable_result = build_analysis_result_envelope(
            prepared_result,
            ability_family=command.ability_family,
            ability_name=command.ability_name,
            input_payload=command.input_payload,
        )
        return RuntimeNormalizedResult(
            durable_result=durable_result,
            transient_result=transient_result,
        )

    @staticmethod
    def _prepare_result_for_storage(
        result_json: dict[str, Any],
        *,
        storage_mode: str,
    ) -> dict[str, Any]:
        if storage_mode == RUNTIME_STORAGE_MODE_NO_STORE:
            return {
                "stored": False,
                "status": "omitted",
            }
        return result_json if isinstance(result_json, dict) else {}


def set_transient_runtime_result(
    run: RunRecord,
    result_json: dict[str, Any],
) -> None:
    setattr(run, _TRANSIENT_RESULT_JSON_ATTR, result_json)


def get_transient_runtime_result(run: RunRecord) -> dict[str, Any] | None:
    result_json = getattr(run, _TRANSIENT_RESULT_JSON_ATTR, None)
    if isinstance(result_json, dict):
        return result_json
    return None
