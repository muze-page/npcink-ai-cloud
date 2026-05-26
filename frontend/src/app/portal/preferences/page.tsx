import { Suspense } from 'react';
import { LoadingFallback } from '@/components/ui/LoadingFallback';
import { PortalPreferencesClient } from './PortalPreferencesClient';

export default function PortalPreferencesPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <PortalPreferencesClient />
    </Suspense>
  );
}
