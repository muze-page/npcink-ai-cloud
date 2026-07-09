'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeLayer,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { readResponsePayload } from '@/lib/safe-response';
import { formatNumber } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';
import { ADMIN_CURRENCY } from '@/lib/currency';

type CreditPackItem = {
  pack_id: string;
  label: string;
  ai_credits: number;
  amount: number;
  currency: string;
  recommended_for_tiers: string[];
  validity_days: number;
  active: boolean;
};

type CreditPackCatalogPayload = {
  catalog_version: string;
  period_policy: string;
  expiry_policy: string;
  default_validity_days: number;
  items: CreditPackItem[];
  updated_at?: string;
};

const MANAGED_TIERS = ['free', 'plus', 'pro', 'agency'] as const;

function normalizeItem(item: CreditPackItem): CreditPackItem {
  return {
    ...item,
    ai_credits: Math.max(1, Number(item.ai_credits || 0)),
    amount: Math.max(0.01, Number(item.amount || 0)),
    validity_days: Math.max(1, Number(item.validity_days || 365)),
    currency: ADMIN_CURRENCY,
    recommended_for_tiers: Array.isArray(item.recommended_for_tiers)
      ? item.recommended_for_tiers
      : [],
    active: Boolean(item.active),
  };
}

async function fetchCatalog(): Promise<Response> {
  return fetch('/api/admin/credit-packs', {
    credentials: 'include',
    cache: 'no-store',
  });
}

async function saveCatalog(items: CreditPackItem[]): Promise<Response> {
  return fetch('/api/admin/credit-packs', {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
  });
}

