/**
 * Npcink AI Cloud Portal API Client
 *
 * 对接后端 Portal API (/portal/v1/*)
 * 支持邮箱验证码认证、Session 管理与 Portal 工作区能力
 */

import { ApiClient, type ApiEnvelope, type ApiMethod } from './api-client';
import { getPortalApiBaseUrl } from './env';

// ============================================
// 类型定义
// ============================================

export interface PortalSession {
  email: string;
  sites: Site[];
  selected_context: PortalSelectedContext | null;
  auth_mode: string;
  session: {
    state: 'active';
    transport: string;
    issued_at: string;
    expires_at: string;
    revocable: boolean;
  };
}

export interface PortalSelectedContext {
  site: Site;
  allowed_actions: string[];
  current_subscription: PortalCurrentSubscription | null;
}

export interface PortalCurrentSubscription {
  subscription_id: string;
  plan_id: string;
  plan_version_id: string;
  status: string;
  tier_id: string;
  plan_kind: string;
  package_kind: string;
  package_alias: string;
  display_package_label: string;
  coverage_state: string;
  current_period_start_at: string;
  current_period_end_at: string;
  scheduled_plan_id: string;
  scheduled_plan_version_id: string;
  scheduled_change_at: string;
}

export interface Site {
  site_id: string;
  name: string;
  site_url: string;
  platform_kind: string;
  status: string;
}

