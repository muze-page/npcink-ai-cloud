'use client';

import { useCallback, useEffect, useState } from 'react';
import { portalClient, type PortalMonitoringOverviewSummary } from '@/lib/portal-client';
import { formatPortalErrorMessage } from '@/lib/portal-error';

type TranslateFn = (key: string, params?: Record<string, string>, fallback?: string) => string;

export function usePortalSiteMonitoring(siteId: string, t: TranslateFn) {
  const [overview, setOverview] = useState<PortalMonitoringOverviewSummary | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [refreshNonce, setRefreshNonce] = useState(0);

  const refresh = useCallback(() => {
    setRefreshNonce((current) => current + 1);
  }, []);

  useEffect(() => {
    if (!siteId) {
      setOverview(null);
      setError('');
      return;
    }

    let isCancelled = false;
    setIsLoading(true);
    setError('');
    void portalClient
      .getMonitoringOverview(siteId, { windowHours: 24 })
      .then((response) => {
        if (!isCancelled) setOverview(response.data);
      })
      .catch((loadError) => {
        if (isCancelled) return;
        setOverview(null);
        setError(formatPortalErrorMessage(
          loadError,
          t,
          t('portal.monitoring.load_failed', {}, 'Service status could not be loaded for the current site.')
        ));
      })
      .finally(() => {
        if (!isCancelled) setIsLoading(false);
      });

    return () => {
      isCancelled = true;
    };
  }, [refreshNonce, siteId, t]);

  return { overview, isLoading, error, refresh };
}
