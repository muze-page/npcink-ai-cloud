'use client';

import { useLocale } from '@/contexts/LocaleContext';
import { Skeleton } from '@/components/ui/Skeleton';

export function LoadingFallback() {
  const { t } = useLocale();

  return (
    <div className="flex min-h-72 items-center justify-center px-3 py-6" aria-busy="true" aria-label={t('common.loading')}>
      <div className="w-full max-w-4xl rounded-2xl border border-slate-200/80 bg-white/76 p-4 shadow-sm dark:border-slate-800 dark:bg-slate-950/45">
        <div className="h-1 overflow-hidden rounded-full bg-slate-200/80 dark:bg-slate-800">
          <div className="admin-route-progress h-full w-1/3 rounded-full bg-blue-600 dark:bg-blue-400" />
        </div>
        <div className="mt-5 grid gap-4 md:grid-cols-[1fr_16rem]">
          <div className="space-y-3">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-8 w-full max-w-sm" />
            <Skeleton className="h-4 w-full max-w-2xl" />
            <Skeleton className="h-4 w-full max-w-xl" />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-1">
            <Skeleton className="h-16 w-full rounded-xl" />
            <Skeleton className="h-16 w-full rounded-xl" />
          </div>
        </div>
      </div>
    </div>
  );
}
