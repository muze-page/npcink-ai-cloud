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
import { translateAllowedAction, translateExternalCommercialRole } from '@/lib/admin-display';
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
  member_count: number;
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
  members: Array<{
    member_ref: string;
    identity_type?: string;
    allowed_actions?: string[];
    role: string;
    joined_at: string;
    status?: string;
    email?: string;
    invite_state?: string;
    invite_count?: number;
    invited_at?: string;
    last_invited_at?: string;
    invite_expires_at?: string;
    last_delivery_status?: string;
    last_delivery_error_code?: string;
    last_delivery_error_message?: string;
    last_login_at?: string;
    enabled_at?: string;
    disabled_at?: string;
    disabled_reason?: string;
    accessible_sites?: Array<{
      site_id: string;
      name?: string;
      status?: string;
    }>;
    metadata?: Record<string, unknown>;
    updated_at?: string;
  }>;
  trial_readiness?: TrialReadinessSummary;
}

interface TrialReadinessCheck {
  code: string;
  label: string;
  ok: boolean;
  detail: string;
}

interface TrialReadinessSummary {
  status: 'ready' | 'action_required' | 'blocked' | string;
  next_action: string;
  next_action_label: string;
  blocking_codes: string[];
  summary: {
    site_count: number;
    active_site_count: number;
    active_key_site_count: number;
    sites_without_active_key: string[];
    member_count: number;
    active_member_count: number;
    active_or_pending_member_count: number;
    subscription_status?: string;
    display_package_label?: string;
    package_kind?: PackageKind | string;
    coverage_state?: CoverageState | string;
  };
  checks: TrialReadinessCheck[];
}

interface MemberPlanCoverageSummary {
  member_count: number;
  covered_member_count: number;
  sites_needing_follow_up: number;
}

interface MemberPlanCoverageMember {
  member_ref: string;
  email?: string;
  identity_type?: string;
  allowed_actions?: string[];
  role: string;
  status: string;
  covered_site_count: number;
  sites_needing_follow_up: number;
  accessible_sites: Array<{
    site_id: string;
    site_name: string;
    site_status?: string;
    plan_id?: string;
    plan_version_id?: string;
    package_alias?: string;
    display_package_label?: string;
    package_kind?: PackageKind;
    coverage_state?: CoverageState;
    covered: boolean;
    coverage?: {
      covered_by_subscription_id?: string;
      status?: string;
    };
  }>;
}

interface MemberPlanCoveragePayload {
  summary: MemberPlanCoverageSummary;
  members: MemberPlanCoverageMember[];
}

interface SiteMembership {
  member_ref: string;
  identity_type?: string;
  allowed_actions?: string[];
  role: string;
  status?: string;
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
    runs_increment: 150000,
    tokens_increment: 30000000,
    cost_increment: 1499,
    recommended_for_tiers: ['agency'],
  },
];