export interface PortalSiteDetail extends Site {
  created_at: string;
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

export interface PortalIdentityProviderBinding {
  binding_id: string;
  provider: string;
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

export interface CreateAddonConnectionRequest {
  account_id: string;
  site_name?: string;
  site_url: string;
  return_url: string;
  state: string;
}

export interface PortalAddonConnectionAccount {
  account_id: string;
  name: string;
  site_count: number;
}

export interface PortalAddonConnectionAccountsPayload {
  items: PortalAddonConnectionAccount[];
}

export interface AddonConnectionResult {
  site_id: string;
  site_url: string;
  platform_kind: 'wordpress';
  key_id: string;
  site_created: boolean;
  redirect_url: string;
  return_url: string;
  expires_at: string;
  expires_in_seconds: number;
}

export interface PortalAccountEntitlements {
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
      package_limit?: number;
      package_remaining?: number;
      paid_remaining?: number;
      paid_grant_count?: number;
      paid_next_expires_at?: string;
      total_remaining?: number;
    };
    credit_ledger_summary?: {
      consumed_credits?: number;
      granted_credits?: number;
      adjustment_credits?: number;
      refund_credits?: number;
      net_credit_delta?: number;
      net_used_credits?: number;
      entry_count?: number;
    };
    credit_policy?: {
      rate_version?: string;
      period_policy?: string;
      renewal_policy?: string;
      topup_policy?: string;
      paid_credit_policy?: string;
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

export interface PortalSitePlanVersion {
  plan_version_id: string;
  plan_id: string;
  version_label: string;
  status: string;
  currency: string;
  entitlements: Record<string, unknown>;
  budgets: Record<string, unknown>;
}

export interface PortalSiteEntitlementSnapshot {
  subscription_id: string;
  plan_version_id: string;
  status: string;
  entitlements: Record<string, unknown>;
  budgets: Record<string, unknown>;
  site_limit: number;
  generated_at: string;
}

export interface PortalSiteEntitlements extends PortalAccountEntitlements {
  site_id: string;
  site: PortalSiteDetail;
  subscription: PortalCurrentSubscription | null;
  plan_version: PortalSitePlanVersion | null;
  entitlement_snapshot: PortalSiteEntitlementSnapshot | null;
  policy: {
    subscription: {
      grace_period_days: number;
    };
  };
}

export type Entitlements = PortalAccountEntitlements;

export interface PortalSiteSummaryRecord {
  site_id: string;
  site: PortalSiteDetail;
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
  };
  entitlement_snapshot?: PortalSiteEntitlementSnapshot | null;
  customer_status?: {
    status: string;
    needs_attention: boolean;
    issue_count: number;
    generated_at?: string;
  };
  generated_at?: string;
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
  site_ids?: string[];
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
}

export interface PortalPluginObservabilitySummary {
  contract_version: string;
  site_id: string;
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
  delivery_started_count: number;
  delivery_stream_completed_count: number;
  delivery_acknowledged_count: number;
  stream_completion_rate: number;
  acknowledgement_rate: number;
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
  analysis: PortalAIInsightAnalysis;
  safety: PortalAIInsightSafety;
}

export interface PortalAIInsightHistoryResponse {
  portal_ai_insight_version: string;
  site_id: string;
  items: PortalAIInsightHistoryItem[];
  safety: PortalAIInsightSafety;
}

export interface PortalAuditEvent {
  event_id: string | number;
  event_kind: string;
  outcome: string;
  created_at: string;
  trace_id?: string;
}

export interface PortalAuditSummary {
  site_id?: string;
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
  items: PortalAuditEvent[];
}

export interface PortalBillingSnapshot {
  snapshot_id: string;
  site_id?: string;
  subscription_id?: string;
  plan_version_id?: string;
  currency?: string;
  period_start_at: string;
  period_end_at: string;
  totals?: {
    runs: number;
    provider_calls: number;
    tokens_in?: number;
    tokens_out?: number;
    tokens_total?: number;
    cost: number;
  };
  breakdown?: Record<string, unknown>;
  generated_at: string;
}

export interface PortalBillingReconciliation {
  site_id?: string;
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

function normalizePortalSiteEntitlementSnapshot(
  raw: unknown
): PortalSiteEntitlementSnapshot | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const snapshot = raw as Record<string, unknown>;
  const entitlements = snapshot.entitlements;
  const budgets = snapshot.budgets;
  return {
    subscription_id: String(snapshot.subscription_id || ''),
    plan_version_id: String(snapshot.plan_version_id || ''),
    status: String(snapshot.status || ''),
    entitlements:
      entitlements && typeof entitlements === 'object' && !Array.isArray(entitlements)
        ? (entitlements as Record<string, unknown>)
        : {},
    budgets:
      budgets && typeof budgets === 'object' && !Array.isArray(budgets)
        ? (budgets as Record<string, unknown>)
        : {},
    site_limit: Number(snapshot.site_limit || 0),
    generated_at: String(snapshot.generated_at || ''),
  };
}

function normalizePortalSiteSummaryRecord(raw: unknown): PortalSiteSummaryRecord {
  const record = (raw || {}) as Record<string, unknown>;
  const nestedCoverage = ((record.coverage || {}) as Record<string, unknown>);
  const nestedCustomerStatus = ((record.customer_status || {}) as Record<string, unknown>);
  const nestedSite = ((record.site || {}) as Record<string, unknown>);

  return {
    site_id: String(record.site_id || ''),
    site: {
      site_id: String(nestedSite.site_id || record.site_id || ''),
      name: String(nestedSite.name || nestedSite.site_id || record.site_id || ''),
      site_url: String(nestedSite.site_url || ''),
      platform_kind: String(nestedSite.platform_kind || ''),
      status: String(nestedSite.status || 'inactive'),
      created_at: String(nestedSite.created_at || ''),
    },
    package_alias:
      String(record.package_alias || '') ||
      String(nestedCoverage.package_alias || ''),
    covered_by_subscription_id: String(record.covered_by_subscription_id || nestedCoverage.subscription_id || ''),
    subscription_status: String(record.subscription_status || nestedCoverage.status || ''),
    coverage: {
      subscription_id: String(record.covered_by_subscription_id || nestedCoverage.subscription_id || ''),
      status: String(record.subscription_status || nestedCoverage.status || ''),
      plan_id: String(nestedCoverage.plan_id || ''),
      plan_version_id: String(nestedCoverage.plan_version_id || ''),
      package_alias:
        String(nestedCoverage.package_alias || '') ||
        String(record.package_alias || ''),
      current_period_start: String(nestedCoverage.current_period_start || ''),
      current_period_end: String(nestedCoverage.current_period_end || ''),
      current_period_start_at: String(nestedCoverage.current_period_start_at || ''),
      current_period_end_at: String(nestedCoverage.current_period_end_at || ''),
    },
    entitlement_snapshot: normalizePortalSiteEntitlementSnapshot(record.entitlement_snapshot),
    customer_status:
      Object.keys(nestedCustomerStatus).length > 0
        ? {
            status: String(nestedCustomerStatus.status || 'inactive'),
            needs_attention: Boolean(nestedCustomerStatus.needs_attention),
            issue_count: Number(nestedCustomerStatus.issue_count || 0),
            generated_at: String(nestedCustomerStatus.generated_at || ''),
          }
        : undefined,
    generated_at: String(record.generated_at || ''),
  };
}

export interface PortalUsageBundle {
  usage: PortalUsageSummaryPayload;
  entitlements: PortalAccountEntitlements;
}

export interface PortalCommercialBundle {
  entitlements: PortalAccountEntitlements;
  creditPacks: PortalCreditPackCatalogPayload;
  planOffers: PortalPlanOfferListPayload;
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
  validity_days: number;
  recommended_for_tiers?: string[];
  active?: boolean;
  period_policy?: string;
  grant_event_type?: string;
  catalog_version?: string;
}

export interface PortalCreditPackCatalogPayload {
  site_id?: string;
  catalog_version?: string;
  period_policy?: string;
  expiry_policy?: string;
  default_validity_days?: number;
  grant_event_type?: string;
  items: PortalCreditPack[];
}

export interface PortalPaymentOrder {
  order_id: string;
  site_id?: string;
  subscription_id?: string;
  target_subscription_id?: string;
  target_tier_id?: string;
  plan_id?: string;
  plan_version_id?: string;
  provider: string;
  status: string;
  amount: number;
  currency: string;
  subject: string;
  checkout_url?: string;
  available_actions?: Array<'continue_payment' | 'cancel'>;
  expires_at?: string;
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
  canceled_at?: string;
  refund_window_end_at?: string;
  refunded_at?: string;
  updated_at?: string;
}

export interface PortalCreditPackOrderPayload {
  site_id?: string;
  order: PortalPaymentOrder;
}

export type PortalPaymentOrderStatusGroup = 'all' | 'pending' | 'paid' | 'closed';

export interface PortalPlanOffer {
  offer_id: string;
  plan_id: string;
  plan_version_id: string;
  tier_id: 'plus' | 'pro' | 'agency';
  billing_cycle: 'monthly';
  amount: number;
  currency: 'CNY';
  purchase_mode: 'self_serve' | 'quote';
  status: string;
  trial_enabled: boolean;
  trial_days: number;
  trial_credit_limit: number;
  trial_requires_approval: boolean;
  valid_from_at?: string;
  valid_until_at?: string;
}

export interface PortalPlanComparisonTier {
  tier_id: 'free' | 'plus' | 'pro';
  label: string;
  plan_id: string;
  plan_version_id: string;
  monthly_points: number | null;
  site_limit: number | null;
  knowledge_article_limit: number | null;
  concurrency_limit: number | null;
  batch_item_limit: number | null;
  comparison_rights?: Record<PortalPlanComparisonRightKey, PortalPlanComparisonRight>;
  amount?: number | null;
  currency: 'CNY';
  billing_cycle?: 'monthly' | null;
  purchase_mode: 'included' | 'self_serve';
}

export type PortalPlanComparisonRightKey =
  | 'monthly_points'
  | 'site_limit'
  | 'knowledge_article_limit'
  | 'concurrency_limit'
  | 'batch_item_limit';

export interface PortalPlanComparisonRight {
  state: 'limited' | 'unlimited' | 'not_included' | 'unconfigured';
  value: number | null;
}

export interface PortalPlanOfferListPayload {
  items: PortalPlanOffer[];
  comparison_tiers?: PortalPlanComparisonTier[];
  trial?: {
    available?: boolean;
    status?: string;
    state?: 'eligible' | 'active' | 'used' | 'blocked' | 'unavailable';
    reason_code?:
      | 'trial_available'
      | 'trial_active'
      | 'trial_already_used'
      | 'paid_plan_active'
      | 'trial_not_offered';
    allowed_tiers?: Array<'plus' | 'pro'>;
    tier_id?: string;
    highest_tier_id?: string;
    trial_days?: number;
    credit_limit?: number;
    trial_started_at?: string;
    trial_ends_at?: string;
  };
}

export interface PortalPlanTrialPayload {
  subscription: PortalCurrentSubscription;
  entitlement_snapshot: PortalSiteEntitlementSnapshot | null;
  trial?: {
    available?: boolean;
    status?: string;
    tier_id?: string;
    trial_days?: number;
    credit_limit?: number;
    trial_started_at?: string;
    trial_ends_at?: string;
    monthly_price_cny?: number;
  };
  session?: PortalSession;
}

export interface PortalSubscriptionOrder {
  subscription_order_id: string;
  offer_id: string;
  payment_order_id: string;
  source_subscription_id?: string;
  target_plan_id: string;
  target_plan_version_id: string;
  order_kind: 'purchase' | 'upgrade' | 'renewal' | 'downgrade';
  status: string;
  list_amount: number;
  credit_amount: number;
  payable_amount: number;
  currency: 'CNY';
  effective_at?: string;
  period_start_at?: string;
  period_end_at?: string;
}

export interface PortalSubscriptionOrderPayload {
  order: PortalPaymentOrder;
  subscription_order: PortalSubscriptionOrder;
}

export interface PortalPaymentOrderListPayload {
  site_id?: string;
  generated_at?: string;
  status_group?: PortalPaymentOrderStatusGroup;
  counts?: Record<PortalPaymentOrderStatusGroup, number>;
  visibility?: {
    canceled_orders_visible_days?: number;
    database_records_deleted?: boolean;
  };
  pagination?: {
    limit?: number;
    offset?: number;
    total?: number;
    has_more?: boolean;
  };
  items: PortalPaymentOrder[];
}

export type PortalSupportRequestStatus = 'open' | 'in_progress' | 'resolved' | 'closed';

export interface PortalSupportRequest {
  request_id: string;
  site_id?: string;
  topic: string;
  title: string;
  description: string;
  status: PortalSupportRequestStatus;
  priority: string;
  source_path?: string;
  context?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  resolved_at?: string;
  closed_at?: string;
}

export interface PortalSupportRequestMessage {
  message_id: string;
  request_id: string;
  author_kind: 'customer' | 'operator' | 'system' | string;
  body: string;
  created_at?: string;
}

export interface PortalSupportRequestAttachment {
  attachment_id: string;
  request_id: string;
  message_id?: string;
  uploader_kind: 'customer' | 'operator' | string;
  filename: string;
  content_type: string;
  byte_size: number;
  content_base64?: string;
  created_at?: string;
}

export interface PortalSupportRequestFeedback {
  feedback_id: string;
  request_id: string;
  resolved: boolean;
  rating: number;
  comment?: string;
  created_at?: string;
  updated_at?: string;
}

export interface PortalSupportRequestListPayload {
  items: PortalSupportRequest[];
  pagination?: {
    limit?: number;
    offset?: number;
    total?: number;
    has_more?: boolean;
  };
  summary?: {
    open?: number;
    in_progress?: number;
  };
}

export interface PortalSupportRequestDetailPayload {
  request: PortalSupportRequest;
  messages: PortalSupportRequestMessage[];
  attachments?: PortalSupportRequestAttachment[];
  feedback?: PortalSupportRequestFeedback | null;
}

export interface CreatePortalSupportRequestPayload {
  topic: string;
  title: string;
  description: string;
  site_id?: string;
  source_path?: string;
  context?: Record<string, unknown>;
}

export interface CreatePortalSupportRequestMessagePayload {
  body: string;
}

export interface CreatePortalSupportRequestAttachmentPayload {
  filename: string;
  content_type: string;
  content_base64: string;
  message_id?: string;
}

export interface SubmitPortalSupportRequestFeedbackPayload {
  resolved: boolean;
  rating: number;
  comment?: string;
}

export interface PortalCreditLedgerPayload {
  site_id?: string;
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
  usage_detail?: {
    surface?: string;
    default_visibility?: string;
    local_addon_policy?: string;
    generated_at?: string;
    period?: {
      start_at?: string;
      end_at?: string;
    };
    summary?: {
      used?: number;
      limit?: number;
      remaining?: number | null;
      status?: string;
      unit?: string;
      rate_version?: string;
    };
    breakdown?: Array<{
      key?: string;
      label?: string;
      quantity?: number;
      unit?: string;
      rate?: number;
      rate_unit?: string;
      credits?: number;
      capability_group?: string;
    }>;
    recent_items?: PortalCreditLedgerEntry[];
    copy?: {
      title?: string;
      summary?: string;
      addon_summary?: string;
    };
    legend?: Array<{ category?: string; label?: string }>;
    portal_paths?: {
      credit_usage?: string;
      credit_ledger?: string;
    };
  };
  items: PortalCreditLedgerEntry[];
}

export type PortalCreditTrendWindow = '1h' | '24h' | '7d' | '30d';

export interface PortalCreditTrendPoint {
  start_at: string;
  end_at: string;
  credits: number;
  entry_count: number;
}

export interface PortalCreditTrendPayload {
  contract_version: 'portal-credit-trend-v1';
  generated_at: string;
  site_id: string;
  window: PortalCreditTrendWindow;
  bucket_seconds: number;
  start_at: string;
  end_at: string;
  total_credits: number;
  entry_count: number;
  points: PortalCreditTrendPoint[];
}

export type PortalCreditEventWindow = '24h' | '7d' | '30d' | 'period';
export type PortalCreditEventFeature =
  | ''
  | 'content_generation'
  | 'topic_research'
  | 'web_search'
  | 'site_knowledge'
  | 'image_assistance'
  | 'audio_generation';

export interface PortalCreditEvent {
  event_id: string;
  support_reference: string;
  site_id: string;
  feature_key: string;
  feature_label: string;
  feature_detail: string;
  created_at: string;
  net_credit_delta: number;
  consumed_credits: number;
  direction: 'consumed' | 'added';
  component_count: number;
  components: Array<{ key: string; credits: number }>;
}

export interface PortalCreditEventsPayload {
  contract_version: 'portal-credit-events-v1';
  generated_at: string;
  period_start_at: string;
  period_end_at: string;
  filters: { window: PortalCreditEventWindow; site_id: string; feature: string };
  summary: { event_count: number; consumed_credits: number };
  pagination: { limit: number; offset: number; total: number; has_more: boolean };
  items: PortalCreditEvent[];
}

export type PortalCreditEventBucketSize = '10m' | '30m' | '60m';
export interface PortalCreditEventBucket {
  bucket_id: string;
  start_at: string;
  end_at: string;
  consumed_credits: number;
  event_count: number;
  site_count: number;
  top_feature_key: string;
  feature_totals: Array<{ feature_key: string; consumed_credits: number; event_count: number }>;
}
export interface PortalCreditEventBucketsPayload {
  contract_version: 'portal-credit-event-buckets-v1';
  generated_at: string;
  period_start_at: string;
  period_end_at: string;
  bucket: PortalCreditEventBucketSize;
  bucket_seconds: number;
  timezone: string;
  filters: { window: PortalCreditEventWindow; site_id: string; feature: string };
  summary: { bucket_count: number; consumed_credits: number };
  pagination: { limit: number; offset: number; total: number; has_more: boolean };
  items: PortalCreditEventBucket[];
}

export interface PortalAuditBundle {
  summary: PortalAuditSummary;
  events: PortalAuditEvent[];
}

export interface PortalSiteDiagnostics {
  site_id: string;
  generated_at: string;
  site_status?: string;
  site_url: string;
  platform_kind: 'wordpress';
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

export type PortalEnvelope<T> = ApiEnvelope<T>;

// ============================================
// Portal API Client
// ============================================

export class PortalClient {
  private apiClient?: ApiClient;

