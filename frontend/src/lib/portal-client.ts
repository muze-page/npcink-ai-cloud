/**
 * Magick AI Cloud Portal API Client
 * 
 * 对接后端 Portal API (/portal/v1/*)
 * 支持邮箱验证码认证、Session 管理、API Key 管理等
 */

import { getPortalApiBaseUrl } from './env';
import { generateIdempotencyKey } from './idempotency';
import type { Locale } from './i18n';

export type ProductIdentityType = 'platform_admin' | 'user_admin';

// ============================================
// 类型定义
// ============================================

export interface PortalSession {
  member_ref: string;
  site_id: string;
  account_id?: string;
  identity_type?: ProductIdentityType;
  allowed_actions?: string[];
  role?: string;
  accounts?: Array<{
    account_id: string;
    name: string;
    status: string;
    member_ref: string;
    role: string;
    membership_status: string;
    site_count: number;
    sites: Site[];
  }>;
  auth_mode?: string;
  sites: Site[];
  impersonation?: {
    impersonation_id: string;
    read_only: boolean;
    status?: string;
    reason_code?: string;
    reason_text?: string;
    expires_at?: string;
  };
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

export interface PortalMemberSummary {
  member_ref: string;
  email: string;
  auth_mode: string;
  identity_type?: ProductIdentityType;
  allowed_actions?: string[];
  roles: ProductIdentityType[];
  accessible_sites_count: number;
  selected_site_id: string;
  memberships: Array<{
    account_id: string;
    identity_type?: ProductIdentityType;
    allowed_actions?: string[];
    role: string;
    membership_status: string;
    site_count: number;
  }>;
}

export interface PortalMemberPreferences {
  member_ref: string;
  locale: Locale | '';
  currency: 'CNY' | 'USD' | 'HKD';
  updated_at?: string;
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
  locale?: 'en' | 'zh-CN' | 'zh-TW';
}

export interface PortalLoginCodeVerifyRequest {
  email: string;
  code: string;
}

export interface PortalMemberPreferencesUpdateRequest {
  locale: Locale;
  currency: 'CNY' | 'USD' | 'HKD';
}

export interface CreateSiteRequest {
  account_id: string;
  site_name?: string;
  wordpress_url: string;
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
  member_ref: string;
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
  generated_at: string;
}

export interface PortalSiteSummaryRecord {
  site_id: string;
  account_id: string;
  member_ref: string;
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
  member_ref?: string;
  role?: string;
  timezone?: string;
  generated_at?: string;
  windows?: {
    today?: PortalUsageWindow;
    rolling_24h?: PortalUsageWindow;
  };
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
  member_ref?: string;
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
  member_ref?: string;
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
  member_ref?: string;
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

export interface PortalAnalyticsOverview {
  site_id: string;
  account_id?: string;
  member_ref?: string;
  identity_type?: string;
  role?: string;
  tier_id?: string;
  allowed_ranges?: string[];
  selected_range?: string;
  overview?: {
    total_calls: number;
    success_rate: number;
    error_rate: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
    total_cost: number;
    trend_7d: Array<{
      date: string;
      total: number;
      success: number;
      error: number;
    }>;
  };
  generated_at?: string;
}

export interface PortalAnalyticsTrend {
  site_id: string;
  account_id?: string;
  member_ref?: string;
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
  member_ref?: string;
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
  member_ref?: string;
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

export interface PortalSiteBundle {
  summary: PortalSiteSummaryRecord;
  apiKeys: ApiKey[];
}

export interface PortalAnalyticsOverview {
  site_id: string;
  account_id?: string;
  member_ref?: string;
  identity_type?: string;
  role?: string;
  tier_id?: string;
  allowed_ranges?: string[];
  selected_range?: string;
  overview?: {
    total_calls: number;
    success_rate: number;
    error_rate: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
    total_cost: number;
    trend_7d: Array<{
      date: string;
      total: number;
      success: number;
      error: number;
    }>;
  };
  generated_at?: string;
}

export interface PortalAnalyticsTrend {
  site_id: string;
  account_id?: string;
  member_ref?: string;
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
  member_ref?: string;
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
  member_ref?: string;
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
    member_ref: String(record.member_ref || ''),
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
  member_ref: string;
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
    keys_path: string;
    settings_path: string;
  };
}

export interface PortalActivatedSite {
  site_id: string;
  account_id: string;
  member_ref: string;
  role: string;
  site: ProvisionedSiteRecord;
}

export interface PortalUsageBundle {
  usage: PortalUsageSummaryPayload;
  entitlements: Entitlements;
}

export interface PortalAuditBundle {
  summary: PortalAuditSummary;
  events: PortalAuditEvent[];
}

export interface PortalBillingBundle {
  snapshots: PortalBillingSnapshot[];
  reconciliation: PortalBillingReconciliation;
}

export type PortalActionRequestStatus = 'open' | 'acknowledged' | 'resolved' | 'canceled';

export interface PortalActionRequest {
  request_id: string;
  request_type: 'package_change' | 'topup_pack' | 'site_delete' | 'usage_alert' | 'key_expiry' | 'auth_guard' | string;
  account_id: string;
  site_id?: string;
  member_ref: string;
  title: string;
  message?: string;
  status: PortalActionRequestStatus;
  payload?: Record<string, unknown>;
  created_at: string;
  updated_at?: string;
  acknowledged_at?: string;
  resolved_at?: string;
  canceled_at?: string;
}

export interface PortalActionRequestList {
  items: PortalActionRequest[];
  total?: number;
}

export interface PortalPackageChangeRequestPayload {
  target_package: 'free' | 'basic' | 'bulk';
  reason?: string;
  expected_sites?: number;
  expected_usage?: string;
}

export interface PortalTopUpPack {
  pack_id: string;
  label: string;
  points_label: string;
  runs_increment: number;
  tokens_increment: number;
  cost_increment: number;
  recommended_for_tiers: string[];
  display_order: number;
  active: boolean;
}

export interface PortalTopUpPackRequestPayload {
  pack_id: string;
  reason?: string;
  expected_usage?: string;
}

export interface PortalDeleteSiteRequestPayload {
  reason?: string;
  delete_mode?: 'disconnect' | 'delete';
}

export interface PortalUsageAlertThreshold {
  warning: number;
  critical: number;
}

export interface PortalUsageAlertSettings {
  enabled: boolean;
  requests: PortalUsageAlertThreshold;
  tokens: PortalUsageAlertThreshold;
  cost: PortalUsageAlertThreshold;
  updated_at?: string;
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
  private baseUrl: string;
  private token?: string;

