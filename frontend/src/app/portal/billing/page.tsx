'use client';

import React, { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  PortalMetricStrip,
  PortalPageStack,
  PortalCard,
} from '@/components/portal/PortalScaffold';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import { PortalEntitlementUsage } from '@/components/portal/PortalEntitlementUsage';
import { PortalCreditPackDialog } from '@/components/portal/PortalCreditPackDialog';
import {
  PortalPackageChangePanel,
  type PortalPackageTier,
} from '@/components/portal/PortalPackageChangePanel';
import {
  isPortalPaymentOrderPending,
  PortalPaymentOrderHistory,
} from '@/components/portal/PortalPaymentOrderHistory';
import { PortalPaymentReturnNotice } from '@/components/portal/PortalPaymentReturnNotice';
import { PortalTrialEligibilityPanel } from '@/components/portal/PortalTrialEligibilityPanel';
import {
  PortalErrorState,
  PortalLoadingState,
  PortalSignedOutState,
} from '@/components/portal/PortalPageState';
import { PortalWorkspaceHeader } from '@/components/portal/PortalWorkspaceHeader';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { Modal } from '@/components/ui/Modal';
import { useLocale } from '@/contexts/LocaleContext';
import { usePortalCommercialCatalog } from '@/hooks/usePortalCommercialCatalog';
import { usePortalPaymentOrders } from '@/hooks/usePortalPaymentOrders';
import { useSession } from '@/hooks/useSession';
import {
  portalClient,
  type Entitlements,
  type PortalPlanOffer,
} from '@/lib/portal-client';
import { resolveCustomerPackageDisplay } from '@/lib/customer-package-display';
import { formatPortalErrorMessage } from '@/lib/portal-error';
import { formatDate, formatNumber } from '@/lib/utils';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;
type QuotaSummary = NonNullable<Entitlements['quota_summary']>;

type PaymentLaunchState = {
  checkoutUrl: string;
  opened: boolean;
};

function preparePaymentWindow(): Window | null {
  const paymentWindow = window.open('about:blank', '_blank');
  if (paymentWindow) paymentWindow.opener = null;
  return paymentWindow;
}

function closePreparedPaymentWindow(paymentWindow: Window | null): void {
  if (paymentWindow && !paymentWindow.closed) paymentWindow.close();
}

function normalizePaymentText(value: unknown): string {
  return String(value || '').trim().toLowerCase().replace(/[\s_-]+/g, '_');
}

function resolvePackageStatusDetail(
  quotaSummary: QuotaSummary | null,
  packageLabel: string,
  t: TranslateFn
): string {
  const credit = quotaSummary?.credit;
  if (credit?.status === 'limited') {
    return t(
      'portal.billing.package_status_credit_limited',
      {},
      'The package has no points remaining. Buy points or change the package to continue.'
    );
  }
  const limitedResource = quotaSummary?.resource_limits?.find((resource) => (
    resource.status === 'limited'
    || (!resource.unlimited && Number(resource.limit || 0) > 0 && Number(resource.used || 0) > Number(resource.limit || 0))
  ));
  if (limitedResource?.key === 'bound_sites') {
    return t(
      'portal.billing.package_status_site_limited',
      {
        used: formatNumber(Number(limitedResource.used || 0)),
        limit: formatNumber(Number(limitedResource.limit || 0)),
        package: packageLabel,
      },
      `${formatNumber(Number(limitedResource.used || 0))} sites are connected; ${packageLabel} includes ${formatNumber(Number(limitedResource.limit || 0))}.`
    );
  }
  if (limitedResource?.key === 'vector_documents') {
    return t(
      'portal.billing.package_status_knowledge_limited',
      {
        used: formatNumber(Number(limitedResource.used || 0)),
        limit: formatNumber(Number(limitedResource.limit || 0)),
      },
      `Knowledge usage is ${formatNumber(Number(limitedResource.used || 0))} of ${formatNumber(Number(limitedResource.limit || 0))}.`
    );
  }
  return t('portal.billing.package_status_detail', {}, 'Use this page to handle package or point needs.');
}

