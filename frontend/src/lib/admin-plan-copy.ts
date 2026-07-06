type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

export function localizeTierLabel(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'free':
      return t('admin.plan_tier_free', {}, fallback || 'Free');
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
    case 'free':
      return t('admin.plan_package_alias_free', {}, fallback || 'Free');
    case 'pro':
      return t('admin.plan_package_alias_pro', {}, fallback || 'Pro');
    case 'agency':
      return t('admin.plan_package_alias_agency', {}, fallback || 'Agency');
    default:
      return fallback || tierId;
  }
}

export function localizeUsageBand(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'free':
      return t('admin.plan_usage_band_free', {}, fallback || '300 AI credits per month.');
    case 'pro':
      return t('admin.plan_usage_band_pro', {}, fallback || '10,000 AI credits and 30 Pro Nightly Inspection runs per month.');
    case 'agency':
      return t('admin.plan_usage_band_agency', {}, fallback || '150,000 AI credits and 150 Pro Nightly Inspection runs per month.');
    default:
      return fallback || '';
  }
}

export function localizePositioning(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'free':
      return t('admin.plan_positioning_free', {}, fallback || 'Conservative single-site package with a small monthly AI credit grant and separate resource boundaries.');
    case 'pro':
      return t('admin.plan_positioning_pro', {}, fallback || 'Commercial Pro package with normal hosted AI consumption controlled by monthly AI credits and separate resource boundaries.');
    case 'agency':
      return t('admin.plan_positioning_agency', {}, fallback || 'Commercial Agency package for custom or multi-site Cloud runtime detail with higher AI credit, batch, and resource headroom.');
    default:
      return fallback || '';
  }
}

export function localizeOperatorNote(t: TranslateFn, tierId: string, fallback?: string): string {
  switch (tierId) {
    case 'free':
      return t('admin.plan_operator_note_free', {}, fallback || 'Free limits high-cost AI consumption through monthly AI credits while keeping ordinary Cloud service usage reviewable.');
    case 'pro':
      return t('admin.plan_operator_note_pro', {}, fallback || 'Pro keeps ordinary usage broadly available while high-cost AI search, query, and generation paths spend AI credits.');
    case 'agency':
      return t('admin.plan_operator_note_agency', {}, fallback || 'Agency represents custom/high-volume coverage; AI credits remain the primary high-cost consumption control.');
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
  if (planId === 'free' || name === 'Free') {
    return t('admin.plan_name_free', {}, name || 'Free');
  }
  if (name === 'Magick Cloud MVP Plan' || name === 'Npcink Cloud MVP Plan') {
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
  if (raw.includes('agency')) {
    return localizePackageAlias(t, 'agency', fallback || packageAlias || 'Agency');
  }
  if (raw.includes('pro')) {
    return localizePackageAlias(t, 'pro', fallback || packageAlias || 'Pro');
  }
  if (raw.includes('free')) {
    return localizePackageAlias(t, 'free', fallback || packageAlias || 'Free');
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
    case 'package_fit.cost_ceiling_missing':
      return {
        title: t('admin.package_fit.cost_ceiling_missing_title', {}, cue.title),
        detail: t('admin.package_fit.cost_ceiling_missing_detail', {}, cue.detail),
      };
    default:
      return cue;
  }
}
