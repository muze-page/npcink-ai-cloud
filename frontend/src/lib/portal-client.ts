/**
 * Npcink AI Cloud Portal API Client
 *
 * 对接后端 Portal API (/portal/v1/*)
 * 支持邮箱验证码认证、Session 管理、API Key 管理等
 */

import { getPortalApiBaseUrl } from './env';
import { generateIdempotencyKey } from './idempotency';

export type ProductIdentityType = 'platform_admin' | 'site_admin';

// ============================================
// 类型定义
// ============================================

export interface PortalSession {
  principal_id?: string;
  email?: string;
  site_admin_ref: string;
  site_id: string;
  account_id?: string;
  identity_type?: ProductIdentityType;
  allowed_actions?: string[];
  role?: string;
  accounts?: Array<{
    account_id: string;
    name: string;
    status: string;
    site_admin_ref: string;
    role: string;
    site_count: number;
    sites: Site[];
  }>;
  auth_mode?: string;
  sites: Site[];
  current_subscription?: {
    status: 'active' | 'canceled' | 'expired' | 'trialing';
    subscription_id?: string;
    plan_id: string;
    plan_version_id?: string;
    tier_id?: string;
    plan_kind?: string;
    package_alias?: string;
    current_period_start: string;
    current_period_end: string;
    metadata?: Record<string, unknown>;
  };
  entitlements?: {
    requests_limit: number;
    tokens_limit: number;
    features: string[];
  };
}

export interface PortalSiteAdminSummary {
  site_admin_ref: string;
  email: string;
  auth_mode: string;
  identity_type?: ProductIdentityType;
  allowed_actions?: string[];
  roles: ProductIdentityType[];
  accessible_sites_count: number;
  selected_site_id: string;
  grants: Array<{
    account_id: string;
    identity_type?: ProductIdentityType;
    allowed_actions?: string[];
    role: string;
    site_count: number;
  }>;
}

export interface Site {
  site_id: string;
  site_name: string;
  account_id: string;
  status: 'active' | 'suspended' | 'inactive' | 'provisioning' | 'archived';
  created_at: string;
  plan_name?: string;
  wordpress_url?: string;
  metadata?: Record<string, unknown>;
}

export interface ApiKey {
  key_id: string;
  site_id: string;
  label: string;
  scopes: string[];
  status: 'active' | 'revoked' | 'expired';
  created_at: string;
  expires_at?: string;
  last_used_at?: string;
  metadata?: Record<string, unknown>;
}

export interface ApiKeyWithSecret extends ApiKey {
  secret?: string;
  cloud_api_key?: string;
}

export interface RotateKeyResponse {
  previous: ApiKey;
  current: ApiKeyWithSecret;
}

export interface PortalLoginCodeRequest {
  email: string;
  locale?: 'en' | 'zh-CN';
}

export interface PortalLoginCodeVerifyRequest {
  email: string;
  code: string;
  remember_me?: boolean;
}

export interface PortalEmailChangeCodeRequest {
  new_email: string;
  locale?: 'en' | 'zh-CN';
}

export interface PortalEmailChangeVerifyRequest {
  new_email: string;
  code: string;
}

export interface PortalEmailChangeCodeResponse {
  old_email: string;
  new_email: string;
  delivery: 'email' | 'development_code';
  expires_in_seconds: number;
  code: string;
}

export interface PortalEmailChangeResult extends PortalSession {
  old_email: string;
  new_email: string;
}

export interface PortalRegistrationCodeRequest {
  email: string;
  site_url?: string;
  site_name?: string;
  use_case?: string;
  locale?: 'en' | 'zh-CN';
}

export interface PortalRegistrationVerifyRequest {
  email: string;
  code: string;
}

export interface PortalRegistrationResult {
  status: 'registered' | 'existing_user';
  email: string;
  principal_id: string;
  account_id?: string;
  site_id?: string;
  site?: Site;
  subscription?: PortalSession['current_subscription'];
  next?: Record<string, string>;
}

export interface PortalIdentityProviderBinding {
  binding_id: string;
  provider: string;
  principal_id: string;
  identity_type: ProductIdentityType | 'user';
  role: string;
  status: string;
  has_unionid: boolean;
  last_login_at: string;
}

export interface PortalIdentityProviderStatus {
  provider: string;
  display_name: string;
  configured: boolean;
  bound: boolean;
  binding?: PortalIdentityProviderBinding | null;
  bind_start_path?: string;
}

export interface PortalIdentityProvidersResponse {
  principal_id: string;
  providers: PortalIdentityProviderStatus[];
}

export interface PortalQqStartResponse {
  provider: 'qq';
  authorization_url: string;
  state: string;
  expires_in_seconds: number;
  return_to: string;
  intent?: 'login' | 'bind';
}

export interface CreateSiteRequest {
  account_id: string;
  site_name?: string;
  wordpress_url: string;
}

export interface CreateAddonConnectionRequest {
  account_id: string;
  site_name?: string;
  wordpress_url: string;
  return_url: string;
  state: string;
}

export interface AddonConnectionResult {
  site_id: string;
  key_id: string;
  site_created: boolean;
  redirect_url: string;
  return_url: string;
  expires_at: string;
  expires_in_seconds: number;
}

export interface CreateKeyRequest {
  label?: string;
  scopes?: string[];
  expires_at?: string;
  metadata?: Record<string, unknown>;
}

export interface RotateKeyRequest {
  label?: string;
  scopes?: string[];
  expires_at?: string;
  metadata?: Record<string, unknown>;
}

export interface UsageSummary {
  site_id: string;
  period_start_at: string;
  period_end_at: string;
  requests_total: number;
  requests_limit: number;
  tokens_total: number;
  tokens_limit: number;
  cost_estimate: number;
  by_model: Array<{
    model_id: string;
    requests: number;
    tokens: number;
  }>;
  by_day: Array<{
    date: string;
    requests: number;
    tokens: number;
  }>;
}

export interface Entitlements {
  site_id: string;
  account_id: string;
  site_admin_ref: string;
  identity_type?: ProductIdentityType;
  allowed_actions?: string[];
  role: string;
  site: {
    site_id: string;
    site_name: string;
    status: string;
  };
  subscription: {
    status: string;
    plan_id: string;
    plan_version_id?: string;
    current_period_start?: string;
    current_period_end?: string;
    current_period_start_at?: string;
    current_period_end_at?: string;
  };
  plan_version: {
    plan_id: string;
    plan_version_id?: string;
    version?: number;
    name?: string;
    version_label?: string;
    status?: string;
    budgets?: {
      max_ai_credits_per_period?: number;
      max_runs_per_period?: number;
      max_tokens_per_period?: number;
      max_cost_per_period?: number;
    };
  };
  entitlement_snapshot: {
    requests_limit?: number;
    tokens_limit?: number;
    features?: string[];
    budgets?: {
      max_ai_credits_per_period?: number;
      max_runs_per_period?: number;
      max_tokens_per_period?: number;
      max_cost_per_period?: number;
    };
    entitlements?: Record<string, string[]>;
    policy?: Record<string, unknown>;
  };
  policy: Record<string, unknown>;
  period_start_at: string;
  period_end_at: string;
  usage_totals: {
    runs?: number;
    requests?: number;
    provider_calls?: number;
    tokens?: number;
    tokens_total?: number;
    cost?: number;
  };
  subscription_grace: {
    active?: boolean;
    subscription_status?: string;
    grace_period_days?: number;
    grace_until_at?: string;
    runtime_policy_overrides?: Record<string, unknown>;
  };
  budget_state: Record<
    string,
    {
      current_total?: number;
      limit?: number;
      grace_requests?: number;
      used_grace_requests?: number;
      remaining_grace_requests?: number;
      downgrade_policy?: Record<string, unknown>;
      over_limit?: boolean;
    }
  >;
  quota_summary?: {
    status?: string;
    generated_at?: string;
    period_start_at?: string;
    period_end_at?: string;
    credit?: {
      key?: string;
      used?: number;
      limit?: number;
      remaining?: number;
      unlimited?: boolean;
      usage_ratio?: number;
      status?: string;
      unit?: string;
      estimated?: boolean;
      rate_version?: string;
      source?: string;
    };
    credit_policy?: {
      rate_version?: string;
      period_policy?: string;
      renewal_policy?: string;
      topup_policy?: string;
    };
    resource_limits?: Array<{
      key?: string;
      used?: number;
      limit?: number;
      remaining?: number;
      unlimited?: boolean;
      usage_ratio?: number;
      status?: string;
      unit?: string;
    }>;
    breakdown?: Array<{
      key?: string;
      label?: string;
      quantity?: number;
      unit?: string;
      credits?: number;
    }>;
  };
  generated_at: string;
}