  constructor(baseUrl?: string, token?: string) {
    this.baseUrl = baseUrl || getPortalApiBaseUrl();
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
    const url = `${this.baseUrl}${path}`;
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

  async getMemberSummary(): Promise<PortalEnvelope<PortalMemberSummary>> {
    return this.request('GET', '/member-summary', undefined, { requireAuth: true });
  }

  async getMemberPreferences(): Promise<PortalEnvelope<PortalMemberPreferences>> {
    return this.request('GET', '/member-preferences', undefined, { requireAuth: true });
  }

  async updateMemberPreferences(
    payload: PortalMemberPreferencesUpdateRequest
  ): Promise<PortalEnvelope<PortalMemberPreferences>> {
    return this.request('POST', '/member-preferences', payload, { requireAuth: true });
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

  async activateSite(siteId: string): Promise<PortalEnvelope<PortalActivatedSite>> {
    return this.request('POST', `/sites/${siteId}/activate`, {}, { requireAuth: true });
  }

  async archiveSite(siteId: string): Promise<PortalEnvelope<PortalActivatedSite>> {
    return this.request('POST', `/sites/${siteId}/archive`, {}, { requireAuth: true });
  }

  async restoreSite(siteId: string): Promise<PortalEnvelope<PortalActivatedSite>> {
    return this.request('POST', `/sites/${siteId}/restore`, {}, { requireAuth: true });
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

  /**
   * 获取权益信息
   * GET /portal/v1/sites/{siteId}/entitlements
   */
  async getEntitlements(siteId: string): Promise<PortalEnvelope<Entitlements>> {
    return this.request('GET', `/sites/${siteId}/entitlements`, undefined, { requireAuth: true });
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
    member_ref?: string;
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
    const [usageResponse, entitlementsResponse] = await Promise.all([
      this.getUsageSummary(siteId),
      this.getEntitlements(siteId),
    ]);
    return {
      usage: usageResponse.data,
      entitlements: entitlementsResponse.data,
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

  async listNotifications(options?: {
    status?: PortalActionRequestStatus | '';
    limit?: number;
  }): Promise<PortalEnvelope<PortalActionRequestList>> {
    const params = new URLSearchParams();
    if (options?.status !== undefined) params.set('status', options.status);
    if (options?.limit) params.set('limit', String(options.limit));
    const query = params.toString() ? `?${params.toString()}` : '';
    return this.request('GET', `/notifications${query}`, undefined, { requireAuth: true });
  }

  async acknowledgeNotification(notificationId: string): Promise<PortalEnvelope<PortalActionRequest>> {
    return this.request('POST', `/notifications/${notificationId}/ack`, {}, { requireAuth: true });
  }

  async listPackageChangeRequests(siteId: string): Promise<PortalEnvelope<PortalActionRequestList>> {
    return this.request('GET', `/sites/${siteId}/package-change-requests`, undefined, { requireAuth: true });
  }

  async createPackageChangeRequest(
    siteId: string,
    payload: PortalPackageChangeRequestPayload
  ): Promise<PortalEnvelope<PortalActionRequest>> {
    return this.request('POST', `/sites/${siteId}/package-change-requests`, payload, { requireAuth: true });
  }

  async listTopUpPacks(): Promise<PortalEnvelope<{ items: PortalTopUpPack[] }>> {
    return this.request('GET', '/topup-packs', undefined, { requireAuth: true });
  }

  async listTopUpPackRequests(siteId: string): Promise<PortalEnvelope<PortalActionRequestList>> {
    return this.request('GET', `/sites/${siteId}/topup-pack-requests`, undefined, { requireAuth: true });
  }

  async createTopUpPackRequest(
    siteId: string,
    payload: PortalTopUpPackRequestPayload
  ): Promise<PortalEnvelope<PortalActionRequest>> {
    return this.request('POST', `/sites/${siteId}/topup-pack-requests`, payload, { requireAuth: true });
  }

  async createSiteDeleteRequest(
    siteId: string,
    payload: PortalDeleteSiteRequestPayload
  ): Promise<PortalEnvelope<PortalActionRequest>> {
    return this.request('POST', `/sites/${siteId}/delete-requests`, payload, { requireAuth: true });
  }

  async getUsageAlertSettings(siteId: string): Promise<PortalEnvelope<PortalUsageAlertSettings>> {
    return this.request('GET', `/sites/${siteId}/usage-alert-settings`, undefined, { requireAuth: true });
  }

  async updateUsageAlertSettings(
    siteId: string,
    payload: PortalUsageAlertSettings
  ): Promise<PortalEnvelope<PortalUsageAlertSettings>> {
    return this.request('POST', `/sites/${siteId}/usage-alert-settings`, payload, { requireAuth: true });
  }

  async getSiteDiagnostics(siteId: string): Promise<PortalEnvelope<PortalSiteDiagnostics>> {
    return this.request('GET', `/sites/${siteId}/diagnostics`, undefined, { requireAuth: true });
  }

  // ========================================
  // Analytics Dashboard
  // ========================================

  /**
   * 获取 Analytics Overview
   * GET /portal/v1/sites/{siteId}/analytics/overview
   */
  async getAnalyticsOverview(
    siteId: string,
    range: string = '7d'
  ): Promise<PortalEnvelope<PortalAnalyticsOverview>> {
    return this.request('GET', `/sites/${siteId}/analytics/overview?range=${encodeURIComponent(range)}`, undefined, { requireAuth: true });
  }

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
    total_memberships: number;
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
    member_ref?: string;
    expires_before?: string;
    limit?: number;
  }): Promise<PortalEnvelope<{
    items: Array<{
      account_id: string;
      name: string;
      status: string;
      member_count: number;
      site_count: number;
      subscription_count: number;
      top_plan?: string;
      nearest_expiry?: string;
    }>;
    total: number;
  }>> {
    const params = new URLSearchParams();
    if (options?.status) params.set('status', options.status);
    if (options?.member_ref) params.set('member_ref', options.member_ref);
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
    member_count: number;
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
    members: Array<{
      member_ref: string;
      role: string;
      joined_at: string;
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
      member_count: number;
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
    member_count: number;
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
