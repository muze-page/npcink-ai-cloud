'use client';

import Link from 'next/link';
import { useState } from 'react';
import { BackofficeIdentifier } from '@/components/backoffice/BackofficeIdentifier';
import { BackofficeStackCard } from '@/components/backoffice/BackofficeScaffold';
import { useLocale } from '@/contexts/LocaleContext';

export type AdminMutationReceiptPayload = {
  audit_event_id?: number;
  event_kind: string;
  scope_kind: string;
  scope_id: string;
  outcome: string;
  effective_summary: string;
  audit_filters?: Record<string, string>;
};

export function buildAdminAuditTrailHref(
  receipt: AdminMutationReceiptPayload | null | undefined
): string {
  if (!receipt?.audit_filters) {
    return '/api/admin/audit-events?limit=20';
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(receipt.audit_filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  if (!params.has('limit')) {
    params.set('limit', '20');
  }
  return `/api/admin/audit-events?${params.toString()}`;
}

export function buildAdminMutationReceiptText(receipt: AdminMutationReceiptPayload): string {
  const lines = [
    `event_kind: ${receipt.event_kind}`,
    `outcome: ${receipt.outcome}`,
    `scope_kind: ${receipt.scope_kind}`,
    `scope_id: ${receipt.scope_id}`,
    `summary: ${receipt.effective_summary}`,
  ];
  if (receipt.audit_event_id) {
    lines.push(`audit_event_id: ${receipt.audit_event_id}`);
  }
  return lines.join('\n');
}

export function AdminMutationReceipt({
  receipt,
  title,
}: {
  receipt: AdminMutationReceiptPayload | null | undefined;
  title?: string;
}) {
  const { t } = useLocale();
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');

  if (!receipt) {
    return null;
  }

  async function copyReceipt() {
    if (!receipt) {
      return;
    }
    try {
      await navigator.clipboard.writeText(buildAdminMutationReceiptText(receipt));
      setCopyState('copied');
      window.setTimeout(() => setCopyState('idle'), 1800);
    } catch {
      setCopyState('failed');
    }
  }

  return (
    <BackofficeStackCard className="border-emerald-200 bg-emerald-50/80 dark:border-emerald-900/50 dark:bg-emerald-950/20">
      <p className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-emerald-700 dark:text-emerald-300">
        {title || t('admin.receipt_latest', {}, 'Latest receipt')}
      </p>
      <p className="mt-2 text-sm font-semibold text-slate-950 dark:text-white">
        {receipt.effective_summary}
      </p>
      <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-600 dark:text-slate-300">
        <span>{receipt.event_kind}</span>
        <span>·</span>
        <span>{receipt.outcome}</span>
        <span>·</span>
        <BackofficeIdentifier
          value={receipt.scope_id}
          className="inline text-xs text-slate-600 dark:text-slate-300"
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
        <button
          type="button"
          className="font-medium text-blue-600 hover:underline dark:text-blue-300"
          onClick={() => void copyReceipt()}
        >
          {copyState === 'copied'
            ? t('admin.receipt_copied', {}, 'Receipt copied')
            : copyState === 'failed'
              ? t('admin.receipt_copy_failed', {}, 'Copy failed')
              : t('admin.receipt_copy', {}, 'Copy receipt')}
        </button>
        <Link
          href={buildAdminAuditTrailHref(receipt)}
          className="font-medium text-blue-600 hover:underline dark:text-blue-300"
          target="_blank"
          rel="noreferrer"
        >
          {t('admin.receipt_view_audit', {}, 'View audit trail')}
        </Link>
        {receipt.audit_event_id ? (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {t('admin.receipt_audit_event', { id: String(receipt.audit_event_id) }, 'Audit event #{{id}}')}
          </span>
        ) : null}
      </div>
    </BackofficeStackCard>
  );
}