export interface PortalSiteSummaryRecord {
  site_id: string;
  account_id: string;
  site_admin_ref: string;
  identity_type?: ProductIdentityType;
  allowed_actions?: string[];
  role: string;
  site: Site;
  covered_by_subscription_id?: string;
  subscription_status?: string;
  package_alias?: string;
  coverage?: {
    subscription_id?: string;
    status?: string;
    plan_id?: string;
    plan_version_id?: string;
    package_alias?: string;
    current_period_start?: string;
    current_period_end?: string;
    current_period_start_at?: string;
    current_period_end_at?: string;
    metadata?: Record<string, unknown>;
  };
  entitlement_snapshot?: {
    budgets?: {
      max_ai_credits_per_period?: number;
      max_runs_per_period?: number;
      max_tokens_per_period?: number;
      max_cost_per_period?: number;
    };
    entitlements?: Record<string, string[]>;
    requests_limit?: number;
    tokens_limit?: number;
    features?: string[];
  };
}

export interface PortalUsageWindow {
  start_at: string;
  end_at: string;
  runs_total: number;
  provider_calls_total: number;
  tokens_in_total: number;
  tokens_out_total: number;
  cost_total: number;
  success_rate: number;
  avg_latency_ms: number;
}

export interface PortalUsageSummaryPayload {
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  role?: string;
  timezone?: string;
  generated_at?: string;
  windows?: {
    today?: PortalUsageWindow;
    rolling_24h?: PortalUsageWindow;
  };
}

export interface PortalPluginObservabilityTotals {
  events_total: number;
  ok_total: number;
  error_total: number;
  success_rate: number;
  avg_latency_ms: number;
  last_seen_at: string;
}

export interface PortalPluginObservabilityEventKind {
  event_kind: string;
  events_total: number;
  error_total: number;
  success_rate: number;
  avg_latency_ms: number;
  last_seen_at: string;
}

export interface PortalPluginObservabilityPlugin {
  plugin_slug: string;
  events_total: number;
  ok_total: number;
  error_total: number;
  success_rate: number;
  avg_latency_ms: number;
  last_seen_at: string;
  event_kinds: PortalPluginObservabilityEventKind[];
}

export interface PortalPluginObservabilityError {
  plugin_slug: string;
  event_kind: string;
  error_code: string;
  count: number;
  last_seen_at: string;
}

export interface PortalPluginObservabilityRecentError {
  plugin_slug: string;
  event_kind: string;
  error_code: string;
  status: string;
  ability_id: string;
  proposal_id: string;
  route: string;
  received_at: string;
}

export interface PortalPluginObservabilityTimelinePoint {
  bucket_start_at: string;
  bucket_end_at: string;
  bucket_hours: number;
  events_total: number;
  ok_total: number;
  error_total: number;
  success_rate: number;
  avg_latency_ms: number;
}

export interface PortalPluginObservabilityHealth {
  status: string;
  score: number;
  summary: string;
  reasons: string[];
}

export interface PortalPluginObservabilityAttentionItem {
  attention_key: string;
  severity: string;
  code: string;
  title: string;
  detail: string;
  suggested_action: string;
  workflow_status?: string;
  state?: {
    muted_until?: string;
    operator_note?: string;
    updated_at?: string;
  };
  site_id?: string;
  plugin_slug?: string;
  event_kind?: string;
  error_code?: string;
}

export interface PortalPluginObservabilityAttentionWorkflow {
  active: number;
  acknowledged: number;
  muted: number;
  resolved: number;
  total: number;
  needs_attention: number;
}

export interface PortalPluginObservabilityDigest {
  period_label: string;
  window_hours: number;
  headline: string;
  bullets: string[];
  top_plugin_slug: string;
  top_error_code: string;
}

export interface PortalMonitoringOverviewQuotaMetric {
  used: number;
  limit: number;
  remaining: number;
  usage_ratio: number;
  over_limit: boolean;
}

export interface PortalMonitoringOverviewAction {
  code: string;
  severity: 'warning' | 'error';
  source: string;
  title: string;
  detail: string;
  suggested_action: string;
  sort_weight?: number;
}

export interface PortalMonitoringOverviewComponent {
  component: string;
  status: 'ok' | 'warning' | 'error' | 'inactive';
  score: number;
  summary: string;
}

export interface PortalMonitoringOverviewSummary {
  contract_version: string;
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  role?: string;
  generated_at: string;
  window: {
    hours: number;
    start_at: string;
    end_at: string;
  };
  health: {
    status: 'ok' | 'warning' | 'error' | 'inactive';
    score: number;
    summary: string;
    components_count: number;
  };
  action_required: PortalMonitoringOverviewAction[];
  quota: {
    period_start_at: string;
    period_end_at: string;
    runs: PortalMonitoringOverviewQuotaMetric;
    tokens: PortalMonitoringOverviewQuotaMetric;
    cost: PortalMonitoringOverviewQuotaMetric;
    top_pressure: 'runs' | 'tokens' | 'cost' | 'none';
    summary: string;
  };
  activity: {
    last_seen_at: string;
    plugin_events_total: number;
    plugin_errors_total: number;
    media_jobs_total: number;
    media_failed_total: number;
    vector_searches_total: number;
    vector_no_hit_total: number;
    runtime_runs_total: number;
    runtime_success_rate: number;
    runtime_p95_latency_ms: number;
  };
  components: PortalMonitoringOverviewComponent[];
}

export interface PortalDiagnosticAdvisorEvidence {
  kind: string;
  ref: string;
  label: string;
}

export interface PortalDiagnosticAdvisorAction {
  action: string;
  requires_operator: boolean;
}

export interface PortalDiagnosticAdvisorSafety {
  write_posture: string;
  direct_wordpress_write: boolean;
  operator_review_required: boolean;
  automatic_repair_allowed: boolean;
  raw_payload_exposed: boolean;
}

export interface PortalDiagnosticEvidenceWindow {
  hours: number;
  start_at: string;
  end_at: string;
}

export interface PortalDiagnosticStatusDetail {
  workflow_status: string;
  status_source: string;
  allowed_statuses: string[];
  muted_until: string;
  operator_note: string;
  updated_at: string;
}

export interface PortalDiagnosticWorkflowSummary {
  new: number;
  acknowledged: number;
  muted: number;
  resolved: number;
  total: number;
  needs_attention: number;
  allowed_statuses: string[];
}

export interface PortalDiagnosticItem {
  diagnostic_key: string;
  code: string;
  severity: 'warning' | 'error' | 'info' | string;
  source: string;
  title: string;
  evidence_summary: string;
  likely_cause: string;
  next_step: string;
  recommended_action_id: string;
  workflow_status: 'new' | 'acknowledged' | 'muted' | 'resolved' | string;
  status_detail: PortalDiagnosticStatusDetail;
  evidence_window: PortalDiagnosticEvidenceWindow;
  last_updated_at: string;
  operator_review_required: boolean;
  direct_wordpress_write: boolean;
}

export interface PortalDiagnosticAdvisorSummary {
  advisor_version: string;
  scope: 'site_diagnostics' | string;
  status: string;
  severity: string;
  headline: string;
  summary: string;
  evidence: PortalDiagnosticAdvisorEvidence[];
  recommended_actions: PortalDiagnosticAdvisorAction[];
  confidence: string;
  filters: {
    site_id?: string;
    window_hours?: number;
    [key: string]: unknown;
  };
  signals: Array<Record<string, unknown>>;
  diagnostic_items: PortalDiagnosticItem[];
  diagnostic_workflow?: PortalDiagnosticWorkflowSummary;
  evidence_window?: PortalDiagnosticEvidenceWindow;
  safety: PortalDiagnosticAdvisorSafety;
  generated_at: string;
  site_id?: string;
  account_id?: string;
  site_admin_ref?: string;
  identity_type?: ProductIdentityType;
  allowed_actions?: string[];
  role?: string;
}

