from __future__ import annotations

import io

import pytest
from PIL import Image

from app.domain.media_derivatives import processor
from app.domain.media_derivatives.errors import MediaDerivativeOutputTooLargeError


def _png_bytes() -> bytes:
    image = Image.new("RGB", (2, 2), color="red")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_derivative_output_over_delivery_envelope_fails_before_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(processor, "MAX_DELIVERABLE_ARTIFACT_BYTES", 8)
    monkeypatch.setattr(
        processor,
        "_save_image",
        lambda *args, **kwargs: (b"x" * 9, "image/png", "png"),
    )

    with pytest.raises(MediaDerivativeOutputTooLargeError) as raised:
        processor.process_media_derivative(
            source_bytes=_png_bytes(),
            source_media_type="image",
            target_format="png",
            max_width=2,
            quality=80,
        )

    assert raised.value.status_code == 413
    assert raised.value.error_code == "media_derivative.output_too_large"
