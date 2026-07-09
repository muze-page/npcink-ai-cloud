import type { Entitlements } from '@/lib/portal-client';
import { cn, formatNumber } from '@/lib/utils';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;
type QuotaSummary = NonNullable<Entitlements['quota_summary']>;
type QuotaResource = NonNullable<QuotaSummary['resource_limits']>[number];
type EntitlementMetric = {
  key?: string;
  used?: number;
  limit?: number;
  remaining?: number;
  unlimited?: boolean;
  usage_ratio?: number;
  status?: string;
};

type PortalEntitlementUsageProps = {
  quotaSummary?: QuotaSummary | null;
  periodLabel?: string;
  t: TranslateFn;
};

function quotaStatusTone(status: string | undefined): 'ok' | 'warning' | 'error' {
  if (status === 'limited') return 'error';
  if (status === 'near_limit') return 'warning';
  return 'ok';
}

function formatQuotaValue(
  value: unknown,
  options: { unlimited?: boolean; unlimitedLabel: string }
): string {
  if (options.unlimited) return options.unlimitedLabel;
  return formatNumber(Math.round(Number(value || 0)));
}

function humanizeKey(key: string): string {
  return String(key || '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function resourceLabel(key: string, t: TranslateFn): string {
  const labels: Record<string, string> = {
    ai_credits: t('portal.usage.package_credit_allowance_label', {}, 'Package points'),
    bound_sites: t('portal.usage.site_allowance_label', {}, 'Sites'),
    vector_documents: t('portal.usage.resource_vector_documents', {}, 'Knowledge articles'),
  };
  return labels[key] || humanizeKey(key);
}

function normalizeMetrics(quotaSummary?: QuotaSummary | null): EntitlementMetric[] {
  if (!quotaSummary) return [];
  const visibleResourceKeys = new Set(['bound_sites', 'vector_documents']);
  const metrics: EntitlementMetric[] = [];
  if (quotaSummary.credit) {
    metrics.push({
      ...quotaSummary.credit,
      key: quotaSummary.credit.key || 'ai_credits',
    });
  }
  const resources = Array.isArray(quotaSummary.resource_limits)
    ? quotaSummary.resource_limits
    : [];
  resources.forEach((resource: QuotaResource) => {
    const key = String(resource.key || '');
    if (visibleResourceKeys.has(key)) {
      metrics.push({ ...resource, key });
    }
  });
  return metrics.filter((metric) => String(metric.key || '').trim());
}

export function PortalEntitlementUsage({
  quotaSummary,
  periodLabel,
  t,
}: PortalEntitlementUsageProps) {
  const unlimitedLabel = t('common.unlimited', {}, 'Unlimited');
  const metrics = normalizeMetrics(quotaSummary);
  const title = t('portal.billing.current_entitlements_title', {}, 'Current package rights');
  const description = t(
    'portal.billing.current_entitlements_desc',
    {},
    'These are the main rights included in the current package.'
  );

  return (
    <section className="space-y-4" data-portal-entitlement-usage="included">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400">
            {t('portal.billing.package_rights_label', {}, 'Package rights')}
          </p>
          <h2 className="mt-1 text-lg font-semibold text-slate-950 dark:text-white">
            {title}
          </h2>
          <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {description}
          </p>
        </div>
        {periodLabel ? (
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {periodLabel}
          </p>
        ) : null}
      </div>

      {metrics.length > 0 ? (
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
          {metrics.map((metric) => {
            const key = String(metric.key || '');
            const used = Number(metric.used || 0);
            const limit = Number(metric.limit || 0);
            const remaining = Number(metric.remaining || 0);
            const displayRemaining = Math.max(0, remaining);
            const unlimited = Boolean(metric.unlimited);
            const ratio = unlimited
              ? 0
              : Math.min(100, Math.max(0, Number(metric.usage_ratio || 0) * 100));
            const tone = quotaStatusTone(metric.status);
            const limitLabel = formatQuotaValue(limit, { unlimited, unlimitedLabel });
            const usedLabel = formatQuotaValue(used, { unlimited: false, unlimitedLabel });
            const remainingLabel = formatQuotaValue(displayRemaining, { unlimited, unlimitedLabel });

            return (
              <div
                key={key}
                className="rounded-xl border border-slate-200/80 bg-white/70 px-4 py-4 dark:border-slate-800 dark:bg-slate-950/35"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-950 dark:text-white">
                      {resourceLabel(key, t)}
                    </p>
                    <p className="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                      {t('portal.billing.entitlement_included_line', {}, 'Included in this package')}
                    </p>
                  </div>
                  <span
                    className={cn(
                      'rounded-full px-2.5 py-1 text-xs font-semibold',
                      tone === 'error'
                        ? 'bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-200'
                        : tone === 'warning'
                          ? 'bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-200'
                          : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-200'
                    )}
                  >
                    {tone === 'error'
                      ? t('portal.home.filter_attention_only', {}, 'Needs attention')
                      : tone === 'warning'
                        ? t('portal.usage.headroom_watch', {}, 'Close to limit')
                        : t('portal.home.risk_level_normal', {}, 'Normal')}
                  </span>
                </div>

                <div className="mt-4 flex items-end justify-between gap-3">
                  <div>
                    <p className="text-2xl font-semibold text-slate-950 dark:text-white">
                      {limitLabel}
                    </p>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {t('portal.usage.included_label', {}, 'Included')}
                    </p>
                  </div>
                  <p className="text-right text-sm text-slate-600 dark:text-slate-300">
                    {t('portal.usage.remaining_credits', {}, 'Remaining')}: {remainingLabel}
                  </p>
                </div>

                {!unlimited ? (
                  <div className="mt-4">
                    <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                      <div
                        className={cn(
                          'h-full rounded-full',
                          tone === 'error'
                            ? 'bg-red-500'
                            : tone === 'warning'
                              ? 'bg-amber-500'
                              : 'bg-emerald-500'
                        )}
                        style={{ width: `${ratio}%` }}
                      />
                    </div>
                    <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                      {usedLabel} / {limitLabel}
                    </p>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500 dark:border-slate-700 dark:text-slate-400">
          {t('portal.billing.no_feature_detail', {}, 'No package rights are available yet.')}
        </div>
      )}
    </section>
  );
}
