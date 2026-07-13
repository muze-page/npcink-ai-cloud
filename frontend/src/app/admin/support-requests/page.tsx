'use client';

import React, { FormEvent, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';
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
import { useToast } from '@/components/ui/Toast';
import { useLocale } from '@/contexts/LocaleContext';
import { resolveUiErrorMessage } from '@/lib/errors';
import { readResponsePayload } from '@/lib/safe-response';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';

type SupportRequestStatus = 'open' | 'in_progress' | 'resolved' | 'closed';
type SupportRequestSort = 'risk' | 'updated_at';
type SupportRequestRisk = 'critical' | 'warning' | 'monitor' | 'stable';

type SupportRequest = {
  request_id: string;
  account_id: string;
  site_id?: string;
  principal_id?: string;
  email: string;
  topic: string;
  title: string;
  description: string;
  status: SupportRequestStatus;
  priority: string;
  admin_note?: string;
  created_at?: string;
  updated_at?: string;
};

type SupportRequestListPayload = {
  items?: SupportRequest[];
  pagination?: { total?: number; limit?: number; offset?: number; has_more?: boolean };
  summary?: { open?: number; in_progress?: number };
};

const STATUS_FILTERS: Array<SupportRequestStatus | ''> = ['', 'open', 'in_progress', 'resolved', 'closed'];
const NEXT_STATUSES: SupportRequestStatus[] = ['open', 'in_progress', 'resolved', 'closed'];
const TOPIC_FILTERS = ['', 'billing', 'payment', 'site', 'usage', 'account', 'general'] as const;
const SORTS = new Set<SupportRequestSort>(['risk', 'updated_at']);
const PAGE_SIZE = 20;

function normalizeOffset(value: string | null): number {
  const parsed = Number(value || 0);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 0;
}

function normalizeSort(value: string | null): SupportRequestSort {
  return value && SORTS.has(value as SupportRequestSort) ? (value as SupportRequestSort) : 'risk';
}

function ageHours(value?: string): number | null {
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) return null;
  return Math.max(0, Math.floor((Date.now() - timestamp) / 3_600_000));
}

function requestRisk(item: SupportRequest): SupportRequestRisk {
  const age = ageHours(item.created_at);
  const priority = item.priority.toLowerCase();
  if (priority === 'critical' || priority === 'urgent' || (item.status === 'open' && age !== null && age >= 48)) {
    return 'critical';
  }
  if (item.status === 'open' || priority === 'high') return 'warning';
  if (item.status === 'in_progress') return 'monitor';
  return 'stable';
}

function riskRank(item: SupportRequest): number {
  return { critical: 0, warning: 1, monitor: 2, stable: 3 }[requestRisk(item)];
}

function sortRequests(items: SupportRequest[], sort: SupportRequestSort): SupportRequest[] {
  return [...items].sort((left, right) => {
    const leftTime = new Date(left.updated_at || left.created_at || 0).getTime() || 0;
    const rightTime = new Date(right.updated_at || right.created_at || 0).getTime() || 0;
    if (sort === 'updated_at') return rightTime - leftTime;
    const rankDifference = riskRank(left) - riskRank(right);
    if (rankDifference) return rankDifference;
    if (left.status === 'open' || left.status === 'in_progress') return leftTime - rightTime;
    return rightTime - leftTime;
  });
}

function riskToneClassName(risk: SupportRequestRisk): string {
  if (risk === 'critical') return 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200';
  if (risk === 'warning') return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200';
  if (risk === 'monitor') return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-900/60 dark:bg-blue-950/25 dark:text-blue-200';
  return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200';
}

function statusTone(status: SupportRequestStatus): string {
  if (status === 'open') return 'warning';
  if (status === 'resolved') return 'success';
  if (status === 'closed') return 'inactive';
  return 'read_only';
}