export default function AdminCreditPacksPage() {
  const { t } = useLocale();
  const [catalog, setCatalog] = useState<CreditPackCatalogPayload | null>(null);
  const [items, setItems] = useState<CreditPackItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadCatalog = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetchCatalog();
      const payload = await readResponsePayload<{ data?: CreditPackCatalogPayload; message?: string }>(response);
      if (!response.ok || !('data' in payload) || !payload.data) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
      }
      setCatalog(payload.data);
      setItems((payload.data.items || []).map(normalizeItem));
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const activeCount = useMemo(() => items.filter((item) => item.active).length, [items]);
  const defaultValidityDays = Number(catalog?.default_validity_days || 365);

  const updateItem = (packId: string, patch: Partial<CreditPackItem>) => {
    setItems((current) =>
      current.map((item) => (item.pack_id === packId ? normalizeItem({ ...item, ...patch }) : item))
    );
  };

  const toggleTier = (packId: string, tier: string) => {
    setItems((current) =>
      current.map((item) => {
        if (item.pack_id !== packId) {
          return item;
        }
        const tiers = new Set(item.recommended_for_tiers);
        if (tiers.has(tier)) {
          tiers.delete(tier);
        } else {
          tiers.add(tier);
        }
        return normalizeItem({ ...item, recommended_for_tiers: Array.from(tiers) });
      })
    );
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    setNotice(null);
    try {
      const response = await saveCatalog(items.map(normalizeItem));
      const payload = await readResponsePayload<{ data?: CreditPackCatalogPayload; message?: string }>(response);
      if (!response.ok || !('data' in payload) || !payload.data) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_save')));
      }
      setCatalog(payload.data);
      setItems((payload.data.items || []).map(normalizeItem));
      setNotice(t('admin.credit_packs_saved_notice', {}, 'Credit pack catalog saved.'));
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return <LoadingFallback />;
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.credit_packs_eyebrow', {}, 'Commercial catalog')}
        title={t('admin.credit_packs_title', {}, 'Credit packs')}
        description={t(
          'admin.credit_packs_desc',
          {},
          'Manage the Cloud credit pack catalog used by customer payment orders. Existing orders keep their purchase-time snapshot.'
        )}
        aside={<BackofficeStatusBadge status="ok" label={t('admin.cloud_owned_runtime_detail', {}, 'Cloud-owned detail')} />}
        actions={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => void loadCatalog()} disabled={isSaving}>
              {t('common.refresh', {}, 'Refresh')}
            </button>
            <button type="button" className="btn btn-primary" onClick={() => void handleSave()} disabled={isSaving}>
              {isSaving ? t('common.saving', {}, 'Saving...') : t('common.save', {}, 'Save')}
            </button>
          </>
        }
        summary={
          <BackofficeMetricStrip
            columnsClassName="md:grid-cols-3"
            items={[
              {
                label: t('admin.credit_packs_active_count', {}, 'Active packs'),
                value: `${activeCount}/${items.length}`,
              },
              {
                label: t('admin.credit_packs_default_validity', {}, 'Default validity'),
                value: t('admin.credit_packs_validity_days_value', { days: String(defaultValidityDays) }, `${defaultValidityDays} days`),
              },
              {
                label: t('admin.credit_packs_expiry_policy', {}, 'Expiry policy'),
                value: catalog?.expiry_policy || 'paid_at_plus_validity_days',
                size: 'compact',
              },
            ]}
          />
        }
      />

      {error ? (
        <BackofficeSectionPanel className="border-red-200 bg-red-50 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/25 dark:text-red-200">
          {error}
        </BackofficeSectionPanel>
      ) : null}
      {notice ? (
        <BackofficeSectionPanel className="border-emerald-200 bg-emerald-50 text-sm text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200">
          {notice}
        </BackofficeSectionPanel>
      ) : null}

      <BackofficeLayer
        title={t('admin.credit_packs_catalog_title', {}, 'Managed packs')}
        description={t(
          'admin.credit_packs_catalog_desc',
          {},
          'Edit RMB price, included credits, one-year validity, visibility, and recommended package fit.'
        )}
      />

      <BackofficeSectionPanel className="overflow-x-auto">
        <div className="min-w-[980px] divide-y divide-slate-200 dark:divide-slate-800">
          <div className="grid grid-cols-[1.2fr_0.8fr_0.8fr_0.7fr_1.2fr_0.4fr] gap-3 px-2 pb-3 text-xs font-semibold uppercase tracking-[0.14em] text-slate-500 dark:text-slate-400">
            <span>{t('admin.credit_packs_pack_label', {}, 'Pack')}</span>
            <span>{t('admin.credit_packs_credits_label', {}, 'Credits')}</span>
            <span>{t('admin.credit_packs_amount_label', {}, 'Amount')}</span>
            <span>{t('admin.credit_packs_validity_label', {}, 'Validity')}</span>
            <span>{t('admin.credit_packs_recommended_tiers_label', {}, 'Recommended')}</span>
            <span>{t('common.status', {}, 'Status')}</span>
          </div>
          {items.map((item) => (
            <div
              key={item.pack_id}
              className="grid grid-cols-[1.2fr_0.8fr_0.8fr_0.7fr_1.2fr_0.4fr] gap-3 px-2 py-4 text-sm"
            >
              <label className="space-y-1">
                <span className="block text-xs text-slate-500 dark:text-slate-400">{item.pack_id}</span>
                <input
                  className="input w-full"
                  value={item.label}
                  onChange={(event) => updateItem(item.pack_id, { label: event.target.value })}
                />
              </label>
              <label className="space-y-1">
                <span className="block text-xs text-slate-500 dark:text-slate-400">
                  {formatNumber(item.ai_credits)}
                </span>
                <input
                  className="input w-full"
                  type="number"
                  min={1}
                  step={100}
                  value={item.ai_credits}
                  onChange={(event) => updateItem(item.pack_id, { ai_credits: Number(event.target.value) })}
                />
              </label>
              <label className="space-y-1">
                <span className="block text-xs text-slate-500 dark:text-slate-400">
                  {t('admin.credit_packs_currency_fixed_cny', {}, 'RMB pricing')}
                </span>
                <input
                  className="input w-full"
                  type="number"
                  min={0.01}
                  step={1}
                  value={item.amount}
                  onChange={(event) => updateItem(item.pack_id, { amount: Number(event.target.value) })}
                />
              </label>
              <label className="space-y-1">
                <span className="block text-xs text-slate-500 dark:text-slate-400">
                  {t('admin.credit_packs_validity_days_value', { days: String(item.validity_days) }, `${item.validity_days} days`)}
                </span>
                <input
                  className="input w-full"
                  type="number"
                  min={1}
                  max={1095}
                  step={1}
                  value={item.validity_days}
                  onChange={(event) => updateItem(item.pack_id, { validity_days: Number(event.target.value) })}
                />
              </label>
              <div className="flex flex-wrap gap-2">
                {MANAGED_TIERS.map((tier) => (
                  <label
                    key={tier}
                    className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-700 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-200"
                  >
                    <input
                      type="checkbox"
                      checked={item.recommended_for_tiers.includes(tier)}
                      onChange={() => toggleTier(item.pack_id, tier)}
                    />
                    <span>{tier}</span>
                  </label>
                ))}
              </div>
              <label className="inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                <input
                  type="checkbox"
                  checked={item.active}
                  onChange={(event) => updateItem(item.pack_id, { active: event.target.checked })}
                />
                <span>{t(item.active ? 'common.active' : 'common.inactive', {}, item.active ? 'Active' : 'Inactive')}</span>
              </label>
            </div>
          ))}
        </div>
      </BackofficeSectionPanel>
    </BackofficePageStack>
  );
}
