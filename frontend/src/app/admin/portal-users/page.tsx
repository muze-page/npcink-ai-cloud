'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { AdminMutationReceipt, type AdminMutationReceiptPayload } from '@/components/admin/AdminMutationReceipt';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ListPagination } from '@/components/ui/ListPagination';
import { ConfirmModal, Modal } from '@/components/ui/Modal';
import { useLocale } from '@/contexts/LocaleContext';
import { cn, formatDate } from '@/lib/utils';
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

export default function AdminPortalUsersPage() {
  const { t } = useLocale();
  const [users, setUsers] = useState<PortalUserItem[]>([]);
  const [summary, setSummary] = useState<PortalUsersSummary>({});
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [filters, setFilters] = useState<Filters>({
    q: '',
    status: '',
    package_alias: '',
    qq_bound: '',
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastReceipt, setLastReceipt] = useState<AdminMutationReceiptPayload | null>(null);
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

  const loadUsers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`/api/admin/portal-users?${buildQuery(filters, offset)}`, {
        credentials: 'include',
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || t('admin.portal_users.load_failed', {}, 'Failed to load Portal users.'));
      }
      const data = (payload.data || {}) as PortalUsersResponse;
      setUsers(Array.isArray(data.items) ? data.items : []);
      setSummary(data.summary || {});
      setTotal(Number(data.total || 0));
      setSelectedPrincipalIds((current) => {
        const nextIds = new Set((data.items || []).map((item) => item.principal_id));
        return current.filter((principalId) => nextIds.has(principalId));
      });
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('admin.portal_users.load_failed', {}, 'Failed to load Portal users.')));
    } finally {
      setLoading(false);
    }
  }, [filters, offset, t]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  const visibleMetricItems = useMemo(
    () => [
      { label: t('admin.portal_users.metric_filtered', {}, 'Filtered'), value: total },
      { label: t('admin.portal_users.status_active', {}, 'Active'), value: summary.active || 0, toneClassName: 'text-emerald-700 dark:text-emerald-200' },
      { label: t('admin.portal_users.status_disabled', {}, 'Disabled'), value: summary.disabled || 0, toneClassName: 'text-slate-700 dark:text-slate-200' },
      { label: t('admin.portal_users.metric_qq_bound', {}, 'QQ bound'), value: summary.qq_bound || 0, toneClassName: 'text-blue-700 dark:text-blue-200' },
    ],
    [summary.active, summary.disabled, summary.qq_bound, t, total]
  );

  const updateFilter = (key: keyof Filters, value: string) => {
    setOffset(0);
    setFilters((current) => ({ ...current, [key]: value }));
  };

  const clearFilters = () => {
    setOffset(0);
    setFilters({
      q: '',
      status: '',
      package_alias: '',
      qq_bound: '',
    });
  };

  const activeUsers = users.filter((user) => user.status !== 'disabled');
  const selectedActiveUsers = users.filter((user) => selectedPrincipalIds.includes(user.principal_id));
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
    setNotice(null);
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
      setNotice(t('admin.portal_users.disable_notice', { user: user.email || user.principal_id }, '{{user}} was disabled. Existing Portal sessions and QQ bindings were revoked.'));
      setDisableReason('');
      void loadUsers();
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
    setNotice(null);
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
      setNotice(t('admin.portal_users.batch_disable_notice', { attempted: String(attempted), failed: String(failed) }, 'Batch disable processed {{attempted}} user(s), failed {{failed}}.'));
      void loadUsers();
    } catch (err) {
      setActionError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('admin.portal_users.batch_disable_failed', {}, 'Batch disable failed.')));
    } finally {
      setBatchSaving(false);
    }
  };

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.portal_users.eyebrow', {}, 'Portal Users')}
        title={t('admin.portal_users.title', {}, 'Self-registered users')}
        description={t('admin.portal_users.desc', {}, 'Review Free accounts, sites, packages, and QQ binding status created through Portal self-registration.')}
        actions={
          <div className="grid w-full gap-3 md:grid-cols-[minmax(12rem,1.5fr)_minmax(8rem,0.8fr)_minmax(8rem,0.8fr)_minmax(8rem,0.8fr)_auto]">
            <input
              value={filters.q}
              onChange={(event) => updateFilter('q', event.target.value)}
              className="input h-11"
              placeholder={t('admin.portal_users.search_placeholder', {}, 'Email, account, site, or domain')}
            />
            <select
              value={filters.status}
              onChange={(event) => updateFilter('status', event.target.value)}
              className="input h-11"
              aria-label={t('admin.portal_users.status_filter_label', {}, 'User status')}
            >
              <option value="">{t('admin.portal_users.status_all', {}, 'All statuses')}</option>
              <option value="active">{t('admin.portal_users.status_active', {}, 'Active')}</option>
              <option value="disabled">{t('admin.portal_users.status_disabled', {}, 'Disabled')}</option>
            </select>
            <input
              value={filters.package_alias}
              onChange={(event) => updateFilter('package_alias', event.target.value)}
              className="input h-11"
              placeholder={t('common.package', {}, 'Package')}
            />
            <select
              value={filters.qq_bound}
              onChange={(event) => updateFilter('qq_bound', event.target.value)}
              className="input h-11"
              aria-label={t('admin.portal_users.qq_filter_label', {}, 'QQ binding status')}
            >
              <option value="">{t('admin.portal_users.qq_all', {}, 'All QQ')}</option>
              <option value="true">{t('admin.portal_users.qq_bound', {}, 'Bound')}</option>
              <option value="false">{t('admin.portal_users.qq_unbound', {}, 'Not bound')}</option>
            </select>
            <button type="button" onClick={clearFilters} className="btn btn-secondary h-11">
              {t('common.clear', {}, 'Clear')}
            </button>
          </div>
        }
        summary={<BackofficeMetricStrip items={visibleMetricItems} columnsClassName="xl:grid-cols-4" />}
      />

      {notice ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 dark:border-emerald-900/50 dark:bg-emerald-950/25 dark:text-emerald-200">
          {notice}
        </div>
      ) : null}
      {actionError || error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/25 dark:text-rose-200">
          {actionError || error}
        </div>
      ) : null}
      <AdminMutationReceipt receipt={lastReceipt} />

      <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white/80 px-4 py-3 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-950/45 dark:text-slate-200 sm:flex-row sm:items-center sm:justify-between">
        <div>
          {t('admin.portal_users.selected_count_prefix', {}, 'Selected')}{' '}
          <span className="font-semibold text-slate-950 dark:text-white">{selectedPrincipalIds.length}</span>{' '}
          {t('admin.portal_users.selected_count_suffix', {}, 'active user(s)')}
        </div>
        <button
          type="button"
          className="btn btn-secondary self-start sm:self-auto"
          disabled={selectedPrincipalIds.length === 0}
          onClick={() => setBatchDisableOpen(true)}
        >
          {t('admin.portal_users.batch_disable', {}, 'Batch disable')}
        </button>
      </div>

      <BackofficeSectionPanel className="overflow-hidden p-0">
        {loading ? (
          <div className="p-8">
            <LoadingFallback />
          </div>
        ) : users.length === 0 ? (
          <div className="p-8 text-center">
            <h2 className="text-lg font-semibold text-slate-950 dark:text-white">{t('admin.portal_users.empty_title', {}, 'No self-registered users')}</h2>
            <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
              {t('admin.portal_users.empty_desc', {}, 'New users will appear here after they register through Portal and open the Free package.')}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
              <thead className="bg-slate-50/80 dark:bg-slate-950/40">
                <tr>
                  <th className="w-12 px-5 py-3 text-left">
                    <input
                      type="checkbox"
                      checked={allActiveSelected}
                      disabled={activeUsers.length === 0}
                      onChange={toggleAllActiveUsers}
                      aria-label={t('admin.portal_users.select_all_active', {}, 'Select all active users on this page')}
                    />
                  </th>
                  {[
                    t('admin.portal_users.column_user', {}, 'User'),
                    t('admin.portal_users.column_account_site', {}, 'Account / Site'),
                    t('common.package', {}, 'Package'),
                    'QQ',
                    t('admin.portal_users.column_time', {}, 'Time'),
                    t('common.actions', {}, 'Actions'),
                  ].map((heading) => (
                    <th
                      key={heading}
                      className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400"
                    >
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 bg-white/75 dark:divide-slate-800 dark:bg-slate-950/25">
                {users.map((user) => (
                  <tr key={user.principal_id} className="align-top">
                    <td className="px-5 py-4">
                      <input
                        type="checkbox"
                        checked={selectedPrincipalIds.includes(user.principal_id)}
                        disabled={user.status === 'disabled'}
                        onChange={() => toggleUserSelection(user.principal_id)}
                        aria-label={t('admin.portal_users.select_user', { user: user.email || user.principal_id }, 'Select {{user}}')}
                      />
                    </td>
                    <td className="px-5 py-4">
                      <div className="space-y-2">
                        <div className="font-semibold text-slate-950 dark:text-white">
                          {user.email || t('admin.portal_users.email_missing', {}, 'Email missing')}
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <BackofficeStatusBadge
                            label={user.status === 'disabled' ? t('admin.portal_users.status_disabled', {}, 'Disabled') : t('admin.portal_users.status_active', {}, 'Active')}
                            status={user.status}
                          />
                          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600 dark:bg-slate-900 dark:text-slate-300">
                            {sourceLabel(user.source, t)}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="space-y-2">
                        <div>
                          <div className="font-medium text-slate-900 dark:text-slate-100">
                            {user.account_name || t('admin.portal_users.account_unbound', {}, 'No account bound')}
                          </div>
                          <div className="text-xs text-slate-500 dark:text-slate-400">
                            {user.membership_status || t('admin.portal_users.no_membership_status', {}, 'No membership status')}
                          </div>
                        </div>
                        <div>
                          {user.site_id ? (
                            <Link
                              href={`/admin/sites/${encodeURIComponent(user.site_id)}`}
                              className="font-medium text-blue-700 hover:text-blue-600 dark:text-blue-300"
                            >
                              {user.site_name || user.wordpress_url || t('admin.portal_users.open_site', {}, 'Open site')}
                            </Link>
                          ) : (
                            <span className="font-medium text-slate-700 dark:text-slate-200">{t('admin.portal_users.site_unbound', {}, 'No site bound')}</span>
                          )}
                          <div className="max-w-xs truncate text-xs text-slate-500 dark:text-slate-400">
                            {user.wordpress_url || t('admin.portal_users.no_site_url', {}, 'No site URL')}
                          </div>
                          <details className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                            <summary className="cursor-pointer font-medium">{t('portal.support_information', {}, 'Support information')}</summary>
                            <div className="mt-2 space-y-1">
                              <BackofficeIdentifier value={user.principal_id} full />
                              {user.account_id ? <BackofficeIdentifier value={user.account_id} full /> : null}
                              {user.site_id ? <BackofficeIdentifier value={user.site_id} full /> : null}
                            </div>
                          </details>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="space-y-2">
                        <div className="font-medium text-slate-900 dark:text-slate-100">
                          {user.display_package_label || user.package_alias || user.plan_id || t('admin.portal_users.no_coverage', {}, 'No coverage')}
                        </div>
                        <BackofficeStatusBadge
                          label={user.subscription_status || t('admin.portal_users.no_subscription', {}, 'No subscription')}
                          status={user.subscription_status || 'inactive'}
                        />
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="space-y-2">
                        <BackofficeStatusBadge
                          label={user.qq_bound ? t('admin.portal_users.qq_bound', {}, 'Bound') : t('admin.portal_users.qq_unbound', {}, 'Not bound')}
                          status={user.qq_bound ? 'active' : 'inactive'}
                        />
                        <div className="text-xs text-slate-500 dark:text-slate-400">
                          {user.qq_bound
                            ? t('admin.portal_users.qq_binding_count', { count: String(user.qq_binding_count) }, 'Bindings {{count}}')
                            : t('admin.portal_users.qq_quick_login_disabled', {}, 'Quick login not enabled')}
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-4 text-xs text-slate-600 dark:text-slate-300">
                      <div>{t('admin.portal_users.registered_at', {}, 'Registered')}: {dateLabel(user.created_at, t)}</div>
                      <div>{t('admin.portal_users.logged_in_at', {}, 'Login')}: {dateLabel(user.last_login_at, t)}</div>
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          className="btn btn-secondary"
                          onClick={() => {
                            void loadAuditDetail(user);
                          }}
                        >
                          {t('admin.portal_users.audit_action', {}, 'Audit')}
                        </button>
                        <button
                          type="button"
                          className={cn('btn btn-secondary', user.status === 'disabled' && 'opacity-60')}
                          disabled={user.status === 'disabled' || savingPrincipalId === user.principal_id}
                          onClick={() => setPendingUser(user)}
                        >
                          {savingPrincipalId === user.principal_id ? t('admin.portal_users.processing', {}, 'Processing') : t('admin.portal_users.disable_action', {}, 'Disable')}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <ListPagination
          offset={offset}
          limit={PAGE_SIZE}
          total={total}
          isLoading={loading}
          onOffsetChange={setOffset}
        />
      </BackofficeSectionPanel>

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
