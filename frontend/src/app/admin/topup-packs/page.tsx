'use client';

import React, { Suspense, useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStatusBadge } from '@/components/backoffice/BackofficeStatusBadge';
import {
  BackofficeLayer,
  BackofficeMetricStrip,
  BackofficePageStack,
  BackofficePrimaryPanel,
  BackofficeSectionPanel,
  BackofficeStackCard,
} from '@/components/backoffice/BackofficeScaffold';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { useLocale } from '@/contexts/LocaleContext';
import { formatAdminCurrency } from '@/lib/currency';
import { readResponsePayload } from '@/lib/safe-response';
import {
  canonicalizeTopUpPackFieldForSave,
  localizeTopUpPackLabel,
  localizeTopUpPackOperatorNote,
  localizeTopUpPackPointsLabel,
  localizeTopUpTierLabel,
} from '@/lib/topup-pack-copy';
import { cn, formatDate, formatNumber as formatInteger } from '@/lib/utils';
import { resolveUiErrorMessage } from '@/lib/errors';

type TopUpPack = {
  pack_id: string;
  label: string;
  points_label: string;
  runs_increment: number;
  tokens_increment: number;
  cost_increment: number;
  operator_note: string;
  recommended_for_tiers: string[];
  display_order: number;
  active: boolean;
  has_operator_overlay?: boolean;
  overlay_updated_at?: string | null;
};

type TopUpPackPayload = {
  items?: TopUpPack[];
  summary?: {
    total?: number;
    active?: number;
    inactive?: number;
  };
};

const ALLOWED_TIERS = ['starter', 'pro', 'agency'];

function normalizePayload(payload: unknown): TopUpPackPayload {
  const record = (payload || {}) as { data?: TopUpPackPayload } & TopUpPackPayload;
  return record.data || record || {};
}

