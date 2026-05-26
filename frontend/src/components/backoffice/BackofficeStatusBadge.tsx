'use client';

import { normalizeStatusToken } from '@/lib/status-display';
import { cn } from '@/lib/utils';

function getBackofficeStatusBadgeClassName(status: string): string {
  switch (normalizeStatusToken(status)) {
    case 'active':
    case 'success':
    case 'succeeded':
    case 'within_budget':
    case 'published':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200';
    case 'warning':
    case 'over_budget':
    case 'provisioning':
    case 'pending':
    case 'pending_invite':
    case 'trialing':
    case 'past_due':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200';
    case 'error':
    case 'denied':
    case 'revoked':
    case 'expired':
    case 'canceled':
    case 'failed':
      return 'bg-rose-100 text-rose-800 dark:bg-rose-950/30 dark:text-rose-200';
    case 'inactive':
    case 'unknown':
    case 'read_only':
    case 'disabled':
    case 'draft':
    case 'archived':
    default:
      return 'bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300';
  }
}

type BackofficeStatusBadgeProps = {
  label: string;
  status: string;
  className?: string;
};

export function BackofficeStatusBadge({
  label,
  status,
  className,
}: BackofficeStatusBadgeProps) {
  return (
    <span
      data-ui="backoffice-status-badge"
      className={cn(
        'inline-flex rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.14em]',
        getBackofficeStatusBadgeClassName(status),
        className
      )}
    >
      {label}
    </span>
  );
}
