from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_b5_performance_proof_quick_mode_is_executable_and_bounded() -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/media-runtime-b5-performance-proof.py"),
            "--quick",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    report = json.loads(completed.stdout)

    assert report["status"] == "passed"
    assert report["mode"] == "quick"
    assert report["limits"] == {
        "deliverable_output_bytes": 25 * 1024 * 1024,
        "image_axis": 8192,
        "image_pixels": 16_777_216,
        "process_rss_delta_budget_bytes": 384 * 1024 * 1024,
        "stream_chunk_bytes": 64 * 1024,
        "stream_rss_delta_budget_bytes": 16 * 1024 * 1024,
        "upload_file_bytes": 50 * 1024 * 1024,
    }
    assert [item["name"] for item in report["measurements"]] == [
        "upload_store_1048576",
        "signed_pull_stream_1048576",
        "process_small",
    ]
    assert all(
        item["rss_delta_bytes"] <= item["budget_bytes"]
        for item in report["measurements"]
    )
    assert report["boundary_probes"] == []
