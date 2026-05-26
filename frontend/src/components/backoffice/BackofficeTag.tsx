'use client';

import React from 'react';
import { cn } from '@/lib/utils';

export type BackofficeTagTone =
  | 'neutral'
  | 'success'
  | 'info'
  | 'warning'
  | 'danger'
  | 'accent';

export function backofficeTagToneClassName(tone: BackofficeTagTone): string {
  switch (tone) {
    case 'success':
      return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300';
    case 'info':
      return 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300';
    case 'warning':
      return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300';
    case 'danger':
      return 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300';
    case 'accent':
      return 'bg-blue-600 text-white dark:bg-blue-500 dark:text-white';
    default:
      return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300';
  }
}

type BackofficeTagProps = {
  tone?: BackofficeTagTone;
  children: React.ReactNode;
  className?: string;
  dataUi?: string;
};

export function BackofficeTag({
  tone = 'neutral',
  children,
  className,
  dataUi = 'backoffice-tag',
}: BackofficeTagProps) {
  return (
    <span
      data-ui={dataUi}
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-1 text-[0.68rem] font-semibold',
        backofficeTagToneClassName(tone),
        className
      )}
    >
      {children}
    </span>
  );
}