type PendingConfirmation = {
  title: string;
  message: string;
  confirmLabel: string;
  showSuspendReason?: boolean;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

function normalizeEmailFromMember(memberRef: string, metadata?: Record<string, unknown>): string {
  const metadataEmail = String(metadata?.email || '').trim().toLowerCase();
  if (metadataEmail) {
    return metadataEmail;
  }
  if (memberRef.startsWith('user:')) {
    return memberRef.slice('user:'.length).trim().toLowerCase();
  }
  return '';
}

function getInviteStateLabel(member: AccountDetail['members'][number], t: (key: string, vars?: Record<string, string>, fallback?: string) => string): string {
  if (member.status === 'disabled') {
    return translateStatusLabel('disabled', t);
  }
  const source = String(member.metadata?.source || '');
  const inviteState = String(member.invite_state || member.metadata?.invite_state || '');
  if (inviteState === 'pending') {
    return translateStatusLabel('pending', t);
  }
  if (inviteState === 'sent') {
    return t('admin.invite_state_sent');
  }
  if (inviteState === 'accepted') {
    return t('admin.invite_state_accepted');
  }
  if (source === 'bootstrap_portal_site') {
    return t('admin.member_state_provisioned');
  }
  return translateStatusLabel(member.status || 'active', t);
}

function getDeliveryStateLabel(member: AccountDetail['members'][number], t: (key: string, vars?: Record<string, string>, fallback?: string) => string): string {
  const deliveryStatus = String(member.last_delivery_status || member.metadata?.last_delivery_status || '').trim();
  if (!deliveryStatus) {
    return t('common.unknown');
  }
  return t(`admin.delivery_${deliveryStatus}`, undefined, deliveryStatus);
}

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

function AccountDetailContent() {
  const params = useParams();
  const { t } = useLocale();
  const { accountId } = params as { accountId: string };
  
  const [account, setAccount] = useState<AccountDetail | null>(null);
  const [coverage, setCoverage] = useState<MemberPlanCoveragePayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedSiteId, setSelectedSiteId] = useState('');
  const [selectedMemberRef, setSelectedMemberRef] = useState('');
  const [siteMembers, setSiteMembers] = useState<SiteMembership[]>([]);
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
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteNotice, setInviteNotice] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [isInviting, setIsInviting] = useState(false);
  const [memberActionNotice, setMemberActionNotice] = useState<string | null>(null);
  const [memberActionError, setMemberActionError] = useState<string | null>(null);
  const [memberActionRef, setMemberActionRef] = useState<string | null>(null);
  const [memberStatusFilter, setMemberStatusFilter] = useState('all');
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
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [packagePlans, setPackagePlans] = useState<PackagePlanListItem[]>([]);
  const [siteRuntimeData, setSiteRuntimeData] = useState<Record<string, {
    totalRuns: number;
    failedRuns: number;
    lastRunAt: string | null;
    costEstimate: number;
    tokensTotal: number;
  }>>({});

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

  const loadSiteMembers = useCallback(async (siteId: string) => {
    if (!siteId) {
      setSiteMembers([]);
      setSelectedMemberRef('');
      return;
    }

    try {
      const response = await fetch(`/api/admin/sites/${encodeURIComponent(siteId)}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        setSiteMembers([]);
        setSelectedMemberRef('');
        return;
      }

      const data = await response.json();
      const memberships = data.data?.memberships || [];
      const allowedMembers = memberships.filter((membership: SiteMembership) => membership.status === 'active');
      setSiteMembers(allowedMembers);
      setSelectedMemberRef((current) => {
        if (current && allowedMembers.some((item: SiteMembership) => item.member_ref === current)) {
          return current;
        }
        return allowedMembers[0]?.member_ref || '';
      });
    } catch {
      setSiteMembers([]);
      setSelectedMemberRef('');
    }
  }, []);

  const loadSiteRuntimeData = useCallback(async (siteIds: string[]) => {
    if (siteIds.length === 0) {
      setSiteRuntimeData({});
      return;
    }
    const results: Record<string, {
      totalRuns: number;
      failedRuns: number;
      lastRunAt: string | null;
      costEstimate: number;
      tokensTotal: number;
    }> = {};
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
          results[siteId] = {
            totalRuns: Number(runtimeSummary.total_runs ?? 0),
            failedRuns: Number(runtimeSummary.failed_runs ?? 0),
            lastRunAt: runtimeSummary.last_run_at || null,
            costEstimate: Number(usageSummary.cost_estimate ?? 0),
            tokensTotal: Number(usageSummary.tokens_total ?? 0),
          };
        } catch {
          results[siteId] = {
            totalRuns: 0,
            failedRuns: 0,
            lastRunAt: null,
            costEstimate: 0,
            tokensTotal: 0,
          };
        }
      })
    );
    setSiteRuntimeData(results);
  }, []);

  const loadAccount = useCallback(async (preferredSiteId = '', preferredMemberRef = '') => {
    setIsLoading(true);
    setError(null);

    try {
      const [accountResponse, coverageResponse] = await Promise.all([
        fetch(`/api/admin/accounts/${accountId}`, {
          credentials: 'include',
        }),
        fetch(`/api/admin/accounts/${accountId}/member-plan-coverage`, {
          credentials: 'include',
        }),
      ]);

      if (!accountResponse.ok || !coverageResponse.ok) {
        throw new Error(t('error.failed_load'));
      }

      const [data, coverageData] = await Promise.all([
        accountResponse.json(),
        coverageResponse.json(),
      ]);
      const payload = data.data || {};
      const coveragePayload = coverageData.data || {};
      const accountData = payload.account || {};
      const accountMetadata =
        accountData.metadata && typeof accountData.metadata === 'object'
          ? (accountData.metadata as Record<string, unknown>)
          : {};
      const operatorDisplayName = String(accountMetadata.operator_display_name || '').trim();
      const operatorNote = String(accountMetadata.operator_note || '').trim();
      const accountStatusNote = String(accountMetadata.account_status_note || '').trim();
      const accountStatusUpdatedAt = String(accountMetadata.account_status_updated_at || '').trim();
      const memberships = Array.isArray(payload.memberships) ? payload.memberships : [];
      const sites = Array.isArray(payload.sites) ? payload.sites : [];
      const subscriptions = Array.isArray(payload.subscriptions) ? payload.subscriptions : [];
      const readiness = payload.trial_readiness || {};
      const readinessSummary = readiness.summary || {};
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
        member_count: memberships.length,
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
        members: memberships.map((membership: { member_ref?: string; role?: string; status?: string; created_at?: string; updated_at?: string; metadata?: Record<string, unknown> }) => ({
          member_ref: String(membership.member_ref || ''),
          role: String(membership.role || ''),
          joined_at: String(membership.created_at || membership.updated_at || ''),
          updated_at: String(membership.updated_at || ''),
          status: membership.status || 'unknown',
          invite_state: String((membership as { invite_state?: string }).invite_state || ''),
          invite_count: Number((membership as { invite_count?: number }).invite_count || 0) || 0,
          invited_at: String((membership as { invited_at?: string }).invited_at || ''),
          last_invited_at: String((membership as { last_invited_at?: string }).last_invited_at || ''),
          invite_expires_at: String((membership as { invite_expires_at?: string }).invite_expires_at || ''),
          last_delivery_status: String((membership as { last_delivery_status?: string }).last_delivery_status || ''),
          last_delivery_error_code: String((membership as { last_delivery_error_code?: string }).last_delivery_error_code || ''),
          last_delivery_error_message: String((membership as { last_delivery_error_message?: string }).last_delivery_error_message || ''),
          last_login_at: String((membership as { last_login_at?: string }).last_login_at || ''),
          enabled_at: String((membership as { enabled_at?: string }).enabled_at || ''),
          disabled_at: String((membership as { disabled_at?: string }).disabled_at || ''),
          disabled_reason: String((membership as { disabled_reason?: string }).disabled_reason || ''),
          accessible_sites: Array.isArray((membership as { accessible_sites?: Array<{ site_id?: string; name?: string; status?: string }> }).accessible_sites)
            ? ((membership as { accessible_sites?: Array<{ site_id?: string; name?: string; status?: string }> }).accessible_sites || []).map((site) => ({
                site_id: String(site.site_id || ''),
                name: String(site.name || ''),
                status: String(site.status || ''),
              }))
            : [],
          metadata: membership.metadata || {},
          email: normalizeEmailFromMember(String(membership.member_ref || ''), membership.metadata || {}),
        })),
        trial_readiness: readiness.status
          ? {
              status: String(readiness.status || 'action_required'),
              next_action: String(readiness.next_action || ''),
              next_action_label: String(readiness.next_action_label || ''),
              blocking_codes: Array.isArray(readiness.blocking_codes)
                ? readiness.blocking_codes.map((item: unknown) => String(item))
                : [],
              summary: {
                site_count: Number(readinessSummary.site_count || 0),
                active_site_count: Number(readinessSummary.active_site_count || 0),
                active_key_site_count: Number(readinessSummary.active_key_site_count || 0),
                sites_without_active_key: Array.isArray(readinessSummary.sites_without_active_key)
                  ? readinessSummary.sites_without_active_key.map((item: unknown) => String(item))
                  : [],
                member_count: Number(readinessSummary.member_count || 0),
                active_member_count: Number(readinessSummary.active_member_count || 0),
                active_or_pending_member_count: Number(readinessSummary.active_or_pending_member_count || 0),
                subscription_status: String(readinessSummary.subscription_status || ''),
                display_package_label: String(readinessSummary.display_package_label || ''),
                package_kind: String(readinessSummary.package_kind || ''),
                coverage_state: String(readinessSummary.coverage_state || ''),
              },
              checks: Array.isArray(readiness.checks)
                ? readiness.checks.map((item: Record<string, unknown>) => ({
                    code: String(item.code || ''),
                    label: String(item.label || ''),
                    ok: Boolean(item.ok),
                    detail: String(item.detail || ''),
                  }))
                : [],
            }
          : undefined,
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
      setCoverage({
        summary: {
          member_count: Number(coveragePayload.summary?.member_count || 0),
          covered_member_count: Number(coveragePayload.summary?.covered_member_count || 0),
          sites_needing_follow_up: Number(coveragePayload.summary?.sites_needing_follow_up_count || 0),
        },
        members: Array.isArray(coveragePayload.members)
          ? coveragePayload.members.map((member: Record<string, unknown>) => ({
              member_ref: String(member.member_ref || ''),
              email: String(member.email || ''),
              role: String(member.role || ''),
              status: String(member.status || ''),
              covered_site_count: Number(member.covered_site_count || 0),
              sites_needing_follow_up: Number(member.sites_needing_follow_up_count || 0),
              accessible_sites: Array.isArray(member.accessible_sites)
                ? member.accessible_sites.map((site: Record<string, unknown>) => {
                    const packageDisplay = resolveCustomerPackageDisplay(t, {
                      planId: String(site.plan_id || ''),
                      packageAlias: String(site.package_alias || ''),
                      packageKind: String(site.package_kind || ''),
                      coverageState: String(site.coverage_state || (site.covered ? 'covered' : 'uncovered')),
                    });
                    return {
                      site_id: String(site.site_id || ''),
                      site_name: String(site.site_name || site.site_id || ''),
                      site_status: String(site.site_status || ''),
                      plan_id: String(site.plan_id || ''),
                      plan_version_id: String(site.plan_version_id || ''),
                      package_alias: String(site.package_alias || ''),
                      display_package_label:
                        String(site.display_package_label || '') || packageDisplay.display_package_label,
                      package_kind:
                        (String(site.package_kind || '') as PackageKind) || packageDisplay.package_kind,
                      coverage_state:
                        (String(site.coverage_state || '') as CoverageState) || packageDisplay.coverage_state,
                      covered: Boolean(site.covered),
                      coverage: {
                        covered_by_subscription_id: String((site.coverage as Record<string, unknown> | undefined)?.covered_by_subscription_id || ''),
                        status: String((site.coverage as Record<string, unknown> | undefined)?.status || ''),
                      },
                    };
                  })
                : [],
            }))
          : [],
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

      const nextMemberRef =
        (preferredMemberRef &&
        (nextAccount?.members || []).some((member: { member_ref: string }) => member.member_ref === preferredMemberRef)
          ? preferredMemberRef
          : nextAccount?.members?.[0]?.member_ref) || '';

      setSelectedSiteId(nextSiteId);
      setSelectedMemberRef(nextMemberRef);

      if (nextSiteId) {
        await loadSiteMembers(nextSiteId);
      } else {
        setSiteMembers([]);
      }

      const nextSiteIds = nextAccount?.sites?.map((s) => s.site_id).filter(Boolean) || [];
      if (nextSiteIds.length > 0) {
        void loadSiteRuntimeData(nextSiteIds);
      }
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [accountId, loadSiteMembers, loadSiteRuntimeData, t]);

  const handleInviteMember = async () => {
    const normalizedEmail = inviteEmail.trim().toLowerCase();
    if (!normalizedEmail) {
      setInviteError(t('error.email_required'));
      return;
    }

    setIsInviting(true);
    setInviteError(null);
    setInviteNotice(null);

    try {
      const response = await fetch(`/api/admin/accounts/${encodeURIComponent(accountId)}/invite-member`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          email: normalizedEmail,
          role: 'user',
        }),
      });

      const payload = await response.json();

      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload.message, t('error.failed_invite_member')));
      }

      setInviteNotice(
        t(
          'admin.invite_member_success',
          { email: normalizedEmail },
          `${normalizedEmail} has been invited as a user.`
        )
      );
      setInviteEmail('');
      setMemberActionNotice(null);
      setMemberActionError(null);
      await loadAccount(selectedSiteId, `user:${normalizedEmail}`);
    } catch (err) {
      setInviteError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_invite_member')));
    } finally {
      setIsInviting(false);
    }
  };

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
      await loadAccount(selectedSiteId, selectedMemberRef);
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
      await loadAccount(selectedSiteId, selectedMemberRef);
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
      await loadAccount(selectedSiteId, selectedMemberRef);
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
      await loadAccount(selectedSiteId, selectedMemberRef);
    } catch (err) {
      setPackageActionError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save'))
      );
    } finally {
      setTopUpActionPending(null);
    }
  };

  const handleResendInvite = async (member: AccountDetail['members'][number]) => {
    setMemberActionRef(member.member_ref);
    setMemberActionNotice(null);
    setMemberActionError(null);
    try {
      const response = await fetch(
        `/api/admin/accounts/${encodeURIComponent(accountId)}/members/${encodeURIComponent(member.member_ref)}/resend-invite`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload.message, t('error.failed_resend_invite')));
      }
      const email = member.email || member.member_ref;
      setMemberActionNotice(t('admin.invite_member_resent', { email }));
      await loadAccount(selectedSiteId, member.member_ref);
    } catch (err) {
      setMemberActionError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_resend_invite'))
      );
    } finally {
      setMemberActionRef(null);
    }
  };

  const handleDisableMember = async (member: AccountDetail['members'][number]) => {
    setMemberActionRef(member.member_ref);
    setMemberActionNotice(null);
    setMemberActionError(null);
    try {
      const response = await fetch(
        `/api/admin/accounts/${encodeURIComponent(accountId)}/members/${encodeURIComponent(member.member_ref)}/disable`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload.message, t('error.failed_disable_member')));
      }
      setMemberActionNotice(t('admin.member_disabled_notice', { member: member.email || member.member_ref }));
      await loadAccount(selectedSiteId, selectedMemberRef === member.member_ref ? '' : selectedMemberRef);
    } catch (err) {
      setMemberActionError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_disable_member'))
      );
    } finally {
      setMemberActionRef(null);
    }
  };

  const handleEnableMember = async (member: AccountDetail['members'][number]) => {
    setMemberActionRef(member.member_ref);
    setMemberActionNotice(null);
    setMemberActionError(null);
    try {
      const response = await fetch(
        `/api/admin/accounts/${encodeURIComponent(accountId)}/members/${encodeURIComponent(member.member_ref)}/enable`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload.message, t('error.failed_reenable_member')));
      }
      setMemberActionNotice(t('admin.member_enabled_notice', { member: member.email || member.member_ref }));
      await loadAccount(selectedSiteId, member.member_ref);
    } catch (err) {
      setMemberActionError(
        resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_reenable_member'))
      );
    } finally {
      setMemberActionRef(null);
    }
  };

  useEffect(() => {
    void loadAccount();
    void loadPackagePlans();
  }, [loadAccount, loadPackagePlans]);

  useEffect(() => {
    if (!selectedSiteId) {
      setSiteMembers([]);
      return;
    }
    void loadSiteMembers(selectedSiteId);
  }, [loadSiteMembers, selectedSiteId]);

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

  const filteredMembers = account.members.filter((member) => {
    if (memberStatusFilter === 'all') {
      return true;
    }
    if (memberStatusFilter === 'delivery_failed') {
      return member.last_delivery_status === 'failed';
    }
    if (memberStatusFilter === 'never_logged_in') {
      return !member.last_login_at;
    }
    return member.status === memberStatusFilter;
  });

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
    const diff = new Date(sub.current_period_end).getTime() - Date.now();
    return diff >= 0 && diff <= 1000 * 60 * 60 * 24 * 30;
  });
  const disabledMembers = account.members.filter((member) => member.status === 'disabled');
  const pendingMembers = account.members.filter((member) => member.status === 'pending_invite');
  const membersWithDeliveryFailures = account.members.filter((member) => member.last_delivery_status === 'failed');
  const uncoveredSiteCount = coverage?.summary.sites_needing_follow_up || 0;
  const coveredMemberCount = coverage?.summary.covered_member_count || 0;
  const uncoveredMembers = (coverage?.members || []).filter((member) => member.sites_needing_follow_up > 0);
  const hasCoverageGap = uncoveredSiteCount > 0;
  const hasUncoveredCommercialPosture =
    primaryPackage.coverage_state === 'uncovered' || hasCoverageGap || (account.subscription_count === 0 && account.site_count > 0);
  const hasDevBaselineOnly = primaryPackage.package_kind === 'dev_baseline';
  const hasPaidCoverage =
    primaryPackage.package_kind === 'tier_package' && primaryPackage.coverage_state === 'covered';
  const hasFormalFreeCoverage =
    primaryPackage.package_kind === 'formal_free' && primaryPackage.coverage_state === 'covered';
  const trialReadiness = account.trial_readiness || null;
  const trialReadinessTone =
    trialReadiness?.status === 'ready'
      ? 'ok'
      : trialReadiness?.status === 'blocked'
        ? 'error'
        : 'warning';
  const trialReadinessTitle =
    trialReadiness?.status === 'ready'
      ? t('admin.account_detail.trial_readiness_ready_title', undefined, 'Ready for controlled trial')
      : trialReadiness?.status === 'blocked'
        ? t('admin.account_detail.trial_readiness_blocked_title', undefined, 'Blocked before trial')
        : t('admin.account_detail.trial_readiness_action_title', undefined, 'Action required before trial');
  const trialReadinessDescription =
    trialReadiness?.status === 'ready'
      ? t(
          'admin.account_detail.trial_readiness_ready_desc',
          undefined,
          'Package coverage, active site posture, Cloud API key coverage, and portal access are ready for an approved trial invite.'
        )
      : t(
          'admin.account_detail.trial_readiness_action_desc',
          undefined,
          'Use this checklist as the operator path for internal testing: fix the first failed item, then rerun smoke or invite the approved site.'
        );
  const trialSummary = trialReadiness?.summary;
  const trialMetricItems = [
    {
      label: t('admin.account_detail.trial_sites_metric', undefined, 'Sites active'),
      value: `${formatInteger(trialSummary?.active_site_count || 0)}/${formatInteger(trialSummary?.site_count || 0)}`,
      detail: t('admin.account_detail.trial_sites_metric_desc', undefined, 'Approved WordPress sites attached to this customer.'),
      toneClassName:
        trialSummary && trialSummary.site_count > 0 && trialSummary.active_site_count === trialSummary.site_count
          ? undefined
          : 'text-red-600 dark:text-red-400',
      size: 'compact' as const,
    },
    {
      label: t('admin.account_detail.trial_keys_metric', undefined, 'API keys'),
      value: `${formatInteger(trialSummary?.active_key_site_count || 0)}/${formatInteger(trialSummary?.site_count || 0)}`,
      detail: t('admin.account_detail.trial_keys_metric_desc', undefined, 'Sites with active Cloud API key coverage.'),
      toneClassName:
        trialSummary && trialSummary.site_count > 0 && trialSummary.active_key_site_count === trialSummary.site_count
          ? undefined
          : 'text-red-600 dark:text-red-400',
      size: 'compact' as const,
    },
    {
      label: t('common.package', undefined, 'Package'),
      value: trialSummary?.display_package_label || primaryPackage.display_package_label,
      detail: translateCoverageStateLabel(t, (trialSummary?.coverage_state as CoverageState) || primaryPackage.coverage_state),
      toneClassName:
        (trialSummary?.coverage_state || primaryPackage.coverage_state) === 'covered'
          ? undefined
          : 'text-red-600 dark:text-red-400',
      size: 'compact' as const,
    },
    {
      label: t('admin.account_detail.trial_portal_metric', undefined, 'Portal users'),
      value: `${formatInteger(trialSummary?.active_or_pending_member_count || 0)}/${formatInteger(trialSummary?.member_count || 0)}`,
      detail: t('admin.account_detail.trial_portal_metric_desc', undefined, 'Active or invited users for customer access.'),
      toneClassName:
        trialSummary && trialSummary.active_or_pending_member_count > 0
          ? undefined
          : 'text-red-600 dark:text-red-400',
      size: 'compact' as const,
    },
  ];
  const postureTone =
    account.status === 'suspended' || riskySubscriptions.length > 0 || hasUncoveredCommercialPosture || hasDevBaselineOnly
      ? 'error'
      : disabledMembers.length > 0 || pendingMembers.length > 0 || membersWithDeliveryFailures.length > 0
        ? 'warning'
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
    if (disabledMembers.length > 0 || pendingMembers.length > 0 || membersWithDeliveryFailures.length > 0) {
      return t('admin.account_detail.member_attention_title', undefined, 'Member follow-up is pending');
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
    if (disabledMembers.length > 0 || pendingMembers.length > 0 || membersWithDeliveryFailures.length > 0) {
      return t('admin.account_detail.member_attention_desc', undefined, 'Coverage is broadly healthy, but member delivery or access state still needs operator follow-up.');
    }
    return t('admin.account_detail.healthy_desc', undefined, 'Commercial coverage, site footprint, and member access are all readable from this surface.');
  })();
  const nextStepDescription = account.status === 'suspended'
    ? t('admin.account_detail.next_step_suspended_desc', undefined, 'Keep support actions bounded until you confirm why the customer is suspended.')
    : primarySubscription && riskySubscriptions[0]
      ? t('admin.account_detail.next_step_subscription_desc', undefined, 'Coverage posture still needs operator attention. Use the bounded actions on this page before opening any deeper commercial detail.')
      : hasUncoveredCommercialPosture
        ? t('admin.account_detail.open_subscription_queue_desc', undefined, 'This customer has site footprint without readable package coverage, so keep the next decision on customer coverage and site impact first.')
        : disabledMembers.length > 0 || pendingMembers.length > 0 || membersWithDeliveryFailures.length > 0
          ? t('admin.account_detail.review_member_access_desc', undefined, 'Coverage is readable; the next follow-up is usually inside portal access and invite delivery below.')
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
    {
      label: t('common.members'),
      value: formatInteger(account.member_count),
      detail:
        uncoveredMembers.length > 0
          ? t('admin.account_detail.member_uncovered_desc', { count: String(uncoveredMembers.length) }, `${uncoveredMembers.length} members can reach at least one site that needs subscription follow-up.`)
          : membersWithDeliveryFailures.length > 0
          ? t('admin.account_detail.member_delivery_failed_desc', { count: String(membersWithDeliveryFailures.length) }, `${membersWithDeliveryFailures.length} members have delivery issues.`)
          : pendingMembers.length > 0
            ? t('admin.account_detail.member_pending_desc', { count: String(pendingMembers.length) }, `${pendingMembers.length} members still need invite follow-up.`)
            : t('admin.account_detail.member_access_stable_desc', undefined, 'Member access and invite state look stable from this customer boundary.'),
      toneClassName: membersWithDeliveryFailures.length > 0 || pendingMembers.length > 0 ? 'text-amber-700 dark:text-amber-300' : undefined,
    },
  ];
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
  const portalAccessSummaryItems = [
    {
      label: t('common.members'),
      value: formatInteger(account.member_count),
      detail: t('admin.account_detail.portal_access_member_count_desc', undefined, 'Portal members currently attached to this customer.'),
    },
    {
      label: t('admin.pending_invites', undefined, 'Pending invites'),
      value: formatInteger(pendingMembers.length),
      detail: pendingMembers.length > 0
        ? t('admin.account_detail.member_pending_desc', { count: String(pendingMembers.length) }, `${pendingMembers.length} members still need invite follow-up.`)
        : t('admin.account_detail.portal_access_pending_clear_desc', undefined, 'No pending invite follow-up is visible right now.'),
      toneClassName: pendingMembers.length > 0 ? 'text-amber-700 dark:text-amber-300' : undefined,
    },
    {
      label: t('admin.disabled_members', undefined, 'Disabled members'),
      value: formatInteger(disabledMembers.length),
      detail: disabledMembers.length > 0
        ? t('admin.account_detail.portal_access_disabled_desc', { count: String(disabledMembers.length) }, `${disabledMembers.length} members are currently disabled and may need support review.`)
        : t('admin.account_detail.portal_access_disabled_clear_desc', undefined, 'No disabled portal members are visible on this customer.'),
    },
    {
      label: t('admin.members_needing_coverage_follow_up', undefined, 'Members needing coverage follow-up'),
      value: formatInteger(uncoveredMembers.length),
      detail: uncoveredMembers.length > 0
        ? t('admin.account_detail.members_with_coverage_follow_up_desc', undefined, 'These members can reach one or more sites whose customer coverage still needs follow-up.')
        : t('admin.account_detail.members_fully_covered_desc', undefined, 'No member currently points at a site that needs commercial follow-up.'),
      toneClassName: uncoveredMembers.length > 0 ? 'text-red-600 dark:text-red-400' : undefined,
    },
  ];
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
              className="btn btn-secondary"
              disabled={accountStatusPending !== null}
            >
              {accountStatusPending
                ? t('common.saving', {}, 'Saving...')
                : account.status === 'suspended'
                  ? t('admin.accounts.restore_account_action', {}, 'Restore account')
                  : t('admin.accounts.suspend_account_action', {}, 'Suspend account')}
            </button>
            <Link href="/admin/accounts" className="btn btn-secondary">
              {t('admin.back_to_accounts')}
            </Link>
          </>
        )}
        aside={(
          <div className="w-full xl:w-[46rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('common.members'), value: formatInteger(account.member_count), size: 'compact' },
                { label: t('common.sites'), value: formatInteger(account.site_count), size: 'compact' },
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
                    : pendingMembers.length > 0 || disabledMembers.length > 0 || membersWithDeliveryFailures.length > 0
                      ? t('admin.account_detail.next_focus_portal_access', undefined, 'Portal access and member delivery')
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
              <a href="#portal-access" className="btn btn-secondary">
                {t('admin.account_detail.invite_member_action', undefined, 'Invite member')}
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

      {trialReadiness ? (
        <BackofficeSectionPanel>
          <details data-ui="trial-readiness-summary" className="group">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('admin.account_detail.advanced_checks_eyebrow', undefined, 'Advanced checks')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
                  {t('admin.account_detail.trial_readiness_eyebrow', undefined, 'Trial readiness')}
                </h2>
                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
                  {trialReadinessTitle}
                </p>
              </div>
              <BackofficeStatusBadge status={trialReadinessTone} label={translateStatusLabel(trialReadinessTone, t)} />
            </summary>
            <div className="mt-5 space-y-4">
              <p className="max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
                {trialReadinessDescription}
              </p>
              <BackofficeMetricStrip items={trialMetricItems} columnsClassName="md:grid-cols-2 xl:grid-cols-4" />
              <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                {trialReadiness.checks.map((check) => (
                  <div
                    key={check.code}
                    className={cn(
                      'rounded-[1rem] border px-3 py-3 text-sm',
                      check.ok
                        ? 'border-emerald-200 bg-emerald-50/70 text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/20 dark:text-emerald-200'
                        : 'border-amber-200 bg-amber-50/75 text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-100'
                    )}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="font-semibold">{check.label}</p>
                      <BackofficeStatusBadge
                        status={check.ok ? 'ok' : 'warning'}
                        label={check.ok ? translateStatusLabel('ok', t) : translateStatusLabel('warning', t)}
                      />
                    </div>
                    <p className="mt-2 text-xs leading-5 opacity-85">{check.detail}</p>
                  </div>
                ))}
              </div>
            </div>
          </details>
        </BackofficeSectionPanel>
      ) : null}

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
                    label: t('admin.active_memberships'),
                    value: formatInteger(account.members.filter((member) => member.status !== 'inactive').length),
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

      <div id="portal-access" className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <BackofficeSectionPanel className="space-y-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.member_directory')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.account_detail.portal_access_title', undefined, 'Portal access')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t('admin.account_detail.portal_access_desc', undefined, 'Use this block for invite delivery and member access follow-up after the customer coverage posture is clear.')}
            </p>
          </div>
          <BackofficeMetricStrip items={portalAccessSummaryItems} columnsClassName="xl:grid-cols-2" />
          {coverage?.members.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {coverage.members.slice(0, 2).map((member) => (
                <BackofficeStackCard key={`portal-access-summary-${member.member_ref}`}>
                  <p className="text-sm font-semibold text-slate-950 dark:text-white">
                    {member.email || member.member_ref}
                  </p>
                  <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                    {translateExternalCommercialRole(member.identity_type || member.role, t)}
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <BackofficeStatusBadge status={member.status} label={translateStatusLabel(member.status, t)} />
                    <BackofficeStatusBadge
                      status={member.sites_needing_follow_up > 0 ? 'error' : 'ok'}
                      label={
                        member.sites_needing_follow_up > 0
                          ? t('admin.coverage_follow_up_required', undefined, 'Coverage follow-up required')
                          : t('status.active')
                      }
                    />
                  </div>
                </BackofficeStackCard>
              ))}
            </div>
          ) : null}
          <details
            data-ui="member-coverage-details"
            className="rounded-2xl border border-dashed border-gray-200 px-4 py-4 dark:border-gray-800"
          >
            <summary className="cursor-pointer list-none text-sm font-medium text-gray-700 dark:text-gray-300">
              {t('admin.account_detail.member_plan_coverage_reveal', undefined, 'View member coverage details')}
            </summary>
            <div className="mt-4 space-y-4">
              <BackofficeMetricStrip
                columnsClassName="md:grid-cols-2 xl:grid-cols-2"
                items={[
                  {
                    label: t('admin.covered_members', undefined, 'Covered members'),
                    value: formatInteger(coveredMemberCount),
                    detail: t('admin.account_detail.covered_members_desc', undefined, 'Members with at least one covered site.'),
                  },
                  {
                    label: t('admin.members_needing_coverage_follow_up', undefined, 'Members needing coverage follow-up'),
                    value: formatInteger(uncoveredMembers.length),
                    detail: hasCoverageGap
                      ? t('admin.account_detail.members_with_coverage_follow_up_desc', undefined, 'These members can access one or more sites whose current customer subscription needs operator follow-up.')
                      : t('admin.account_detail.members_fully_covered_desc', undefined, 'No member currently points at a site that needs commercial follow-up.'),
                  },
                  {
                    label: t('admin.sites_needing_subscription_follow_up', undefined, 'Sites needing subscription follow-up'),
                    value: formatInteger(uncoveredSiteCount),
                    detail: hasCoverageGap
                      ? t('admin.account_detail.sites_needing_follow_up_desc', undefined, 'These sites are covered by the customer account, but their current subscription posture still needs explicit operator follow-up.')
                      : t('admin.account_detail.uncovered_sites_clear_desc', undefined, 'All visible sites currently resolve to readable customer subscription coverage.'),
                  },
                ]}
              />
              {coverage?.members.length ? (
                <div className="space-y-3">
                  {coverage.members.map((member) => (
                    <BackofficeStackCard key={member.member_ref} className="space-y-3">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <BackofficeIdentifier value={member.member_ref} className="text-sm font-semibold text-gray-950 dark:text-white" />
                          {member.email ? (
                            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{member.email}</p>
                          ) : null}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <BackofficeStatusBadge status={member.status} label={translateStatusLabel(member.status, t)} />
                          <BackofficeStatusBadge status={member.sites_needing_follow_up > 0 ? 'error' : 'ok'} label={member.sites_needing_follow_up > 0 ? t('admin.coverage_follow_up_required', undefined, 'Coverage follow-up required') : t('status.active')} />
                        </div>
                      </div>
                      <div className="grid gap-3 md:grid-cols-3">
                        <div>
                          <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">{t('admin.product_role', undefined, 'Product role')}</p>
                          <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
                            {translateExternalCommercialRole(member.identity_type || member.role, t)}
                          </p>
                          {member.allowed_actions?.length ? (
                            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                              {member.allowed_actions.map((action) => translateAllowedAction(action, t)).join(' · ')}
                            </p>
                          ) : null}
                        </div>
                        <div>
                          <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">{t('admin.covered_sites', undefined, 'Covered sites')}</p>
                          <p className="mt-1 text-sm font-semibold text-gray-900 dark:text-gray-100">{formatInteger(member.covered_site_count)}</p>
                        </div>
                        <div>
                          <p className="text-xs uppercase tracking-[0.14em] text-gray-500 dark:text-gray-400">{t('admin.sites_needing_follow_up', undefined, 'Sites needing follow-up')}</p>
                          <p className={cn('mt-1 text-sm font-semibold', member.sites_needing_follow_up > 0 ? 'text-red-600 dark:text-red-400' : 'text-gray-900 dark:text-gray-100')}>
                            {formatInteger(member.sites_needing_follow_up)}
                          </p>
                        </div>
                      </div>
                      <div className="space-y-2">
                        {member.accessible_sites.map((site) => (
                          <div key={`${member.member_ref}:${site.site_id}`} className="rounded-2xl border border-gray-200 px-4 py-3 dark:border-gray-800">
                            <div className="flex items-start justify-between gap-4">
                              <div>
                                <Link href={`/admin/sites/${site.site_id}`} className="font-mono text-sm font-semibold text-blue-600 hover:underline dark:text-blue-300">
                                  <BackofficeIdentifier value={site.site_id} className="text-sm text-blue-600 dark:text-blue-300" />
                                </Link>
                                <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">{site.site_name || site.site_id}</p>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                <BackofficeStatusBadge status={site.covered ? 'ok' : 'error'} label={site.covered ? t('status.active') : t('admin.coverage_follow_up_required', undefined, 'Coverage follow-up required')} />
                                <BackofficeStatusBadge status={site.coverage?.status || site.site_status || 'unknown'} label={translateStatusLabel(site.coverage?.status || site.site_status || 'unknown', t)} />
                              </div>
                            </div>
                            <div className="mt-3 flex flex-wrap gap-2 text-xs text-gray-600 dark:text-gray-400">
                              <span>{t('common.package', undefined, 'Package')}: {site.display_package_label || site.package_alias || site.plan_id || t('common.not_found')}</span>
                              <span>{t('admin.package_kind', undefined, 'Package kind')}: {translatePackageKindLabel(t, site.package_kind || (site.covered ? 'tier_package' : 'unknown'))}</span>
                              <span>{t('admin.coverage_state', undefined, 'Coverage state')}: {translateCoverageStateLabel(t, site.coverage_state || (site.covered ? 'covered' : 'uncovered'))}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </BackofficeStackCard>
                  ))}
                </div>
              ) : (
                <BackofficeEmptyState
                  title={t('admin.account_detail.members_empty_title', undefined, 'No members on this customer')}
                  description={t('admin.account_detail.members_empty_desc', undefined, 'No user or support member is attached to this customer yet. Use the member directory for invite and access follow-up.')}
                />
              )}
            </div>
          </details>
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <div className="border-b border-gray-200 px-6 py-5 dark:border-gray-800">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.member_directory')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('admin.account_detail.member_ops_title', undefined, 'Portal access controls')}
            </h2>
            <p className="mt-1 text-sm text-gray-600 dark:text-gray-400">
              {t('admin.account_detail.member_ops_desc', undefined, 'Keep invite delivery, disable/reenable, and member directory work behind an explicit reveal so the first screen stays customer-first.')}
            </p>
          </div>
          <details className="rounded-2xl border border-dashed border-gray-200 px-4 py-4 dark:border-gray-800">
            <summary className="cursor-pointer list-none text-sm font-medium text-gray-700 dark:text-gray-300">
              {t('admin.account_detail.portal_access_controls_reveal', undefined, 'Manage portal access')}
            </summary>
            <div className="mt-4 rounded-2xl border border-gray-200 dark:border-gray-800">
          <div className="border-b border-gray-200 px-6 py-5 dark:border-gray-800">
            <div className="flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-300">
                  {t('admin.invite_portal_member')}
                </p>
                <h3 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
                  {t('admin.invite_portal_member_title')}
                </h3>
                <p className="mt-1 max-w-2xl text-sm text-gray-600 dark:text-gray-400">
                  {t('admin.invite_portal_member_desc')}
                </p>
              </div>
              <button
                type="button"
                onClick={handleInviteMember}
                className={cn('btn btn-secondary', (isInviting || !inviteEmail.trim()) && 'pointer-events-none opacity-50')}
                disabled={isInviting || !inviteEmail.trim()}
              >
                {isInviting ? t('auth.sending') : t('admin.send_invite')}
              </button>
            </div>
            <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_0.7fr]">
              <label className="text-sm">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.email')}</span>
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(event) => setInviteEmail(event.target.value)}
                  placeholder={t('auth.email_placeholder')}
                  className="w-full rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm dark:border-gray-800 dark:bg-gray-900/90"
                />
              </label>
              <div className="rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm dark:border-gray-800 dark:bg-gray-900/90">
                <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.role')}</span>
                <div className="font-medium text-slate-900 dark:text-slate-100">
                  {t('admin.external_role_user', undefined, 'User')}
                </div>
                <p className="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">
                  {t(
                    'admin.user_role_notice',
                    undefined,
                    'Invited portal members are provisioned as users in the current Cloud model.'
                  )}
                </p>
              </div>
            </div>
            {inviteNotice ? (
              <BackofficeStackCard className="mt-4 border-green-200 bg-green-50 text-green-700 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300">
                {inviteNotice}
              </BackofficeStackCard>
            ) : null}
            {inviteError ? (
              <BackofficeStackCard className="mt-4 border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                {inviteError}
              </BackofficeStackCard>
            ) : null}
            {memberActionNotice ? (
              <BackofficeStackCard className="mt-4 border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900 dark:bg-blue-950/30 dark:text-blue-300">
                {memberActionNotice}
              </BackofficeStackCard>
            ) : null}
            {memberActionError ? (
              <BackofficeStackCard className="mt-4 border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
                {memberActionError}
              </BackofficeStackCard>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3 px-6 py-4">
            <div>
              <h3 className="text-sm font-semibold text-gray-950 dark:text-white">{t('admin.member_directory')}</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">{t('admin.member_directory_desc')}</p>
            </div>
            <label className="text-sm">
              <span className="mb-2 block font-medium text-gray-700 dark:text-gray-300">{t('common.status')}</span>
              <select
                value={memberStatusFilter}
                onChange={(event) => setMemberStatusFilter(event.target.value)}
                className="rounded-2xl border border-gray-200 bg-white px-4 py-2 text-sm dark:border-gray-800 dark:bg-gray-900/90"
              >
                <option value="all">{t('common.all')}</option>
                <option value="pending_invite">{translateStatusLabel('pending_invite', t)}</option>
                <option value="active">{translateStatusLabel('active', t)}</option>
                <option value="disabled">{translateStatusLabel('disabled', t)}</option>
                <option value="delivery_failed">{t('admin.delivery_failed')}</option>
                <option value="never_logged_in">{t('admin.never_logged_in')}</option>
              </select>
            </label>
          </div>
          {filteredMembers.length === 0 ? (
            <div className="p-6">
              <BackofficeEmptyState
                title={t('admin.account_detail.members_filter_empty_title', undefined, 'No members match this filter')}
                description={t('admin.account_detail.members_filter_empty_desc', undefined, 'The customer has no member in the selected status. Clear the filter or inspect the member directory.')}
                action={
                  <button type="button" className="btn btn-secondary" onClick={() => setMemberStatusFilter('all')}>
                    {t('common.clear_filters', undefined, 'Clear filters')}
                  </button>
                }
              />
            </div>
          ) : (
            <div className="divide-y divide-gray-200 dark:divide-gray-800">
              {filteredMembers.map((member) => (
                <article key={member.member_ref} className="grid gap-4 px-6 py-4 lg:grid-cols-[minmax(0,1fr)_0.5fr_0.6fr_auto] lg:items-center">
                  <div>
                    <BackofficeIdentifier value={member.member_ref} className="text-sm font-semibold text-gray-950 dark:text-white" />
                    {member.email ? (
                      <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">{member.email}</p>
                    ) : null}
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      {getInviteStateLabel(member, t)}
                      {member.last_invited_at ? ` · ${t('admin.last_invited_at')}: ${formatDate(String(member.last_invited_at))}` : ''}
                    </p>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      {t('admin.delivery_status')}: {getDeliveryStateLabel(member, t)}
                      {member.invite_expires_at ? ` · ${t('admin.invite_expires_at')}: ${formatDate(member.invite_expires_at)}` : ''}
                    </p>
                    <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                      {t('admin.last_login_at')}: {member.last_login_at ? formatDate(member.last_login_at) : t('common.never')}
                    </p>
                    {member.last_delivery_error_message ? (
                      <p className="mt-1 text-xs text-red-600 dark:text-red-400">{member.last_delivery_error_message}</p>
                    ) : null}
                  </div>
                  <div>
                    <span className="inline-flex rounded-full bg-blue-100 px-2.5 py-1 text-xs font-medium text-blue-700 dark:bg-blue-900/30 dark:text-blue-300">
                      {translateExternalCommercialRole(member.identity_type || member.role, t)}
                    </span>
                  </div>
                  <div className="text-sm text-gray-600 dark:text-gray-400">
                    <p>{formatDate(member.joined_at)}</p>
                    <BackofficeStatusBadge
                      status={member.status || 'unknown'}
                      label={translateStatusLabel(member.status || 'unknown', t)}
                      className="mt-2"
                    />
                  </div>
                  <div className="flex flex-wrap justify-start gap-2 lg:justify-end">
                    {member.status === 'active' && member.email ? (
                      <button
                        type="button"
                        onClick={() => handleResendInvite(member)}
                        className={cn('btn btn-secondary', memberActionRef === member.member_ref && 'pointer-events-none opacity-50')}
                        disabled={memberActionRef === member.member_ref}
                      >
                        {t('admin.resend_invite')}
                      </button>
                    ) : null}
                    {member.status === 'disabled' ? (
                      <button
                        type="button"
                        onClick={() => handleEnableMember(member)}
                        className={cn('btn btn-secondary', memberActionRef === member.member_ref && 'pointer-events-none opacity-50')}
                        disabled={memberActionRef === member.member_ref}
                      >
                        {t('admin.reenable_member')}
                      </button>
                    ) : null}
                    {member.status !== 'disabled' ? (
                      <button
                        type="button"
                        onClick={() => handleDisableMember(member)}
                        className={cn('btn btn-secondary', memberActionRef === member.member_ref && 'pointer-events-none opacity-50')}
                        disabled={memberActionRef === member.member_ref}
                      >
                        {t('admin.disable_member')}
                      </button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          )}
            </div>
          </details>
        </BackofficeSectionPanel>
      </div>
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
