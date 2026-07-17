from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.domain.routing.models import RoutingResolution
from app.domain.runtime.contract_validation import RuntimeContractValidator
from app.domain.runtime.errors import RuntimeExecutionContractError
from app.domain.runtime.models import RuntimeRequest


class RecordingCallbackDelivery:
    def __init__(self, target: dict[str, object] | None = None) -> None:
        self.target = dict(target or {})
        self.calls: list[tuple[object, RuntimeRequest, str]] = []

    def resolve_callback_target(
        self,
        *,
        site: object,
        request: RuntimeRequest,
        callback_mode: str,
    ) -> dict[str, object]:
        self.calls.append((site, request, callback_mode))
        return dict(self.target)


def _validator(
    *,
    callback_target: dict[str, object] | None = None,
) -> tuple[RuntimeContractValidator, RecordingCallbackDelivery]:
    callback_delivery = RecordingCallbackDelivery(callback_target)
    return (
        RuntimeContractValidator(
            callback_target_resolver=callback_delivery,
        ),
        callback_delivery,
    )


def _request(**overrides: Any) -> RuntimeRequest:
    values: dict[str, Any] = {
        "site_id": "site_alpha",
        "ability_name": "npcink-cloud/test-runtime",
        "channel": "editor",
        "execution_kind": "text",
        "profile_id": "text.balanced",
        "input_payload": {"text": "safe runtime input"},
        "contract_version": "test_runtime.v1",
        "execution_pattern": "inline",
        "data_classification": "internal",
        "storage_mode": "result_only",
        "timeout_seconds": 60,
        "retry_max": 1,
        "retention_ttl": 3600,
    }
    values.update(overrides)
    return RuntimeRequest(**values)


def _connector_request(**overrides: Any) -> RuntimeRequest:
    request = _request(
        ability_name="npcink-cloud/connector-runtime",
        contract_version="cloud_connector_runtime.v1",
        channel="editor",
        data_classification="public_site_content",
        input_payload={
            "site_url": "https://example.com",
            "platform_kind": "wordpress",
            "connector_id": "npcink-cloud-addon",
            "connector_version": "1.2.3",
            "suggestion_only": True,
            "operation_contract": {
                "contract_version": "wordpress_operation.v1",
                "task": "title_generation",
                "request": {
                    "source_text": "<content>Current WordPress article content.</content>"
                },
            },
        },
        timeout_seconds=60,
        retry_max=0,
        retention_ttl=86400,
    )
    for key, value in overrides.items():
        setattr(request, key, value)
    return request


