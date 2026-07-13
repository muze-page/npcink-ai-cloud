'use client';

import { normalizeStatusToken } from '@/lib/status-display';
import { cn } from '@/lib/utils';

type PortalStatusBadgeProps = { label: string; status: string; className?: string };

function portalStatusClassName(status: string): string {
  switch (normalizeStatusToken(status)) {
    case 'active': case 'success': case 'succeeded': case 'within_budget': case 'published':
      return 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200';
    case 'warning': case 'over_budget': case 'provisioning': case 'pending': case 'trialing': case 'past_due':
      return 'bg-amber-100 text-amber-800 dark:bg-amber-950/30 dark:text-amber-200';
    case 'error': case 'denied': case 'revoked': case 'expired': case 'canceled': case 'failed':
      return 'bg-rose-100 text-rose-800 dark:bg-rose-950/30 dark:text-rose-200';
    default:
      return 'bg-slate-100 text-slate-700 dark:bg-slate-900 dark:text-slate-300';
  }
}

export function PortalStatusBadge({ label, status, className }: PortalStatusBadgeProps) {
  return <span data-ui="portal-status-badge" className={cn('inline-flex rounded-full px-2.5 py-1 text-xs font-semibold uppercase tracking-[0.14em]', portalStatusClassName(status), className)}>{label}</span>;
}