function coerceNumber(value: FormDataEntryValue | null): number {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function TopUpPacksContent() {
  const { t } = useLocale();
  const [packs, setPacks] = useState<TopUpPack[]>([]);
  const [summary, setSummary] = useState<TopUpPackPayload['summary']>({});
  const [isLoading, setIsLoading] = useState(true);
  const [savingPackId, setSavingPackId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadPacks = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch('/api/admin/topup-packs', { credentials: 'include' });
      const payload = await readResponsePayload<TopUpPackPayload & { data?: TopUpPackPayload; message?: string }>(response);
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage('message' in payload ? payload.message : null, t('error.failed_load')));
      }
      const normalized = normalizePayload(payload);
      setPacks([...(normalized.items || [])].sort((a, b) => Number(a.display_order || 0) - Number(b.display_order || 0)));
      setSummary(normalized.summary || {});
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_load')));
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadPacks();
  }, [loadPacks]);

  const visibleSummary = useMemo(() => {
    const total = Number(summary?.total ?? packs.length);
    const active = Number(summary?.active ?? packs.filter((pack) => pack.active).length);
    const inactive = Number(summary?.inactive ?? Math.max(total - active, 0));
    return { total, active, inactive };
  }, [packs, summary]);

  const handleSavePack = async (event: React.FormEvent<HTMLFormElement>, pack: TopUpPack) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    setSavingPackId(pack.pack_id);
    setError(null);
    setNotice(null);

    const recommendedForTiers = ALLOWED_TIERS.filter((tier) => formData.get(`tier_${tier}`) === 'on');
    const payload = {
      label: canonicalizeTopUpPackFieldForSave(t, pack.pack_id, 'label', String(formData.get('label') || '')),
      points_label: canonicalizeTopUpPackFieldForSave(
        t,
        pack.pack_id,
        'pointsLabel',
        String(formData.get('points_label') || '')
      ),
      runs_increment: coerceNumber(formData.get('runs_increment')),
      tokens_increment: coerceNumber(formData.get('tokens_increment')),
      cost_increment: coerceNumber(formData.get('cost_increment')),
      operator_note: canonicalizeTopUpPackFieldForSave(
        t,
        pack.pack_id,
        'operatorNote',
        String(formData.get('operator_note') || '')
      ),
      recommended_for_tiers: recommendedForTiers,
      display_order: Math.max(1, Math.round(coerceNumber(formData.get('display_order')) || pack.display_order || 1)),
      active: formData.get('active') === 'on',
    };

    try {
      const response = await fetch(`/api/admin/topup-packs/${encodeURIComponent(pack.pack_id)}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const responsePayload = await readResponsePayload<{ message?: string }>(response);
      if (!response.ok) {
        throw new Error(resolveUiErrorMessage('message' in responsePayload ? responsePayload.message : null, t('error.failed_save')));
      }
      setNotice(t('admin.topup_packs_saved', {}, 'Top-up pack catalog updated.'));
      await loadPacks();
    } catch (err) {
      setError(resolveUiErrorMessage(err instanceof Error ? err.message : null, t('error.failed_save')));
    } finally {
      setSavingPackId(null);
    }
  };

  if (isLoading) {
    return <LoadingFallback />;
  }

  if (error && packs.length === 0) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="max-w-md text-center">
          <h2 className="mb-4 text-2xl font-bold text-red-600">{t('common.error')}</h2>
          <p className="mb-6 text-gray-600 dark:text-gray-400">{error}</p>
          <button type="button" onClick={() => void loadPacks()} className="btn btn-primary">
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <BackofficePageStack>
      <BackofficePrimaryPanel
        eyebrow={t('admin.nav_coverage', {}, 'Coverage')}
        title={t('admin.topup_pack_workspace_title', {}, 'Operator top-up pack catalog')}
        description={t(
          'admin.topup_pack_workspace_desc',
          {},
          'Maintain the three standard top-up packs used by operators in subscription details.'
        )}
        actions={
          <>
            <Link href="/admin/plans" className="btn btn-secondary">
              {t('common.package', {}, 'Package')}
            </Link>
            <Link href="/admin/subscriptions" className="btn btn-secondary">
              {t('common.subscriptions', {}, 'Subscriptions')}
            </Link>
          </>
        }
      />

      {error ? (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200">
          {error}
        </div>
      ) : null}
      {notice ? (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200">
          {notice}
        </div>
      ) : null}

      <BackofficeSectionPanel>
        <BackofficeMetricStrip
          items={[
            {
              label: t('admin.topup_pack_total', {}, 'Catalog packs'),
              value: formatInteger(visibleSummary.total),
              detail: t('admin.topup_pack_total_detail', {}, 'Only three standard top-up packs are managed here.'),
              size: 'compact',
            },
            {
              label: t('admin.topup_pack_active', {}, 'Active in operator catalog'),
              value: formatInteger(visibleSummary.active),
              size: 'compact',
            },
            {
              label: t('admin.topup_pack_workspace_scope', {}, 'Scope'),
              value: t('admin.topup_pack_workspace_kind', {}, 'Operator-only workspace'),
              detail: t('admin.topup_pack_workspace_not_storefront', {}, 'Not a storefront'),
              size: 'compact',
            },
          ]}
          columnsClassName="md:grid-cols-3 xl:grid-cols-3"
        />
      </BackofficeSectionPanel>

      <BackofficeLayer
        eyebrow={t('admin.topup_pack_workspace_shared_catalog', {}, 'Shared pack catalog')}
        title={t('admin.topup_pack_catalog_title', {}, 'Standard top-up packs')}
        description={t(
          'admin.topup_pack_catalog_desc',
          {},
          'Keep top-up packs bounded. Operators apply them from subscription details when a current period needs extra headroom.'
        )}
      />

      <div className="grid gap-4 xl:grid-cols-3">
        {packs.map((pack) => {
          const isSaving = savingPackId === pack.pack_id;
          const localizedLabel = localizeTopUpPackLabel(t, pack.pack_id, pack.label);
          const localizedPointsLabel = localizeTopUpPackPointsLabel(t, pack.pack_id, pack.points_label);
          const localizedOperatorNote = localizeTopUpPackOperatorNote(t, pack.pack_id, pack.operator_note);
          return (
            <BackofficeStackCard key={pack.pack_id} className="bg-white/80 dark:bg-slate-950/55">
              <form className="space-y-4" onSubmit={(event) => void handleSavePack(event, pack)}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                      {t('admin.topup_pack_standard', {}, 'Standard pack')}
                    </p>
                    <h2 className="mt-2 text-xl font-semibold text-slate-950 dark:text-white">{localizedLabel}</h2>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <BackofficeIdentifier value={pack.pack_id} />
                      <BackofficeStatusBadge
                        status={pack.active ? 'active' : 'inactive'}
                        label={pack.active ? t('status.active', {}, 'active') : t('status.inactive', {}, 'inactive')}
                      />
                    </div>
                  </div>
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-600 dark:text-slate-300">
                    <input name="active" type="checkbox" defaultChecked={pack.active} className="h-4 w-4 rounded border-slate-300" />
                    {t('common.enabled', {}, 'Enabled')}
                  </label>
                </div>

                <label className="block">
                  <span className="form-label">{t('common.label', {}, 'Label')}</span>
                  <input name="label" defaultValue={localizedLabel} className="form-input mt-1" />
                </label>
                <label className="block">
                  <span className="form-label">{t('admin.topup_pack_points_label', {}, 'Points label')}</span>
                  <input name="points_label" defaultValue={localizedPointsLabel} className="form-input mt-1" />
                </label>

                <div className="grid gap-3 sm:grid-cols-2">
                  <NumberField name="runs_increment" label={t('billing.runs', {}, 'Runs')} defaultValue={pack.runs_increment} />
                  <NumberField name="tokens_increment" label={t('common.tokens', {}, 'Tokens')} defaultValue={pack.tokens_increment} />
                  <NumberField name="cost_increment" label={t('common.cost', {}, 'Cost')} defaultValue={pack.cost_increment} step="0.01" />
                  <NumberField name="display_order" label={t('common.sort_order', {}, 'Sort order')} defaultValue={pack.display_order} />
                </div>

                <div>
                  <p className="form-label">{t('admin.topup_pack_recommended', {}, 'Recommended tiers')}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {ALLOWED_TIERS.map((tier) => (
                      <label
                        key={tier}
                        className={cn(
                          'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold',
                          'border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300'
                        )}
                      >
                        <input
                          name={`tier_${tier}`}
                          type="checkbox"
                          defaultChecked={(pack.recommended_for_tiers || []).includes(tier)}
                          className="h-3.5 w-3.5 rounded border-slate-300"
                        />
                        {localizeTopUpTierLabel(t, tier)}
                      </label>
                    ))}
                  </div>
                </div>

                <label className="block">
                  <span className="form-label">{t('admin.operator_notes', {}, 'Operator notes')}</span>
                  <textarea name="operator_note" defaultValue={localizedOperatorNote} className="form-textarea mt-1 min-h-24" />
                </label>

                <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-800">
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    {pack.has_operator_overlay
                      ? t(
                          'admin.topup_pack_overlay_state',
                          { updatedAt: pack.overlay_updated_at ? formatDate(pack.overlay_updated_at) : t('common.unknown') },
                          'Operator overlay is active.'
                        )
                      : t('admin.topup_pack_overlay_state_default', {}, 'This pack uses the default registry.')}
                  </p>
                  <button type="submit" className="btn btn-primary" disabled={isSaving}>
                    {isSaving ? t('common.saving') : t('common.save')}
                  </button>
                </div>
              </form>
            </BackofficeStackCard>
          );
        })}
      </div>
    </BackofficePageStack>
  );
}

function NumberField({
  name,
  label,
  defaultValue,
  step = '1',
}: {
  name: string;
  label: string;
  defaultValue: number;
  step?: string;
}) {
  return (
    <label className="block">
      <span className="form-label">{label}</span>
      <input name={name} type="number" min="0" step={step} defaultValue={Number(defaultValue || 0)} className="form-input mt-1" />
    </label>
  );
}

export default function TopUpPacksPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <TopUpPacksContent />
    </Suspense>
  );
}