def _family_requests() -> list[tuple[str, RuntimeRequest]]:
    return [
        (
            "validate_site_knowledge_contract",
            _request(
                ability_name="npcink-cloud/site-knowledge-status",
                contract_version="site_knowledge_status.v1",
                input_payload={
                    "contract_version": "site_knowledge_status.v1",
                    "write_posture": "suggestion_only",
                },
            ),
        ),
        (
            "validate_cloud_batch_runtime_contract",
            _request(
                ability_name="npcink-cloud/analyze-nightly-content-batch",
                contract_version="cloud_batch_runtime_request.v1",
                execution_pattern="whole_run_offload",
                input_payload={
                    "contract_version": "cloud_batch_runtime_request.v1",
                    "items": [{}],
                    "direct_wordpress_write": False,
                },
            ),
        ),
        (
            "validate_image_source_contract",
            _request(
                ability_name="npcink-cloud/search-image-source",
                contract_version="image_source_cloud_request.v1",
                execution_pattern="step_offload",
                input_payload={
                    "contract_version": "image_source_cloud_request.v1",
                    "candidate_contract": "image_candidate.v1",
                    "direct_wordpress_write": False,
                },
            ),
        ),
        (
            "validate_audio_generation_contract",
            _request(
                ability_name="npcink-cloud/generate-audio",
                contract_version="audio_generation_request.v1",
                execution_kind="audio_generation",
                input_payload={
                    "contract_version": "audio_generation_request.v1",
                    "text": "A short narration.",
                },
            ),
        ),
        (
            "validate_image_generation_contract",
            _request(
                ability_name="npcink-cloud/generate-image",
                contract_version="image_generation_request.v1",
                execution_kind="image_generation",
                input_payload={
                    "contract_version": "image_generation_request.v1",
                    "prompt": "An editorial illustration of a writing desk.",
                    "resolution": "medium",
                },
            ),
        ),
        (
            "validate_media_batch_plan_contract",
            _request(
                ability_name="npcink-cloud/plan-media-derivative-batch",
                contract_version="media_derivative_batch_plan_request.v1",
                input_payload={
                    "contract_version": "media_derivative_batch_plan_request.v1",
                    "user_request": "Plan reviewable image derivatives.",
                    "direct_wordpress_write": False,
                },
            ),
        ),
        (
            "validate_site_ops_analysis_contract",
            _request(
                ability_name="npcink-cloud/analyze-site-ops",
                contract_version="site_ops_cloud_analysis_request.v1",
                input_payload={
                    "contract_version": "site_ops_cloud_analysis_request.v1",
                    "write_posture": "suggestion_only",
                    "direct_wordpress_write": False,
                    "core_proposal_created": False,
                    "input": {"sample_summaries": {}, "local_findings": []},
                },
            ),
        ),
        (
            "validate_image_context_evidence_contract",
            _request(
                ability_name="npcink-cloud/image-context-evidence",
                contract_version="image_context_evidence_request.v1",
                execution_kind="vision",
                input_payload={
                    "contract_version": "image_context_evidence_request.v1",
                    "items": [
                        {
                            "attachment_id": "42",
                            "source_url": "https://images.example.com/media.jpg",
                        }
                    ],
                },
            ),
        ),
        (
            "validate_web_search_contract",
            _request(
                ability_name="npcink-cloud/web-search",
                contract_version="web_search.v1",
                input_payload={
                    "contract_version": "web_search.v1",
                    "write_posture": "suggestion_only",
                },
            ),
        ),
    ]


@pytest.mark.parametrize(("method_name", "runtime_request"), _family_requests())
def test_each_runtime_family_keeps_validation_and_common_limits(
    method_name: str,
    runtime_request: RuntimeRequest,
) -> None:
    validator, _ = _validator()
    method = getattr(validator, method_name)

    method(runtime_request)
    runtime_request.timeout_seconds = 3601

    with pytest.raises(RuntimeExecutionContractError) as caught:
        method(runtime_request)

    assert caught.value.error_code == "runtime.contract_timeout_exceeded"
    assert caught.value.message == "timeout_seconds exceeds max allowed value 3600"


def test_data_handling_guard_preserves_secret_pii_and_no_store_errors() -> None:
    validator, _ = _validator()

    with pytest.raises(RuntimeExecutionContractError) as secret_input:
        validator.validate_runtime_data_handling_contract(
            _request(input_payload={"api_key": "not-logged"})
        )
    assert secret_input.value.error_code == "runtime.secret_input_detected"
    assert secret_input.value.message == (
        "runtime input contains secret-like data at 'input.api_key'"
    )

    with pytest.raises(RuntimeExecutionContractError) as pii_classification:
        validator.validate_runtime_data_handling_contract(
            _request(input_payload={"contact": "writer@example.com"})
        )
    assert pii_classification.value.error_code == "runtime.pii_classification_required"
    assert pii_classification.value.message == (
        "runtime input appears to contain personal data and must use data_classification=pii"
    )

    with pytest.raises(RuntimeExecutionContractError) as no_store:
        validator.validate_runtime_data_handling_contract(
            _request(
                input_payload={"contact": "writer@example.com"},
                data_classification="pii",
            )
        )
    assert no_store.value.error_code == "runtime.sensitive_data_requires_no_store"
    assert no_store.value.message == (
        "pii and secret runtime requests must use storage_mode=no_store"
    )

    with pytest.raises(RuntimeExecutionContractError) as forbidden:
        validator.validate_runtime_data_handling_contract(
            _request(data_classification="secret", storage_mode="no_store")
        )
    assert forbidden.value.error_code == "runtime.secret_data_forbidden"
    assert forbidden.value.message == (
        "secret-classified data is excluded from hosted runtime execution"
    )


