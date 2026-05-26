'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeEmptyState, BackofficeMetricStrip, BackofficePageStack, BackofficePrimaryPanel, BackofficeSectionPanel, BackofficeStackCard } from '@/components/backoffice/BackofficeScaffold';
import { PortalActionRequestResultStrip } from '@/components/portal/PortalActionRequestResultStrip';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { Modal } from '@/components/ui/Modal';
import { useLocale } from '@/contexts/LocaleContext';
import {
  formatPortalActionRequestResultSummary,
  formatPortalActionRequestStatusLabel,
  formatPortalActionRequestTypeLabel,
} from '@/lib/portal-action-request-display';
import { readResponsePayload } from '@/lib/safe-response';
import { formatDate, formatNumber } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';

type PortalActionRequest = {
  request_id: string;
  request_type: string;
  account_id?: string;
  site_id?: string;
  member_ref: string;
  title: string;
  message?: string;
  status: string;
  payload?: Record<string, unknown>;
  created_at: string;
  updated_at?: string;
};

const REQUEST_TYPES = [
  { value: '', labelKey: 'admin.requests_filter_all', fallback: 'All requests' },
  { value: 'package_change', labelKey: 'admin.request_type_package_change', fallback: 'Package change' },
  { value: 'topup_pack', labelKey: 'admin.request_type_topup_pack', fallback: 'Top-up pack' },
  { value: 'site_delete', labelKey: 'admin.request_type_site_delete', fallback: 'Site delete' },
  { value: 'usage_alert', labelKey: 'admin.request_type_usage_alert', fallback: 'Usage alert' },
  { value: 'key_expiry', labelKey: 'admin.request_type_key_expiry', fallback: 'Key expiry' },
  { value: 'auth_guard', labelKey: 'admin.request_type_auth_guard', fallback: 'Auth guard' },
];

const REQUEST_STATUSES = [
  { value: 'open', labelKey: 'admin.request_status_open', fallback: 'Open' },
  { value: 'acknowledged', labelKey: 'admin.request_status_acknowledged', fallback: 'Acknowledged' },
  { value: 'resolved', labelKey: 'admin.request_status_resolved', fallback: 'Resolved' },
  { value: 'canceled', labelKey: 'admin.request_status_canceled', fallback: 'Canceled' },
  { value: '', labelKey: 'admin.requests_filter_all_statuses', fallback: 'All statuses' },
];

const RESULT_FILTERS = [
  { value: '', labelKey: 'admin.requests_result_all', fallback: 'All results' },
  { value: 'pending', labelKey: 'admin.requests_result_pending', fallback: 'Pending decision' },
  { value: 'applied', labelKey: 'admin.requests_result_applied', fallback: 'Applied' },
  { value: 'rejected', labelKey: 'admin.requests_result_rejected', fallback: 'Rejected' },
  { value: 'no_result', labelKey: 'admin.requests_result_no_result', fallback: 'No execution result' },
];

