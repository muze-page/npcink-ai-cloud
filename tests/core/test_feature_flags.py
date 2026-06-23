from __future__ import annotations

from app.core.config import Settings
from app.core.feature_flags import EnvFeatureFlagProvider


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url="redis://localhost:6379/0",
        internal_auth_token="i" * 32,
        **overrides,
    )


def test_feature_flags_provider_uses_settings_defaults() -> None:
    provider = EnvFeatureFlagProvider(_settings())

    assert provider.parse_error == ""
    summary = provider.build_summary()
    assert summary["summary"]["overridden_total"] == 0


def test_feature_flags_provider_applies_env_json_overrides() -> None:
    provider = EnvFeatureFlagProvider(
        _settings(
            feature_flags_json=(
                '{"portal.billing.readonly.enabled": false,'
                ' "runtime.experimental_probe.enabled": true}'
            ),
        )
    )

    assert provider.parse_error == ""
    assert provider.is_enabled("portal.billing.readonly.enabled") is False
    assert provider.is_enabled("runtime.experimental_probe.enabled") is True
    summary = provider.build_summary()
    assert summary["summary"]["overridden_total"] == 2


def test_feature_flags_provider_reports_parse_errors_without_crashing() -> None:
    provider = EnvFeatureFlagProvider(
        _settings(feature_flags_json='{"portal.billing.readonly.enabled":"maybe"}')
    )

    assert "invalid NPCINK_CLOUD_FEATURE_FLAGS_JSON entries" in provider.parse_error
    assert provider.is_enabled("portal.billing.readonly.enabled") is True