def test_connector_validation_delegates_neutral_and_wordpress_contracts() -> None:
    validator, _ = _validator()
    request = _connector_request()

    envelope = validator.validate_connector_runtime_contract(request)

    assert envelope["site_url"] == "https://example.com"
    assert envelope["operation_contract"] == {
        "contract_version": "wordpress_operation.v1",
        "task": "title_generation",
        "request": {"source_text": "<content>Current WordPress article content.</content>"},
    }

    request.channel = "openapi"
    with pytest.raises(RuntimeExecutionContractError) as channel:
        validator.validate_connector_runtime_contract(request)
    assert channel.value.error_code == "connector_runtime.channel_invalid"
    assert channel.value.message == "connector runtime requires channel=editor"

    request = _connector_request()
    request.input_payload["operation_contract"]["request"]["direct_wordpress_write"] = False
    with pytest.raises(RuntimeExecutionContractError) as operation:
        validator.validate_connector_runtime_contract(request)
    assert operation.value.error_code == "wordpress_operation.control_field_forbidden"
    assert operation.value.message == (
        "WordPress operation request may not include connector envelope, result, "
        "or write-control field 'request.direct_wordpress_write'"
    )


def test_connector_validation_preserves_limits_and_site_binding() -> None:
    validator, _ = _validator()
    request = _connector_request(timeout_seconds=61)

    with pytest.raises(RuntimeExecutionContractError) as timeout:
        validator.validate_connector_runtime_contract(request)
    assert timeout.value.error_code == "connector_runtime.timeout_exceeded"
    assert timeout.value.message == (
        "connector runtime timeout_seconds exceeds max allowed value 60"
    )

    envelope = _connector_request().input_payload
    site = SimpleNamespace(site_url="https://other.example.com", platform_kind="wordpress")
    with pytest.raises(RuntimeExecutionContractError) as site_binding:
        validator.validate_connector_runtime_site_binding(envelope, site=site)
    assert site_binding.value.error_code == "connector_runtime.site_url_mismatch"
    assert site_binding.value.message == (
        "connector runtime site_url does not match the authenticated site"
    )


def test_build_execution_contract_preserves_callback_and_backend_contract() -> None:
    callback_target = {
        "source": "site_registered",
        "callback_url": "https://example.com/runtime-callback",
        "key_id": "callback_key",
        "callback_id": "runtime_terminal",
        "registered": True,
    }
    validator, callback_delivery = _validator(callback_target=callback_target)
    request = _request(
        execution_pattern="whole_run_offload",
        task_backend={
            "enabled": True,
            "mode": "queue",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 5,
        },
    )
    resolution = RoutingResolution(
        profile_id="text.balanced",
        execution_kind="text",
        revision="routing-v1",
        default_policy={},
        selection_policy={},
    )
    site = SimpleNamespace(metadata_json={})

    contract = validator.build_execution_contract(
        request=request,
        resolution=resolution,
        site=site,
    )

    assert contract == {
        "ability_name": "npcink-cloud/test-runtime",
        "contract_version": "test_runtime.v1",
        "profile_id": "text.balanced",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "storage_mode": "result_only",
        "timeout_seconds": 60,
        "retry_max": 1,
        "retention_ttl": 3600,
        "task_backend": {
            "enabled": True,
            "mode": "queue",
            "callback_mode": "polling_preferred",
            "polling_interval_sec": 5,
        },
        "callback_target": callback_target,
    }
    assert callback_delivery.calls == [(site, request, "polling_preferred")]

    request.task_backend = {"enabled": False}
    with pytest.raises(RuntimeExecutionContractError) as backend:
        validator.build_execution_contract(
            request=request,
            resolution=resolution,
            site=site,
        )
    assert backend.value.error_code == "runtime.contract_task_backend_required"
    assert backend.value.message == "whole_run_offload requires task_backend.enabled=true"


