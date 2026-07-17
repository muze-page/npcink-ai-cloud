from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

from app.dev import seed_runtime


def test_seed_runtime_uses_provider_registry(monkeypatch, capsys) -> None:
    sentinel_providers = {"openai": object()}
    captured: dict[str, object] = {}

    class DummyCatalogService:
        def __init__(self, database_url: str, providers: dict[str, object] | None = None) -> None:
            captured["database_url"] = database_url
            captured["providers"] = providers

        def refresh_catalog(self) -> dict[str, object]:
            return {"revision": "catalog-test", "refreshed_count": 1}

        def scan_provider_health(self) -> dict[str, object]:
            return {"providers": ["openai"], "scanned_count": 1}

    monkeypatch.setattr(
        seed_runtime,
        "parse_args",
        lambda: Namespace(
            site_id="site_test",
            key_id="key_test",
            secret="secret_test",
            site_name="",
            scopes="runtime:resolve,runtime:execute",
            skip_catalog_refresh=False,
            skip_health_scan=False,
        ),
    )
    monkeypatch.setattr(
        seed_runtime,
        "Settings",
        lambda: SimpleNamespace(
            environment="test",
            database_url="postgresql+psycopg://test",
        ),
    )
    monkeypatch.setattr(
        seed_runtime,
        "build_provider_adapters",
        lambda settings: sentinel_providers,
    )
    monkeypatch.setattr(seed_runtime, "CatalogService", DummyCatalogService)
    monkeypatch.setattr(
        seed_runtime,
        "seed_site_auth",
        lambda **_: {"site_id": "site_test", "key_id": "key_test"},
    )

    seed_runtime.main()

    output = capsys.readouterr().out
    public_result = json.loads(output)
    assert "catalog-test" in output
    assert "database_url" not in public_result
    assert "secret_hash" not in public_result["auth"]
    assert captured["database_url"] == "postgresql+psycopg://test"
    assert captured["providers"] is sentinel_providers
