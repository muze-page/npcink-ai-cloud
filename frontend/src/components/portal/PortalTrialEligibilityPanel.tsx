'use client';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

type PortalTrialEligibilityPanelProps = {
  t: TranslateFn;
  state: string;
  title: string;
  description: string;
  allowedTiers: Array<'plus' | 'pro'>;
  selectedTier?: 'plus' | 'pro';
  trialDays: number;
  pendingAction: string | null;
  error: string | null;
  onSelectTier: (tier: 'plus' | 'pro') => void;
  onStartTrial: (tier: 'plus' | 'pro') => void;
};

export function PortalTrialEligibilityPanel({
  t,
  state,
  title,
  description,
  allowedTiers,
  selectedTier,
  trialDays,
  pendingAction,
  error,
  onSelectTier,
  onStartTrial,
}: PortalTrialEligibilityPanelProps) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-blue-200 bg-blue-50/70 px-4 py-4 dark:border-blue-900/60 dark:bg-blue-950/20">
        <p className="text-base font-semibold text-slate-950 dark:text-white">{title}</p>
        <p className="mt-2 text-sm leading-6 text-slate-600 dark:text-slate-300">{description}</p>
      </div>
      {selectedTier && (state === 'eligible' || state === 'active') ? (
        <div className="space-y-4">
          {allowedTiers.length > 1 ? (
            <div>
              <p className="mb-2 text-sm font-medium text-slate-700 dark:text-slate-200">
                {t('portal.package.trial_choose_tier', {}, 'Choose trial package')}
              </p>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {allowedTiers.map((tier) => (
                  <button
                    key={tier}
                    type="button"
                    className={tier === selectedTier ? 'btn btn-primary' : 'btn btn-secondary'}
                    aria-pressed={tier === selectedTier}
                    disabled={pendingAction !== null}
                    onClick={() => onSelectTier(tier)}
                  >
                    {tier === 'plus' ? 'Plus' : 'Pro'}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <button
            type="button"
            className="btn btn-primary w-full whitespace-nowrap"
            disabled={pendingAction !== null}
            onClick={() => onStartTrial(selectedTier)}
          >
            {pendingAction === `trial:${selectedTier}`
              ? t('common.saving', {}, 'Saving...')
              : state === 'active'
                ? t(
                    'portal.package.trial_upgrade_action',
                    { tier: selectedTier === 'plus' ? 'Plus' : 'Pro' },
                    `Move trial to ${selectedTier === 'plus' ? 'Plus' : 'Pro'}`
                  )
                : t(
                    'portal.package.trial_start_action',
                    {
                      tier: selectedTier === 'plus' ? 'Plus' : 'Pro',
                      days: String(trialDays),
                    },
                    `Start ${trialDays}-day ${selectedTier === 'plus' ? 'Plus' : 'Pro'} trial`
                  )}
          </button>
        </div>
      ) : null}
      {error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-200">
          {error}
        </div>
      ) : null}
    </div>
  );
}
