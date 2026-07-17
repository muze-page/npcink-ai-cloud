#!/usr/bin/env python3
# ruff: noqa: E402
"""Measure the bounded media byte path used by the P3-B5 closeout gate."""

from __future__ import annotations

import argparse
import gc
import hashlib
import io
import json
import os
import random
import resource
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.domain.media_artifacts import ArtifactStoreError, LocalVolumeArtifactStore
from app.domain.media_derivatives.contracts import (
    MAX_DELIVERABLE_ARTIFACT_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_PIXEL_COUNT,
)
from app.domain.media_derivatives.errors import (
    MediaDerivativeOutputTooLargeError,
    MediaDerivativeSourceTooLargeError,
)
from app.domain.media_derivatives.processor import process_media_derivative

MIB = 1024 * 1024
STREAM_CHUNK_BYTES = 64 * 1024
STREAM_RSS_DELTA_BUDGET = 16 * MIB
PROCESS_RSS_DELTA_BUDGET = 384 * MIB
UPLOAD_FILE_LIMIT = 50 * MIB


class PatternReader(io.RawIOBase):
    """A deterministic source that never materializes the complete payload."""

    def __init__(self, byte_size: int) -> None:
        self.remaining = byte_size

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        if size < 0:
            raise AssertionError("the proof source must be read with a positive bound")
        current = min(size, self.remaining)
        self.remaining -= current
        return b"p" * current


def _current_rss_bytes() -> int:
    statm = Path("/proc/self/statm")
    if statm.is_file():
        fields = statm.read_text(encoding="ascii").split()
        if len(fields) >= 2:
            return int(fields[1]) * int(os.sysconf("SC_PAGE_SIZE"))
    maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return maximum if sys.platform == "darwin" else maximum * 1024


class PeakRssSampler:
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
class Measurement:
    name: str
    input_bytes: int
    output_bytes: int
    elapsed_ms: float
    peak_rss_bytes: int
    rss_delta_bytes: int
    budget_bytes: int


def _measure[T](
    name: str,
    input_bytes: int,
    budget_bytes: int,
    operation: Callable[[], tuple[T, int]],
) -> tuple[T, Measurement]:
    gc.collect()
    started = time.perf_counter()
    with PeakRssSampler() as sampler:
        value, output_bytes = operation()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    measurement = Measurement(
        name=name,
        input_bytes=input_bytes,
        output_bytes=output_bytes,
        elapsed_ms=elapsed_ms,
        peak_rss_bytes=sampler.peak_bytes,
        rss_delta_bytes=sampler.delta_bytes,
        budget_bytes=budget_bytes,
    )
    if measurement.rss_delta_bytes > budget_bytes:
        raise RuntimeError(
            f"{name} exceeded RSS delta budget: "
            f"{measurement.rss_delta_bytes} > {budget_bytes}"
        )
    return value, measurement


def _stream_round_trip(root: Path, byte_size: int) -> tuple[Measurement, Measurement]:
    store = LocalVolumeArtifactStore(root, chunk_size=STREAM_CHUNK_BYTES)

    def put() -> tuple[object, int]:
        metadata = store.put(PatternReader(byte_size), max_bytes=byte_size)
        return metadata, metadata.byte_size

    metadata, put_measurement = _measure(
        f"upload_store_{byte_size}",
        byte_size,
        STREAM_RSS_DELTA_BUDGET,
        put,
    )

    def pull() -> tuple[str, int]:
        digest = hashlib.sha256()
        received = 0
        with store.open(metadata.storage_key) as stream:
            while True:
                chunk = stream.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                if len(chunk) > STREAM_CHUNK_BYTES:
                    raise RuntimeError("artifact pull exceeded its chunk bound")
                received += len(chunk)
                digest.update(chunk)
        checksum = f"sha256:{digest.hexdigest()}"
        if received != metadata.byte_size or checksum != metadata.checksum:
            raise RuntimeError("artifact pull facts differ from stored evidence")
        return checksum, received

    _, pull_measurement = _measure(
        f"signed_pull_stream_{byte_size}",
        byte_size,
        STREAM_RSS_DELTA_BUDGET,
        pull,
    )
    store.delete(metadata.storage_key)
    return put_measurement, pull_measurement


def _random_jpeg(width: int, height: int, *, seed: int) -> bytes:
    payload = random.Random(seed).randbytes(width * height * 3)
    image = Image.frombytes("RGB", (width, height), payload)
    try:
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=False)
        return output.getvalue()
    finally:
        image.close()
        del payload