function PortalBillingContent() {
  const searchParams = useSearchParams();
  const { t } = useLocale();
  const { session, isLoading: sessionLoading, isAuthenticated, refresh } = useSession();
  const {
    entitlements,
    creditPacks,
    planOffers,
    isLoading,
    error,
    load: loadBilling,
  } = usePortalCommercialCatalog({
    accountId: session?.account_id,
    isAuthenticated,
    t,
  });
  const {
    payload: paymentOrders,
    statusGroup: paymentOrderStatusGroup,
    offset: paymentOrderOffset,
    isLoading: paymentOrdersLoading,
    error: paymentOrderError,
    cancelPendingOrderId,
    cancelConfirmOrderId,
    load: loadPaymentOrders,
    cancel: handleCancelPaymentOrder,
    setStatusGroup: setPaymentOrderStatusGroup,
    setOffset: setPaymentOrderOffset,
    setCancelConfirmOrderId,
  } = usePortalPaymentOrders({
    accountId: session?.account_id,
    isAuthenticated,
    t,
  });
  const [creditPackPending, setCreditPackPending] = useState<string | null>(null);
  const [creditPackError, setCreditPackError] = useState<string | null>(null);
  const [packagePending, setPackagePending] = useState<string | null>(null);
  const [packageError, setPackageError] = useState<string | null>(null);
  const [trialTierSelection, setTrialTierSelection] = useState<'plus' | 'pro'>('pro');
  const [activeCommercialDialog, setActiveCommercialDialog] = useState<
    'package' | 'credits' | 'trial' | null
  >(null);
  const [selectedPackageTier, setSelectedPackageTier] = useState<
    PortalPackageTier | null
  >(null);
  const [showOnlyPackageDifferences, setShowOnlyPackageDifferences] = useState(true);
  const [selectedCreditPackId, setSelectedCreditPackId] = useState<string | null>(null);
  const [paymentLaunch, setPaymentLaunch] = useState<PaymentLaunchState | null>(null);

  useEffect(() => {
    const allowedTiers = planOffers?.trial?.allowed_tiers || [];
    if (!allowedTiers.length || allowedTiers.includes(trialTierSelection)) return;
    setTrialTierSelection(allowedTiers.includes('pro') ? 'pro' : allowedTiers[0]);
  }, [planOffers?.trial?.allowed_tiers, trialTierSelection]);

  const paymentReturnProvider = String(searchParams.get('payment_return') || '').toLowerCase();
  const paymentReturnOrderId = String(searchParams.get('out_trade_no') || '').trim();

  const handleStartPlanTrial = async (tierId: 'plus' | 'pro') => {
    setPackagePending(`trial:${tierId}`);
    setPackageError(null);
    try {
      await portalClient.startPlanTrial(tierId);
      await refresh();
      await loadBilling();
      setActiveCommercialDialog(null);
    } catch (err) {
      setPackageError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setPackagePending(null);
    }
  };

  const handleCreateSubscriptionOrder = async (offer: PortalPlanOffer) => {
    const paymentWindow = preparePaymentWindow();
    setPackagePending(`order:${offer.tier_id}`);
    setPackageError(null);
    setPaymentLaunch(null);
    try {
      const response = await portalClient.createSubscriptionOrder(offer.offer_id, 'alipay');
      if (response.data.order.checkout_url) {
        if (paymentWindow && !paymentWindow.closed) {
          paymentWindow.location.replace(response.data.order.checkout_url);
          setPaymentLaunch({ checkoutUrl: response.data.order.checkout_url, opened: true });
        } else {
          setPaymentLaunch({ checkoutUrl: response.data.order.checkout_url, opened: false });
        }
        setPaymentOrderStatusGroup('pending');
        setPaymentOrderOffset(0);
        await loadPaymentOrders('pending', 0);
        setActiveCommercialDialog(null);
      } else {
        closePreparedPaymentWindow(paymentWindow);
      }
    } catch (err) {
      closePreparedPaymentWindow(paymentWindow);
      setPackageError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setPackagePending(null);
    }
  };

  const handleScheduleFreeDowngrade = async () => {
    setPackagePending('downgrade:free');
    setPackageError(null);
    try {
      await portalClient.scheduleFreeDowngrade();
      await refresh();
      await loadBilling();
      setActiveCommercialDialog(null);
    } catch (err) {
      setPackageError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setPackagePending(null);
    }
  };

  const handleCreateCreditPackOrder = async (packId: string) => {
    const paymentWindow = preparePaymentWindow();
    setCreditPackPending(packId);
    setCreditPackError(null);
    setPaymentLaunch(null);
    try {
      const response = await portalClient.createAccountCreditPackOrder(packId);
      if (response.data.order.checkout_url) {
        if (paymentWindow && !paymentWindow.closed) {
          paymentWindow.location.replace(response.data.order.checkout_url);
          setPaymentLaunch({ checkoutUrl: response.data.order.checkout_url, opened: true });
        } else {
          setPaymentLaunch({ checkoutUrl: response.data.order.checkout_url, opened: false });
        }
        setPaymentOrderStatusGroup('pending');
        setPaymentOrderOffset(0);
        await loadPaymentOrders('pending', 0);
        setActiveCommercialDialog(null);
      } else {
        closePreparedPaymentWindow(paymentWindow);
      }
    } catch (err) {
      closePreparedPaymentWindow(paymentWindow);
      setCreditPackError(formatPortalErrorMessage(err, t, t('error.failed_save')));
    } finally {
      setCreditPackPending(null);
    }
  };

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

  const currentSubscription = session.current_subscription || null;
  const currentPlanId = String(currentSubscription?.plan_id || '').toLowerCase();
  const currentStatus = String(currentSubscription?.status || '').toLowerCase();
  const offersByTier = new Map(
    (planOffers?.items || []).map((offer) => [offer.tier_id, offer] as const)
  );
  const plusOffer = offersByTier.get('plus');
  const proOffer = offersByTier.get('pro');
  const agencyOffer = offersByTier.get('agency');
  const trial = planOffers?.trial;
  const trialState = trial?.state
    || (trial?.status === 'active'
      ? 'active'
      : trial?.available === true
        ? 'eligible'
        : trial?.available === false
          ? 'used'
          : 'unavailable');
  const allowedTrialTiers = (trial?.allowed_tiers || []).filter(
    (tier): tier is 'plus' | 'pro' => tier === 'plus' || tier === 'pro'
  );
  const selectedTrialTier = allowedTrialTiers.includes(trialTierSelection)
    ? trialTierSelection
    : allowedTrialTiers.includes('pro')
      ? 'pro'
      : allowedTrialTiers[0];
  const selectedTrialOffer = selectedTrialTier ? offersByTier.get(selectedTrialTier) : null;
  const trialDays = Number(trial?.trial_days || selectedTrialOffer?.trial_days || 14);
  const activeTrialTier = String(trial?.highest_tier_id || trial?.tier_id || currentPlanId || '').toLowerCase();
  const activeTrialTierLabel = activeTrialTier === 'plus' ? 'Plus' : activeTrialTier === 'pro' ? 'Pro' : '';
  const availableCreditPacks = creditPacks?.items || [];
  const selectedPackageOffer = selectedPackageTier && selectedPackageTier !== 'free'
    ? offersByTier.get(selectedPackageTier)
    : null;
  const allPaymentOrders = paymentOrders?.items || [];
  const paymentOrderCounts = paymentOrders?.counts || {
    all: allPaymentOrders.length,
    pending: allPaymentOrders.filter(isPortalPaymentOrderPending).length,
    paid: allPaymentOrders.filter((order) => normalizePaymentText(order.status) === 'paid').length,
    closed: allPaymentOrders.filter((order) => !['pending', 'paid'].includes(normalizePaymentText(order.status))).length,
  };

  const paymentLaunchNotice = paymentLaunch ? (
    <div
      role="status"
      className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900 dark:border-blue-900/60 dark:bg-blue-950/20 dark:text-blue-100"
    >
      {paymentLaunch.opened ? (
        t(
          'portal.usage.payment_page_opened',
          {},
          'Alipay opened in a new tab. Return here after payment and the order status will refresh automatically.'
        )
      ) : (
        <span className="flex flex-wrap items-center gap-3">
          <span>
            {t(
              'portal.usage.payment_page_blocked',
              {},
              'Your browser blocked the payment tab. Use the button to open Alipay.'
            )}
          </span>
          <a
            className="btn btn-primary"
            href={paymentLaunch.checkoutUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t('portal.usage.payment_page_open_action', {}, 'Open Alipay')}
          </a>
        </span>
      )}
    </div>
  ) : null;

  const comparisonTiers = planOffers?.comparison_tiers || [];

  const handleConfirmPackageSelection = () => {
    if (!selectedPackageTier || packagePending !== null) return;
    if (selectedPackageTier === 'free') {
      void handleScheduleFreeDowngrade();
      return;
    }
    const selectedOffer = offersByTier.get(selectedPackageTier);
    if (selectedOffer) void handleCreateSubscriptionOrder(selectedOffer);
  };

  const handleConfirmCreditPackSelection = () => {
    if (!selectedCreditPackId || creditPackPending !== null) return;
    void handleCreateCreditPackOrder(selectedCreditPackId);
  };

  const packageOptions = (
    <PortalPackageChangePanel
      t={t}
      currentPlanId={currentPlanId}
      currentStatus={currentStatus}
      comparisonTiers={comparisonTiers}
      plusOffer={plusOffer}
      proOffer={proOffer}
      agencyOffer={agencyOffer}
      selectedTier={selectedPackageTier}
      showOnlyDifferences={showOnlyPackageDifferences}
      pendingAction={packagePending}
      error={packageError}
      onSelectTier={setSelectedPackageTier}
      onShowOnlyDifferencesChange={setShowOnlyPackageDifferences}
      onConfirm={handleConfirmPackageSelection}
      onAgencyPurchase={(offer) => void handleCreateSubscriptionOrder(offer)}
    />
  );

  const trialStatusTitle = trialState === 'eligible'
    ? t('portal.package.trial_eligible_title', { days: String(trialDays) }, `${trialDays}-day paid-package trial available`)
    : trialState === 'active'
      ? t('portal.package.trial_active_title', { tier: activeTrialTierLabel }, `${activeTrialTierLabel} trial is active`)
      : trialState === 'used'
        ? t('portal.package.trial_used_title', {}, 'Trial already used')
        : trialState === 'blocked'
          ? t('portal.package.trial_blocked_title', {}, 'Trial unavailable with an active paid package')
          : t('portal.package.trial_unavailable_title', {}, 'Trial is not currently offered');
  const trialStatusDescription = trialState === 'eligible'
    ? t('portal.package.trial_shared_desc', {}, 'Each account has one shared paid-package trial. You may move to a higher tier during the trial, but the end date will not be extended.')
    : trialState === 'active'
      ? t(
          'portal.package.trial_active_desc',
          {
            tier: activeTrialTierLabel,
            date: trial?.trial_ends_at ? formatDate(trial.trial_ends_at) : t('common.unknown', {}, 'To confirm'),
          },
          `${activeTrialTierLabel} trial ends ${trial?.trial_ends_at ? formatDate(trial.trial_ends_at) : 'to be confirmed'}. Moving to a higher tier does not extend the end date.`
        )
      : trialState === 'used'
        ? t('portal.package.trial_used_desc', {}, 'This account has already used its paid-package trial. You can still purchase a package.')
        : trialState === 'blocked'
          ? t('portal.package.trial_blocked_desc', {}, 'This account already has an active paid package, so a trial cannot be started. Renew or change the package instead.')
          : t('portal.package.trial_unavailable_desc', {}, 'No self-service trial is available for this account. Package purchase remains available.');

  const trialOptions = (
    <PortalTrialEligibilityPanel
      t={t}
      state={trialState}
      title={trialStatusTitle}
      description={trialStatusDescription}
      allowedTiers={allowedTrialTiers}
      selectedTier={selectedTrialTier}
      trialDays={trialDays}
      pendingAction={packagePending}
      error={packageError}
      onSelectTier={setTrialTierSelection}
      onStartTrial={(tier) => void handleStartPlanTrial(tier)}
    />
  );

  const paymentOrdersCard = (
    <PortalPaymentOrderHistory
      t={t}
      payload={paymentOrders}
      counts={paymentOrderCounts}
      statusGroup={paymentOrderStatusGroup}
      offset={paymentOrderOffset}
      isLoading={paymentOrdersLoading}
      error={paymentOrderError}
      cancelPendingOrderId={cancelPendingOrderId}
      cancelConfirmOrderId={cancelConfirmOrderId}
      onStatusGroupChange={setPaymentOrderStatusGroup}
      onOffsetChange={setPaymentOrderOffset}
      onCancelConfirmChange={setCancelConfirmOrderId}
      onCancel={(order) => void handleCancelPaymentOrder(order)}
    />
  );

  if (isLoading && !entitlements && !planOffers && !creditPacks) {
    return <PortalLoadingState message={t('portal.billing.loading', {}, 'Loading package details...')} />;
  }

  const snapshotPlanVersionId =
    currentSubscription?.plan_version_id || '';
  const packageDisplay = resolveCustomerPackageDisplay(t, {
    planId: currentSubscription?.plan_id,
    planVersionId: snapshotPlanVersionId,
    packageAlias: currentSubscription?.package_alias,
    planKind: currentSubscription?.plan_kind,
    coverageState: currentSubscription ? 'covered' : 'uncovered',
  });
  const packageLabel = packageDisplay.display_package_label || t('portal.home.package_pending_label', {}, 'To confirm');
  const quotaSummary = entitlements?.quota_summary || null;
  const currentPeriodStart =
    entitlements?.period_start_at ||
    currentSubscription?.current_period_start ||
    '';
  const currentPeriodEnd =
    entitlements?.period_end_at ||
    currentSubscription?.current_period_end ||
    '';
  const currentPeriodLabel =
    currentPeriodStart && currentPeriodEnd
      ? `${formatDate(currentPeriodStart)} - ${formatDate(currentPeriodEnd)}`
      : t('portal.home.package_pending_label', {}, 'To confirm');
  const packageStatus =
    String(quotaSummary?.status || '') === 'limited'
      ? 'warning'
      : 'ok';
  const packageStatusLabel =
    packageStatus === 'warning'
      ? t('common.attention', {}, 'Attention')
      : t('common.ok', {}, 'OK');

  return (
    <PortalPageStack>
      <PortalWorkspaceHeader
        eyebrow={t('portal.workspace_label', {}, 'Portal')}
        title={t('portal.billing.customer_title', {}, 'Package')}
        description={t('portal.billing.subtitle', {}, 'Confirm the current package, included rights, and upgrade options.')}
        currentPage="billing"
      />

      <PortalPaymentReturnNotice
        t={t}
        provider={paymentReturnProvider}
        orderId={paymentReturnOrderId}
        isAuthenticated={isAuthenticated}
        accountId={session.account_id}
        entitlements={entitlements}
        refreshSession={refresh}
        refreshBilling={loadBilling}
        refreshPaymentOrders={() => loadPaymentOrders(paymentOrderStatusGroup, paymentOrderOffset)}
      />

      {paymentLaunchNotice}

      {error ? (
        <PortalErrorState
          title={t('error.failed_load', {}, 'Failed to load')}
          description={error}
          retryLabel={t('common.retry', {}, 'Retry')}
          onRetry={() => void loadBilling()}
        />
      ) : null}

      <PortalMetricStrip
        items={[
          { label: t('portal.current_subscription_label', {}, 'Current package'), value: packageLabel },
          {
            label: t('common.status'),
            value: packageStatusLabel,
            detail: resolvePackageStatusDetail(quotaSummary, packageLabel, t),
            size: 'compact',
          },
          {
            label: t('portal.usage.period_label', {}, 'Period'),
            value: currentPeriodLabel,
            size: 'compact',
          },
        ]}
        columnsClassName="lg:grid-cols-3"
        variant="portal"
      />

      <PortalCard variant="portal" className="bg-white dark:bg-slate-950">
        <PortalEntitlementUsage
          quotaSummary={quotaSummary}
          periodLabel={currentPeriodLabel}
          t={t}
        />
      </PortalCard>

      <div id="package-options" className="scroll-mt-24">
        <PortalCard variant="portal" className="bg-white dark:bg-slate-950">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-center lg:justify-between">
            <div className="max-w-2xl">
              <h2 className="text-lg font-semibold text-slate-950 dark:text-white">
                {t('portal.billing.manage_title', {}, 'Manage package')}
              </h2>
              <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
                {t('portal.billing.manage_desc', {}, 'Open an option only when you need to change the package, add points, or review trial eligibility.')}
              </p>
              <p className="mt-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                {trialStatusTitle}
              </p>
            </div>
            <div className="grid w-full gap-2 sm:grid-cols-2 lg:w-auto lg:min-w-[31rem] lg:grid-cols-3">
              <button
                type="button"
                className="btn btn-primary whitespace-nowrap"
                onClick={() => {
                  setPackageError(null);
                  setSelectedPackageTier(null);
                  setShowOnlyPackageDifferences(true);
                  setActiveCommercialDialog('package');
                }}
              >
                {t('portal.billing.upgrade_action', {}, 'Upgrade package')}
              </button>
              {availableCreditPacks.length > 0 ? (
                <button
                  type="button"
                  className="btn btn-secondary whitespace-nowrap"
                  onClick={() => {
                    setCreditPackError(null);
                    setSelectedCreditPackId(null);
                    setActiveCommercialDialog('credits');
                  }}
                >
                  {t('portal.usage.credit_pack_buy_action', {}, 'Buy credits')}
                </button>
              ) : null}
              <button
                type="button"
                className="btn btn-secondary whitespace-nowrap"
                onClick={() => {
                  setPackageError(null);
                  setActiveCommercialDialog('trial');
                }}
              >
                {trialState === 'eligible'
                  ? t('portal.package.trial_entry_action', { days: String(trialDays) }, `Start ${trialDays}-day trial`)
                  : trialState === 'active'
                    ? t('portal.package.trial_active_entry_action', {}, 'View active trial')
                    : t('portal.package.trial_eligibility_action', {}, 'Trial eligibility')}
              </button>
            </div>
          </div>
        </PortalCard>
      </div>

      {paymentOrdersCard}

      <Modal
        isOpen={activeCommercialDialog === 'package'}
        onClose={() => setActiveCommercialDialog(null)}
        title={t('portal.billing.package_dialog_title', {}, 'Choose a package')}
        description={t('portal.billing.package_dialog_desc', {}, 'Compare available packages and choose the change you want to make.')}
        size="xl"
        className="portal-commercial-dialog max-w-5xl rounded-[18px] shadow-[0_16px_44px_rgba(15,23,42,0.14)]"
      >
        {packageOptions}
      </Modal>

      <PortalCreditPackDialog
        t={t}
        isOpen={activeCommercialDialog === 'credits'}
        packs={availableCreditPacks}
        selectedPackId={selectedCreditPackId}
        pendingPackId={creditPackPending}
        error={creditPackError}
        onClose={() => setActiveCommercialDialog(null)}
        onSelect={setSelectedCreditPackId}
        onConfirm={handleConfirmCreditPackSelection}
      />

      <Modal
        isOpen={activeCommercialDialog === 'trial'}
        onClose={() => setActiveCommercialDialog(null)}
        title={t('portal.package.trial_dialog_title', {}, 'Trial eligibility')}
        description={t('portal.package.trial_dialog_desc', {}, 'Review this account trial status before starting or changing a trial.')}
        size="lg"
        className="portal-commercial-dialog rounded-[18px] shadow-[0_16px_44px_rgba(15,23,42,0.14)]"
      >
        {trialOptions}
      </Modal>
    </PortalPageStack>
  );
}

export default function PortalBillingPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalBillingContent />
    </Suspense>
  );
}
