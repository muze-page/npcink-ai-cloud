'use client';

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export function AdminHorizontalScroll({
  children,
  label,
  hint,
  className,
}: {
  children: ReactNode;
  label: string;
  hint: string;
  className?: string;
}) {
  return (
    <div className={className}>
      <p className="border-b border-slate-200/70 px-4 py-2 text-xs text-slate-500 dark:border-slate-800 dark:text-slate-400 md:hidden">
        {hint}
      </p>
      <div
        className={cn(
          'overflow-x-auto overscroll-x-contain focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500/50'
        )}
        role="region"
        aria-label={label}
        tabIndex={0}
      >
        {children}
      </div>
    </div>
  );
}
