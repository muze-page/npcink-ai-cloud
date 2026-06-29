'use client';

import React, { useCallback, useEffect, useState, Suspense } from 'react';
import Link from 'next/link';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { ConfirmModal } from '@/components/ui/Modal';
import {
  BackofficeEmptyState,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import {
  resolveCustomerPackageDisplay,
  translateCoverageStateLabel,
  translatePackageKindLabel,
  type CoverageState,
  type PackageKind,
} from '@/lib/customer-package-display';
import { localizePackageAlias } from '@/lib/admin-plan-copy';
import { formatAdminCurrency } from '@/lib/currency';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';
import { translateStatusLabel } from '@/lib/status-display';

interface AccountDetail {
  account_id: string;
  name: string;
  operator_display_name: string;
  operator_note: string;
  account_status_note: string;
  account_status_updated_at: string;
  status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  site_count: number;
  subscription_count: number;
  subscriptions: Array<{
    subscription_id: string;
    status: string;
    plan_id: string;
    plan_version_id?: string;
    current_period_start?: string;
    current_period_end: string;
    package_alias?: string;
    plan_kind?: string;
    display_package_label?: string;
    package_kind?: PackageKind;
    coverage_state?: CoverageState;
  }>;
  sites?: Array<{
    site_id: string;
    status?: string;
    name?: string;
  }>;
}

interface PackagePlanListItem {
  plan?: {
    plan_id?: string;
    name?: string;
    metadata?: Record<string, unknown>;
  };
  latest_version?: {
    plan_version_id?: string;
  } | null;
  tier_summary?: {
    package_alias?: string;
  } | null;
}

type QuickPackageOption = {
  tier_id: 'free' | 'pro' | 'agency';
  plan_id: string;
  plan_version_id: string;
};

const QUICK_PACKAGE_OPTIONS: QuickPackageOption[] = [
  { tier_id: 'free', plan_id: 'free', plan_version_id: 'free_v1' },
  { tier_id: 'pro', plan_id: 'pro', plan_version_id: 'pro_v1' },
  { tier_id: 'agency', plan_id: 'agency', plan_version_id: 'agency_v1' },
];

type TopUpPackOption = {
  pack_id: 'pack_small' | 'pack_medium' | 'pack_large';
  label_key: string;
  fallback_label: string;
  points_label: string;
  ai_credits_increment: number;
  runs_increment: number;
  tokens_increment: number;
  cost_increment: number;
  recommended_for_tiers: Array<'free' | 'pro' | 'agency'>;
};

const TOPUP_PACK_OPTIONS: TopUpPackOption[] = [
  {
    pack_id: 'pack_small',
    label_key: 'admin.account_detail.topup_pack_small',
    fallback_label: 'Small top-up',
    points_label: '10,000 points',
    ai_credits_increment: 10000,
    runs_increment: 10000,
    tokens_increment: 2000000,
    cost_increment: 99,
    recommended_for_tiers: ['free', 'pro'],
  },
  {
    pack_id: 'pack_medium',
    label_key: 'admin.account_detail.topup_pack_medium',
    fallback_label: 'Medium top-up',
    points_label: '35,000 points',
    ai_credits_increment: 35000,
    runs_increment: 35000,
    tokens_increment: 7000000,
    cost_increment: 349,
    recommended_for_tiers: ['pro', 'agency'],
  },
  {
    pack_id: 'pack_large',
    label_key: 'admin.account_detail.topup_pack_large',
    fallback_label: 'Large top-up',
    points_label: '150,000 points',
    ai_credits_increment: 150000,
    runs_increment: 150000,
    tokens_increment: 30000000,
    cost_increment: 1499,
    recommended_for_tiers: ['agency'],
  },
];

type BudgetStateMetric = {
  current_total?: number;
  limit?: number;
  over_limit?: boolean;
};

type SiteRuntimeData = {
  totalRuns: number;
  failedRuns: number;
  lastRunAt: string | null;
  costEstimate: number;
  tokensTotal: number;
  providerCalls: number;
  budgetState: Record<string, BudgetStateMetric>;
  siteLimit: number;
  activeKeyCount: number;
  subscriptionStatus: string;
  coverageState: string;
  packageLabel: string;
};

type AccountBudgetSummary = {
  used: number;
  limit: number;
  remaining: number;
  usageRatio: number;
  overLimit: boolean;
  unlimited: boolean;
};

type AccountQuotaMetric = {
  key: string;
  label?: string;
  used: number;
  limit: number;
  remaining: number;
  usage_ratio: number;
  unlimited: boolean;
  status: string;
  unit: string;
  estimated?: boolean;
  rate_version?: string;
  source?: string;
  limit_source?: string;
};

type AccountCreditBreakdownItem = {
  key: string;
  label?: string;
  quantity: number;
  unit: string;
  rate: number;
  rate_unit?: string;
  credits: number;
};

type AccountQuotaSummary = {
  status: string;
  generated_at?: string;
  period_start_at?: string;
  period_end_at?: string;
  credit: AccountQuotaMetric;
  credit_ledger_summary?: {
    consumed_credits?: number;
    granted_credits?: number;
    adjustment_credits?: number;
    refund_credits?: number;
    net_credit_delta?: number;
    net_used_credits?: number;
  };
  resource_limits: AccountQuotaMetric[];
  internal_limits: AccountQuotaMetric[];
  breakdown: AccountCreditBreakdownItem[];
  totals?: Record<string, number>;
};

type AccountCreditLedgerEntry = {
  ledger_entry_id: string;
  site_id?: string;
  event_type?: string;
  source_type: string;
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
};

type AccountCreditLedger = {
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
    breakdown?: AccountCreditBreakdownItem[];
  };
  items: AccountCreditLedgerEntry[];
};