  constructor(private readonly baseUrl?: string) {}

  /**
   * 通用请求方法
   */
  private async request<T>(
    method: ApiMethod,
    path: string,
    body?: unknown
  ): Promise<PortalEnvelope<T>> {
    this.apiClient ??= new ApiClient({
      baseUrl: this.baseUrl || getPortalApiBaseUrl(),
      idempotencyPrefix: 'portal_write',
    });
    return this.apiClient.request<T>(path, {
      method,
      ...(body === undefined ? {} : { body }),
    });
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
    return this.request('POST', '/account/email-change/request', payload);
  }

  async verifyEmailChangeCode(payload: PortalEmailChangeVerifyRequest): Promise<PortalEnvelope<PortalEmailChangeResult>> {
    return this.request('POST', '/account/email-change/verify', payload);
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
      site_url: string;
      platform_kind: 'wordpress';
    };
  }>> {
    return this.request('POST', '/register/code/request', payload);
  }

  /**
   * 验证注册验证码并创建 Free 账号
   * POST /portal/v1/register/verify
   */
  async verifyRegistration(payload: PortalRegistrationVerifyRequest): Promise<PortalEnvelope<PortalSession>> {
    return this.request('POST', '/register/verify', payload);
  }

  /**
   * 获取当前账号的第三方登录绑定状态
   * GET /portal/v1/auth/identity-providers
   */
  async getIdentityProviders(): Promise<PortalEnvelope<PortalIdentityProvidersResponse>> {
    return this.request('GET', '/auth/identity-providers', undefined);
  }

