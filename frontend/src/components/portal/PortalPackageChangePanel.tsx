'use client';

import Link from 'next/link';
import { PortalStatusBadge } from '@/components/portal/PortalStatusBadge';
import type {
  PortalPlanComparisonRightKey,
  PortalPlanComparisonTier,
  PortalPlanOffer,
} from '@/lib/portal-client';
import { formatPortalCurrency } from '@/lib/currency';
import { formatNumber } from '@/lib/utils';

export type PortalPackageTier = 'free' | 'plus' | 'pro';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

type PortalPackageChangePanelProps = {
  t: TranslateFn;
  currentPlanId: string;
  currentStatus: string;
  comparisonTiers: PortalPlanComparisonTier[];
  plusOffer?: PortalPlanOffer;
  proOffer?: PortalPlanOffer;
  agencyOffer?: PortalPlanOffer;
  selectedTier: PortalPackageTier | null;
  showOnlyDifferences: boolean;
  pendingAction: string | null;
  error: string | null;
  onSelectTier: (tier: PortalPackageTier) => void;
  onShowOnlyDifferencesChange: (showOnlyDifferences: boolean) => void;
  onConfirm: () => void;
  onAgencyPurchase: (offer: PortalPlanOffer) => void;
};

type PackageChoice = {
  tier: PortalPackageTier;
  label: string;
  description: string;
  selectable: boolean;
  statusLabel?: string;
  statusTone?: string;
};

const tierRank: Record<string, number> = { free: 0, plus: 1, pro: 2, agency: 3 };
const requiredComparisonRights: PortalPlanComparisonRightKey[] = [
  'monthly_points',
  'site_limit',
  'knowledge_article_limit',
  'concurrency_limit',
  'batch_item_limit',
];

