from __future__ import annotations

import pytest

from app.domain.image_generation.contracts import (
    IMAGE_GENERATION_CLOUD_ABILITY,
    IMAGE_GENERATION_CONTRACT,
    ImageGenerationContractViolation,
    validate_image_generation_runtime_contract,
)


def _validate(input_payload: dict[str, object]) -> None:
    validate_image_generation_runtime_contract(
        ability_name=IMAGE_GENERATION_CLOUD_ABILITY,
        contract_version=IMAGE_GENERATION_CONTRACT,
        input_payload=input_payload,
    )


def test_image_generation_v1_accepts_only_platform_neutral_bounded_inputs() -> None:
    _validate(
        {
            "contract_version": IMAGE_GENERATION_CONTRACT,
            "source_surface": "wordpress_ai_connector",
            "connector_id": "npcink-cloud",
            "connector_version": "1.0.0",
            "task": "image_generation",
            "prompt": "An editorial illustration of a writing desk.",
            "n": 2,
            "aspect_ratio": "16:9",
            "resolution": "high",
            "media_context": {"purpose": "featured_image"},
            "review": {"requires_operator_review": True},
            "source_handoff": {"source": "image_source_runtime"},
        }
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("response_format", "url"),
        ("url", "https://provider.example/image.png"),
        ("b64_json", "aW1hZ2U="),
        ("fetch_url", "https://provider.example/image.png"),
    ],
)
def test_image_generation_v1_rejects_provider_media_fields(
    field: str,
    value: str,
) -> None:
    with pytest.raises(ImageGenerationContractViolation) as error:
        _validate(
            {
                "contract_version": IMAGE_GENERATION_CONTRACT,
                "prompt": "An editorial illustration.",
                field: value,
            }
        )

    assert error.value.error_code == "image_generation.provider_media_field_forbidden"


def test_image_generation_v1_rejects_nested_provider_media_fields() -> None:
    with pytest.raises(ImageGenerationContractViolation) as error:
        _validate(
            {
                "contract_version": IMAGE_GENERATION_CONTRACT,
                "prompt": "An editorial illustration.",
                "media_context": {"provider": {"base64": "aW1hZ2U="}},
            }
        )

    assert error.value.error_code == "image_generation.provider_media_field_forbidden"
    assert "media_context.provider.base64" in error.value.message

    with pytest.raises(ImageGenerationContractViolation) as fetch_error:
        _validate(
            {
                "contract_version": IMAGE_GENERATION_CONTRACT,
                "prompt": "An editorial illustration.",
                "source_handoff": {"provider_fetch_policy": "remote"},
            }
        )

    assert fetch_error.value.error_code == "image_generation.provider_media_field_forbidden"


def test_image_generation_v1_requires_exact_input_contract_version() -> None:
    for input_contract_version in (None, "image_generation_request.v0"):
        payload: dict[str, object] = {"prompt": "An editorial illustration."}
        if input_contract_version is not None:
            payload["contract_version"] = input_contract_version
        with pytest.raises(ImageGenerationContractViolation) as error:
            _validate(payload)
        assert error.value.error_code == "image_generation.input_contract_mismatch"


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("prompt", {}, "image_generation.prompt_invalid"),
        ("prompt", 123, "image_generation.prompt_invalid"),
        ("n", True, "image_generation.image_count_invalid"),
        ("n", "2", "image_generation.image_count_invalid"),
        ("n", "garbage", "image_generation.image_count_invalid"),
        ("aspect_ratio", 1, "image_generation.aspect_ratio_invalid"),
        ("resolution", ["high"], "image_generation.resolution_invalid"),
    ],
)
def test_image_generation_v1_rejects_coercible_or_non_scalar_field_types(
    field: str,
    value: object,
    error_code: str,
) -> None:
    payload: dict[str, object] = {
        "contract_version": IMAGE_GENERATION_CONTRACT,
        "prompt": "An editorial illustration.",
        field: value,
    }

    with pytest.raises(ImageGenerationContractViolation) as error:
        _validate(payload)

    assert error.value.error_code == error_code


@pytest.mark.parametrize(
    ("field", "value", "error_code"),
    [
        ("unknown", "value", "image_generation.unknown_input_field"),
        ("text", "legacy prompt", "image_generation.unknown_input_field"),
        (
            "direct_wordpress_write",
            False,
            "image_generation.write_or_secret_field_forbidden",
        ),
    ],
)
def test_image_generation_v1_rejects_unknown_and_legacy_fields(
    field: str,
    value: object,
    error_code: str,
) -> None:
    with pytest.raises(ImageGenerationContractViolation) as error:
        _validate(
            {
                "contract_version": IMAGE_GENERATION_CONTRACT,
                "prompt": "An editorial illustration.",
                field: value,
            }
        )

    assert error.value.error_code == error_code
