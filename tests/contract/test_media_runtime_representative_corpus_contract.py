from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path


def test_representative_corpus_proof_is_offline_runtime_only() -> None:
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/media-runtime-representative-corpus-proof.py"
    package_scripts = json.loads((root / "package.json").read_text())["scripts"]
    tree = ast.parse(script.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert not imported_roots.intersection({"httpx", "requests", "socket", "urllib"})
    imported_symbols = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert (
        "app.domain.media_derivatives.artifacts",
        "validate_image_upload_stream",
    ) in imported_symbols
    assert (
        "app.domain.media_derivatives.processor",
        "process_media_derivative",
    ) in imported_symbols
    called_names = [
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert called_names.count("validate_image_upload_stream") >= 2
    assert called_names.count("process_media_derivative") == 1
    source = script.read_text(encoding="utf-8")
    assert "LocalVolumeArtifactStore" not in source
    assert "create_artifact" not in source
    assert package_scripts["check:media:corpus"] == (
        "docker compose -f docker-compose.dev.yml run --rm "
        "-e NPCINK_CLOUD_OPENAI_API_KEY= api python "
        "scripts/media-runtime-representative-corpus-proof.py"
    )


def test_representative_corpus_proof_reports_current_formats_and_fail_closed_inputs() -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/media-runtime-representative-corpus-proof.py"),
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    report = json.loads(completed.stdout)

    assert report["status"] == "passed"
    assert report["contract_version"] == "media_runtime_representative_corpus_proof.v1"
    assert report["boundary"] == {
        "bytes_persisted": False,
        "cms_write_performed": False,
        "network_used": False,
    }
    assert report["measurement_scope"] == {
        "case_elapsed": (
            "upload validation, upload checksum comparison, image transform, "
            "and output verification; source generation and source inspection excluded"
        ),
        "case_rss_delta": (
            "RSS growth during the case pipeline after the generated source is resident"
        ),
        "peak_rss": "whole-process RSS observed while the case pipeline runs",
        "suite_elapsed": "source generation, source inspection, case pipelines, and rejects",
    }
    assert report["limits"] == {
        "case_elapsed_budget_ms": 5_000.0,
        "case_rss_delta_budget_bytes": 128 * 1024 * 1024,
        "deliverable_output_bytes": 25 * 1024 * 1024,
        "suite_elapsed_budget_ms": 20_000.0,
        "upload_bytes": 50 * 1024 * 1024,
    }
    assert report["suite_elapsed_ms"] <= report["limits"]["suite_elapsed_budget_ms"]

    expected_cases = {
        "jpeg_to_webp": ("jpeg", "image/jpeg", 1280, 720, "webp", "image/webp", 960, 540),
        "png_alpha_to_png": ("png", "image/png", 1024, 768, "png", "image/png", 640, 480),
        "webp_to_jpeg": ("webp", "image/webp", 960, 640, "jpeg", "image/jpeg", 720, 480),
        "jpeg_exif_orientation_to_png": (
            "jpeg",
            "image/jpeg",
            640,
            360,
            "png",
            "image/png",
            360,
            640,
        ),
        "large_random_png_to_webp": (
            "png",
            "image/png",
            2304,
            2304,
            "webp",
            "image/webp",
            1600,
            1600,
        ),
    }
    assert {item["name"] for item in report["cases"]} == set(expected_cases)
    for item in report["cases"]:
        expected = expected_cases[item["name"]]
        assert item["status"] == "passed"
        assert item["operation"] == "image.transform.v1"
        assert (
            item["input"]["format"],
            item["input"]["mime_type"],
            item["input"]["width"],
            item["input"]["height"],
            item["output"]["format"],
            item["output"]["mime_type"],
            item["output"]["width"],
            item["output"]["height"],
        ) == expected
        assert 0 < item["input"]["bytes"] <= report["limits"]["upload_bytes"]
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", item["input"]["checksum"])
        assert item["input"]["checksum_verified"] is True
        assert 0 < item["output"]["bytes"] <= report["limits"]["deliverable_output_bytes"]
        assert item["elapsed_ms"] <= item["elapsed_budget_ms"]
        assert item["rss_delta_bytes"] <= item["rss_delta_budget_bytes"]
        assert item["peak_rss_bytes"] > 0
        assert item["properties"]["metadata_stripped"] is True
        expected_orientation = item["name"] == "jpeg_exif_orientation_to_png"
        assert item["properties"]["orientation_applied"] is expected_orientation

    alpha_case = next(item for item in report["cases"] if item["name"] == "png_alpha_to_png")
    assert alpha_case["source_evidence"]["structured_alpha"] is True
    assert alpha_case["source_evidence"]["source_alpha_levels"] >= 64
    assert alpha_case["properties"]["alpha_plane_matches_expected"] is True

    metadata_case = next(
        item
        for item in report["cases"]
        if item["name"] == "jpeg_exif_orientation_to_png"
    )
    assert metadata_case["source_evidence"] == {
        "exif_artist_present": True,
        "exif_description_present": True,
        "gps_present": True,
        "icc_profile_present": True,
        "orientation": 6,
        "private_metadata_injected": True,
        "structured_alpha": False,
    }
    assert metadata_case["properties"]["metadata_stripped"] is True
    assert metadata_case["properties"]["orientation_applied"] is True
    assert metadata_case["properties"]["orientation_pixels_match_expected"] is True

    large_case = next(
        item for item in report["cases"] if item["name"] == "large_random_png_to_webp"
    )
    assert 5 * 1024 * 1024 <= large_case["input"]["bytes"] <= 25 * 1024 * 1024

    assert [item["name"] for item in report["rejections"]] == [
        "animated_gif",
        "unsupported_static_bmp",
    ]
    assert [item["observed_error_code"] for item in report["rejections"]] == [
        "media_derivative.animated_source_unavailable",
        "media_upload.format_unavailable",
    ]
    for item in report["rejections"]:
        assert item["status"] == "rejected"
        assert item["stage"] == "upload_validation"
        assert item["observed_error_code"] == item["expected_error_code"]
        assert item["elapsed_ms"] <= item["elapsed_budget_ms"]
        assert item["rss_delta_bytes"] <= item["rss_delta_budget_bytes"]
        assert item["peak_rss_bytes"] > 0
