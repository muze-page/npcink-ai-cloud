'use client';

import React, { Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { ListPagination } from '@/components/ui/ListPagination';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import {
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalCreditTrendPanel } from '@/components/portal/PortalCreditTrendPanel';
import { useLocale } from '@/contexts/LocaleContext';
import { useRetry } from '@/hooks/useRetry';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type Entitlements,
  type PortalCreditEvent,
  type PortalCreditEventBucket,
  type PortalCreditEventBucketsPayload,
  type PortalCreditEventBucketSize,
  type PortalCreditEventFeature,
  type PortalCreditEventsPayload,
  type PortalCreditEventWindow,
  type PortalCreditTrendPayload,
  type PortalCreditTrendWindow,
  type PortalUsageSummaryPayload,
} from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import type { Locale } from '@/lib/i18n';
import { formatDate, formatNumber } from '@/lib/utils';
import {
  getPortalSiteDisplayName,
  getPortalSiteSecondaryLabel,
  getVisiblePortalSites,
} from '@/lib/portal-site-display';
import {
  PortalPageStack,
  PortalSection,
  PortalMetricStrip,
} from '@/components/portal/PortalScaffold';

function formatQuotaValue(value: unknown, unlimited = false, unlimitedLabel = 'Unlimited'): string {
  if (unlimited) return unlimitedLabel;
  return formatNumber(Math.round(Number(value || 0)));
}

function quotaStatusTone(status: string | undefined): 'ok' | 'warning' | 'error' {
  if (status === 'limited') return 'error';
  if (status === 'near_limit') return 'warning';
  return 'ok';
}

type PortalUsageView = 'trend' | 'records';
const PORTAL_USAGE_VIEWS: PortalUsageView[] = ['trend', 'records'];

function resolvePortalUsageView(value: string | null): PortalUsageView {
  return value === 'records' ? value : 'trend';
}

function parseUsageDate(value: string): Date | null {
  const normalizedValue = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
    ? value
    : `${value.replace(' ', 'T')}Z`;
  const date = new Date(normalizedValue);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatUsagePeriodRange(startValue: string, endValue: string, locale: Locale): string {
  const start = parseUsageDate(startValue);
  const end = parseUsageDate(endValue);
  if (!start || !end) return '';
  const currentYear = new Date().getFullYear();
  const includeYear = start.getFullYear() !== end.getFullYear()
    || start.getFullYear() !== currentYear
    || end.getFullYear() !== currentYear;
  const formatter = new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', {
    ...(includeYear ? { year: 'numeric' as const } : {}),
    month: locale === 'en' ? 'short' : 'numeric',
    day: 'numeric',
  });
  return `${formatter.format(start)} – ${formatter.format(end)}`;
}

function formatUsagePeriodEnd(value: string, locale: Locale): string {
  const date = parseUsageDate(value);
  if (!date) return '';
  return new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', {
    year: 'numeric',
    month: locale === 'en' ? 'short' : 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function formatUsageUpdatedAt(value: string, locale: Locale): string {
  const date = parseUsageDate(value);
  if (!date) return '';
  const now = new Date();
  const sameDay = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
  return new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', sameDay
    ? { hour: '2-digit', minute: '2-digit' }
    : {
        ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' as const } : {}),
        month: locale === 'en' ? 'short' : 'numeric',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }).format(date);
}

function formatCreditEventTime(value: string, locale: Locale): string {
  const date = parseUsageDate(value);
  if (!date) return '-';
  const now = new Date();
  const sameDay = date.toDateString() === now.toDateString();
  const time = new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
  if (sameDay) return locale === 'en' ? `Today ${time}` : `今天 ${time}`;
  return new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', {
    ...(date.getFullYear() !== now.getFullYear() ? { year: 'numeric' as const } : {}),
    month: locale === 'en' ? 'short' : 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function formatCreditBucketRange(startValue: string, endValue: string, locale: Locale): string {
  const start = parseUsageDate(startValue);
  const end = parseUsageDate(endValue);
  if (!start || !end) return '-';
  const date = new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', {
    month: locale === 'en' ? 'short' : 'numeric',
    day: 'numeric',
  }).format(start);
  const time = new Intl.DateTimeFormat(locale === 'en' ? 'en-US' : 'zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  });
  return `${date} ${time.format(start)}-${time.format(end)}`;
}

