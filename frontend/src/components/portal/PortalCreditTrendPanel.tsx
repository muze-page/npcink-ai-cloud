'use client';

import { PortalSection } from '@/components/portal/PortalScaffold';
import { useLocale } from '@/contexts/LocaleContext';
import type {
  PortalCreditTrendPayload,
  PortalCreditTrendWindow,
} from '@/lib/portal-client';
import { formatNumber } from '@/lib/utils';

type PortalCreditTrendPanelProps = {
  payload: PortalCreditTrendPayload | null;
  window: PortalCreditTrendWindow;
  isLoading: boolean;
  error: string;
  onWindowChange: (window: PortalCreditTrendWindow) => void;
  onRetry: () => void;
};

const WINDOW_OPTIONS: Array<{ value: PortalCreditTrendWindow; key: string; fallback: string }> = [
  { value: '1h', key: 'portal.usage.trend_window_1h', fallback: '1 hour' },
  { value: '24h', key: 'portal.usage.trend_window_24h', fallback: '24 hours' },
  { value: '7d', key: 'portal.usage.trend_window_7d', fallback: '7 days' },
  { value: '30d', key: 'portal.usage.trend_window_30d', fallback: '30 days' },
];

export function PortalCreditTrendPanel({
  payload,
  window,
  isLoading,
  error,
  onWindowChange,
  onRetry,
}: PortalCreditTrendPanelProps) {
  const { locale, t } = useLocale();
  const points = payload?.points || [];
  const totalCredits = Number(payload?.total_credits || 0);
  const maxCredits = Math.max(...points.map((point) => Number(point.credits || 0)), 0);
  const hasUsage = totalCredits > 0 && maxCredits > 0;
  const labelEvery = points.length <= 12 ? 1 : points.length <= 24 ? 4 : 5;
  const dateLocale = locale === 'en' ? 'en-US' : 'zh-CN';
  const generatedAt = payload?.generated_at || payload?.end_at || '';
  const generatedAtDate = generatedAt ? new Date(generatedAt) : null;
  const updatedAt = generatedAtDate && !Number.isNaN(generatedAtDate.getTime())
    ? new Intl.DateTimeFormat(dateLocale, {
        hour: '2-digit',
        minute: '2-digit',
      }).format(generatedAtDate)
    : '';
  const formatPointLabel = (value: string) => new Intl.DateTimeFormat(
    dateLocale,
    window === '1h' || window === '24h'
      ? { hour: '2-digit', minute: '2-digit' }
      : { month: 'numeric', day: 'numeric' },
  ).format(new Date(value));

  return (
    <PortalSection className="space-y-5" data-portal-usage="primary-trend">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-950 dark:text-white">
            {t('portal.usage.primary_trend_title', {}, 'Point usage trend')}
          </h2>
          <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-400">
            {t('portal.usage.primary_trend_desc', {}, 'Review actual point consumption over time before opening individual usage records.')}
          </p>
        </div>
        <div
          role="tablist"
          aria-label={t('portal.usage.trend_window_label', {}, 'Trend range')}
          className="inline-flex max-w-full gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1 dark:bg-slate-900"
        >
          {WINDOW_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={window === option.value}
              className={`min-h-10 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                window === option.value
                  ? 'bg-white text-blue-700 shadow-sm dark:bg-slate-800 dark:text-blue-300'
                  : 'text-slate-600 hover:text-slate-950 dark:text-slate-400 dark:hover:text-white'
              }`}
              onClick={() => onWindowChange(option.value)}
            >
              {t(option.key, {}, option.fallback)}
            </button>
          ))}
        </div>
      </div>

      <div
        role="tabpanel"
        aria-live="polite"
        data-trend-window={window}
        data-trend-points={points.length}
      >
        {isLoading ? (
          <div className="flex min-h-40 items-center justify-center rounded-xl border border-slate-200 text-sm text-slate-500 dark:border-slate-800 dark:text-slate-400">
            {t('common.loading', {}, 'Loading...')}
          </div>
        ) : error ? (
          <div className="flex min-h-40 flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50/50 px-6 text-center dark:border-red-900/60 dark:bg-red-950/20">
            <p className="text-sm text-red-700 dark:text-red-300">{error}</p>
            <button type="button" className="btn btn-secondary btn-sm" onClick={onRetry}>
              {t('common.retry', {}, 'Retry')}
            </button>
          </div>
        ) : !hasUsage ? (
          <div className="flex min-h-40 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50/60 px-6 text-center dark:border-slate-700 dark:bg-slate-900/35">
            <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              {t('portal.usage.trend_empty_title', {}, 'No point usage in this range')}
            </p>
            <p className="mt-2 max-w-xl text-sm leading-6 text-slate-500 dark:text-slate-400">
              {t('portal.usage.trend_empty_desc', {}, 'Point consumption will appear here after Cloud services are used.')}
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
            <p className="text-sm text-slate-600 dark:text-slate-300">
              {t(
                'portal.usage.trend_total',
                { count: formatNumber(totalCredits) },
                `${formatNumber(totalCredits)} points used in this range`,
              )}
              {updatedAt
                ? ` · ${t('portal.usage.updated_at_inline', { time: updatedAt }, 'Updated {{time}}')}`
                : ''}
            </p>
            <div
              role="img"
              aria-label={t('portal.usage.trend_chart_label', {}, 'Point usage over time')}
              className="mt-4 flex h-44 items-end gap-1"
            >
              {points.map((point, index) => {
                const credits = Number(point.credits || 0);
                const height = credits > 0 ? Math.max(4, (credits / maxCredits) * 100) : 0;
                const pointLabel = formatPointLabel(point.start_at);
                const showLabel = index % labelEvery === 0 || index === points.length - 1;
                return (
                  <div key={point.start_at} className="group relative flex h-full min-w-0 flex-1 flex-col justify-end">
                    <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-2 hidden -translate-x-1/2 whitespace-nowrap rounded-lg bg-slate-950 px-2 py-1 text-xs text-white shadow-lg group-hover:block dark:bg-white dark:text-slate-950">
                      {pointLabel} · {formatNumber(credits)}
                    </div>
                    <div
                      aria-label={`${pointLabel}: ${formatNumber(credits)}`}
                      className="w-full rounded-t bg-blue-500 transition-colors group-hover:bg-blue-600 dark:bg-blue-400 dark:group-hover:bg-blue-300"
                      style={{ height: `${height}%` }}
                    />
                    <span className="absolute top-full mt-2 w-max max-w-14 -translate-x-1/4 text-[11px] text-slate-500 dark:text-slate-400">
                      {showLabel ? pointLabel : ''}
                    </span>
                  </div>
                );
              })}
            </div>
            <div className="h-7" aria-hidden="true" />
          </div>
        )}
      </div>
    </PortalSection>
  );
}