  /**
   * 发起 QQ 绑定授权
   * GET /portal/v1/auth/qq/start?intent=bind
   */
  async startQqBind(returnTo = '/portal/account'): Promise<PortalEnvelope<PortalQqStartResponse>> {
    const params = new URLSearchParams({ intent: 'bind', return_to: returnTo });
    return this.request('GET', `/auth/qq/start?${params.toString()}`, undefined);
  }

  /**
   * 解绑 QQ 快捷登录
   * POST /portal/v1/auth/qq/unbind
   */
  async unbindQqLogin(): Promise<PortalEnvelope<{ provider: string; revoked: number }>> {
    return this.request('POST', '/auth/qq/unbind', { provider: 'qq' });
  }

  // ========================================
  // Session 管理
  // ========================================

  /**
   * 获取当前 Session
   * GET /portal/v1/session
   */
  async getSession(): Promise<PortalEnvelope<PortalSession>> {
    return this.request('GET', '/session', undefined);
  }

  /**
   * 选择站点
   * POST /portal/v1/session/site
   */
  async selectSite(siteId: string): Promise<PortalEnvelope<PortalSession>> {
    return this.request('POST', '/session/site', { site_id: siteId });
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

  async listAddonConnectionAccounts(): Promise<PortalEnvelope<PortalAddonConnectionAccountsPayload>> {
    return this.request('GET', '/addon-connection-accounts', undefined);
  }

  async createAddonConnection(payload: CreateAddonConnectionRequest): Promise<PortalEnvelope<AddonConnectionResult>> {
    return this.request('POST', '/addon-connections', payload);
  }

  async removeSite(siteId: string): Promise<PortalEnvelope<{ site: Site; revoked_key_ids: string[] }>> {
    return this.request('POST', `/sites/${siteId}/remove`, {});
  }

  /**
   * 获取站点摘要
   * GET /portal/v1/sites/{siteId}/summary
   */
  async getSiteSummary(siteId: string): Promise<PortalEnvelope<PortalSiteSummaryRecord>> {
    const response = await this.request<PortalSiteSummaryRecord>('GET', `/sites/${siteId}/summary`, undefined);
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
    return this.request('GET', `/sites/${siteId}/usage-summary`, undefined);
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
      undefined
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
      undefined
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
      undefined
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
      undefined
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
      undefined
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
      undefined
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
      { force_refresh: Boolean(options?.forceRefresh) }
    );
  }

