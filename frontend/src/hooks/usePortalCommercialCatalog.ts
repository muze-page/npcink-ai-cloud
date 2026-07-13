'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  portalClient,
  type Entitlements,
  type PortalCreditPackCatalogPayload,
  type PortalPlanOfferListPayload,
} from '@/lib/portal-client';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

type UsePortalCommercialCatalogOptions = {
  accountId?: string;
  isAuthenticated: boolean;
  t: TranslateFn;
};

export function usePortalCommercialCatalog({
  accountId,
  isAuthenticated,
  t,
}: UsePortalCommercialCatalogOptions) {
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [creditPacks, setCreditPacks] = useState<PortalCreditPackCatalogPayload | null>(null);
  const [planOffers, setPlanOffers] = useState<PortalPlanOfferListPayload | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const bundle = await portalClient.getAccountCommercialBundle();
      setEntitlements(bundle.entitlements);
      setCreditPacks(bundle.creditPacks);
      setPlanOffers(bundle.planOffers || null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : t('error.failed_load', {}, 'Failed to load.'));
      setEntitlements(null);
      setCreditPacks(null);
      setPlanOffers(null);
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (!isAuthenticated || !accountId) {
      setIsLoading(false);
      return;
    }
    void load();
  }, [accountId, isAuthenticated, load]);

  return {
    entitlements,
    creditPacks,
    planOffers,
    isLoading,
    error,
    load,
  };
}
