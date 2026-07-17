'use client';

import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeEmptyState,
  BackofficeLayer,
  BackofficePageStack,
  BackofficeSectionPanel,
  BackofficeSummaryStrip,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { Modal } from '@/components/ui/Modal';
import { useToast } from '@/components/ui/Toast';
import { useLocale } from '@/contexts/LocaleContext';
import { createApiClient } from '@/lib/api-client';
import { ADMIN_CURRENCY } from '@/lib/currency';
import { resolveUiErrorMessage } from '@/lib/errors';
import { cn, formatDate, formatNumber } from '@/lib/utils';

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

type PackStatusFilter = 'all' | 'active' | 'inactive';

const MANAGED_TIERS = ['free', 'plus', 'pro', 'agency'] as const;
const creditPacksClient = createApiClient({ idempotencyPrefix: 'admin_credit_packs' });

function normalizeItem(item: CreditPackItem): CreditPackItem {
  return {
    ...item,
    ai_credits: Math.max(1, Number(item.ai_credits || 0)),
    amount: Math.max(0.01, Number(item.amount || 0)),
    validity_days: Math.max(1, Number(item.validity_days || 365)),
    currency: ADMIN_CURRENCY,
    recommended_for_tiers: Array.isArray(item.recommended_for_tiers) ? item.recommended_for_tiers : [],
    active: Boolean(item.active),
  };
}

function normalizeStatusFilter(value: string | null): PackStatusFilter {
  return value === 'active' || value === 'inactive' ? value : 'all';
}

function formatPackAmount(item: CreditPackItem): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: ADMIN_CURRENCY,
    minimumFractionDigits: 2,
  }).format(item.amount);
}

async function fetchCatalog(): Promise<CreditPackCatalogPayload> {
  return (await creditPacksClient.request<CreditPackCatalogPayload>('/api/admin/credit-packs')).data;
}

async function saveCatalog(items: CreditPackItem[]): Promise<CreditPackCatalogPayload> {
  return (await creditPacksClient.request<CreditPackCatalogPayload>('/api/admin/credit-packs', {
    method: 'PATCH',
    body: { items },
  })).data;
}

