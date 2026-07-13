'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

type PortalTagTone = 'neutral' | 'success' | 'info' | 'warning' | 'danger' | 'accent';
type PortalTagProps = { tone?: PortalTagTone; children: ReactNode; className?: string; dataUi?: string };

const toneClassNames: Record<PortalTagTone, string> = {
  neutral: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  success: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
  info: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300',
  warning: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  danger: 'bg-rose-100 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300',
  accent: 'bg-blue-600 text-white dark:bg-blue-500 dark:text-white',
};

export function PortalTag({ tone = 'neutral', children, className, dataUi = 'portal-tag' }: PortalTagProps) {
  return <span data-ui={dataUi} className={cn('inline-flex items-center rounded-full px-2.5 py-1 text-[0.68rem] font-semibold', toneClassNames[tone], className)}>{children}</span>;
}
