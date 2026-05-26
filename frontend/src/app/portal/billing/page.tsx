'use client';

import Link from 'next/link';
import React, { useCallback, useEffect, Suspense, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import { BackofficeTag } from '@/components/backoffice/BackofficeTag';
import { PortalActionRequestResultStrip } from '@/components/portal/PortalActionRequestResultStrip';
import {
  PortalEmptyState,
  PortalErrorState,
  PortalLoadingState,
  PortalSiteSwitchingNotice,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalSiteSelection } from '@/hooks/usePortalSiteSelection';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  PortalApiError,
  type Entitlements,
  type PortalActionRequest,
  type PortalBillingReconciliation,
  type PortalBillingSnapshot,
  type PortalMemberPreferences,
  type PortalPackageChangeRequestPayload,
  type PortalSiteSummaryRecord,
  type PortalTopUpPack,
} from '@/lib/portal-client';
import { localizePackageAlias, localizeUsageBand } from '@/lib/admin-plan-copy';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import { formatPortalActionRequestStatusLabel } from '@/lib/portal-action-request-display';
import {
  localizeTopUpPackLabel,
  localizeTopUpPackPointsLabel,
  localizeTopUpTierLabel,
} from '@/lib/topup-pack-copy';
import {
  DEFAULT_PORTAL_CURRENCY,
  formatPortalCurrency,
  normalizePortalCurrency,
  resolvePortalDisplayCurrency,
  type PortalCurrency,
} from '@/lib/currency';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatCompactNumber, formatDate, formatNumber } from '@/lib/utils';

const PACKAGE_TIER_CATALOG = [
  {
    tierId: 'starter',
    fallbackAlias: 'Free',
    runs: 500,
    tokens: 200_000,
    cost: 5,
    sites: 1,
    concurrency: 1,
    batch: 0,
    featureKeys: [
      'portal.billing.tier_feature_runtime',
      'portal.billing.tier_feature_usage_visibility',
      'portal.billing.tier_feature_operator_changes',
    ],
  },
  {
    tierId: 'pro',
    fallbackAlias: 'Basic',
    runs: 10_000,
    tokens: 2_000_000,
    cost: 99,
    sites: 5,
    concurrency: 2,
    batch: 10,
    featureKeys: [
      'portal.billing.tier_feature_workflow',
      'portal.billing.tier_feature_automation',
      'portal.billing.tier_feature_budget_follow_up',
    ],
  },
  {
    tierId: 'agency',
    fallbackAlias: 'Bulk',
    runs: 50_000,
    tokens: 10_000_000,
    cost: 499,
    sites: 25,
    concurrency: 6,
    batch: 100,
    featureKeys: [
      'portal.billing.tier_feature_concurrency',
      'portal.billing.tier_feature_multisite',
      'portal.billing.tier_feature_sustained_automation',
    ],
  },
] as const;

function coerceFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function flattenEntitlements(value: unknown): string[] {
  if (!value || typeof value !== 'object') {
    return [];
  }

  return Object.values(value as Record<string, unknown>)
    .flatMap((entry) => (Array.isArray(entry) ? entry : []))
    .map((entry) => String(entry || '').trim())
    .filter(Boolean);
}

function inferTierId({
  planId,
  planVersionId,
  packageAlias,
}: {
  planId?: string;
  planVersionId?: string;
  packageAlias?: string;
}): string {
  const raw = `${planId || ''} ${planVersionId || ''} ${packageAlias || ''}`.toLowerCase();
  if (raw.includes('agency') || raw.includes('bulk')) return 'agency';
  if (raw.includes('pro') || raw.includes('basic')) return 'pro';
  if (raw.includes('starter') || raw.includes('free') || raw.includes('plan_free')) return 'starter';
  return '';
}

function formatLimit(value: number | null, formatter: (next: number) => string, fallback: string): string {
  return value !== null && value > 0 ? formatter(value) : fallback;
}

function PortalBillingContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, selectSite } = useSession();
  const { sites, selectedSiteId, selectedSite, isSwitchingSite, switchingSiteName, setSelectedSiteId } = usePortalSiteSelection({
    session,
    isAuthenticated,
    searchParams,
    selectSite,
  });
  const [billingSnapshots, setBillingSnapshots] = useState<PortalBillingSnapshot[]>([]);
  const [reconciliation, setReconciliation] = useState<PortalBillingReconciliation | null>(null);
  const [siteSummary, setSiteSummary] = useState<PortalSiteSummaryRecord | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [preferredCurrency, setPreferredCurrency] = useState<PortalCurrency>(DEFAULT_PORTAL_CURRENCY);
  const [packageRequests, setPackageRequests] = useState<PortalActionRequest[]>([]);
  const [topUpPacks, setTopUpPacks] = useState<PortalTopUpPack[]>([]);
  const [topUpRequests, setTopUpRequests] = useState<PortalActionRequest[]>([]);
  const [requestTarget, setRequestTarget] = useState<PortalPackageChangeRequestPayload['target_package']>('basic');
  const [requestReason, setRequestReason] = useState('');
  const [requestExpectedSites, setRequestExpectedSites] = useState('1');
  const [requestExpectedUsage, setRequestExpectedUsage] = useState('');
  const [selectedTopUpPackId, setSelectedTopUpPackId] = useState('');
  const [topUpExpectedUsage, setTopUpExpectedUsage] = useState('');
  const [topUpReason, setTopUpReason] = useState('');
  const [isSubmittingRequest, setIsSubmittingRequest] = useState(false);
  const [isSubmittingTopUpRequest, setIsSubmittingTopUpRequest] = useState(false);
  const [requestMessage, setRequestMessage] = useState<string | null>(null);
  const [topUpRequestMessage, setTopUpRequestMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [emptyReason, setEmptyReason] = useState<'no_subscription_coverage' | null>(null);

  const loadBillingBundle = useCallback(
    async (siteId: string, options: { allowFallback: boolean }): Promise<void> => {
      const loadSiteSummary = async (nextSiteId: string) => {
        const siteSummaryResponse = await portalClient.getSiteSummary(nextSiteId);
        setSiteSummary(siteSummaryResponse.data as PortalSiteSummaryRecord);
      };
      const loadEntitlements = async (nextSiteId: string) => {
        try {
          const entitlementsResponse = await portalClient.getEntitlements(nextSiteId);
          setEntitlements(entitlementsResponse.data);
        } catch {
          setEntitlements(null);
        }
      };
      const loadMemberPreferences = async () => {
        try {
          const preferencesResponse = await portalClient.getMemberPreferences();
          setPreferredCurrency(resolvePortalDisplayCurrency((preferencesResponse.data as PortalMemberPreferences).currency));
        } catch {
          setPreferredCurrency(DEFAULT_PORTAL_CURRENCY);
        }
      };
      const loadPackageRequests = async (nextSiteId: string) => {
        try {
          const response = await portalClient.listPackageChangeRequests(nextSiteId);
          setPackageRequests(response.data.items || []);
        } catch {
          setPackageRequests([]);
        }
      };
      const loadTopUpPacks = async () => {
        try {
          const response = await portalClient.listTopUpPacks();
          const items = [...(response.data.items || [])].sort(
            (a, b) => Number(a.display_order || 0) - Number(b.display_order || 0)
          );
          setTopUpPacks(items);
          setSelectedTopUpPackId((current) => current || items[0]?.pack_id || '');
        } catch {
          setTopUpPacks([]);
        }
      };
      const loadTopUpRequests = async (nextSiteId: string) => {
        try {
          const response = await portalClient.listTopUpPackRequests(nextSiteId);
          setTopUpRequests(response.data.items || []);
        } catch {
          setTopUpRequests([]);
        }
      };

      try {
        const [bundle] = await Promise.all([
          portalClient.getBillingBundle(siteId),
          loadSiteSummary(siteId),
          loadEntitlements(siteId),
          loadMemberPreferences(),
          loadPackageRequests(siteId),
          loadTopUpPacks(),
          loadTopUpRequests(siteId),
        ]);
        setBillingSnapshots(bundle.snapshots);
        setReconciliation(bundle.reconciliation);
        setEmptyReason(null);
        return;
      } catch (err) {
        if (
          err instanceof PortalApiError &&
          err.errorCode === 'service.subscription_not_found'
        ) {
          if (options.allowFallback) {
            for (const site of sites) {
              if (!site.site_id || site.site_id === siteId) {
                continue;
              }

              try {
                const [fallbackBundle] = await Promise.all([
                  portalClient.getBillingBundle(site.site_id),
                  loadSiteSummary(site.site_id),
                  loadEntitlements(site.site_id),
                  loadMemberPreferences(),
                  loadPackageRequests(site.site_id),
                  loadTopUpPacks(),
                  loadTopUpRequests(site.site_id),
                ]);
                setBillingSnapshots(fallbackBundle.snapshots);
                setReconciliation(fallbackBundle.reconciliation);
                await setSelectedSiteId(site.site_id);
                setEmptyReason(null);
                return;
              } catch (fallbackError) {
                if (
                  !(
                    fallbackError instanceof PortalApiError &&
                    fallbackError.errorCode === 'service.subscription_not_found'
                  )
                ) {
                  throw fallbackError;
                }
              }
            }
          }

          setBillingSnapshots([]);
          setPackageRequests([]);
          setTopUpRequests([]);
          setReconciliation(null);
          setEntitlements(null);
          await loadSiteSummary(siteId);
          setEmptyReason('no_subscription_coverage');
          return;
        }

        throw err;
      }
    },
    [setSelectedSiteId, sites]
  );

  useEffect(() => {
    const loadData = async () => {
      if (!session || !isAuthenticated || !selectedSiteId) {
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);
      setEmptyReason(null);

      try {
        await loadBillingBundle(selectedSiteId, {
          allowFallback: !searchParams?.get('site') && !session.site_id,
        });
      } catch (err) {
        setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
      } finally {
        setIsLoading(false);
      }
    };

    void loadData();
  }, [isAuthenticated, loadBillingBundle, searchParams, selectedSiteId, session, t]);

  useEffect(() => {
    if (!selectedSiteId || (!packageRequests.some((item) => item.status === 'open') && !topUpRequests.some((item) => item.status === 'open'))) {
      return;
    }
    const timer = window.setInterval(() => {
      void loadBillingBundle(selectedSiteId, { allowFallback: false }).catch(() => undefined);
    }, 20000);
    return () => window.clearInterval(timer);
  }, [loadBillingBundle, packageRequests, selectedSiteId, topUpRequests]);

  const handleSiteChange = async (siteId: string) => {
    await setSelectedSiteId(siteId);
    setIsLoading(true);
    setError(null);
    setEmptyReason(null);

    try {
      await loadBillingBundle(siteId, { allowFallback: false });
    } catch (err) {
      setError(formatPortalErrorMessage(err, t, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  };

  const handlePackageRequestSubmit = async () => {
    if (!selectedSiteId) {
      return;
    }
    if (packageRequests.some((item) => item.status === 'open' || item.status === 'acknowledged')) {
      setRequestMessage(t('portal.billing.pending_package_request_notice', {}, '已有套餐申请正在处理中，处理完成前不能重复提交。'));
      return;
    }
    setIsSubmittingRequest(true);
    setError(null);
    setRequestMessage(null);
    try {
      const response = await portalClient.createPackageChangeRequest(selectedSiteId, {
        target_package: requestTarget,
        reason: requestReason.trim(),
        expected_sites: Math.max(1, Number.parseInt(requestExpectedSites, 10) || 1),
        expected_usage: requestExpectedUsage.trim(),
      });
      setPackageRequests((current) => {
        const existing = current.filter((item) => item.request_id !== response.data.request_id);
        return [response.data, ...existing];
      });
      setRequestMessage(t('portal.billing.request_submitted', {}, '套餐申请已提交，处理状态会显示在待办和本页记录里。'));
    } catch (err) {
      setRequestMessage(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setIsSubmittingRequest(false);
    }
  };

  const handleTopUpRequestSubmit = async () => {
    if (!selectedSiteId || !selectedTopUpPackId) {
      return;
    }
    if (topUpRequests.some((item) => item.status === 'open' || item.status === 'acknowledged')) {
      setTopUpRequestMessage(t('portal.billing.pending_topup_request_notice', {}, '已有加量申请正在处理中，处理完成前不能重复提交。'));
      return;
    }
    setIsSubmittingTopUpRequest(true);
    setError(null);
    setTopUpRequestMessage(null);
    try {
      const response = await portalClient.createTopUpPackRequest(selectedSiteId, {
        pack_id: selectedTopUpPackId,
        reason: topUpReason.trim(),
        expected_usage: topUpExpectedUsage.trim(),
      });
      setTopUpRequests((current) => {
        const existing = current.filter((item) => item.request_id !== response.data.request_id);
        return [response.data, ...existing];
      });
      setTopUpRequestMessage(t('portal.billing.topup_request_submitted', {}, '加量包申请已提交，处理状态会显示在待办和本页记录里。'));
    } catch (err) {
      setTopUpRequestMessage(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setIsSubmittingTopUpRequest(false);
    }
  };

  if (sessionLoading || isLoading) {
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

  if (error) {
    return (
      <PortalErrorState
        title={t('common.error')}
        description={error}
        retryLabel={t('common.retry')}
        onRetry={() => void handleSiteChange(selectedSiteId)}
      />
    );
  }

  const latestSnapshot = billingSnapshots[0] || null;
  const snapshotPlanVersionId =
    latestSnapshot?.plan_version_id || reconciliation?.snapshot?.plan_version_id || '';
  const siteCoverage = siteSummary?.coverage || null;
  const entitlementSnapshot = entitlements?.entitlement_snapshot || siteSummary?.entitlement_snapshot || null;
  const planVersion = entitlements?.plan_version || null;
  const entitlementBudgets = entitlementSnapshot?.budgets || {};
  const planBudgets = planVersion?.budgets || {};
  const currentRunsLimit = coerceFiniteNumber(
    planBudgets.max_runs_per_period ||
      entitlementBudgets.max_runs_per_period ||
      entitlementSnapshot?.requests_limit
  );
  const currentTokensLimit = coerceFiniteNumber(
    planBudgets.max_tokens_per_period ||
      entitlementBudgets.max_tokens_per_period ||
      entitlementSnapshot?.tokens_limit
  );
  const currentCostLimit = coerceFiniteNumber(
    planBudgets.max_cost_per_period ||
      entitlementBudgets.max_cost_per_period
  );
  const currentFeatureList = Array.from(new Set([
    ...((entitlementSnapshot?.features || []) as string[]),
    ...flattenEntitlements(entitlementSnapshot?.entitlements),
  ])).filter(Boolean);
  const snapshotCost = coerceFiniteNumber(reconciliation?.snapshot?.totals?.cost);
  const latestSnapshotCost = coerceFiniteNumber(latestSnapshot?.totals?.cost);
  const deltaCost = coerceFiniteNumber(reconciliation?.reconciliation?.deltas?.cost) || 0;
  const reconciledAt = reconciliation?.snapshot?.generated_at || '';
  const formatPreferredCurrency = (
    value: number,
    sourceCurrency: PortalCurrency = 'USD'
  ): string => formatPortalCurrency(value, { from: sourceCurrency, to: preferredCurrency });
  const packageDisplay = resolveCustomerPackageDisplay(t, {
    planId: siteCoverage?.plan_id || session.current_subscription?.plan_id,
    planVersionId: snapshotPlanVersionId || siteCoverage?.plan_version_id || session.current_subscription?.plan_version_id,
    packageAlias: siteCoverage?.package_alias || session.current_subscription?.package_alias,
    formalPlanName: selectedSite?.plan_name,
    planKind: session.current_subscription?.plan_kind,
    coverageState: siteCoverage || session.current_subscription ? 'covered' : 'uncovered',
  });
  const currentPlanLabel = packageDisplay.display_package_label || t('common.not_found');
  const currentTierId = inferTierId({
    planId: siteCoverage?.plan_id || session.current_subscription?.plan_id,
    planVersionId: siteCoverage?.plan_version_id || snapshotPlanVersionId || session.current_subscription?.plan_version_id,
    packageAlias: siteCoverage?.package_alias || session.current_subscription?.package_alias || currentPlanLabel,
  });
  const selectedTierId =
    requestTarget === 'bulk' ? 'agency' : requestTarget === 'free' ? 'starter' : 'pro';
  const currentCatalogTier = PACKAGE_TIER_CATALOG.find((tier) => tier.tierId === currentTierId) || null;
  const selectedTopUpPack = topUpPacks.find((pack) => pack.pack_id === selectedTopUpPackId) || topUpPacks[0] || null;
  const hasPendingPackageRequest = packageRequests.some((item) => item.status === 'open' || item.status === 'acknowledged');
  const hasPendingTopUpRequest = topUpRequests.some((item) => item.status === 'open' || item.status === 'acknowledged');
  const currentRunsUsed = coerceFiniteNumber(entitlements?.usage_totals?.runs ?? entitlements?.usage_totals?.requests) || 0;
  const currentTokensUsed = coerceFiniteNumber(entitlements?.usage_totals?.tokens ?? entitlements?.usage_totals?.tokens_total) || 0;
  const currentCostUsed = coerceFiniteNumber(entitlements?.usage_totals?.cost) || 0;
  const remainingRuns = currentRunsLimit !== null ? Math.max(currentRunsLimit - currentRunsUsed, 0) : null;
  const remainingTokens = currentTokensLimit !== null ? Math.max(currentTokensLimit - currentTokensUsed, 0) : null;
  const remainingCost = currentCostLimit !== null ? Math.max(currentCostLimit - currentCostUsed, 0) : null;
  const currentPeriodLabel = latestSnapshot
    ? `${formatDate(latestSnapshot.period_start_at)} - ${formatDate(latestSnapshot.period_end_at)}`
    : siteCoverage?.current_period_start_at && siteCoverage?.current_period_end_at
      ? `${formatDate(siteCoverage.current_period_start_at)} - ${formatDate(siteCoverage.current_period_end_at)}`
      : siteCoverage?.current_period_start && siteCoverage?.current_period_end
      ? `${formatDate(siteCoverage.current_period_start)} - ${formatDate(siteCoverage.current_period_end)}`
      : session.current_subscription?.current_period_start && session.current_subscription?.current_period_end
      ? `${formatDate(session.current_subscription.current_period_start)} - ${formatDate(session.current_subscription.current_period_end)}`
      : t('common.not_found');
  const hasCoveredPackage = Boolean(siteCoverage || session.current_subscription);
  const latestSnapshotTotalLabel =
    latestSnapshotCost !== null
      ? formatPreferredCurrency(latestSnapshotCost, normalizePortalCurrency(latestSnapshot?.currency || 'USD'))
      : snapshotCost !== null
        ? formatPreferredCurrency(snapshotCost, normalizePortalCurrency(reconciliation?.snapshot?.currency || 'USD'))
        : hasCoveredPackage
          ? formatPreferredCurrency(
              0,
              normalizePortalCurrency(latestSnapshot?.currency || reconciliation?.snapshot?.currency || 'USD')
            )
          : '--';
  const latestSnapshotTotalDetail = reconciledAt
    ? `${t('portal.updated_at', {}, 'Updated')}: ${formatDate(reconciledAt)}`
    : hasCoveredPackage
      ? t(
          'portal.billing.current_period_total_empty_detail',
          {},
          'No site billing record has been generated for this period yet.'
        )
      : undefined;
  const billingStatusLabel = emptyReason === 'no_subscription_coverage'
    ? t('common.not_found')
    : reconciliation
    ? deltaCost === 0
      ? t('status.active')
      : t('status.warning')
    : t('common.not_found');
  const coverageTitle =
    emptyReason === 'no_subscription_coverage'
      ? t('portal.billing.uncovered_title', {}, 'Current package is uncovered')
      : deltaCost !== 0
        ? t('portal.billing.coverage_attention_title', {}, 'Package coverage needs review')
        : t('portal.billing.covered_title', {}, 'Current package is covered');
  const coverageDetail =
    emptyReason === 'no_subscription_coverage'
      ? t(
          'portal.billing.no_subscription_notice',
          {},
          'This site is not currently covered by an active customer package. This is an uncovered state, not a Free package.'
        )
      : deltaCost !== 0
        ? t(
            'portal.billing.coverage_attention_desc',
            { delta: formatPreferredCurrency(deltaCost) },
            `The latest package record differs by ${formatPreferredCurrency(deltaCost)}. If this looks wrong, contact your operator.`
          )
        : t(
            'portal.billing.covered_desc',
            {},
            'This site is currently covered by the package shown here.'
          );
  const shouldShowCoverageCard = emptyReason === 'no_subscription_coverage' || deltaCost !== 0;
  const formatDelta = (nextValue: number, currentValue: number | null, formatter: (value: number) => string): string | null => {
    if (!currentValue || currentValue === nextValue) {
      return null;
    }
    const delta = nextValue - currentValue;
    return `${delta > 0 ? '+' : ''}${formatter(delta)}`;
  };
  return (
    <BackofficePageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.nav_package', {}, 'Package')}
        title={t('portal.nav_package', {}, 'Package')}
        eyebrowInfo={t(
          'portal.billing.desc',
          {},
          'See which package this site is currently using and the coverage period for this site.'
        )}
        currentPage="billing"
        selectedSiteId={selectedSiteId}
        selectedSiteName={selectedSite?.site_name}
        sites={sites}
        onSiteChange={handleSiteChange}
        metrics={[
          { label: t('portal.current_subscription_label', {}, 'Current package'), value: currentPlanLabel },
          { label: t('portal.billing.current_period'), value: currentPeriodLabel, size: 'compact' },
          {
            label: t('common.status'),
            value: billingStatusLabel,
            toneClassName: deltaCost === 0 ? 'text-green-600 dark:text-green-400' : 'text-yellow-600 dark:text-yellow-400',
          },
          {
            label: t('portal.billing.current_period_total', {}, 'This period'),
            value: latestSnapshotTotalLabel,
            detail: latestSnapshotTotalDetail,
          },
        ]}
        metricsColumnsClassName="lg:grid-cols-4"
      >
        {shouldShowCoverageCard ? (
          <BackofficeStackCard className="bg-white/80 dark:bg-slate-950/55">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <p className="text-xs uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
                  {t('portal.billing.coverage_label', {}, 'Coverage')}
                </p>
                <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">{coverageTitle}</h2>
                <div className="mt-3 flex flex-wrap gap-2">
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] ${
                    emptyReason === 'no_subscription_coverage'
                      ? 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300'
                      : deltaCost !== 0
                        ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
                        : 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300'
                  }`}>
                    {emptyReason === 'no_subscription_coverage'
                      ? t('portal.billing.coverage_outcome_uncovered', {}, 'Uncovered')
                      : deltaCost !== 0
                        ? t('portal.billing.coverage_outcome_review', {}, 'Needs review')
                        : t('portal.billing.coverage_outcome_covered', {}, 'Covered')}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-6 text-gray-600 dark:text-gray-300">{coverageDetail}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Link href={`/portal/usage?site=${selectedSiteId}`} className="btn btn-secondary btn-sm">
                  {t('usage.title', {}, 'Open Usage')}
                </Link>
                <Link href={`/portal/sites/${selectedSiteId}`} className="btn btn-secondary btn-sm">
                  {t('portal.site_record', {}, 'Open site record')}
                </Link>
              </div>
            </div>
          </BackofficeStackCard>
        ) : null}
      </PortalWorkspaceHeader>

      {isSwitchingSite ? (
        <PortalSiteSwitchingNotice
          message={t(
            'portal.site_switching_notice_with_target',
            { site: switchingSiteName || selectedSite?.site_name || selectedSiteId },
            `正在切换到 ${switchingSiteName || selectedSite?.site_name || selectedSiteId}，页面数据会自动更新。`
          )}
        />
      ) : null}

      <section className="rounded-[1.4rem] border border-slate-200/80 bg-white/90 px-6 py-5 dark:border-slate-800 dark:bg-slate-950/30">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
            {t('portal.billing.entitlements_label', {}, 'Entitlements')}
          </p>
          <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
            {t('portal.billing.current_entitlements_title', {}, 'Current package permissions')}
          </h2>
        </div>
        <div className="mt-5">
          <BackofficeMetricStrip
            items={[
              {
                label: t('usage.requests_month', {}, 'Requests/month'),
                value: formatLimit(currentRunsLimit, formatNumber, t('common.not_found')),
                detail: t('portal.usage.request_ceiling_desc', {}, 'Current request ceiling in the active plan version.'),
              },
              {
                label: t('usage.tokens_month', {}, 'Tokens/month'),
                value: formatLimit(currentTokensLimit, formatCompactNumber, t('common.not_found')),
                detail: t('portal.usage.token_ceiling_desc', {}, 'Current token ceiling in the active plan version.'),
              },
              {
                label: t('common.cost'),
                value: formatLimit(currentCostLimit, formatPreferredCurrency, t('common.not_found')),
                detail: t('portal.usage.cost_ceiling_desc', {}, 'Estimated provider cost budget for the current package period.'),
              },
              {
                label: t('usage.features', {}, 'Features'),
                value: currentFeatureList.length ? formatNumber(currentFeatureList.length) : t('common.not_found'),
                detail: t('portal.usage.feature_list_desc', {}, 'Features currently exposed by the active entitlement snapshot.'),
              },
            ]}
            columnsClassName="lg:grid-cols-4"
          />
        </div>
        <div className="mt-5 flex flex-wrap gap-2">
          {currentFeatureList.length > 0 ? (
            currentFeatureList.map((feature) => (
              <BackofficeTag key={feature} tone="info">{feature}</BackofficeTag>
            ))
          ) : (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {t('portal.billing.no_feature_detail', {}, 'No feature list is attached to the current entitlement snapshot yet.')}
            </p>
          )}
        </div>
      </section>

      <section className="rounded-[1.4rem] border border-slate-200/80 bg-white/90 px-6 py-5 dark:border-slate-800 dark:bg-slate-950/30">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.billing.package_options_label', {}, 'Package options')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.billing.package_options_title', {}, '选择目标套餐并提交申请')}
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
              {t(
                'portal.billing.package_options_desc',
                {},
                '用户管理员只能提交套餐变更申请，不能直接切换订阅、价格或权益。申请会保留在待办和审计里。'
              )}
            </p>
            <p className="mt-2 max-w-3xl text-xs leading-5 text-gray-500 dark:text-gray-400">
              {t(
                'portal.billing.currency_note',
                {},
                '当前测试阶段统一按人民币展示金额；语言切换不会改变币种。'
              )}
            </p>
          </div>
          <BackofficeTag tone="warning">
            {t('portal.billing.operator_managed_change', {}, 'Operator-managed change')}
          </BackofficeTag>
        </div>
        <div className="mt-5 grid gap-4 lg:grid-cols-3">
          {PACKAGE_TIER_CATALOG.map((tier) => {
            const isCurrent = currentTierId === tier.tierId;
            const isSelected = selectedTierId === tier.tierId;
            const targetValue =
              tier.tierId === 'agency' ? 'bulk' : tier.tierId === 'starter' ? 'free' : 'basic';
            const deltas = [
              formatDelta(tier.runs, currentCatalogTier?.runs ?? currentRunsLimit, formatNumber),
              formatDelta(tier.tokens, currentCatalogTier?.tokens ?? currentTokensLimit, formatCompactNumber),
              formatDelta(tier.sites, currentCatalogTier?.sites ?? null, formatNumber),
              formatDelta(tier.cost, currentCatalogTier?.cost ?? currentCostLimit, (value) => formatPreferredCurrency(value)),
            ].filter(Boolean);
            return (
              <BackofficeStackCard
                key={tier.tierId}
                className={[
                  'relative transition cursor-pointer select-none',
                  isCurrent
                    ? 'border-blue-300 bg-blue-50/70 dark:border-blue-800 dark:bg-blue-950/20'
                    : isSelected
                      ? 'border-slate-900 bg-slate-100/90 shadow-[0_0_0_1px_rgba(15,23,42,0.06)] dark:border-slate-200 dark:bg-slate-900/70'
                      : 'bg-white/80 hover:border-slate-300 hover:bg-slate-100/70 dark:bg-slate-950/45 dark:hover:border-slate-700 dark:hover:bg-slate-900/60',
                ].join(' ')}
                role="button"
                tabIndex={0}
                aria-pressed={isSelected}
                onClick={() => setRequestTarget(targetValue as PortalPackageChangeRequestPayload['target_package'])}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    setRequestTarget(targetValue as PortalPackageChangeRequestPayload['target_package']);
                  }
                }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="text-lg font-semibold text-gray-950 dark:text-white">
                      {localizePackageAlias(t, tier.tierId, tier.fallbackAlias)}
                    </h3>
                    <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-300">
                      {localizeUsageBand(t, tier.tierId)}
                    </p>
                  </div>
                  {isCurrent ? (
                    <BackofficeTag tone="accent">{t('common.current', {}, 'Current')}</BackofficeTag>
                  ) : isSelected ? (
                    <BackofficeTag>{t('portal.billing.selected_target_package', {}, '已选中')}</BackofficeTag>
                  ) : null}
                </div>
                <dl className="mt-4 grid gap-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-gray-500 dark:text-gray-400">{t('usage.requests_month', {}, 'Requests/month')}</dt>
                    <dd className="font-semibold text-gray-950 dark:text-white">{formatNumber(tier.runs)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-gray-500 dark:text-gray-400">{t('usage.tokens_month', {}, 'Tokens/month')}</dt>
                    <dd className="font-semibold text-gray-950 dark:text-white">{formatCompactNumber(tier.tokens)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-gray-500 dark:text-gray-400">{t('common.cost')}</dt>
                    <dd className="font-semibold text-gray-950 dark:text-white">{formatPreferredCurrency(tier.cost)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-gray-500 dark:text-gray-400">{t('portal.billing.site_limit_label', {}, 'Sites')}</dt>
                    <dd className="font-semibold text-gray-950 dark:text-white">{formatNumber(tier.sites)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-gray-500 dark:text-gray-400">{t('portal.billing.concurrency_label', {}, 'Active runs')}</dt>
                    <dd className="font-semibold text-gray-950 dark:text-white">{formatNumber(tier.concurrency)}</dd>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <dt className="text-gray-500 dark:text-gray-400">{t('portal.billing.batch_label', {}, 'Batch size')}</dt>
                    <dd className="font-semibold text-gray-950 dark:text-white">{formatNumber(tier.batch)}</dd>
                  </div>
                </dl>
                <div className="mt-4 flex flex-wrap gap-2">
                  {tier.featureKeys.map((featureKey) => (
                    <BackofficeTag key={featureKey}>{t(featureKey, {}, featureKey)}</BackofficeTag>
                  ))}
                </div>
                {deltas.length ? (
                  <p className="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                    {t('portal.billing.package_delta_label', {}, 'Compared with current package')}: {deltas.join(' / ')}
                  </p>
                ) : null}
              </BackofficeStackCard>
            );
          })}
        </div>
        <div className="mt-5 rounded-[1.1rem] border border-slate-200/80 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/45">
          <div className="grid gap-4 lg:grid-cols-[0.8fr_0.6fr_1fr_auto] lg:items-end">
            <div className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <span>{t('portal.billing.target_package', {}, '目标套餐')}</span>
              <div className="input flex min-h-11 items-center bg-white/90 dark:bg-slate-950/60">
                {localizePackageAlias(
                  t,
                  selectedTierId,
                  requestTarget === 'free' ? 'Free' : requestTarget === 'bulk' ? 'Bulk' : 'Basic'
                )}
              </div>
            </div>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <span>{t('portal.billing.expected_sites', {}, '预计站点数')}</span>
              <input className="input w-full" type="number" min="1" value={requestExpectedSites} onChange={(event) => setRequestExpectedSites(event.target.value)} />
            </label>
            <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
              <span>{t('portal.billing.expected_usage', {}, '预计用量 / 原因')}</span>
              <input
                className="input w-full"
                value={requestExpectedUsage}
                onChange={(event) => setRequestExpectedUsage(event.target.value)}
                placeholder={t('portal.billing.expected_usage_placeholder', {}, '例如：本月预计 3 个站点，需要更高请求额度')}
              />
            </label>
            <button
              type="button"
              className="btn btn-primary"
              disabled={isSubmittingRequest || hasPendingPackageRequest}
              onClick={() => void handlePackageRequestSubmit()}
            >
              {isSubmittingRequest ? t('common.saving') : t('portal.billing.submit_request', {}, '提交申请')}
            </button>
          </div>
          <label className="mt-4 block space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
            <span>{t('portal.billing.request_reason', {}, '补充说明')}</span>
            <textarea
              className="input min-h-24 w-full resize-y"
              value={requestReason}
              onChange={(event) => setRequestReason(event.target.value)}
              placeholder={t('portal.billing.request_reason_placeholder', {}, '说明为什么需要调整套餐，便于运营判断。')}
            />
          </label>
          {requestMessage ? <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{requestMessage}</p> : null}
          {hasPendingPackageRequest ? (
            <p className="mt-3 text-sm text-amber-700 dark:text-amber-300">
              {t('portal.billing.pending_package_request_notice', {}, '已有套餐申请正在处理中，处理完成前不能重复提交。')}
            </p>
          ) : null}
        </div>
        {packageRequests.length ? (
          <div className="mt-5">
            <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
              {t('portal.billing.recent_requests', {}, '最近申请')}
            </h3>
            <div className="mt-3 grid gap-3">
              {packageRequests.slice(0, 5).map((item) => (
                <div key={item.request_id} className="rounded-2xl border border-slate-200/80 bg-white/80 px-4 py-3 text-sm dark:border-slate-800 dark:bg-slate-950/45">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="font-semibold text-slate-950 dark:text-white">{item.title}</span>
                    <BackofficeStatusBadge
                      label={formatPortalActionRequestStatusLabel(t, item.status)}
                      status={item.status}
                    />
                  </div>
                  <PortalActionRequestResultStrip item={item} />
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{formatDate(item.created_at)}</p>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      <section className="rounded-[1.4rem] border border-slate-200/80 bg-white/90 px-6 py-5 dark:border-slate-800 dark:bg-slate-950/30">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500 dark:text-gray-400">
              {t('portal.billing.topup_options_label', {}, 'Top-up packs')}
            </p>
            <h2 className="mt-2 text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.billing.topup_options_title', {}, '选择加量包并提交申请')}
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-gray-600 dark:text-gray-300">
              {t(
                'portal.billing.topup_options_desc',
                {},
                '加量包只用于当前套餐周期的临时余量补充。用户管理员只能提交申请，是否应用仍由平台管理员处理。'
              )}
            </p>
            <p className="mt-2 max-w-3xl text-xs leading-5 text-gray-500 dark:text-gray-400">
              {t(
                'portal.billing.currency_note',
                {},
                '当前测试阶段统一按人民币展示金额；语言切换不会改变币种。'
              )}
            </p>
          </div>
          <BackofficeTag tone="warning">
            {t('portal.billing.operator_managed_change', {}, 'Operator-managed change')}
          </BackofficeTag>
        </div>

        {topUpPacks.length ? (
          <>
            <div className="mt-5">
              <BackofficeMetricStrip
                items={[
                  {
                    label: t('portal.billing.remaining_runs', {}, '剩余请求'),
                    value: remainingRuns !== null ? formatNumber(remainingRuns) : t('common.not_found'),
                    detail: `${formatNumber(currentRunsUsed)} / ${currentRunsLimit !== null ? formatNumber(currentRunsLimit) : t('common.not_found')}`,
                  },
                  {
                    label: t('portal.billing.remaining_tokens', {}, '剩余 Token'),
                    value: remainingTokens !== null ? formatCompactNumber(remainingTokens) : t('common.not_found'),
                    detail: `${formatCompactNumber(currentTokensUsed)} / ${currentTokensLimit !== null ? formatCompactNumber(currentTokensLimit) : t('common.not_found')}`,
                  },
                  {
                    label: t('portal.billing.remaining_cost', {}, '剩余预算'),
                    value: remainingCost !== null ? formatPreferredCurrency(remainingCost) : t('common.not_found'),
                    detail: `${formatPreferredCurrency(currentCostUsed)} / ${currentCostLimit !== null ? formatPreferredCurrency(currentCostLimit) : t('common.not_found')}`,
                  },
                ]}
                columnsClassName="lg:grid-cols-3"
              />
            </div>
            <div className="mt-5 grid gap-4 lg:grid-cols-3">
              {topUpPacks.map((pack) => {
                const isSelected = selectedTopUpPackId === pack.pack_id;
                const recommendedTiers = (pack.recommended_for_tiers || []).map((tier) => localizeTopUpTierLabel(t, tier)).join(' / ');
                return (
                  <BackofficeStackCard
                    key={pack.pack_id}
                    className={[
                      'relative transition cursor-pointer select-none',
                      isSelected
                        ? 'border-slate-900 bg-slate-100/90 shadow-[0_0_0_1px_rgba(15,23,42,0.06)] dark:border-slate-200 dark:bg-slate-900/70'
                        : 'bg-white/80 hover:border-slate-300 hover:bg-slate-100/70 dark:bg-slate-950/45 dark:hover:border-slate-700 dark:hover:bg-slate-900/60',
                    ].join(' ')}
                    role="button"
                    tabIndex={0}
                    aria-pressed={isSelected}
                    onClick={() => setSelectedTopUpPackId(pack.pack_id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setSelectedTopUpPackId(pack.pack_id);
                      }
                    }}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <h3 className="text-lg font-semibold text-gray-950 dark:text-white">
                          {localizeTopUpPackLabel(t, pack.pack_id, pack.label)}
                        </h3>
                        <p className="mt-1 text-sm leading-6 text-gray-600 dark:text-gray-300">
                          {localizeTopUpPackPointsLabel(t, pack.pack_id, pack.points_label)}
                        </p>
                      </div>
                      {isSelected ? <BackofficeTag tone="accent">{t('portal.billing.selected_target_package', {}, 'Selected')}</BackofficeTag> : null}
                    </div>
                    <dl className="mt-4 grid gap-3 text-sm">
                      <div className="flex items-center justify-between gap-3">
                        <dt className="text-gray-500 dark:text-gray-400">{t('billing.runs', {}, 'Runs')}</dt>
                        <dd className="font-semibold text-gray-950 dark:text-white">+{formatNumber(Number(pack.runs_increment || 0))}</dd>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <dt className="text-gray-500 dark:text-gray-400">{t('common.tokens')}</dt>
                        <dd className="font-semibold text-gray-950 dark:text-white">+{formatCompactNumber(Number(pack.tokens_increment || 0))}</dd>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <dt className="text-gray-500 dark:text-gray-400">{t('common.cost')}</dt>
                        <dd className="font-semibold text-gray-950 dark:text-white">
                          {formatPortalCurrency(Number(pack.cost_increment || 0), { from: 'CNY', to: preferredCurrency })}
                        </dd>
                      </div>
                    </dl>
                    {recommendedTiers ? (
                      <p className="mt-4 text-xs leading-5 text-gray-500 dark:text-gray-400">
                        {t('portal.billing.topup_recommended_for', { tiers: recommendedTiers }, `Recommended for ${recommendedTiers}`)}
                      </p>
                    ) : null}
                  </BackofficeStackCard>
                );
              })}
            </div>

            <div className="mt-5 rounded-[1.1rem] border border-slate-200/80 bg-slate-50/70 p-4 dark:border-slate-800 dark:bg-slate-950/45">
              <div className="grid gap-4 lg:grid-cols-[0.8fr_1fr_auto] lg:items-end">
                <div className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  <span>{t('portal.billing.target_topup_pack', {}, '目标加量包')}</span>
                  <div className="input flex min-h-11 items-center bg-white/90 dark:bg-slate-950/60">
                    {selectedTopUpPack
                      ? localizeTopUpPackLabel(t, selectedTopUpPack.pack_id, selectedTopUpPack.label)
                      : t('common.not_found')}
                  </div>
                </div>
                <label className="space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                  <span>{t('portal.billing.expected_usage', {}, '预计用量 / 原因')}</span>
                  <input
                    className="input w-full"
                    value={topUpExpectedUsage}
                    onChange={(event) => setTopUpExpectedUsage(event.target.value)}
                    placeholder={t('portal.billing.topup_expected_usage_placeholder', {}, '例如：本周活动流量临时升高，需要补足当前周期余量')}
                  />
                </label>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={isSubmittingTopUpRequest || !selectedTopUpPack || hasPendingTopUpRequest}
                  onClick={() => void handleTopUpRequestSubmit()}
                >
                  {isSubmittingTopUpRequest ? t('common.saving') : t('portal.billing.submit_topup_request', {}, '提交加量申请')}
                </button>
              </div>
              <label className="mt-4 block space-y-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                <span>{t('portal.billing.request_reason', {}, '补充说明')}</span>
                <textarea
                  className="input min-h-24 w-full resize-y"
                  value={topUpReason}
                  onChange={(event) => setTopUpReason(event.target.value)}
                  placeholder={t('portal.billing.topup_reason_placeholder', {}, '说明为什么需要加量，便于运营判断是否加量或建议改套餐。')}
                />
              </label>
              {topUpRequestMessage ? <p className="mt-3 text-sm text-slate-600 dark:text-slate-300">{topUpRequestMessage}</p> : null}
              {hasPendingTopUpRequest ? (
                <p className="mt-3 text-sm text-amber-700 dark:text-amber-300">
                  {t('portal.billing.pending_topup_request_notice', {}, '已有加量申请正在处理中，处理完成前不能重复提交。')}
                </p>
              ) : null}
            </div>
          </>
        ) : (
          <PortalEmptyState
            title={t('portal.billing.topup_empty_title', {}, '暂无可申请的加量包')}
            description={t('portal.billing.topup_empty_desc', {}, '平台管理员还没有启用加量包目录。需要临时余量时，请先提交套餐申请或联系运营。')}
            diagnosticCode="portal.billing.topup.catalog.empty"
          />
        )}

        {topUpRequests.length ? (
          <div className="mt-5">
            <h3 className="text-sm font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
              {t('portal.billing.recent_topup_requests', {}, '最近加量申请')}
            </h3>
            <div className="mt-3 grid gap-3">
              {topUpRequests.slice(0, 5).map((item) => (
                <div key={item.request_id} className="rounded-2xl border border-slate-200/80 bg-white/80 px-4 py-3 text-sm dark:border-slate-800 dark:bg-slate-950/45">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="font-semibold text-slate-950 dark:text-white">{item.title}</span>
                    <BackofficeStatusBadge
                      label={formatPortalActionRequestStatusLabel(t, item.status)}
                      status={item.status}
                    />
                  </div>
                  <PortalActionRequestResultStrip item={item} />
                  <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">{formatDate(item.created_at)}</p>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      <details className="overflow-hidden rounded-[1.4rem] border border-slate-200/80 bg-white/90 dark:border-slate-800 dark:bg-slate-950/30">
        <summary className="flex cursor-pointer list-none items-start justify-between gap-4 px-6 py-5">
          <div className="min-w-0">
            <h2 className="text-xl font-semibold text-gray-950 dark:text-white">
              {t('portal.billing.records_title', {}, 'Recent package records')}
            </h2>
          </div>
          <span className="rounded-full border border-slate-200/80 bg-slate-50/85 px-3 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-300">
            {billingSnapshots.length > 0
              ? t('portal.billing.records_count', { count: String(billingSnapshots.length) }, `${billingSnapshots.length} records`)
              : t('portal.billing.records_empty', {}, 'No records')}
          </span>
        </summary>

        <div className="border-t border-gray-200 dark:border-gray-800">
          {billingSnapshots.length === 0 ? (
            <div className="p-6">
              <PortalEmptyState
                title={
                  emptyReason === 'no_subscription_coverage'
                    ? t('portal.billing.uncovered_title', {}, 'Current package is uncovered')
                    : t('portal.billing.empty_title', {}, 'No package records yet')
                }
                description={
                  emptyReason === 'no_subscription_coverage'
                    ? t(
                        'portal.billing.no_subscription_notice',
                        {},
                        'This site is not currently covered by an active customer package. Open another connected site or return to the workspace before reviewing package detail.'
                      )
                    : t(
                        'portal.billing.empty_desc',
                        {},
                        'This site does not have a package record yet. Return to the workspace or open Usage if you only need the current activity view.'
                      )
                }
                actionLabel={t('portal.workspace_label', {}, 'Workspace')}
                actionHref="/portal"
              />
            </div>
          ) : (
            <div className="divide-y divide-gray-200 dark:divide-gray-800">
              {billingSnapshots.map((snapshot) => (
                <article key={snapshot.snapshot_id} className="px-6 py-5">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-lg font-medium text-gray-950 dark:text-white">
                        {t('portal.billing.record_title', {}, 'Package record')}
                      </h3>
                      <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                        {t('portal.billing.current_period', {}, 'Current period')}: {formatDate(snapshot.period_start_at)} - {formatDate(snapshot.period_end_at)}
                      </p>
                    </div>
                    <span className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
                      {preferredCurrency}
                    </span>
                  </div>
                  {snapshot.totals ? (
                    <div className="mt-4">
                      <BackofficeMetricStrip
                        items={[
                          {
                            label: t('portal.billing.current_site_total', {}, 'Cost this period'),
                            value:
                              coerceFiniteNumber(snapshot.totals.cost) !== null
                                ? formatPreferredCurrency(
                                    coerceFiniteNumber(snapshot.totals.cost) || 0,
                                    normalizePortalCurrency(snapshot.currency || 'USD')
                                  )
                                : '--',
                          },
                          { label: t('billing.runs', {}, 'Runs'), value: formatNumber(Number(snapshot.totals.runs || 0)) },
                          { label: t('portal.billing.requests', {}, 'Requests'), value: formatNumber(Number(snapshot.totals.provider_calls || 0)) },
                          { label: t('common.tokens'), value: formatCompactNumber(Number(snapshot.totals.tokens_total || 0)) },
                        ]}
                      />
                    </div>
                  ) : null}
                  <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-gray-500">
                    <span>{t('common.created')} {formatDate(snapshot.generated_at)}</span>
                    <details>
                      <summary className="cursor-pointer">{t('common.view_details', {}, 'View details')}</summary>
                      <div className="mt-2 space-y-2">
                        <BackofficeIdentifier value={snapshot.snapshot_id} />
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {t(
                            'portal.billing.record_detail_hint',
                            {},
                            'Use this historical record only when you need to inspect an older package window for this site.'
                          )}
                        </p>
                      </div>
                    </details>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </details>
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
