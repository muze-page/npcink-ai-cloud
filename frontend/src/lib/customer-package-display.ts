import { localizePackageAlias, localizePlanName } from './admin-plan-copy';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

export type PackageKind =
  | 'formal_free'
  | 'tier_package'
  | 'uncovered'
  | 'unknown';

export type CoverageState = 'covered' | 'uncovered';

export type CustomerPackageInput = {
  planId?: string;
  planVersionId?: string;
  packageAlias?: string;
  formalPlanName?: string;
  planKind?: string;
  packageKind?: string;
  coverageState?: string;
};

export function inferPlanIdFromPlanVersionId(planVersionId: string | null | undefined): string {
  const normalized = String(planVersionId || '').trim();
  if (!normalized) {
    return '';
  }

  return normalized
    .replace(/_v\d+$/i, '')
    .replace(/_primary_version$/i, '')
    .replace(/_version$/i, '');
}

function humanizePlanIdentifier(identifier: string): string {
  const normalized = String(identifier || '')
    .trim()
    .replace(/^plan_/i, '')
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ');

  if (!normalized) {
    return '';
  }

  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function resolveCustomerPackageDisplay(
  t: TranslateFn,
  input: CustomerPackageInput
): {
  display_package_label: string;
  package_kind: PackageKind;
  coverage_state: CoverageState;
} {
  const planVersionId = String(input.planVersionId || '').trim();
  const inferredPlanId = inferPlanIdFromPlanVersionId(planVersionId);
  const planId = String(input.planId || '').trim() || inferredPlanId;
  const packageAlias = String(input.packageAlias || '').trim();
  const formalPlanName = String(input.formalPlanName || '').trim();
  const explicitPlanKind = String(input.planKind || '').trim();
  const explicitPackageKind = normalizePackageKind(input.packageKind);
  const coverageState =
    String(input.coverageState || '').trim() === 'covered' ? 'covered' : 'uncovered';

  let packageKind: PackageKind = explicitPackageKind || 'unknown';
  if (!explicitPackageKind) {
    if (planId === 'free' || explicitPlanKind === 'default_free') {
      packageKind = 'formal_free';
    } else if (planId || planVersionId) {
      packageKind = 'tier_package';
    } else if (coverageState === 'uncovered') {
      packageKind = 'uncovered';
    }
  }

  if (packageKind === 'uncovered') {
    return {
      display_package_label: t('admin.package_label_uncovered', {}, 'Uncovered'),
      package_kind: packageKind,
      coverage_state: coverageState,
    };
  }
  if (packageKind === 'formal_free') {
    return {
      display_package_label:
        packageAlias || localizePackageAlias(t, 'free', localizePlanName(t, 'free', 'Free')),
      package_kind: packageKind,
      coverage_state: coverageState,
    };
  }
  if (packageKind === 'tier_package') {
    const fallbackName =
      humanizePlanIdentifier(planId) ||
      humanizePlanIdentifier(planVersionId) ||
      t('common.unknown', {}, 'Unknown');
    return {
      display_package_label:
        packageAlias ||
        (formalPlanName ? localizePlanName(t, planId, formalPlanName) : '') ||
        localizePlanName(t, planId, fallbackName),
      package_kind: packageKind,
      coverage_state: coverageState,
    };
  }
  const fallbackName =
    humanizePlanIdentifier(planId) ||
    humanizePlanIdentifier(planVersionId) ||
    t('common.unknown', {}, 'Unknown');
  return {
    display_package_label:
      packageAlias ||
      (formalPlanName ? localizePlanName(t, planId, formalPlanName) : '') ||
      localizePlanName(t, planId, fallbackName),
    package_kind: packageKind,
    coverage_state: coverageState,
  };
}

export function translatePackageKindLabel(
  t: TranslateFn,
  packageKind: PackageKind
): string {
  switch (packageKind) {
    case 'formal_free':
      return t('admin.plan_package_alias_free', {}, 'Free');
    case 'tier_package':
      return t('admin.tier_template_binding', {}, 'Standard package');
    case 'uncovered':
      return t('admin.package_label_uncovered', {}, 'Uncovered');
    default:
      return t('common.unknown', {}, 'Unknown');
  }
}

function normalizePackageKind(value: unknown): PackageKind | undefined {
  const normalized = String(value || '').trim();
  if (!normalized) {
    return undefined;
  }
  return normalized === 'formal_free' ||
    normalized === 'tier_package' ||
    normalized === 'uncovered' ||
    normalized === 'unknown'
    ? normalized
    : 'unknown';
}

export function translateCoverageStateLabel(
  t: TranslateFn,
  coverageState: CoverageState
): string {
  return coverageState === 'covered'
    ? t('admin.coverage_state_covered', {}, 'Covered')
    : t('admin.coverage_state_uncovered', {}, 'Uncovered');
}
