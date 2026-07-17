from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.models import PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN


class Settings(BaseSettings):
    artifact_store_root: str = Field(default="/tmp/npcink-ai-cloud-artifacts")
    artifact_store_chunk_bytes: int = Field(default=64 * 1024, ge=4096, le=1024 * 1024)
    model_config = SettingsConfigDict(
        env_prefix="NPCINK_CLOUD_",
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    project_name: str = Field(default="Npcink AI Cloud")
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    database_url: str = Field(
        default="postgresql+psycopg://npcink:npcink@postgres:5432/npcink_ai_cloud"
    )
    redis_url: str = Field(default="redis://redis:6379/0")
    runtime_queue_key: str = Field(default="npcink_ai_cloud:runtime_queue")
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
    plugin_observability_retention_days: int = Field(default=180)
    plugin_observability_cleanup_interval_seconds: int = Field(default=86400)
    usage_rollup_interval_seconds: int = Field(default=3600)
    router_diagnostics_interval_seconds: int = Field(default=900)
    latency_probe_interval_seconds: int = Field(default=900)
    alert_provider_degradation_interval_seconds: int = Field(default=900)
    provider_health_scan_interval_seconds: int = Field(default=900)
    media_upload_max_body_bytes: int = Field(
        default=51 * 1024 * 1024,
        ge=1,
        le=51 * 1024 * 1024,
    )
    media_derivative_batch_default_chunk_size: int = Field(default=10)
    media_derivative_batch_max_chunk_size: int = Field(default=20)
    media_derivative_site_queued_limit: int = Field(default=100)
    media_derivative_site_running_limit: int = Field(default=2)
    artifact_cleanup_interval_seconds: int = Field(default=3600)
    artifact_reconciliation_interval_seconds: int = Field(default=3600, ge=60)
    artifact_reconciliation_safety_window_seconds: int = Field(default=86400, ge=3600)
    artifact_reconciliation_page_size: int = Field(default=200, ge=1, le=500)
    artifact_reconciliation_lease_seconds: int = Field(default=300, ge=300, le=3600)
    artifact_orphan_cleanup_enabled: bool = Field(default=False)
    artifact_orphan_cleanup_batch_size: int = Field(default=25, ge=1, le=100)
    artifact_orphan_claim_lease_seconds: int = Field(default=300, ge=30, le=3600)
    artifact_orphan_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    artifact_orphan_retry_max_seconds: int = Field(default=3600, ge=1, le=86400)
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
    public_pull_rate_limit_window_seconds: int = Field(default=60)
    public_pull_max_requests_per_window: int = Field(default=120)
    public_pull_max_requests_per_key_window: int = Field(default=90)
    public_pull_max_requests_per_ip_window: int = Field(default=150)
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
    admin_session_secret: str | None = Field(default=None)
    service_settings_secret: str | None = Field(default=None)
    debug_local_origin_allowlist: str = Field(default="")
    browser_origin_allowlist: str = Field(default="")
    trusted_host_allowlist: str = Field(default="")
    allow_dev_admin_internal_token_fallback: bool = Field(default=False)
    admin_session_ttl_seconds: int = Field(default=8 * 60 * 60)
    admin_bootstrap_principal_id: str = Field(
        default="platform:internal_root",
        validation_alias="NPCINK_CLOUD_ADMIN_BOOTSTRAP_PRINCIPAL_ID",
    )
    admin_bootstrap_platform_admin_role: str = Field(
        default=PLATFORM_ADMIN_ROLE_PLATFORM_ADMIN,
        validation_alias="NPCINK_CLOUD_ADMIN_BOOTSTRAP_PLATFORM_ADMIN_ROLE",
    )
    portal_jwt_secret: str | None = Field(default=None)
    portal_jwt_algorithm: str = Field(default="HS256")
    portal_jwt_issuer: str | None = Field(default=None)
    portal_jwt_audience: str | None = Field(default=None)
    portal_session_ttl_seconds: int = Field(default=8 * 60 * 60)
    portal_remember_me_session_ttl_seconds: int = Field(default=7 * 24 * 60 * 60)
    portal_login_code_ttl_seconds: int = Field(default=10 * 60)
    portal_login_code_max_attempts: int = Field(default=5)
    portal_oauth_state_ttl_seconds: int = Field(default=10 * 60)
    otel_service_name: str = Field(default="npcink-ai-cloud")
    otel_exporter_otlp_endpoint: str | None = Field(default=None)
    otel_trace_sink_otlp_endpoint: str | None = Field(default=None)
    otel_trace_query_url: str | None = Field(default=None)
    deployment_region: str = Field(default="unspecified")
    audit_retention_days_default: int = Field(default=90)
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    openai_api_key: str | None = Field(default=None)
    openai_organization: str | None = Field(default=None)
    openai_timeout_seconds: float = Field(default=60.0)
    openai_sample_catalog_profile: str = Field(default="")
    openai_provider_label: str = Field(default="")
    minimax_provider_enabled: bool = Field(default=False)
    minimax_base_url: str = Field(default="https://api.minimaxi.com")
    minimax_api_key: str | None = Field(default=None)
    minimax_group_id: str | None = Field(default=None)
    minimax_timeout_seconds: float = Field(default=30.0)
    minimax_default_voice_id: str = Field(default="male-qn-qingse")
    minimax_admin_env_path: str = Field(default=".env.local")
    audio_generation_artifact_ttl_minutes: int = Field(default=60)
    audio_generation_artifact_max_bytes: int = Field(default=24 * 1024 * 1024)
    audio_generation_artifact_download_timeout_seconds: float = Field(default=20.0)
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
    internal_ops_summarizer_provider_allowlist: str = Field(default="")
    site_knowledge_vector_backend: str = Field(default="postgres_json")
    site_knowledge_embedding_provider: str = Field(default="deterministic")
    site_knowledge_embedding_model: str = Field(default="BAAI/bge-m3")
    site_knowledge_embedding_dimensions: int = Field(default=1024)
    site_knowledge_vector_metric_type: str = Field(default="COSINE")
    site_knowledge_comments_enabled: bool = Field(default=False)
    site_knowledge_max_sync_documents_per_run: int = Field(default=500)
    site_knowledge_max_sync_chunks_per_run: int = Field(default=5000)
    site_knowledge_max_indexed_documents_per_site: int = Field(default=10000)
    site_knowledge_max_indexed_chunks_per_site: int = Field(default=200000)
    site_knowledge_quota_warning_ratio: float = Field(default=0.85)
    site_knowledge_rerank_provider: str = Field(default="disabled")
    site_knowledge_rerank_top_k: int = Field(default=30)
    site_knowledge_rerank_timeout_seconds: float = Field(default=8.0)
    site_knowledge_jina_base_url: str = Field(default="https://api.jina.ai")
    site_knowledge_jina_api_key: str | None = Field(default=None)
    site_knowledge_jina_rerank_model: str = Field(default="jina-reranker-v3")
    site_knowledge_zilliz_uri: str | None = Field(default=None)
    site_knowledge_zilliz_token: str | None = Field(default=None)
    site_knowledge_zilliz_database: str | None = Field(default=None)
    site_knowledge_zilliz_collection: str = Field(default="npcink_site_knowledge_chunks")
    site_knowledge_zilliz_timeout_seconds: float = Field(default=10.0)
    web_search_provider: str = Field(default="disabled")
    web_search_tavily_base_url: str = Field(default="https://api.tavily.com")
    web_search_tavily_api_key: str | None = Field(default=None)
    web_search_tavily_api_keys: str | None = Field(default=None)
    web_search_tavily_api_key_labels: str | None = Field(default=None)
    web_search_tavily_timeout_seconds: float = Field(default=15.0)
    web_search_tavily_cost_per_query: float = Field(default=0.0)
    web_search_bocha_base_url: str = Field(default="https://api.bochaai.com/v1")
    web_search_bocha_api_key: str | None = Field(default=None)
    web_search_bocha_timeout_seconds: float = Field(default=15.0)
    web_search_bocha_cost_per_query: float = Field(default=0.0)
    web_search_jina_reader_enabled: bool = Field(default=False)
    web_search_jina_reader_base_url: str = Field(default="https://r.jina.ai")
    web_search_jina_reader_api_key: str | None = Field(default=None)
    web_search_jina_reader_timeout_seconds: float = Field(default=15.0)
    web_search_jina_reader_max_pages: int = Field(default=2)
    web_search_jina_reader_cost_per_page: float = Field(default=0.0)
    web_search_apify_base_url: str = Field(default="https://api.apify.com/v2")
    web_search_apify_api_token: str | None = Field(default=None)
    web_search_apify_actor_id: str = Field(default="apify/google-search-scraper")
    web_search_apify_timeout_seconds: float = Field(default=30.0)
    web_search_apify_cost_per_query: float = Field(default=0.0)
    web_search_zhihu_base_url: str = Field(default="https://developer.zhihu.com")
    web_search_zhihu_access_secret: str | None = Field(default=None)
    web_search_zhihu_search_path: str = Field(default="/api/v1/content/zhihu_search")
    web_search_zhihu_global_search_path: str = Field(default="/api/v1/content/global_search")
    web_search_zhihu_hot_list_path: str = Field(default="/api/v1/content/hot_list")
    web_search_zhihu_direct_answer_path: str = Field(default="/v1/chat/completions")
    web_search_zhihu_timeout_seconds: float = Field(default=15.0)
    web_search_zhihu_cost_per_query: float = Field(default=0.0)
    web_search_zhihu_hot_list_cache_ttl_seconds: int = Field(default=3600)
    web_search_admin_env_path: str = Field(default=".env.local")
    image_source_provider: str = Field(default="disabled")
    image_source_auto_strategy: str = Field(default="fast_first")
    image_source_unsplash_base_url: str = Field(default="https://api.unsplash.com")
    image_source_unsplash_access_key: str | None = Field(default=None)
    image_source_pixabay_base_url: str = Field(default="https://pixabay.com/api/")
    image_source_pixabay_api_key: str | None = Field(default=None)
    image_source_pexels_base_url: str = Field(default="https://api.pexels.com/v1")
    image_source_pexels_api_key: str | None = Field(default=None)
    image_source_timeout_seconds: float = Field(default=15.0)
    image_source_cost_per_query: float = Field(default=0.0)
    image_source_admin_env_path: str = Field(default=".env.local")
    openrouter_provider_enabled: bool = Field(default=False)
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")
    openrouter_api_key: str | None = Field(default=None)
    openrouter_timeout_seconds: float = Field(default=30.0)
    openrouter_site_url: str | None = Field(default=None)
    siliconflow_provider_enabled: bool = Field(default=False)
    siliconflow_base_url: str = Field(default="https://api.siliconflow.cn/v1")
    siliconflow_api_key: str | None = Field(default=None)
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
            for item in str(self.browser_origin_allowlist or "").split(",")
        }
        return {origin for origin in origins if origin}

    def trusted_hosts(self) -> set[str]:
        hosts = {
            self._normalize_host(item) for item in str(self.trusted_host_allowlist or "").split(",")
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
        production_like = self.production_like_environment()
        secret_fields = {
            "internal_auth_token": self.internal_auth_token,
            "admin_bootstrap_token": self.admin_bootstrap_token,
            "admin_session_secret": self.admin_session_secret,
            "service_settings_secret": self.service_settings_secret,
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
            raise ValueError("openai_sample_catalog_profile is only allowed in development/test")
        if production_like and not str(self.admin_session_secret or "").strip():
            raise ValueError(
                "admin_session_secret is required outside development/test environments"
            )
        if production_like and not str(self.service_settings_secret or "").strip():
            raise ValueError(
                "service_settings_secret is required outside development/test environments"
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
                "admin_bootstrap_token must differ from internal_auth_token outside "
                "development/test environments"
            )
        if production_like and not str(self.portal_jwt_secret or "").strip():
            raise ValueError("portal_jwt_secret is required outside development/test environments")
        if production_like and not self.explicit_browser_origins():
            raise ValueError(
                "browser_origin_allowlist is required outside development/test environments"
            )
        if production_like and not self.trusted_hosts():
            raise ValueError(
                "trusted_host_allowlist is required outside development/test environments"
            )
        if self.portal_oauth_state_ttl_seconds < 60:
            raise ValueError("portal_oauth_state_ttl_seconds must be at least 60")
        if self.ops_cadence_poll_seconds < 5:
            raise ValueError("ops_cadence_poll_seconds must be at least 5")
        if self.runtime_callback_worker_poll_seconds < 1:
            raise ValueError("runtime_callback_worker_poll_seconds must be at least 1")
        if self.worker_heartbeat_interval_seconds < 30:
            raise ValueError("worker_heartbeat_interval_seconds must be at least 30")
        if self.retention_cleanup_interval_seconds < 60:
            raise ValueError("retention_cleanup_interval_seconds must be at least 60")
        if self.plugin_observability_retention_days < 1:
            raise ValueError("plugin_observability_retention_days must be at least 1")
        if self.plugin_observability_cleanup_interval_seconds < 60:
            raise ValueError("plugin_observability_cleanup_interval_seconds must be at least 60")
        if self.artifact_cleanup_interval_seconds < 60:
            raise ValueError("artifact_cleanup_interval_seconds must be at least 60")
        if self.artifact_orphan_retry_max_seconds < self.artifact_orphan_retry_base_seconds:
            raise ValueError(
                "artifact_orphan_retry_max_seconds must not be less than "
                "artifact_orphan_retry_base_seconds"
            )
        if self.media_derivative_batch_default_chunk_size < 1:
            raise ValueError("media_derivative_batch_default_chunk_size must be at least 1")
        if not 1 <= self.media_derivative_batch_max_chunk_size <= 100:
            raise ValueError("media_derivative_batch_max_chunk_size must be between 1 and 100")
        if (
            self.media_derivative_batch_default_chunk_size
            > self.media_derivative_batch_max_chunk_size
        ):
            raise ValueError(
                "media_derivative_batch_default_chunk_size must not exceed "
                "media_derivative_batch_max_chunk_size"
            )
        if self.media_derivative_site_queued_limit < 1:
            raise ValueError("media_derivative_site_queued_limit must be at least 1")
        if self.media_derivative_site_running_limit < 1:
            raise ValueError("media_derivative_site_running_limit must be at least 1")
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
        if self.site_knowledge_embedding_dimensions <= 0:
            raise ValueError("site_knowledge_embedding_dimensions must be greater than 0")
        if self.site_knowledge_max_sync_documents_per_run <= 0:
            raise ValueError("site_knowledge_max_sync_documents_per_run must be greater than 0")
        if self.site_knowledge_max_sync_chunks_per_run <= 0:
            raise ValueError("site_knowledge_max_sync_chunks_per_run must be greater than 0")
        if self.site_knowledge_max_indexed_documents_per_site <= 0:
            raise ValueError("site_knowledge_max_indexed_documents_per_site must be greater than 0")
        if self.site_knowledge_max_indexed_chunks_per_site <= 0:
            raise ValueError("site_knowledge_max_indexed_chunks_per_site must be greater than 0")
        if not 0 < self.site_knowledge_quota_warning_ratio <= 1:
            raise ValueError("site_knowledge_quota_warning_ratio must be between 0 and 1")
        if self.site_knowledge_zilliz_timeout_seconds <= 0:
            raise ValueError("site_knowledge_zilliz_timeout_seconds must be greater than 0")
        web_search_provider = str(self.web_search_provider or "disabled").strip().lower()
        allowed_web_search_providers = {
            "disabled",
            "auto",
            "tavily",
            "bocha",
            "apify",
            "zhihu",
        }
        if web_search_provider not in allowed_web_search_providers:
            raise ValueError(
                "web_search_provider must be disabled, auto, tavily, bocha, apify, or zhihu"
            )
        self.web_search_provider = web_search_provider
        if self.web_search_tavily_timeout_seconds <= 0:
            raise ValueError("web_search_tavily_timeout_seconds must be greater than 0")
        if self.web_search_tavily_cost_per_query < 0:
            raise ValueError("web_search_tavily_cost_per_query must be zero or greater")
        if self.web_search_bocha_timeout_seconds <= 0:
            raise ValueError("web_search_bocha_timeout_seconds must be greater than 0")
        if self.web_search_bocha_cost_per_query < 0:
            raise ValueError("web_search_bocha_cost_per_query must be zero or greater")
        if self.web_search_jina_reader_timeout_seconds <= 0:
            raise ValueError("web_search_jina_reader_timeout_seconds must be greater than 0")
        if self.web_search_jina_reader_max_pages <= 0:
            raise ValueError("web_search_jina_reader_max_pages must be greater than 0")
        if self.web_search_jina_reader_cost_per_page < 0:
            raise ValueError("web_search_jina_reader_cost_per_page must be zero or greater")
        if self.web_search_apify_timeout_seconds <= 0:
            raise ValueError("web_search_apify_timeout_seconds must be greater than 0")
        if self.web_search_apify_cost_per_query < 0:
            raise ValueError("web_search_apify_cost_per_query must be zero or greater")
        if self.web_search_zhihu_timeout_seconds <= 0:
            raise ValueError("web_search_zhihu_timeout_seconds must be greater than 0")
        if self.web_search_zhihu_cost_per_query < 0:
            raise ValueError("web_search_zhihu_cost_per_query must be zero or greater")
        if self.web_search_zhihu_hot_list_cache_ttl_seconds <= 0:
            raise ValueError("web_search_zhihu_hot_list_cache_ttl_seconds must be greater than 0")
        for zhihu_path_name in (
            "web_search_zhihu_search_path",
            "web_search_zhihu_global_search_path",
            "web_search_zhihu_hot_list_path",
            "web_search_zhihu_direct_answer_path",
        ):
            zhihu_path_value = str(getattr(self, zhihu_path_name) or "").strip()
            if zhihu_path_value and not zhihu_path_value.startswith("/"):
                raise ValueError(f"{zhihu_path_name} must be empty or start with /")
        if web_search_provider == "tavily":
            if not str(self.web_search_tavily_base_url or "").strip():
                raise ValueError(
                    "web_search_tavily_base_url is required when web_search_provider=tavily"
                )
            if (
                not str(self.web_search_tavily_api_key or "").strip()
                and not str(self.web_search_tavily_api_keys or "").strip()
            ):
                raise ValueError(
                    "web_search_tavily_api_key or web_search_tavily_api_keys is required "
                    "when web_search_provider=tavily"
                )
        if web_search_provider == "bocha":
            if not str(self.web_search_bocha_base_url or "").strip():
                raise ValueError(
                    "web_search_bocha_base_url is required when web_search_provider=bocha"
                )
            if not str(self.web_search_bocha_api_key or "").strip():
                raise ValueError(
                    "web_search_bocha_api_key is required when web_search_provider=bocha"
                )
        if web_search_provider == "apify":
            if not str(self.web_search_apify_base_url or "").strip():
                raise ValueError(
                    "web_search_apify_base_url is required when web_search_provider=apify"
                )
            if not str(self.web_search_apify_api_token or "").strip():
                raise ValueError(
                    "web_search_apify_api_token is required when web_search_provider=apify"
                )
            if not str(self.web_search_apify_actor_id or "").strip():
                raise ValueError(
                    "web_search_apify_actor_id is required when web_search_provider=apify"
                )
        if web_search_provider == "zhihu":
            if not str(self.web_search_zhihu_base_url or "").strip():
                raise ValueError(
                    "web_search_zhihu_base_url is required when web_search_provider=zhihu"
                )
            if not str(self.web_search_zhihu_access_secret or "").strip():
                raise ValueError(
                    "web_search_zhihu_access_secret is required when web_search_provider=zhihu"
                )
        image_source_provider = str(self.image_source_provider or "disabled").strip().lower()
        if image_source_provider not in {"disabled", "auto", "unsplash", "pixabay", "pexels"}:
            raise ValueError(
                "image_source_provider must be disabled, auto, unsplash, pixabay, or pexels"
            )
        self.image_source_provider = image_source_provider
        image_source_auto_strategy = (
            str(self.image_source_auto_strategy or "fast_first").strip().lower()
        )
        if image_source_auto_strategy not in {
            "first_available",
            "random",
            "parallel",
            "fast_first",
        }:
            raise ValueError(
                "image_source_auto_strategy must be first_available, random, "
                "parallel, or fast_first"
            )
        self.image_source_auto_strategy = image_source_auto_strategy
        if self.image_source_timeout_seconds <= 0:
            raise ValueError("image_source_timeout_seconds must be greater than 0")
        if self.image_source_cost_per_query < 0:
            raise ValueError("image_source_cost_per_query must be zero or greater")
        if (
            image_source_provider == "unsplash"
            and not str(self.image_source_unsplash_access_key or "").strip()
        ):
            raise ValueError(
                "image_source_unsplash_access_key is required when image_source_provider=unsplash"
            )
        if (
            image_source_provider == "pixabay"
            and not str(self.image_source_pixabay_api_key or "").strip()
        ):
            raise ValueError(
                "image_source_pixabay_api_key is required when image_source_provider=pixabay"
            )
        if (
            image_source_provider == "pexels"
            and not str(self.image_source_pexels_api_key or "").strip()
        ):
            raise ValueError(
                "image_source_pexels_api_key is required when image_source_provider=pexels"
            )
        if image_source_provider == "auto":
            has_image_source_key = any(
                str(value or "").strip()
                for value in (
                    self.image_source_unsplash_access_key,
                    self.image_source_pixabay_api_key,
                    self.image_source_pexels_api_key,
                )
            )
            if not has_image_source_key:
                raise ValueError(
                    "at least one image source provider key is required when "
                    "image_source_provider=auto"
                )
        site_knowledge_embedding_provider = str(
            self.site_knowledge_embedding_provider or ""
        ).strip()
        allowed_site_knowledge_embedding_providers = {
            "deterministic",
            "openai",
            "siliconflow",
            "tei",
        }
        if site_knowledge_embedding_provider not in allowed_site_knowledge_embedding_providers:
            raise ValueError(
                "site_knowledge_embedding_provider must be deterministic, "
                "openai, siliconflow, or tei"
            )
        site_knowledge_backend = str(self.site_knowledge_vector_backend or "").strip()
        if site_knowledge_backend not in {"postgres_json", "zilliz_cloud"}:
            raise ValueError("site_knowledge_vector_backend must be postgres_json or zilliz_cloud")
        metric_type = str(self.site_knowledge_vector_metric_type or "").strip().upper()
        if metric_type not in {"COSINE", "IP", "L2"}:
            raise ValueError("site_knowledge_vector_metric_type must be COSINE, IP, or L2")
        self.site_knowledge_vector_metric_type = metric_type
        site_knowledge_rerank_provider = (
            str(self.site_knowledge_rerank_provider or "disabled").strip().lower()
        )
        if site_knowledge_rerank_provider not in {"disabled", "jina"}:
            raise ValueError("site_knowledge_rerank_provider must be disabled or jina")
        self.site_knowledge_rerank_provider = site_knowledge_rerank_provider
        if self.site_knowledge_rerank_top_k <= 0:
            raise ValueError("site_knowledge_rerank_top_k must be greater than 0")
        if self.site_knowledge_rerank_timeout_seconds <= 0:
            raise ValueError("site_knowledge_rerank_timeout_seconds must be greater than 0")
        if site_knowledge_rerank_provider == "jina":
            if not str(self.site_knowledge_jina_base_url or "").strip():
                raise ValueError(
                    "site_knowledge_jina_base_url is required when Jina rerank is enabled"
                )
            if not str(self.site_knowledge_jina_api_key or "").strip():
                raise ValueError(
                    "site_knowledge_jina_api_key is required when Jina rerank is enabled"
                )
            if not str(self.site_knowledge_jina_rerank_model or "").strip():
                raise ValueError(
                    "site_knowledge_jina_rerank_model is required when Jina rerank is enabled"
                )
        if site_knowledge_backend == "zilliz_cloud":
            if not str(self.site_knowledge_zilliz_uri or "").strip():
                raise ValueError(
                    "site_knowledge_zilliz_uri is required when zilliz_cloud is enabled"
                )
            if not str(self.site_knowledge_zilliz_token or "").strip():
                raise ValueError(
                    "site_knowledge_zilliz_token is required when zilliz_cloud is enabled"
                )
            if not str(self.site_knowledge_zilliz_collection or "").strip():
                raise ValueError(
                    "site_knowledge_zilliz_collection is required when zilliz_cloud is enabled"
                )
        if site_knowledge_embedding_provider == "tei":
            if not self.tei_provider_enabled:
                raise ValueError(
                    "tei_provider_enabled is required when site knowledge uses tei embeddings"
                )
            model_id = str(self.site_knowledge_embedding_model or "").strip()
            configured_model_ids = {
                item.strip() for item in str(self.tei_model_ids or "").split(",") if item.strip()
            }
            configured_model_ids.update(f"tei/{item}" for item in list(configured_model_ids))
            if model_id not in configured_model_ids:
                raise ValueError("site_knowledge_embedding_model must be included in tei_model_ids")
        if site_knowledge_embedding_provider == "openai":
            if not str(self.openai_api_key or "").strip():
                raise ValueError(
                    "openai_api_key is required when site knowledge uses openai embeddings"
                )
        if site_knowledge_embedding_provider == "siliconflow":
            if not self.siliconflow_provider_enabled:
                raise ValueError(
                    "siliconflow_provider_enabled is required when site "
                    "knowledge uses siliconflow embeddings"
                )
            if not str(self.siliconflow_api_key or "").strip():
                raise ValueError(
                    "siliconflow_api_key is required when siliconflow_provider_enabled is true"
                )
        if self.openrouter_timeout_seconds <= 0:
            raise ValueError("openrouter_timeout_seconds must be greater than 0")
        if self.siliconflow_timeout_seconds <= 0:
            raise ValueError("siliconflow_timeout_seconds must be greater than 0")
        if self.siliconflow_provider_enabled and not str(self.siliconflow_base_url or "").strip():
            raise ValueError(
                "siliconflow_base_url is required when siliconflow_provider_enabled is true"
            )
        if self.siliconflow_provider_enabled and not str(self.siliconflow_api_key or "").strip():
            raise ValueError(
                "siliconflow_api_key is required when siliconflow_provider_enabled is true"
            )
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
