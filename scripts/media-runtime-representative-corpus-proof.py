#!/usr/bin/env python3
# ruff: noqa: E402
"""Run a deterministic, in-memory image corpus through the current media runtime."""

from __future__ import annotations

import gc
import hashlib
import io
import json
import os
import random
import resource
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import ExifTags, Image, ImageDraw
from PIL.TiffImagePlugin import IFDRational

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.media_derivatives.artifacts import (
    ValidatedImageUpload,
    validate_image_upload_stream,
)
from app.domain.media_derivatives.contracts import (
    MAX_DELIVERABLE_ARTIFACT_BYTES,
    MAX_UPLOAD_BYTES_IMAGE,
    MIME_TYPE_BY_FORMAT,
)
from app.domain.media_derivatives.errors import (
    MediaDerivativeAnimatedSourceUnavailableError,
    MediaDerivativeErrorBase,
    MediaUploadFormatUnavailableError,
)
from app.domain.media_derivatives.processor import (
    MediaDerivativeResult,
    process_media_derivative,
)

MIB = 1024 * 1024
CASE_ELAPSED_BUDGET_MS = 5_000.0
CASE_RSS_DELTA_BUDGET_BYTES = 128 * MIB
SUITE_ELAPSED_BUDGET_MS = 20_000.0
PRIVATE_DESCRIPTION = "npcink private corpus description"
PRIVATE_ARTIST = "npcink private corpus artist"
PRIVATE_ICC_PROFILE = b"npcink-private-corpus-icc-profile"


def _current_rss_bytes() -> int:
    statm = Path("/proc/self/statm")
    if statm.is_file():
        fields = statm.read_text(encoding="ascii").split()
        if len(fields) >= 2:
            return int(fields[1]) * int(os.sysconf("SC_PAGE_SIZE"))
    maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return maximum if sys.platform == "darwin" else maximum * 1024


class PeakRssSampler:
    """Sample process RSS using the same bounded pattern as the P3-B5 proof."""

    def __init__(self) -> None:
        self.start_bytes = _current_rss_bytes()
        self.peak_bytes = self.start_bytes
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.wait(0.005):
            self.peak_bytes = max(self.peak_bytes, _current_rss_bytes())

    def __enter__(self) -> PeakRssSampler:
        self._thread.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.peak_bytes = max(self.peak_bytes, _current_rss_bytes())
        self._stop.set()
        self._thread.join(timeout=1)

    @property
    def delta_bytes(self) -> int:
        return max(0, self.peak_bytes - self.start_bytes)


@dataclass(frozen=True, slots=True)
class CorpusCase:
    name: str
    input_format: str
    input_mime_type: str
    input_width: int
    input_height: int
    target_format: str
    max_width: int
    quality: int
    seed: int
    mode: str = "RGB"
    pattern: str = "random"
    exif_orientation: int | None = None
    private_metadata: bool = False


CASES = (
    CorpusCase(
        name="jpeg_to_webp",
        input_format="jpeg",
        input_mime_type="image/jpeg",
        input_width=1280,
        input_height=720,
        target_format="webp",
        max_width=960,
        quality=82,
        seed=101,
    ),
    CorpusCase(
        name="png_alpha_to_png",
        input_format="png",
        input_mime_type="image/png",
        input_width=1024,
        input_height=768,
        target_format="png",
        max_width=640,
        quality=82,
        seed=202,
        mode="RGBA",
        pattern="structured_alpha",
    ),
    CorpusCase(
        name="webp_to_jpeg",
        input_format="webp",
        input_mime_type="image/webp",
        input_width=960,
        input_height=640,
        target_format="jpeg",
        max_width=720,
        quality=82,
        seed=303,
    ),
    CorpusCase(
        name="jpeg_exif_orientation_to_png",
        input_format="jpeg",
        input_mime_type="image/jpeg",
        input_width=640,
        input_height=360,
        target_format="png",
        max_width=500,
        quality=82,
        seed=404,
        pattern="orientation_markers",
        exif_orientation=6,
        private_metadata=True,
    ),
    CorpusCase(
        name="large_random_png_to_webp",
        input_format="png",
        input_mime_type="image/png",
        input_width=2304,
        input_height=2304,
        target_format="webp",
        max_width=1600,
        quality=82,
        seed=505,
    ),
)


