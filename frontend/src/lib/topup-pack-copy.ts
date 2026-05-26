type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

type TopUpField = 'label' | 'pointsLabel' | 'operatorNote';

type TopUpCopy = {
  label: string;
  pointsLabel: string;
  operatorNote: string;
};

const TOPUP_PACK_COPY: Record<string, TopUpCopy> = {
  pack_small: {
    label: 'Small pack',
    pointsLabel: '10,000 points equivalent',
    operatorNote:
      'Use when the current billing period needs basic-tier-sized budget headroom without rebinding the subscription.',
  },
  pack_medium: {
    label: 'Medium pack',
    pointsLabel: '35,000 points equivalent',
    operatorNote:
      'Use when sustained workflow pressure needs materially higher current-period headroom before a package review.',
  },
  pack_large: {
    label: 'Large pack',
    pointsLabel: '150,000 points equivalent',
    operatorNote:
      'Use when an operator needs a high-headroom current-period top-up without introducing a wallet or self-serve flow.',
  },
};

function getCanonicalTopUpCopy(packId: string): TopUpCopy | null {
  return TOPUP_PACK_COPY[packId] || null;
}

function getLocalizedFieldKey(packId: string, field: TopUpField): string | null {
  switch (packId) {
    case 'pack_small':
      return field === 'label'
        ? 'admin.topup_pack_label_small'
        : field === 'pointsLabel'
        ? 'admin.topup_pack_points_small'
        : 'admin.topup_pack_note_small';
    case 'pack_medium':
      return field === 'label'
        ? 'admin.topup_pack_label_medium'
        : field === 'pointsLabel'
        ? 'admin.topup_pack_points_medium'
        : 'admin.topup_pack_note_medium';
    case 'pack_large':
      return field === 'label'
        ? 'admin.topup_pack_label_large'
        : field === 'pointsLabel'
        ? 'admin.topup_pack_points_large'
        : 'admin.topup_pack_note_large';
    default:
      return null;
  }
}

function isCanonicalTopUpField(packId: string, field: TopUpField, value: string | null | undefined): boolean {
  const canonical = getCanonicalTopUpCopy(packId);
  const normalized = String(value || '').trim();
  if (!canonical) {
    return false;
  }
  if (!normalized) {
    return true;
  }
  if (field === 'label') {
    return normalized === canonical.label;
  }
  if (field === 'pointsLabel') {
    return normalized === canonical.pointsLabel;
  }
  return normalized === canonical.operatorNote;
}

function localizeCanonicalTopUpField(t: TranslateFn, packId: string, field: TopUpField, fallback?: string): string {
  const canonical = getCanonicalTopUpCopy(packId);
  const key = getLocalizedFieldKey(packId, field);
  if (!canonical || !key) {
    return fallback || '';
  }
  if (field === 'label') {
    return t(key, {}, fallback || canonical.label);
  }
  if (field === 'pointsLabel') {
    return t(key, {}, fallback || canonical.pointsLabel);
  }
  return t(key, {}, fallback || canonical.operatorNote);
}

export function localizeTopUpPackLabel(t: TranslateFn, packId: string | null | undefined, rawValue?: string | null): string {
  const normalizedPackId = String(packId || '').trim();
  const fallback = String(rawValue || '').trim() || normalizedPackId;
  if (!normalizedPackId || !isCanonicalTopUpField(normalizedPackId, 'label', rawValue)) {
    return fallback;
  }
  return localizeCanonicalTopUpField(t, normalizedPackId, 'label', fallback);
}

export function localizeTopUpPackPointsLabel(t: TranslateFn, packId: string | null | undefined, rawValue?: string | null): string {
  const normalizedPackId = String(packId || '').trim();
  const fallback = String(rawValue || '').trim();
  if (!normalizedPackId || !isCanonicalTopUpField(normalizedPackId, 'pointsLabel', rawValue)) {
    return fallback;
  }
  return localizeCanonicalTopUpField(t, normalizedPackId, 'pointsLabel', fallback);
}

export function localizeTopUpPackOperatorNote(t: TranslateFn, packId: string | null | undefined, rawValue?: string | null): string {
  const normalizedPackId = String(packId || '').trim();
  const fallback = String(rawValue || '').trim();
  if (!normalizedPackId || !isCanonicalTopUpField(normalizedPackId, 'operatorNote', rawValue)) {
    return fallback;
  }
  return localizeCanonicalTopUpField(t, normalizedPackId, 'operatorNote', fallback);
}

export function localizeTopUpTierLabel(t: TranslateFn, tierId: string): string {
  switch (tierId) {
    case 'starter':
      return t('admin.plan_package_alias_starter', {}, 'Free');
    case 'pro':
      return t('admin.plan_package_alias_pro', {}, 'Basic');
    case 'agency':
      return t('admin.plan_package_alias_agency', {}, 'Bulk');
    default:
      return tierId;
  }
}

export function canonicalizeTopUpPackFieldForSave(
  t: TranslateFn,
  packId: string | null | undefined,
  field: TopUpField,
  value?: string | null
): string {
  const normalizedPackId = String(packId || '').trim();
  const normalizedValue = String(value || '').trim();
  const canonical = getCanonicalTopUpCopy(normalizedPackId);
  if (!canonical || !normalizedValue) {
    return normalizedValue;
  }

  const localized = localizeCanonicalTopUpField(t, normalizedPackId, field);
  if (normalizedValue !== localized) {
    return normalizedValue;
  }

  if (field === 'label') {
    return canonical.label;
  }
  if (field === 'pointsLabel') {
    return canonical.pointsLabel;
  }
  return canonical.operatorNote;
}