def test_build_execution_contract_preserves_profile_and_retention_errors() -> None:
    validator, _ = _validator()
    resolution = RoutingResolution(
        profile_id="text.quality",
        execution_kind="text",
        revision="routing-v1",
        default_policy={},
        selection_policy={},
    )

    with pytest.raises(RuntimeExecutionContractError) as profile:
        validator.build_execution_contract(
            request=_request(),
            resolution=resolution,
            site=SimpleNamespace(metadata_json={}),
        )
    assert profile.value.error_code == "runtime.contract_profile_mismatch"
    assert profile.value.message == ("profile_id does not match the resolved routing profile")

    with pytest.raises(RuntimeExecutionContractError) as retention:
        validator.build_execution_contract(
            request=_request(
                profile_id="text.quality",
                storage_mode="full_store_with_ttl",
                retention_ttl=0,
            ),
            resolution=resolution,
            site=SimpleNamespace(metadata_json={}),
        )
    assert retention.value.error_code == "runtime.contract_retention_required"
    assert retention.value.message == ("full_store_with_ttl requires a positive retention_ttl")


def test_apply_execution_contract_preserves_runtime_controls_and_callback() -> None:
    validator, _ = _validator()
    callback = {
        "source": "site_registered",
        "callback_url": "https://example.com/runtime-callback",
    }

    policy = validator.apply_execution_contract(
        {"allow_fallback": True, "callback_url": "https://ignored.example.com"},
        execution_contract={
            "ability_name": "npcink-cloud/test-runtime",
            "contract_version": "test_runtime.v1",
            "profile_id": "text.balanced",
            "execution_pattern": "whole_run_offload",
            "data_classification": "internal",
            "storage_mode": "result_only",
            "timeout_seconds": 60,
            "retry_max": 1,
            "retention_ttl": 3600,
            "task_backend": {
                "enabled": True,
                "mode": "queue",
                "callback_mode": "polling_preferred",
            },
            "callback_target": callback,
        },
    )

    assert policy["timeout_seconds"] == 60
    assert policy["timeout_ms"] == 60000
    assert policy["retry_max"] == 1
    assert policy["max_retries"] == 1
    assert policy["retention_ttl"] == 3600
    assert policy["runtime_callback"] == callback
    assert "callback_url" not in policy
    assert policy["execution_contract"] == {
        "ability_name": "npcink-cloud/test-runtime",
        "contract_version": "test_runtime.v1",
        "profile_id": "text.balanced",
        "execution_pattern": "whole_run_offload",
        "data_classification": "internal",
        "storage_mode": "result_only",
        "timeout_seconds": 60,
        "retry_max": 1,
        "retention_ttl": 3600,
        "task_backend": {
            "enabled": True,
            "mode": "queue",
            "callback_mode": "polling_preferred",
        },
    }


@pytest.mark.parametrize(
    ("override", "message"),
    [
        (
            {"timeout_seconds": 61},
            "commercial override may not increase timeout_seconds beyond the execution contract",
        ),
        (
            {"retry_max": 2},
            "commercial override may not increase retry_max beyond the execution contract",
        ),
        (
            {"retention_ttl": 3601},
            "commercial override may not increase retention_ttl beyond the execution contract",
        ),
        (
            {"task_backend": {"enabled": True, "mode": "queue"}},
            "commercial override may not enable task_backend when the execution "
            "contract disabled it",
        ),
    ],
)
def test_commercial_overrides_cannot_widen_execution_contract(
    override: dict[str, object],
    message: str,
) -> None:
    validator, _ = _validator()
    policy: dict[str, object] = {
        "timeout_seconds": 60,
        "retry_max": 1,
        "retention_ttl": 3600,
        "task_backend": {"enabled": False},
        "execution_contract": {
            "timeout_seconds": 60,
            "retry_max": 1,
            "retention_ttl": 3600,
            "task_backend": {"enabled": False},
        },
    }
    policy.update(override)

    with pytest.raises(RuntimeExecutionContractError) as caught:
        validator.enforce_policy_within_execution_contract(policy)

    assert caught.value.error_code == "runtime.contract_override_out_of_range"
    assert caught.value.message == message