  /**
   * 获取权益信息
   * GET /portal/v1/sites/{siteId}/entitlements
   */
  async getEntitlements(siteId: string): Promise<PortalEnvelope<PortalSiteEntitlements>> {
    return this.request('GET', `/sites/${siteId}/entitlements`, undefined);
  }

  async getAccountEntitlements(): Promise<PortalEnvelope<PortalAccountEntitlements>> {
    return this.request('GET', '/account/entitlements', undefined);
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
    return this.request('GET', `/sites/${siteId}/credit-ledger${query}`, undefined);
  }

  async getAccountCreditLedger(
    options?: { limit?: number; offset?: number }
  ): Promise<PortalEnvelope<PortalCreditLedgerPayload>> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/account/credit-ledger${query}`, undefined);
  }

  async getAccountCreditTrend(
    options: { window: PortalCreditTrendWindow; siteId?: string }
  ): Promise<PortalEnvelope<PortalCreditTrendPayload>> {
    const params = new URLSearchParams({ window: options.window });
    if (options.siteId) params.set('site_id', options.siteId);
    return this.request('GET', `/account/credit-trend?${params.toString()}`, undefined);
  }

  async getAccountCreditEvents(options: {
    window: PortalCreditEventWindow;
    siteId?: string;
    feature?: PortalCreditEventFeature;
    limit?: number;
    offset?: number;
    startAt?: string;
    endAt?: string;
  }): Promise<PortalEnvelope<PortalCreditEventsPayload>> {
    const params = new URLSearchParams({ window: options.window });
    if (options.siteId) params.set('site_id', options.siteId);
    if (options.feature) params.set('feature', options.feature);
    if (options.limit) params.set('limit', String(options.limit));
    if (options.offset) params.set('offset', String(options.offset));
    if (options.startAt) params.set('start_at', options.startAt);
    if (options.endAt) params.set('end_at', options.endAt);
    return this.request('GET', `/account/credit-events?${params.toString()}`, undefined);
  }

  async getAccountCreditEventBuckets(options: {
    bucket: PortalCreditEventBucketSize;
    window: PortalCreditEventWindow;
    siteId?: string;
    feature?: PortalCreditEventFeature;
    limit?: number;
    offset?: number;
  }): Promise<PortalEnvelope<PortalCreditEventBucketsPayload>> {
    const params = new URLSearchParams({ bucket: options.bucket, window: options.window });
    if (options.siteId) params.set('site_id', options.siteId);
    if (options.feature) params.set('feature', options.feature);
    if (options.limit) params.set('limit', String(options.limit));
    if (options.offset) params.set('offset', String(options.offset));
    return this.request('GET', `/account/credit-event-buckets?${params.toString()}`, undefined);
  }

  async listCreditPacks(siteId: string): Promise<PortalEnvelope<PortalCreditPackCatalogPayload>> {
    return this.request('GET', `/sites/${siteId}/credit-packs`, undefined);
  }

  async listAccountCreditPacks(): Promise<PortalEnvelope<PortalCreditPackCatalogPayload>> {
    return this.request('GET', '/account/credit-packs', undefined);
  }

  async listPaymentOrders(
    siteId: string,
    options?: { statusGroup?: PortalPaymentOrderStatusGroup; limit?: number; offset?: number }
  ): Promise<PortalEnvelope<PortalPaymentOrderListPayload>> {
    const params = new URLSearchParams();
    if (options?.statusGroup) params.set('status_group', options.statusGroup);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/sites/${siteId}/payment-orders${query}`, undefined);
  }

