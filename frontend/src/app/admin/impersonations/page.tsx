'use client';

import React, { Suspense, useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  AdminMutationReceipt,
  type AdminMutationReceiptPayload,
} from '@/components/admin/AdminMutationReceipt';
import {
  BackofficeLayer,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { cn, formatDate } from '@/lib/utils';
import { translateAdminReasonCode, translateAdminRole } from '@/lib/admin-display';
import { resolveUiErrorMessage } from '@/lib/errors';

interface ImpersonationRecord {
  impersonation_id: string;
  platform_admin_ref: string;
  platform_role: string;
  member_ref: string;
  account_id: string;
  site_id: string;
  reason_code: string;
  reason_text: string;
  read_only: boolean;
  status: string;
  started_at?: string;
  expires_at?: string;
  ended_at?: string;
}

interface ImpersonationResult {
  impersonation: ImpersonationRecord;
  portal_session?: {
    member_ref: string;
    site_id: string;
  };
  receipt?: AdminMutationReceiptPayload;
}

function buildImpersonationReceipt(
  record: ImpersonationRecord | null | undefined,
  eventKind: 'platform_impersonation.start' | 'platform_impersonation.end'
): AdminMutationReceiptPayload | null {
  if (!record?.impersonation_id) {
    return null;
  }
  return {
    event_kind: eventKind,
    scope_kind: 'platform_impersonation',
    scope_id: record.impersonation_id,
    outcome: 'succeeded',
    effective_summary:
      eventKind === 'platform_impersonation.start'
        ? `Read-only impersonation for ${record.member_ref} on ${record.site_id} is now active.`
        : `Read-only impersonation ${record.impersonation_id} is now ended.`,
    audit_filters: {
      account_id: record.account_id || '',
      site_id: record.site_id || '',
      event_kind: eventKind,
      outcome: 'succeeded',
    },
  };
}

function ImpersonationsContent() {
  const searchParams = useSearchParams();
  const { locale, t } = useLocale();
  const [items, setItems] = useState<ImpersonationRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<ImpersonationResult | null>(null);
  const [lastReceipt, setLastReceipt] = useState<AdminMutationReceiptPayload | null>(null);
  const [filters, setFilters] = useState({
    status: searchParams.get('status') || '',
    platform_admin_ref: searchParams.get('platform_admin_ref') || '',
    member_ref: searchParams.get('member_ref') || '',
    account_id: searchParams.get('account_id') || '',
    site_id: searchParams.get('site_id') || '',
    active_only: searchParams.get('active_only') === 'true',
  });
  const [form, setForm] = useState({
    member_ref: searchParams.get('member_ref') || '',
    site_id: searchParams.get('site_id') || '',
    reason_code: 'support_debug',
    reason_text: '',
  });

  const loadImpersonations = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (filters.status) params.set('status', filters.status);
      if (filters.platform_admin_ref) params.set('platform_admin_ref', filters.platform_admin_ref);
      if (filters.member_ref) params.set('member_ref', filters.member_ref);
      if (filters.account_id) params.set('account_id', filters.account_id);
      if (filters.site_id) params.set('site_id', filters.site_id);
      if (filters.active_only) params.set('active_only', 'true');

      const response = await fetch(`/api/admin/impersonations?${params.toString()}`, {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error(t('error.failed_load'));
      }

      const data = await response.json();
      setItems(data.data.items || []);
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [filters, t]);

  useEffect(() => {
    loadImpersonations();
  }, [loadImpersonations]);

  const handleStart = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setNotice(null);
    setLastReceipt(null);

    try {
      const response = await fetch('/api/admin/impersonations', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(form),
      });

      const payload = await response.json();

      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload.message, t('error.failed_start_impersonation')));
      }

      setLastResult(payload.data);
      setNotice(t('admin.impersonation_started_notice'));
      setLastReceipt(
        (payload?.data?.receipt ??
          buildImpersonationReceipt(payload?.data?.impersonation, 'platform_impersonation.start')) as AdminMutationReceiptPayload | null
      );
      await loadImpersonations();
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_start_impersonation')));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleEnd = async (impersonationId: string) => {
    setIsSubmitting(true);
    setError(null);
    setNotice(null);
    setLastReceipt(null);

    try {
      const response = await fetch(`/api/admin/impersonations/${impersonationId}/end`, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ended_reason: 'ended_from_admin_console',
        }),
      });

      const payload = await response.json();

      if (!response.ok) {
        throw new Error(resolveUiErrorMessage(payload.message, t('error.failed_end_impersonation')));
      }

      setNotice(t('admin.impersonation_ended_notice'));
      setLastResult(null);
      setLastReceipt(
        (payload?.data?.receipt ??
          buildImpersonationReceipt(payload?.data?.impersonation, 'platform_impersonation.end')) as AdminMutationReceiptPayload | null
      );
      await loadImpersonations();
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_end_impersonation')));
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return <LoadingFallback />;
  }

  const activeItems = items.filter((item) => item.status === 'active');
  const latestActive = lastResult?.impersonation || activeItems[0] || null;
  const postureTone = latestActive ? 'warning' : items.length > 0 ? 'ok' : 'inactive';
  const postureTitle = latestActive
    ? t('admin.impersonations.active_posture_title', {}, 'An active impersonation session needs bounded follow-up')
    : items.length > 0
      ? t('admin.impersonations.queue_posture_title', {}, 'Support access queue is currently bounded')
      : t('admin.impersonations.empty_posture_title', {}, 'No impersonation session is currently active');
  const postureDescription = latestActive
    ? t(
        'admin.impersonations.active_posture_desc',
        {},
        'End the current support session before starting another one, unless you intentionally need parallel bounded access.'
      )
    : t(
        'admin.impersonations.queue_posture_desc',
        {},
        'Use this page as a bounded support-access operator surface: start or end one session, then inspect the queue history below.'
      );

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_group_support_access', {}, 'Support / Access')}
        title={t('admin.impersonations_title')}
        description={t(
          'admin.impersonations_desc',
          { count: String(items.length) }
        )}
        actions={(
          <>
            <Link href="/admin" className="btn btn-secondary">
              {t('nav.admin')}
            </Link>
            <Link href="/portal" className="btn btn-secondary">
              {t('admin.open_customer_portal')}
            </Link>
          </>
        )}
        aside={(
          <div className="w-full xl:w-[32rem]">
            <BackofficeMetricStrip
              items={[
                { label: t('admin.active_only'), value: activeItems.length, size: 'compact' },
                { label: t('admin.impersonation_inventory'), value: items.length, size: 'compact' },
                {
                  label: t('common.status'),
                  value: latestActive ? t('status.active', {}, 'Active') : t('status.inactive', {}, 'Inactive'),
                  size: 'compact',
                },
              ]}
              columnsClassName="md:grid-cols-3 xl:grid-cols-3"
            />
          </div>
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <BackofficeStatusBadge
            status={postureTone}
            label={t(`status.${postureTone}`, undefined, postureTone)}
          />
          {latestActive?.read_only ? (
            <BackofficeStatusBadge
              status="read_only"
              label={t('admin.read_only', {}, 'Read only')}
            />
          ) : null}
          {latestActive ? (
            <BackofficeIdentifier value={latestActive.impersonation_id} className="text-sm font-semibold text-slate-950 dark:text-white" />
          ) : null}
          <span className="text-sm text-slate-600 dark:text-slate-300">{postureTitle}</span>
        </div>
      </BackofficePrimaryPanel>

      <BackofficeLayer
        eyebrow={
          latestActive
            ? t('admin.current_impersonation', {}, 'Current impersonation')
            : t('admin.start_impersonation')
        }
        title={
          latestActive
            ? t('admin.impersonations.bounded_action_title', {}, 'Close the current support session')
            : t('admin.start_impersonation')
        }
        description={
          latestActive
            ? t(
                'admin.impersonations.bounded_action_desc',
                {},
                'Keep support access bounded here: close the active session first, then inspect history or start a new one only after that boundary is cleared.'
              )
            : t('admin.start_impersonation_desc')
        }
      />
      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <BackofficeSectionPanel className="space-y-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('admin.current_impersonation', {}, 'Current impersonation')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">
              {latestActive
                ? t('admin.impersonations.active_panel_title', {}, 'Current support session')
                : t('admin.start_impersonation', {}, 'Start impersonation')}
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">
              {latestActive
                ? t(
                    'admin.impersonations.active_panel_desc',
                    {},
                    'An active session already exists. End it here, or start a new bounded session only if you intentionally need a separate support path.'
                  )
                : t('admin.start_impersonation_desc')}
            </p>
          </div>
          {notice ? (
            <BackofficeStackCard className="border-green-200 bg-green-50 text-green-700 dark:border-green-900 dark:bg-green-950/30 dark:text-green-300">
              {notice}
            </BackofficeStackCard>
          ) : null}
          {lastReceipt ? (
            <AdminMutationReceipt
              receipt={lastReceipt}
              title={t('admin.latest_receipt', {}, 'Latest receipt')}
            />
          ) : null}

          {error ? (
            <BackofficeStackCard className="border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
              {error}
            </BackofficeStackCard>
          ) : null}
          {latestActive ? (
            <BackofficeStackCard className="border-amber-200 bg-amber-50 dark:border-amber-900/60 dark:bg-amber-950/20">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <BackofficeIdentifier value={latestActive.impersonation_id} className="block text-sm font-semibold text-slate-950 dark:text-white" />
                  <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                    {latestActive.member_ref} · {latestActive.site_id}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => handleEnd(latestActive.impersonation_id)}
                  className="btn btn-primary"
                  disabled={isSubmitting}
                >
                  {t('admin.end_impersonation')}
                </button>
              </div>
            </BackofficeStackCard>
          ) : null}
          {latestActive ? (
            <BackofficeStackCard className="border-dashed border-slate-300 bg-slate-50/80 dark:border-slate-700 dark:bg-slate-900/40">
              <p className="text-sm font-medium text-slate-950 dark:text-white">
                {t(
                  'admin.impersonations.start_blocked_title',
                  {},
                  'Start a new impersonation only after the active session is closed'
                )}
              </p>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                {t(
                  'admin.impersonations.start_blocked_desc',
                  {},
                  'This page keeps support access bounded. End the current session first, then return here if you still need a new impersonation path.'
                )}
              </p>
            </BackofficeStackCard>
          ) : (
            <form className="grid gap-4 md:grid-cols-2" onSubmit={handleStart}>
              <label className="block text-sm">
                <span className="mb-1 block font-medium">{t('admin.member_ref')}</span>
                <input
                  type="text"
                  value={form.member_ref}
                  onChange={(event) => setForm((current) => ({ ...current, member_ref: event.target.value }))}
                  placeholder="user:customer@example.com"
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
                  required
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-medium">{t('common.site')}</span>
                <input
                  type="text"
                  value={form.site_id}
                  onChange={(event) => setForm((current) => ({ ...current, site_id: event.target.value }))}
                  placeholder="site_123"
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
                  required
                />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-medium">{t('admin.reason_code')}</span>
                <select
                  value={form.reason_code}
                  onChange={(event) => setForm((current) => ({ ...current, reason_code: event.target.value }))}
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
                  required
                >
                  <option value="support_debug">{t('admin.reason_support_debug')}</option>
                </select>
              </label>
              <label className="block text-sm">
                <span className="mb-1 block font-medium">{t('admin.reason_text')}</span>
                <input
                  type="text"
                  value={form.reason_text}
                  onChange={(event) => setForm((current) => ({ ...current, reason_text: event.target.value }))}
                  placeholder={t('admin.reason_text_placeholder')}
                  className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
                />
              </label>
              <div className="md:col-span-2 flex flex-wrap gap-3">
                <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
                  {isSubmitting ? t('common.saving') : t('admin.start_impersonation')}
                </button>
              </div>
            </form>
          )}
        </BackofficeSectionPanel>

        <BackofficeSectionPanel className="space-y-4">
          <h2 className="text-lg font-semibold">{t('admin.impersonation_inventory')}</h2>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {t('admin.impersonation_inventory_desc')}
          </p>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <label className="block text-sm">
            <span className="mb-1 block font-medium">{t('common.status')}</span>
            <input
              type="text"
              value={filters.status}
              onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value }))}
              placeholder={t('common.status')}
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">{t('admin.admin_ref')}</span>
            <input
              type="text"
              value={filters.platform_admin_ref}
              onChange={(event) => setFilters((current) => ({ ...current, platform_admin_ref: event.target.value }))}
              placeholder="platform:..."
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">{t('admin.member_ref')}</span>
            <input
              type="text"
              value={filters.member_ref}
              onChange={(event) => setFilters((current) => ({ ...current, member_ref: event.target.value }))}
              placeholder={t('admin.member_ref')}
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">{t('common.account')}</span>
            <input
              type="text"
              value={filters.account_id}
              onChange={(event) => setFilters((current) => ({ ...current, account_id: event.target.value }))}
              placeholder="acct_123"
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">{t('common.site')}</span>
            <input
              type="text"
              value={filters.site_id}
              onChange={(event) => setFilters((current) => ({ ...current, site_id: event.target.value }))}
              placeholder="site_123"
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
            />
          </label>
          <label className="flex items-center gap-2 pt-7 text-sm">
            <input
              type="checkbox"
              checked={filters.active_only}
              onChange={(event) => setFilters((current) => ({ ...current, active_only: event.target.checked }))}
            />
            <span>{t('admin.active_only')}</span>
          </label>
          </div>
        </BackofficeSectionPanel>
      </div>

      <BackofficeLayer
        eyebrow={t('admin.impersonation_inventory')}
        title={t('admin.impersonations.queue_title', {}, 'Support session queue')}
      />
      <BackofficeSectionPanel className="overflow-hidden p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('admin.impersonation_id')}</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('admin.admin_ref')}</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('admin.member_ref')}</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('common.account')}</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('common.site')}</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('admin.reason')}</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('admin.mode')}</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('common.status')}</th>
                <th className="px-4 py-3 text-left font-medium text-gray-600 dark:text-gray-400">{t('admin.expires_at')}</th>
                <th className="px-4 py-3 text-right font-medium text-gray-600 dark:text-gray-400">{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={10} className="px-4 py-10 text-center text-gray-600 dark:text-gray-400">
                    {t('admin.no_impersonations')}
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.impersonation_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                    <td className="px-4 py-3">
                      <BackofficeIdentifier value={item.impersonation_id} className="text-xs" />
                    </td>
                    <td className="px-4 py-3">
                      <BackofficeIdentifier value={item.platform_admin_ref} className="text-xs" />
                      <div className="text-xs text-gray-500">{translateAdminRole(item.platform_role, t)}</div>
                    </td>
                    <td className="px-4 py-3">
                      <BackofficeIdentifier value={item.member_ref} className="text-xs" />
                    </td>
                    <td className="px-4 py-3">
                      {item.account_id ? <BackofficeIdentifier value={item.account_id} className="text-xs" /> : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {item.site_id ? <BackofficeIdentifier value={item.site_id} className="text-xs" /> : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="text-xs">{item.reason_code ? translateAdminReasonCode(item.reason_code, t) : '—'}</div>
                      {item.reason_text ? (
                        <div className="text-xs text-gray-500">{item.reason_text}</div>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {item.read_only ? t('admin.read_only') : t('admin.write')}
                    </td>
                    <td className="px-4 py-3">
                      {item.status ? (
                        <BackofficeStatusBadge
                          status={item.status === 'ended' ? 'inactive' : item.status}
                          label={t(`status.${item.status}`, undefined, item.status)}
                        />
                      ) : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs">{formatDate(item.expires_at || item.ended_at || item.started_at)}</td>
                    <td className="px-4 py-3 text-right">
                      {item.status === 'active' ? (
                        <button
                          type="button"
                          onClick={() => handleEnd(item.impersonation_id)}
                          className="text-red-600 hover:underline disabled:opacity-50"
                          disabled={isSubmitting}
                        >
                          {t('admin.end_impersonation')}
                        </button>
                      ) : (
                        <span className="text-xs text-gray-500">{t('common.done')}</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}

export default function AdminImpersonationsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <ImpersonationsContent />
    </Suspense>
  );
}
