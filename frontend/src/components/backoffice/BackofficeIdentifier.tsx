'use client';

import { cn } from '@/lib/utils';

function shortenIdentifier(value: string, leading = 12, trailing = 6): string {
  if (value.length <= leading + trailing + 3) {
    return value;
  }

  return `${value.slice(0, leading)}...${value.slice(-trailing)}`;
}

type BackofficeIdentifierProps = {
  value: string;
  className?: string;
  full?: boolean;
};

export function BackofficeIdentifier({
  value,
  className,
  full = false,
}: BackofficeIdentifierProps) {
  return (
    <span
      className={cn(
        'font-mono text-sm text-slate-600 dark:text-slate-400',
        !full && 'truncate',
        className
      )}
      title={value}
    >
      {full ? value : shortenIdentifier(value)}
    </span>
  );
}