export function PortalPackageChangePanel({
  t,
  currentPlanId,
  currentStatus,
  comparisonTiers,
  plusOffer,
  proOffer,
  agencyOffer,
  selectedTier,
  showOnlyDifferences,
  pendingAction,
  error,
  onSelectTier,
  onShowOnlyDifferencesChange,
  onConfirm,
  onAgencyPurchase,
}: PortalPackageChangePanelProps) {
  const currentRank = tierRank[currentPlanId] ?? 0;
  const comparisonByTier = new Map(
    comparisonTiers.map((tier) => [tier.tier_id, tier] as const)
  );
  const tierRightsArePublished = (tierId: PortalPackageTier) => {
    const tier = comparisonByTier.get(tierId);
    if (!tier) return false;
    const rights = tier.comparison_rights;
    return requiredComparisonRights.every((key) => {
      const right = rights?.[key];
      return Boolean(right && right.state !== 'unconfigured');
    });
  };
  const plusRightsArePublished = tierRightsArePublished('plus');
  const proRightsArePublished = tierRightsArePublished('pro');
  const packageChoices: PackageChoice[] = [
    {
      tier: 'free',
      label: t('portal.package.free_title', {}, 'Free'),
      description: t('portal.billing.package_included_price', {}, 'Included with the account'),
      selectable: currentRank > 0,
      statusLabel: currentPlanId === 'free'
        ? t('common.current', {}, 'Current')
        : t('common.available', {}, 'Available'),
      statusTone: currentPlanId === 'free' ? 'ok' : 'neutral',
    },
    {
      tier: 'plus',
      label: t('portal.package.plus_title', {}, 'Plus'),
      description: plusOffer && plusRightsArePublished
        ? t(
            'portal.package.paid_offer_desc',
            { amount: formatPortalCurrency(plusOffer.amount) },
            `${formatPortalCurrency(plusOffer.amount)} for 30 days.`
          )
        : t('portal.package.offer_unavailable_desc', {}, 'This package is not currently available for purchase.'),
      selectable: Boolean(plusOffer && plusRightsArePublished),
      statusLabel: currentPlanId === 'plus'
        ? currentStatus === 'trialing'
          ? t('portal.package.pro_trial_active', {}, 'Trial active')
          : t('common.current', {}, 'Current')
        : !plusOffer
          ? t('portal.package.offer_unavailable', {}, 'Unavailable')
          : !plusRightsArePublished
            ? t('portal.billing.compare_unconfigured', {}, 'To confirm')
          : undefined,
      statusTone: currentPlanId === 'plus' ? 'ok' : 'warning',
    },
    {
      tier: 'pro',
      label: t('portal.package.pro_title', {}, 'Pro'),
      description: proOffer && proRightsArePublished
        ? t(
            'portal.package.paid_offer_desc',
            { amount: formatPortalCurrency(proOffer.amount) },
            `${formatPortalCurrency(proOffer.amount)} for 30 days.`
          )
        : t('portal.package.offer_unavailable_desc', {}, 'This package is not currently available for purchase.'),
      selectable: Boolean(proOffer && proRightsArePublished),
      statusLabel: currentPlanId === 'pro'
        ? currentStatus === 'trialing'
          ? t('portal.package.pro_trial_active', {}, 'Trial active')
          : t('common.current', {}, 'Current')
        : !proOffer
          ? t('portal.package.offer_unavailable', {}, 'Unavailable')
          : !proRightsArePublished
            ? t('portal.billing.compare_unconfigured', {}, 'To confirm')
          : undefined,
      statusTone: currentPlanId === 'pro' ? 'ok' : 'warning',
    },
  ];
  const selectedChoice = packageChoices.find((choice) => choice.tier === selectedTier) || null;
  const selectedComparison = selectedTier ? comparisonByTier.get(selectedTier) || null : null;
  const currentComparison = comparisonByTier.get(currentPlanId as PortalPackageTier) || null;
  const currentChoiceLabel = currentComparison?.label
    || (currentPlanId ? `${currentPlanId.charAt(0).toUpperCase()}${currentPlanId.slice(1)}` : '')
    || t('portal.home.package_pending_label', {}, 'To confirm');
  const comparisonRows = [
    { key: 'monthly_points', label: t('portal.billing.compare_monthly_points', {}, 'Monthly package points') },
    { key: 'site_limit', label: t('portal.billing.compare_site_limit', {}, 'Connected sites') },
    { key: 'knowledge_article_limit', label: t('portal.billing.compare_knowledge_limit', {}, 'Knowledge articles') },
    { key: 'concurrency_limit', label: t('portal.billing.compare_concurrency_limit', {}, 'Active runs') },
    { key: 'batch_item_limit', label: t('portal.billing.compare_batch_limit', {}, 'Batch size') },
  ] as const;
  const comparisonRightSignature = (
    tier: PortalPlanComparisonTier,
    key: PortalPlanComparisonRightKey,
  ) => {
    const right = tier.comparison_rights?.[key];
    if (right) return `${right.state}:${right.value ?? ''}`;
    const legacyValue = tier[key];
    return legacyValue == null ? 'unconfigured:' : `limited:${legacyValue}`;
  };
  const visibleComparisonRows = showOnlyDifferences
    ? comparisonRows.filter((row) => (
        new Set(comparisonTiers.map((tier) => comparisonRightSignature(tier, row.key))).size > 1
      ))
    : comparisonRows;
  const formatComparisonRight = (
    tier: PortalPlanComparisonTier,
    key: PortalPlanComparisonRightKey,
  ) => {
    const right = tier.comparison_rights?.[key];
    if (!right) {
      const legacyValue = tier[key];
      return {
        label: legacyValue == null
          ? t('portal.billing.compare_unconfigured', {}, 'To confirm')
          : formatNumber(legacyValue),
        state: legacyValue == null ? 'unconfigured' : 'limited',
      };
    }
    if (right.state === 'unlimited') {
      return { label: t('common.unlimited', {}, 'Unlimited'), state: right.state };
    }
    if (right.state === 'not_included') {
      return { label: t('portal.billing.compare_not_included', {}, 'Not included'), state: right.state };
    }
    if (right.state === 'unconfigured') {
      return { label: t('portal.billing.compare_unconfigured', {}, 'To confirm'), state: right.state };
    }
    return { label: formatNumber(right.value || 0), state: right.state };
  };
  const hasUnconfiguredRights = comparisonTiers.some((tier) => (
    Object.values(tier.comparison_rights || {}).some((right) => right.state === 'unconfigured')
  ));
  const selectedOffer = selectedTier === 'plus' ? plusOffer : selectedTier === 'pro' ? proOffer : null;
  const selectedTierRightsArePublished = selectedTier
    ? tierRightsArePublished(selectedTier)
    : false;
  const selectedAmount = selectedOffer ? formatPortalCurrency(selectedOffer.amount) : '';
  const actionLabel = selectedTier === 'free'
    ? t('portal.package.schedule_free_downgrade', {}, 'Switch to Free at period end')
    : selectedTier === 'plus' || selectedTier === 'pro'
      ? currentPlanId === selectedTier
        ? t('portal.billing.package_renew_price_action', { amount: selectedAmount }, `Renew ${selectedAmount}`)
        : currentRank > tierRank[selectedTier]
          ? t('portal.package.schedule_paid_downgrade', {}, 'Use next period')
          : t('portal.billing.package_pay_price_action', { amount: selectedAmount }, `Pay ${selectedAmount}`)
      : t('portal.billing.package_select_action', {}, 'Select a package');
  const changeDetail = !selectedTier
    ? ''
    : selectedTier === currentPlanId
      ? t('portal.billing.package_renew_effective', {}, 'Adds another 30-day package period after payment confirmation.')
      : currentRank > tierRank[selectedTier]
        ? t('portal.billing.package_downgrade_effective', {}, 'The lower package takes effect after the current period ends.')
        : t('portal.billing.package_upgrade_effective', {}, 'The new 30-day package takes effect after payment confirmation.');
  const selectionDisabled = pendingAction !== null
    || !selectedChoice
    || !selectedChoice.selectable
    || (selectedTier !== 'free' && (!selectedOffer || !selectedTierRightsArePublished));

  return (
    <>
      <div
        className="grid gap-3 sm:grid-cols-3"
        role="radiogroup"
        aria-label={t('portal.billing.package_dialog_title', {}, 'Choose a package')}
      >
        {packageChoices.map((choice) => {
          const selected = selectedTier === choice.tier;
          return (
            <div
              key={choice.tier}
              className={`flex min-h-32 flex-col rounded-[18px] border-2 bg-white p-1 transition-colors dark:bg-slate-950 ${
                selected
                  ? 'border-[#0071e3] dark:border-[#2997ff]'
                  : 'border-slate-200 dark:border-slate-800'
              }`}
            >
              <button
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={!choice.selectable || pendingAction !== null}
                className="flex flex-1 flex-col items-start rounded-[14px] px-4 py-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0071e3] focus-visible:ring-offset-2 disabled:cursor-default disabled:opacity-100 dark:focus-visible:ring-[#2997ff] dark:focus-visible:ring-offset-slate-950"
                onClick={() => onSelectTier(choice.tier)}
              >
                <span className="text-base font-semibold text-slate-950 dark:text-white">{choice.label}</span>
                <span className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{choice.description}</span>
                {choice.statusLabel ? (
                  <PortalStatusBadge
                    status={choice.statusTone || 'neutral'}
                    label={choice.statusLabel}
                    className="mt-4 normal-case tracking-normal"
                  />
                ) : null}
                {choice.selectable ? (
                  <span className="mt-auto pt-3 text-sm font-semibold text-[#0066cc] dark:text-[#2997ff]">
                    {selected
                      ? t('portal.billing.selected_target_package', {}, 'Selected')
                      : t('portal.billing.package_select_action', {}, 'Select package')}
                  </span>
                ) : null}
              </button>
            </div>
          );
        })}
      </div>

      <div className="mt-4 flex flex-col gap-4 rounded-[18px] border border-blue-100 bg-blue-50/70 p-4 dark:border-blue-900/60 dark:bg-blue-950/20 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {selectedChoice
              ? t(
                  'portal.billing.package_change_path',
                  { from: currentChoiceLabel, to: selectedChoice.label },
                  `${currentChoiceLabel} to ${selectedChoice.label}`
                )
              : t('portal.billing.package_select_hint', {}, 'Select a package above to continue.')}
          </p>
          {selectedComparison ? (
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{changeDetail}</p>
          ) : null}
        </div>
        <button
          type="button"
          className="btn btn-primary shrink-0 whitespace-nowrap"
          disabled={selectionDisabled}
          onClick={onConfirm}
        >
          {pendingAction ? t('common.saving', {}, 'Saving...') : actionLabel}
        </button>
      </div>

      <section className="mt-5" aria-labelledby="portal-package-comparison-title">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <h3 id="portal-package-comparison-title" className="text-base font-semibold text-slate-950 dark:text-white">
              {t('portal.billing.package_comparison_title', {}, 'Compare package rights')}
            </h3>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
              {t('portal.billing.package_comparison_desc', {}, 'Compare the customer-visible limits that change between packages.')}
            </p>
          </div>
          <label className="inline-flex min-h-11 items-center gap-2 text-sm text-slate-600 dark:text-slate-300">
            <input
              type="checkbox"
              checked={showOnlyDifferences}
              onChange={(event) => onShowOnlyDifferencesChange(event.target.checked)}
              className="h-4 w-4 rounded border-slate-300 text-[#0066cc] focus:ring-[#0071e3]"
            />
            {t('portal.billing.package_only_differences', {}, 'Only show differences')}
          </label>
        </div>
        {comparisonTiers.length > 0 ? (
          <div className="mt-3 overflow-x-auto rounded-[18px] border border-slate-200 dark:border-slate-800">
            <table className="min-w-[42rem] w-full border-collapse text-sm">
              <thead className="bg-[#f5f5f7] dark:bg-slate-900/70">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left font-semibold text-slate-600 dark:text-slate-300">
                    {t('portal.billing.package_comparison_right_label', {}, 'Right')}
                  </th>
                  {comparisonTiers.map((tier) => (
                    <th
                      key={tier.tier_id}
                      scope="col"
                      className={`px-4 py-3 text-right font-semibold ${
                        selectedTier === tier.tier_id
                          ? 'bg-blue-50 text-[#0066cc] dark:bg-blue-950/25 dark:text-[#2997ff]'
                          : 'text-slate-950 dark:text-white'
                      }`}
                    >
                      <span>{tier.label}</span>
                      {currentPlanId === tier.tier_id ? (
                        <span className="ml-2 text-xs font-medium text-slate-500 dark:text-slate-400">
                          {t('common.current', {}, 'Current')}
                        </span>
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 bg-white dark:divide-slate-800 dark:bg-slate-950">
                {visibleComparisonRows.map((row) => (
                  <tr key={row.key}>
                    <th scope="row" className="px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-300">
                      {row.label}
                    </th>
                    {comparisonTiers.map((tier) => {
                      const right = formatComparisonRight(tier, row.key);
                      return (
                        <td
                          key={tier.tier_id}
                          data-comparison-state={right.state}
                          className={`px-4 py-3 text-right font-semibold ${
                          selectedTier === tier.tier_id
                            ? 'bg-blue-50/70 text-slate-950 dark:bg-blue-950/20 dark:text-white'
                            : right.state === 'unconfigured'
                              ? 'text-amber-700 dark:text-amber-300'
                              : 'text-slate-700 dark:text-slate-200'
                          }`}
                        >
                          {right.label}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            {hasUnconfiguredRights ? (
              <p className="border-t border-amber-200 bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-200">
                {t(
                  'portal.billing.compare_unconfigured_desc',
                  {},
                  'To confirm means the published package does not currently define this right. Confirm it before purchase.'
                )}
              </p>
            ) : null}
          </div>
        ) : (
          <div className="mt-3 rounded-xl border border-slate-200 px-4 py-4 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-300">
            {t('portal.billing.package_comparison_unavailable', {}, 'Package rights comparison is temporarily unavailable.')}
          </div>
        )}
      </section>

      <div className="mt-5 flex flex-col gap-4 rounded-[18px] border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-950 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-950 dark:text-white">
            {t('portal.billing.agency_separate_title', {}, 'Need more capacity?')}
          </p>
          <p className="mt-1 text-sm leading-6 text-slate-600 dark:text-slate-300">
            {agencyOffer
              ? t(
                  'portal.billing.agency_quote_ready_desc',
                  { amount: formatPortalCurrency(agencyOffer.amount) },
                  `Your Agency quote is ready at ${formatPortalCurrency(agencyOffer.amount)} for 30 days.`
                )
              : t('portal.package.agency_desc', {}, 'Custom high-volume coverage. Submit a request for a time-limited quote and approved trial.')}
          </p>
        </div>
        {agencyOffer ? (
          <button
            type="button"
            className="btn btn-secondary shrink-0 whitespace-nowrap"
            disabled={pendingAction !== null}
            onClick={() => onAgencyPurchase(agencyOffer)}
          >
            {pendingAction === 'order:agency'
              ? t('common.saving', {}, 'Saving...')
              : t('portal.package.buy_agency_quote', {}, 'Pay Agency quote')}
          </button>
        ) : (
          <Link href="/portal/support?new=1&topic=billing" className="btn btn-secondary shrink-0 whitespace-nowrap">
            {t('portal.package.request_agency_quote', {}, 'Request Agency quote')}
          </Link>
        )}
      </div>

      {error ? (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-200">
          {error}
        </div>
      ) : null}
    </>
  );
}