def _process_case(name: str, width: int, height: int, seed: int) -> tuple[bytes, Measurement]:
    source = _random_jpeg(width, height, seed=seed)

    def process() -> tuple[bytes, int]:
        result = process_media_derivative(
            source_bytes=source,
            source_media_type="image/jpeg",
            target_format="webp",
            max_width=width,
            quality=82,
        )
        if result.filesize_bytes > MAX_DELIVERABLE_ARTIFACT_BYTES:
            raise RuntimeError("processor published an undeliverable result")
        return result.output_bytes, result.filesize_bytes

    output, measurement = _measure(
        name,
        len(source),
        PROCESS_RSS_DELTA_BUDGET,
        process,
    )
    return source, measurement


def _encode_png(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), (17, 23, 41))
    try:
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
    finally:
        image.close()


def _assert_source_limit(source: bytes, expected: str) -> None:
    try:
        process_media_derivative(
            source_bytes=source,
            source_media_type="image/png",
            target_format="webp",
            max_width=MAX_IMAGE_DIMENSION,
            quality=82,
        )
    except MediaDerivativeSourceTooLargeError:
        return
    raise RuntimeError(f"{expected} did not fail closed")


def _run_boundary_probes(max_pixel_source: bytes) -> list[dict[str, object]]:
    probes: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="npcink-b5-over-limit-") as directory:
        store = LocalVolumeArtifactStore(Path(directory), chunk_size=STREAM_CHUNK_BYTES)
        try:
            store.put(PatternReader(UPLOAD_FILE_LIMIT + 1), max_bytes=UPLOAD_FILE_LIMIT)
        except ArtifactStoreError:
            probes.append(
                {
                    "name": "upload_50_mib_plus_one",
                    "status": "rejected",
                    "limit_bytes": UPLOAD_FILE_LIMIT,
                }
            )
        else:
            raise RuntimeError("50 MiB + 1 byte upload did not fail closed")

    _assert_source_limit(_encode_png(MAX_IMAGE_DIMENSION + 1, 1), "axis limit")
    probes.append(
        {
            "name": "axis_8192_plus_one",
            "status": "rejected",
            "limit": MAX_IMAGE_DIMENSION,
        }
    )

    _assert_source_limit(_encode_png(4097, 4097), "pixel limit")
    probes.append(
        {
            "name": "pixel_16777216_plus",
            "status": "rejected",
            "limit": MAX_PIXEL_COUNT,
        }
    )

    try:
        process_media_derivative(
            source_bytes=max_pixel_source,
            source_media_type="image/jpeg",
            target_format="png",
            max_width=4096,
            quality=100,
        )
    except MediaDerivativeOutputTooLargeError:
        probes.append(
            {
                "name": "deliverable_25_mib_output",
                "status": "rejected",
                "limit_bytes": MAX_DELIVERABLE_ARTIFACT_BYTES,
            }
        )
    else:
        raise RuntimeError("a greater-than-25-MiB derivative did not fail closed")
    return probes


def run_proof(*, quick: bool) -> dict[str, object]:
    stream_sizes = (1 * MIB,) if quick else (1 * MIB, 8 * MIB, 25 * MIB, 50 * MIB)
    process_cases = (("process_small", 256, 256, 1),) if quick else (
        ("process_small", 512, 512, 1),
        ("process_medium", 2048, 2048, 2),
        ("process_max_pixels", 4096, 4096, 3),
    )
    measurements: list[Measurement] = []
    with tempfile.TemporaryDirectory(prefix="npcink-b5-artifacts-") as directory:
        root = Path(directory)
        for byte_size in stream_sizes:
            measurements.extend(_stream_round_trip(root, byte_size))

    max_pixel_source = b""
    for name, width, height, seed in process_cases:
        source, measurement = _process_case(name, width, height, seed)
        measurements.append(measurement)
        if width == 4096 and height == 4096:
            max_pixel_source = source
        else:
            del source

    boundary_probes: list[dict[str, object]] = []
    if not quick:
        if not max_pixel_source:
            raise RuntimeError("max-pixel source was not measured")
        boundary_probes = _run_boundary_probes(max_pixel_source)

    return {
        "status": "passed",
        "mode": "quick" if quick else "full",
        "limits": {
            "upload_file_bytes": UPLOAD_FILE_LIMIT,
            "deliverable_output_bytes": MAX_DELIVERABLE_ARTIFACT_BYTES,
            "image_axis": MAX_IMAGE_DIMENSION,
            "image_pixels": MAX_PIXEL_COUNT,
            "stream_chunk_bytes": STREAM_CHUNK_BYTES,
            "stream_rss_delta_budget_bytes": STREAM_RSS_DELTA_BUDGET,
            "process_rss_delta_budget_bytes": PROCESS_RSS_DELTA_BUDGET,
        },
        "measurements": [asdict(item) for item in measurements],
        "boundary_probes": boundary_probes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run_proof(quick=args.quick), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
