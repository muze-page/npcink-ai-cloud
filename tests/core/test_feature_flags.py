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
        provider_connection_secret="p" * 32,
        **overrides,
    )


def test_feature_flags_provider_uses_settings_defaults() -> None:
    provider = EnvFeatureFlagProvider(
        _settings(
            model_intelligence_publisher_enabled=True,
            recognition_evidence_worker_enabled=False,
        )
    )

    assert provider.parse_error == ""
    assert provider.is_enabled("model_ops.publisher.enabled") is True
    assert provider.is_enabled("recognition.legacy_worker.enabled") is False
    summary = provider.build_summary()
    assert summary["summary"]["overridden_total"] == 0


def test_feature_flags_provider_applies_env_json_overrides() -> None:
    provider = EnvFeatureFlagProvider(
        _settings(
            feature_flags_json=(
                '{"portal.billing.readonly.enabled": false,'
                ' "model_ops.publisher.enabled": false,'
                ' "runtime.experimental_probe.enabled": true}'
            ),
            model_intelligence_publisher_enabled=True,
        )
    )

    assert provider.parse_error == ""
    assert provider.is_enabled("portal.billing.readonly.enabled") is False
    assert provider.is_enabled("model_ops.publisher.enabled") is False
    assert provider.is_enabled("runtime.experimental_probe.enabled") is True
    summary = provider.build_summary()
    assert summary["summary"]["overridden_total"] == 3


def test_feature_flags_provider_reports_parse_errors_without_crashing() -> None:
    provider = EnvFeatureFlagProvider(
        _settings(feature_flags_json='{"portal.billing.readonly.enabled":"maybe"}')
    )

    assert "invalid MAGICK_CLOUD_FEATURE_FLAGS_JSON entries" in provider.parse_error
    assert provider.is_enabled("portal.billing.readonly.enabled") is True
