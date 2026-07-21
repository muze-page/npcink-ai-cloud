'use client';

import { cn } from '@/lib/utils';

type PortalIdentifierProps = { value: string; className?: string; full?: boolean };

function shortenIdentifier(value: string, leading = 12, trailing = 6): string {
  return value.length <= leading + trailing + 3 ? value : `${value.slice(0, leading)}...${value.slice(-trailing)}`;
}

export function PortalIdentifier({ value, className, full = false }: PortalIdentifierProps) {
  return <span className={cn('font-mono text-sm text-slate-600 dark:text-slate-400', !full && 'truncate', className)} title={value}>{full ? value : shortenIdentifier(value)}</span>;
}