function SupportRequestsContent() {
  const { t } = useLocale();
  const toast = useToast();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const [queueParamsKey, setQueueParamsKey] = useState(searchParamsKey);
  const queueParams = useMemo(() => new URLSearchParams(queueParamsKey), [queueParamsKey]);
  const appliedStatus = queueParams.get('status') || '';
  const appliedTopic = queueParams.get('topic') || '';
  const appliedQuery = queueParams.get('q') || '';
  const sort = normalizeSort(queueParams.get('sort'));
  const offset = normalizeOffset(queueParams.get('offset'));
  const focusedRequestId = queueParams.get('focus') || '';

  const [items, setItems] = useState<SupportRequest[]>([]);
  const [summary, setSummary] = useState<SupportRequestListPayload['summary']>({});
  const [total, setTotal] = useState(0);
  const [queryDraft, setQueryDraft] = useState(appliedQuery);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [pendingRequestId, setPendingRequestId] = useState('');
  const [statusDraft, setStatusDraft] = useState<SupportRequestStatus>('open');
  const [noteDraft, setNoteDraft] = useState('');
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const [loadedRequestKey, setLoadedRequestKey] = useState('');
  const activeRequestKeyRef = useRef('');
  const requestSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);
  const [hasLoaded, setHasLoaded] = useState(false);

  const requestKey = useMemo(() => {
    const params = new URLSearchParams();
    params.set('limit', String(PAGE_SIZE));
    if (offset > 0) params.set('offset', String(offset));
    if (appliedStatus) params.set('status', appliedStatus);
    if (appliedTopic) params.set('topic', appliedTopic);
    if (appliedQuery.trim()) params.set('q', appliedQuery.trim());
    return params.toString();
  }, [appliedQuery, appliedStatus, appliedTopic, offset]);

  const updateQueueUrl = useCallback((changes: Record<string, string | null>) => {
    const params = new URLSearchParams(queueParamsKey);
    Object.entries(changes).forEach(([key, value]) => {
      if (!value || (key === 'sort' && value === 'risk')) params.delete(key);
      else params.set(key, value);
    });
    const next = params.toString();
    setQueueParamsKey(next);
    const nextUrl = next ? `${pathname}?${next}` : pathname;
    window.history.replaceState(window.history.state, '', nextUrl);
  }, [pathname, queueParamsKey]);

  const loadRequests = useCallback(async (force = false) => {
    if (!force && activeRequestKeyRef.current === requestKey) return;
    activeRequestKeyRef.current = requestKey;
    const sequence = ++requestSequenceRef.current;
    if (hasLoadedRef.current) setIsRefreshing(true);
    else setIsLoading(true);
    setLoadError('');
    try {
      const response = await fetch(`/api/admin/support-requests?${requestKey}`, { credentials: 'include', cache: 'no-store' });
      const payload = await readResponsePayload<{ data?: SupportRequestListPayload; message?: string }>(response);
      if (!response.ok || !('data' in payload) || !payload.data) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
      }
      if (sequence !== requestSequenceRef.current) return;
      setItems(payload.data.items || []);
      setSummary(payload.data.summary || {});
      setTotal(Number(payload.data.pagination?.total || 0));
      setLoadedAt(new Date());
      setLoadedRequestKey(requestKey);
      hasLoadedRef.current = true;
      setHasLoaded(true);
    } catch (error) {
      if (sequence !== requestSequenceRef.current) return;
      setLoadError(resolveUiErrorMessage(error instanceof Error ? error.message : null, t('error.failed_load')));
    } finally {
      if (sequence === requestSequenceRef.current) {
        activeRequestKeyRef.current = '';
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, [requestKey, t]);

  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  useEffect(() => {
    setQueueParamsKey(searchParamsKey);
  }, [searchParamsKey]);

  useEffect(() => {
    setQueryDraft(appliedQuery);
  }, [appliedQuery]);

  const sortedItems = useMemo(() => sortRequests(items, sort), [items, sort]);
  const selectedRequest = sortedItems.find((item) => item.request_id === focusedRequestId) || sortedItems[0] || null;

  useEffect(() => {
    if (!selectedRequest) return;
    setStatusDraft(selectedRequest.status);
    setNoteDraft(selectedRequest.admin_note || '');
    setActionError('');
  }, [selectedRequest]);

  const pageSummary = useMemo(() => sortedItems.reduce(
    (counts, item) => ({ ...counts, [requestRisk(item)]: counts[requestRisk(item)] + 1 }),
    { critical: 0, warning: 0, monitor: 0, stable: 0 }
  ), [sortedItems]);

  const applySearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const submittedQuery = String(new FormData(event.currentTarget).get('q') || '').trim();
    setQueryDraft(submittedQuery);
    updateQueueUrl({ q: submittedQuery || null, offset: null, focus: null });
  };

  const clearFilters = () => {
    setQueryDraft('');
    updateQueueUrl({ status: null, topic: null, q: null, sort: null, offset: null, focus: null });
  };

  const handleUpdate = async (item: SupportRequest) => {
    setPendingRequestId(item.request_id);
    setActionError('');
    try {
      const response = await fetch(`/api/admin/support-requests/${encodeURIComponent(item.request_id)}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: statusDraft, admin_note: noteDraft }),
      });
      const payload = await readResponsePayload<{ data?: { request?: SupportRequest }; message?: string }>(response);
      if (!response.ok || !('data' in payload) || !payload.data?.request) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_save')));
      }
      updateQueueUrl({ focus: item.request_id });
      toast.success(t('admin.support_requests_updated_notice', {}, 'Ticket updated.'), t('admin.support_requests_updated_title', {}, 'Ticket saved'));
      await loadRequests(true);
    } catch (error) {
      setActionError(resolveUiErrorMessage(error instanceof Error ? error.message : null, t('error.failed_save')));
    } finally {
      setPendingRequestId('');
    }
  };

  if (loadError && !hasLoaded) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div role="alert" className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-rose-600">{t('common.error')}</h2>
          <p className="mb-6 text-slate-600 dark:text-slate-400">{loadError}</p>
          <button type="button" onClick={() => void loadRequests(true)} className="btn btn-primary">{t('common.retry')}</button>
        </div>
      </div>
    );
  }
  if (isLoading && !hasLoaded) return <LoadingFallback />;

  const hasFilters = Boolean(appliedStatus || appliedTopic || appliedQuery || sort !== 'risk');
  const isShowingRetainedResults = Boolean(loadError && loadedRequestKey && loadedRequestKey !== requestKey);
  const openCount = Number(summary?.open || 0);
  const inProgressCount = Number(summary?.in_progress || 0);

  return (
    <BackofficePageStack className="space-y-5">
      <BackofficeLayer
        eyebrow={t('admin.support_requests_eyebrow', {}, 'Customer support')}
        title={t('admin.support_requests_title', {}, 'Tickets')}
        description={t('admin.support_requests_workspace_desc', {}, 'Prioritize unanswered customer issues, inspect one ticket, then continue the full conversation in its detail view.')}
        actions={(
          <button type="button" className="btn btn-secondary" onClick={() => void loadRequests(true)} disabled={isRefreshing}>
            {isRefreshing ? t('common.loading', {}, 'Loading...') : t('admin.support_requests_refresh_action', {}, 'Refresh tickets')}
          </button>
        )}
      />

      {loadError ? (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/25 dark:text-rose-200 sm:flex-row sm:items-center sm:justify-between">
          <span>
            {loadError}
            {isShowingRetainedResults ? <span className="mt-1 block text-xs">{t('admin.support_requests_retained_notice', {}, 'Showing the last successfully loaded page; it may not match the current filters.')}</span> : null}
          </span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadRequests(true)}>{t('common.retry')}</button>
        </div>
      ) : null}

      <BackofficeSummaryStrip items={[
        { label: t('admin.support_requests_open', {}, 'Open'), value: formatInteger(openCount), toneClassName: openCount ? 'text-amber-600 dark:text-amber-300' : undefined },
        { label: t('admin.support_requests_in_progress', {}, 'In progress'), value: formatInteger(inProgressCount) },
        { label: t('admin.support_requests_page_critical', {}, 'Page overdue'), value: formatInteger(pageSummary.critical), toneClassName: pageSummary.critical ? 'text-rose-600 dark:text-rose-300' : undefined },
        { label: t('admin.support_requests_total', {}, 'Filtered total'), value: formatInteger(total) },
        { label: t('common.updated_at', {}, 'Updated'), value: loadedAt ? formatDate(loadedAt.toISOString()) : t('common.unknown', {}, 'Unknown') },
      ]} />

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.65fr)_minmax(20rem,0.72fr)]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div className="space-y-4 border-b border-slate-200/80 px-5 py-5 dark:border-slate-800 md:px-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-slate-950 dark:text-white">{t('admin.support_requests_queue_title', {}, 'Customer ticket queue')}</h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('admin.support_requests_queue_desc', {}, 'The service applies filters and pagination; risk ordering applies to the current page.')}</p>
              </div>
              <p className="text-sm font-medium text-slate-500 dark:text-slate-400" role="status">{t('admin.support_requests_result_count', { visible: formatInteger(sortedItems.length), total: formatInteger(total) }, `${formatInteger(sortedItems.length)} on this page · ${formatInteger(total)} total`)}</p>
            </div>

            <div className="flex flex-wrap gap-2" aria-label={t('admin.support_requests_status_filter_label', {}, 'Ticket status')}>
              {STATUS_FILTERS.map((status) => (
                <button
                  key={status || 'all'}
                  type="button"
                  aria-pressed={appliedStatus === status}
                  className={cn('cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium transition', appliedStatus === status ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200' : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600')}
                  onClick={() => updateQueueUrl({ status: status || null, offset: null, focus: null })}
                >
                  {status ? t(`admin.support_status_${status}`, {}, status) : t('common.all', {}, 'All')}
                </button>
              ))}
            </div>

            <form onSubmit={applySearch} className="grid gap-3 md:grid-cols-2 2xl:grid-cols-[minmax(13rem,1.2fr)_minmax(9rem,0.7fr)_minmax(9rem,0.7fr)_auto]">
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.support_requests_search_label', {}, 'Search tickets')}</span>
                <input name="q" type="search" className="input w-full" value={queryDraft} onChange={(event) => setQueryDraft(event.target.value)} placeholder={t('admin.support_requests_search_placeholder', {}, 'Email, site, account, or title')} />
              </label>
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.support_requests_topic_filter_label', {}, 'Ticket topic')}</span>
                <select className="input w-full" value={appliedTopic} onChange={(event) => updateQueueUrl({ topic: event.target.value || null, offset: null, focus: null })}>
                  {TOPIC_FILTERS.map((topic) => <option key={topic || 'all'} value={topic}>{topic ? t(`portal.support_topic_${topic}`, {}, topic) : t('admin.support_topic_all', {}, 'All topics')}</option>)}
                </select>
              </label>
              <label className="text-sm text-slate-700 dark:text-slate-200">
                <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.support_requests_sort_label', {}, 'Sort')}</span>
                <select className="input w-full" value={sort} onChange={(event) => updateQueueUrl({ sort: normalizeSort(event.target.value), focus: null })}>
                  <option value="risk">{t('admin.support_requests_sort_risk', {}, 'Current-page risk')}</option>
                  <option value="updated_at">{t('admin.support_requests_sort_updated', {}, 'Recently updated')}</option>
                </select>
              </label>
              <div className="flex items-end gap-2 md:col-span-2 2xl:col-span-1">
                <button type="submit" className="btn btn-primary flex-1 2xl:flex-none">{t('common.apply', {}, 'Apply')}</button>
                <button type="button" className="btn btn-secondary flex-1 2xl:flex-none" disabled={!hasFilters && !queryDraft} onClick={clearFilters}>{t('common.clear_filters', {}, 'Clear filters')}</button>
              </div>
            </form>
          </div>

          {sortedItems.length ? (
            <div role="list" aria-label={t('admin.support_requests_list_label', {}, 'Ticket list')}>
              {sortedItems.map((item) => {
                const risk = requestRisk(item);
                const isSelected = selectedRequest?.request_id === item.request_id;
                const age = ageHours(item.created_at);
                const riskReason = risk === 'critical'
                  ? t('admin.support_requests_reason_overdue', {}, 'This unanswered or urgent ticket needs immediate operator review.')
                  : risk === 'warning'
                    ? t('admin.support_requests_reason_open', {}, 'The customer is waiting for the first operator response.')
                    : risk === 'monitor'
                      ? t('admin.support_requests_reason_in_progress', {}, 'Work has started; keep the customer conversation and internal next step current.')
                      : t('admin.support_requests_reason_complete', {}, 'The ticket is resolved or closed and remains available as support history.');
                return (
                  <article key={item.request_id} role="listitem" data-ui="support-request-queue-item" className={cn('grid gap-4 border-b border-slate-200/80 px-5 py-5 transition last:border-b-0 dark:border-slate-800 md:grid-cols-[minmax(11rem,0.9fr)_minmax(13rem,1.1fr)] md:items-center md:px-6 2xl:grid-cols-[minmax(12rem,1fr)_minmax(14rem,1.2fr)_minmax(9rem,0.75fr)_auto]', isSelected ? 'bg-blue-50/65 dark:bg-blue-950/15' : 'hover:bg-slate-50/70 dark:hover:bg-slate-950/35')}>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="line-clamp-2 font-semibold text-slate-950 dark:text-white">{item.title}</h3>
                        <BackofficeStatusBadge status={statusTone(item.status)} label={t(`admin.support_status_${item.status}`, {}, item.status)} />
                      </div>
                      <p className="mt-2 truncate text-xs text-slate-500 dark:text-slate-400">{item.email}</p>
                      <div className="mt-1 text-xs text-slate-500 dark:text-slate-400"><BackofficeIdentifier value={item.request_id} /></div>
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={cn('inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', riskToneClassName(risk))}>{t(`admin.support_requests_risk_${risk}`, {}, risk)}</span>
                        <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{t(`portal.support_topic_${item.topic}`, {}, item.topic)}</span>
                      </div>
                      <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{riskReason}</p>
                    </div>
                    <dl className="grid gap-2 text-xs text-slate-600 dark:text-slate-300">
                      <div className="flex justify-between gap-3"><dt>{t('admin.account_id', {}, 'Account ID')}</dt><dd className="max-w-32 truncate font-semibold text-slate-950 dark:text-white">{item.account_id}</dd></div>
                      <div className="flex justify-between gap-3"><dt>{t('common.site', {}, 'Site')}</dt><dd className="max-w-32 truncate font-semibold text-slate-950 dark:text-white">{item.site_id || t('common.not_available', {}, 'N/A')}</dd></div>
                      <div className="flex justify-between gap-3"><dt>{t('admin.support_requests_age_label', {}, 'Age')}</dt><dd className="font-semibold text-slate-950 dark:text-white">{age === null ? t('common.unknown', {}, 'Unknown') : t('admin.support_requests_age_hours', { hours: String(age) }, `${age}h`)}</dd></div>
                    </dl>
                    <div className="flex flex-wrap gap-2 md:justify-end">
                      <button type="button" className="btn btn-secondary btn-sm" aria-pressed={isSelected} aria-controls="support-request-inspector" onClick={() => updateQueueUrl({ focus: item.request_id })}>{t('admin.support_requests_inspect_action', {}, 'Inspect')}</button>
                      <Link className="btn btn-primary btn-sm" href={`/admin/support-requests/${encodeURIComponent(item.request_id)}`}>{t('admin.support_request_view_detail', {}, 'View detail')}</Link>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <BackofficeEmptyState className="m-5 md:m-6" title={t('admin.support_requests_empty_title', {}, 'No tickets in this view')} description={t('admin.support_requests_empty_desc', {}, 'Change the filter or wait for Portal users to submit a ticket.')} action={hasFilters ? <button type="button" className="btn btn-secondary btn-sm" onClick={clearFilters}>{t('common.clear_filters', {}, 'Clear filters')}</button> : null} />
          )}

          <ListPagination offset={offset} limit={PAGE_SIZE} total={total} isLoading={isRefreshing} onOffsetChange={(nextOffset) => updateQueueUrl({ offset: String(nextOffset), focus: null })} />
        </BackofficeSectionPanel>

        <aside id="support-request-inspector" className="xl:sticky xl:top-24" aria-live="polite">
          <BackofficeSectionPanel className="space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{t('admin.support_requests_inspector_eyebrow', {}, 'Inspector')}</p>
                <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{t('admin.support_requests_inspector_title', {}, 'Current ticket')}</h2>
              </div>
              {selectedRequest ? <span className={cn('inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold', riskToneClassName(requestRisk(selectedRequest)))}>{t(`admin.support_requests_risk_${requestRisk(selectedRequest)}`, {}, requestRisk(selectedRequest))}</span> : null}
            </div>
            {selectedRequest ? (
              <div className="space-y-5">
                <div>
                  <p className="text-base font-semibold text-slate-950 dark:text-white">{selectedRequest.title}</p>
                  <div className="mt-1 text-xs text-slate-500 dark:text-slate-400"><BackofficeIdentifier value={selectedRequest.request_id} full /></div>
                </div>
                <section aria-labelledby="customer-submission-title" className="rounded-xl border border-slate-200/80 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/35">
                  <h3 id="customer-submission-title" className="text-sm font-semibold text-slate-950 dark:text-white">{t('admin.support_requests_customer_submission_title', {}, 'Customer submission')}</h3>
                  <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-600 dark:text-slate-300">{selectedRequest.description}</p>
                  <dl className="mt-3 grid gap-1 text-xs text-slate-500 dark:text-slate-400">
                    <div className="flex justify-between gap-3"><dt>{t('common.email', {}, 'Email')}</dt><dd className="truncate text-right">{selectedRequest.email}</dd></div>
                    <div className="flex justify-between gap-3"><dt>{t('admin.account_id', {}, 'Account ID')}</dt><dd className="truncate text-right">{selectedRequest.account_id}</dd></div>
                    <div className="flex justify-between gap-3"><dt>{t('common.site', {}, 'Site')}</dt><dd className="truncate text-right">{selectedRequest.site_id || t('common.not_available', {}, 'N/A')}</dd></div>
                    <div className="flex justify-between gap-3"><dt>{t('common.updated_at', {}, 'Updated')}</dt><dd>{selectedRequest.updated_at ? formatDate(selectedRequest.updated_at) : t('common.unknown', {}, 'Unknown')}</dd></div>
                  </dl>
                </section>
                <section aria-labelledby="internal-handling-title" className="space-y-3 border-t border-slate-200/80 pt-4 dark:border-slate-800">
                  <div>
                    <h3 id="internal-handling-title" className="text-sm font-semibold text-slate-950 dark:text-white">{t('admin.support_requests_internal_handling_title', {}, 'Internal handling')}</h3>
                    <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">{t('admin.support_requests_internal_handling_desc', {}, 'Status and this note are internal. Use ticket detail for the customer conversation.')}</p>
                  </div>
                  <label className="block text-sm text-slate-700 dark:text-slate-200">
                    <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('common.status')}</span>
                    <select className="input w-full" value={statusDraft} onChange={(event) => setStatusDraft(event.target.value as SupportRequestStatus)}>
                      {NEXT_STATUSES.map((status) => <option key={status} value={status}>{t(`admin.support_status_${status}`, {}, status)}</option>)}
                    </select>
                  </label>
                  <label className="block text-sm text-slate-700 dark:text-slate-200">
                    <span className="mb-1.5 block text-xs font-medium text-slate-500 dark:text-slate-400">{t('admin.support_requests_note_placeholder', {}, 'Internal handling note')}</span>
                    <textarea className="input min-h-28 w-full" value={noteDraft} onChange={(event) => setNoteDraft(event.target.value)} placeholder={t('admin.support_requests_note_placeholder', {}, 'Internal handling note')} />
                  </label>
                  {actionError ? <p role="alert" className="text-sm text-rose-700 dark:text-rose-300">{actionError}</p> : null}
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="btn btn-primary btn-sm" disabled={pendingRequestId === selectedRequest.request_id} onClick={() => void handleUpdate(selectedRequest)}>{pendingRequestId === selectedRequest.request_id ? t('common.saving', {}, 'Saving...') : t('admin.support_requests_update_action', {}, 'Update ticket')}</button>
                    <Link className="btn btn-secondary btn-sm" href={`/admin/support-requests/${encodeURIComponent(selectedRequest.request_id)}`}>{t('admin.support_requests_open_conversation_action', {}, 'Open conversation')}</Link>
                  </div>
                </section>
                <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{t('admin.support_requests_inspector_boundary', {}, 'The queue updates Cloud support status and internal notes only. Public replies, attachments, and the full timeline stay in ticket detail; no WordPress write is created.')}</p>
              </div>
            ) : <p className="text-sm text-slate-600 dark:text-slate-300">{t('admin.support_requests_inspector_empty', {}, 'No ticket is visible on this page.')}</p>}
          </BackofficeSectionPanel>
        </aside>
      </div>
    </BackofficePageStack>
  );
}

export default function AdminSupportRequestsPage() {
  return <Suspense fallback={<LoadingFallback />}><SupportRequestsContent /></Suspense>;
}