export interface PortalPluginObservabilitySummary {
  contract_version: string;
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  role?: string;
  generated_at: string;
  window: {
    hours: number;
    start_at: string;
    end_at: string;
  };
  totals: PortalPluginObservabilityTotals;
  health: PortalPluginObservabilityHealth;
  attention: PortalPluginObservabilityAttentionItem[];
  attention_workflow?: PortalPluginObservabilityAttentionWorkflow;
  digest?: PortalPluginObservabilityDigest;
  plugins: PortalPluginObservabilityPlugin[];
  timeline: PortalPluginObservabilityTimelinePoint[];
  errors: PortalPluginObservabilityError[];
  recent_errors: PortalPluginObservabilityRecentError[];
}

export interface PortalMediaObservabilityTotals {
  jobs_total: number;
  succeeded_total: number;
  failed_total: number;
  success_rate: number;
  avg_processing_duration_ms: number;
  p95_processing_duration_ms: number;
  avg_queue_wait_ms: number;
  source_bytes_total: number;
  output_bytes_total: number;
  bytes_saved_total: number;
  compression_ratio: number;
  artifact_download_count: number;
  last_finished_at: string;
  active_site_count: number;
  active_account_count: number;
  watermark_job_count: number;
  active_artifact_count: number;
  active_artifact_bytes: number;
}

export interface PortalMediaObservabilityHealth {
  status: string;
  score: number;
  summary: string;
}

export interface PortalMediaObservabilityTimelinePoint {
  bucket_start_at: string;
  jobs_total: number;
  failed_total: number;
  bytes_saved_total: number;
}

export interface PortalMediaObservabilityFormat {
  target_format: string;
  jobs_total: number;
  succeeded_total: number;
  failed_total: number;
  success_rate: number;
  source_bytes_total: number;
  output_bytes_total: number;
  bytes_saved_total: number;
  compression_ratio: number;
  avg_processing_duration_ms: number;
}

export interface PortalMediaObservabilityError {
  error_code: string;
  count: number;
  last_seen_at: string;
}

export interface PortalMediaObservabilityRecentFailure {
  run_id: string;
  site_id: string;
  target_format: string;
  error_code: string;
  source_bytes: number;
  queue_wait_ms: number;
  processing_duration_ms: number;
  finished_at: string;
}

export interface PortalWorkflowMetadata {
  workflow_id: string;
  workflow_version: string;
  title: string;
  summary: string;
  ability_name: string;
  contract: string;
  owner: string;
  handoff_owner: string;
  execution_pattern: string;
  storage_mode: string;
  badges: Array<{ label: string; status: string }>;
  steps: string[];
  stop_conditions: string[];
  direct_wordpress_write: boolean;
  requires_operator_review: boolean;
  fail_closed_behavior: string;
}

export interface PortalMediaObservabilitySummary {
  contract_version: string;
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  role?: string;
  generated_at: string;
  window: {
    hours: number;
    start_at: string;
    end_at: string;
  };
  totals: PortalMediaObservabilityTotals;
  health: PortalMediaObservabilityHealth;
  timeline: PortalMediaObservabilityTimelinePoint[];
  formats: PortalMediaObservabilityFormat[];
  errors: PortalMediaObservabilityError[];
  recent_failures: PortalMediaObservabilityRecentFailure[];
  workflow_metadata: PortalWorkflowMetadata;
}

export interface PortalVectorObservabilityTotals {
  index_jobs_total: number;
  index_succeeded_total: number;
  index_failed_total: number;
  index_success_rate: number;
  accepted_documents_total: number;
  indexed_documents_total: number;
  indexed_chunks_total: number;
  failed_documents_total: number;
  deleted_entries_total: number;
  avg_index_duration_ms: number;
  p95_index_duration_ms: number;
  last_index_job_finished_at: string;
  search_queries_total: number;
  search_succeeded_total: number;
  search_failed_total: number;
  search_success_rate: number;
  no_hit_total: number;
  no_hit_rate: number;
  avg_search_latency_ms: number;
  p95_search_latency_ms: number;
  avg_top1_score: number;
  avg_result_score: number;
  last_search_finished_at: string;
  active_site_count: number;
  indexed_site_count: number;
  current_document_count: number;
  current_chunk_count: number;
}

export interface PortalVectorObservabilityHealth {
  status: string;
  score: number;
  summary: string;
}

export interface PortalVectorObservabilityTimelinePoint {
  bucket_start_at: string;
  index_jobs_total: number;
  indexed_chunks_total: number;
  search_queries_total: number;
  no_hit_total: number;
  failed_total: number;
}

export interface PortalVectorObservabilityIntent {
  intent: string;
  queries_total: number;
  no_hit_total: number;
  no_hit_rate: number;
  avg_top1_score: number;
  avg_latency_ms: number;
}

export interface PortalVectorObservabilitySnapshot {
  site_id: string;
  document_count: number;
  chunk_count: number;
  post_type_counts: Record<string, number>;
  source_type_counts: Record<string, number>;
  last_indexed_at: string;
  embedding_provider: string;
  embedding_model: string;
  embedding_dimensions: number;
  vector_backend: string;
  captured_at: string;
}

export interface PortalVectorObservabilityError {
  error_code: string;
  count: number;
  last_seen_at: string;
}

export interface PortalVectorObservabilitySummary {
  contract_version: string;
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  role?: string;
  generated_at: string;
  window: {
    hours: number;
    start_at: string;
    end_at: string;
  };
  totals: PortalVectorObservabilityTotals;
  health: PortalVectorObservabilityHealth;
  timeline: PortalVectorObservabilityTimelinePoint[];
  intents: PortalVectorObservabilityIntent[];
  index_snapshots: PortalVectorObservabilitySnapshot[];
  errors: PortalVectorObservabilityError[];
}

export interface PortalAIInsightDisclosure {
  version: string;
  content_origin: string;
  generated_by_ai: boolean;
  ai_assisted: boolean;
  visible_label_required: boolean;
  visible_label: string;
  brand_label: string;
  visible_notice: string;
  review_status: string;
  reviewed_at: string;
  source_generation_mode: string;
}

export interface PortalAIInsightGeneration {
  mode: string;
  error_code: string;
  cache_status: string;
  cache_hit: boolean;
  cache_generated_at: string;
  cache_expires_at: string;
}

export interface PortalAIInsightAgentHandoff {
  agent_id: string;
  agent_version: string;
  agent_role: string;
  handoff_type: string;
  handoff_owner: string;
  requires_operator_review: boolean;
  direct_wordpress_write: boolean;
  execution_pattern: string;
  storage_mode: string;
  allowed_actions: string[];
  stop_conditions: string[];
  forbidden_actions: string[];
  fail_closed_behavior: string;
}

export interface PortalAIInsightAnalysis {
  summary_version: string;
  scope: string;
  status: string;
  severity: string;
  headline: string;
  operator_summary: string;
  operator_next_step: string;
  safety_note: string;
  generated_at: string;
  generation: PortalAIInsightGeneration;
  ai_disclosure: PortalAIInsightDisclosure;
  agent_handoff: PortalAIInsightAgentHandoff;
  agent_metadata_projection: PortalAIInsightAgentHandoff;
}

export interface PortalAIInsightHistoryItem {
  site_id: string;
  scope: string;
  status: string;
  severity: string;
  headline: string;
  operator_summary: string;
  operator_next_step: string;
  generated_at: string;
  fresh_until: string;
  is_stale: boolean;
  generation: PortalAIInsightGeneration;
  ai_disclosure: PortalAIInsightDisclosure;
  agent_handoff: PortalAIInsightAgentHandoff;
  agent_metadata_projection: PortalAIInsightAgentHandoff;
}

