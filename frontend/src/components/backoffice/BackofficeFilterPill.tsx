'use client';

import React from 'react';
import { cn } from '@/lib/utils';
import { type BackofficeTagTone } from '@/components/backoffice/BackofficeTag';

function activeToneClassName(tone: BackofficeTagTone): string {
  switch (tone) {
    case 'success':
      return 'border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-200';
    case 'info':
    case 'accent':
      return 'border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/30 dark:text-blue-200';
    case 'warning':
      return 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200';
    case 'danger':
      return 'border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/30 dark:text-rose-200';
    default:
      return 'border-slate-900 bg-slate-900 text-white dark:border-white dark:bg-white dark:text-slate-950';
  }
}

type BackofficeFilterPillProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  active?: boolean;
  tone?: BackofficeTagTone;
};

export function BackofficeFilterPill({
  active = false,
  tone = 'neutral',
  className,
  type = 'button',
  ...props
}: BackofficeFilterPillProps) {
  return (
    <button
      type={type}
      data-ui="backoffice-filter-pill"
      className={cn(
        'rounded-full border px-3 py-1.5 text-xs font-medium transition',
        active
          ? activeToneClassName(tone)
          : 'border-slate-200/80 bg-white/80 text-slate-700 hover:border-slate-300 hover:text-slate-950 dark:border-slate-700 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:border-slate-600 dark:hover:text-white',
        className
      )}
      {...props}
    />
  );
}