def test_commercial_overrides_cannot_replace_backend_mode_or_callback_mode() -> None:
    validator, _ = _validator()
    execution_contract = {
        "timeout_seconds": 60,
        "retry_max": 1,
        "retention_ttl": 3600,
        "task_backend": {
            "enabled": True,
            "mode": "queue",
            "callback_mode": "polling_preferred",
        },
    }

    with pytest.raises(RuntimeExecutionContractError) as mode:
        validator.enforce_policy_within_execution_contract(
            {
                "execution_contract": execution_contract,
                "task_backend": {"enabled": True, "mode": "inline"},
            }
        )
    assert mode.value.error_code == "runtime.contract_override_out_of_range"
    assert mode.value.message == (
        "commercial override may not replace task_backend.mode outside the execution contract"
    )

    with pytest.raises(RuntimeExecutionContractError) as callback:
        validator.enforce_policy_within_execution_contract(
            {
                "execution_contract": execution_contract,
                "task_backend": {
                    "enabled": True,
                    "mode": "queue",
                    "callback_mode": "terminal_callback_required",
                },
            }
        )
    assert callback.value.error_code == "runtime.contract_override_out_of_range"
    assert callback.value.message == (
        "commercial override may not widen task_backend.callback_mode beyond the execution contract"
    )


def test_runtime_contract_validator_has_no_execution_or_truth_ownership_imports() -> None:
    module_path = (
        Path(__file__).parents[2] / "app" / "domain" / "runtime" / "contract_validation.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "app.domain.runtime.callback_delivery" not in imported_modules
    assert not imported_modules.intersection(
        {
            "app.domain.runtime.service",
            "app.core.db",
            "app.core.models",
            "app.domain.commercial.service",
            "app.domain.audio_generation.artifacts",
            "app.domain.image_generation.materialization",
        }
    )
    assert not any(module.startswith("app.adapters.repositories") for module in imported_modules)
    assert not any(module.startswith("app.adapters.queue") for module in imported_modules)
    assert not any(module.startswith("app.adapters.providers") for module in imported_modules)
    assert not any(module.endswith(".service") for module in imported_modules)


def test_runtime_service_delegates_without_private_validation_wrappers() -> None:
    service_path = Path(__file__).parents[2] / "app" / "domain" / "runtime" / "service.py"
    tree = ast.parse(service_path.read_text(encoding="utf-8"))
    runtime_service = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "RuntimeService"
    )
    method_names = {node.name for node in runtime_service.body if isinstance(node, ast.FunctionDef)}

    assert not method_names.intersection(
        {
            "_validate_runtime_data_handling_contract",
            "_validate_site_knowledge_contract",
            "_validate_cloud_batch_runtime_contract",
            "_validate_image_source_contract",
            "_validate_audio_generation_contract",
            "_validate_image_generation_contract",
            "_validate_media_batch_plan_contract",
            "_validate_site_ops_analysis_contract",
            "_validate_image_context_evidence_contract",
            "_normalize_wordpress_ai_connector_envelope",
            "_validate_wordpress_ai_connector_contract",
            "_validate_connector_runtime_site_binding",
            "_validate_web_search_contract",
            "_build_execution_contract",
            "_apply_execution_contract",
            "_enforce_policy_within_execution_contract",
        }
    )