export interface PortalAIInsightSafety {
  manual_trigger_required: boolean;
  prompt_saved: boolean;
  raw_payload_saved: boolean;
  wordpress_write_allowed: boolean;
  provider_visible: boolean;
  model_visible: boolean;
  token_usage_visible: boolean;
  cost_visible: boolean;
  cache_key_visible: boolean;
  customer_article_generation_allowed: boolean;
}

export interface PortalAIInsightResponse {
  portal_ai_insight_version: string;
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  identity_type?: ProductIdentityType;
  role?: string;
  analysis: PortalAIInsightAnalysis;
  safety: PortalAIInsightSafety;
}

export interface PortalAIInsightHistoryResponse {
  portal_ai_insight_version: string;
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  identity_type?: ProductIdentityType;
  role?: string;
  items: PortalAIInsightHistoryItem[];
  safety: PortalAIInsightSafety;
}

export interface PortalAuditEvent {
  event_id: string;
  event_kind: string;
  outcome: string;
  message: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface PortalAuditSummary {
  site_id?: string;
  account_id?: string;
  site_admin_ref?: string;
  role?: string;
  generated_at?: string;
  totals?: {
    events?: number;
    succeeded?: number;
    error?: number;
  };
  groups?: Array<{
    event_kind: string;
    outcome: string;
    count: number;
    first_seen_at?: string;
    last_seen_at?: string;
  }>;
}

export interface PortalAuditEventList {
  site_id?: string;
  account_id?: string;
  site_admin_ref?: string;
  role?: string;
  items: PortalAuditEvent[];
}

export interface PortalBillingSnapshot {
  snapshot_id: string;
  period_start_at: string;
  period_end_at: string;
  generated_at: string;
  currency?: string;
  plan_version_id?: string;
  totals?: {
    runs: number;
    provider_calls: number;
    tokens_in?: number;
    tokens_out?: number;
    tokens_total?: number;
    cost: number;
  };
}

export interface PortalBillingReconciliation {
  site_id?: string;
  account_id?: string;
  site_admin_ref?: string;
  role?: string;
  ledger_totals?: {
    cost?: number;
    provider_calls?: number;
    runs?: number;
    tokens_total?: number;
  };
  snapshot?: PortalBillingSnapshot | null;
  reconciliation?: {
    in_sync?: boolean;
    deltas?: {
      cost?: number;
      provider_calls?: number;
      runs?: number;
      tokens_total?: number;
    };
  };
}

export interface PortalSiteBundle {
  summary: PortalSiteSummaryRecord;
  apiKeys: ApiKey[];
}

export interface PortalAnalyticsTrend {
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  identity_type?: string;
  role?: string;
  tier_id?: string;
  allowed_ranges?: string[];
  selected_range?: string;
  granularity?: string;
  start_at?: string;
  end_at?: string;
  rows: Array<{
    bucket_gmt: string;
    ability_id: string;
    caller_id: string;
    request_total: number;
    success_total: number;
    guard_fail_total: number;
    avg_latency_ms: number;
  }>;
}

export interface PortalAnalyticsCostBreakdown {
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  identity_type?: string;
  role?: string;
  tier_id?: string;
  allowed_ranges?: string[];
  selected_range?: string;
  group_by?: string;
  total_cost: number;
  breakdown: Array<{
    label: string;
    value: number;
    percentage: number;
  }>;
  generated_at?: string;
}

export interface PortalAnalyticsPerformance {
  site_id: string;
  account_id?: string;
  site_admin_ref?: string;
  identity_type?: string;
  role?: string;
  tier_id?: string;
  allowed_ranges?: string[];
  selected_range?: string;
  performance?: {
    latency: {
      p50_ms: number;
      p95_ms: number;
      p99_ms: number;
      avg_ms: number;
    };
    tool_latency: {
      p50_ms: number;
      p95_ms: number;
    };
    error_rate: number;
    timeout_rate: number;
    blocked_rate: number;
    canceled_rate: number;
    top_errors: Array<{
      error_code: string;
      count: number;
      percentage: number;
    }>;
    status_distribution: {
      total: number;
      success: number;
      error: number;
      timeout: number;
      blocked: number;
      canceled: number;
    };
  };
  generated_at?: string;
}

function normalizePortalSiteSummaryRecord(raw: unknown): PortalSiteSummaryRecord {
  const record = (raw || {}) as Record<string, unknown>;
  const nestedCoverage = ((record.coverage || {}) as Record<string, unknown>);
  const nestedSubscription = ((nestedCoverage.subscription || {}) as Record<string, unknown>);
  const nestedPlanVersion = ((nestedCoverage.plan_version || {}) as Record<string, unknown>);
  const nestedEntitlementSnapshot = ((nestedCoverage.entitlement_snapshot || {}) as Record<string, unknown>);
  const subscriptionMetadata = ((nestedSubscription.metadata || {}) as Record<string, unknown>);

  return {
    site_id: String(record.site_id || ''),
    account_id: String(record.account_id || ''),
    site_admin_ref: String(record.site_admin_ref || ''),
    identity_type: (record.identity_type as ProductIdentityType | undefined) || undefined,
    allowed_actions: Array.isArray(record.allowed_actions)
      ? record.allowed_actions.map((action) => String(action))
      : undefined,
    role: String(record.role || ''),
    site: (record.site as Site) || {
      site_id: '',
      site_name: '',
      account_id: '',
      status: 'inactive',
      created_at: '',
    },
    package_alias:
      String(record.package_alias || '') ||
      String(subscriptionMetadata.package_alias || ''),
    covered_by_subscription_id: String(record.covered_by_subscription_id || nestedSubscription.subscription_id || ''),
    subscription_status: String(record.subscription_status || nestedSubscription.status || ''),
    coverage: {
      subscription_id: String(record.covered_by_subscription_id || nestedSubscription.subscription_id || ''),
      status: String(record.subscription_status || nestedSubscription.status || ''),
      plan_id: String(nestedSubscription.plan_id || ''),
      plan_version_id: String(nestedSubscription.plan_version_id || nestedPlanVersion.plan_version_id || ''),
      package_alias:
        String(subscriptionMetadata.package_alias || '') ||
        String(record.package_alias || ''),
      current_period_start: String(nestedSubscription.current_period_start || ''),
      current_period_end: String(nestedSubscription.current_period_end || ''),
      current_period_start_at: String(nestedSubscription.current_period_start_at || ''),
      current_period_end_at: String(nestedSubscription.current_period_end_at || ''),
      metadata:
        typeof nestedSubscription.metadata === 'object' && nestedSubscription.metadata !== null
          ? (nestedSubscription.metadata as Record<string, unknown>)
          : undefined,
    },
    entitlement_snapshot:
      typeof nestedEntitlementSnapshot === 'object' && Object.keys(nestedEntitlementSnapshot).length > 0
        ? (nestedEntitlementSnapshot as PortalSiteSummaryRecord['entitlement_snapshot'])
        : (record.entitlement_snapshot as PortalSiteSummaryRecord['entitlement_snapshot']),
  };
}

export interface ProvisionedSiteRecord {
  site_id: string;
  account_id: string;
  name: string;
  status: 'active' | 'suspended' | 'inactive' | 'provisioning';
  metadata?: Record<string, unknown>;
  provisioned_at?: string;
  activated_at?: string;
  suspended_at?: string;
  suspension_reason?: string;
  created_at: string;
  updated_at?: string;
}

export interface PortalProvisionedSite {
  account_id: string;
  site_admin_ref: string;
  role: string;
  wordpress_url: string;
  site: ProvisionedSiteRecord;
  current_subscription?: {
    subscription_id?: string;
    status: string;
    plan_id: string;
    plan_version_id?: string;
    tier_id?: string;
    plan_kind?: string;
    package_alias?: string;
  } | null;
  commercial_onboarding?: {
    auto_bound: boolean;
    tier_id: string;
    package_alias: string;
  } | null;
  next: {
    connection_path: string;
    sites_path: string;
  };
}

export interface PortalActivatedSite {
  site_id: string;
  account_id: string;
  site_admin_ref: string;
  role: string;
  site: ProvisionedSiteRecord;
}

export interface PortalUsageBundle {
  usage: PortalUsageSummaryPayload;
  entitlements: Entitlements;
  creditLedger: PortalCreditLedgerPayload;
  creditPacks: PortalCreditPackCatalogPayload;
  paymentOrders: PortalPaymentOrderListPayload;
}

export interface PortalCreditLedgerEntry {
  ledger_entry_id: string;
  site_id?: string;
  event_type?: string;
  source_type: string;
  category?: string;
  category_label?: string;
  feature_key?: string;
  feature_label?: string;
  feature_detail?: string;
  direction?: string;
  explanation?: string;
  source_id?: string;
  run_id?: string;
  credit_delta: number;
  consumed_credits: number;
  granted_credits?: number;
  net_credit_delta?: number;
  quantity: number;
  unit: string;
  rate?: number;
  rate_unit?: string;
  rate_version?: string;
  created_at?: string;
}

export interface PortalCreditPack {
  pack_id: string;
  label: string;
  ai_credits: number;
  amount: number;
  currency: string;
  recommended_for_tiers?: string[];
  active?: boolean;
  period_policy?: string;
  grant_event_type?: string;
  catalog_version?: string;
}

export interface PortalCreditPackCatalogPayload {
  site_id?: string;
  account_id?: string;
  catalog_version?: string;
  period_policy?: string;
  grant_event_type?: string;
  items: PortalCreditPack[];
}

export interface PortalCreditPackPaymentOrder {
  order_id: string;
  account_id: string;
  site_id?: string;
  subscription_id?: string;
  target_subscription_id?: string;
  provider: string;
  status: string;
  amount: number;
  currency: string;
  subject: string;
  checkout_url?: string;
  purchase_kind?: string;
  status_detail?: {
    code?: string;
    label?: string;
    detail?: string;
    next_action?: string;
    simulated_payment?: boolean;
  };
  credit_pack?: PortalCreditPack;
  created_at?: string;
  paid_at?: string;
  refunded_at?: string;
  metadata?: Record<string, unknown>;
}

export interface PortalCreditPackOrderPayload {
  site_id?: string;
  account_id?: string;
  order: PortalCreditPackPaymentOrder;
}

export type PortalPaymentOrder = PortalCreditPackPaymentOrder;

export interface PortalProTrialPayload {
  account_id: string;
  principal_id: string;
  subscription: NonNullable<PortalSession['current_subscription']>;
  entitlement_snapshot?: Record<string, unknown>;
  trial?: {
    available?: boolean;
    status?: string;
    tier_id?: string;
    trial_days?: number;
    trial_started_at?: string;
    trial_ends_at?: string;
    monthly_price_cny?: number;
  };
  session?: PortalSession;
}

export interface PortalProMonthlyOrderPayload {
  account_id: string;
  principal_id: string;
  order: PortalPaymentOrder;
}

export interface PortalPaymentOrderListPayload {
  site_id?: string;
  account_id?: string;
  generated_at?: string;
  pagination?: {
    limit?: number;
    offset?: number;
    total?: number;
    has_more?: boolean;
  };
  items: PortalPaymentOrder[];
}

export interface PortalCreditLedgerPayload {
  site_id: string;
  account_id: string;
  generated_at?: string;
  period_start_at?: string;
  period_end_at?: string;
  rate_version?: string;
  pagination?: {
    limit?: number;
    offset?: number;
    total?: number;
    has_more?: boolean;
  };
  summary?: {
    total_credits?: number;
    consumed_credits?: number;
    granted_credits?: number;
    adjustment_credits?: number;
    refund_credits?: number;
    net_credit_delta?: number;
    net_used_credits?: number;
    entry_count?: number;
    category_totals?: Record<
      string,
      {
        label?: string;
        net_credit_delta?: number;
      }
    >;
    breakdown?: Array<{
      key?: string;
      label?: string;
      quantity?: number;
      unit?: string;
      credits?: number;
    }>;
  };
  items: PortalCreditLedgerEntry[];
}

export interface PortalAuditBundle {
  summary: PortalAuditSummary;
  events: PortalAuditEvent[];
}

export interface PortalBillingBundle {
  snapshots: PortalBillingSnapshot[];
  reconciliation: PortalBillingReconciliation;
}

export interface PortalSiteDiagnostics {
  site_id: string;
  generated_at: string;
  site_status?: string;
  wordpress_url?: string;
  active_key_count?: number;
  latest_key_used_at?: string;
  latest_auth_failure_at?: string;
  subscription_status?: string;
  package_label?: string;
  checks?: Array<{
    key: string;
    status: 'ok' | 'warning' | 'error' | 'inactive' | 'pending' | string;
    title: string;
    detail: string;
    action?: string;
  }>;
}

export interface PortalEnvelope<T> {
  status: 'ok' | 'error';
  message: string;
  data: T;
  revision: string;
}

export interface PortalError {
  status: 'error';
  message: string;
  error_code: string;
  details?: Record<string, unknown>;
}

type PortalRequestOptions = {
  requireAuth?: boolean;
  headers?: HeadersInit;
};

// ============================================
// 错误类
// ============================================

export class PortalApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode: number,
    public readonly errorCode: string,
    public readonly details?: Record<string, unknown>
  ) {
    super(message);
    this.name = 'PortalApiError';
  }

  static fromResponse(status: number, body: PortalError): PortalApiError {
    return new PortalApiError(
      body.message || 'API request failed',
      status,
      body.error_code || 'unknown_error',
      body.details
    );
  }
}

