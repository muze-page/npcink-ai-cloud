'use client';

import { useLocale } from '@/contexts/LocaleContext';
import {
  formatPortalActionRequestResultSummary,
  formatPortalActionRequestStatusLabel,
} from '@/lib/portal-action-request-display';
import { cn } from '@/lib/utils';

type ActionRequestLike = {
  request_type?: string;
  status?: string;
  payload?: Record<string, unknown>;
};

type PortalActionRequestResultStripProps = {
  item: ActionRequestLike;
  className?: string;
};

function resolveTone(item: Pick<ActionRequestLike, 'status' | 'payload'>): 'pending' | 'success' | 'rejected' | 'neutral' {
  const decision = String(item.payload?.admin_decision || '');
  if (decision === 'reject' || item.status === 'canceled') {
    return 'rejected';
  }
  if (item.status === 'open' || item.status === 'acknowledged') {
    return 'pending';
  }
  if (item.payload?.application_result || item.status === 'resolved') {
    return 'success';
  }
  return 'neutral';
}

export function PortalActionRequestResultStrip({ item, className }: PortalActionRequestResultStripProps) {
  const { t } = useLocale();
  const tone = resolveTone(item);
  const summary = formatPortalActionRequestResultSummary(t, item);
  const fallback = formatPortalActionRequestStatusLabel(t, item.status);
  const label =
    tone === 'pending'
      ? t('portal.request_result_pending', {}, '等待平台管理员处理')
      : tone === 'rejected'
        ? t('portal.request_result_rejected', {}, '申请已拒绝')
        : tone === 'success'
          ? t('portal.request_result_done', {}, '处理已完成')
          : t('portal.request_result_neutral', {}, '处理状态');

  return (
    <div
      className={cn(
        'mt-3 rounded-2xl border px-3 py-2 text-sm',
        tone === 'pending' && 'border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200',
        tone === 'success' && 'border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900/60 dark:bg-emerald-950/30 dark:text-emerald-200',
        tone === 'rejected' && 'border-red-200 bg-red-50 text-red-800 dark:border-red-900/60 dark:bg-red-950/30 dark:text-red-200',
        tone === 'neutral' && 'border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-800 dark:bg-slate-950/45 dark:text-slate-200',
        className
      )}
    >
      <span className="font-semibold">{label}</span>
      <span className="ml-2">{summary || fallback}</span>
    </div>
  );
}