function PortalUsageContent() {
  const { locale, t } = useLocale();
  const searchParams = useSearchParams();
  const { session, isLoading: sessionLoading, isAuthenticated } = useSession();
  const [usage, setUsage] = useState<PortalUsageSummaryPayload | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [creditEvents, setCreditEvents] = useState<PortalCreditEventsPayload | null>(null);
  const [creditEventBuckets, setCreditEventBuckets] = useState<PortalCreditEventBucketsPayload | null>(null);
  const [creditEventOffset, setCreditEventOffset] = useState(0);
  const [creditEventLoading, setCreditEventLoading] = useState(false);
  const [creditEventError, setCreditEventError] = useState('');
  const [creditEventWindow, setCreditEventWindow] = useState<PortalCreditEventWindow>('7d');
  const [creditEventFeature, setCreditEventFeature] = useState<PortalCreditEventFeature>('');
  const [creditEventBucketSize, setCreditEventBucketSize] = useState<PortalCreditEventBucketSize>('30m');
  const [selectedCreditBucket, setSelectedCreditBucket] = useState<PortalCreditEventBucket | null>(null);
  const [selectedCreditEvent, setSelectedCreditEvent] = useState<PortalCreditEvent | null>(null);
  const [creditLedgerSiteId, setCreditLedgerSiteId] = useState(
    () => searchParams.get('site') || ''
  );
  const [creditTrendWindow, setCreditTrendWindow] = useState<PortalCreditTrendWindow>('24h');
  const [creditTrend, setCreditTrend] = useState<PortalCreditTrendPayload | null>(null);
  const [creditTrendLoading, setCreditTrendLoading] = useState(true);
  const [creditTrendError, setCreditTrendError] = useState('');
  const creditTrendRequestId = useRef(0);
  const [activeUsageView, setActiveUsageView] = useState<PortalUsageView>(
    () => resolvePortalUsageView(searchParams.get('view'))
  );
  const creditEventPageSize = 20;

  const loadBundle = useCallback(async () => {
    const bundle = await portalClient.getUsageBundle();
    setUsage(bundle.usage);
    setEntitlements(bundle.entitlements);
  }, []);

  const { execute, isLoading: retryLoading, error: retryError, retry } = useRetry(loadBundle, {
    maxRetries: 2,
    initialDelay: 800,
    backoffMultiplier: 2,
  });

  const loadCreditEventBucketPage = useCallback(async (nextOffset: number) => {
    setCreditEventLoading(true);
    setCreditEventError('');
    try {
      const response = await portalClient.getAccountCreditEventBuckets({
        bucket: creditEventBucketSize,
        window: creditEventWindow,
        siteId: creditLedgerSiteId || undefined,
        feature: creditEventFeature,
        limit: creditEventPageSize,
        offset: nextOffset,
      });
      setCreditEventBuckets(response.data);
      setCreditEventOffset(nextOffset);
    } catch (err) {
      setCreditEventError(formatPortalErrorMessage(err, t, t('error.failed_load')));
    } finally {
      setCreditEventLoading(false);
    }
  }, [creditEventBucketSize, creditEventFeature, creditEventWindow, creditLedgerSiteId, t]);

  const openCreditBucket = useCallback(async (bucket: PortalCreditEventBucket) => {
    setSelectedCreditBucket(bucket);
    setCreditEvents(null);
    setCreditEventLoading(true);
    setCreditEventError('');
    try {
      const response = await portalClient.getAccountCreditEvents({
        window: creditEventWindow,
        siteId: creditLedgerSiteId || undefined,
        feature: creditEventFeature,
        startAt: bucket.start_at,
        endAt: bucket.end_at,
        limit: 50,
        offset: 0,
      });
      setCreditEvents(response.data);
    } catch (err) {
      setCreditEventError(formatPortalErrorMessage(err, t, t('error.failed_load')));
    } finally {
      setCreditEventLoading(false);
    }
  }, [creditEventFeature, creditEventWindow, creditLedgerSiteId, t]);

  const loadCreditTrend = useCallback(async () => {
    const requestId = creditTrendRequestId.current + 1;
    creditTrendRequestId.current = requestId;
    setCreditTrendLoading(true);
    setCreditTrendError('');
    try {
      const response = await portalClient.getAccountCreditTrend({
        window: creditTrendWindow,
        siteId: creditLedgerSiteId || undefined,
      });
      if (creditTrendRequestId.current !== requestId) return;
      setCreditTrend(response.data);
    } catch (err) {
      if (creditTrendRequestId.current !== requestId) return;
      setCreditTrendError(formatPortalErrorMessage(err, t, t('error.failed_load')));
    } finally {
      if (creditTrendRequestId.current === requestId) setCreditTrendLoading(false);
    }
  }, [creditLedgerSiteId, creditTrendWindow, t]);

  useEffect(() => {
    const requestedView = searchParams.get('view');
    setActiveUsageView(resolvePortalUsageView(requestedView));
    if (requestedView && requestedView !== 'records') {
      const nextParams = new URLSearchParams(searchParams.toString());
      nextParams.delete('view');
      const query = nextParams.toString();
      window.history.replaceState(
        window.history.state,
        '',
        `/portal/usage${query ? `?${query}` : ''}`,
      );
    }
  }, [searchParams]);

  useEffect(() => {
    const savedBucketSize = window.localStorage.getItem('portal-credit-bucket-size');
    if (savedBucketSize === '10m' || savedBucketSize === '30m' || savedBucketSize === '60m') {
      setCreditEventBucketSize(savedBucketSize);
    }
  }, []);

  useEffect(() => {
    if (!session || !isAuthenticated) {
      return;
    }
    void execute();
  }, [isAuthenticated, session, execute]);

  useEffect(() => {
    if (!session || !isAuthenticated) {
      return;
    }
    if (activeUsageView !== 'records') return;
    const selectableSiteIds = new Set(getVisiblePortalSites(session.sites).map((site) => site.site_id));
    if (creditLedgerSiteId && !selectableSiteIds.has(creditLedgerSiteId)) {
      setCreditLedgerSiteId('');
      return;
    }
    void loadCreditEventBucketPage(0);
  }, [activeUsageView, creditEventBucketSize, creditEventFeature, creditEventWindow, creditLedgerSiteId, isAuthenticated, loadCreditEventBucketPage, session]);

  useEffect(() => {
    if (!session || !isAuthenticated) return;
    if (activeUsageView !== 'trend') return;
    void loadCreditTrend();
  }, [activeUsageView, isAuthenticated, loadCreditTrend, session]);

  useEffect(() => {
    if (!selectedCreditEvent && !selectedCreditBucket) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (selectedCreditEvent) setSelectedCreditEvent(null);
        else setSelectedCreditBucket(null);
      }
    };
    document.addEventListener('keydown', handleEscape);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleEscape);
      document.body.style.overflow = '';
    };
  }, [selectedCreditBucket, selectedCreditEvent]);

  const handleUsageViewChange = (nextView: PortalUsageView) => {
    setActiveUsageView(nextView);
    const nextParams = new URLSearchParams(searchParams.toString());
    if (nextView === 'trend') nextParams.delete('view');
    else nextParams.set('view', nextView);
    const query = nextParams.toString();
    window.history.replaceState(
      window.history.state,
      '',
      `/portal/usage${query ? `?${query}` : ''}`,
    );
  };

  const handleUsageViewKeyDown = (
    event: React.KeyboardEvent<HTMLButtonElement>,
    currentView: PortalUsageView,
  ) => {
    const currentIndex = PORTAL_USAGE_VIEWS.indexOf(currentView);
    const nextIndex = event.key === 'ArrowRight'
      ? (currentIndex + 1) % PORTAL_USAGE_VIEWS.length
      : event.key === 'ArrowLeft'
        ? (currentIndex - 1 + PORTAL_USAGE_VIEWS.length) % PORTAL_USAGE_VIEWS.length
        : event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? PORTAL_USAGE_VIEWS.length - 1
            : -1;
    if (nextIndex < 0) return;
    event.preventDefault();
    const nextView = PORTAL_USAGE_VIEWS[nextIndex];
    handleUsageViewChange(nextView);
    requestAnimationFrame(() => document.getElementById(`portal-usage-tab-${nextView}`)?.focus());
  };

  const errorMessage = retryError
    ? formatPortalErrorMessage(retryError, t, t('error.failed_load'))
    : null;

  if (sessionLoading || retryLoading) {
    return <PortalLoadingState message={t('common.loading')} />;
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('auth.not_signed_in')}
        description={t('auth.please_sign_in')}
        actionLabel={t('nav.sign_in')}
      />
    );
  }

  if (errorMessage) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={errorMessage}
        retryLabel={t('common.retry')}
        onRetry={() => void retry()}
      />
    );
  }

  const budgetState = entitlements?.budget_state || {};
  const overBudget = Object.values(budgetState).some((entry) => Boolean(entry?.over_limit));
  const subscription = entitlements?.subscription || null;
  const quotaSummary = entitlements?.quota_summary || null;
  const creditEventItems = creditEvents?.items || [];
  const creditBucketItems = creditEventBuckets?.items || [];
  const visibleSites = getVisiblePortalSites(session.sites);
  const availableCredits = Number(quotaSummary?.credit?.total_remaining ?? 0);
  const creditEventCount = Number(creditEventBuckets?.pagination?.total ?? 0);
  const filteredConsumedCredits = Number(creditEventBuckets?.summary?.consumed_credits ?? 0);
  const usedCredits = Number(
    quotaSummary?.credit_ledger_summary?.consumed_credits
    ?? quotaSummary?.credit?.used
    ?? 0
  );
  const paidCredits = Number(quotaSummary?.credit?.paid_remaining ?? 0);
  const nextPaidCreditExpiry = String(quotaSummary?.credit?.paid_next_expires_at || '');
  const currentPeriodStart =
    entitlements?.period_start_at ||
    subscription?.current_period_start_at ||
    subscription?.current_period_start ||
    session.current_subscription?.current_period_start ||
    '';
  const currentPeriodEnd =
    entitlements?.period_end_at ||
    subscription?.current_period_end_at ||
    subscription?.current_period_end ||
    session.current_subscription?.current_period_end ||
    '';
  const currentPeriodRange = currentPeriodStart && currentPeriodEnd
    ? formatUsagePeriodRange(currentPeriodStart, currentPeriodEnd, locale)
    : '';
  const currentPeriodEndDetail = currentPeriodEnd
    ? formatUsagePeriodEnd(currentPeriodEnd, locale)
    : '';
  const updatedAtValue = quotaSummary?.generated_at || usage?.generated_at || '';
  const updatedAt = updatedAtValue ? formatUsageUpdatedAt(updatedAtValue, locale) : '';
  const creditRecordsUpdatedAt = creditEventBuckets?.generated_at
    ? formatUsageUpdatedAt(creditEventBuckets.generated_at, locale)
    : '';
  const formatCreditPoints = (value: number) =>
    t('portal.usage.credit_points_value', { count: formatNumber(Math.abs(Math.round(value))) }, '{{count}} points');
  const eventFeatureText = (entry: PortalCreditEvent, field: 'title' | 'detail') =>
    t(
      `portal.usage.credit_ledger_feature_${entry.feature_key}_${field}`,
      {},
      field === 'title' ? entry.feature_label : entry.feature_detail
    );
  const eventSiteLabel = (entry: PortalCreditEvent) => {
    const site = visibleSites.find((candidate) => candidate.site_id === entry.site_id);
    return site ? getPortalSiteDisplayName(site) : t('common.not_available', {}, 'Not available');
  };

  const creditStatus = quotaSummary?.credit?.status;
  const usageStatusLabel = quotaStatusTone(creditStatus) === 'error' || overBudget
    ? t('portal.home.service_status_attention', {}, 'Needs attention')
    : quotaStatusTone(creditStatus) === 'warning'
      ? t('portal.usage.headroom_watch', {}, 'Close to limit')
      : t('portal.home.risk_level_normal', {}, 'Normal');
  const usageHeaderDescription = t(
    'portal.usage.summary_desc',
    {},
    "Review this period's account point use, records, and trends."
  );
  const usageHeaderInfo = updatedAt
    ? `${usageHeaderDescription} · ${t(
        'portal.usage.updated_at_inline',
        { time: updatedAt },
        'Updated {{time}}'
      )}`
    : usageHeaderDescription;
  const usageHeaderMetrics = [
    {
      label: t('common.status'),
      value: usageStatusLabel,
      detail: t('portal.usage.status_plain_detail', {}, 'Use the numbers below to decide whether you need more points.'),
    },
    {
      label: t('portal.usage.period_label', {}, 'Period'),
      value: currentPeriodRange || t('common.not_found'),
      detail: currentPeriodEndDetail
        ? t(
            'portal.usage.period_end_detail',
            { time: currentPeriodEndDetail },
            'Ends {{time}}'
          )
        : t('portal.usage.header_period_detail', {}, 'Current package period.'),
      size: 'compact' as const,
    },
  ];
  const usageOverviewMetrics = [
    {
      label: t('portal.usage.total_remaining_label', {}, 'Total available'),
      value: formatQuotaValue(availableCredits),
      detail: t('portal.usage.overview_available_detail', {}, 'Package and paid points available now.'),
    },
    {
      label: t('portal.usage.period_used_label', {}, 'Points deducted this period'),
      value: formatQuotaValue(usedCredits),
      detail: t('portal.usage.trend_points_detail', {}, 'Actual service deductions in the current package period.'),
    },
    {
      label: t('portal.usage.paid_remaining_label', {}, 'Paid credits'),
      value: formatQuotaValue(paidCredits),
      detail: t('portal.usage.overview_paid_detail', {}, 'Purchased points that remain available.'),
    },
    {
      label: t('portal.usage.next_expiry_label', {}, 'Next expiry'),
      value: nextPaidCreditExpiry ? formatDate(nextPaidCreditExpiry) : t('common.not_available', {}, 'Not available'),
      detail: nextPaidCreditExpiry
        ? t('portal.usage.paid_credit_expiry_hint', { date: formatDate(nextPaidCreditExpiry) }, `The next paid credit grant expires on ${formatDate(nextPaidCreditExpiry)}.`)
        : t('portal.usage.overview_no_expiry_detail', {}, 'No paid-credit expiry is currently recorded.'),
      size: 'compact' as const,
    },
  ];

  return (
    <PortalPageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.usage.summary_label', {}, 'Usage')}
        title={t('portal.nav_usage', {}, 'Usage')}
        eyebrowInfo={usageHeaderInfo}
        currentPage="usage"
        metrics={usageHeaderMetrics}
        metricsColumnsClassName="lg:grid-cols-2"
      />

      {entitlements ? (
        <PortalSection className="space-y-5" data-portal-usage="current-summary">
          <div>
            <h2 className="text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.usage.overview_title', {}, 'This period')}
            </h2>
            <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-400">
              {t('portal.usage.overview_desc', {}, 'See what is available, what was used, and whether paid points are nearing expiry.')}
            </p>
          </div>
          <PortalMetricStrip items={usageOverviewMetrics} columnsClassName="md:grid-cols-2 xl:grid-cols-4" />
        </PortalSection>
      ) : null}

      <PortalSection className="p-2" data-portal-usage="view-tabs">
        <div
          role="tablist"
          aria-label={t('portal.usage.view_tabs_label', {}, 'Usage views')}
          className="grid gap-1 sm:grid-cols-2"
        >
          {([
            { value: 'trend', label: t('portal.usage.view_tab_trend', {}, 'Trend') },
            { value: 'records', label: t('portal.usage.view_tab_records', {}, 'Point records') },
          ] as Array<{ value: PortalUsageView; label: string }>).map((view) => (
            <button
              key={view.value}
              id={`portal-usage-tab-${view.value}`}
              type="button"
              role="tab"
              aria-selected={activeUsageView === view.value}
              aria-controls={`portal-usage-panel-${view.value}`}
              tabIndex={activeUsageView === view.value ? 0 : -1}
              className={`min-h-11 rounded-xl px-4 py-2.5 text-sm font-semibold transition-colors ${
                activeUsageView === view.value
                  ? 'bg-slate-950 text-white shadow-sm dark:bg-white dark:text-slate-950'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950 dark:text-slate-300 dark:hover:bg-slate-900 dark:hover:text-white'
              }`}
              onClick={() => handleUsageViewChange(view.value)}
              onKeyDown={(event) => handleUsageViewKeyDown(event, view.value)}
            >
              {view.label}
            </button>
          ))}
        </div>
      </PortalSection>

      <div
        id="portal-usage-panel-trend"
        role="tabpanel"
        aria-labelledby="portal-usage-tab-trend"
        hidden={activeUsageView !== 'trend'}
      >
        {activeUsageView === 'trend' ? (
          <PortalCreditTrendPanel
            payload={creditTrend}
            window={creditTrendWindow}
            isLoading={creditTrendLoading}
            error={creditTrendError}
            onWindowChange={setCreditTrendWindow}
            onRetry={() => void loadCreditTrend()}
          />
        ) : null}
      </div>

      <PortalSection
        id="portal-usage-panel-records"
        role="tabpanel"
        aria-labelledby="portal-usage-tab-records"
        hidden={activeUsageView !== 'records'}
        className="space-y-5"
        data-portal-usage="ledger-detail"
      >
          {activeUsageView === 'records' && entitlements ? (
            <div className="space-y-5" data-portal-usage="usage-records">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="text-xl font-semibold text-gray-950 dark:text-white">
                {t('portal.usage.credit_events_title', {}, 'Point records')}
              </h2>
              <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-400">
                {t(
                  'portal.usage.credit_buckets_summary',
                  {
                    credits: formatQuotaValue(filteredConsumedCredits),
                    count: formatQuotaValue(creditEventCount),
                  },
                  '{{credits}} points used across {{count}} time periods.'
                )}
                {creditRecordsUpdatedAt
                  ? ` · ${t('portal.usage.updated_at_inline', { time: creditRecordsUpdatedAt }, 'Updated {{time}}')}`
                  : ''}
              </p>
            </div>
          </div>
          <div className="grid gap-3 lg:grid-cols-4" aria-label={t('portal.usage.credit_events_filters', {}, 'Point record filters')}>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <span>{t('portal.usage.credit_events_window_label', {}, 'Time range')}</span>
              <select className="input" value={creditEventWindow} disabled={creditEventLoading} onChange={(event) => { setCreditEventWindow(event.target.value as PortalCreditEventWindow); setCreditEventOffset(0); }}>
                <option value="24h">{t('portal.usage.credit_events_window_24h', {}, 'Last 24 hours')}</option>
                <option value="7d">{t('portal.usage.credit_events_window_7d', {}, 'Last 7 days')}</option>
                <option value="30d">{t('portal.usage.credit_events_window_30d', {}, 'Last 30 days')}</option>
                <option value="period">{t('portal.usage.credit_events_window_period', {}, 'Current package period')}</option>
              </select>
            </label>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <span>{t('portal.usage.credit_buckets_size_label', {}, 'Summary interval')}</span>
              <select className="input" value={creditEventBucketSize} disabled={creditEventLoading} onChange={(event) => { const value = event.target.value as PortalCreditEventBucketSize; setCreditEventBucketSize(value); window.localStorage.setItem('portal-credit-bucket-size', value); setCreditEventOffset(0); }}>
                <option value="10m">{t('portal.usage.credit_buckets_size_10m', {}, '10 minutes')}</option>
                <option value="30m">{t('portal.usage.credit_buckets_size_30m', {}, '30 minutes')}</option>
                <option value="60m">{t('portal.usage.credit_buckets_size_60m', {}, '60 minutes')}</option>
              </select>
            </label>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <span>{t('portal.usage.site_filter_label', {}, 'Site')}</span>
            <select
              id="portal-usage-site"
              className="input"
              value={creditLedgerSiteId}
              disabled={creditEventLoading}
              onChange={(event) => {
                setCreditLedgerSiteId(event.target.value);
                setCreditEventOffset(0);
              }}
            >
              <option value="">{t('portal.usage.all_sites_option', {}, 'All sites')}</option>
              {visibleSites.map((site) => (
                <option key={site.site_id} value={site.site_id}>
                  {getPortalSiteDisplayName(site)} ({getPortalSiteSecondaryLabel(site)})
                </option>
              ))}
            </select>
            </label>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <span>{t('portal.usage.credit_events_feature_label', {}, 'Service')}</span>
              <select className="input" value={creditEventFeature} disabled={creditEventLoading} onChange={(event) => { setCreditEventFeature(event.target.value as PortalCreditEventFeature); setCreditEventOffset(0); }}>
                <option value="">{t('portal.usage.credit_events_feature_all', {}, 'All services')}</option>
                {['content_generation', 'topic_research', 'web_search', 'site_knowledge', 'image_assistance', 'audio_generation'].map((feature) => (
                  <option key={feature} value={feature}>{t(`portal.usage.credit_ledger_feature_${feature}_title`)}</option>
                ))}
              </select>
            </label>
          </div>
          {creditEventError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">{creditEventError}</div>
          ) : creditEventLoading && !creditEventBuckets ? (
            <div className="space-y-2" aria-label={t('common.loading')}>
              {[0, 1, 2, 3].map((item) => <div key={item} className="h-16 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-900" />)}
            </div>
          ) : creditBucketItems.length > 0 ? (
            <div className="overflow-hidden rounded-[1rem] border border-slate-200 dark:border-slate-800">
              <div className="hidden grid-cols-[1.2fr_0.55fr_0.55fr_0.8fr] gap-3 bg-slate-50 px-4 py-2 text-xs font-semibold text-slate-500 dark:bg-slate-950/45 dark:text-slate-400 sm:grid">
                <span>{t('portal.usage.credit_buckets_time_column', {}, 'Time period')}</span>
                <span className="text-right">{t('portal.usage.credit_events_points_column', {}, 'Points')}</span>
                <span className="text-right">{t('portal.usage.credit_buckets_events_column', {}, 'Services')}</span>
                <span className="text-right">{t('portal.usage.credit_buckets_top_service_column', {}, 'Main service')}</span>
              </div>
              <div className="divide-y divide-slate-200 text-sm dark:divide-slate-800">
                {creditBucketItems.map((bucket) => (
                  <button
                    type="button"
                    key={bucket.bucket_id}
                    onClick={() => void openCreditBucket(bucket)}
                    className="grid w-full grid-cols-1 gap-2 px-4 py-3 text-left transition hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:bg-slate-900/50 sm:grid-cols-[1.2fr_0.55fr_0.55fr_0.8fr] sm:items-center sm:gap-3"
                  >
                    <p className="font-medium text-slate-950 dark:text-white">{formatCreditBucketRange(bucket.start_at, bucket.end_at, locale)}</p>
                    <p className="font-semibold text-slate-950 dark:text-white sm:text-right">
                      {formatCreditPoints(bucket.consumed_credits)}
                    </p>
                    <p className="text-slate-600 dark:text-slate-300 sm:text-right">{t('portal.usage.credit_buckets_event_count', { count: formatQuotaValue(bucket.event_count) }, '{{count}} services')}</p>
                    <p className="text-slate-500 dark:text-slate-400 sm:text-right">{bucket.top_feature_key ? t(`portal.usage.credit_ledger_feature_${bucket.top_feature_key}_title`) : '-'}</p>
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="rounded-[1rem] border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
              {t(
                'portal.usage.credit_ledger_empty',
                {},
                'No package point records are available for the current period.'
              )}
            </div>
          )}
          <ListPagination
            offset={creditEventOffset}
            limit={creditEventPageSize}
            total={creditEventCount}
            isLoading={creditEventLoading}
            onOffsetChange={(nextOffset) => void loadCreditEventBucketPage(nextOffset)}
            className="px-0 pb-0"
          />
            </div>
          ) : null}
      </PortalSection>

      {selectedCreditBucket ? (
        <div className="fixed inset-0 z-50">
          <button type="button" className="absolute inset-0 bg-slate-950/45" aria-label={t('common.close')} onClick={() => setSelectedCreditBucket(null)} />
          <aside role="dialog" aria-modal="true" aria-labelledby="credit-bucket-detail-title" className="absolute right-0 top-0 flex h-full w-full max-w-xl flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-5 dark:border-slate-800">
              <div>
                <h2 id="credit-bucket-detail-title" className="text-xl font-semibold text-slate-950 dark:text-white">{formatCreditBucketRange(selectedCreditBucket.start_at, selectedCreditBucket.end_at, locale)}</h2>
                <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t('portal.usage.credit_buckets_detail_summary', { credits: formatQuotaValue(selectedCreditBucket.consumed_credits), count: formatQuotaValue(selectedCreditBucket.event_count) }, '{{count}} services used {{credits}} points.')}</p>
              </div>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setSelectedCreditBucket(null)}>{t('common.close')}</button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-5">
              {creditEventLoading ? (
                <div className="space-y-2">{[0, 1, 2].map((item) => <div key={item} className="h-16 animate-pulse rounded-xl bg-slate-100 dark:bg-slate-900" />)}</div>
              ) : creditEventError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">{creditEventError}</div>
              ) : (
                <div className="divide-y divide-slate-200 rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">
                  {creditEventItems.map((entry) => (
                    <button type="button" key={entry.event_id} onClick={() => { setSelectedCreditBucket(null); setSelectedCreditEvent(entry); }} className="grid w-full gap-1 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-900/50 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-4">
                      <span><strong className="block text-slate-950 dark:text-white">{eventFeatureText(entry, 'title')}</strong><span className="mt-1 block text-xs text-slate-500">{eventSiteLabel(entry)} | {formatCreditEventTime(entry.created_at, locale)}</span></span>
                      <strong className="text-slate-950 dark:text-white">{formatCreditPoints(entry.consumed_credits)}</strong>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </aside>
        </div>
      ) : null}

      {selectedCreditEvent ? (
        <div className="fixed inset-0 z-50">
          <button type="button" className="absolute inset-0 bg-slate-950/45" aria-label={t('common.close')} onClick={() => setSelectedCreditEvent(null)} />
          <aside role="dialog" aria-modal="true" aria-labelledby="credit-event-detail-title" className="absolute right-0 top-0 flex h-full w-full max-w-lg flex-col border-l border-slate-200 bg-white shadow-2xl dark:border-slate-800 dark:bg-slate-950">
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-5 dark:border-slate-800">
              <div><h2 id="credit-event-detail-title" className="text-xl font-semibold text-slate-950 dark:text-white">{eventFeatureText(selectedCreditEvent, 'title')}</h2><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{eventSiteLabel(selectedCreditEvent)}</p></div>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setSelectedCreditEvent(null)}>{t('common.close')}</button>
            </div>
            <div className="flex-1 space-y-6 overflow-y-auto px-5 py-5">
              <dl className="grid gap-4 sm:grid-cols-2">
                <div><dt className="text-xs text-slate-500">{t('portal.usage.credit_events_points_column', {}, 'Points')}</dt><dd className="mt-1 text-lg font-semibold">{formatCreditPoints(selectedCreditEvent.consumed_credits || selectedCreditEvent.net_credit_delta)}</dd></div>
                <div><dt className="text-xs text-slate-500">{t('portal.usage.credit_ledger_time', {}, 'Time')}</dt><dd className="mt-1 font-medium">{formatUsagePeriodEnd(selectedCreditEvent.created_at, locale)}</dd></div>
              </dl>
              <section><h3 className="font-semibold">{t('portal.usage.credit_events_breakdown_title', {}, 'Point breakdown')}</h3><div className="mt-3 divide-y divide-slate-200 rounded-xl border border-slate-200 dark:divide-slate-800 dark:border-slate-800">{selectedCreditEvent.components.map((component) => <div key={component.key} className="flex justify-between gap-4 px-4 py-3 text-sm"><span>{t(`portal.usage.credit_events_component_${component.key}`)}</span><strong>{formatCreditPoints(component.credits)}</strong></div>)}</div>{selectedCreditEvent.component_count > 1 ? <p className="mt-2 text-xs text-slate-500">{t('portal.usage.credit_events_grouped_hint', { count: String(selectedCreditEvent.component_count) }, '{{count}} billing entries were combined into this service event.')}</p> : null}</section>
              <details className="rounded-xl border border-slate-200 px-4 py-3 dark:border-slate-800"><summary className="cursor-pointer font-medium">{t('portal.support_information', {}, 'Support information')}</summary><p className="mt-3 break-all text-sm text-slate-500">{t('portal.usage.credit_events_support_reference', {}, 'Reference')}: {selectedCreditEvent.support_reference}</p></details>
            </div>
          </aside>
        </div>
      ) : null}

    </PortalPageStack>
  );
}

export default function PortalUsagePage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalUsageContent />
    </Suspense>
  );
}
