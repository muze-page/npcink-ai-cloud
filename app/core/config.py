from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.models import PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MAGICK_CLOUD_",
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    project_name: str = Field(default="Magick AI Cloud")
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    database_url: str = Field(
        default="postgresql+psycopg://magick:magick@postgres:5432/magick_ai_cloud"
    )
    redis_url: str = Field(default="redis://redis:6379/0")
    runtime_queue_key: str = Field(default="magick_ai_cloud:runtime_queue")
    runtime_worker_poll_seconds: int = Field(default=5)
    runtime_callback_worker_poll_seconds: int = Field(default=5)
    worker_heartbeat_interval_seconds: int = Field(default=60)
    runtime_worker_batch_size: int = Field(default=8)
    runtime_callback_batch_size: int = Field(default=8)
    runtime_callback_timeout_seconds: float = Field(default=10.0)
    runtime_callback_max_attempts: int = Field(default=3)
    runtime_callback_retry_backoff_seconds: int = Field(default=30)
    ops_cadence_poll_seconds: int = Field(default=30)
    retention_cleanup_interval_seconds: int = Field(default=3600)
    usage_rollup_interval_seconds: int = Field(default=3600)
    router_diagnostics_interval_seconds: int = Field(default=900)
    latency_probe_interval_seconds: int = Field(default=900)
    alert_provider_degradation_interval_seconds: int = Field(default=900)
    provider_health_scan_interval_seconds: int = Field(default=900)
    router_performance_worker_window_hours: int = Field(default=1)
    router_performance_worker_site_limit: int = Field(default=100)
    router_diagnostics_worker_recent_minutes: int = Field(default=60)
    router_diagnostics_worker_site_limit: int = Field(default=100)
    latency_probe_worker_recent_minutes: int = Field(default=360)
    latency_probe_worker_site_limit: int = Field(default=100)
    latency_probe_worker_instance_limit: int = Field(default=20)
    alert_worker_window_minutes: int = Field(default=30)
    alert_worker_site_limit: int = Field(default=100)
    alert_worker_min_requests: int = Field(default=20)
    alert_worker_error_rate_threshold: float = Field(default=0.25)
    alert_worker_latency_ms_threshold: int = Field(default=20000)
    auth_timestamp_tolerance_seconds: int = Field(default=300)
    public_post_rate_limit_window_seconds: int = Field(default=60)
    public_post_max_requests_per_window: int = Field(default=120)
    public_post_max_requests_per_key_window: int = Field(default=90)
    public_post_max_requests_per_ip_window: int = Field(default=150)
    public_guard_cooldown_window_seconds: int = Field(default=1800)
    public_guard_max_reject_events_per_site_window: int = Field(default=20)
    public_guard_max_reject_events_per_key_window: int = Field(default=16)
    public_guard_max_reject_events_per_ip_window: int = Field(default=24)
    internal_post_rate_limit_window_seconds: int = Field(default=60)
    internal_post_max_requests_per_window: int = Field(default=240)
    internal_post_max_requests_per_ip_window: int = Field(default=300)
    internal_guard_cooldown_window_seconds: int = Field(default=1800)
    internal_guard_max_reject_events_per_token_window: int = Field(default=40)
    internal_guard_max_reject_events_per_ip_window: int = Field(default=50)
    internal_auth_token: str | None = Field(default=None)
    admin_bootstrap_token: str | None = Field(default=None)
    admin_session_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_ADMIN_SESSION_SECRET",
            "MAGICK_CLOUD_OPS_SESSION_SECRET",
        ),
    )
    debug_local_origin_allowlist: str = Field(default="")
    browser_origin_allowlist: str = Field(default="")
    trusted_host_allowlist: str = Field(default="")
    allow_dev_admin_internal_token_fallback: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_ALLOW_DEV_ADMIN_INTERNAL_TOKEN_FALLBACK",
            "MAGICK_CLOUD_ALLOW_DEV_OPS_INTERNAL_TOKEN_FALLBACK",
        ),
    )
    allow_dev_ops_internal_token_fallback: bool = Field(default=False)
    admin_session_ttl_seconds: int = Field(
        default=8 * 60 * 60,
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_ADMIN_SESSION_TTL_SECONDS",
            "MAGICK_CLOUD_OPS_SESSION_TTL_SECONDS",
        ),
    )
    admin_bootstrap_admin_ref: str = Field(
        default="platform:internal_root",
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_REF",
            "MAGICK_CLOUD_OPS_BOOTSTRAP_ADMIN_REF",
        ),
    )
    admin_bootstrap_admin_role: str = Field(
        default=PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_ADMIN_BOOTSTRAP_ADMIN_ROLE",
            "MAGICK_CLOUD_OPS_BOOTSTRAP_ADMIN_ROLE",
        ),
    )
    portal_jwt_secret: str | None = Field(default=None)
    portal_jwt_algorithm: str = Field(default="HS256")
    portal_jwt_issuer: str | None = Field(default=None)
    portal_jwt_audience: str | None = Field(default=None)
    portal_session_ttl_seconds: int = Field(default=8 * 60 * 60)
    portal_login_code_ttl_seconds: int = Field(default=10 * 60)
    portal_login_code_max_attempts: int = Field(default=5)
    portal_public_base_url: str | None = Field(default=None)
    portal_email_smtp_host: str | None = Field(default=None)
    portal_email_smtp_port: int = Field(default=465)
    portal_email_smtp_username: str | None = Field(default=None)
    portal_email_smtp_password: str | None = Field(default=None)
    portal_email_smtp_use_ssl: bool = Field(default=True)
    portal_email_smtp_use_starttls: bool = Field(default=False)
    portal_email_smtp_timeout_seconds: float = Field(default=20.0)
    portal_email_from_email: str | None = Field(default=None)
    portal_email_from_name: str | None = Field(default=None)
    portal_email_reply_to: str | None = Field(default=None)
    otel_service_name: str = Field(default="magick-ai-cloud")
    otel_exporter_otlp_endpoint: str | None = Field(default=None)
    otel_trace_sink_otlp_endpoint: str | None = Field(default=None)
    otel_trace_query_url: str | None = Field(default=None)
    feature_flags_json: str = Field(default="")
    deployment_region: str = Field(default="unspecified")
    audit_retention_days_default: int = Field(default=90)
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_OPENAI_BASE_URL",
            "MAGICK_CLOUD_OPENAI_COMPATIBLE_BASE_URL",
        ),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_OPENAI_API_KEY",
            "MAGICK_CLOUD_OPENAI_COMPATIBLE_API_KEY",
        ),
    )
    openai_organization: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_OPENAI_ORGANIZATION",
            "MAGICK_CLOUD_OPENAI_COMPATIBLE_ORGANIZATION",
        ),
    )
    openai_timeout_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_OPENAI_TIMEOUT_SECONDS",
            "MAGICK_CLOUD_OPENAI_COMPATIBLE_TIMEOUT_SECONDS",
        ),
    )
    openai_sample_catalog_profile: str = Field(
        default="",
        validation_alias=AliasChoices(
            "MAGICK_CLOUD_OPENAI_SAMPLE_CATALOG_PROFILE",
            "MAGICK_CLOUD_OPENAI_COMPATIBLE_SAMPLE_CATALOG_PROFILE",
        ),
    )
    litellm_provider_enabled: bool = Field(default=False)
    litellm_base_url: str | None = Field(default=None)
    litellm_api_key: str | None = Field(default=None)
    litellm_timeout_seconds: float = Field(default=30.0)
    vllm_provider_enabled: bool = Field(default=False)
    vllm_base_url: str | None = Field(default=None)
    vllm_api_key: str | None = Field(default=None)
    vllm_timeout_seconds: float = Field(default=30.0)
    tei_provider_enabled: bool = Field(default=False)
    tei_base_url: str | None = Field(default=None)
    tei_api_key: str | None = Field(default=None)
    tei_timeout_seconds: float = Field(default=30.0)
    tei_model_ids: str = Field(default="")
    tei_region: str = Field(default="self-hosted")
    tei_context_window: int = Field(default=8192)
    openrouter_provider_enabled: bool = Field(default=False)
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")
    openrouter_api_key: str | None = Field(default=None)
    openrouter_timeout_seconds: float = Field(default=30.0)
    openrouter_site_url: str | None = Field(default=None)
    siliconflow_pricing_url: str = Field(default="https://www2.siliconflow.cn/pricing")
    siliconflow_timeout_seconds: float = Field(default=30.0)
    huggingface_base_url: str = Field(default="https://huggingface.co")
    huggingface_api_token: str | None = Field(default=None)
    huggingface_timeout_seconds: float = Field(default=30.0)
    huggingface_model_allowlist: str = Field(default="")
    ollama_base_url: str | None = Field(default=None)
    ollama_api_key: str | None = Field(default=None)
    ollama_timeout_seconds: float = Field(default=30.0)
    ollama_model_allowlist: str = Field(default="")
    ollama_catalog_enabled: bool = Field(default=False)
    ollama_catalog_limit: int = Field(default=250)
    anthropic_base_url: str = Field(default="https://api.anthropic.com")
    anthropic_api_key: str | None = Field(default=None)
    anthropic_version: str = Field(default="2023-06-01")
    anthropic_timeout_seconds: float = Field(default=30.0)

    @staticmethod
    def _normalize_origin(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        parsed = urlsplit(raw)
        if not parsed.scheme or not parsed.netloc:
            return ""
        port = f":{parsed.port}" if parsed.port is not None else ""
        host = str(parsed.hostname or "").strip().lower()
        if not host:
            return ""
        return f"{parsed.scheme.lower()}://{host}{port}"

    @staticmethod
    def _normalize_host(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        if "://" in raw:
            parsed = urlsplit(raw)
            host = str(parsed.hostname or "").strip().lower()
            if not host:
                return ""
            port = f":{parsed.port}" if parsed.port is not None else ""
            return f"{host}{port}"
        host, _, _rest = raw.partition(",")
        host = host.strip().lower()
        if not host:
            return ""
        if host.startswith("[") and "]" in host:
            return host
        return host

    def production_like_environment(self) -> bool:
        return str(self.environment or "").strip().lower() in {"production", "prod", "staging"}

    def explicit_browser_origins(self) -> set[str]:
        origins = {
            self._normalize_origin(item)
            for item in (
                *str(self.browser_origin_allowlist or "").split(","),
                str(self.portal_public_base_url or ""),
            )
        }
        return {origin for origin in origins if origin}

    def trusted_hosts(self) -> set[str]:
        hosts = {
            self._normalize_host(item)
            for item in (
                *str(self.trusted_host_allowlist or "").split(","),
                str(self.portal_public_base_url or ""),
            )
        }
        hosts = {host for host in hosts if host}
        environment = str(self.environment or "").strip().lower()
        if environment in {"development", "test"}:
            hosts.update(
                {
                    "127.0.0.1",
                    "127.0.0.1:8000",
                    "127.0.0.1:8010",
                    "localhost",
                    "localhost:8000",
                    "localhost:8010",
                    "api",
                    "api:8000",
                    "frontend",
                    "frontend:3000",
                    "proxy",
                    "proxy:8080",
                    "testserver",
                }
            )
        return hosts

    @model_validator(mode="after")
    def validate_security_settings(self) -> Settings:
        if (
            not self.allow_dev_admin_internal_token_fallback
            and self.allow_dev_ops_internal_token_fallback
        ):
            self.allow_dev_admin_internal_token_fallback = True
        production_like = self.production_like_environment()
        secret_fields = {
            "internal_auth_token": self.internal_auth_token,
            "admin_bootstrap_token": self.admin_bootstrap_token,
            "admin_session_secret": self.admin_session_secret,
            "portal_jwt_secret": self.portal_jwt_secret,
        }
        for field_name, raw_value in secret_fields.items():
            value = str(raw_value or "").strip()
            if value and len(value) < 32:
                raise ValueError(f"{field_name} must be at least 32 bytes long")
        if production_like and self.allow_dev_admin_internal_token_fallback:
            raise ValueError(
                "allow_dev_admin_internal_token_fallback is only allowed in development/test"
            )
        if production_like and str(self.openai_sample_catalog_profile or "").strip():
            raise ValueError(
                "openai_sample_catalog_profile is only allowed in development/test"
            )
        if production_like and not str(self.admin_session_secret or "").strip():
            raise ValueError(
                "admin_session_secret is required outside development/test environments"
            )
        if production_like and not str(self.internal_auth_token or "").strip():
            raise ValueError(
                "internal_auth_token is required outside development/test environments"
            )
        if production_like and not str(self.admin_bootstrap_token or "").strip():
            raise ValueError(
                "admin_bootstrap_token is required outside development/test environments"
            )
        if (
            production_like
            and str(self.admin_bootstrap_token or "").strip()
            and str(self.admin_bootstrap_token or "").strip()
            == str(self.internal_auth_token or "").strip()
        ):
            raise ValueError(
                "admin_bootstrap_token must differ from internal_auth_token outside development/test environments"
            )
        if production_like and not str(self.portal_public_base_url or "").strip():
            raise ValueError(
                "portal_public_base_url is required outside development/test environments"
            )
        if production_like and not str(self.portal_jwt_secret or "").strip():
            raise ValueError(
                "portal_jwt_secret is required outside development/test environments"
            )
        if production_like and not str(self.portal_email_smtp_host or "").strip():
            raise ValueError(
                "portal_email_smtp_host is required outside development/test environments"
            )
        if production_like and not str(self.portal_email_from_email or "").strip():
            raise ValueError(
                "portal_email_from_email is required outside development/test environments"
            )
        if production_like and not self.explicit_browser_origins():
            raise ValueError(
                "browser_origin_allowlist or portal_public_base_url is required outside development/test environments"
            )
        if production_like and not self.trusted_hosts():
            raise ValueError(
                "trusted_host_allowlist or portal_public_base_url is required outside development/test environments"
            )
        if self.ops_cadence_poll_seconds < 5:
            raise ValueError("ops_cadence_poll_seconds must be at least 5")
        if self.runtime_callback_worker_poll_seconds < 1:
            raise ValueError("runtime_callback_worker_poll_seconds must be at least 1")
        if self.worker_heartbeat_interval_seconds < 30:
            raise ValueError("worker_heartbeat_interval_seconds must be at least 30")
        if self.retention_cleanup_interval_seconds < 60:
            raise ValueError("retention_cleanup_interval_seconds must be at least 60")
        if self.usage_rollup_interval_seconds < 60:
            raise ValueError("usage_rollup_interval_seconds must be at least 60")
        if self.router_diagnostics_interval_seconds < 60:
            raise ValueError("router_diagnostics_interval_seconds must be at least 60")
        if self.latency_probe_interval_seconds < 60:
            raise ValueError("latency_probe_interval_seconds must be at least 60")
        if self.alert_provider_degradation_interval_seconds < 60:
            raise ValueError("alert_provider_degradation_interval_seconds must be at least 60")
        if self.provider_health_scan_interval_seconds < 60:
            raise ValueError("provider_health_scan_interval_seconds must be at least 60")
        if self.router_performance_worker_window_hours < 1:
            raise ValueError("router_performance_worker_window_hours must be at least 1")
        if self.router_performance_worker_site_limit < 1:
            raise ValueError("router_performance_worker_site_limit must be at least 1")
        if not 1 <= self.router_diagnostics_worker_recent_minutes <= 1440:
            raise ValueError("router_diagnostics_worker_recent_minutes must be between 1 and 1440")
        if self.router_diagnostics_worker_site_limit < 1:
            raise ValueError("router_diagnostics_worker_site_limit must be at least 1")
        if not 1 <= self.latency_probe_worker_recent_minutes <= 1440:
            raise ValueError("latency_probe_worker_recent_minutes must be between 1 and 1440")
        if self.latency_probe_worker_site_limit < 1:
            raise ValueError("latency_probe_worker_site_limit must be at least 1")
        if self.latency_probe_worker_instance_limit < 1:
            raise ValueError("latency_probe_worker_instance_limit must be at least 1")
        if not 5 <= self.alert_worker_window_minutes <= 1440:
            raise ValueError("alert_worker_window_minutes must be between 5 and 1440")
        if self.alert_worker_site_limit < 1:
            raise ValueError("alert_worker_site_limit must be at least 1")
        if self.alert_worker_min_requests < 1:
            raise ValueError("alert_worker_min_requests must be at least 1")
        if not 0.01 <= self.alert_worker_error_rate_threshold <= 1.0:
            raise ValueError("alert_worker_error_rate_threshold must be between 0.01 and 1.0")
        if self.alert_worker_latency_ms_threshold < 1:
            raise ValueError("alert_worker_latency_ms_threshold must be at least 1")
        if self.litellm_timeout_seconds <= 0:
            raise ValueError("litellm_timeout_seconds must be greater than 0")
        if self.vllm_timeout_seconds <= 0:
            raise ValueError("vllm_timeout_seconds must be greater than 0")
        if self.tei_timeout_seconds <= 0:
            raise ValueError("tei_timeout_seconds must be greater than 0")
        if self.tei_context_window <= 0:
            raise ValueError("tei_context_window must be greater than 0")
        if self.openrouter_timeout_seconds <= 0:
            raise ValueError("openrouter_timeout_seconds must be greater than 0")
        if self.siliconflow_timeout_seconds <= 0:
            raise ValueError("siliconflow_timeout_seconds must be greater than 0")
        if self.huggingface_timeout_seconds <= 0:
            raise ValueError("huggingface_timeout_seconds must be greater than 0")
        if self.ollama_timeout_seconds <= 0:
            raise ValueError("ollama_timeout_seconds must be greater than 0")
        if self.ollama_catalog_limit <= 0:
            raise ValueError("ollama_catalog_limit must be greater than 0")
        if self.litellm_provider_enabled and not str(self.litellm_base_url or "").strip():
            raise ValueError("litellm_base_url is required when litellm_provider_enabled is true")
        if self.vllm_provider_enabled and not str(self.vllm_base_url or "").strip():
            raise ValueError("vllm_base_url is required when vllm_provider_enabled is true")
        if self.tei_provider_enabled and not str(self.tei_base_url or "").strip():
            raise ValueError("tei_base_url is required when tei_provider_enabled is true")
        if self.tei_provider_enabled and not str(self.tei_model_ids or "").strip():
            raise ValueError("tei_model_ids is required when tei_provider_enabled is true")
        if self.openrouter_provider_enabled and not str(self.openrouter_api_key or "").strip():
            raise ValueError(
                "openrouter_api_key is required when openrouter_provider_enabled is true"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
