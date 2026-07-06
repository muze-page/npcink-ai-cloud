from __future__ import annotations

import json
from pathlib import Path


def test_geo_routing_task_contract_uses_current_cloud_smoke_gate() -> None:
    contract_path = (
        Path(__file__).resolve().parents[2]
        / "docs/history/task-contract-geo-and-routing-2026-06-cleanup.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    required_gates = contract.get("required_gates", [])
    retired_gate = " ".join(
        [
            "pnpm",
            "--dir",
            "magick-ai",
            "run",
            "check:e2e:hosted-runtime:smoke",
        ]
    )

    assert "pnpm run smoke:local-alpha" in required_gates
    assert retired_gate not in required_gates
    assert "pnpm run check:risk" not in required_gates
