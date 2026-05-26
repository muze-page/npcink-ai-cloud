type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

export function localizeTierLabel(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'starter':
      return t('admin.plan_tier_starter', {}, fallback || 'Starter');
    case 'pro':
      return t('admin.plan_tier_pro', {}, fallback || 'Pro');
    case 'agency':
      return t('admin.plan_tier_agency', {}, fallback || 'Agency');
    default:
      return fallback || tierId;
  }
}

export function localizePackageAlias(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'plan_free':
    case 'starter':
      return t('admin.plan_package_alias_starter', {}, fallback || 'Free');
    case 'pro':
      return t('admin.plan_package_alias_pro', {}, fallback || 'Basic');
    case 'agency':
      return t('admin.plan_package_alias_agency', {}, fallback || 'Bulk');
    default:
      return fallback || tierId;
  }
}

export function localizeUsageBand(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'starter':
      return t('admin.plan_usage_band_starter', {}, fallback || 'Low-volume single-site hosted usage.');
    case 'pro':
      return t('admin.plan_usage_band_pro', {}, fallback || 'Mid-band workflow and automation usage.');
    case 'agency':
      return t('admin.plan_usage_band_agency', {}, fallback || 'High-volume multi-site and sustained workflow usage.');
    default:
      return fallback || '';
  }
}

export function localizePositioning(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'starter':
      return t('admin.plan_positioning_starter', {}, fallback || 'Baseline package for conservative hosted runs, lighter workflow usage, and operator-managed growth.');
    case 'pro':
      return t('admin.plan_positioning_pro', {}, fallback || 'General-purpose package for steadier workflow volume, fuller automation usage, and predictable hosted operations.');
    case 'agency':
      return t('admin.plan_positioning_agency', {}, fallback || 'High-headroom package for multi-site operators, continuous automation, and materially higher hosted workload.');
    default:
      return fallback || '';
  }
}

export function localizeOperatorNote(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'starter':
      return t('admin.plan_operator_note_starter', {}, fallback || 'Core capabilities stay available across packages. Free remains the most conservative on points, concurrency, batch headroom, and over-limit handling.');
    case 'pro':
      return t('admin.plan_operator_note_pro', {}, fallback || 'Core capabilities stay available across packages. Basic expands points, concurrency, batch headroom, and grace before operator intervention.');
    case 'agency':
      return t('admin.plan_operator_note_agency', {}, fallback || 'Core capabilities stay available across packages. Bulk provides the highest points budget, concurrency, batch headroom, and policy headroom.');
    default:
      return fallback || '';
  }
}

export function localizeFeatureGroup(t: TranslateFn, feature: string): string {
  switch (feature) {
    case 'Hosted runtime baseline':
      return t('admin.plan_feature_hosted_runtime_baseline', {}, feature);
    case 'Portal usage visibility':
      return t('admin.plan_feature_portal_usage_visibility', {}, feature);
    case 'Operator-managed subscription changes':
      return t('admin.plan_feature_operator_managed_subscription_changes', {}, feature);
    case 'Hosted runtime + workflow coverage':
      return t('admin.plan_feature_hosted_runtime_workflow_coverage', {}, feature);
    case 'Automation-heavy usage':
      return t('admin.plan_feature_automation_heavy_usage', {}, feature);
    case 'Operator-led budget follow-up':
      return t('admin.plan_feature_operator_led_budget_follow_up', {}, feature);
    case 'Higher hosted concurrency':
      return t('admin.plan_feature_higher_hosted_concurrency', {}, feature);
    case 'Multi-site commercial headroom':
      return t('admin.plan_feature_multi_site_commercial_headroom', {}, feature);
    case 'Sustained workflow and automation operations':
      return t('admin.plan_feature_sustained_workflow_automation_operations', {}, feature);
    default:
      return feature;
  }
}

export function localizePlanName(t: TranslateFn, planId: string, name: string): string {
  if (planId === 'plan_free' || name === 'Free') {
    return t('admin.plan_name_free', {}, name || 'Free');
  }
  if (planId === 'plan_dev_unlimited' || name === 'Development Unlimited') {
    return t('admin.plan_name_development_unlimited', {}, name);
  }
  if (name === 'Magick Cloud MVP Plan') {
    return t('admin.plan_name_magick_cloud_mvp', {}, name);
  }
  return name;
}

export function resolveAdminPackageLabel(
  t: TranslateFn,
  {
    planId,
    packageAlias,
    fallback,
  }: {
    planId?: string;
    packageAlias?: string;
    fallback?: string;
  }
): string {
  const raw = `${planId || ''} ${packageAlias || ''} ${fallback || ''}`.toLowerCase();
  if (raw.includes('bulk') || raw.includes('agency')) {
    return localizePackageAlias(t, 'agency', fallback || packageAlias || 'Bulk');
  }
  if (raw.includes('basic') || raw.includes('pro')) {
    return localizePackageAlias(t, 'pro', fallback || packageAlias || 'Basic');
  }
  if (raw.includes('free') || raw.includes('starter') || raw.includes('plan_free')) {
    return localizePackageAlias(t, 'starter', fallback || packageAlias || 'Free');
  }
  return fallback || packageAlias || planId || '';
}

export function localizePackageFitCue(
  t: TranslateFn,
  cue: { code: string; title: string; detail: string }
): { title: string; detail: string } {
  switch (cue.code) {
    case 'package_fit.within_band':
      return {
        title: t('admin.package_fit.within_band_title', {}, cue.title),
        detail: t('admin.package_fit.within_band_detail', {}, cue.detail),
      };
    case 'package_fit.shadow_cost_over_budget':
      return {
        title: t('admin.package_fit.shadow_cost_over_budget_title', {}, cue.title),
        detail: t('admin.package_fit.shadow_cost_over_budget_detail', {}, cue.detail),
      };
    case 'package_fit.shadow_cost_headroom_high':
      return {
        title: t('admin.package_fit.shadow_cost_headroom_high_title', {}, cue.title),
        detail: t('admin.package_fit.shadow_cost_headroom_high_detail', {}, cue.detail),
      };
    case 'package_fit.shadow_tokens_over_budget':
      return {
        title: t('admin.package_fit.shadow_tokens_over_budget_title', {}, cue.title),
        detail: t('admin.package_fit.shadow_tokens_over_budget_detail', {}, cue.detail),
      };
    case 'package_fit.shadow_runs_over_budget':
      return {
        title: t('admin.package_fit.shadow_runs_over_budget_title', {}, cue.title),
        detail: t('admin.package_fit.shadow_runs_over_budget_detail', {}, cue.detail),
      };
    default:
      return cue;
  }
}
