'use client';

import { useCallback, useEffect, useState } from 'react';
import { portalClient, type PortalVectorObservabilitySummary } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

export function usePortalSiteKnowledge(siteId: string, t: TranslateFn) {
  const [summary, setSummary] = useState<PortalVectorObservabilitySummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);

  const refresh = useCallback(() => {
    setRefreshNonce((current) => current + 1);
  }, []);

  useEffect(() => {
    if (!siteId) {
      setSummary(null);
      setError('');
      return;
    }

    let isCancelled = false;
    setIsLoading(true);
    setError('');
    void portalClient
      .getVectorObservability(siteId, { windowHours: 168 })
      .then((response) => {
        if (!isCancelled) setSummary(response.data);
      })
      .catch((loadError) => {
        if (isCancelled) return;
        setSummary(null);
        setError(formatPortalErrorMessage(
          loadError,
          t,
          t(
            'portal.vector_obs.load_failed',
            {},
            'Site knowledge status could not be loaded. Try again later.'
          )
        ));
      })
      .finally(() => {
        if (!isCancelled) setIsLoading(false);
      });

    return () => {
      isCancelled = true;
    };
  }, [refreshNonce, siteId, t]);

  return { summary, isLoading, error, refresh };
}
