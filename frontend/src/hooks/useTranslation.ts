'use client';

import { useLocale } from '@/contexts/LocaleContext';

export function useTranslation() {
  return useLocale();
}

export default useTranslation;