function stringifyPayloadValue(value: unknown): string {
  if (value === null || value === undefined || value === '') {
    return '—';
  }
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(', ');
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function formatPayloadLabel(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  key: string
): string {
  const labels: Record<string, string> = {
    target_package: t('admin.request_field_target_package', {}, 'Target package'),
    expected_sites: t('admin.request_field_expected_sites', {}, 'Expected sites'),
    expected_usage: t('admin.request_field_expected_usage', {}, 'Expected usage'),
    current_role: t('admin.request_field_current_role', {}, 'Current role'),
    pack_id: t('admin.request_field_pack_id', {}, 'Top-up pack ID'),
    pack_label: t('admin.request_field_pack_label', {}, 'Top-up pack'),
    points_label: t('admin.request_field_points_label', {}, 'Points label'),
    runs_increment: t('admin.request_field_runs_increment', {}, 'Runs increment'),
    tokens_increment: t('admin.request_field_tokens_increment', {}, 'Tokens increment'),
    cost_increment: t('admin.request_field_cost_increment', {}, 'Cost increment'),
    admin_decision: t('admin.request_field_admin_decision', {}, 'Admin decision'),
    admin_decision_note: t('admin.request_field_admin_decision_note', {}, 'Decision note'),
    admin_decided_at: t('admin.request_field_admin_decided_at', {}, 'Decision time'),
  };
  return labels[key] || key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

function formatPayloadValue(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  key: string,
  value: unknown
): string {
  if (key === 'target_package') {
    const normalized = String(value || '').toLowerCase();
    if (normalized === 'free') return t('admin.plan_package_alias_starter', {}, 'Free');
    if (normalized === 'basic') return t('admin.plan_package_alias_pro', {}, 'Basic');
    if (normalized === 'bulk') return t('admin.plan_package_alias_agency', {}, 'Bulk');
  }
  if (key === 'current_role' && String(value) === 'user_admin') {
    return t('admin.identity_customer_title', {}, 'User administrators');
  }
  if (key === 'admin_decision') {
    return String(value) === 'approve'
      ? t('admin.request_decision_approved', {}, 'Approved')
      : String(value) === 'reject'
      ? t('admin.request_decision_rejected', {}, 'Rejected')
      : stringifyPayloadValue(value);
  }
  return stringifyPayloadValue(value);
}

function formatDecisionError(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  errorCode?: string,
  message?: string
): string {
  if (errorCode === 'service.subscription_not_found') {
    return t(
      'admin.request_error_subscription_not_found',
      {},
      'No active subscription was found for this customer or site. Open the subscription directory first, then apply this request.'
    );
  }
  if (errorCode === 'service.portal_action_request_already_decided') {
    return t(
      'admin.request_error_already_decided',
      {},
      'This request has already been processed. Refresh the list before taking another action.'
    );
  }
  if (errorCode === 'service.subscription_topup_pack_not_found' || errorCode === 'service.topup_pack_not_found') {
    return t(
      'admin.request_error_topup_pack_not_found',
      {},
      'The requested top-up pack is no longer available. Ask the user to submit a new request.'
    );
  }
  return resolveUiErrorMessage(message || null, t('error.failed_save'));
}

function resolveRequestTarget(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  item: PortalActionRequest
): string {
  const payload = item.payload || {};
  if (item.request_type === 'package_change') {
    return formatPayloadValue(t, 'target_package', payload.target_package);
  }
  if (item.request_type === 'topup_pack') {
    return formatPayloadValue(t, 'pack_label', payload.pack_label || payload.pack_id);
  }
  if (item.request_type === 'site_delete') {
    return item.site_id || t('common.site', {}, 'Site');
  }
  return item.title || formatRequestType(t, item.request_type);
}

function formatDecisionConsequence(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  item: PortalActionRequest,
  decision: 'approve' | 'reject'
): string {
  if (decision === 'reject') {
    return t(
      'admin.request_decision_reject_consequence',
      {},
      '拒绝后，用户侧会看到申请未通过和处理说明；不会修改套餐、加量包或站点状态。'
    );
  }
  if (item.request_type === 'package_change') {
    return t(
      'admin.request_decision_package_consequence',
      {},
      '同意后，系统会尝试为该客户应用目标套餐，并把处理结果同步到用户侧申请记录。'
    );
  }
  if (item.request_type === 'topup_pack') {
    return t(
      'admin.request_decision_topup_consequence',
      {},
      '同意后，系统会尝试把该加量包应用到当前订阅，并把处理结果同步到用户侧申请记录。'
    );
  }
  if (item.request_type === 'site_delete') {
    return t(
      'admin.request_decision_site_delete_consequence',
      {},
      '同意后，只记录平台已处理删除/断开申请；站点是否最终移除仍按平台运营策略执行。'
    );
  }
  return t(
    'admin.request_decision_generic_consequence',
    {},
    '同意后会记录审计并把处理结果显示给用户；不会绕过现有权限与业务校验。'
  );
}

function buildRequestSummary(
  t: (key: string, params?: Record<string, string>, fallback?: string) => string,
  item: PortalActionRequest
): string {
  const lines = [
    `${t('common.request_type', {}, 'Request type')}: ${formatRequestType(t, item.request_type)}`,
    `${t('admin.request_decision_target', {}, 'Target')}: ${resolveRequestTarget(t, item)}`,
    `${t('common.status', {}, 'Status')}: ${formatRequestStatus(t, item.status)}`,
    `${t('common.created', {}, 'Created')}: ${formatDate(item.created_at)}`,
    `${t('common.member', {}, 'Member')}: ${item.member_ref || '—'}`,
    `${t('common.account', {}, 'Account')}: ${item.account_id || '—'}`,
    `${t('common.site', {}, 'Site')}: ${item.site_id || '—'}`,
  ];
  const result = formatPortalActionRequestResultSummary(t, item);
  if (result) {
    lines.push(`${t('admin.requests_result_filter', {}, 'Result')}: ${result}`);
  }
  if (item.message) {
    lines.push(`${t('common.message', {}, 'Message')}: ${item.message}`);
  }
  return lines.join('\n');
}

function AdminRequestsContent() {
  const { t } = useLocale();
  const router = useRouter();
  const [items, setItems] = useState<PortalActionRequest[]>([]);
  const [requestType, setRequestType] = useState('');
  const [status, setStatus] = useState('open,acknowledged');
  const [resultFilter, setResultFilter] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [decidingRequestId, setDecidingRequestId] = useState<string | null>(null);
  const [copiedRequestId, setCopiedRequestId] = useState('');
  const [decisionModal, setDecisionModal] = useState<{
    item: PortalActionRequest;
    decision: 'approve' | 'reject';
    note: string;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRequests = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      params.set('limit', '100');
      if (requestType) params.set('request_type', requestType);
      if (status) params.set('status', status);
      const response = await fetch(`/api/admin/portal-action-requests?${params.toString()}`, {
        credentials: 'include',
      });
      const payload = await readResponsePayload<{ data?: { items?: PortalActionRequest[] }; message?: string }>(response);
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
      }
      setItems(('data' in payload ? payload.data?.items : []) || []);
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [requestType, status, t]);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  const openDecisionModal = (item: PortalActionRequest, decision: 'approve' | 'reject') => {
    setDecisionModal({
      item,
      decision,
      note:
        decision === 'approve'
          ? t('admin.request_decision_approved', {}, 'Approved')
          : t('admin.request_decision_rejected', {}, 'Rejected'),
    });
  };

  const submitDecision = async () => {
    if (!decisionModal) {
      return;
    }
    const { item, decision, note } = decisionModal;
    setDecidingRequestId(item.request_id);
    setError(null);
    try {
      const response = await fetch(`/api/admin/portal-action-requests/${encodeURIComponent(item.request_id)}/decision`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision, decision_note: note.trim() }),
      });
      const payload = await readResponsePayload<{ data?: PortalActionRequest; message?: string; error_code?: string }>(response);
      if (!response.ok) {
        throw new Error(formatDecisionError(t, 'error_code' in payload ? payload.error_code : undefined, 'message' in payload ? payload.message : undefined));
      }
      await loadRequests();
      router.refresh();
      setDecisionModal(null);
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setDecidingRequestId(null);
    }
  };

  const copyRequestSummary = async (item: PortalActionRequest) => {
    await navigator.clipboard.writeText(buildRequestSummary(t, item));
    setCopiedRequestId(item.request_id);
    window.setTimeout(() => setCopiedRequestId((current) => (current === item.request_id ? '' : current)), 1800);
  };

  useEffect(() => {
    if (!items.some((item) => item.status === 'open')) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadRequests();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [items, loadRequests]);

  const counters = useMemo(() => {
    return {
      total: items.length,
      packageChange: items.filter((item) => item.request_type === 'package_change').length,
      topupPack: items.filter((item) => item.request_type === 'topup_pack').length,
    };
  }, [items]);

  const filteredItems = useMemo(() => {
    if (!resultFilter) {
      return items;
    }
    return items.filter((item) => {
      const payload = item.payload || {};
      const applicationResult = payload.application_result as Record<string, unknown> | undefined;
      const decision = String(payload.admin_decision || '');
      if (resultFilter === 'pending') {
        return item.status === 'open' || item.status === 'acknowledged';
      }
      if (resultFilter === 'applied') {
        return Boolean(applicationResult && Object.keys(applicationResult).length);
      }
      if (resultFilter === 'rejected') {
        return decision === 'reject' || item.status === 'canceled';
      }
      if (resultFilter === 'no_result') {
        return item.status === 'resolved' && !applicationResult;
      }
      return true;
    });
  }, [items, resultFilter]);

  if (isLoading) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.user_requests', {}, 'User requests')}
        title={t('admin.user_requests_title', {}, 'User request review')}
        description={t(
          'admin.user_requests_desc',
          {},
          'Check package change requests, top-up pack requests, site delete requests, and user-visible to-dos submitted from the user admin workspace.'
        )}
        actions={
          <>
            <Link href="/admin/subscriptions" className="btn btn-secondary">
              {t('common.subscriptions', {}, 'Subscriptions')}
            </Link>
            <Link href="/admin/topup-packs" className="btn btn-secondary">
              {t('admin.topup_packs', {}, 'Top-up packs')}
            </Link>
          </>
        }
      />

      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
          {error}
        </div>
      ) : null}

      <BackofficeSectionPanel className="space-y-4">
        <BackofficeMetricStrip
          items={[
            { label: t('admin.requests_total', {}, 'Requests'), value: formatNumber(counters.total), size: 'compact' },
            { label: t('admin.request_type_package_change', {}, 'Package change'), value: formatNumber(counters.packageChange), size: 'compact' },
            { label: t('admin.request_type_topup_pack', {}, 'Top-up pack'), value: formatNumber(counters.topupPack), size: 'compact' },
          ]}
          columnsClassName="md:grid-cols-3 xl:grid-cols-3"
        />
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className={`btn btn-sm ${status === 'open,acknowledged' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setStatus('open,acknowledged')}
          >
            {t('admin.requests_pending_mine', {}, '只看待我处理')}
          </button>
          <button
            type="button"
            className={`btn btn-sm ${status === '' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setStatus('')}
          >
            {t('admin.requests_view_all', {}, '全部')}
          </button>
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
            <span>{t('common.request_type', {}, 'Request type')}</span>
            <select className="input w-full" value={requestType} onChange={(event) => setRequestType(event.target.value)}>
              {REQUEST_TYPES.map((option) => (
                <option key={option.value || 'all'} value={option.value}>
                  {t(option.labelKey, {}, option.fallback)}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
            <span>{t('common.status')}</span>
            <select className="input w-full" value={status} onChange={(event) => setStatus(event.target.value)}>
              {status === 'open,acknowledged' ? (
                <option value="open,acknowledged">
                  {t('admin.requests_pending_mine', {}, '只看待我处理')}
                </option>
              ) : null}
              {REQUEST_STATUSES.map((option) => (
                <option key={option.value || 'all'} value={option.value}>
                  {t(option.labelKey, {}, option.fallback)}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
            <span>{t('admin.requests_result_filter', {}, 'Execution result')}</span>
            <select className="input w-full" value={resultFilter} onChange={(event) => setResultFilter(event.target.value)}>
              {RESULT_FILTERS.map((option) => (
                <option key={option.value || 'all'} value={option.value}>
                  {t(option.labelKey, {}, option.fallback)}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-end">
            <button type="button" className="btn btn-secondary w-full justify-center" onClick={() => void loadRequests()}>
              {t('common.refresh', {}, 'Refresh')}
            </button>
          </div>
        </div>
      </BackofficeSectionPanel>

      <div className="grid gap-4">
        {filteredItems.map((item) => (
          <BackofficeStackCard key={item.request_id} className="bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                    {formatRequestType(t, item.request_type)}
                  </span>
                  <BackofficeStatusBadge label={formatRequestStatus(t, item.status)} status={item.status} />
                </div>
                <h2 className="mt-3 text-lg font-semibold text-slate-950 dark:text-white">
                  {formatRequestType(t, item.request_type)}：{resolveRequestTarget(t, item)}
                </h2>
                {item.message ? (
                  <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-600 dark:text-slate-300">{item.message}</p>
                ) : null}
                <PortalActionRequestResultStrip item={item} />
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
                  <span>{t('common.created', {}, 'Created')}: {formatDate(item.created_at)}</span>
                  <span>{t('common.member', {}, 'Member')}: {item.member_ref}</span>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                {item.account_id ? (
                  <Link href={`/admin/accounts/${encodeURIComponent(item.account_id)}`} className="btn btn-secondary btn-sm">
                    {t('common.account', {}, 'Account')}
                  </Link>
                ) : null}
                {item.site_id ? (
                  <Link href={`/admin/sites/${encodeURIComponent(item.site_id)}`} className="btn btn-secondary btn-sm">
                    {t('common.site', {}, 'Site')}
                  </Link>
                ) : null}
                {item.request_type === 'topup_pack' ? (
                  <Link href="/admin/subscriptions" className="btn btn-secondary btn-sm">
                    {t('admin.open_subscription_to_apply_topup', {}, 'Open subscription to apply')}
                  </Link>
                ) : null}
                {item.request_type === 'package_change' ? (
                  <Link href="/admin/subscriptions" className="btn btn-secondary btn-sm">
                    {t('admin.open_subscription_to_change_package', {}, 'Open subscription')}
                  </Link>
                ) : null}
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => void copyRequestSummary(item)}
                >
                  {copiedRequestId === item.request_id
                    ? t('common.copied', {}, '已复制')
                    : t('admin.copy_request_summary', {}, '复制摘要')}
                </button>
                {item.status === 'open' ? (
                  <>
                    <button
                      type="button"
                      className="btn btn-primary btn-sm"
                      disabled={decidingRequestId === item.request_id}
                      onClick={() => openDecisionModal(item, 'approve')}
                    >
                      {t('admin.request_approve', {}, 'Approve')}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      disabled={decidingRequestId === item.request_id}
                      onClick={() => openDecisionModal(item, 'reject')}
                    >
                      {t('admin.request_reject', {}, 'Reject')}
                    </button>
                  </>
                ) : null}
              </div>
            </div>
            {(item.payload && Object.keys(item.payload).length) || item.request_id ? (
              <details className="mt-4 rounded-2xl border border-slate-200/80 bg-slate-50/70 px-4 py-3 dark:border-slate-800 dark:bg-slate-950/45">
                <summary className="cursor-pointer text-sm font-semibold text-slate-700 dark:text-slate-200">
                  {t('admin.request_payload_detail', {}, 'Request detail')}
                </summary>
                <dl className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950/60">
                    <dt className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
                      {t('common.request_id', {}, 'Request ID')}
                    </dt>
                    <dd className="mt-1 break-words text-sm font-medium text-slate-900 dark:text-slate-100">
                      <BackofficeIdentifier value={item.request_id} />
                    </dd>
                  </div>
                  {Object.entries(item.payload || {}).filter(([key]) => key !== 'application_result').map(([key, value]) => (
                    <div key={key} className="rounded-xl border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-950/60">
                      <dt className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">{formatPayloadLabel(t, key)}</dt>
                      <dd className="mt-1 break-words text-sm font-medium text-slate-900 dark:text-slate-100">{formatPayloadValue(t, key, value)}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            ) : null}
          </BackofficeStackCard>
        ))}

        {!filteredItems.length ? (
          <BackofficeEmptyState
            className="bg-white/80 dark:bg-slate-950/55"
            title={t('admin.requests_empty_title', {}, 'No matching requests')}
            description={t('admin.requests_empty_desc', {}, 'Change the type or status filter, or wait for users to submit requests from the portal.')}
            diagnosticCode="admin.requests.empty.filtered"
            action={
              <button type="button" className="btn btn-secondary" onClick={() => void loadRequests()}>
                {t('common.refresh', {}, 'Refresh')}
              </button>
            }
          />
        ) : null}
      </div>

      <Modal
        isOpen={Boolean(decisionModal)}
        onClose={() => setDecisionModal(null)}
        title={
          decisionModal?.decision === 'approve'
            ? t('admin.request_approve_confirm_title', {}, '确认同意申请')
            : t('admin.request_reject_confirm_title', {}, '确认拒绝申请')
        }
        description={t(
          'admin.request_decision_confirm_desc',
          {},
          '提交后会记录审计，并把处理结果显示给用户。'
        )}
        size="lg"
      >
        {decisionModal ? (
          <div className="space-y-4">
            <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm dark:border-slate-800 dark:bg-slate-950/45 md:grid-cols-2">
              <DecisionSummaryItem label={t('common.request_type', {}, 'Request type')} value={formatRequestType(t, decisionModal.item.request_type)} />
              <DecisionSummaryItem label={t('admin.request_decision_target', {}, '处理目标')} value={resolveRequestTarget(t, decisionModal.item)} />
              <DecisionSummaryItem label={t('common.member', {}, 'Member')} value={decisionModal.item.member_ref || '—'} />
              <DecisionSummaryItem label={t('common.site', {}, 'Site')} value={decisionModal.item.site_id || '—'} />
            </div>
            <div className="rounded-2xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm leading-6 text-blue-800 dark:border-blue-900/60 dark:bg-blue-950/30 dark:text-blue-200">
              {formatDecisionConsequence(t, decisionModal.item, decisionModal.decision)}
            </div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-200">
              <span>
                {decisionModal.decision === 'approve'
                  ? t('admin.request_approve_prompt', {}, 'Optional approval note')
                  : t('admin.request_reject_prompt', {}, 'Optional rejection reason')}
              </span>
              <textarea
                className="input mt-2 min-h-24 w-full"
                value={decisionModal.note}
                onChange={(event) =>
                  setDecisionModal((current) =>
                    current ? { ...current, note: event.target.value } : current
                  )
                }
              />
            </label>
            <div className="flex justify-end gap-2">
              <button type="button" className="btn btn-secondary" onClick={() => setDecisionModal(null)}>
                {t('common.cancel')}
              </button>
              <button
                type="button"
                className={decisionModal.decision === 'approve' ? 'btn btn-primary' : 'btn btn-secondary'}
                disabled={decidingRequestId === decisionModal.item.request_id}
                onClick={() => void submitDecision()}
              >
                {decidingRequestId === decisionModal.item.request_id
                  ? t('common.saving')
                  : decisionModal.decision === 'approve'
                    ? t('admin.request_approve', {}, 'Approve')
                    : t('admin.request_reject', {}, 'Reject')}
              </button>
            </div>
          </div>
        ) : null}
      </Modal>
    </BackofficePageStack>
  );
}

function DecisionSummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
        {label}
      </p>
      <p className="mt-1 break-words font-medium text-slate-950 dark:text-slate-100">{value || '—'}</p>
    </div>
  );
}

function formatRequestType(t: (key: string, params?: Record<string, string>, fallback?: string) => string, value: string): string {
  const found = REQUEST_TYPES.find((item) => item.value === value);
  return found ? t(found.labelKey, {}, found.fallback) : formatPortalActionRequestTypeLabel(t, value);
}

function formatRequestStatus(t: (key: string, params?: Record<string, string>, fallback?: string) => string, value: string): string {
  const found = REQUEST_STATUSES.find((item) => item.value === value);
  return found ? t(found.labelKey, {}, found.fallback) : formatPortalActionRequestStatusLabel(t, value);
}

export default function AdminRequestsPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <AdminRequestsContent />
    </Suspense>
  );
}