def _structured_alpha_image(case: CorpusCase) -> Image.Image:
    image = Image.new("RGB", (case.input_width, case.input_height), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    midpoint_x = case.input_width // 2
    midpoint_y = case.input_height // 2
    draw.rectangle((0, 0, midpoint_x - 1, midpoint_y - 1), fill=(220, 30, 30))
    draw.rectangle(
        (midpoint_x, 0, case.input_width - 1, midpoint_y - 1),
        fill=(30, 180, 60),
    )
    draw.rectangle(
        (0, midpoint_y, midpoint_x - 1, case.input_height - 1),
        fill=(30, 80, 220),
    )
    draw.rectangle(
        (midpoint_x, midpoint_y, case.input_width - 1, case.input_height - 1),
        fill=(230, 190, 30),
    )

    transparent_end = case.input_width // 4
    opaque_start = case.input_width * 3 // 4
    gradient_width = max(2, opaque_start - transparent_end)
    alpha_row = bytearray(case.input_width)
    for x in range(case.input_width):
        if x < transparent_end:
            alpha_row[x] = 0
        elif x >= opaque_start:
            alpha_row[x] = 255
        else:
            alpha_row[x] = round((x - transparent_end) * 255 / (gradient_width - 1))
    alpha = Image.frombytes("L", image.size, bytes(alpha_row) * case.input_height)
    try:
        image.putalpha(alpha)
    finally:
        alpha.close()
    return image


def _orientation_marker_image(case: CorpusCase) -> Image.Image:
    image = Image.new("RGB", (case.input_width, case.input_height), color=(0, 0, 0))
    draw = ImageDraw.Draw(image)
    midpoint_x = case.input_width // 2
    midpoint_y = case.input_height // 2
    draw.rectangle((0, 0, midpoint_x - 1, midpoint_y - 1), fill=(230, 20, 20))
    draw.rectangle(
        (midpoint_x, 0, case.input_width - 1, midpoint_y - 1),
        fill=(20, 210, 40),
    )
    draw.rectangle(
        (0, midpoint_y, midpoint_x - 1, case.input_height - 1),
        fill=(20, 60, 230),
    )
    draw.rectangle(
        (midpoint_x, midpoint_y, case.input_width - 1, case.input_height - 1),
        fill=(230, 210, 20),
    )
    return image


def _build_source_image(case: CorpusCase) -> Image.Image:
    if case.pattern == "structured_alpha":
        return _structured_alpha_image(case)
    if case.pattern == "orientation_markers":
        return _orientation_marker_image(case)
    channels = len(case.mode)
    payload = random.Random(case.seed).randbytes(
        case.input_width * case.input_height * channels
    )
    try:
        return Image.frombytes(case.mode, (case.input_width, case.input_height), payload)
    finally:
        del payload


def _source_image_bytes(case: CorpusCase) -> bytes:
    image = _build_source_image(case)
    try:
        output = io.BytesIO()
        save_kwargs: dict[str, object] = {}
        if case.input_format in {"jpeg", "webp"}:
            save_kwargs["quality"] = 88
        if case.private_metadata:
            exif = image.getexif()
            exif[274] = case.exif_orientation or 1
            exif[270] = PRIVATE_DESCRIPTION
            exif[315] = PRIVATE_ARTIST
            exif[int(ExifTags.IFD.GPSInfo)] = {
                1: "N",
                2: (IFDRational(1), IFDRational(2), IFDRational(3)),
                3: "E",
                4: (IFDRational(4), IFDRational(5), IFDRational(6)),
            }
            save_kwargs["exif"] = exif.tobytes()
            save_kwargs["icc_profile"] = PRIVATE_ICC_PROFILE
        elif case.exif_orientation is not None:
            exif = image.getexif()
            exif[274] = case.exif_orientation
            save_kwargs["exif"] = exif.tobytes()
        image.save(output, format=case.input_format.upper(), **save_kwargs)
        return output.getvalue()
    finally:
        image.close()


def _inspect_source(case: CorpusCase, source: bytes) -> dict[str, object]:
    with Image.open(io.BytesIO(source)) as decoded:
        decoded.load()
        if decoded.size != (case.input_width, case.input_height):
            raise RuntimeError(f"{case.name} source dimensions do not match")
        if str(decoded.format or "").lower() != case.input_format:
            raise RuntimeError(f"{case.name} source format does not match")

        evidence: dict[str, object] = {
            "private_metadata_injected": False,
            "icc_profile_present": False,
            "exif_description_present": False,
            "exif_artist_present": False,
            "gps_present": False,
            "orientation": None,
            "structured_alpha": False,
        }
        if case.pattern == "structured_alpha":
            if decoded.mode != "RGBA":
                raise RuntimeError(f"{case.name} source alpha channel is unavailable")
            alpha = decoded.getchannel("A")
            try:
                alpha_values = set(alpha.get_flattened_data())
            finally:
                alpha.close()
            if min(alpha_values) != 0 or max(alpha_values) != 255 or len(alpha_values) < 64:
                raise RuntimeError(f"{case.name} source alpha pattern is not representative")
            evidence["structured_alpha"] = True
            evidence["source_alpha_levels"] = len(alpha_values)

        if case.private_metadata:
            exif = decoded.getexif()
            gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
            facts = {
                "icc_profile_present": decoded.info.get("icc_profile") == PRIVATE_ICC_PROFILE,
                "exif_description_present": exif.get(270) == PRIVATE_DESCRIPTION,
                "exif_artist_present": exif.get(315) == PRIVATE_ARTIST,
                "gps_present": bool(gps.get(1) and gps.get(2) and gps.get(3) and gps.get(4)),
                "orientation": exif.get(274),
            }
            if not all(
                facts[key]
                for key in (
                    "icc_profile_present",
                    "exif_description_present",
                    "exif_artist_present",
                    "gps_present",
                )
            ) or facts["orientation"] != case.exif_orientation:
                raise RuntimeError(f"{case.name} private source metadata was not injected")
            evidence.update(facts)
            evidence["private_metadata_injected"] = True
        return evidence


def _expected_dimensions(case: CorpusCase) -> tuple[int, int]:
    width = case.input_width
    height = case.input_height
    if case.exif_orientation in {6, 8}:
        width, height = height, width
    if width > case.max_width:
        height = int(height * (case.max_width / width))
        width = case.max_width
    return width, height


def _measure[T](operation: Callable[[], T]) -> tuple[T, float, int, int]:
    gc.collect()
    started = time.perf_counter()
    with PeakRssSampler() as sampler:
        value = operation()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    if elapsed_ms > CASE_ELAPSED_BUDGET_MS:
        raise RuntimeError(
            f"corpus case exceeded elapsed budget: {elapsed_ms} > {CASE_ELAPSED_BUDGET_MS}"
        )
    if sampler.delta_bytes > CASE_RSS_DELTA_BUDGET_BYTES:
        raise RuntimeError(
            "corpus case exceeded RSS delta budget: "
            f"{sampler.delta_bytes} > {CASE_RSS_DELTA_BUDGET_BYTES}"
        )
    return value, elapsed_ms, sampler.peak_bytes, sampler.delta_bytes


def _validate_output(
    case: CorpusCase,
    source: bytes,
    result: MediaDerivativeResult,
) -> dict[str, object]:
    expected_width, expected_height = _expected_dimensions(case)
    if result.format != case.target_format:
        raise RuntimeError(f"{case.name} returned unexpected output format")
    if result.mime_type != MIME_TYPE_BY_FORMAT[case.target_format]:
        raise RuntimeError(f"{case.name} returned unexpected output MIME type")
    if (result.width, result.height) != (expected_width, expected_height):
        raise RuntimeError(f"{case.name} returned unexpected output dimensions")
    if not (0 < result.filesize_bytes <= MAX_DELIVERABLE_ARTIFACT_BYTES):
        raise RuntimeError(f"{case.name} returned an undeliverable output size")
    if result.filesize_bytes != len(result.output_bytes):
        raise RuntimeError(f"{case.name} output byte evidence does not match")
    checksum = f"sha256:{hashlib.sha256(result.output_bytes).hexdigest()}"
    if result.checksum != checksum:
        raise RuntimeError(f"{case.name} output checksum evidence does not match")

    alpha_plane_matches_expected = False
    orientation_pixels_match_expected = False
    with Image.open(io.BytesIO(result.output_bytes)) as output:
        output.load()
        if output.size != (expected_width, expected_height):
            raise RuntimeError(f"{case.name} decoded output dimensions do not match")
        if output.getexif() or "exif" in output.info or "icc_profile" in output.info:
            raise RuntimeError(f"{case.name} retained private image metadata")
        if case.mode == "RGBA":
            if output.mode != "RGBA":
                raise RuntimeError(f"{case.name} did not preserve its alpha channel")
            output_alpha = output.getchannel("A")
            with Image.open(io.BytesIO(source)) as source_image:
                source_image.load()
                source_alpha = source_image.getchannel("A")
                try:
                    expected_alpha = source_alpha.resize(
                        (expected_width, expected_height),
                        Image.Resampling.LANCZOS,
                    )
                finally:
                    source_alpha.close()
            try:
                alpha_values = set(output_alpha.get_flattened_data())
                alpha_plane_matches_expected = (
                    output_alpha.tobytes() == expected_alpha.tobytes()
                )
                if (
                    min(alpha_values) != 0
                    or max(alpha_values) != 255
                    or len(alpha_values) < 64
                    or not alpha_plane_matches_expected
                ):
                    raise RuntimeError(f"{case.name} output alpha plane does not match")
            finally:
                output_alpha.close()
                expected_alpha.close()

        if case.exif_orientation is not None:
            with Image.open(io.BytesIO(source)) as source_image:
                source_image.load()
                if case.exif_orientation == 3:
                    expected = source_image.rotate(180, expand=True)
                elif case.exif_orientation == 6:
                    expected = source_image.rotate(270, expand=True)
                elif case.exif_orientation == 8:
                    expected = source_image.rotate(90, expand=True)
                else:
                    expected = source_image.copy()
            try:
                if expected.width > case.max_width:
                    resized_height = int(expected.height * (case.max_width / expected.width))
                    resized = expected.resize(
                        (case.max_width, resized_height),
                        Image.Resampling.LANCZOS,
                    )
                    expected.close()
                    expected = resized
                output_rgb = output.convert("RGB")
                expected_rgb = expected.convert("RGB")
                try:
                    orientation_pixels_match_expected = (
                        output_rgb.tobytes() == expected_rgb.tobytes()
                    )
                finally:
                    output_rgb.close()
                    expected_rgb.close()
                if not orientation_pixels_match_expected:
                    raise RuntimeError(f"{case.name} did not orient source pixels")
            finally:
                expected.close()

    orientation_applied = case.exif_orientation is not None and (
        result.source_width == case.input_width
        and result.source_height == case.input_height
        and (result.width, result.height) == (expected_width, expected_height)
        and orientation_pixels_match_expected
    )
    return {
        "alpha_plane_matches_expected": alpha_plane_matches_expected,
        "metadata_stripped": True,
        "orientation_applied": orientation_applied,
        "orientation_pixels_match_expected": orientation_pixels_match_expected,
    }


def _run_case(case: CorpusCase) -> dict[str, object]:
    source = _source_image_bytes(case)
    source_evidence = _inspect_source(case, source)

    def pipeline() -> tuple[ValidatedImageUpload, MediaDerivativeResult, dict[str, object]]:
        upload = validate_image_upload_stream(
            io.BytesIO(source),
            declared_content_type=case.input_mime_type,
        )
        expected_upload_checksum = f"sha256:{hashlib.sha256(source).hexdigest()}"
        if upload.checksum != expected_upload_checksum:
            raise RuntimeError(f"{case.name} upload checksum evidence does not match")
        result = process_media_derivative(
            source_bytes=source,
            source_media_type="image",
            target_format=case.target_format,
            max_width=case.max_width,
            quality=case.quality,
        )
        properties = _validate_output(case, source, result)
        return upload, result, properties

    (upload, result, properties), elapsed_ms, peak_rss, rss_delta = _measure(pipeline)
    if upload.format != case.input_format or upload.content_type != case.input_mime_type:
        raise RuntimeError(f"{case.name} upload format evidence does not match")
    if upload.byte_size != len(source):
        raise RuntimeError(f"{case.name} upload byte evidence does not match")
    return {
        "name": case.name,
        "status": "passed",
        "operation": "image.transform.v1",
        "input": {
            "format": upload.format,
            "mime_type": upload.content_type,
            "width": upload.width,
            "height": upload.height,
            "bytes": upload.byte_size,
            "checksum": upload.checksum,
            "checksum_verified": True,
        },
        "request": {
            "target_format": case.target_format,
            "max_width": case.max_width,
            "quality": case.quality,
        },
        "output": {
            "format": result.format,
            "mime_type": result.mime_type,
            "width": result.width,
            "height": result.height,
            "bytes": result.filesize_bytes,
        },
        "elapsed_ms": elapsed_ms,
        "peak_rss_bytes": peak_rss,
        "rss_delta_bytes": rss_delta,
        "elapsed_budget_ms": CASE_ELAPSED_BUDGET_MS,
        "rss_delta_budget_bytes": CASE_RSS_DELTA_BUDGET_BYTES,
        "source_evidence": source_evidence,
        "properties": properties,
    }


def _animated_gif() -> bytes:
    frames = [Image.new("RGB", (64, 48), color=color) for color in ("red", "blue")]
    try:
        output = io.BytesIO()
        frames[0].save(
            output,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=100,
            loop=0,
        )
        return output.getvalue()
    finally:
        for frame in frames:
            frame.close()


def _static_bmp() -> bytes:
    image = Image.new("RGB", (64, 48), color=(17, 23, 41))
    try:
        output = io.BytesIO()
        image.save(output, format="BMP")
        return output.getvalue()
    finally:
        image.close()


def _run_rejection(
    *,
    name: str,
    source_factory: Callable[[], bytes],
    input_format: str,
    input_mime_type: str,
    expected_error: type[MediaDerivativeErrorBase],
    expected_error_code: str,
) -> dict[str, object]:
    source = source_factory()

    def reject() -> str:
        try:
            validate_image_upload_stream(
                io.BytesIO(source),
                declared_content_type=input_mime_type,
            )
        except expected_error as error:
            if error.error_code != expected_error_code:
                raise RuntimeError(f"{name} returned unexpected error code") from error
            return error.error_code
        raise RuntimeError(f"{name} did not fail closed")

    error_code, elapsed_ms, peak_rss, rss_delta = _measure(reject)
    return {
        "name": name,
        "status": "rejected",
        "stage": "upload_validation",
        "input": {
            "format": input_format,
            "mime_type": input_mime_type,
            "width": 64,
            "height": 48,
            "bytes": len(source),
        },
        "expected_error_code": expected_error_code,
        "observed_error_code": error_code,
        "elapsed_ms": elapsed_ms,
        "peak_rss_bytes": peak_rss,
        "rss_delta_bytes": rss_delta,
        "elapsed_budget_ms": CASE_ELAPSED_BUDGET_MS,
        "rss_delta_budget_bytes": CASE_RSS_DELTA_BUDGET_BYTES,
    }


def run_proof() -> dict[str, object]:
    started = time.perf_counter()
    cases = [_run_case(case) for case in CASES]
    rejections = [
        _run_rejection(
            name="animated_gif",
            source_factory=_animated_gif,
            input_format="gif",
            input_mime_type="image/gif",
            expected_error=MediaDerivativeAnimatedSourceUnavailableError,
            expected_error_code="media_derivative.animated_source_unavailable",
        ),
        _run_rejection(
            name="unsupported_static_bmp",
            source_factory=_static_bmp,
            input_format="bmp",
            input_mime_type="image/bmp",
            expected_error=MediaUploadFormatUnavailableError,
            expected_error_code="media_upload.format_unavailable",
        ),
    ]
    suite_elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    if suite_elapsed_ms > SUITE_ELAPSED_BUDGET_MS:
        raise RuntimeError(
            f"corpus suite exceeded elapsed budget: "
            f"{suite_elapsed_ms} > {SUITE_ELAPSED_BUDGET_MS}"
        )
    return {
        "status": "passed",
        "contract_version": "media_runtime_representative_corpus_proof.v1",
        "boundary": {
            "network_used": False,
            "bytes_persisted": False,
            "cms_write_performed": False,
        },
        "measurement_scope": {
            "case_elapsed": (
                "upload validation, upload checksum comparison, image transform, "
                "and output verification; source generation and source inspection excluded"
            ),
            "case_rss_delta": (
                "RSS growth during the case pipeline after the generated source is resident"
            ),
            "peak_rss": "whole-process RSS observed while the case pipeline runs",
            "suite_elapsed": "source generation, source inspection, case pipelines, and rejects",
        },
        "limits": {
            "upload_bytes": MAX_UPLOAD_BYTES_IMAGE,
            "deliverable_output_bytes": MAX_DELIVERABLE_ARTIFACT_BYTES,
            "case_elapsed_budget_ms": CASE_ELAPSED_BUDGET_MS,
            "case_rss_delta_budget_bytes": CASE_RSS_DELTA_BUDGET_BYTES,
            "suite_elapsed_budget_ms": SUITE_ELAPSED_BUDGET_MS,
        },
        "suite_elapsed_ms": suite_elapsed_ms,
        "cases": cases,
        "rejections": rejections,
    }


def main() -> int:
    print(json.dumps(run_proof(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
