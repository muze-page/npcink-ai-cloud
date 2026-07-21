type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

const COMMERCIAL_COPY_KEYS: Record<string, string> = {
  'Read current status and grace posture first; commercial follow-up should lead before runtime debugging when the subscription is degraded.':
    'admin.commercial_follow_up.subscription_lifecycle_posture',
  'Read current status and grace posture first.':
    'admin.commercial_follow_up.subscription_lifecycle_posture',
  'Use site detail and filtered audit evidence to confirm whether snapshot posture and current operational impact are still aligned.':
    'admin.commercial_follow_up.subscription_snapshot_reconciliation',
  'Use site detail and filtered audit evidence to confirm whether snapshot posture and impact are aligned.':
    'admin.commercial_follow_up.subscription_snapshot_reconciliation',
  'Open site detail for runtime and entitlement impact, or customer detail for support scope.':
    'admin.commercial_follow_up.subscription_next_step',
  'Open site detail for runtime and entitlement impact.':
    'admin.commercial_follow_up.subscription_next_step',
  'Current-period billing snapshots need rebuild to match the latest subscription posture.':
    'admin.commercial_follow_up.snapshot_needs_rebuild',
  'Current-period billing snapshots are still missing for at least one covered site.':
    'admin.commercial_follow_up.snapshot_missing',
  'Current-period billing snapshots are fresh for every covered site.':
    'admin.commercial_follow_up.snapshot_fresh',
  'Current-period billing snapshots were rebuilt for every covered site.':
    'admin.commercial_follow_up.snapshot_rebuilt',
  'No covered sites are currently attached to this subscription, so there were no billing snapshots to rebuild.':
    'admin.commercial_follow_up.snapshot_no_sites',
  'Rebuild current-period billing snapshots':
    'admin.subscription_detail.snapshot_refresh_action',
  'Refresh current-period billing snapshots for every covered site before treating billing posture as reconciled.':
    'admin.subscription_detail.snapshot_refresh_detail',
  'Use the linked plan and version snapshot as the current commercial entitlement boundary for this site.':
    'admin.commercial_follow_up.site_entitlement_summary',
  'Budget headroom should be read before widening runtime troubleshooting, because over-limit posture can be the real blocker.':
    'admin.commercial_follow_up.site_budget_headroom',
  'Budget headroom should be read before widening runtime troubleshooting.':
    'admin.commercial_follow_up.site_budget_headroom',
  'If runtime posture is degraded or policy-gated, confirm whether subscription state, grace, or downgrade policy is already constraining this site.':
    'admin.commercial_follow_up.site_runtime_gating',
  'Confirm whether subscription state or downgrade policy is constraining this site.':
    'admin.commercial_follow_up.site_runtime_gating',
  'Open the current customer subscription when commercial coverage is the blocker; stay on site detail when runtime posture is the blocker.':
    'admin.commercial_follow_up.site_next_step',
  'Open the current customer subscription when commercial coverage is the blocker.':
    'admin.commercial_follow_up.site_next_step',
};

export function localizeAdminCommercialCopy(text: string | null | undefined, t: TranslateFn): string {
  const normalized = typeof text === 'string' ? text.trim() : '';
  if (!normalized) {
    return '';
  }

  const key = COMMERCIAL_COPY_KEYS[normalized];
  return key ? t(key, {}, normalized) : normalized;
}
