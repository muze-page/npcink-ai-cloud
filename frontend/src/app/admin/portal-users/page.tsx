'use client';

import React, { FormEvent, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { AdminMutationReceiptPayload } from '@/components/admin/AdminMutationReceipt';
import { AdminLatestOperationButton } from '@/components/admin/AdminLatestOperationDialog';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeEmptyState,
  BackofficeLayer,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ListPagination } from '@/components/ui/ListPagination';
import { ConfirmModal, Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { useLocale } from '@/contexts/LocaleContext';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';

type PortalUserItem = {
  principal_id: string;
  email: string;
  status: string;
  session_version: number;
  source: string;
  created_at?: string;
  last_login_at?: string;
  account_id?: string;
  account_name?: string;
  account_status?: string;
  membership_status?: string;
  site_id?: string;
  site_name?: string;
  site_status?: string;
  wordpress_url?: string;
  subscription_id?: string;
  subscription_status?: string;
  plan_id?: string;
  package_alias?: string;
  display_package_label?: string;
  qq_bound: boolean;
  qq_binding_count: number;
  qq_last_login_at?: string;
};

type PortalUsersSummary = {
  active?: number;
  disabled?: number;
  qq_bound?: number;
  self_registered?: number;
};

type PortalUsersResponse = {
  items?: PortalUserItem[];
  total?: number;
  summary?: PortalUsersSummary;
  pagination?: {
    offset?: number;
    limit?: number;
    total?: number;
    has_more?: boolean;
  };
};

type PortalUserAuditEvent = {
  event_id: number;
  event_kind: string;
  outcome: string;
  actor_kind: string;
  actor_ref: string;
  method: string;
  path: string;
  trace_id: string;
  idempotency_key: string;
  scope_kind: string;
  scope_id: string;
  account_id?: string;
  site_id?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
};

type PortalUserAuditDetail = {
  principal?: {
    principal_id?: string;
    email?: string;
    status?: string;
    session_version?: number;
    last_login_at?: string;
    created_at?: string;
  };
  items?: PortalUserAuditEvent[];
  total?: number;
  summary?: {
    events?: number;
    succeeded?: number;
    failed?: number;
    registration_events?: number;
    disable_events?: number;
    latest_disable_reason?: string;
    latest_disable_revoked_account_memberships?: number;
    latest_disable_revoked_identity_provider_bindings?: number;
  };
};

type BatchDisableResult = {
  receipt?: AdminMutationReceiptPayload;
  totals?: {
    attempted?: number;
    disabled?: number;
    already_disabled?: number;
    failed?: number;
  };
  items?: Array<{
    principal_id?: string;
    outcome?: string;
    status?: string;
    session_version?: number;
    error_code?: string;
    message?: string;
  }>;
};

type PortalUserDisableResult = {
  receipt?: AdminMutationReceiptPayload;
  session_version?: number;
};

type Filters = {
  q: string;
  status: string;
  package_alias: string;
  qq_bound: string;
};

type PortalUserSort = 'access_risk' | 'recent_login' | 'recent_registration';
type PortalUserRisk = 'access_issue' | 'onboarding' | 'active' | 'disabled';

type Translator = (key: string, params?: Record<string, string>, fallback?: string) => string;

function sourceLabel(source: string, t: Translator): string {
  if (source === 'portal_self_registration') {
    return t('admin.portal_users.source_self_registration', {}, 'Self registration');
  }
  if (source === 'account_membership') {
    return t('admin.portal_users.source_admin_provisioned', {}, 'Admin provisioned');
  }
  return source || t('common.unknown', {}, 'Unknown');
}

function dateLabel(value: string | undefined, t: Translator): string {
  return value ? formatDate(value) : t('admin.portal_users.not_recorded', {}, 'Not recorded');
}

function auditEventLabel(eventKind: string, t: Translator): string {
  if (eventKind === 'portal.registration') {
    return t('admin.portal_users.audit_registration', {}, 'Self registration');
  }
  if (eventKind === 'portal_user.disable') {
    return t('admin.portal_users.audit_disable', {}, 'User disabled');
  }
  if (eventKind === 'account_membership.upsert') {
    return t('admin.portal_users.audit_account_membership', {}, 'Account access provisioned');
  }
  return eventKind || t('admin.portal_users.audit_unknown', {}, 'Unknown event');
}

function payloadText(payload: Record<string, unknown> | undefined, t: Translator): string {
  if (!payload) {
    return '';
  }
  const reason = String(payload.reason || '').trim();
  const revokedMemberships = Number(payload.revoked_account_memberships || 0);
  const revokedBindings = Number(payload.revoked_identity_provider_bindings || 0);
  if (reason || revokedMemberships || revokedBindings) {
    return [
      reason ? t('admin.portal_users.payload_reason', { reason }, 'Reason: {{reason}}') : '',
      revokedMemberships ? t('admin.portal_users.payload_account_memberships', { count: String(revokedMemberships) }, 'Account memberships {{count}}') : '',
      revokedBindings ? t('admin.portal_users.payload_qq_bindings', { count: String(revokedBindings) }, 'QQ bindings {{count}}') : '',
    ].filter(Boolean).join(' · ');
  }
  const email = String(payload.email || '').trim();
  const siteId = String(payload.site_id || '').trim();
  if (email || siteId) {
    return [
      email ? t('admin.portal_users.payload_email', { email }, 'Email: {{email}}') : '',
      siteId ? t('admin.portal_users.payload_site', { site: siteId }, 'Site: {{site}}') : '',
    ].filter(Boolean).join(' · ');
  }
  return '';
}

const PAGE_SIZE = 25;
const SORTS = new Set<PortalUserSort>(['access_risk', 'recent_login', 'recent_registration']);

function normalizeOffset(value: string | null): number {
  const parsed = Number(value || 0);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

function normalizeSort(value: string | null): PortalUserSort {
  return value && SORTS.has(value as PortalUserSort) ? (value as PortalUserSort) : 'access_risk';
}

function portalUserRisk(user: PortalUserItem): PortalUserRisk {
  if (user.status === 'disabled') return 'disabled';
  const membershipHealthy = !user.membership_status || user.membership_status === 'active';
  const accountHealthy = !user.account_id || user.account_status === 'active';
  const siteHealthy = !user.site_id || user.site_status === 'active';
  const subscriptionHealthy = !user.subscription_id || user.subscription_status === 'active';
  if (!membershipHealthy || !accountHealthy || !siteHealthy || !subscriptionHealthy || !user.account_id) {
    return 'access_issue';
  }
  if (!user.last_login_at) return 'onboarding';
  return 'active';
}

function portalUserRiskRank(user: PortalUserItem): number {
  return { access_issue: 0, onboarding: 1, active: 2, disabled: 3 }[portalUserRisk(user)];
}

function sortPortalUsers(users: PortalUserItem[], sort: PortalUserSort): PortalUserItem[] {
  return [...users].sort((left, right) => {
    const leftLogin = new Date(left.last_login_at || 0).getTime() || 0;
    const rightLogin = new Date(right.last_login_at || 0).getTime() || 0;
    const leftCreated = new Date(left.created_at || 0).getTime() || 0;
    const rightCreated = new Date(right.created_at || 0).getTime() || 0;
    if (sort === 'recent_login') return rightLogin - leftLogin;
    if (sort === 'recent_registration') return rightCreated - leftCreated;
    return portalUserRiskRank(left) - portalUserRiskRank(right) || leftCreated - rightCreated;
  });
}

function riskToneClassName(risk: PortalUserRisk): string {
  if (risk === 'access_issue') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200';
  if (risk === 'onboarding') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200';
  if (risk === 'active') return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200';
  return 'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-300';
}

function buildQuery(filters: Filters, offset: number): string {
  const params = new URLSearchParams();
  params.set('source', 'portal_self_registration');
  params.set('limit', String(PAGE_SIZE));
  if (offset > 0) params.set('offset', String(offset));
  if (filters.q.trim()) params.set('q', filters.q.trim());
  if (filters.status) params.set('status', filters.status);
  if (filters.package_alias.trim()) params.set('package_alias', filters.package_alias.trim());
  if (filters.qq_bound) params.set('qq_bound', filters.qq_bound);
  return params.toString();
}

function PortalUsersContent() {
  const { t } = useLocale();
  const toast = useToast();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const appliedQuery = searchParams.get('q') || '';
  const appliedStatus = searchParams.get('status') || '';
  const appliedPackageAlias = searchParams.get('package_alias') || '';
  const appliedQqBound = searchParams.get('qq_bound') || '';
  const appliedFilters = useMemo<Filters>(() => ({
    q: appliedQuery,
    status: appliedStatus,
    package_alias: appliedPackageAlias,
    qq_bound: appliedQqBound,
  }), [appliedPackageAlias, appliedQqBound, appliedQuery, appliedStatus]);
  const sort = normalizeSort(searchParams.get('sort'));
  const offset = normalizeOffset(searchParams.get('offset'));
  const focusedPrincipalId = searchParams.get('focus') || '';
  const [users, setUsers] = useState<PortalUserItem[]>([]);
  const [summary, setSummary] = useState<PortalUsersSummary>({});
  const [total, setTotal] = useState(0);
  const [draftFilters, setDraftFilters] = useState<Filters>(appliedFilters);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastReceipt, setLastReceipt] = useState<AdminMutationReceiptPayload | null>(null);
  const [receiptOpen, setReceiptOpen] = useState(false);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const [loadedRequestKey, setLoadedRequestKey] = useState('');
  const [pendingUser, setPendingUser] = useState<PortalUserItem | null>(null);
  const [disableReason, setDisableReason] = useState('');
  const [savingPrincipalId, setSavingPrincipalId] = useState<string | null>(null);
  const [auditUser, setAuditUser] = useState<PortalUserItem | null>(null);
  const [auditDetail, setAuditDetail] = useState<PortalUserAuditDetail | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [selectedPrincipalIds, setSelectedPrincipalIds] = useState<string[]>([]);
  const [batchDisableOpen, setBatchDisableOpen] = useState(false);
  const [batchDisableReason, setBatchDisableReason] = useState('');
  const [batchSaving, setBatchSaving] = useState(false);
  const activeRequestKeyRef = useRef('');
  const requestSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  const requestKey = useMemo(() => buildQuery(appliedFilters, offset), [appliedFilters, offset]);

  const updateDirectoryUrl = useCallback((changes: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParamsKey);
    Object.entries(changes).forEach(([key, value]) => {
      if (!value || (key === 'sort' && value === 'access_risk')) params.delete(key);
      else params.set(key, value);
    });
    const next = params.toString();
    router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
  }, [pathname, router, searchParamsKey]);

  const loadUsers = useCallback(async (force = false) => {
    if (!force && activeRequestKeyRef.current === requestKey) return;
    activeRequestKeyRef.current = requestKey;
    const sequence = ++requestSequenceRef.current;
    if (hasLoadedRef.current) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/admin/portal-users?${requestKey}`, { credentials: 'include', cache: 'no-store' });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('admin.portal_users.load_failed', {}, 'Failed to load Portal users.'));
      }
      if (sequence !== requestSequenceRef.current) return;
      const data = (payload.data || {}) as PortalUsersResponse;
      setUsers(Array.isArray(data.items) ? data.items : []);
      setSummary(data.summary || {});
      setTotal(Number(data.total || 0));
      setLoadedAt(new Date());
      setLoadedRequestKey(requestKey);
      hasLoadedRef.current = true;
      setHasLoaded(true);
      setSelectedPrincipalIds((current) => {
        const nextIds = new Set((data.items || []).map((item) => item.principal_id));
        return current.filter((principalId) => nextIds.has(principalId));
      });
    } catch (err) {
      if (sequence !== requestSequenceRef.current) return;
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('admin.portal_users.load_failed', {}, 'Failed to load Portal users.')));
    } finally {
      if (sequence === requestSequenceRef.current) {
        activeRequestKeyRef.current = '';
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [requestKey, t]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    setDraftFilters(appliedFilters);
  }, [appliedFilters]);

  const sortedUsers = useMemo(() => sortPortalUsers(users, sort), [sort, users]);
  const selectedUser = sortedUsers.find((user) => user.principal_id === focusedPrincipalId) || sortedUsers[0] || null;
  const pageAccessIssues = sortedUsers.filter((user) => portalUserRisk(user) === 'access_issue').length;
  const pageOnboarding = sortedUsers.filter((user) => portalUserRisk(user) === 'onboarding').length;

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    updateDirectoryUrl({
      q: draftFilters.q.trim() || null,
      status: draftFilters.status || null,
      package_alias: draftFilters.package_alias.trim() || null,
      qq_bound: draftFilters.qq_bound || null,
      offset: null,
      focus: null,
    });
  };

  const clearFilters = () => {
    setDraftFilters({
      q: '',
      status: '',
      package_alias: '',
      qq_bound: '',
    });
    updateDirectoryUrl({ q: null, status: null, package_alias: null, qq_bound: null, sort: null, offset: null, focus: null });
  };

  const activeUsers = sortedUsers.filter((user) => user.status !== 'disabled');
  const selectedActiveUsers = sortedUsers.filter((user) => selectedPrincipalIds.includes(user.principal_id));
  const allActiveSelected =
    activeUsers.length > 0 && activeUsers.every((user) => selectedPrincipalIds.includes(user.principal_id));

  const toggleUserSelection = (principalId: string) => {
    setSelectedPrincipalIds((current) =>
      current.includes(principalId)
        ? current.filter((item) => item !== principalId)
        : [...current, principalId]
    );
  };

  const toggleAllActiveUsers = () => {
    if (allActiveSelected) {
      setSelectedPrincipalIds([]);
      return;
    }
    setSelectedPrincipalIds(activeUsers.map((user) => user.principal_id));
  };

  const disableUser = async (user: PortalUserItem) => {
    setSavingPrincipalId(user.principal_id);
    setActionError(null);
    setLastReceipt(null);
    try {
      const response = await fetch(
        `/api/admin/portal-users/${encodeURIComponent(user.principal_id)}/disable`,
        {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reason: disableReason.trim() }),
        }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('admin.portal_users.disable_failed', {}, 'Failed to disable user.'));
      }
      const data = (payload.data || {}) as PortalUserDisableResult;
      setUsers((current) =>
        current.map((item) =>
          item.principal_id === user.principal_id
            ? {
                ...item,
                status: 'disabled',
                membership_status: 'revoked',
                qq_bound: false,
                qq_binding_count: 0,
                session_version: Number(data.session_version || item.session_version),
              }
            : item
        )
      );
      setLastReceipt(data.receipt || null);
      updateDirectoryUrl({ focus: user.principal_id });
      toast.success(
        t('admin.portal_users.disable_notice', { user: user.email || user.principal_id }, '{{user}} was disabled. Existing Portal sessions and QQ bindings were revoked.'),
        t('admin.portal_users.disable_success_title', {}, 'User disabled')
      );
      setDisableReason('');
      void loadUsers(true);
    } catch (err) {
      setActionError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('admin.portal_users.disable_failed', {}, 'Failed to disable user.')));
    } finally {
      setSavingPrincipalId(null);
    }
  };

  const loadAuditDetail = async (user: PortalUserItem) => {
    setAuditUser(user);
    setAuditDetail(null);
    setAuditError(null);
    setAuditLoading(true);
    try {
      const response = await fetch(
        `/api/admin/portal-users/${encodeURIComponent(user.principal_id)}/audit?limit=50`,
        { credentials: 'include' }
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('admin.portal_users.audit_load_failed', {}, 'Failed to load user audit.'));
      }
      setAuditDetail((payload.data || {}) as PortalUserAuditDetail);
    } catch (err) {
      setAuditError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('admin.portal_users.audit_load_failed', {}, 'Failed to load user audit.')));
    } finally {
      setAuditLoading(false);
    }
  };

  const batchDisableUsers = async () => {
    const principalIds = selectedActiveUsers.map((user) => user.principal_id);
    const reason = batchDisableReason.trim();
    if (!reason) {
      setActionError(t('admin.portal_users.batch_reason_required', {}, 'Batch disable requires a reason.'));
      return;
    }
    if (principalIds.length === 0) {
      setActionError(t('admin.portal_users.batch_select_required', {}, 'Select at least one active user.'));
      return;
    }
    setBatchSaving(true);
    setActionError(null);
    setLastReceipt(null);
    try {
      const response = await fetch('/api/admin/portal-users/batch-disable', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          principal_ids: principalIds,
          reason,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('admin.portal_users.batch_disable_failed', {}, 'Batch disable failed.'));
      }
      const data = (payload.data || {}) as BatchDisableResult;
      const disabledIds = new Set(
        (data.items || [])
          .filter((item) => item.outcome === 'disabled' || item.outcome === 'already_disabled')
          .map((item) => String(item.principal_id || ''))
          .filter(Boolean)
      );
      setUsers((current) =>
        current.map((item) =>
          disabledIds.has(item.principal_id)
            ? {
                ...item,
                status: 'disabled',
                membership_status: 'revoked',
                qq_bound: false,
                qq_binding_count: 0,
              }
            : item
        )
      );
      setSelectedPrincipalIds([]);
      setBatchDisableOpen(false);
      setBatchDisableReason('');
      const attempted = Number(data.totals?.attempted || principalIds.length);
      const failed = Number(data.totals?.failed || 0);
      setLastReceipt(data.receipt || null);
      toast.success(
        t('admin.portal_users.batch_disable_notice', { attempted: String(attempted), failed: String(failed) }, 'Batch disable processed {{attempted}} user(s), failed {{failed}}.'),
        t('admin.portal_users.batch_disable_success_title', {}, 'Batch disable complete')
      );
      void loadUsers(true);
    } catch (err) {
      setActionError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('admin.portal_users.batch_disable_failed', {}, 'Batch disable failed.')));
    } finally {
      setBatchSaving(false);
    }
  };

  if (error && !hasLoaded) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div role="alert" className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-rose-600">{t('common.error')}</h2>
          <p className="mb-6 text-slate-600 dark:text-slate-400">{error}</p>
          <button type="button" className="btn btn-primary" onClick={() => void loadUsers(true)}>{t('common.retry')}</button>
        </div>
      </div>
    );
  }
  if (loading && !hasLoaded) return <LoadingFallback />;

  const hasFilters = Boolean(appliedFilters.q || appliedFilters.status || appliedFilters.package_alias || appliedFilters.qq_bound || sort !== 'access_risk');
  const isShowingRetainedResults = Boolean(error && loadedRequestKey && loadedRequestKey !== requestKey);

  return (
    <BackofficePageStack className="space-y-5">
      <BackofficeLayer
        eyebrow={t('admin.portal_users.eyebrow', {}, 'Portal Users')}
        title={t('admin.portal_users.title', {}, 'Self-registered users')}
        description={t('admin.portal_users.workspace_desc', {}, 'Find self-registered users with access inconsistencies, inspect one identity, then open its existing customer or audit context.')}
        actions={(
          <>
            <button type="button" className="btn btn-secondary" disabled={refreshing} onClick={() => void loadUsers(true)}>{refreshing ? t('common.loading', {}, 'Loading...') : t('admin.portal_users.refresh_action', {}, 'Refresh users')}</button>
            <AdminLatestOperationButton receipt={lastReceipt} isOpen={receiptOpen} onOpen={() => setReceiptOpen(true)} onClose={() => setReceiptOpen(false)} title={t('admin.receipt_latest', {}, 'Latest operation')} triggerLabel={t('admin.receipt_latest', {}, 'Latest operation')} />
          </>
        )}
      />

      {error ? (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200 sm:flex-row sm:items-center sm:justify-between">
          <span>{error}{isShowingRetainedResults ? <span className="mt-1 block text-xs">{t('admin.portal_users.retained_notice', {}, 'Showing the last successfully loaded page; it may not match the current filters.')}</span> : null}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadUsers(true)}>{t('common.retry')}</button>
        </div>
      ) : null}
      {actionError ? <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200">{actionError}</div> : null}

      <BackofficeSummaryStrip items={[
        { label: t('admin.portal_users.status_active', {}, 'Active'), value: formatInteger(summary.active || 0), toneClassName: summary.active ? 'text-emerald-600 dark:text-emerald-300' : undefined },
        { label: t('admin.portal_users.status_disabled', {}, 'Disabled'), value: formatInteger(summary.disabled || 0) },
        { label: t('admin.portal_users.page_access_issues', {}, 'Page access issues'), value: formatInteger(pageAccessIssues), toneClassName: pageAccessIssues ? 'text-rose-600 dark:text-rose-300' : undefined },
        { label: t('admin.portal_users.page_onboarding', {}, 'Page awaiting login'), value: formatInteger(pageOnboarding), toneClassName: pageOnboarding ? 'text-amber-600 dark:text-amber-300' : undefined },
        { label: t('common.updated_at', {}, 'Updated'), value: loadedAt ? formatDate(loadedAt.toISOString()) : t('common.unknown', {}, 'Unknown') },
      ]} />

      {selectedPrincipalIds.length > 0 ? (
        <div className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-100 sm:flex-row sm:items-center sm:justify-between">
          <span>{t('admin.portal_users.batch_selected_count', { count: String(selectedPrincipalIds.length) }, '{{count}} active users selected.')}</span>
          <div className="flex gap-2">
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => setSelectedPrincipalIds([])}>{t('common.clear', {}, 'Clear')}</button>
            <button type="button" className="btn btn-danger btn-sm" onClick={() => setBatchDisableOpen(true)}>{t('admin.portal_users.batch_disable', {}, 'Batch disable')}</button>
          </div>
        </div>
      ) : null}

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(20rem,0.72fr)]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div className="space-y-4 border-b border-slate-200/80 px-5 py-5 dark:border-slate-800 md:px-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-slate-950 dark:text-white">{t('admin.portal_users.directory_title', {}, 'Portal user directory')}</h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('admin.portal_users.directory_desc', {}, 'The service filters and paginates self-registered users; access-risk ordering applies to the current page.')}</p>
              </div>
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400" role="status">{t('admin.portal_users.result_count', { visible: formatInteger(sortedUsers.length), total: formatInteger(total) }, `${formatInteger(sortedUsers.length)} on this page · ${formatInteger(total)} total`)}</p>
            </div>

            <div className="flex flex-wrap items-center gap-2" aria-label={t('admin.portal_users.status_filter_label', {}, 'User status')}>
              {['', 'active', 'disabled'].map((status) => (
                <button key={status || 'all'} type="button" aria-pressed={appliedFilters.status === status} onClick={() => updateDirectoryUrl({ status: status || null, offset: null, focus: null })} className={cn('cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium transition', appliedFilters.status === status ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200' : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600')}>
                  {status === 'active' ? t('admin.portal_users.status_active', {}, 'Active') : status === 'disabled' ? t('admin.portal_users.status_disabled', {}, 'Disabled') : t('admin.portal_users.status_all', {}, 'All statuses')}
                </button>
              ))}
              <label className="ml-auto flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
                <input type="checkbox" checked={allActiveSelected} disabled={activeUsers.length === 0} onChange={toggleAllActiveUsers} aria-label={t('admin.portal_users.select_all_active', {}, 'Select all active users on this page')} />
                {t('admin.portal_users.select_all_active_short', {}, 'Select page')}
              </label>
            </div>

            <form onSubmit={applyFilters} className="grid gap-3 md:grid-cols-2 2xl:grid-cols-[minmax(13rem,1.2fr)_minmax(9rem,0.7fr)_auto]">
              <label className="text-sm text-slate-700 dark:text-slate-200"><span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.portal_users.search_label', {}, 'Search users')}</span><input value={draftFilters.q} onChange={(event) => setDraftFilters((current) => ({ ...current, q: event.target.value }))} className="input w-full" placeholder={t('admin.portal_users.search_placeholder', {}, 'Email, account, site, or domain')} /></label>
              <label className="text-sm text-slate-700 dark:text-slate-200"><span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.portal_users.package_filter_label', {}, 'Package filter')}</span><input value={draftFilters.package_alias} onChange={(event) => setDraftFilters((current) => ({ ...current, package_alias: event.target.value }))} className="input w-full" placeholder={t('common.package', {}, 'Package')} /></label>
              <div className="flex items-end gap-2 md:col-span-2 2xl:col-span-1"><button type="submit" className="btn btn-primary flex-1 2xl:flex-none">{t('common.apply', {}, 'Apply')}</button><button type="button" className="btn btn-secondary flex-1 2xl:flex-none" disabled={!hasFilters && !draftFilters.q && !draftFilters.package_alias && !draftFilters.qq_bound} onClick={clearFilters}>{t('common.clear_filters', {}, 'Clear filters')}</button></div>
              <details className="md:col-span-2 2xl:col-span-3">
                <summary className="cursor-pointer text-sm font-medium text-slate-600 hover:text-slate-950 dark:text-slate-300 dark:hover:text-white">{t('admin.portal_users.advanced_filters', {}, 'More filters')}</summary>
                <div className="mt-3 grid gap-3 md:grid-cols-2">
                  <label className="text-sm text-slate-700 dark:text-slate-200"><span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.portal_users.qq_filter_label', {}, 'QQ binding status')}</span><select value={draftFilters.qq_bound} onChange={(event) => setDraftFilters((current) => ({ ...current, qq_bound: event.target.value }))} className="input w-full"><option value="">{t('admin.portal_users.qq_all', {}, 'All QQ')}</option><option value="true">{t('admin.portal_users.qq_bound', {}, 'Bound')}</option><option value="false">{t('admin.portal_users.qq_unbound', {}, 'Not bound')}</option></select></label>
                  <label className="text-sm text-slate-700 dark:text-slate-200"><span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.portal_users.sort_label', {}, 'Sort')}</span><select value={sort} onChange={(event) => updateDirectoryUrl({ sort: normalizeSort(event.target.value), focus: null })} className="input w-full"><option value="access_risk">{t('admin.portal_users.sort_access_risk', {}, 'Current-page access risk')}</option><option value="recent_login">{t('admin.portal_users.sort_recent_login', {}, 'Recent login')}</option><option value="recent_registration">{t('admin.portal_users.sort_recent_registration', {}, 'Recent registration')}</option></select></label>
                </div>
              </details>
            </form>
          </div>

          {sortedUsers.length ? (
            <div role="list" aria-label={t('admin.portal_users.list_label', {}, 'Portal user list')}>
              {sortedUsers.map((user) => {
                const risk = portalUserRisk(user);
                const selected = selectedUser?.principal_id === user.principal_id;
                const riskReason = risk === 'access_issue' ? t('admin.portal_users.reason_access_issue', {}, 'Identity, membership, customer, site, or subscription state is inconsistent.') : risk === 'onboarding' ? t('admin.portal_users.reason_onboarding', {}, 'The user is provisioned but has no recorded Portal login yet.') : risk === 'disabled' ? t('admin.portal_users.reason_disabled', {}, 'Portal sessions and account access have been revoked.') : t('admin.portal_users.reason_active', {}, 'Identity, membership, site, and subscription access are currently active.');
                return (
                  <article key={user.principal_id} role="listitem" data-ui="portal-user-directory-item" className={cn('grid gap-4 border-b border-slate-200/80 px-5 py-5 transition last:border-b-0 dark:border-slate-800 md:grid-cols-[auto_minmax(11rem,0.9fr)_minmax(13rem,1.1fr)] md:items-center md:px-6 2xl:grid-cols-[auto_minmax(12rem,1fr)_minmax(14rem,1.2fr)_minmax(9rem,0.75fr)_auto]', selected ? 'bg-blue-50/65 dark:bg-blue-950/15' : 'hover:bg-slate-50/70 dark:hover:bg-slate-950/35')}>
                    <input type="checkbox" checked={selectedPrincipalIds.includes(user.principal_id)} disabled={user.status === 'disabled'} onChange={() => toggleUserSelection(user.principal_id)} aria-label={t('admin.portal_users.select_user', { user: user.email || user.principal_id }, 'Select {{user}}')} />
                    <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate font-semibold text-slate-950 dark:text-white">{user.email || t('admin.portal_users.email_missing', {}, 'Email missing')}</h3><BackofficeStatusBadge label={user.status === 'disabled' ? t('admin.portal_users.status_disabled', {}, 'Disabled') : t('admin.portal_users.status_active', {}, 'Active')} status={user.status} /></div><div className="mt-2 text-xs text-slate-500 dark:text-slate-400"><BackofficeIdentifier value={user.principal_id} /></div><p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{sourceLabel(user.source, t)}</p></div>
                    <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><span className={cn('inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', riskToneClassName(risk))}>{t(`admin.portal_users.risk_${risk}`, {}, risk)}</span><span className="text-xs font-medium text-slate-500 dark:text-slate-400">{user.display_package_label || user.package_alias || user.plan_id || t('admin.portal_users.no_coverage', {}, 'No coverage')}</span></div><p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{riskReason}</p></div>
                    <dl className="grid gap-2 text-xs text-slate-600 dark:text-slate-300"><div className="flex justify-between gap-3"><dt>{t('common.account', {}, 'Account')}</dt><dd className="max-w-32 truncate font-semibold text-slate-950 dark:text-white">{user.account_name || t('admin.portal_users.account_unbound', {}, 'No account bound')}</dd></div><div className="flex justify-between gap-3"><dt>{t('common.site', {}, 'Site')}</dt><dd className="max-w-32 truncate font-semibold text-slate-950 dark:text-white">{user.site_name || t('admin.portal_users.site_unbound', {}, 'No site bound')}</dd></div><div className="flex justify-between gap-3"><dt>QQ</dt><dd className="font-semibold text-slate-950 dark:text-white">{user.qq_bound ? t('admin.portal_users.qq_bound', {}, 'Bound') : t('admin.portal_users.qq_unbound', {}, 'Not bound')}</dd></div></dl>
                    <div className="flex md:justify-end"><button type="button" className="btn btn-primary btn-sm" aria-pressed={selected} aria-controls="portal-user-inspector" onClick={() => updateDirectoryUrl({ focus: user.principal_id })}>{t('admin.portal_users.inspect_action', {}, 'Inspect')}</button></div>
                  </article>
                );
              })}
            </div>
          ) : <BackofficeEmptyState className="m-5 md:m-6" title={t('admin.portal_users.empty_title', {}, 'No self-registered users')} description={t('admin.portal_users.empty_desc', {}, 'New users will appear here after they register through Portal and open the Free package.')} action={hasFilters ? <button type="button" className="btn btn-secondary btn-sm" onClick={clearFilters}>{t('common.clear_filters', {}, 'Clear filters')}</button> : null} />}
          <ListPagination offset={offset} limit={PAGE_SIZE} total={total} isLoading={refreshing} onOffsetChange={(nextOffset) => updateDirectoryUrl({ offset: String(nextOffset), focus: null })} />
        </BackofficeSectionPanel>

        <aside id="portal-user-inspector" className="xl:sticky xl:top-24" aria-live="polite">
          <BackofficeSectionPanel className="space-y-5">
            <div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{t('admin.portal_users.inspector_eyebrow', {}, 'Inspector')}</p><h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{t('admin.portal_users.inspector_title', {}, 'Current Portal user')}</h2></div>{selectedUser ? <span className={cn('inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', riskToneClassName(portalUserRisk(selectedUser)))}>{t(`admin.portal_users.risk_${portalUserRisk(selectedUser)}`, {}, portalUserRisk(selectedUser))}</span> : null}</div>
            {selectedUser ? (
              <div className="space-y-5">
                <div><p className="break-all text-base font-semibold text-slate-950 dark:text-white">{selectedUser.email || t('admin.portal_users.email_missing', {}, 'Email missing')}</p><div className="mt-1 text-xs text-slate-500 dark:text-slate-400"><BackofficeIdentifier value={selectedUser.principal_id} full /></div></div>
                <dl className="grid gap-2 text-sm text-slate-600 dark:text-slate-300">{[[t('common.status'), selectedUser.status === 'disabled' ? t('admin.portal_users.status_disabled', {}, 'Disabled') : t('admin.portal_users.status_active', {}, 'Active')],[t('common.account', {}, 'Account'), selectedUser.account_name || t('admin.portal_users.account_unbound', {}, 'No account bound')],[t('admin.portal_users.membership_label', {}, 'Membership'), selectedUser.membership_status || t('admin.portal_users.no_membership_status', {}, 'No membership status')],[t('common.site', {}, 'Site'), selectedUser.site_name || t('admin.portal_users.site_unbound', {}, 'No site bound')],[t('common.package', {}, 'Package'), selectedUser.display_package_label || selectedUser.package_alias || t('admin.portal_users.no_coverage', {}, 'No coverage')],[t('common.subscription', {}, 'Subscription'), selectedUser.subscription_status || t('admin.portal_users.no_subscription', {}, 'No subscription')],['QQ', selectedUser.qq_bound ? t('admin.portal_users.qq_bound', {}, 'Bound') : t('admin.portal_users.qq_unbound', {}, 'Not bound')],[t('admin.portal_users.logged_in_at', {}, 'Login'), dateLabel(selectedUser.last_login_at, t)],[t('admin.portal_users.session_version_label', {}, 'Session version'), String(selectedUser.session_version)]].map(([label, value]) => <div key={label} className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 last:border-b-0 dark:border-slate-800"><dt>{label}</dt><dd className="max-w-48 truncate text-right font-semibold text-slate-950 dark:text-white">{value}</dd></div>)}</dl>
                <div className="flex flex-wrap gap-2">{selectedUser.account_id ? <Link href={`/admin/accounts/${encodeURIComponent(selectedUser.account_id)}`} className="btn btn-primary btn-sm">{t('admin.portal_users.open_customer_action', {}, 'Open customer')}</Link> : null}<button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadAuditDetail(selectedUser)}>{t('admin.portal_users.audit_action', {}, 'Audit')}</button>{selectedUser.site_id ? <Link href={`/admin/sites/${encodeURIComponent(selectedUser.site_id)}`} className="btn btn-secondary btn-sm">{t('admin.portal_users.open_site', {}, 'Open site')}</Link> : null}</div>
                <details className="border-t border-slate-200/80 pt-4 text-sm dark:border-slate-800"><summary className="cursor-pointer font-semibold text-slate-800 dark:text-slate-100">{t('portal.support_information', {}, 'Support information')}</summary><div className="mt-3 space-y-2 text-xs text-slate-500 dark:text-slate-400"><BackofficeIdentifier value={selectedUser.principal_id} full />{selectedUser.account_id ? <BackofficeIdentifier value={selectedUser.account_id} full /> : null}{selectedUser.site_id ? <BackofficeIdentifier value={selectedUser.site_id} full /> : null}{selectedUser.wordpress_url ? <p className="break-all">{selectedUser.wordpress_url}</p> : null}</div></details>
                {selectedUser.status !== 'disabled' ? <details className="border-t border-rose-200/80 pt-4 text-sm dark:border-rose-900/50"><summary className="cursor-pointer font-semibold text-rose-700 dark:text-rose-300">{t('admin.portal_users.access_actions_title', {}, 'Access actions')}</summary><p className="mt-2 text-xs leading-5 text-slate-500 dark:text-slate-400">{t('admin.portal_users.disable_boundary', {}, 'Disabling revokes Portal sessions, account memberships, and QQ quick-login bindings. It does not delete the customer or WordPress user.')}</p><button type="button" className="btn btn-danger btn-sm mt-3" disabled={savingPrincipalId === selectedUser.principal_id} onClick={() => setPendingUser(selectedUser)}>{savingPrincipalId === selectedUser.principal_id ? t('admin.portal_users.processing', {}, 'Processing') : t('admin.portal_users.disable_action', {}, 'Disable')}</button></details> : null}
                <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{t('admin.portal_users.inspector_boundary', {}, 'This directory manages the external Cloud user identity and its Portal access evidence only. It does not create roles, permissions, payments, entitlements, or WordPress users.')}</p>
              </div>
            ) : <p className="text-sm text-slate-600 dark:text-slate-300">{t('admin.portal_users.inspector_empty', {}, 'No Portal user is visible on this page.')}</p>}
          </BackofficeSectionPanel>
        </aside>
      </div>

      {pendingUser ? (
        <ConfirmModal
          isOpen={Boolean(pendingUser)}
          title={t('admin.portal_users.confirm_disable_title', {}, 'Confirm disable user')}
          message={t(
            'admin.portal_users.confirm_disable_message',
            { user: pendingUser.email || pendingUser.principal_id },
            'After disabling {{user}}, existing Portal sessions, account memberships, and QQ quick-login bindings will be revoked.'
          )}
          confirmLabel={t('common.confirm', {}, 'Confirm')}
          cancelLabel={t('common.cancel', {}, 'Cancel')}
          variant="danger"
          onClose={() => {
            setPendingUser(null);
            setDisableReason('');
          }}
          onConfirm={() => {
            void disableUser(pendingUser);
          }}
        >
          <textarea
            value={disableReason}
            onChange={(event) => setDisableReason(event.target.value)}
            className="input min-h-[5.5rem]"
            placeholder={t('admin.portal_users.reason_optional', {}, 'Reason, optional')}
          />
        </ConfirmModal>
      ) : null}

      {batchDisableOpen ? (
        <Modal
          isOpen={batchDisableOpen}
          title={t('admin.portal_users.batch_disable_title', {}, 'Batch disable users')}
          description={t('admin.portal_users.batch_disable_desc', { count: String(selectedPrincipalIds.length) }, 'Will disable {{count}} user(s).')}
          size="md"
          onClose={() => {
            if (!batchSaving) {
              setBatchDisableOpen(false);
              setBatchDisableReason('');
            }
          }}
          footer={
            <>
              <button
                type="button"
                className="btn btn-secondary"
                disabled={batchSaving}
                onClick={() => {
                  setBatchDisableOpen(false);
                  setBatchDisableReason('');
                }}
              >
                {t('common.cancel', {}, 'Cancel')}
              </button>
              <button
                type="button"
                className="btn btn-danger"
                disabled={batchSaving || !batchDisableReason.trim() || selectedPrincipalIds.length === 0}
                onClick={() => {
                  void batchDisableUsers();
                }}
              >
                {batchSaving ? t('admin.portal_users.processing', {}, 'Processing') : t('admin.portal_users.confirm_disable', {}, 'Confirm disable')}
              </button>
            </>
          }
        >
          <div className="space-y-4">
            <p className="text-sm leading-6 text-slate-600 dark:text-slate-300">
              {t('admin.portal_users.batch_disable_body', {}, 'Batch disable invalidates selected users Portal sessions and revokes account memberships and QQ quick-login bindings.')}
            </p>
            <textarea
              value={batchDisableReason}
              onChange={(event) => setBatchDisableReason(event.target.value)}
              className="input min-h-[5.5rem]"
              placeholder={t('admin.portal_users.reason_required', {}, 'Reason, required')}
            />
          </div>
        </Modal>
      ) : null}

      {auditUser ? (
        <Modal
          isOpen={Boolean(auditUser)}
          title={t('admin.portal_users.audit_modal_title', {}, 'User audit detail')}
          description={auditUser.email || auditUser.principal_id}
          size="xl"
          onClose={() => {
            setAuditUser(null);
            setAuditDetail(null);
            setAuditError(null);
          }}
          footer={
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => {
                setAuditUser(null);
                setAuditDetail(null);
                setAuditError(null);
              }}
            >
              {t('common.close', {}, 'Close')}
            </button>
          }
        >
          {auditLoading ? (
            <LoadingFallback />
          ) : auditError ? (
            <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/25 dark:text-rose-200">
              {auditError}
            </div>
          ) : (
            <div className="space-y-5">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {[
                  [t('admin.portal_users.audit_metric_events', {}, 'Events'), String(auditDetail?.summary?.events || 0)],
                  [t('admin.portal_users.audit_metric_registration', {}, 'Registration events'), String(auditDetail?.summary?.registration_events || 0)],
                  [t('admin.portal_users.audit_metric_disable', {}, 'Disable events'), String(auditDetail?.summary?.disable_events || 0)],
                  [t('admin.portal_users.audit_metric_success', {}, 'Succeeded'), String(auditDetail?.summary?.succeeded || 0)],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45"
                  >
                    <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                      {label}
                    </div>
                    <div className="mt-2 text-lg font-semibold text-slate-950 dark:text-white">{value}</div>
                  </div>
                ))}
              </div>

              {auditDetail?.summary?.latest_disable_reason ? (
                <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/25 dark:text-amber-200">
                  {t('admin.portal_users.latest_disable_reason', {}, 'Latest disable reason')}: {auditDetail.summary.latest_disable_reason}
                </div>
              ) : null}

              <div className="space-y-3">
                {(auditDetail?.items || []).length === 0 ? (
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-6 text-center text-sm text-slate-600 dark:border-slate-800 dark:bg-slate-950/45 dark:text-slate-300">
                    {t('admin.portal_users.no_audit_events', {}, 'No service audit events for this user.')}
                  </div>
                ) : (
                  (auditDetail?.items || []).map((event) => {
                    const detail = payloadText(event.payload, t);
                    return (
                      <div
                        key={event.event_id}
                        className="rounded-2xl border border-slate-200 bg-white px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45"
                      >
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                          <div>
                            <div className="font-semibold text-slate-950 dark:text-white">
                              {auditEventLabel(event.event_kind, t)}
                            </div>
                            <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                              {dateLabel(event.created_at, t)} · {event.actor_kind || 'unknown'} · {event.actor_ref || t('admin.portal_users.no_actor', {}, 'No actor')}
                            </div>
                          </div>
                          <BackofficeStatusBadge
                            label={event.outcome || 'unknown'}
                            status={event.outcome || 'inactive'}
                          />
                        </div>
                        {detail ? (
                          <div className="mt-3 text-sm text-slate-700 dark:text-slate-200">{detail}</div>
                        ) : null}
                        <details className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                          <summary className="cursor-pointer font-medium text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
                            {t('admin.portal_users.request_technical_detail', {}, 'Request technical detail')}
                          </summary>
                          <div className="mt-2 grid gap-2 rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-900/45 sm:grid-cols-2">
                            <div>scope：{event.scope_kind || '-'} / {event.scope_id || '-'}</div>
                            <div>trace：{event.trace_id || '-'}</div>
                            <div>path：{event.method || 'GET'} {event.path || '-'}</div>
                            <div>idempotency：{event.idempotency_key || '-'}</div>
                          </div>
                        </details>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}
        </Modal>
      ) : null}
    </BackofficePageStack>
  );
}

export default function AdminPortalUsersPage() {
  return <Suspense fallback={<LoadingFallback />}><PortalUsersContent /></Suspense>;
}