  async listAccountPaymentOrders(
    options?: { statusGroup?: PortalPaymentOrderStatusGroup; limit?: number; offset?: number }
  ): Promise<PortalEnvelope<PortalPaymentOrderListPayload>> {
    const params = new URLSearchParams();
    if (options?.statusGroup) params.set('status_group', options.statusGroup);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/account/payment-orders${query}`, undefined);
  }

  async getAccountPaymentOrder(
    orderId: string
  ): Promise<PortalEnvelope<{ order: PortalPaymentOrder }>> {
    return this.request(
      'GET',
      `/account/payment-orders/${encodeURIComponent(orderId)}`,
      undefined
    );
  }

  async cancelAccountPaymentOrder(
    orderId: string
  ): Promise<PortalEnvelope<{ order: PortalPaymentOrder }>> {
    return this.request(
      'POST',
      `/account/payment-orders/${encodeURIComponent(orderId)}/cancellation`,
      {}
    );
  }

  async listSupportRequests(
    options?: { status?: string; limit?: number; offset?: number }
  ): Promise<PortalEnvelope<PortalSupportRequestListPayload>> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));

    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/support-requests${query}`, undefined);
  }

  async createSupportRequest(
    payload: CreatePortalSupportRequestPayload
  ): Promise<PortalEnvelope<{ request: PortalSupportRequest }>> {
    return this.request('POST', '/support-requests', payload);
  }

  async getSupportRequest(requestId: string): Promise<PortalEnvelope<PortalSupportRequestDetailPayload>> {
    return this.request('GET', `/support-requests/${requestId}`, undefined);
  }

  async createSupportRequestMessage(
    requestId: string,
    payload: CreatePortalSupportRequestMessagePayload
  ): Promise<PortalEnvelope<{ request: PortalSupportRequest; message: PortalSupportRequestMessage }>> {
    return this.request('POST', `/support-requests/${requestId}/messages`, payload);
  }

  async createSupportRequestAttachment(
    requestId: string,
    payload: CreatePortalSupportRequestAttachmentPayload
  ): Promise<PortalEnvelope<{ request: PortalSupportRequest; attachment: PortalSupportRequestAttachment }>> {
    return this.request('POST', `/support-requests/${requestId}/attachments`, payload);
  }

  async getSupportRequestAttachment(
    requestId: string,
    attachmentId: string
  ): Promise<PortalEnvelope<{ attachment: PortalSupportRequestAttachment }>> {
    return this.request(
      'GET',
      `/support-requests/${requestId}/attachments/${attachmentId}`,
      undefined
    );
  }

  async submitSupportRequestFeedback(
    requestId: string,
    payload: SubmitPortalSupportRequestFeedbackPayload
  ): Promise<PortalEnvelope<{ request: PortalSupportRequest; feedback: PortalSupportRequestFeedback }>> {
    return this.request('POST', `/support-requests/${requestId}/feedback`, payload);
  }

  async createCreditPackOrder(
    siteId: string,
    packId: string,
    provider = 'alipay'
  ): Promise<PortalEnvelope<PortalCreditPackOrderPayload>> {
    return this.request(
      'POST',
      `/sites/${siteId}/credit-pack-orders`,
      { pack_id: packId, provider }
    );
  }

  async createAccountCreditPackOrder(
    packId: string,
    provider = 'alipay'
  ): Promise<PortalEnvelope<PortalCreditPackOrderPayload>> {
    return this.request(
      'POST',
      '/account/credit-pack-orders',
      { pack_id: packId, provider }
    );
  }

  async listAccountPlanOffers(): Promise<PortalEnvelope<PortalPlanOfferListPayload>> {
    return this.request('GET', '/account/plan-offers', undefined);
  }

  async startPlanTrial(tierId: 'plus' | 'pro'): Promise<PortalEnvelope<PortalPlanTrialPayload>> {
    return this.request('POST', '/account/plan-trials', { tier_id: tierId });
  }

  async createSubscriptionOrder(
    offerId: string,
    provider = 'alipay'
  ): Promise<PortalEnvelope<PortalSubscriptionOrderPayload>> {
    return this.request(
      'POST',
      '/account/subscription-orders',
      { offer_id: offerId, provider }
    );
  }

  async cancelSubscriptionOrder(
    subscriptionOrderId: string
  ): Promise<PortalEnvelope<PortalSubscriptionOrderPayload>> {
    return this.request(
      'DELETE',
      `/account/subscription-orders/${encodeURIComponent(subscriptionOrderId)}`,
      undefined
    );
  }

  async scheduleFreeDowngrade(): Promise<PortalEnvelope<{
    scheduled_tier_id: 'free';
    scheduled_change_at: string;
  }>> {
    return this.request('POST', '/account/free-downgrade', {});
  }

  /**
   * 获取审计摘要
   * GET /portal/v1/sites/{siteId}/audit-summary
   */
  async getAuditSummary(siteId: string): Promise<PortalEnvelope<PortalAuditSummary>> {
    return this.request('GET', `/sites/${siteId}/audit-summary`, undefined);
  }

  async getAccountAuditSummary(): Promise<PortalEnvelope<PortalAuditSummary>> {
    return this.request('GET', '/account/audit-summary', undefined);
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
    return this.request('GET', `/sites/${siteId}/audit-events${query}`, undefined);
  }

  async listAccountAuditEvents(
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
    return this.request('GET', `/account/audit-events${query}`, undefined);
  }

  /**
   * 获取账单快照列表
   * GET /portal/v1/sites/{siteId}/billing-snapshots
   */
  async listBillingSnapshots(siteId: string): Promise<PortalEnvelope<{
    site_id?: string;
    items: PortalBillingSnapshot[];
  }>> {
    return this.request('GET', `/sites/${siteId}/billing-snapshots`, undefined);
  }

  /**
   * 获取账单对账信息
   * GET /portal/v1/sites/{siteId}/billing-snapshots/reconciliation
   */
  async getBillingReconciliation(siteId: string): Promise<PortalEnvelope<PortalBillingReconciliation>> {
    return this.request('GET', `/sites/${siteId}/billing-snapshots/reconciliation`, undefined);
  }

  async getAccountUsageSummary(): Promise<PortalEnvelope<PortalUsageSummaryPayload>> {
    return this.request('GET', '/account/usage-summary', undefined);
  }

  async getUsageBundle(): Promise<PortalUsageBundle> {
    const [usageResponse, entitlementsResponse] = await Promise.all([
      this.getAccountUsageSummary(),
      this.getAccountEntitlements(),
    ]);
    return {
      usage: usageResponse.data,
      entitlements: entitlementsResponse.data,
    };
  }

  async getAccountCommercialBundle(): Promise<PortalCommercialBundle> {
    const [entitlementsResponse, creditPacksResponse, planOffersResponse] = await Promise.all([
      this.getAccountEntitlements(),
      this.listAccountCreditPacks(),
      this.listAccountPlanOffers(),
    ]);
    return {
      entitlements: entitlementsResponse.data,
      creditPacks: creditPacksResponse.data,
      planOffers: planOffersResponse.data,
    };
  }

  async getAuditBundle(
    options?: {
      eventKind?: string;
      outcome?: string;
      limit?: number;
    }
  ): Promise<PortalAuditBundle> {
    const [summaryResponse, eventsResponse] = await Promise.all([
      this.getAccountAuditSummary(),
      this.listAccountAuditEvents(options),
    ]);
    return {
      summary: summaryResponse.data,
      events: eventsResponse.data.items || [],
    };
  }

  async getSiteDiagnostics(siteId: string): Promise<PortalEnvelope<PortalSiteDiagnostics>> {
    return this.request('GET', `/sites/${siteId}/diagnostics`, undefined);
  }

}

// ============================================
// 单例实例
// ============================================

export const portalClient = new PortalClient();

export default PortalClient;
