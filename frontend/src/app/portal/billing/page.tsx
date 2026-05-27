'use client';

import React, { Suspense, useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type PortalBillingReconciliation,
  type PortalBillingSnapshot,
} from '@/lib/portal-client';
import { DEFAULT_PORTAL_CURRENCY, formatPortalCurrency, normalizePortalCurrency } from '@/lib/currency';
import { formatCompactNumber, formatDate, formatNumber } from '@/lib/utils';

function sumSnapshots(
  snapshots: PortalBillingSnapshot[],
  selector: (snapshot: PortalBillingSnapshot) => number | undefined
): number {
  return snapshots.reduce((total, snapshot) => total + Number(selector(snapshot) || 0), 0);
}

function PortalBillingContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { sites, selectedSiteId, selectedSite, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });
  const [snapshots, setSnapshots] = useState<PortalBillingSnapshot[]>([]);
  const [reconciliation, setReconciliation] = useState<PortalBillingReconciliation | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadBilling = useCallback(async (siteId: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const bundle = await portalClient.getBillingBundle(siteId);
      setSnapshots(bundle.snapshots);
      setReconciliation(bundle.reconciliation);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('error.failed_load', {}, 'Failed to load.'));
      setSnapshots([]);
      setReconciliation(null);
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (!selectedSiteId) {
      setIsLoading(false);
      return;
    }
    void loadBilling(selectedSiteId);
  }, [loadBilling, selectedSiteId]);

  if (sessionLoading) {
    return <PortalLoadingState message={t('portal.loading_session', {}, 'Loading session...')} />;
  }

  if (!isAuthenticated || !session) {
    return (
      <PortalSignedOutState
        title={t('auth.sign_in_required', {}, 'Sign in required')}
        description={t('portal.signed_out_desc', {}, 'Sign in to view Cloud service details.')}
        actionLabel={t('nav.sign_in', {}, 'Sign in')}
      />
    );
  }

  if (!sites.length || !selectedSiteId || !selectedSite) {
    return (
      <PortalEmptyState
        title={t('portal.empty_no_site_title', {}, 'No site available')}
        description={t('portal.empty_no_site_desc', {}, 'Ask an operator to provision a site before using Cloud billing detail.')}
      />
    );
  }

  if (isLoading) {
    return <PortalLoadingState message={t('portal.billing.loading', {}, 'Loading billing snapshots...')} />;
  }

  const currency = normalizePortalCurrency(snapshots[0]?.currency || DEFAULT_PORTAL_CURRENCY);
  const totalRuns = sumSnapshots(snapshots, (snapshot) => snapshot.totals?.runs);
  const totalTokens = sumSnapshots(snapshots, (snapshot) => snapshot.totals?.tokens_total);
  const totalCost = sumSnapshots(snapshots, (snapshot) => snapshot.totals?.cost);
  const latestSnapshot = snapshots[0] || null;
  const syncState = reconciliation?.reconciliation?.in_sync;

  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.workspace_label', {}, 'Portal')}
        title={t('portal.nav_billing', {}, 'Billing')}
        description={t('portal.billing.subtitle', {}, 'Read-only billing snapshots and ledger reconciliation for the selected site.')}
        currentPage="billing"
        sites={sites}
        selectedSiteId={selectedSiteId}
        onSiteChange={setSelectedSiteId}
      />

      {error ? (
        <PortalErrorState
          title={t('error.failed_load', {}, 'Failed to load')}
          description={error}
          retryLabel={t('common.retry', {}, 'Retry')}
          onRetry={() => void loadBilling(selectedSiteId)}
        />
      ) : null}

      <BackofficeMetricStrip
        items={[
          { label: t('portal.billing.snapshots', {}, 'Snapshots'), value: formatNumber(snapshots.length) },
          { label: t('common.requests', {}, 'Requests'), value: formatCompactNumber(totalRuns) },
          { label: t('common.tokens', {}, 'Tokens'), value: formatCompactNumber(totalTokens) },
          { label: t('common.cost', {}, 'Cost'), value: formatPortalCurrency(totalCost, { to: currency }) },
        ]}
      />

      <BackofficeStackCard>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.billing.reconciliation', {}, 'Reconciliation')}
            </p>
            <h2 className="mt-2 text-lg font-semibold text-gray-950 dark:text-white">
              {syncState === false
                ? t('portal.billing.reconciliation_attention', {}, 'Ledger and snapshot need operator review')
                : t('portal.billing.reconciliation_ready', {}, 'Ledger and snapshot are readable')}
            </h2>
          </div>
          <span className="rounded-full border border-gray-200 px-3 py-1 text-xs font-semibold text-gray-700 dark:border-gray-700 dark:text-gray-200">
            {syncState === false ? t('common.attention', {}, 'Attention') : t('common.ok', {}, 'OK')}
          </span>
        </div>
      </BackofficeStackCard>

      <div className="grid gap-4 lg:grid-cols-2">
        {snapshots.map((snapshot) => (
          <BackofficeStackCard key={snapshot.snapshot_id}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-gray-950 dark:text-white">{snapshot.snapshot_id}</p>
                <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                  {formatDate(snapshot.period_start_at)} - {formatDate(snapshot.period_end_at)}
                </p>
              </div>
              <span className="text-xs text-gray-500 dark:text-gray-400">{formatDate(snapshot.generated_at)}</span>
            </div>
            <BackofficeMetricStrip
              items={[
                { label: t('common.requests', {}, 'Requests'), value: formatNumber(snapshot.totals?.runs || 0) },
                { label: t('common.tokens', {}, 'Tokens'), value: formatCompactNumber(snapshot.totals?.tokens_total || 0) },
                { label: t('common.cost', {}, 'Cost'), value: formatPortalCurrency(snapshot.totals?.cost || 0, { to: currency }) },
              ]}
            />
          </BackofficeStackCard>
        ))}
      </div>

      {!snapshots.length ? (
        <PortalEmptyState
          title={t('portal.billing.empty_title', {}, 'No billing snapshots yet')}
          description={t('portal.billing.empty_desc', {}, 'Snapshots appear after an operator rebuilds or the billing cadence records usage.')}
        />
      ) : null}

      {latestSnapshot ? (
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t('portal.billing.latest_snapshot', {}, 'Latest snapshot')}: {latestSnapshot.snapshot_id}
        </p>
      ) : null}
    </BackofficePageStack>
  );
}

export default function PortalBillingPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalBillingContent />
    </Suspense>
  );
}