type PendingConfirmation = {
  title: string;
  message: string;
  confirmLabel: string;
  showSuspendReason?: boolean;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

function selectPrimarySubscription(account: AccountDetail | null): AccountDetail['subscriptions'][number] | null {
  if (!account?.subscriptions.length) {
    return null;
  }
  return (
    account.subscriptions.find((subscription) =>
      ['active', 'trialing', 'past_due', 'suspended'].includes(subscription.status)
    ) || account.subscriptions[0]
  );
}

const MALFORMED_ACCOUNT_TEXT_RE = /Fatal error|Stack trace|Command line code|Uncaught ValueError|Path must not be empty/i;

function prettifyAccountId(accountId: string): string {
  if (MALFORMED_ACCOUNT_TEXT_RE.test(accountId)) {
    return '';
  }
  const stripped = accountId
    .replace(/^acct[_-]?/i, '')
    .replace(/^site[_-]?/i, '')
    .replace(/[_-]+/g, ' ')
    .trim();
  if (!stripped) {
    return accountId;
  }
  return stripped
    .split(/\s+/)
    .map((word) => {
      const lower = word.toLowerCase();
      if (lower === 'ai') return 'AI';
      if (lower === 'api') return 'API';
      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(' ');
}

function resolveAccountTitle(
  account: AccountDetail,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  if (account.operator_display_name.trim()) {
    return account.operator_display_name.trim();
  }
  const rawName = account.name.trim();
  const isRawName =
    !rawName ||
    rawName === account.account_id ||
    /^acct[_-]/i.test(rawName) ||
    MALFORMED_ACCOUNT_TEXT_RE.test(rawName);
  if (!isRawName) {
    return rawName;
  }
  if (MALFORMED_ACCOUNT_TEXT_RE.test(`${account.account_id} ${rawName}`)) {
    return t('admin.accounts.malformed_account_label', undefined, 'Malformed account record');
  }
  return prettifyAccountId(account.account_id) || account.account_id;
}

function emptyBudgetSummary(): AccountBudgetSummary {
  return {
    used: 0,
    limit: 0,
    remaining: 0,
    usageRatio: 0,
    overLimit: false,
    unlimited: true,
  };
}

function summarizeBudget(
  siteRuntimeData: Record<string, SiteRuntimeData>,
  metric: 'runs' | 'tokens' | 'cost'
): AccountBudgetSummary {
  const entries = Object.values(siteRuntimeData);
  if (entries.length === 0) {
    return emptyBudgetSummary();
  }
  const used = entries.reduce(
    (sum, item) => sum + Number(item.budgetState?.[metric]?.current_total ?? 0),
    0
  );
  const positiveLimits = entries
    .map((item) => Number(item.budgetState?.[metric]?.limit ?? 0))
    .filter((value) => value > 0);
  const limit = positiveLimits.reduce((sum, value) => sum + value, 0);
  const unlimited = positiveLimits.length === 0;
  return {
    used,
    limit,
    remaining: unlimited ? 0 : Math.max(0, limit - used),
    usageRatio: unlimited || limit <= 0 ? 0 : used / limit,
    overLimit: entries.some((item) => Boolean(item.budgetState?.[metric]?.over_limit)),
    unlimited,
  };
}

function formatUsageRatio(summary: AccountBudgetSummary, unlimitedLabel = 'Unlimited'): string {
  if (summary.unlimited) {
    return unlimitedLabel;
  }
  return `${Math.round(Math.min(999, Math.max(0, summary.usageRatio * 100)))}%`;
}

function quotaToneClass(summary: AccountBudgetSummary): string | undefined {
  if (summary.overLimit || summary.usageRatio >= 1) {
    return 'text-red-600 dark:text-red-400';
  }
  if (summary.usageRatio >= 0.8) {
    return 'text-amber-700 dark:text-amber-300';
  }
  return undefined;
}

function quotaMetricToneClass(metric?: AccountQuotaMetric | null): string | undefined {
  if (!metric) {
    return undefined;
  }
  if (metric.status === 'limited' || (!metric.unlimited && metric.usage_ratio >= 1)) {
    return 'text-red-600 dark:text-red-400';
  }
  if (metric.status === 'near_limit' || (!metric.unlimited && metric.usage_ratio >= 0.8)) {
    return 'text-amber-700 dark:text-amber-300';
  }
  return undefined;
}

function metricToBudgetSummary(metric?: AccountQuotaMetric | null): AccountBudgetSummary {
  if (!metric) {
    return emptyBudgetSummary();
  }
  return {
    used: Number(metric.used || 0),
    limit: Number(metric.limit || 0),
    remaining: Number(metric.remaining || 0),
    usageRatio: Number(metric.usage_ratio || 0),
    overLimit: metric.status === 'limited' || (!metric.unlimited && Number(metric.used || 0) >= Number(metric.limit || 0)),
    unlimited: Boolean(metric.unlimited),
  };
}

function quotaMetricLabel(
  metric: AccountQuotaMetric,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  const labels: Record<string, string> = {
    ai_credits: t('admin.account_detail.ai_credits_label', undefined, 'AI credits'),
    bound_sites: t('admin.account_detail.bound_sites_label', undefined, 'Bound sites'),
    active_api_key_sites: t('admin.account_detail.active_api_keys_label', undefined, 'Active API keys'),
    concurrent_runs: t('admin.account_detail.concurrent_runs_label', undefined, 'Concurrent runs'),
    batch_items: t('admin.account_detail.batch_items_label', undefined, 'Batch items'),
    vector_documents: t('admin.account_detail.vector_documents_label', undefined, 'Vector articles'),
    vector_chunks: t('admin.account_detail.vector_chunks_label', undefined, 'Vector chunks'),
    vector_sync_documents_per_run: t('admin.account_detail.vector_sync_documents_label', undefined, 'Sync articles/run'),
    vector_sync_chunks_per_run: t('admin.account_detail.vector_sync_chunks_label', undefined, 'Sync chunks/run'),
    tokens: t('admin.tokens_used', undefined, 'Tokens used'),
    cost: t('admin.cost_estimate', undefined, 'Cost estimate'),
    provider_calls: t('admin.account_detail.provider_calls_label', undefined, 'Provider calls'),
  };
  return labels[metric.key] || metric.label || metric.key;
}

function creditBreakdownLabel(
  item: AccountCreditBreakdownItem,
  t: (key: string, vars?: Record<string, string>, fallback?: string) => string
): string {
  const labels: Record<string, string> = {
    runs: t('admin.account_detail.breakdown_runs_label', undefined, 'Hosted runs'),
    tokens_total: t('admin.account_detail.breakdown_tokens_label', undefined, 'Model tokens'),
    web_search: t('admin.account_detail.breakdown_search_label', undefined, 'Search'),
    image_recommendation: t('admin.account_detail.breakdown_image_label', undefined, 'Image recommendation'),
    provider_calls_other: t('admin.account_detail.breakdown_provider_other_label', undefined, 'Other provider calls'),
    vector_documents: t('admin.account_detail.breakdown_vector_documents_label', undefined, 'Vector articles'),
    vector_chunks: t('admin.account_detail.breakdown_vector_chunks_label', undefined, 'Vector chunks'),
  };
  return labels[item.key] || item.label || item.key;
}

function formatSignedCreditDelta(value: number): string {
  const rounded = Math.round(Number(value || 0));
  const formatted = formatInteger(Math.abs(rounded));
  if (rounded > 0) {
    return `+${formatted}`;
  }
  if (rounded < 0) {
    return `-${formatted}`;
  }
  return formatted;
}

function AccountDetailContent() {
  const params = useParams();
  const { t } = useLocale();
  const { accountId } = params as { accountId: string };
  
  const [account, setAccount] = useState<AccountDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSiteId, setSelectedSiteId] = useState('');
  const [accountMetaForm, setAccountMetaForm] = useState({
    operator_display_name: '',
    operator_note: '',
  });
  const [accountMetaNotice, setAccountMetaNotice] = useState<string | null>(null);
  const [accountMetaError, setAccountMetaError] = useState<string | null>(null);
  const [isSavingAccountMeta, setIsSavingAccountMeta] = useState(false);
  const [accountStatusNotice, setAccountStatusNotice] = useState<string | null>(null);
  const [accountStatusError, setAccountStatusError] = useState<string | null>(null);
  const [accountStatusPending, setAccountStatusPending] = useState<'suspend' | 'restore' | null>(null);
  const [suspendReason, setSuspendReason] = useState('');
  const [packageForm, setPackageForm] = useState({
    subscription_id: '',
    plan_id: '',
    plan_version_id: '',
    status: 'active',
    current_period_start_at: '',
    current_period_end_at: '',
  });
  const [packageActionNotice, setPackageActionNotice] = useState<string | null>(null);
  const [packageActionError, setPackageActionError] = useState<string | null>(null);
  const [packageActionPending, setPackageActionPending] = useState<'change' | 'suspend' | 'cancel' | null>(null);
  const [topUpActionPending, setTopUpActionPending] = useState<string | null>(null);
  const [creditAdjustmentForm, setCreditAdjustmentForm] = useState({
    event_type: 'grant',
    credit_delta: '',
    reason: '',
    note: '',
  });
  const [creditAdjustmentPending, setCreditAdjustmentPending] = useState(false);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [packagePlans, setPackagePlans] = useState<PackagePlanListItem[]>([]);
  const [siteRuntimeData, setSiteRuntimeData] = useState<Record<string, SiteRuntimeData>>({});
  const [quotaSummary, setQuotaSummary] = useState<AccountQuotaSummary | null>(null);
  const [creditLedger, setCreditLedger] = useState<AccountCreditLedger | null>(null);
  const [nowMs] = useState(() => Date.now());

  const loadPackagePlans = useCallback(async () => {
    try {
      const response = await fetch('/api/admin/plans', {
        credentials: 'include',
      });
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      setPackagePlans(Array.isArray(data.data?.items) ? (data.data.items as PackagePlanListItem[]) : []);
    } catch {
      setPackagePlans([]);
    }
  }, []);

  const loadSiteRuntimeData = useCallback(async (siteIds: string[]) => {
    if (siteIds.length === 0) {
      setSiteRuntimeData({});
      return;
    }
    const results: Record<string, SiteRuntimeData> = {};
    await Promise.all(
      siteIds.map(async (siteId) => {
        try {
          const response = await fetch(`/api/admin/sites/${encodeURIComponent(siteId)}`, {
            credentials: 'include',
          });
          if (!response.ok) return;
          const data = await response.json();
          const siteData = data.data || {};
          const usageSummary = siteData.usage_summary || {};
          const runtimeSummary = siteData.runtime_summary || {};
          const commercialPolicy = siteData.commercial_policy || {};
          const policyUsageTotals = commercialPolicy.usage_totals || {};
          const budgetState =
            commercialPolicy.budget_state && typeof commercialPolicy.budget_state === 'object'
              ? (commercialPolicy.budget_state as Record<string, BudgetStateMetric>)
              : {};
          const entitlementSnapshot = commercialPolicy.entitlement_snapshot || {};
          const coverage = siteData.coverage || {};
          const siteKeys = Array.isArray(siteData.site_keys) ? siteData.site_keys : [];
          results[siteId] = {
            totalRuns: Number(runtimeSummary.total_runs ?? 0),
            failedRuns: Number(runtimeSummary.failed_runs ?? 0),
            lastRunAt: runtimeSummary.last_run_at || null,
            costEstimate: Number(
              budgetState.cost?.current_total ??
                usageSummary.cost_estimate ??
                policyUsageTotals.cost_usd ??
                0
            ),
            tokensTotal: Number(
              budgetState.tokens?.current_total ??
                usageSummary.tokens_total ??
                policyUsageTotals.tokens_total ??
                0
            ),
            providerCalls: Number(policyUsageTotals.provider_calls ?? 0),
            budgetState,
            siteLimit: Number(entitlementSnapshot.site_limit ?? coverage.site_limit ?? 0),
            activeKeyCount: siteKeys.filter((key: { status?: string }) => key.status === 'active').length,
            subscriptionStatus: String(siteData.subscription?.status || coverage.subscription_status || 'unknown'),
            coverageState: String(coverage.coverage_state || 'unknown'),
            packageLabel: String(coverage.display_package_label || ''),
          };
        } catch {
          results[siteId] = {
            totalRuns: 0,
            failedRuns: 0,
            lastRunAt: null,
            costEstimate: 0,
            tokensTotal: 0,
            providerCalls: 0,
            budgetState: {},
            siteLimit: 0,
            activeKeyCount: 0,
            subscriptionStatus: 'unknown',
            coverageState: 'unknown',
            packageLabel: '',
          };
        }
      })
    );
    setSiteRuntimeData(results);
  }, []);

  const loadQuotaSummary = useCallback(async () => {
    try {
      const response = await fetch(`/api/admin/accounts/${encodeURIComponent(accountId)}/quota-summary`, {
        credentials: 'include',
      });
      if (!response.ok) {
        setQuotaSummary(null);
        return;
      }
      const data = await response.json();
      const payload = data.data || {};
      if (!payload.credit) {
        setQuotaSummary(null);
        return;
      }
      setQuotaSummary({
        status: String(payload.status || 'ok'),
        generated_at: String(payload.generated_at || ''),
        period_start_at: String(payload.period_start_at || ''),
        period_end_at: String(payload.period_end_at || ''),
        credit: payload.credit as AccountQuotaMetric,
        credit_ledger_summary:
          payload.credit_ledger_summary && typeof payload.credit_ledger_summary === 'object'
            ? (payload.credit_ledger_summary as AccountQuotaSummary['credit_ledger_summary'])
            : undefined,
        resource_limits: Array.isArray(payload.resource_limits)
          ? (payload.resource_limits as AccountQuotaMetric[])
          : [],
        internal_limits: Array.isArray(payload.internal_limits)
          ? (payload.internal_limits as AccountQuotaMetric[])
          : [],
        breakdown: Array.isArray(payload.breakdown)
          ? (payload.breakdown as AccountCreditBreakdownItem[])
          : [],
        totals:
          payload.totals && typeof payload.totals === 'object'
            ? (payload.totals as Record<string, number>)
            : {},
      });
    } catch {
      setQuotaSummary(null);
    }
  }, [accountId]);

  const loadCreditLedger = useCallback(async () => {
    try {
      const response = await fetch(`/api/admin/accounts/${encodeURIComponent(accountId)}/credit-ledger?limit=12`, {
        credentials: 'include',
      });
      if (!response.ok) {
        setCreditLedger(null);
        return;
      }
      const data = await response.json();
      const payload = data.data || {};
      setCreditLedger({
        account_id: String(payload.account_id || accountId),
        generated_at: String(payload.generated_at || ''),
        period_start_at: String(payload.period_start_at || ''),
        period_end_at: String(payload.period_end_at || ''),
        rate_version: String(payload.rate_version || ''),
        pagination: payload.pagination || {},
        summary: payload.summary || {},
        items: Array.isArray(payload.items) ? (payload.items as AccountCreditLedgerEntry[]) : [],
      });
    } catch {
      setCreditLedger(null);
    }
  }, [accountId]);

  const loadAccount = useCallback(async (preferredSiteId = '') => {
    setIsLoading(true);
    setError(null);

    try {
      const accountResponse = await fetch(`/api/admin/accounts/${accountId}`, {
        credentials: 'include',
      });

      if (!accountResponse.ok) {
        throw new Error(t('error.failed_load'));
      }

      const data = await accountResponse.json();
      const payload = data.data || {};
      const accountData = payload.account || {};
      const accountMetadata =
        accountData.metadata && typeof accountData.metadata === 'object'
          ? (accountData.metadata as Record<string, unknown>)
          : {};
      const operatorDisplayName = String(accountMetadata.operator_display_name || '').trim();
      const operatorNote = String(accountMetadata.operator_note || '').trim();
      const accountStatusNote = String(accountMetadata.account_status_note || '').trim();
      const accountStatusUpdatedAt = String(accountMetadata.account_status_updated_at || '').trim();
      const sites = Array.isArray(payload.sites) ? payload.sites : [];
      const subscriptions = Array.isArray(payload.subscriptions) ? payload.subscriptions : [];
      const nextAccount: AccountDetail = {
        account_id: String(accountData.account_id || accountId),
        name: String(accountData.name || accountData.account_id || accountId),
        operator_display_name: operatorDisplayName,
        operator_note: operatorNote,
        account_status_note: accountStatusNote,
        account_status_updated_at: accountStatusUpdatedAt,
        status: String(accountData.status || 'unknown'),
        metadata: accountMetadata,
        created_at: String(accountData.created_at || ''),
        site_count: sites.length,
        subscription_count: subscriptions.length,
        sites: sites.map((site: { site_id?: string; status?: string; name?: string }) => ({
          site_id: String(site.site_id || ''),
          status: site.status || 'unknown',
          name: site.name || '',
        })),
        subscriptions: subscriptions.map((item: { subscription?: Record<string, unknown> } | Record<string, unknown>) => {
          const subscription =
            item && typeof item === 'object' && 'subscription' in item
              ? (((item as { subscription?: Record<string, unknown> }).subscription || {}) as Record<string, unknown>)
              : (item as Record<string, unknown>);
          const packageDisplay = resolveCustomerPackageDisplay(t, {
            planId: String(subscription.plan_id || ''),
            packageAlias: String(subscription.package_alias || ''),
            planKind: String(subscription.plan_kind || ''),
            packageKind: String(subscription.package_kind || ''),
            coverageState: String(subscription.coverage_state || ''),
          });
          return {
            subscription_id: String(subscription.subscription_id || ''),
            status: String(subscription.status || 'unknown'),
            plan_id: String(subscription.plan_id || ''),
            plan_version_id: String(subscription.plan_version_id || ''),
            current_period_start: String(subscription.current_period_start_at || ''),
            current_period_end: String(subscription.current_period_end_at || ''),
            package_alias: String(subscription.package_alias || ''),
            plan_kind: String(subscription.plan_kind || ''),
            display_package_label:
              String(subscription.display_package_label || '') || packageDisplay.display_package_label,
            package_kind: packageDisplay.package_kind,
            coverage_state: packageDisplay.coverage_state,
          };
        }),
      };
      setAccount(nextAccount);
      setAccountMetaForm({
        operator_display_name: operatorDisplayName,
        operator_note: operatorNote,
      });
      const defaultSubscription =
        nextAccount.subscriptions.find((subscription) =>
          ['active', 'trialing', 'past_due', 'suspended'].includes(subscription.status)
        ) || nextAccount.subscriptions[0];
      setPackageForm({
        subscription_id: defaultSubscription?.subscription_id || '',
        plan_id: defaultSubscription?.plan_id || '',
        plan_version_id: defaultSubscription?.plan_version_id || '',
        status:
          defaultSubscription?.status && defaultSubscription.status !== 'unknown'
            ? defaultSubscription.status
            : 'active',
        current_period_start_at: defaultSubscription?.current_period_start || '',
        current_period_end_at: defaultSubscription?.current_period_end || '',
      });
      const nextSiteOptions =
        nextAccount?.sites && nextAccount.sites.length > 0
          ? nextAccount.sites.map((site: { site_id: string; status?: string; name?: string }) => ({
              site_id: site.site_id,
              status: site.status || 'unknown',
              name: site.name || '',
            }))
          : [];

      const nextSiteId =
        (preferredSiteId && nextSiteOptions.some((site: { site_id: string }) => site.site_id === preferredSiteId)
          ? preferredSiteId
          : nextSiteOptions[0]?.site_id) || '';

      setSelectedSiteId(nextSiteId);

      const nextSiteIds = nextAccount?.sites?.map((s) => s.site_id).filter(Boolean) || [];
      if (nextSiteIds.length > 0) {
        void loadSiteRuntimeData(nextSiteIds);
      }
      void loadQuotaSummary();
      void loadCreditLedger();
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [accountId, loadCreditLedger, loadQuotaSummary, loadSiteRuntimeData, t]);

  const handleSaveAccountMeta = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!account) {
      return;
    }

    const operatorDisplayName = accountMetaForm.operator_display_name.trim();
    const operatorNote = accountMetaForm.operator_note.trim();
    const metadata = { ...(account.metadata || {}) };
    if (operatorDisplayName) {
      metadata.operator_display_name = operatorDisplayName;
    } else {
      delete metadata.operator_display_name;
    }
    if (operatorNote) {
      metadata.operator_note = operatorNote;
    } else {
      delete metadata.operator_note;
    }

    setIsSavingAccountMeta(true);
    setAccountMetaNotice(null);
    setAccountMetaError(null);
    try {
      const response = await fetch('/api/admin/accounts', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: account.account_id,
          name: account.name || account.account_id,
          status: account.status || 'active',
          metadata,
          bind_default_free: false,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('error.failed_save', {}, 'Failed to save.'));
      }
      setAccount((current) =>
        current
          ? {
              ...current,
              metadata,
              operator_display_name: operatorDisplayName,
              operator_note: operatorNote,
            }
          : current
      );
      setAccountMetaNotice(
        t('admin.account_detail.operator_profile_saved_notice', undefined, 'Operator note has been saved.')
      );
    } catch (err) {
      setAccountMetaError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setIsSavingAccountMeta(false);
    }
  };

  const handleChangePackage = async (quickPackage?: QuickPackageOption) => {
    const selectedPlanId = (quickPackage?.plan_id || packageForm.plan_id).trim();
    const selectedPlanVersionId = (quickPackage?.plan_version_id || packageForm.plan_version_id).trim();
    const selectedTierId = quickPackage?.tier_id || '';
    const selectedPackageAlias = selectedTierId
      ? localizePackageAlias(t, selectedTierId, selectedTierId)
      : selectedPackageOption?.label || '';

    if (!selectedPlanId || !selectedPlanVersionId) {
      setPackageActionError(
        t(
          'admin.account_detail.package_action_missing_fields',
          undefined,
          'A coverage package option and package version are required before changing coverage.'
        )
      );
      return;
    }

    setPackageActionPending('change');
    setPackageActionError(null);
    setPackageActionNotice(null);
    try {
      const response = await fetch(`/api/admin/accounts/${encodeURIComponent(accountId)}/subscription`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subscription_id: packageForm.subscription_id || undefined,
          account_id: accountId,
          plan_id: selectedPlanId,
          plan_version_id: selectedPlanVersionId,
          status:
            packageForm.status === 'canceled' || packageForm.status === 'suspended'
              ? 'active'
              : packageForm.status || 'active',
          current_period_start_at: packageForm.current_period_start_at || null,
          current_period_end_at: packageForm.current_period_end_at || null,
          metadata: {
            source: quickPackage
              ? 'admin_account_detail_quick_package_switch'
              : 'admin_account_detail_package_switch',
            tier_id: selectedTierId || undefined,
            package_alias: selectedPackageAlias || undefined,
          },
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('error.failed_save', {}, 'Failed to save.'));
      }
      setPackageActionNotice(
        t(
          'admin.account_detail.package_changed_notice',
          undefined,
          quickPackage
            ? `Customer package coverage has been switched to ${selectedPackageAlias}.`
            : 'Customer package coverage has been updated.'
        )
      );
      await loadAccount(selectedSiteId);
    } catch (err) {
      setPackageActionError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save'))
      );
    } finally {
      setPackageActionPending(null);
    }
  };

  const handleCoverageMutation = async (action: 'suspend' | 'cancel') => {
    setPackageActionPending(action);
    setPackageActionError(null);
    setPackageActionNotice(null);
    try {
      const response = await fetch(
        `/api/admin/accounts/${encodeURIComponent(accountId)}/subscription/${action}`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('error.failed_save', {}, 'Failed to save.'));
      }
      setPackageActionNotice(
        action === 'suspend'
          ? t(
              'admin.account_detail.coverage_suspended_notice',
              undefined,
              'Customer coverage has been suspended.'
            )
          : t(
              'admin.account_detail.coverage_canceled_notice',
              undefined,
              'Customer coverage has been canceled.'
            )
      );
      await loadAccount(selectedSiteId);
    } catch (err) {
      setPackageActionError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save'))
      );
    } finally {
      setPackageActionPending(null);
    }
  };

  const handleAccountStatusMutation = async (action: 'suspend' | 'restore') => {
    if (!account) {
      return;
    }
    setAccountStatusPending(action);
    setAccountStatusNotice(null);
    setAccountStatusError(null);
    try {
      const response = await fetch(`/api/admin/accounts/${encodeURIComponent(account.account_id)}/${action}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reason: action === 'suspend' ? suspendReason.trim() : '',
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('error.failed_save', {}, 'Failed to save.'));
      }
      const nextStatus = String(payload.data?.status || (action === 'restore' ? 'active' : 'suspended'));
      const metadata = payload.data?.metadata && typeof payload.data.metadata === 'object'
        ? payload.data.metadata
        : {};
      setAccount((current) =>
        current
          ? {
              ...current,
              status: nextStatus,
              account_status_note: String(metadata.account_status_note || current.account_status_note || ''),
              account_status_updated_at: String(metadata.account_status_updated_at || current.account_status_updated_at || ''),
            }
          : current
      );
      setAccountStatusNotice(
        action === 'restore'
          ? t('admin.accounts.account_restored_notice', { account: accountTitle }, `${accountTitle} has been restored.`)
          : t('admin.accounts.account_suspended_notice', { account: accountTitle }, `${accountTitle} has been suspended.`)
      );
      await loadAccount(selectedSiteId);
    } catch (err) {
      setAccountStatusError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setAccountStatusPending(null);
      setSuspendReason('');
    }
  };

  const handleApplyTopUpPack = async (pack: TopUpPackOption) => {
    const subscriptionId = packageForm.subscription_id || selectPrimarySubscription(account)?.subscription_id || '';
    if (!subscriptionId) {
      setPackageActionError(
        t(
          'admin.account_detail.topup_missing_subscription',
          undefined,
          'A current subscription is required before applying a top-up pack.'
        )
      );
      return;
    }

    setTopUpActionPending(pack.pack_id);
    setPackageActionError(null);
    setPackageActionNotice(null);
    try {
      const response = await fetch(`/api/admin/subscriptions/${encodeURIComponent(subscriptionId)}/topup`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          target_period_start_at: packageForm.current_period_start_at || null,
          target_period_end_at: packageForm.current_period_end_at || null,
          ai_credits_increment: pack.ai_credits_increment,
          runs_increment: pack.runs_increment,
          tokens_increment: pack.tokens_increment,
          cost_increment: pack.cost_increment,
          reason: 'operator_overage_buffer',
          note: `Applied ${pack.pack_id} from account coverage screen.`,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('error.failed_save', {}, 'Failed to save.'));
      }
      setPackageActionNotice(
        t(
          'admin.account_detail.topup_pack_applied_notice',
          { pack: t(pack.label_key, undefined, pack.fallback_label) },
          `${pack.fallback_label} has been applied to the current period.`
        )
      );
      await loadAccount(selectedSiteId);
    } catch (err) {
      setPackageActionError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save'))
      );
    } finally {
      setTopUpActionPending(null);
    }
  };

  const handleApplyCreditAdjustment = async () => {
    const creditDelta = Number(creditAdjustmentForm.credit_delta);
    if (!Number.isFinite(creditDelta) || creditDelta === 0) {
      setPackageActionError(
        t(
          'admin.account_detail.credit_adjustment_delta_required',
          undefined,
          'Enter a non-zero AI credit delta.'
        )
      );
      return;
    }
    if (!creditAdjustmentForm.reason.trim()) {
      setPackageActionError(
        t(
          'admin.account_detail.credit_adjustment_reason_required',
          undefined,
          'Enter an operator reason before applying the credit adjustment.'
        )
      );
      return;
    }

    setCreditAdjustmentPending(true);
    setPackageActionError(null);
    setPackageActionNotice(null);
    try {
      const response = await fetch(
        `/api/admin/accounts/${encodeURIComponent(accountId)}/credit-ledger/adjustments`,
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': crypto.randomUUID(),
          },
          body: JSON.stringify({
            event_type: creditAdjustmentForm.event_type,
            credit_delta: creditDelta,
            reason: creditAdjustmentForm.reason.trim(),
            note: creditAdjustmentForm.note.trim(),
          }),
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('error.failed_save', {}, 'Failed to save.'));
      }
      setPackageActionNotice(
        t(
          'admin.account_detail.credit_adjustment_applied_notice',
          undefined,
          'AI credit adjustment has been written to the current ledger period.'
        )
      );
      setCreditAdjustmentForm((current) => ({
        event_type: current.event_type,
        credit_delta: '',
        reason: '',
        note: '',
      }));
      await Promise.all([loadAccount(selectedSiteId), loadQuotaSummary(), loadCreditLedger()]);
    } catch (err) {
      setPackageActionError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save'))
      );
    } finally {
      setCreditAdjustmentPending(false);
    }
  };

  useEffect(() => {
    void loadAccount();
    void loadPackagePlans();
  }, [loadAccount, loadPackagePlans]);

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <div className="animate-spin text-4xl mb-4">⏳</div>
          <p className="text-gray-600 dark:text-gray-400">{t('common.loading')}</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center max-w-md">
          <h2 className="text-2xl font-bold mb-4 text-red-600">{t('common.error')}</h2>
          <p className="text-gray-600 dark:text-gray-400 mb-6">{error}</p>
          <button onClick={() => window.location.reload()} className="btn btn-primary">{t('common.retry')}</button>
        </div>
      </div>
    );
  }

  if (!account) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="text-center">
          <h2 className="text-2xl font-bold mb-4">{t('admin.account_not_found')}</h2>
          <Link href="/admin/accounts" className="text-blue-600 hover:underline">
            ← {t('admin.back_to_accounts')}
          </Link>
        </div>
      </div>
    );
  }

  const siteOptions = account.sites && account.sites.length > 0
    ? account.sites.map((site) => ({
        site_id: site.site_id,
        status: site.status || 'unknown',
        name: site.name || '',
      }))
    : [];
  const siteRuntimeItems = Object.values(siteRuntimeData);
  const resourceMetricByKey = new Map((quotaSummary?.resource_limits || []).map((item) => [item.key, item]));
  const creditMetric = quotaSummary?.credit || null;
  const runBudgetSummary = creditMetric ? metricToBudgetSummary(creditMetric) : summarizeBudget(siteRuntimeData, 'runs');
  const activeKeySiteCount = siteRuntimeItems.filter((item) => item.activeKeyCount > 0).length;
  const boundSitesMetric = resourceMetricByKey.get('bound_sites') || null;
  const vectorDocumentsMetric = resourceMetricByKey.get('vector_documents') || null;
  const concurrentRunsMetric = resourceMetricByKey.get('concurrent_runs') || null;
  const siteLimitValues = siteRuntimeItems.map((item) => Number(item.siteLimit || 0)).filter((value) => value > 0);
  const accountSiteLimit = boundSitesMetric && !boundSitesMetric.unlimited
    ? Number(boundSitesMetric.limit || 0)
    : siteLimitValues.length > 0
      ? Math.max(...siteLimitValues)
      : 0;
  const siteLimitUnlimited = accountSiteLimit <= 0;
  const siteUsageRatio = boundSitesMetric
    ? Number(boundSitesMetric.usage_ratio || 0)
    : siteLimitUnlimited
      ? 0
      : account.site_count / accountSiteLimit;
  const hasSiteLimitPressure = !siteLimitUnlimited && siteUsageRatio >= 0.8;
  const hasApiKeyGap = account.site_count > 0 && activeKeySiteCount < account.site_count;
  const quotaNeedsAttention =
    quotaSummary?.status === 'limited' ||
    quotaSummary?.status === 'near_limit' ||
    runBudgetSummary.overLimit ||
    runBudgetSummary.usageRatio >= 0.8 ||
    hasSiteLimitPressure ||
    hasApiKeyGap;

  const riskySubscriptions = account.subscriptions.filter((sub) => sub.status !== 'active');
  const primarySubscription = selectPrimarySubscription(account);
  const primaryPackage = resolveCustomerPackageDisplay(t, {
    planId: primarySubscription?.plan_id,
    packageAlias: primarySubscription?.package_alias,
    planKind: primarySubscription?.plan_kind,
    packageKind: primarySubscription?.package_kind,
    coverageState: primarySubscription?.coverage_state || (primarySubscription ? 'covered' : 'uncovered'),
  });
  const expiringSubscriptions = account.subscriptions.filter((sub) => {
    if (!sub.current_period_end) {
      return false;
    }
    const diff = new Date(sub.current_period_end).getTime() - nowMs;
    return diff >= 0 && diff <= 1000 * 60 * 60 * 24 * 30;
  });
  const uncoveredSiteCount =
    primaryPackage.coverage_state === 'uncovered' && account.site_count > 0 ? account.site_count : 0;
  const hasCoverageGap = uncoveredSiteCount > 0;
  const hasUncoveredCommercialPosture =
    primaryPackage.coverage_state === 'uncovered' || hasCoverageGap || (account.subscription_count === 0 && account.site_count > 0);
  const hasDevBaselineOnly = primaryPackage.package_kind === 'dev_baseline';
  const hasPaidCoverage =
    primaryPackage.package_kind === 'tier_package' && primaryPackage.coverage_state === 'covered';
  const hasFormalFreeCoverage =
    primaryPackage.package_kind === 'formal_free' && primaryPackage.coverage_state === 'covered';
  const postureTone =
    account.status === 'suspended' || riskySubscriptions.length > 0 || hasUncoveredCommercialPosture || hasDevBaselineOnly
      ? 'error'
      : 'ok';
  const postureTitle = (() => {
    if (account.status === 'suspended') {
      return t('admin.account_detail.suspended_title', undefined, 'Customer access is suspended');
    }
    if (hasDevBaselineOnly) {
      return t('admin.account_detail.dev_baseline_only_title', undefined, 'Dev baseline only');
    }
    if (hasUncoveredCommercialPosture) {
      return t('admin.account_detail.uncovered_posture_title', undefined, 'Uncovered commercial posture');
    }
    if (riskySubscriptions.length > 0) {
      return t('admin.account_detail.commercial_risk_title', undefined, 'Subscription follow-up is required');
    }
    if (hasFormalFreeCoverage) {
      return t('admin.account_detail.free_covered_title', undefined, 'Free but covered');
    }
    if (hasPaidCoverage) {
      return t('admin.account_detail.paid_covered_title', undefined, 'Covered by paid package');
    }
    return t('admin.account_detail.healthy_title', undefined, 'Customer posture is stable');
  })();
  const postureDescription = (() => {
    if (account.status === 'suspended') {
      return t('admin.account_detail.suspended_desc', undefined, 'Commercial or support review should happen before any new customer session starts from this customer.');
    }
    if (hasDevBaselineOnly) {
      return t('admin.account_detail.dev_baseline_only_desc', undefined, 'This customer currently resolves to a dev baseline. Do not treat it as production package coverage until an operator rebinds it.');
    }
    if (hasUncoveredCommercialPosture) {
      return t('admin.account_detail.uncovered_posture_desc', undefined, 'This customer has real uncovered posture. Keep it distinct from Free coverage and move directly into subscription/package follow-up.');
    }
    if (riskySubscriptions.length > 0) {
      return t('admin.account_detail.commercial_risk_desc', undefined, 'Subscription lifecycle is the main blocker; resolve coverage before treating this customer as stable.');
    }
    if (hasFormalFreeCoverage) {
      return t('admin.account_detail.free_covered_desc', undefined, 'This customer is explicitly covered by the formal Free package. Treat it as covered posture, not implicit fallback.');
    }
    if (hasPaidCoverage) {
      return t('admin.account_detail.paid_covered_desc', undefined, 'This customer is covered by a paid package. Use the current subscription record for package changes, suspension, or cancellation.');
    }
    return t('admin.account_detail.healthy_desc', undefined, 'Commercial coverage and site footprint are readable from this surface.');
  })();
  const nextStepDescription = account.status === 'suspended'
    ? t('admin.account_detail.next_step_suspended_desc', undefined, 'Keep support actions bounded until you confirm why the customer is suspended.')
    : primarySubscription && riskySubscriptions[0]
      ? t('admin.account_detail.next_step_subscription_desc', undefined, 'Coverage posture still needs operator attention. Use the bounded actions on this page before opening any deeper commercial detail.')
      : hasUncoveredCommercialPosture
        ? t('admin.account_detail.open_subscription_queue_desc', undefined, 'This customer has site footprint without readable package coverage, so keep the next decision on customer coverage and site impact first.')
        : t('admin.account_detail.open_primary_site_desc', undefined, 'The customer is stable; only open a site when you need lower-level runtime, key, or support detail.');
  const watchItems = [
    {
      label: t('common.package', undefined, 'Package'),
      value: primaryPackage.display_package_label,
      detail: `${translatePackageKindLabel(t, primaryPackage.package_kind)} · ${translateCoverageStateLabel(t, primaryPackage.coverage_state)}`,
      toneClassName:
        primaryPackage.coverage_state === 'uncovered' || primaryPackage.package_kind === 'dev_baseline'
          ? 'text-red-600 dark:text-red-400'
          : undefined,
    },
    {
      label: t('common.subscriptions'),
      value: riskySubscriptions.length > 0
        ? t('admin.account_detail.subscriptions_attention_value', { count: String(riskySubscriptions.length) }, `${riskySubscriptions.length} need follow-up`)
        : translateStatusLabel('ok', t),
      detail: expiringSubscriptions.length > 0
        ? t('admin.account_detail.expiring_subscriptions_desc', { count: String(expiringSubscriptions.length) }, `${expiringSubscriptions.length} renew within 30 days.`)
        : t('admin.account_detail.subscriptions_stable_desc', undefined, 'No expiring or unhealthy subscriptions are visible from this customer surface.'),
      toneClassName: riskySubscriptions.length > 0 ? 'text-red-600 dark:text-red-400' : undefined,
    },
    {
      label: t('common.sites'),
      value: formatInteger(account.site_count),
      detail: hasCoverageGap
        ? t('admin.account_detail.site_coverage_gap_desc', undefined, 'One or more sites exist without matching active subscription coverage.')
        : t('admin.account_detail.site_coverage_ready_desc', undefined, 'Site footprint is attached to current subscription coverage.'),
      toneClassName: hasCoverageGap ? 'text-red-600 dark:text-red-400' : undefined,
    },
  ];
  const quotaRecommendationItems = [
    runBudgetSummary.overLimit || runBudgetSummary.usageRatio >= 0.8
      ? t(
          'admin.account_detail.recommend_topup_runs',
          undefined,
          'Apply a top-up pack or move this account to a higher package before more AI credits are consumed.'
        )
      : '',
    hasSiteLimitPressure
      ? t(
          'admin.account_detail.recommend_site_limit',
          undefined,
          'Confirm the package site limit before binding another WordPress site to this customer.'
        )
      : '',
    hasApiKeyGap
      ? t(
          'admin.account_detail.recommend_key_gap',
          undefined,
          'Issue or restore active Cloud API key coverage for every bound site before trial traffic.'
        )
      : '',
    !quotaNeedsAttention
      ? t(
          'admin.account_detail.recommend_quota_stable',
          undefined,
          'Current quota posture is healthy. Keep this page as the account-level checkpoint before opening site detail.'
        )
      : '',
  ].filter(Boolean);
  const unlimitedLabel = t('common.unlimited', {}, 'Unlimited');
  const formatQuotaMetricValue = (metric: AccountQuotaMetric): string => {
    if (metric.unit === 'usd') {
      return formatAdminCurrency(metric.used);
    }
    return formatInteger(Math.round(Number(metric.used || 0)));
  };
  const formatQuotaMetricLimit = (metric: AccountQuotaMetric): string => {
    if (metric.unlimited) {
      return unlimitedLabel;
    }
    if (metric.unit === 'usd') {
      return formatAdminCurrency(metric.limit);
    }
    return formatInteger(Math.round(Number(metric.limit || 0)));
  };
  const quotaRows = [
    {
      key: 'ai-credits',
      label: t('admin.account_detail.ai_credits_label', undefined, 'AI credits'),
      used: formatInteger(Math.round(runBudgetSummary.used)),
      limit: runBudgetSummary.unlimited ? unlimitedLabel : formatInteger(Math.round(runBudgetSummary.limit)),
      remaining: runBudgetSummary.unlimited
        ? unlimitedLabel
        : formatInteger(Math.round(runBudgetSummary.remaining)),
      ratio: formatUsageRatio(runBudgetSummary, unlimitedLabel),
      detail: t(
        'admin.account_detail.ai_credits_desc',
        undefined,
        'Run budget for the current subscription period.'
      ),
      summary: runBudgetSummary,
    },
  ];
  const resourceRows = quotaSummary?.resource_limits || [];
  const internalLimitRows = quotaSummary?.internal_limits || [];
  const creditLedgerItems = creditLedger?.items || [];
  const creditLedgerNetUsed = Number(
    creditLedger?.summary?.net_used_credits ??
      quotaSummary?.credit_ledger_summary?.net_used_credits ??
      creditLedger?.summary?.total_credits ??
      0
  );
  const creditLedgerGranted = Number(
    creditLedger?.summary?.granted_credits ?? quotaSummary?.credit_ledger_summary?.granted_credits ?? 0
  );
  const creditLedgerCount = Number(creditLedger?.pagination?.total ?? creditLedger?.summary?.entry_count ?? 0);
  const siteLimitLabel = siteLimitUnlimited ? unlimitedLabel : formatInteger(accountSiteLimit);
  const packagePlanOptions = packagePlans
    .filter((item) => item.plan?.plan_id)
    .map((item) => {
      const packageDisplay = resolveCustomerPackageDisplay(t, {
        planId: item.plan?.plan_id,
        packageAlias:
          String(item.plan?.metadata?.package_alias || '') ||
          String(item.tier_summary?.package_alias || ''),
        formalPlanName: item.plan?.name,
        planKind: String(item.plan?.metadata?.plan_kind || ''),
      });
      return {
        plan_id: String(item.plan?.plan_id || ''),
        plan_version_id: String(item.latest_version?.plan_version_id || ''),
        label: packageDisplay.display_package_label,
      };
    });
  const selectedPackageOption = packagePlanOptions.find((item) => item.plan_id === packageForm.plan_id) || null;
  const currentTierId =
    primarySubscription?.package_alias === 'Free' || primarySubscription?.plan_id === 'free'
      ? 'free'
      : primarySubscription?.package_alias === 'Agency' || primarySubscription?.plan_id === 'agency'
        ? 'agency'
        : 'pro';
  const accountTitle = resolveAccountTitle(account, t);
  const showPostureBadge = postureTone !== 'ok';
  const showAccountStatusBadge = account.status !== 'active' && account.status !== 'unknown';
  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.account_posture')}
        title={accountTitle}
        description={postureDescription}
	        actions={(
	          <>
	            <a href="#coverage-actions" className="btn btn-primary">
	              {t('admin.account_detail.manage_package_action', undefined, 'Manage package')}
	            </a>
	            <Link href="/admin/accounts" className="btn btn-secondary">
	              {t('admin.back_to_accounts')}
	            </Link>
          </>
        )}
        aside={(
          <div className="w-full xl:w-[46rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('common.sites'), value: formatInteger(account.site_count), size: 'compact' },
                {
                  label: t('common.status'),
                  value: translateStatusLabel(account.status, t),
                  size: 'compact',
                },
                {
                  label: t('common.subscriptions'),
                  value: formatInteger(account.subscription_count),
                  toneClassName: riskySubscriptions.length > 0 ? 'text-red-600 dark:text-red-400' : undefined,
                  size: 'compact',
                },
                {
                  label: t('admin.no_commercial_coverage', undefined, 'No commercial coverage'),
                  value: formatInteger(uncoveredSiteCount),
                  toneClassName: uncoveredSiteCount > 0 ? 'text-red-600 dark:text-red-400' : undefined,
                  size: 'compact',
                },
                {
                  label: t('admin.expiring_soon', undefined, 'Expiring Soon'),
                  value: formatInteger(expiringSubscriptions.length),
                  toneClassName: expiringSubscriptions.length > 0 ? 'text-amber-700 dark:text-amber-300' : undefined,
                  size: 'compact',
                },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-5"
            />
          </div>
        )}
      >
	        <div className="flex flex-wrap items-center gap-2">
	          <BackofficeIdentifier value={account.account_id} className="text-xs text-gray-500 dark:text-gray-400" />
	          {showPostureBadge ? (
	            <BackofficeStatusBadge status={postureTone} label={translateStatusLabel(postureTone, t)} />
          ) : null}
          {showAccountStatusBadge ? (
	            <BackofficeStatusBadge status={account.status} label={translateStatusLabel(account.status, t)} />
	          ) : null}
	        </div>
	        <BackofficeStackCard className="flex flex-col gap-4 bg-white/80 dark:bg-slate-950/55 lg:flex-row lg:items-center lg:justify-between">
	          <div>
	            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
	              {t('admin.account_detail.access_status_title', undefined, 'Customer access status')}
	            </p>
	            <div className="mt-2 flex flex-wrap items-center gap-2">
	              <BackofficeStatusBadge status={account.status} label={translateStatusLabel(account.status, t)} />
	              <span className="text-sm text-slate-600 dark:text-slate-300">
	                {account.status === 'suspended'
	                  ? t(
	                      'admin.account_detail.access_status_suspended_desc',
	                      undefined,
	                      'Portal access and site actions are currently blocked for this customer.'
	                    )
	                  : t(
	                      'admin.account_detail.access_status_active_desc',
	                      undefined,
	                      'Portal access follows this customer record and related site grants.'
	                    )}
	              </span>
	            </div>
	          </div>
	          <button
	            type="button"
	            onClick={() => {
	              setSuspendReason('');
	              setPendingConfirmation({
	                title:
	                  account.status === 'suspended'
	                    ? t('admin.accounts.confirm_restore_title', {}, 'Confirm account restore')
	                    : t('admin.accounts.confirm_suspend_title', {}, 'Confirm account suspension'),
	                message:
	                  account.status === 'suspended'
	                    ? t(
	                        'admin.accounts.confirm_restore_desc',
	                        { account: accountTitle },
	                        `Restore ${accountTitle} to active access?`
	                      )
	                    : t(
	                        'admin.accounts.confirm_suspend_desc',
	                        { account: accountTitle },
	                        `Suspend ${accountTitle}? Customer portal access and site actions will be blocked by account status.`
	                      ),
	                confirmLabel:
	                  account.status === 'suspended'
	                    ? t('admin.accounts.restore_account_action', {}, 'Restore account')
	                    : t('admin.accounts.suspend_account_action', {}, 'Suspend account'),
	                showSuspendReason: account.status !== 'suspended',
	                variant: account.status === 'suspended' ? 'default' : 'danger',
	                onConfirm: () => void handleAccountStatusMutation(account.status === 'suspended' ? 'restore' : 'suspend'),
	              });
	            }}
	            className={cn(
	              'btn btn-secondary self-start lg:self-auto',
	              account.status !== 'suspended' && 'border-amber-200 text-amber-700 hover:border-amber-300 dark:border-amber-900/60 dark:text-amber-200'
	            )}
	            disabled={accountStatusPending !== null}
	          >
	            {accountStatusPending
	              ? t('common.saving', {}, 'Saving...')
	              : account.status === 'suspended'
	                ? t('admin.accounts.restore_account_action', {}, 'Restore account')
	                : t('admin.accounts.suspend_account_action', {}, 'Suspend account')}
	          </button>
	        </BackofficeStackCard>
	        {accountStatusNotice ? (
	          <p className="text-sm text-emerald-700 dark:text-emerald-300">{accountStatusNotice}</p>
	        ) : null}
        {accountStatusError ? (
          <p className="text-sm text-red-600 dark:text-red-300">{accountStatusError}</p>
        ) : null}
        {account.account_status_note ? (
          <p className="text-sm text-amber-700 dark:text-amber-300">
            {t('admin.accounts.suspend_reason_label', {}, 'Suspension reason')}: {account.account_status_note}
          </p>
        ) : null}
        <details
          data-ui="operator-profile-editor"
          className="rounded-lg border border-slate-200/80 bg-white/75 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/40"
        >
          <summary className="cursor-pointer list-none text-sm font-semibold text-slate-800 dark:text-slate-100">
            {t('admin.account_detail.edit_operator_profile', undefined, 'Edit customer info')}
            <span className="ml-3 font-normal text-slate-500 dark:text-slate-400">
              {t(
                'admin.account_detail.operator_profile_desc',
                undefined,
                'Internal display name and note; user workspace is not affected.'
              )}
            </span>
          </summary>
          <form
            onSubmit={handleSaveAccountMeta}
            className="mt-4 grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto] md:items-end"
          >
            <label className="text-sm">
              <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                {t('admin.accounts.operator_display_name_label', {}, 'Operator name')}
              </span>
              <input
                type="text"
                value={accountMetaForm.operator_display_name}
                onChange={(event) =>
                  setAccountMetaForm((current) => ({ ...current, operator_display_name: event.target.value }))
                }
                placeholder={accountTitle}
                className="input"
              />
            </label>
            <label className="text-sm">
              <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                {t('admin.accounts.operator_note_label', {}, 'Operator note')}
              </span>
              <input
                type="text"
                value={accountMetaForm.operator_note}
                onChange={(event) => setAccountMetaForm((current) => ({ ...current, operator_note: event.target.value }))}
                placeholder={t('admin.accounts.operator_note_placeholder', {}, 'Internal follow-up note')}
                className="input"
              />
            </label>
            <button type="submit" className="btn btn-secondary whitespace-nowrap" disabled={isSavingAccountMeta}>
              {isSavingAccountMeta ? t('common.saving', {}, 'Saving...') : t('common.save', {}, 'Save')}
            </button>
            {accountMetaNotice ? (
              <p className="text-sm text-emerald-700 dark:text-emerald-300 md:col-span-3">{accountMetaNotice}</p>
            ) : null}
            {accountMetaError ? (
              <p className="text-sm text-red-600 dark:text-red-300 md:col-span-3">{accountMetaError}</p>
            ) : null}
          </form>
        </details>
        <div className="grid gap-4 xl:grid-cols-[0.9fr_1.1fr]">
          <div id="coverage-actions">
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.account_detail.current_coverage_title', undefined, 'Current coverage')}
            </p>
            <h3 className="mt-3 text-lg font-semibold text-gray-950 dark:text-white">{postureTitle}</h3>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">{nextStepDescription}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="rounded-full border border-slate-200/80 bg-slate-50 px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
                {primaryPackage.display_package_label}
              </span>
              <span className="rounded-full border border-slate-200/80 bg-white px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-slate-700 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-200">
                {translatePackageKindLabel(t, primaryPackage.package_kind)}
              </span>
              <span
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-[0.16em]',
                  primaryPackage.coverage_state === 'covered'
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200'
                    : 'border-red-200 bg-red-50 text-red-700 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-200'
                )}
              >
                {translateCoverageStateLabel(t, primaryPackage.coverage_state)}
              </span>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm dark:border-gray-800 dark:bg-slate-950/60">
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                  {t('common.status')}
                </p>
                <div className="mt-2">
                  <BackofficeStatusBadge
                    status={primarySubscription?.status || 'unknown'}
                    label={translateStatusLabel(primarySubscription?.status || 'unknown', t)}
                  />
                </div>
              </div>
              <div className="rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm dark:border-gray-800 dark:bg-slate-950/60">
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                  {t('admin.period_end')}
                </p>
                <p className="mt-2 font-medium text-gray-950 dark:text-white">
                  {primarySubscription?.current_period_end ? formatDate(primarySubscription.current_period_end) : t('common.not_found')}
                </p>
              </div>
              <div className="rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm dark:border-gray-800 dark:bg-slate-950/60">
                <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                  {t('admin.account_detail.next_step_label', undefined, 'Next focus')}
                </p>
                <p className="mt-2 font-medium text-gray-950 dark:text-white">
                  {hasCoverageGap
                    ? t('admin.account_detail.next_focus_coverage', undefined, 'Customer coverage and site impact')
                    : t('admin.account_detail.next_focus_sites', undefined, 'Site footprint and runtime detail')}
                </p>
              </div>
            </div>
          </BackofficeStackCard>
          </div>
          <BackofficeStackCard>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.account_detail.package_actions_eyebrow', undefined, 'Package actions')}
            </p>
            <h3 className="mt-3 text-lg font-semibold text-gray-950 dark:text-white">
              {t('admin.account_detail.package_actions_title', undefined, 'Package and top-up')}
            </h3>
            <p className="mt-2 text-sm text-gray-600 dark:text-gray-300">
              {t(
                'admin.account_detail.package_actions_desc',
                undefined,
                'Change the customer package or add current-period headroom from this primary operation area.'
              )}
            </p>
            <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/30">
              <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-700 dark:text-slate-300">
                    {t('admin.account_detail.change_customer_package_label', undefined, 'Change customer package')}
                  </p>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                    {t(
                      'admin.account_detail.change_customer_package_desc',
                      undefined,
                      'Switch this account to Free, Pro, or Agency. User workspace stays read-only.'
                    )}
                  </p>
                </div>
                <BackofficeStatusBadge status="ok" label={t('admin.operator_managed', {}, 'Operator managed')} />
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                {QUICK_PACKAGE_OPTIONS.map((option) => {
                  const label = localizePackageAlias(t, option.tier_id, option.tier_id);
                  const isCurrent =
                    primarySubscription?.plan_id === option.plan_id ||
                    primarySubscription?.plan_version_id === option.plan_version_id ||
                    primaryPackage.display_package_label === label;
                  return (
                    <button
                      key={option.tier_id}
                      type="button"
                      onClick={() =>
                        setPendingConfirmation({
                          title: t('admin.account_detail.confirm_package_change_title', undefined, 'Confirm package change'),
                          message: t(
                            'admin.account_detail.confirm_package_change_desc',
                            { package: label, account: account.name || account.account_id },
                            `Change ${account.name || account.account_id} to ${label}? This updates the customer package immediately.`
                          ),
                          confirmLabel: t('admin.account_detail.confirm_package_change_action', undefined, 'Change package'),
                          onConfirm: () => void handleChangePackage(option),
                        })
                      }
                      className={cn(
                        'rounded-2xl border px-4 py-3 text-left text-sm transition',
                        isCurrent
                          ? 'border-emerald-300 bg-white text-emerald-800 dark:border-emerald-800 dark:bg-slate-950/60 dark:text-emerald-200'
                          : 'border-slate-200 bg-white text-slate-800 hover:border-slate-400 dark:border-slate-800 dark:bg-slate-950/60 dark:text-slate-100'
                      )}
                      disabled={packageActionPending !== null}
                    >
                      <span className="block font-semibold">{label}</span>
                      <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">
                        {isCurrent
                          ? t('common.current', {}, 'Current')
                          : t('admin.account_detail.apply_package_action', undefined, 'Apply package')}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="mt-5 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/45">
              <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-700 dark:text-slate-300">
                    {t('admin.account_detail.topup_packs_label', undefined, 'Top-up packs')}
                  </p>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                    {t(
                      'admin.account_detail.topup_packs_desc',
                      undefined,
                      'Add temporary current-period headroom without changing the customer package.'
                    )}
                  </p>
                </div>
                <BackofficeStatusBadge status="warning" label={t('admin.current_period_only', {}, 'Current period only')} />
              </div>
              <div className="mt-4 grid gap-2 sm:grid-cols-3">
                {TOPUP_PACK_OPTIONS.map((pack) => {
                  const label = t(pack.label_key, undefined, pack.fallback_label);
                  const isRecommended = pack.recommended_for_tiers.includes(currentTierId);
                  return (
                    <button
                      key={pack.pack_id}
                      type="button"
                      onClick={() =>
                        setPendingConfirmation({
                          title: t('admin.account_detail.confirm_topup_title', undefined, 'Confirm top-up pack'),
                          message: t(
                            'admin.account_detail.confirm_topup_desc',
                            { pack: label, points: pack.points_label, account: account.name || account.account_id },
                            `Apply ${label} (${pack.points_label}) to ${account.name || account.account_id} for the current period?`
                          ),
                          confirmLabel: t('admin.account_detail.confirm_topup_action', undefined, 'Apply top-up'),
                          onConfirm: () => void handleApplyTopUpPack(pack),
                        })
                      }
                      className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-left text-sm text-slate-800 transition hover:border-slate-400 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-800 dark:bg-slate-950/60 dark:text-slate-100 dark:hover:border-slate-600"
                      disabled={topUpActionPending !== null || packageActionPending !== null || !primarySubscription}
                    >
                      <span className="block font-semibold">{label}</span>
                      <span className="mt-1 block text-xs text-slate-500 dark:text-slate-400">{pack.points_label}</span>
                      <span className="mt-2 block text-xs text-slate-500 dark:text-slate-400">
                        {topUpActionPending === pack.pack_id
                          ? t('common.saving', {}, 'Saving...')
                          : isRecommended
                            ? t('admin.recommended', {}, 'Recommended')
                            : t('admin.account_detail.apply_topup_pack_action', undefined, 'Apply top-up')}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="mt-5 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950/45">
              <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-700 dark:text-slate-300">
                    {t('admin.account_detail.credit_adjustment_label', undefined, 'AI credit adjustment')}
                  </p>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                    {t(
                      'admin.account_detail.credit_adjustment_desc',
                      undefined,
                      'Write a grant or signed adjustment to the current AI credit ledger. A reason is required.'
                    )}
                  </p>
                </div>
                <BackofficeStatusBadge status="warning" label={t('admin.audit_required', {}, 'Audit required')} />
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-[0.75fr_0.75fr_1fr]">
                <label className="text-sm">
                  <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                    {t('admin.account_detail.credit_adjustment_type_label', undefined, 'Entry type')}
                  </span>
                  <select
                    value={creditAdjustmentForm.event_type}
                    onChange={(event) =>
                      setCreditAdjustmentForm((current) => ({ ...current, event_type: event.target.value }))
                    }
                    className="input"
                  >
                    <option value="grant">{t('admin.account_detail.credit_adjustment_grant', undefined, 'Grant')}</option>
                    <option value="adjustment">
                      {t('admin.account_detail.credit_adjustment_adjustment', undefined, 'Adjustment')}
                    </option>
                  </select>
                </label>
                <label className="text-sm">
                  <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                    {t('admin.account_detail.credit_adjustment_delta_label', undefined, 'Credit delta')}
                  </span>
                  <input
                    type="number"
                    step="1"
                    value={creditAdjustmentForm.credit_delta}
                    onChange={(event) =>
                      setCreditAdjustmentForm((current) => ({ ...current, credit_delta: event.target.value }))
                    }
                    className="input"
                    placeholder="+1000"
                  />
                </label>
                <label className="text-sm">
                  <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                    {t('admin.account_detail.credit_adjustment_reason_label', undefined, 'Reason')}
                  </span>
                  <input
                    type="text"
                    value={creditAdjustmentForm.reason}
                    onChange={(event) =>
                      setCreditAdjustmentForm((current) => ({ ...current, reason: event.target.value }))
                    }
                    className="input"
                    placeholder={t('admin.account_detail.credit_adjustment_reason_placeholder', undefined, 'billing correction')}
                  />
                </label>
              </div>
              <div className="mt-3 grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                <label className="text-sm">
                  <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                    {t('admin.account_detail.credit_adjustment_note_label', undefined, 'Operator note')}
                  </span>
                  <input
                    type="text"
                    value={creditAdjustmentForm.note}
                    onChange={(event) =>
                      setCreditAdjustmentForm((current) => ({ ...current, note: event.target.value }))
                    }
                    className="input"
                    placeholder={t('admin.optional', {}, 'Optional')}
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-secondary whitespace-nowrap"
                  disabled={creditAdjustmentPending || packageActionPending !== null}
                  onClick={() => void handleApplyCreditAdjustment()}
                >
                  {creditAdjustmentPending
                    ? t('common.saving', {}, 'Saving...')
                    : t('admin.account_detail.apply_credit_adjustment_action', undefined, 'Apply adjustment')}
                </button>
              </div>
            </div>
            {packageActionNotice ? (
              <BackofficeStackCard
                data-ui="account-package-action-notice"
                className="mt-4 border-green-200 bg-green-50 text-green-700 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300"
              >
                {packageActionNotice}
              </BackofficeStackCard>
            ) : null}
            {packageActionError ? (
              <BackofficeStackCard
                data-ui="account-package-action-error"
                className="mt-4 border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300"
              >
                {packageActionError}
              </BackofficeStackCard>
            ) : null}
            <div className="mt-4 flex flex-wrap gap-3">
              <a href="#site-footprint" className="btn btn-secondary">
                {t('admin.account_detail.view_sites_action', undefined, 'View sites')}
              </a>
            </div>
            <details
              data-ui="advanced-coverage-controls"
              className="mt-5 rounded-2xl border border-dashed border-gray-200 px-4 py-4 dark:border-gray-800"
            >
              <summary className="cursor-pointer list-none text-sm font-medium text-gray-700 dark:text-gray-300">
              {t('admin.account_detail.package_actions_reveal', undefined, 'Repair subscription record')}
            </summary>
            <div className="mt-4 flex flex-wrap gap-3">
                {primarySubscription ? (
                  <Link
                    href={`/admin/subscriptions/${primarySubscription.subscription_id}`}
                    className="text-xs font-medium text-gray-500 underline decoration-dotted underline-offset-4 transition hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
                  >
                    {t('admin.coverage_open_subscription_detail_action', {}, 'Inspect detail')} →
                  </Link>
                ) : null}
              </div>
            <p className="mt-4 text-sm text-gray-600 dark:text-gray-400">
              {t('admin.account_detail.package_controls_desc', undefined, 'Only open these fields for subscription-level repair work. Normal package changes should use the buttons above.')}
            </p>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                  {t('admin.account_detail.coverage_package_option_label', undefined, 'Coverage package option')}
                </span>
                <select
                  value={packageForm.plan_id}
                  onChange={(event) =>
                    setPackageForm((current) => {
                      const selected = packagePlanOptions.find((item) => item.plan_id === event.target.value);
                      return {
                        ...current,
                        plan_id: event.target.value,
                        plan_version_id: selected?.plan_version_id || current.plan_version_id,
                      };
                    })
                  }
                  className="input"
                >
                  <option value="">{t('common.select', {}, 'Select')}</option>
                  {packagePlanOptions.map((item) => (
                    <option key={item.plan_id} value={item.plan_id}>
                      {item.label}
                    </option>
                  ))}
                </select>
                <span className="mt-2 block text-xs text-slate-500 dark:text-slate-400">
                  {selectedPackageOption
                    ? t(
                        'admin.account_detail.coverage_package_option_auto_hint',
                        undefined,
                        'The matching package release is applied automatically on this surface.'
                      )
                    : t(
                        'admin.account_detail.coverage_package_option_empty_hint',
                        undefined,
                        'Choose a coverage package option first. The matching package release will be applied automatically.'
                      )}
                </span>
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                  {t('common.status')}
                </span>
                <select
                  value={packageForm.status}
                  onChange={(event) =>
                    setPackageForm((current) => ({ ...current, status: event.target.value }))
                  }
                  className="input"
                >
                  <option value="active">{translateStatusLabel('active', t)}</option>
                  <option value="trialing">{translateStatusLabel('trialing', t)}</option>
                  <option value="past_due">{translateStatusLabel('past_due', t)}</option>
                  <option value="suspended">{translateStatusLabel('suspended', t)}</option>
                  <option value="canceled">{translateStatusLabel('canceled', t)}</option>
                </select>
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                  {t('admin.account_detail.subscription_record_label', undefined, 'Subscription record')}
                </span>
                <input
                  type="text"
                  value={packageForm.subscription_id}
                  onChange={(event) =>
                    setPackageForm((current) => ({ ...current, subscription_id: event.target.value }))
                  }
                  className="input"
                  placeholder="sub_account_current"
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                  {t('portal.period_start', {}, 'Period Start')}
                </span>
                <input
                  type="datetime-local"
                  value={packageForm.current_period_start_at ? packageForm.current_period_start_at.slice(0, 16) : ''}
                  onChange={(event) =>
                    setPackageForm((current) => ({ ...current, current_period_start_at: event.target.value }))
                  }
                  className="input"
                />
              </label>
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
                  {t('portal.period_end', {}, 'Period End')}
                </span>
                <input
                  type="datetime-local"
                  value={packageForm.current_period_end_at ? packageForm.current_period_end_at.slice(0, 16) : ''}
                  onChange={(event) =>
                    setPackageForm((current) => ({ ...current, current_period_end_at: event.target.value }))
                  }
                  className="input"
                />
              </label>
            </div>
            <div className="mt-5 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() =>
                  setPendingConfirmation({
                    title: t('admin.account_detail.confirm_package_repair_title', undefined, 'Confirm subscription repair'),
                    message: t(
                      'admin.account_detail.confirm_package_repair_desc',
                      { account: account.name || account.account_id },
                      `Apply the subscription repair fields to ${account.name || account.account_id}?`
                    ),
                    confirmLabel: t('admin.account_detail.change_package_action', undefined, 'Change package'),
                    onConfirm: () => void handleChangePackage(),
                  })
                }
                className="btn btn-secondary"
                disabled={packageActionPending !== null || topUpActionPending !== null}
              >
                {packageActionPending === 'change'
                  ? t('common.saving', {}, 'Saving...')
                  : t('admin.account_detail.change_package_action', undefined, 'Change package')}
              </button>
              <button
                type="button"
                onClick={() =>
                  setPendingConfirmation({
                    title: t('admin.account_detail.confirm_suspend_title', undefined, 'Confirm suspension'),
                    message: t(
                      'admin.account_detail.confirm_suspend_desc',
                      { account: account.name || account.account_id },
                      `Suspend current coverage for ${account.name || account.account_id}?`
                    ),
                    confirmLabel: t('admin.account_detail.suspend_coverage_action', undefined, 'Suspend coverage'),
                    variant: 'danger',
                    onConfirm: () => void handleCoverageMutation('suspend'),
                  })
                }
                className="btn btn-secondary"
                disabled={packageActionPending !== null || topUpActionPending !== null || !primarySubscription}
              >
                {packageActionPending === 'suspend'
                  ? t('common.saving', {}, 'Saving...')
                  : t('admin.account_detail.suspend_coverage_action', undefined, 'Suspend coverage')}
              </button>
              <button
                type="button"
                onClick={() =>
                  setPendingConfirmation({
                    title: t('admin.account_detail.confirm_cancel_title', undefined, 'Confirm cancellation'),
                    message: t(
                      'admin.account_detail.confirm_cancel_desc',
                      { account: account.name || account.account_id },
                      `Cancel current coverage for ${account.name || account.account_id}?`
                    ),
                    confirmLabel: t('admin.account_detail.cancel_coverage_action', undefined, 'Cancel coverage'),
                    variant: 'danger',
                    onConfirm: () => void handleCoverageMutation('cancel'),
                  })
                }
                className="btn btn-secondary"
                disabled={packageActionPending !== null || topUpActionPending !== null || !primarySubscription}
              >
                {packageActionPending === 'cancel'
                  ? t('common.saving', {}, 'Saving...')
                  : t('admin.account_detail.cancel_coverage_action', undefined, 'Cancel coverage')}
              </button>
            </div>
            <div className="mt-5 space-y-4">
              {watchItems.map((item) => (
                <div key={item.label} className="flex items-start justify-between gap-4 border-b border-gray-200 pb-4 last:border-b-0 last:pb-0 dark:border-gray-800">
                  <div className="min-w-0">
                    <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">{item.label}</p>
                    <p className={cn('mt-1 text-sm font-semibold text-gray-950 dark:text-white', item.toneClassName)}>
                      {item.value}
                    </p>
                  </div>
                  <p className="max-w-sm text-right text-sm text-gray-600 dark:text-gray-400">{item.detail}</p>
                </div>
              ))}
            </div>
            </details>
          </BackofficeStackCard>
        </div>
      </BackofficePrimaryPanel>

      <BackofficeSectionPanel className="space-y-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.account_detail.quota_eyebrow', undefined, 'Quota posture')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.account_detail.quota_title', undefined, 'Current usage and limits')}
            </h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-400">
              {t(
                'admin.account_detail.quota_desc',
                undefined,
                'Account-level view of current-period AI credits, token usage, cost headroom, bound sites, and active key coverage.'
              )}
            </p>
          </div>
          <BackofficeStatusBadge
            status={quotaNeedsAttention ? 'warning' : 'ok'}
            label={quotaNeedsAttention ? translateStatusLabel('warning', t) : translateStatusLabel('ok', t)}
          />
        </div>

        <BackofficeMetricStrip
          columnsClassName="md:grid-cols-2 xl:grid-cols-4"
          items={[
            {
              label: t('admin.account_detail.ai_credits_label', undefined, 'AI credits'),
              value: `${formatInteger(Math.round(runBudgetSummary.used))} / ${
                runBudgetSummary.unlimited ? unlimitedLabel : formatInteger(Math.round(runBudgetSummary.limit))
              }`,
              detail: t('admin.account_detail.ai_credits_metric_desc', undefined, 'Used and available run credits.'),
              toneClassName: quotaToneClass(runBudgetSummary),
              size: 'compact',
            },
            {
              label: t('admin.account_detail.bound_sites_label', undefined, 'Bound sites'),
              value: `${formatInteger(account.site_count)} / ${siteLimitLabel}`,
              detail: t('admin.account_detail.bound_sites_metric_desc', undefined, 'Sites attached to this customer account.'),
              toneClassName: hasSiteLimitPressure ? 'text-amber-700 dark:text-amber-300' : undefined,
              size: 'compact',
            },
            {
              label: t('admin.account_detail.vector_documents_label', undefined, 'Vector articles'),
              value: vectorDocumentsMetric
                ? `${formatQuotaMetricValue(vectorDocumentsMetric)} / ${formatQuotaMetricLimit(vectorDocumentsMetric)}`
                : `0 / ${unlimitedLabel}`,
              detail: t('admin.account_detail.vector_documents_metric_desc', undefined, 'Indexed article capacity stays as a separate resource limit.'),
              toneClassName: quotaMetricToneClass(vectorDocumentsMetric),
              size: 'compact',
            },
            {
              label: t('admin.account_detail.concurrent_runs_label', undefined, 'Concurrent runs'),
              value: concurrentRunsMetric
                ? `${formatQuotaMetricValue(concurrentRunsMetric)} / ${formatQuotaMetricLimit(concurrentRunsMetric)}`
                : `0 / ${unlimitedLabel}`,
              detail: t('admin.account_detail.concurrent_runs_metric_desc', undefined, 'Current queued or running workload against concurrency guardrails.'),
              toneClassName: quotaMetricToneClass(concurrentRunsMetric),
              size: 'compact',
            },
          ]}
        />

        <div className="grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-gray-950 dark:text-white">
                  {t('admin.account_detail.credit_breakdown_title', undefined, 'AI credit usage')}
                </h3>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  {t(
                    'admin.account_detail.credit_breakdown_desc',
                    undefined,
                    'AI credits are estimated from runs, tokens, search, image recommendation, and vector processing until the ledger is enforced.'
                  )}
                </p>
              </div>
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                {creditMetric?.estimated
                  ? t('admin.account_detail.estimated_credit_label', undefined, 'Estimated')
                  : t('admin.current_period_only', undefined, 'Current period only')}
              </span>
            </div>
            <div className="mt-5 space-y-4">
              {quotaRows.map((item) => {
                const progress = item.summary.unlimited
                  ? 0
                  : Math.min(100, Math.max(0, item.summary.usageRatio * 100));
                return (
                  <div key={item.key} className="space-y-2">
                    <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-sm font-semibold text-gray-950 dark:text-white">{item.label}</p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">{item.detail}</p>
                      </div>
                      <div className="text-left sm:text-right">
                        <p className={cn('text-sm font-semibold text-gray-950 dark:text-white', quotaToneClass(item.summary))}>
                          {item.used} / {item.limit}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {t('admin.account_detail.quota_remaining_label', undefined, 'Remaining')}: {item.remaining}
                        </p>
                      </div>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                      <div
                        className={cn(
                          'h-full rounded-full',
                          item.summary.overLimit || item.summary.usageRatio >= 1
                            ? 'bg-red-500'
                            : item.summary.usageRatio >= 0.8
                              ? 'bg-amber-500'
                              : 'bg-emerald-500'
                        )}
                        style={{ width: `${progress}%` }}
                      />
                    </div>
                    <p className="text-xs text-gray-500 dark:text-gray-400">
                      {t('admin.account_detail.quota_usage_ratio_label', undefined, 'Usage')}: {item.ratio}
                    </p>
                  </div>
                );
              })}
              {(quotaSummary?.breakdown || []).length > 0 ? (
                <div className="rounded-[1rem] border border-slate-200 bg-slate-50/70 p-3 dark:border-slate-800 dark:bg-slate-950/35">
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                    {t('admin.account_detail.credit_components_label', undefined, 'Credit components')}
                  </p>
                  <div className="mt-3 divide-y divide-slate-200 text-sm dark:divide-slate-800">
                    {(quotaSummary?.breakdown || []).map((item) => (
                      <div key={item.key} className="flex items-start justify-between gap-4 py-2">
                        <div>
                          <p className="font-medium text-gray-900 dark:text-white">
                            {creditBreakdownLabel(item, t)}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            {formatInteger(Math.round(Number(item.quantity || 0)))} {item.unit}
                          </p>
                        </div>
                        <p className="text-right text-sm font-semibold text-gray-950 dark:text-white">
                          {formatInteger(Math.round(Number(item.credits || 0)))}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </BackofficeStackCard>

          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55 xl:col-span-2">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-gray-950 dark:text-white">
                  {t('admin.account_detail.credit_ledger_title', undefined, 'Credit ledger detail')}
                </h3>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  {t(
                    'admin.account_detail.credit_ledger_desc',
                    undefined,
                    'Current-period consume, grant, adjustment, and refund records from the AI credit ledger.'
                  )}
                </p>
              </div>
              <div className="text-left sm:text-right">
                <p className="text-sm font-semibold text-gray-950 dark:text-white">
                  {formatInteger(Math.round(creditLedgerNetUsed))}
                </p>
                <p className="text-xs text-gray-500 dark:text-gray-400">
                  {t(
                    'admin.account_detail.credit_ledger_net_used_label',
                    { count: formatInteger(creditLedgerCount), granted: formatInteger(Math.round(creditLedgerGranted)) },
                    `Net used, ${formatInteger(creditLedgerCount)} records, ${formatInteger(Math.round(creditLedgerGranted))} granted`
                  )}
                </p>
              </div>
            </div>
            {creditLedgerItems.length > 0 ? (
              <div className="mt-4 overflow-hidden rounded-[1rem] border border-slate-200 dark:border-slate-800">
                <div className="hidden grid-cols-[1.15fr_0.85fr_0.7fr_0.9fr] gap-3 bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500 dark:bg-slate-950/45 dark:text-slate-400 sm:grid">
                  <span>{t('admin.account_detail.credit_ledger_source', undefined, 'Source')}</span>
                  <span>{t('admin.account_detail.credit_ledger_quantity', undefined, 'Quantity')}</span>
                  <span className="text-right">{t('admin.account_detail.credit_ledger_credits', undefined, 'Credits')}</span>
                  <span className="text-right">{t('admin.account_detail.credit_ledger_time', undefined, 'Time')}</span>
                </div>
                <div className="divide-y divide-slate-200 text-sm dark:divide-slate-800">
                  {creditLedgerItems.map((entry) => (
                    <div
                      key={entry.ledger_entry_id || `${entry.source_type}-${entry.created_at}`}
                      className="grid grid-cols-1 gap-2 px-4 py-3 sm:grid-cols-[1.15fr_0.85fr_0.7fr_0.9fr] sm:gap-3"
                    >
                      <div>
                        <p className="font-medium text-slate-950 dark:text-white">
                          {creditBreakdownLabel(
                            {
                              key: entry.source_type,
                              quantity: entry.quantity,
                              unit: entry.unit,
                              rate: Number(entry.rate || 0),
                              credits: Math.abs(Number(entry.net_credit_delta ?? entry.credit_delta ?? 0)),
                            },
                            t
                          )}
                        </p>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          {[entry.event_type, entry.site_id, entry.run_id].filter(Boolean).join(' · ') || entry.source_id || '-'}
                        </p>
                      </div>
                      <p className="text-slate-700 dark:text-slate-300">
                        {formatInteger(Math.round(Number(entry.quantity || 0)))} {entry.unit}
                      </p>
                      <p className="font-semibold text-slate-950 dark:text-white sm:text-right">
                        {formatSignedCreditDelta(Number(entry.net_credit_delta ?? entry.credit_delta ?? 0))}
                      </p>
                      <p className="text-slate-500 dark:text-slate-400 sm:text-right">
                        {entry.created_at ? formatDate(entry.created_at) : '-'}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <BackofficeEmptyState
                title={t('admin.account_detail.credit_ledger_empty', undefined, 'No ledger records this period')}
                description={t(
                  'admin.account_detail.credit_ledger_empty_desc',
                  undefined,
                  'This account has no AI credit ledger entries in the current period.'
                )}
              />
            )}
          </BackofficeStackCard>

          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
            <h3 className="text-sm font-semibold text-gray-950 dark:text-white">
              {t('admin.account_detail.resource_limits_title', undefined, 'Resource limits')}
            </h3>
            <div className="mt-4 space-y-4">
              {resourceRows.map((metric) => {
                const progress = metric.unlimited
                  ? 0
                  : Math.min(100, Math.max(0, Number(metric.usage_ratio || 0) * 100));
                return (
                  <div key={metric.key} className="border-b border-gray-200 pb-4 last:border-b-0 dark:border-gray-800">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">
                          {quotaMetricLabel(metric, t)}
                        </p>
                        <p className={cn('mt-1 text-sm font-semibold text-gray-950 dark:text-white', quotaMetricToneClass(metric))}>
                          {formatQuotaMetricValue(metric)} / {formatQuotaMetricLimit(metric)}
                        </p>
                      </div>
                      <p className="max-w-[12rem] text-right text-xs leading-5 text-gray-500 dark:text-gray-400">
                        {metric.unlimited
                          ? unlimitedLabel
                          : `${Math.round(Math.min(999, Math.max(0, Number(metric.usage_ratio || 0) * 100)))}%`}
                      </p>
                    </div>
                    {!metric.unlimited ? (
                      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                        <div
                          className={cn(
                            'h-full rounded-full',
                            metric.status === 'limited'
                              ? 'bg-red-500'
                              : metric.status === 'near_limit'
                                ? 'bg-amber-500'
                                : 'bg-emerald-500'
                          )}
                          style={{ width: `${progress}%` }}
                        />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
            {internalLimitRows.length > 0 ? (
              <div className="mt-5 rounded-[1rem] border border-slate-200 bg-slate-50/70 px-3 py-3 dark:border-slate-800 dark:bg-slate-950/35">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                  {t('admin.account_detail.internal_guardrails_title', undefined, 'Internal guardrails')}
                </p>
                <div className="mt-3 space-y-2 text-sm text-gray-700 dark:text-gray-300">
                  {internalLimitRows.map((metric) => (
                    <div key={metric.key} className="flex items-center justify-between gap-4">
                      <span>{quotaMetricLabel(metric, t)}</span>
                      <span className={cn('font-semibold text-gray-950 dark:text-white', quotaMetricToneClass(metric))}>
                        {formatQuotaMetricValue(metric)} / {formatQuotaMetricLimit(metric)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            <div className="mt-5 rounded-[1rem] border border-slate-200 bg-slate-50/70 px-3 py-3 dark:border-slate-800 dark:bg-slate-950/35">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                {t('admin.account_detail.operator_recommendations_title', undefined, 'Recommendations')}
              </p>
              <ul className="mt-3 space-y-2 text-sm leading-6 text-gray-700 dark:text-gray-300">
                {quotaRecommendationItems.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          </BackofficeStackCard>
        </div>
      </BackofficeSectionPanel>

      <div id="site-footprint" className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.site_coverage')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.account_detail.site_footprint_title', undefined, 'Site footprint')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t('admin.account_detail.site_footprint_desc', undefined, 'Use site coverage to decide whether the next operator step belongs on a site detail page or stays at the customer level.')}
            </p>
          </div>
          {siteOptions.length === 0 ? (
            <BackofficeEmptyState
              title={t('admin.account_detail.sites_empty_title', undefined, 'No sites on this customer')}
              description={t('admin.account_detail.sites_empty_desc', undefined, 'This customer does not have a connected site yet. Open the customer list or wait for site onboarding before making coverage changes.')}
              action={
                <Link href="/admin/accounts" className="btn btn-secondary">
                  {t('common.accounts', undefined, 'Accounts')}
                </Link>
              }
            />
          ) : (
            <div className="space-y-3">
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-2 xl:grid-cols-2"
                items={[
                  { label: t('admin.active_sites'), value: formatInteger(siteOptions.length) },
                  {
                    label: t('admin.account_detail.site_admin_workspace_metric', undefined, 'Site admin workspace'),
                    value: t('common.enabled', undefined, 'Enabled'),
                  },
                ]}
              />
              <div className="space-y-3">
                {siteOptions.map((site) => (
                  <BackofficeStackCard key={site.site_id} className="flex items-center justify-between gap-4">
                    <div>
                      <Link href={`/admin/sites/${site.site_id}`} className="font-mono text-sm font-semibold text-blue-600 hover:underline dark:text-blue-300">
                        <BackofficeIdentifier value={site.site_id} className="text-sm text-blue-600 dark:text-blue-300" />
                      </Link>
                      {site.name ? (
                        <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{site.name}</p>
                      ) : null}
                    </div>
                    <BackofficeStatusBadge status={site.status} label={translateStatusLabel(site.status, t)} />
                  </BackofficeStackCard>
                ))}
              </div>
            </div>
          )}
        </BackofficeSectionPanel>
      </div>

      {Object.keys(siteRuntimeData).length > 0 ? (
        <BackofficeSectionPanel>
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.account_detail.advanced_checks_eyebrow', undefined, 'Advanced checks')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.provider_health_title', undefined, 'Model health & plan utilization')}
                </h2>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  {t('admin.provider_health_desc', undefined, 'Per-site runtime health and cost utilization for this customer.')}
                </p>
              </div>
              <span className="text-sm font-medium text-blue-600 dark:text-blue-300">
                {t('common.view', {}, 'View')}
              </span>
            </summary>
          <div className="mt-5 space-y-3">
            {Object.entries(siteRuntimeData).map(([siteId, runtime]) => {
              const failureRate = runtime.totalRuns > 0
                ? Math.round((runtime.failedRuns / runtime.totalRuns) * 100)
                : 0;
              const healthStatus = failureRate >= 50 ? 'error' : failureRate >= 20 ? 'warning' : 'ok';
              const siteName = account?.sites?.find((s) => s.site_id === siteId)?.name || siteId;
              return (
                <BackofficeStackCard key={siteId} className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <Link href={`/admin/sites/${siteId}`} className="font-mono text-sm font-semibold text-blue-600 hover:underline dark:text-blue-300">
                        <BackofficeIdentifier value={siteId} className="text-sm text-blue-600 dark:text-blue-300" />
                      </Link>
                      <BackofficeStatusBadge status={healthStatus} label={
                        healthStatus === 'ok'
                          ? t('admin.provider_healthy', undefined, 'Healthy')
                          : healthStatus === 'warning'
                            ? t('admin.provider_degraded', undefined, 'Degraded')
                            : t('admin.provider_unhealthy', undefined, 'Unhealthy')
                      } />
                    </div>
                    {siteName && siteName !== siteId ? (
                      <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{siteName}</p>
                    ) : null}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3 sm:text-right">
                    <div>
                      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                        {t('admin.run_failure_rate', undefined, 'Failure rate')}
                      </p>
                      <p className={cn(
                        'mt-1 text-sm font-semibold',
                        failureRate >= 50 ? 'text-red-600 dark:text-red-400' : failureRate >= 20 ? 'text-amber-700 dark:text-amber-300' : 'text-gray-950 dark:text-white'
                      )}>
                        {failureRate}%
                      </p>
                    </div>
                    <div>
                      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                        {t('admin.cost_estimate', undefined, 'Cost estimate')}
                      </p>
                      <p className="mt-1 text-sm font-semibold text-gray-950 dark:text-white">
                        {formatAdminCurrency(runtime.costEstimate)}
                      </p>
                    </div>
                    <div>
                      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-gray-500 dark:text-gray-400">
                        {t('admin.tokens_used', undefined, 'Tokens used')}
                      </p>
                      <p className="mt-1 text-sm font-semibold text-gray-950 dark:text-white">
                        {formatInteger(runtime.tokensTotal)}
                      </p>
                    </div>
                  </div>
                </BackofficeStackCard>
              );
            })}
          </div>
          </details>
        </BackofficeSectionPanel>
      ) : null}

      <ConfirmModal
        isOpen={Boolean(pendingConfirmation)}
        title={pendingConfirmation?.title}
        message={pendingConfirmation?.message || ''}
        confirmLabel={pendingConfirmation?.confirmLabel || t('common.confirm', {}, 'Confirm')}
        cancelLabel={t('common.cancel', {}, 'Cancel')}
        variant={pendingConfirmation?.variant || 'default'}
        onClose={() => setPendingConfirmation(null)}
        onConfirm={() => {
          pendingConfirmation?.onConfirm();
        }}
      >
        {pendingConfirmation?.showSuspendReason ? (
          <label className="block text-sm">
            <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">
              {t('admin.accounts.suspend_reason_label', {}, 'Suspension reason')}
            </span>
            <input
              type="text"
              value={suspendReason}
              onChange={(event) => setSuspendReason(event.target.value)}
              maxLength={200}
              placeholder={t('admin.accounts.suspend_reason_placeholder', {}, 'Optional short note for internal follow-up')}
              className="input"
            />
          </label>
        ) : null}
      </ConfirmModal>
    </BackofficePageStack>
  );
}

export default function AdminAccountDetailPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AccountDetailContent />
    </Suspense>
  );
}