export default function AdminCreditPacksPage() {
  const { t } = useLocale();
  const toast = useToast();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const statusFilter = normalizeStatusFilter(searchParams.get('status'));
  const focusedPackId = searchParams.get('focus') || '';
  const [catalog, setCatalog] = useState<CreditPackCatalogPayload | null>(null);
  const [items, setItems] = useState<CreditPackItem[]>([]);
  const [draft, setDraft] = useState<CreditPackItem | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadedAt, setLoadedAt] = useState<Date | null>(null);
  const requestActiveRef = useRef(false);
  const requestSequenceRef = useRef(0);
  const hasLoadedRef = useRef(false);

  const updateCatalogUrl = useCallback((updates: { status?: PackStatusFilter | null; focus?: string | null }) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(updates).forEach(([key, value]) => {
      if (value && value !== 'all') params.set(key, value);
      else params.delete(key);
    });
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);

  const loadCatalog = useCallback(async (refresh = false) => {
    if (requestActiveRef.current) return;
    requestActiveRef.current = true;
    const sequence = ++requestSequenceRef.current;
    if (refresh || hasLoadedRef.current) setIsRefreshing(true);
    else setIsLoading(true);
    setError(null);
    try {
      const payload = await fetchCatalog();
      if (sequence !== requestSequenceRef.current) return;
      setCatalog(payload);
      setItems((payload.items || []).map(normalizeItem));
      setLoadedAt(new Date());
      hasLoadedRef.current = true;
    } catch (err) {
      if (sequence !== requestSequenceRef.current) return;
      setError(resolveUiErrorMessage(err, t('error.failed_load')));
    } finally {
      if (sequence === requestSequenceRef.current) {
        requestActiveRef.current = false;
        setIsLoading(false);
        setIsRefreshing(false);
      }
    }
  }, [t]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  const activeCount = useMemo(() => items.filter((item) => item.active).length, [items]);
  const defaultValidityDays = Number(catalog?.default_validity_days || 365);
  const filteredItems = useMemo(
    () => items.filter((item) => statusFilter === 'all' || (statusFilter === 'active' ? item.active : !item.active)),
    [items, statusFilter]
  );
  const selectedItem = filteredItems.find((item) => item.pack_id === focusedPackId) || filteredItems[0] || null;
  const savedItemForDraft = draft ? items.find((item) => item.pack_id === draft.pack_id) || null : null;
  const isDraftDirty = Boolean(draft && savedItemForDraft && JSON.stringify(normalizeItem(draft)) !== JSON.stringify(normalizeItem(savedItemForDraft)));

  const openEditor = (item: CreditPackItem) => {
    setError(null);
    setDraft(normalizeItem({ ...item, recommended_for_tiers: [...item.recommended_for_tiers] }));
  };

  const closeEditor = () => {
    if (!isSaving) setDraft(null);
  };

  const toggleDraftTier = (tier: string) => {
    setDraft((current) => {
      if (!current) return current;
      const tiers = new Set(current.recommended_for_tiers);
      if (tiers.has(tier)) tiers.delete(tier);
      else tiers.add(tier);
      return normalizeItem({ ...current, recommended_for_tiers: Array.from(tiers) });
    });
  };

  const handleSaveDraft = async () => {
    if (!draft || !isDraftDirty) return;
    setIsSaving(true);
    setError(null);
    try {
      const nextItems = items.map((item) => item.pack_id === draft.pack_id ? normalizeItem(draft) : normalizeItem(item));
      const payload = await saveCatalog(nextItems);
      setCatalog(payload);
      setItems((payload.items || []).map(normalizeItem));
      setLoadedAt(new Date());
      setDraft(null);
      toast.success(
        t('admin.credit_packs_saved_notice', {}, 'Credit pack catalog saved.'),
        t('admin.credit_packs_saved_title', {}, 'Credit pack updated')
      );
    } catch (err) {
      setError(resolveUiErrorMessage(err, t('error.failed_save')));
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading && !catalog) return <LoadingFallback />;

  if (!catalog && !isLoading) {
    return (
      <BackofficePageStack>
        <BackofficeEmptyState
          title={t('admin.credit_packs_unavailable_title', {}, 'Credit pack catalog unavailable')}
          description={error || t('error.failed_load')}
          action={<button type="button" className="btn btn-primary" onClick={() => void loadCatalog(true)}>{t('common.retry')}</button>}
        />
      </BackofficePageStack>
    );
  }

  return (
    <BackofficePageStack className="space-y-5">
      <BackofficeLayer
        eyebrow={t('admin.credit_packs_eyebrow', {}, 'Commercial catalog')}
        title={t('admin.credit_packs_title', {}, 'Credit packs')}
        description={t(
          'admin.credit_packs_directory_desc',
          {},
          'Review the customer purchase catalog first. Edit one pack only when price, credits, validity, visibility, or package fit must change.'
        )}
        actions={(
          <>
            <button type="button" className="btn btn-secondary" onClick={() => void loadCatalog(true)} disabled={isRefreshing || isSaving}>
              {isRefreshing ? t('common.loading', {}, 'Loading...') : t('common.refresh', {}, 'Refresh')}
            </button>
            <Link href="/admin/plans" className="btn btn-secondary">{t('admin.credit_packs_open_packages', {}, 'Open package catalog')}</Link>
          </>
        )}
      />

      {error ? (
        <div role="alert" className="flex flex-col gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200 sm:flex-row sm:items-center sm:justify-between">
          <span>{error}{items.length > 0 ? <span className="mt-1 block text-xs">{t('admin.credit_packs_retained_notice', {}, 'Showing the last successfully loaded credit pack catalog.')}</span> : null}</span>
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => void loadCatalog(true)}>{t('common.retry')}</button>
        </div>
      ) : null}

      <BackofficeSummaryStrip items={[
        { label: t('admin.credit_packs_active_count', {}, 'Active packs'), value: `${activeCount}/${items.length}` },
        { label: t('admin.credit_packs_default_validity', {}, 'Default validity'), value: t('admin.credit_packs_validity_days_value', { days: String(defaultValidityDays) }, `${defaultValidityDays} days`) },
        { label: t('admin.credit_packs_expiry_policy', {}, 'Expiry policy'), value: t('admin.credit_packs_expiry_policy_value', {}, 'Purchase time + validity') },
        { label: t('common.updated_at', {}, 'Updated'), value: loadedAt ? formatDate(loadedAt.toISOString()) : t('common.unknown', {}, 'Unknown') },
      ]} />

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(19rem,0.72fr)]">
        <BackofficeSectionPanel className="overflow-hidden p-0">
          <div className="space-y-4 border-b border-slate-200/80 px-5 py-5 dark:border-slate-800 md:px-6">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <h2 className="text-xl font-semibold text-slate-950 dark:text-white">{t('admin.credit_packs_directory_title', {}, 'Credit pack catalog')}</h2>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t('admin.credit_packs_directory_hint', {}, 'Compare purchase value and visibility, then inspect one pack before editing.')}</p>
              </div>
              <p role="status" className="text-sm font-medium text-slate-500 dark:text-slate-400">{t('admin.credit_packs_result_count', { visible: String(filteredItems.length), total: String(items.length) }, '{{visible}} visible · {{total}} total')}</p>
            </div>
            <div className="flex flex-wrap gap-2" aria-label={t('admin.credit_packs_status_filter', {}, 'Pack visibility')}>
              {(['all', 'active', 'inactive'] as PackStatusFilter[]).map((status) => (
                <button
                  key={status}
                  type="button"
                  aria-pressed={statusFilter === status}
                  className={cn(
                    'cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium transition',
                    statusFilter === status
                      ? 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200'
                      : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600'
                  )}
                  onClick={() => updateCatalogUrl({ status, focus: null })}
                >
                  {status === 'all' ? t('common.all', {}, 'All') : status === 'active' ? t('common.active', {}, 'Active') : t('common.inactive', {}, 'Inactive')}
                </button>
              ))}
            </div>
          </div>

          {filteredItems.length ? (
            <div role="list" aria-label={t('admin.credit_packs_list_label', {}, 'Credit pack list')}>
              {filteredItems.map((item) => {
                const selected = selectedItem?.pack_id === item.pack_id;
                return (
                  <article key={item.pack_id} role="listitem" data-ui="credit-pack-directory-item" data-pack-id={item.pack_id} className={cn('border-b border-slate-200/80 last:border-b-0 dark:border-slate-800', selected ? 'bg-blue-50/65 dark:bg-blue-950/15' : 'hover:bg-slate-50/70 dark:hover:bg-slate-950/35')}>
                    <button type="button" aria-pressed={selected} className="grid w-full cursor-pointer gap-3 px-5 py-4 text-left transition md:grid-cols-[minmax(11rem,1fr)_minmax(8rem,0.6fr)_minmax(8rem,0.7fr)_auto] md:items-center md:px-6" onClick={() => updateCatalogUrl({ focus: item.pack_id })}>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2"><span className="truncate font-semibold text-slate-950 dark:text-white">{item.label}</span><BackofficeStatusBadge status={item.active ? 'published' : 'draft'} label={t(item.active ? 'common.active' : 'common.inactive', {}, item.active ? 'Active' : 'Inactive')} /></div>
                        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{item.pack_id}</p>
                      </div>
                      <div><p className="text-xs text-slate-500 dark:text-slate-400">{t('admin.credit_packs_amount_label', {}, 'Amount')}</p><p className="mt-1 font-semibold text-slate-900 dark:text-white">{formatPackAmount(item)}</p></div>
                      <div><p className="text-xs text-slate-500 dark:text-slate-400">{t('admin.credit_packs_credits_label', {}, 'Credits')}</p><p className="mt-1 font-semibold text-slate-900 dark:text-white">{formatNumber(item.ai_credits)}</p></div>
                      <div className="flex flex-wrap gap-1.5 md:justify-end">{item.recommended_for_tiers.map((tier) => <span key={tier} className="rounded-full border border-slate-200 px-2 py-0.5 text-xs font-medium text-slate-600 dark:border-slate-700 dark:text-slate-300">{tier}</span>)}</div>
                    </button>
                  </article>
                );
              })}
            </div>
          ) : (
            <BackofficeEmptyState title={t('admin.credit_packs_empty_title', {}, 'No packs in this view')} description={t('admin.credit_packs_empty_desc', {}, 'Clear the visibility filter to inspect the full catalog.')} />
          )}
        </BackofficeSectionPanel>

        <aside id="credit-pack-inspector" className="xl:sticky xl:top-24" aria-live="polite">
          <BackofficeSectionPanel className="space-y-5">
            <div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">{t('admin.credit_packs_inspector_eyebrow', {}, 'Selected pack')}</p><h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{selectedItem?.label || t('admin.credit_packs_inspector_empty', {}, 'No pack selected')}</h2>{selectedItem ? <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{selectedItem.pack_id}</p> : null}</div>
            {selectedItem ? (
              <>
                <dl className="grid gap-2 text-sm">
                  {[
                    [t('common.status'), t(selectedItem.active ? 'common.active' : 'common.inactive', {}, selectedItem.active ? 'Active' : 'Inactive')],
                    [t('admin.credit_packs_amount_label', {}, 'Amount'), formatPackAmount(selectedItem)],
                    [t('admin.credit_packs_credits_label', {}, 'Credits'), formatNumber(selectedItem.ai_credits)],
                    [t('admin.credit_packs_validity_label', {}, 'Validity'), t('admin.credit_packs_validity_days_value', { days: String(selectedItem.validity_days) }, `${selectedItem.validity_days} days`)],
                    [t('admin.credit_packs_recommended_tiers_label', {}, 'Recommended'), selectedItem.recommended_for_tiers.join(' · ') || t('admin.credit_packs_no_recommended_tiers', {}, 'None')],
                  ].map(([label, value]) => <div key={label} className="flex justify-between gap-4 border-b border-slate-200/70 pb-2 last:border-b-0 dark:border-slate-800"><dt className="text-slate-500 dark:text-slate-400">{label}</dt><dd className="text-right font-semibold text-slate-950 dark:text-white">{value}</dd></div>)}
                </dl>
                <button type="button" className="btn btn-primary w-full" onClick={() => openEditor(selectedItem)}>{t('admin.credit_packs_edit_action', {}, 'Edit selected pack')}</button>
                <p className="border-t border-slate-200 pt-4 text-xs leading-5 text-slate-500 dark:border-slate-800 dark:text-slate-400">{t('admin.credit_packs_inspector_boundary', {}, 'Changes update the Cloud purchase catalog only. Existing payment orders keep their purchase-time snapshot; package entitlement and WordPress control do not change here.')}</p>
              </>
            ) : null}
          </BackofficeSectionPanel>
        </aside>
      </div>

      <Modal
        isOpen={Boolean(draft)}
        onClose={closeEditor}
        size="lg"
        title={draft ? t('admin.credit_packs_edit_title', { name: draft.label }, 'Edit {{name}}') : undefined}
        description={t('admin.credit_packs_edit_desc', {}, 'Save one pack at a time. The service still validates and stores the complete catalog atomically.')}
        closeOnOverlay={!isSaving}
        footer={(
          <>
            <button type="button" className="btn btn-secondary" disabled={isSaving} onClick={closeEditor}>{t('common.cancel', {}, 'Cancel')}</button>
            <button type="button" className="btn btn-primary" disabled={isSaving || !isDraftDirty} onClick={() => void handleSaveDraft()}>{isSaving ? t('common.saving', {}, 'Saving...') : t('admin.credit_packs_save_pack_action', {}, 'Save pack')}</button>
          </>
        )}
      >
        {draft ? (
          <div className="space-y-5">
            {error ? <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">{error}</div> : null}
            <label className="grid gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200"><span>{t('admin.credit_packs_pack_label', {}, 'Pack')}</span><input className="input w-full" value={draft.label} onChange={(event) => setDraft((current) => current ? { ...current, label: event.target.value } : current)} /></label>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200"><span>{t('admin.credit_packs_credits_label', {}, 'Credits')}</span><input className="input w-full" type="number" min={1} step={100} value={draft.ai_credits} onChange={(event) => setDraft((current) => current ? normalizeItem({ ...current, ai_credits: Number(event.target.value) }) : current)} /></label>
              <label className="grid gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200"><span>{t('admin.credit_packs_amount_label', {}, 'Amount')} · {t('admin.credit_packs_currency_fixed_cny', {}, 'RMB pricing')}</span><input className="input w-full" type="number" min={0.01} step={1} value={draft.amount} onChange={(event) => setDraft((current) => current ? normalizeItem({ ...current, amount: Number(event.target.value) }) : current)} /></label>
              <label className="grid gap-1.5 text-sm font-medium text-slate-700 dark:text-slate-200"><span>{t('admin.credit_packs_validity_label', {}, 'Validity')}</span><input className="input w-full" type="number" min={1} max={1095} step={1} value={draft.validity_days} onChange={(event) => setDraft((current) => current ? normalizeItem({ ...current, validity_days: Number(event.target.value) }) : current)} /></label>
              <label className="flex items-center gap-2 self-end rounded-xl border border-slate-200 px-3 py-2.5 text-sm font-medium text-slate-700 dark:border-slate-800 dark:text-slate-200"><input type="checkbox" checked={draft.active} onChange={(event) => setDraft((current) => current ? { ...current, active: event.target.checked } : current)} /><span>{t('admin.credit_packs_visibility_toggle', {}, 'Visible to customer package page')}</span></label>
            </div>
            <fieldset><legend className="text-sm font-medium text-slate-700 dark:text-slate-200">{t('admin.credit_packs_recommended_tiers_label', {}, 'Recommended')}</legend><div className="mt-2 flex flex-wrap gap-2">{MANAGED_TIERS.map((tier) => <label key={tier} className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-800 dark:bg-slate-950/50 dark:text-slate-200"><input type="checkbox" checked={draft.recommended_for_tiers.includes(tier)} onChange={() => toggleDraftTier(tier)} /><span>{tier}</span></label>)}</div></fieldset>
            <p className="text-xs leading-5 text-slate-500 dark:text-slate-400">{t('admin.credit_packs_edit_boundary', {}, 'This edit changes future customer purchases only. It does not rewrite existing payment orders, grant a stored balance, or change package entitlement.')}</p>
          </div>
        ) : null}
      </Modal>
    </BackofficePageStack>
  );
}
