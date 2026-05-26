'use client';

import { useLocale } from '@/contexts/LocaleContext';

export function LoadingFallback() {
  const { t } = useLocale();

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="text-center">
        <div className="mb-4 animate-spin text-4xl">⏳</div>
        <p className="text-gray-600 dark:text-gray-400">{t('common.loading')}</p>
      </div>
    </div>
  );
}