// ============================================
// Portal API Client
// ============================================

export class PortalClient {
  private baseUrl?: string;
  private token?: string;

  constructor(baseUrl?: string, token?: string) {
    this.baseUrl = baseUrl;
    this.token = token;
  }

  /**
   * 设置认证 Token
   */
  setToken(token: string): void {
    this.token = token;
  }

  /**
   * 获取认证头
   */
  private getAuthHeaders(): HeadersInit {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
    };

    if (this.token) {
      (headers as Record<string, string>)['Authorization'] = `Bearer ${this.token}`;
    }

    return headers;
  }

  /**
   * 通用请求方法
   */
  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options: PortalRequestOptions = {}
  ): Promise<PortalEnvelope<T>> {
    const baseUrl = this.baseUrl || getPortalApiBaseUrl();
    const url = `${baseUrl}${path}`;
    const methodName = method.toUpperCase();
    const generatedIdempotencyKey =
      methodName !== 'GET' && methodName !== 'HEAD'
        ? generateIdempotencyKey(`portal_${methodName.toLowerCase()}`)
        : '';
    
    const response = await fetch(url, {
      method,
      headers: {
        ...this.getAuthHeaders(),
        ...(generatedIdempotencyKey ? { 'Idempotency-Key': generatedIdempotencyKey } : {}),
        ...(options.headers || {}),
        ...(options.requireAuth ? {} : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      credentials: 'include',
    });

    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json')
      ? await response.json()
      : {
          status: 'error',
          message: (await response.text()) || `HTTP ${response.status}`,
          error_code: 'proxy.non_json_response',
        };

    if (!response.ok) {
      throw PortalApiError.fromResponse(response.status, data as PortalError);
    }

    return data as PortalEnvelope<T>;
  }

  // ========================================
  // 邮箱验证码认证
  // ========================================

  /**
   * 请求邮箱验证码
   * POST /portal/v1/auth/code/request
   */
  async requestLoginCode(payload: PortalLoginCodeRequest): Promise<PortalEnvelope<{
    email: string;
    delivery: 'email';
    expires_in_seconds: number;
    code: string;
  }>> {
    return this.request('POST', '/auth/code/request', payload);
  }

  /**
   * 验证邮箱验证码
   * POST /portal/v1/auth/code/verify
   */
  async verifyLoginCode(payload: PortalLoginCodeVerifyRequest): Promise<PortalEnvelope<PortalSession>> {
    return this.request('POST', '/auth/code/verify', payload);
  }

  async requestEmailChangeCode(payload: PortalEmailChangeCodeRequest): Promise<PortalEnvelope<PortalEmailChangeCodeResponse>> {
    return this.request('POST', '/account/email-change/request', payload, { requireAuth: true });
  }

  async verifyEmailChangeCode(payload: PortalEmailChangeVerifyRequest): Promise<PortalEnvelope<PortalEmailChangeResult>> {
    return this.request('POST', '/account/email-change/verify', payload, { requireAuth: true });
  }

  /**
   * 请求注册验证码
   * POST /portal/v1/register/code/request
   */
  async requestRegistrationCode(payload: PortalRegistrationCodeRequest): Promise<PortalEnvelope<{
    email: string;
    delivery: 'email' | 'development_code';
    expires_in_seconds: number;
    code: string;
    site?: {
      site_id: string;
      site_name: string;
      wordpress_url: string;
    };
  }>> {
    return this.request('POST', '/register/code/request', payload);
  }

  /**
   * 验证注册验证码并创建 Free 账号
   * POST /portal/v1/register/verify
   */
  async verifyRegistration(payload: PortalRegistrationVerifyRequest): Promise<PortalEnvelope<PortalRegistrationResult>> {
    return this.request('POST', '/register/verify', payload);
  }

  /**
   * 获取当前账号的第三方登录绑定状态
   * GET /portal/v1/auth/identity-providers
   */
  async getIdentityProviders(): Promise<PortalEnvelope<PortalIdentityProvidersResponse>> {
    return this.request('GET', '/auth/identity-providers', undefined, { requireAuth: true });
  }

  /**
   * 发起 QQ 绑定授权
   * GET /portal/v1/auth/qq/start?intent=bind
   */
  async startQqBind(returnTo = '/portal/account'): Promise<PortalEnvelope<PortalQqStartResponse>> {
    const params = new URLSearchParams({ intent: 'bind', return_to: returnTo });
    return this.request('GET', `/auth/qq/start?${params.toString()}`, undefined, { requireAuth: true });
  }

  /**
   * 解绑 QQ 快捷登录
   * POST /portal/v1/auth/qq/unbind
   */
  async unbindQqLogin(): Promise<PortalEnvelope<{ provider: string; principal_id: string; revoked: number }>> {
    return this.request('POST', '/auth/qq/unbind', { provider: 'qq' }, { requireAuth: true });
  }

  // ========================================
  // Session 管理
  // ========================================

  /**
   * 获取当前 Session
   * GET /portal/v1/session
   */
  async getSession(): Promise<PortalEnvelope<PortalSession>> {
    return this.request('GET', '/session', undefined, { requireAuth: true });
  }

  /**
   * 选择站点
   * POST /portal/v1/session/site
   */
  async selectSite(siteId: string): Promise<PortalEnvelope<PortalSession>> {
    return this.request('POST', '/session/site', { site_id: siteId }, { requireAuth: true });
  }

  /**
   * 登出
   * POST /portal/v1/logout
   */
  async logout(): Promise<PortalEnvelope<Record<string, never>>> {
    return this.request('POST', '/logout');
  }

  /**
   * 吊销 Session
   * POST /portal/v1/session/revoke
   */
  async revokeSession(): Promise<PortalEnvelope<Record<string, never>>> {
    return this.request('POST', '/session/revoke');
  }

  // ========================================
  // 站点管理
  // ========================================

  /**
   * 获取站点列表
   * GET /portal/v1/sites
   */
  async listSites(): Promise<PortalEnvelope<{ items: Site[] }>> {
    return this.request('GET', '/sites', undefined, { requireAuth: true });
  }

  async createSite(payload: CreateSiteRequest): Promise<PortalEnvelope<PortalProvisionedSite>> {
    return this.request('POST', '/sites', payload, { requireAuth: true });
  }

  async createAddonConnection(payload: CreateAddonConnectionRequest): Promise<PortalEnvelope<AddonConnectionResult>> {
    return this.request('POST', '/addon-connections', payload, { requireAuth: true });
  }

  async activateSite(siteId: string): Promise<PortalEnvelope<PortalActivatedSite>> {
    return this.request('POST', `/sites/${siteId}/activate`, {}, { requireAuth: true });
  }

  async deactivateSite(siteId: string): Promise<PortalEnvelope<{ site: Site }>> {
    return this.request('POST', `/sites/${siteId}/deactivate`, {}, { requireAuth: true });
  }

  async removeSite(siteId: string): Promise<PortalEnvelope<{ site: Site; revoked_key_ids: string[] }>> {
    return this.request('POST', `/sites/${siteId}/remove`, {}, { requireAuth: true });
  }

  /**
   * 获取站点摘要
   * GET /portal/v1/sites/{siteId}/summary
   */
  async getSiteSummary(siteId: string): Promise<PortalEnvelope<PortalSiteSummaryRecord>> {
    const response = await this.request<PortalSiteSummaryRecord>('GET', `/sites/${siteId}/summary`, undefined, {
      requireAuth: true,
    });
    return {
      ...response,
      data: normalizePortalSiteSummaryRecord(response.data),
    };
  }

  /**
   * 获取使用情况摘要
   * GET /portal/v1/sites/{siteId}/usage-summary
   */
  async getUsageSummary(siteId: string): Promise<PortalEnvelope<PortalUsageSummaryPayload>> {
    return this.request('GET', `/sites/${siteId}/usage-summary`, undefined, { requireAuth: true });
  }

  async getMonitoringOverview(
    siteId: string,
    options?: {
      windowHours?: number;
    }
  ): Promise<PortalEnvelope<PortalMonitoringOverviewSummary>> {
    const params = new URLSearchParams();
    params.set('window_hours', String(options?.windowHours || 24));
    return this.request(
      'GET',
      `/sites/${siteId}/monitoring-overview?${params.toString()}`,
      undefined,
      { requireAuth: true }
    );
  }

  async getDiagnosticAdvisor(
    siteId: string,
    options?: {
      windowHours?: number;
    }
  ): Promise<PortalEnvelope<PortalDiagnosticAdvisorSummary>> {
    const params = new URLSearchParams();
    params.set('window_hours', String(options?.windowHours || 24));
    return this.request(
      'GET',
      `/sites/${siteId}/diagnostic-advisor?${params.toString()}`,
      undefined,
      { requireAuth: true }
    );
  }

  async getPluginObservability(
    siteId: string,
    options?: {
      windowHours?: number;
      pluginSlug?: string;
    }
  ): Promise<PortalEnvelope<PortalPluginObservabilitySummary>> {
    const params = new URLSearchParams();
    params.set('window_hours', String(options?.windowHours || 24));
    if (options?.pluginSlug) {
      params.set('plugin_slug', options.pluginSlug);
    }
    return this.request(
      'GET',
      `/sites/${siteId}/plugin-observability?${params.toString()}`,
      undefined,
      { requireAuth: true }
    );
  }

  async getMediaObservability(
    siteId: string,
    options?: {
      windowHours?: number;
      targetFormat?: string;
    }
  ): Promise<PortalEnvelope<PortalMediaObservabilitySummary>> {
    const params = new URLSearchParams();
    params.set('window_hours', String(options?.windowHours || 24));
    if (options?.targetFormat) {
      params.set('target_format', options.targetFormat);
    }
    return this.request(
      'GET',
      `/sites/${siteId}/media-observability?${params.toString()}`,
      undefined,
      { requireAuth: true }
    );
  }

  async getVectorObservability(
    siteId: string,
    options?: {
      windowHours?: number;
    }
  ): Promise<PortalEnvelope<PortalVectorObservabilitySummary>> {
    const params = new URLSearchParams();
    params.set('window_hours', String(options?.windowHours || 24));
    return this.request(
      'GET',
      `/sites/${siteId}/vector-observability?${params.toString()}`,
      undefined,
      { requireAuth: true }
    );
  }

  async listAIInsightHistory(
    siteId: string,
    options?: {
      limit?: number;
    }
  ): Promise<PortalEnvelope<PortalAIInsightHistoryResponse>> {
    const params = new URLSearchParams();
    params.set('limit', String(options?.limit || 10));
    return this.request(
      'GET',
      `/sites/${siteId}/ai-insights/history?${params.toString()}`,
      undefined,
      { requireAuth: true }
    );
  }

  async analyzeAIInsight(
    siteId: string,
    options?: {
      forceRefresh?: boolean;
    }
  ): Promise<PortalEnvelope<PortalAIInsightResponse>> {
    return this.request(
      'POST',
      `/sites/${siteId}/ai-insights/analyze`,
      { force_refresh: Boolean(options?.forceRefresh) },
      { requireAuth: true }
    );
  }

  /**
   * 获取权益信息
   * GET /portal/v1/sites/{siteId}/entitlements
   */
  async getEntitlements(siteId: string): Promise<PortalEnvelope<Entitlements>> {
    return this.request('GET', `/sites/${siteId}/entitlements`, undefined, { requireAuth: true });
  }

  /**
   * 获取本期积分账本明细
   * GET /portal/v1/sites/{siteId}/credit-ledger
   */
  async getCreditLedger(
    siteId: string,
    options?: { limit?: number; offset?: number }
  ): Promise<PortalEnvelope<PortalCreditLedgerPayload>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/sites/${siteId}/credit-ledger${query}`, undefined, { requireAuth: true });
  }

  async listCreditPacks(siteId: string): Promise<PortalEnvelope<PortalCreditPackCatalogPayload>> {
    return this.request('GET', `/sites/${siteId}/credit-packs`, undefined, { requireAuth: true });
  }

  async listPaymentOrders(
    siteId: string,
    options?: { limit?: number; offset?: number }
  ): Promise<PortalEnvelope<PortalPaymentOrderListPayload>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/sites/${siteId}/payment-orders${query}`, undefined, { requireAuth: true });
  }

  async listAccountPaymentOrders(
    options?: { limit?: number; offset?: number }
  ): Promise<PortalEnvelope<PortalPaymentOrderListPayload>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/account/payment-orders${query}`, undefined, { requireAuth: true });
  }

  async createCreditPackOrder(
    siteId: string,
    packId: string,
    provider = 'alipay'
  ): Promise<PortalEnvelope<PortalCreditPackOrderPayload>> {
    return this.request(
      'POST',
      `/sites/${siteId}/credit-pack-orders`,
      { pack_id: packId, provider },
      { requireAuth: true }
    );
  }

  async startProTrial(): Promise<PortalEnvelope<PortalProTrialPayload>> {
    return this.request('POST', '/account/pro-trial', {}, { requireAuth: true });
  }

  async createProMonthlyOrder(provider = 'alipay'): Promise<PortalEnvelope<PortalProMonthlyOrderPayload>> {
    return this.request(
      'POST',
      '/account/pro-monthly-order',
      { provider },
      { requireAuth: true }
    );
  }

  /**
   * 获取审计摘要
   * GET /portal/v1/sites/{siteId}/audit-summary
   */
  async getAuditSummary(siteId: string): Promise<PortalEnvelope<PortalAuditSummary>> {
    return this.request('GET', `/sites/${siteId}/audit-summary`, undefined, { requireAuth: true });
  }

  /**
   * 获取审计事件列表
   * GET /portal/v1/sites/{siteId}/audit-events
   */
  async listAuditEvents(
    siteId: string,
    options?: {
      eventKind?: string;
      outcome?: string;
      limit?: number;
    }
  ): Promise<PortalEnvelope<PortalAuditEventList>> {
    const params = new URLSearchParams();
    if (options?.eventKind) params.set('event_kind', options.eventKind);
    if (options?.outcome) params.set('outcome', options.outcome);
    if (options?.limit) params.set('limit', String(options.limit));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/sites/${siteId}/audit-events${query}`, undefined, { requireAuth: true });
  }

  /**
   * 获取账单快照列表
   * GET /portal/v1/sites/{siteId}/billing-snapshots
   */
  async listBillingSnapshots(siteId: string): Promise<PortalEnvelope<{
    site_id?: string;
    account_id?: string;
    site_admin_ref?: string;
    role?: string;
    items: PortalBillingSnapshot[];
  }>> {
    return this.request('GET', `/sites/${siteId}/billing-snapshots`, undefined, { requireAuth: true });
  }

  /**
   * 获取账单对账信息
   * GET /portal/v1/sites/{siteId}/billing-snapshots/reconciliation
   */
  async getBillingReconciliation(siteId: string): Promise<PortalEnvelope<PortalBillingReconciliation>> {
    return this.request('GET', `/sites/${siteId}/billing-snapshots/reconciliation`, undefined, { requireAuth: true });
  }

  async getSiteBundle(siteId: string): Promise<PortalSiteBundle> {
    const [summaryResponse, apiKeysResponse] = await Promise.all([
      this.getSiteSummary(siteId),
      this.listApiKeys(siteId),
    ]);
    return {
      summary: normalizePortalSiteSummaryRecord(summaryResponse.data),
      apiKeys: apiKeysResponse.data.items || [],
    };
  }

  async getUsageBundle(siteId: string): Promise<PortalUsageBundle> {
    const [
      usageResponse,
      entitlementsResponse,
      creditLedgerResponse,
      creditPacksResponse,
      paymentOrdersResponse,
    ] = await Promise.all([
      this.getUsageSummary(siteId),
      this.getEntitlements(siteId),
      this.getCreditLedger(siteId, { limit: 12 }),
      this.listCreditPacks(siteId),
      this.listAccountPaymentOrders({ limit: 8 }),
    ]);
    return {
      usage: usageResponse.data,
      entitlements: entitlementsResponse.data,
      creditLedger: creditLedgerResponse.data,
      creditPacks: creditPacksResponse.data,
      paymentOrders: paymentOrdersResponse.data,
    };
  }

  async getAuditBundle(
    siteId: string,
    options?: {
      eventKind?: string;
      outcome?: string;
      limit?: number;
    }
  ): Promise<PortalAuditBundle> {
    const [summaryResponse, eventsResponse] = await Promise.all([
      this.getAuditSummary(siteId),
      this.listAuditEvents(siteId, options),
    ]);
    return {
      summary: summaryResponse.data,
      events: eventsResponse.data.items || [],
    };
  }

  async getBillingBundle(siteId: string): Promise<PortalBillingBundle> {
    const [snapshotsResponse, reconciliationResponse] = await Promise.all([
      this.listBillingSnapshots(siteId),
      this.getBillingReconciliation(siteId),
    ]);
    return {
      snapshots: snapshotsResponse.data.items || [],
      reconciliation: reconciliationResponse.data,
    };
  }

  async getSiteDiagnostics(siteId: string): Promise<PortalEnvelope<PortalSiteDiagnostics>> {
    return this.request('GET', `/sites/${siteId}/diagnostics`, undefined, { requireAuth: true });
  }

  // ========================================
  // Analytics Dashboard
  // ========================================

  /**
   * 获取 Analytics Trend
   * GET /portal/v1/sites/{siteId}/analytics/trend
   */
  async getAnalyticsTrend(
    siteId: string,
    range: string = '7d',
    granularity: string = 'daily'
  ): Promise<PortalEnvelope<PortalAnalyticsTrend>> {
    const params = new URLSearchParams();
    params.set('range', range);
    params.set('granularity', granularity);
    return this.request('GET', `/sites/${siteId}/analytics/trend?${params.toString()}`, undefined, { requireAuth: true });
  }

  /**
   * 获取 Analytics Cost Breakdown
   * GET /portal/v1/sites/{siteId}/analytics/cost-breakdown
   */
  async getAnalyticsCostBreakdown(
    siteId: string,
    range: string = '7d',
    groupBy: string = 'provider'
  ): Promise<PortalEnvelope<PortalAnalyticsCostBreakdown>> {
    const params = new URLSearchParams();
    params.set('range', range);
    params.set('group_by', groupBy);
    return this.request('GET', `/sites/${siteId}/analytics/cost-breakdown?${params.toString()}`, undefined, { requireAuth: true });
  }

  /**
   * 获取 Analytics Performance
   * GET /portal/v1/sites/{siteId}/analytics/performance
   */
  async getAnalyticsPerformance(
    siteId: string,
    range: string = '7d'
  ): Promise<PortalEnvelope<PortalAnalyticsPerformance>> {
    return this.request('GET', `/sites/${siteId}/analytics/performance?range=${encodeURIComponent(range)}`, undefined, { requireAuth: true });
  }

  // ========================================
  // API Key 管理
  // ========================================

  /**
   * 获取 API Key 列表
   * GET /portal/v1/sites/{siteId}/api-keys
   */
  async listApiKeys(siteId: string): Promise<PortalEnvelope<{ items: ApiKey[] }>> {
    return this.request('GET', `/sites/${siteId}/api-keys`, undefined, { requireAuth: true });
  }

  /**
   * 创建 API Key
   * POST /portal/v1/sites/{siteId}/api-keys
   */
  async createApiKey(
    siteId: string,
    payload: CreateKeyRequest
  ): Promise<PortalEnvelope<ApiKeyWithSecret>> {
    return this.request('POST', `/sites/${siteId}/api-keys`, payload, { requireAuth: true });
  }

  /**
   * 轮换 API Key
   * POST /portal/v1/sites/{siteId}/api-keys/{keyId}/rotate
   */
  async rotateApiKey(
    siteId: string,
    keyId: string,
    payload: RotateKeyRequest
  ): Promise<PortalEnvelope<RotateKeyResponse>> {
    return this.request('POST', `/sites/${siteId}/api-keys/${keyId}/rotate`, payload, { requireAuth: true });
  }

  /**
   * 吊销 API Key
   * POST /portal/v1/sites/{siteId}/api-keys/{keyId}/revoke
   */
  async revokeApiKey(siteId: string, keyId: string): Promise<PortalEnvelope<ApiKey>> {
    return this.request('POST', `/sites/${siteId}/api-keys/${keyId}/revoke`, undefined, { requireAuth: true });
  }

  // ========================================
  // Admin API (Internal Only)
  // ========================================

  /**
   * 获取管理员总览
   * GET /internal/service/admin/overview
   */
  async getAdminOverview(): Promise<PortalEnvelope<{
    total_accounts: number;
    total_site_admins: number;
    total_sites: number;
    total_subscriptions: number;
    active_site_keys: number;
    expiring_subscriptions: {
      total: number;
      in_7_days: number;
      in_30_days: number;
      items: Array<{
        subscription_id: string;
        account_id: string;
        site_id: string;
        status: string;
        current_period_end: string;
      }>;
    };
    attention_subscriptions: Array<{
      subscription_id: string;
      account_id: string;
      site_id: string;
      status: string;
      reason: string;
    }>;
    runtime_summary: {
      queued_runs: number;
      callback_failed: number;
      guard_events: number;
    };
  }>> {
    return this.request('GET', '/internal/service/admin/overview', undefined, { requireAuth: true });
  }

  /**
   * 获取账户列表
   * GET /internal/service/admin/accounts
   */
  async listAdminAccounts(options?: {
    status?: string;
    expires_before?: string;
    limit?: number;
  }): Promise<PortalEnvelope<{
    items: Array<{
      account_id: string;
      name: string;
      status: string;
      site_count: number;
      subscription_count: number;
      top_plan?: string;
      nearest_expiry?: string;
    }>;
    total: number;
  }>> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.expires_before) params.set('expires_before', options.expires_before);
    if (options?.limit) params.set('limit', String(options.limit));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/internal/service/admin/accounts${query}`, undefined, { requireAuth: true });
  }

  /**
   * 获取账户详情
   * GET /internal/service/admin/accounts/{account_id}
   */
  async getAdminAccount(accountId: string): Promise<PortalEnvelope<{
    account_id: string;
    name: string;
    status: string;
    created_at: string;
    site_count: number;
    subscription_count: number;
    subscriptions: Array<{
      subscription_id: string;
      status: string;
      plan_id: string;
      plan_version_id?: string;
      package_alias?: string;
      current_period_end: string;
    }>;
  }>> {
    return this.request('GET', `/internal/service/admin/accounts/${accountId}`, undefined, { requireAuth: true });
  }

  /**
   * 获取站点列表
   * GET /internal/service/admin/sites
   */
  async listAdminSites(options?: {
    status?: string;
    account_id?: string;
    subscription_status?: string;
    expires_before?: string;
    limit?: number;
  }): Promise<PortalEnvelope<{
    items: Array<{
      site_id: string;
      account_id: string;
      site_name: string;
      status: string;
      key_count: number;
      subscription_status: string;
      plan_id: string;
      current_period_end: string;
      recent_usage?: {
        requests: number;
        tokens: number;
      };
    }>;
    total: number;
  }>> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.account_id) params.set('account_id', options.account_id);
    if (options?.subscription_status) params.set('subscription_status', options.subscription_status);
    if (options?.expires_before) params.set('expires_before', options.expires_before);
    if (options?.limit) params.set('limit', String(options.limit));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/internal/service/admin/sites${query}`, undefined, { requireAuth: true });
  }

  /**
   * 获取站点详情
   * GET /internal/service/admin/sites/{site_id}
   */
  async getAdminSite(siteId: string): Promise<PortalEnvelope<{
    site_id: string;
    account_id: string;
    site_name: string;
    status: string;
    created_at: string;
    key_count: number;
    subscription?: {
      subscription_id: string;
      status: string;
      plan_id: string;
      current_period_start: string;
      current_period_end: string;
    };
    usage_summary?: {
      requests_total: number;
      tokens_total: number;
      cost_estimate: number;
    };
    billing_summary?: {
      total_snapshots: number;
      latest_snapshot?: {
        snapshot_id: string;
        status: string;
        cost: number;
      };
    };
    runtime_summary?: {
      total_runs: number;
      failed_runs: number;
      last_run_at?: string;
    };
  }>> {
    return this.request('GET', `/internal/service/admin/sites/${siteId}`, undefined, { requireAuth: true });
  }

  /**
   * 获取订阅列表
   * GET /internal/service/admin/subscriptions
   */
  async listAdminSubscriptions(options?: {
    status?: string;
    account_id?: string;
    site_id?: string;
    plan_id?: string;
    expires_before?: string;
    limit?: number;
  }): Promise<PortalEnvelope<{
    items: Array<{
      subscription_id: string;
      account_id: string;
      site_id?: string;
      site_name?: string;
      account_name?: string;
      status: string;
      plan_id: string;
      plan_version_id: string;
      current_period_start: string;
      current_period_end: string;
      grace_state?: string;
      billing_summary?: {
        total_cost: number;
        latest_snapshot_id?: string;
      };
    }>;
    total: number;
  }>> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.account_id) params.set('account_id', options.account_id);
    if (options?.site_id) params.set('site_id', options.site_id);
    if (options?.plan_id) params.set('plan_id', options.plan_id);
    if (options?.expires_before) params.set('expires_before', options.expires_before);
    if (options?.limit) params.set('limit', String(options.limit));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/internal/service/admin/subscriptions${query}`, undefined, { requireAuth: true });
  }

  /**
   * 获取订阅详情
   * GET /internal/service/admin/subscriptions/{subscription_id}
   */
  async getAdminSubscription(subscriptionId: string): Promise<PortalEnvelope<{
    subscription_id: string;
    account_id: string;
    site_id?: string;
    status: string;
    plan_id: string;
    plan_version_id: string;
    current_period_start: string;
    current_period_end: string;
    grace_state?: string;
    downgrade_state?: string;
    billing_snapshots: Array<{
      snapshot_id: string;
      period_start: string;
      period_end: string;
      status: string;
      cost: number;
      created_at: string;
    }>;
    audit_events: Array<{
      event_id: string;
      event_kind: string;
      outcome: string;
      message: string;
      created_at: string;
    }>;
  }>> {
    return this.request('GET', `/internal/service/admin/subscriptions/${subscriptionId}`, undefined, { requireAuth: true });
  }
}

// ============================================
// 单例实例
// ============================================

export const portalClient = new PortalClient();

export default PortalClient;
